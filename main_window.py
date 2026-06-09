"""
VoidPulse — MainWindow: top-level QMainWindow, widget tree construction,
signal wiring, config save/restore, playback control, ALSA/PipeWire probing,
cover/theme reload, tag editing orchestration, "Open With" support.
"""
from constants import *

from constants import ACC, ACCH, BG2, BG3, BG4, BORD, CONFIG_PATH, FG, FG2, SUPPORTED_EXT, _lastfm_api_key, _open_audio, _r
from cover_art import (
    Track, read_metadata, get_cover_pixmap, draw_default_cover,
    _ensure_async_cover_loader, _trim_cover_cache,
    _square_pixmap, _COVER_MASTER_SIZE, _cover_disk_key,
    _COVER_JPEG_QUALITY, _cover_disk_write_mtime, _COVER_DISK_DIR,
    _cover_cache, _async_cover_loader, _cover_locked_set,
)
from player import Player, RepeatMode
from mpris import MprisServer
from views import TrackTable, PlaylistPage, Sidebar, COLS, C_TIT
from controlbar import ControlBar, BlackTitleBar, _TB_H
from lyrics import LyricsPanel
from dialogs_edit import TagEditDialog
from fetch_popups import TagFetchPopup, LyricsFetchPopup
from library import ConfigPlaylistLoader, ScanThread, _recover_rename_temps, _sanitize_filename_part
from blackout_overlay import BlackoutOverlay
# SettingsPopup is instantiated lazily inside ControlBar._ensure_settings_popup
from widgets_base import _ModalOverlay, DeviceBusyPopup, _SpinningOverlay

class MainWindow(QMainWindow):
    def __init__(self, splash=None, open_with: str = None):
        super().__init__()
        self._open_with_path = open_with   # file passed via "Open With" / CLI arg
        self._use_system_decorations = False  # overridden by _load_config if set
        # Remove native decoration; draw our own black titlebar (default)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowTitle('VoidPulse'); self.resize(1280, 760)
        self.setMinimumSize(480, 320)

        self._player        = Player()
        self._playlists:    List[PlaylistPage] = []
        self._lib_page:     Optional[PlaylistPage] = None
        self._cur_page:     Optional[PlaylistPage] = None
        self._cur_idx:      int  = -1
        self._shuffle:      bool = False
        self._scan_threads: List[ScanThread] = []
        self._known_paths:  set  = set()
        self._cover_locked_paths: set = set()
        self._cur_track_mw: Track = None
        self._blackout = BlackoutOverlay()
        self._config_loader = None   # ref to ConfigPlaylistLoader while running
        self._splash_ref = splash    # held so _close_splash can always reach it
        self._build_ui()
        self._connect_signals()
        self._load_config()
        # NOTE: do NOT clear _splash_ref here — ConfigPlaylistLoader.all_done
        # fires asynchronously; _close_splash reads _splash_ref at that point.
        # _close_splash calls deleteLater() so the object is GC'd safely.
        self._mpris = MprisServer(self._player, self)
        self._mpris.set_cover_on(self._ctrlbar.cover_on())
        self._player.sig_seek.connect(self._mpris.notify_seeked)
        # Install app-level event filter to detect mouse/key activity for idle timer.
        # Filtering at application level catches events on all child widgets
        # without installing per-widget filters or enabling mouse-tracking everywhere.
        QApplication.instance().installEventFilter(self)

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Custom frameless titlebar
        self._titlebar = BlackTitleBar(self)
        root.addWidget(self._titlebar)

        body = QSplitter(Qt.Orientation.Horizontal); body.setHandleWidth(16)
        body.setObjectName('body_splitter')
        self._sidebar = Sidebar(); body.addWidget(self._sidebar)

        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)

        cbar = QWidget(); cbar.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        self._cbar_widget = cbar
        cbar.setFixedHeight(28)
        cbl = QHBoxLayout(cbar); cbl.setContentsMargins(12,0,12,0)
        self._count_lbl = QLabel('')
        self._count_lbl.setStyleSheet(f'color:{FG2}; font-size:11px; background:transparent;')
        cbl.addStretch(); cbl.addWidget(self._count_lbl)
        rl.addWidget(cbar)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(False)   # Tabs are never shown for playlists
        self._tabs.tabBar().setVisible(False)   # Hide tab bar entirely; nav via sidebar
        rl.addWidget(self._tabs, 1)
        body.addWidget(right)

        # ctrlbar created just before root.addWidget; use late binding
        self._lyrics_panel = LyricsPanel(self._player, ctrlbar=None)
        self._lyrics_panel.setVisible(False)
        body.addWidget(self._lyrics_panel)

        body.setStretchFactor(0, 0); body.setStretchFactor(1, 1); body.setStretchFactor(2, 0)
        body.setSizes([230, 1050, 0])
        # Debounce splitter moves so config is saved after the user stops dragging
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(400)
        self._splitter_save_timer.timeout.connect(self._save_config)
        body.splitterMoved.connect(lambda *_: self._splitter_save_timer.start())

        self._lib_page = PlaylistPage(label='Library')
        self._lib_page.play_track.connect(self._play_from_page)
        self._lib_page.ctx_requested.connect(self._show_ctx_menu)
        self._lib_page.col_widths_changed.connect(
            lambda w, p=self._lib_page: self._on_col_widths_changed(w, p))
        self._tabs.addTab(self._lib_page, '  Library')
        self._cur_page = self._lib_page

        self._ctrlbar = ControlBar(self._player)
        self._lyrics_panel._ctrlbar = self._ctrlbar

        # Vertical splitter: body on top, ctrlbar on bottom.
        # handleWidth(16) + stylesheet border:1px → thin visual line, fat 16px touch target.
        self._vsplit = QSplitter(Qt.Orientation.Vertical)
        self._vsplit.setHandleWidth(16)
        self._vsplit.setChildrenCollapsible(False)
        self._vsplit.addWidget(body)
        self._vsplit.addWidget(self._ctrlbar)
        self._vsplit.setStretchFactor(0, 1)
        self._vsplit.setStretchFactor(1, 0)
        self._vsplit.setSizes([800, 172])
        self._vsplit.splitterMoved.connect(lambda *_: self._splitter_save_timer.start())
        root.addWidget(self._vsplit, 1)
        self._status = self.statusBar()
        # Tab bar hidden; update count when tab changes programmatically
        self._tabs.currentChanged.connect(self._on_tab_change)

        # Device-busy popup — child of central so it floats above all content
        self._device_busy_popup = DeviceBusyPopup(central)

    # Keep custom titlebar in sync with window title changes
    def setWindowTitle(self, title: str):
        super().setWindowTitle(title)
        if hasattr(self, '_titlebar'):
            self._titlebar.set_title(title)

    def _apply_decoration_mode(self, use_system: bool):
        """Switch between custom frameless titlebar and system window decorations.

        Calling this while the window is visible will cause a brief re-show
        (Qt hides the window when setWindowFlags is called); pass use_system
        during _load_config (before showMaximized) to avoid any flicker.
        """
        self._use_system_decorations = use_system
        was_visible  = self.isVisible()
        was_maximized = self.isMaximized()

        if use_system:
            # Let the OS draw its own titlebar / decorations
            self.setWindowFlags(Qt.WindowType.Window)
            self._titlebar.setFixedHeight(0)
            self._titlebar.hide()
        else:
            # Our custom frameless titlebar
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.Window
            )
            self._titlebar.setFixedHeight(_TB_H)
            self._titlebar.show()

        # setWindowFlags() hides the window; restore its previous state
        if was_visible:
            if was_maximized:
                self.showMaximized()
            else:
                self.show()

    def _connect_signals(self):
        self._sidebar.add_folder_req.connect(self._add_folder_dialog)
        self._sidebar.add_m3u_req.connect(self._import_m3u_dialog)
        self._sidebar.new_playlist_req.connect(self._new_playlist_dialog)
        self._sidebar.remove_req.connect(self._remove_playlist)
        self._sidebar.rename_req.connect(self._rename_playlist)
        self._sidebar.move_up_req.connect(lambda i: self._move_playlist(i, i - 1))
        self._sidebar.move_down_req.connect(lambda i: self._move_playlist(i, i + 1))
        self._sidebar.source_selected.connect(self._select_source)
        self._sidebar.search_changed.connect(self._apply_search)
        self._sidebar.refresh_req.connect(self._refresh_library)
        self._sidebar.export_m3u_req.connect(self._export_m3u_dialog)

        self._player.sig_end.connect(self._on_track_end)
        self._player.sig_err.connect(self._on_player_error)
        self._player.sig_busy.connect(self._on_player_busy)
        self._device_busy_popup.switch_to_pipewire.connect(self._on_switch_to_pipewire)
        self._device_busy_popup.retry.connect(self._on_alsa_retry)

        # _on_output_device_changed is a proper MainWindow method connected via
        # _ensure_settings_popup (ControlBar) when the popup is first created.
        # The old guard `if _settings_popup is not None` was always False at init.
        self._ctrlbar.btn_play.clicked.connect(self._play_pause)
        self._ctrlbar.btn_prev.clicked.connect(self._prev_track)
        self._ctrlbar.btn_next.clicked.connect(self._next_track)
        self._ctrlbar.btn_shuf.toggled.connect(self._on_shuffle_toggled)
        self._ctrlbar.btn_rep.mode_changed.connect(self._on_repeat_changed)
        self._ctrlbar.btn_blackout.clicked.connect(self._blackout.show_blackout)
        # Feed track info + position updates to the overlay — only when visible.
        # The overlay is hidden the vast majority of the time; skipping the
        # set_pos() call entirely avoids a Python function dispatch + attribute
        # lookup on every 250 ms position tick while the user is in normal use.
        self._player.sig_pos.connect(
            lambda ms: self._blackout.set_pos(ms, self._ctrlbar._dur_ms)
            if self._blackout.isVisible() else None)
        self._ctrlbar.cover_on_changed.connect(self._on_cover_toggle)
        self._ctrlbar.accent_changed.connect(self._on_accent_refresh)
        self._ctrlbar.btn_lyrics.clicked.connect(self._toggle_lyrics)
        self._player.sig_pos.connect(self._on_pos_for_lyrics)
        self._lyrics_panel.status_msg.connect(
            lambda m: self._status.showMessage(m, 0) if m else self._status.clearMessage())
        self._lyrics_panel.seek_requested.connect(self._player.seek)
        # Immediately refresh seekbar + time label on lyric-click seek so the
        # position is visible even while paused (sig_pos stops ticking when paused).
        self._lyrics_panel.seek_requested.connect(self._ctrlbar._on_pos)
        self._lyrics_panel.lyrics_context.connect(self._blackout.set_lyrics_context)
        self._ctrlbar.set_blackout_ref(self._blackout)

        # View mode + scale — connect settings popup signals after popup is ensured
        pop = self._ctrlbar._ensure_settings_popup()
        pop.view_mode_changed.connect(self._on_view_mode_changed)
        pop.list_scale_changed.connect(self._on_list_scale_changed)
        pop.gallery_scale_changed.connect(self._on_gallery_scale_changed)
        # Auto-save config whenever any setting changes (debounced via QTimer)
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(500)
        self._settings_save_timer.timeout.connect(self._save_config)
        self._ctrlbar.settings_changed.connect(self._settings_save_timer.start)
        # Update ctrlbar cover thumbnail when async loader delivers a cover
        _ensure_async_cover_loader().cover_loaded.connect(self._on_cover_loaded_mw)

    def _on_cover_toggle(self, on: bool):
        self._lib_page.set_covers_on(on)
        for pl in self._playlists:
            pl.set_covers_on(on)
        if hasattr(self, '_mpris'):
            self._mpris.set_cover_on(on)

    def _on_cover_toggle_with_overlay(self, on: bool, _overlay=None):
        """Cover toggle with async processing and optional overlay."""
        # Start the cover processing
        self._lib_page.set_covers_on(on)
        
        playlists_to_process = list(self._playlists)
        
        def _process_playlists(idx: int):
            if idx >= len(playlists_to_process):
                # All done — update MPRIS and close overlay
                if hasattr(self, '_mpris'):
                    self._mpris.set_cover_on(on)
                if _overlay is not None:
                    _overlay.close_overlay()
                return
            
            pl = playlists_to_process[idx]
            pl.set_covers_on(on)
            
            # Continue to next playlist after a brief delay to let UI update
            QTimer.singleShot(16, lambda: _process_playlists(idx + 1))
        
        # Start processing playlists after a short delay
        QTimer.singleShot(16, lambda: _process_playlists(0))

    def _on_cover_loaded_mw(self, fp: str, size: int):
        """Update ctrlbar thumbnail when async cover loader finishes for the playing track."""
        ctrlbar = self._ctrlbar
        if not ctrlbar._cover_lbl.isVisible():
            return
        cur = ctrlbar._cur_track
        if not (cur and cur.filepath == fp):
            return

        if size == 220:
            # 220px master just landed — if cover-accent is on, invalidate the
            # cached accent pixmap so next paint rebuilds from the real cover.
            if ctrlbar._cover_acc_on:
                ctrlbar._cover_lbl._acc_pm = None
                ctrlbar._cover_lbl.update()
            return

        if size == 64:
            pm = _cover_cache.get((fp, 64))
            if pm:
                ctrlbar._cover_lbl.setPixmap(pm, fp)
            # 64px derived after master — master already cached; rebuild accent.
            if ctrlbar._cover_acc_on:
                ctrlbar._cover_lbl._acc_pm = None
                ctrlbar._cover_lbl.update()

    def _on_view_mode_changed(self, mode: str):
        self._lib_page.set_view_mode(mode)
        for pl in self._playlists:
            pl.set_view_mode(mode)
        self._splitter_save_timer.start()

    def _on_list_scale_changed(self, row_h: int):
        self._lib_page.set_list_scale(row_h)
        for pl in self._playlists:
            pl.set_list_scale(row_h)
        self._splitter_save_timer.start()

    def _on_gallery_scale_changed(self, card_h: int):
        self._lib_page.set_gallery_scale(card_h)
        for pl in self._playlists:
            pl.set_gallery_scale(card_h)
        self._splitter_save_timer.start()

    def _on_tags_fetched(self, fp: str, tags: dict):
        """Called by TagFetchPopup when tags for a track have been written to disk.
        Refreshes the Track object in every page that contains this filepath."""
        if not tags: return
        for page in [self._lib_page] + self._playlists:
            if page is None: continue
            # O(1) lookup via TrackTable reverse index instead of O(n) enumerate scan
            i = page.table._fp_to_row.get(fp, -1)
            if i < 0 or i >= len(page.tracks):
                continue
            t = page.tracks[i]
            if t.filepath != fp:
                continue   # stale index after a re-sort; tolerate silently
            if tags.get('title'):  t.title  = tags['title']
            if tags.get('artist'): t.artist = tags['artist']
            if tags.get('album'):  t.album  = tags['album']
            page.table._fill_row(i, t)
            if (self._cur_page is page and self._cur_idx == i):
                self._ctrlbar.set_track(t)
                self.setWindowTitle(f'{t.title}  —  VoidPulse')

    def _refresh_all_theme_widgets(self, _overlay: '_SpinningOverlay' = None):
        """Re-apply inline stylesheets asynchronously — each chunk yields to the event loop.

        The overlay must already be created and shown before calling this method;
        this method closes it when done.
        """
        # Step 1: critical fast widgets — synchronous, immediately visible
        for lbl in (self._ctrlbar._lbl_title, self._ctrlbar._lbl_artist):
            lbl.setStyleSheet('background:transparent;')
        self._cbar_widget.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        self._count_lbl.setStyleSheet(f'color:{FG2}; font-size:11px; background:transparent;')
        self._ctrlbar._seek.update_accent(ACC, ACCH)
        self._ctrlbar._on_brightness_change(self._ctrlbar._brightness_v)
        _play_ss = (
            f'QPushButton#play {{ background:{BG3}; color:{ACC};'
            f' border:2px solid {ACC}; border-radius:{_r(26)}px;'
            f' min-width:52px; max-width:52px; min-height:52px; max-height:52px;'
            f' font-size:22px; padding:0 0 2px 5px; text-align:center; }}'
            f'QPushButton#play:hover {{ border-color:{ACCH}; color:{ACCH}; background:{BG4}; }}'
            f'QPushButton#play:pressed {{ background:{BG4}; }}')
        self._ctrlbar.btn_play.setStyleSheet(_play_ss)
        _ts = (f'QPushButton#ctrl {{ background:transparent; border:none; color:{FG2};'
               f' font-size:20px; border-radius:{_r(22)}px; padding:0; text-align:center; }}'
               f'QPushButton#ctrl:hover {{ color:{FG}; background:{BG3}; }}'
               f'QPushButton#ctrl:checked {{ color:{ACC}; background:transparent; }}'
               f'QPushButton#ctrl:pressed {{ background:{BG4}; }}')
        for b in (self._ctrlbar.btn_shuf, self._ctrlbar.btn_prev, self._ctrlbar.btn_next):
            b.setStyleSheet(_ts)
        self._ctrlbar.refresh_theme()
        if hasattr(self, '_titlebar'):
            self._titlebar.refresh_theme()
        QApplication.processEvents()

        # Step 2: lyrics + popups — deferred
        def _step2():
            self._lyrics_panel.set_accent(ACC)
            self._lyrics_panel.refresh_theme()
            pop = self._ctrlbar._settings_popup
            if pop is not None:
                pop.refresh_theme()
                pop.repaint()
            eq_pop = self._ctrlbar._eq_popup
            if eq_pop is not None:
                eq_pop.repaint()
            self._sidebar.refresh_theme()
            QTimer.singleShot(0, _step3)

        # Step 3: all playlist pages — one per event loop slot
        def _step3():
            pages = [p for p in [self._lib_page] + self._playlists if p]
            def _do_page(i):
                if i >= len(pages):
                    # Done — close overlay
                    if _overlay is not None:
                        _overlay.close_overlay()
                    return
                pg = pages[i]
                pg.refresh_theme()
                if pg.playing_idx >= 0:
                    pg.table.set_playing_row(pg.playing_idx)
                    pg.gallery.set_playing(pg.playing_idx)
                QTimer.singleShot(0, lambda _i=i+1: _do_page(_i))
            _do_page(0)

        QTimer.singleShot(0, _step2)

    def _on_accent_refresh(self, color: str):
        """Accent colour changed — show overlay and start async theme refresh."""
        overlay = _SpinningOverlay(self)
        overlay.show(); overlay.raise_()
        # Defer work until after the overlay's first paint.
        QTimer.singleShot(32, lambda: self._refresh_all_theme_widgets(_overlay=overlay))

    def _refresh_theme_no_overlay(self):
        """Refresh without overlay (for internal calls such as config restore)."""
        self._refresh_all_theme_widgets(_overlay=None)

    def _on_pos_for_lyrics(self, ms: int):
        # Lyrics use raw playback position — viz audio-delay compensation must not
        # be applied here (that offset only corrects spectrum-display latency).
        # Skip when the panel is hidden: no visible output, no need to run bisect
        # + QPropertyAnimation setup on every 250 ms tick.
        # Also skip when the window is unfocused: _highlight triggers
        # lyrics_context.emit → BlackoutOverlay.set_lyrics_context → update(),
        # which is wasted work when neither the panel nor the overlay is visible.
        if not self._lyrics_panel.isVisible():
            return
        if not getattr(self, '_was_active', True) and not self._blackout.isVisible():
            return
        self._lyrics_panel.on_position(ms)

    def _open_lyrics_panel_from_config(self):
        """Restore lyrics panel open state from config."""
        if not self._lyrics_panel.isVisible():
            self._toggle_lyrics()

    def _toggle_lyrics(self, _checked=False):
        panel = self._lyrics_panel
        body  = self.findChild(QSplitter, 'body_splitter')
        if not body: return
        vis = panel.isVisible()
        panel.setVisible(not vis)
        self._ctrlbar.btn_lyrics.setChecked(not vis)
        sizes = body.sizes()
        if not vis:   # opening
            total = sum(sizes)
            body.setSizes([sizes[0], max(100, total - sizes[0] - 290), 290])
            if self._cur_track_mw:
                deferred = not self.isActiveWindow() or self._blackout.isVisible()
                panel.set_track(self._cur_track_mw, deferred=deferred)
        else:         # closing
            body.setSizes([sizes[0], sizes[1] + sizes[2], 0])

    def _show_ctx_menu(self, src_page, row, pos):
        if not (0 <= row < len(src_page.tracks)): return
        track = src_page.tracks[row]; m = QMenu(self)
        m.addAction('▶  Play').triggered.connect(lambda: self._play_from_page(src_page, row))
        m.addSeparator()
        add_sub = m.addMenu("Add to Playlist")
        for pl in self._playlists:
            if pl is not src_page:
                def _add(_, _pl=pl, _tr=track):
                    fps = {t.filepath for t in _pl.tracks}
                    if _tr.filepath not in fps:
                        tracks = list(_pl.tracks)
                        # Insert at sorted position instead of full re-sort
                        sk = _tr.sort_key()
                        idx = bisect.bisect_left([t.sort_key() for t in tracks], sk)
                        tracks.insert(idx, _tr)
                        _pl.set_tracks(tracks, _pl.playing_idx); self._save_config()
                add_sub.addAction(pl.label).triggered.connect(_add)
        if src_page is not self._lib_page:
            m.addSeparator()
            def _rem(_, _p=src_page, _r=row):
                tracks = list(_p.tracks); tracks.pop(_r)
                _p.set_tracks(tracks, -1); self._rebuild_library(); self._save_config()
            m.addAction("Remove from Playlist").triggered.connect(_rem)
        m.addSeparator()
        m.addAction("✎  Edit Tags...").triggered.connect(
            lambda: self._edit_tags(src_page, row))
        m.exec(pos)

    def _invalidate_cover_cache(self, fp: str, pre_embed_mtime: float = None):  # noqa: pre_embed_mtime kept for API compat
        """Remove all cached cover data for fp so the next paint reloads from disk.

        pre_embed_mtime is kept as a parameter for API compatibility but is no
        longer used: the filename-based disk key does not encode mtime, so we
        simply delete the disk files and update the sidecar .mtime files to force
        a re-extract on next access.
        """
        # Clear ALL cached sizes for this fp (includes gallery's dynamic cover_sz)
        for key in [k for k in _cover_cache if k[0] == fp]:
            _cover_cache.pop(key, None)
        # Delete disk cover files for known fixed sizes; gallery sizes are evicted
        # lazily (staleness detected via sidecar on next access).
        stem = _sanitize_filename_part(Path(fp).stem)
        if len(stem) > 120: stem = stem[:120]
        if _COVER_DISK_DIR.exists():
            for cover_file in list(_COVER_DISK_DIR.glob(f'{stem}_*.jpg')):
                try:
                    cover_file.unlink()
                    sidecar = Path(str(cover_file) + '.mtime')
                    if sidecar.exists():
                        sidecar.unlink()
                except Exception:
                    pass
        # Async loader's no-embed blacklist — remove so it retries on next paint
        loader = _async_cover_loader
        if loader is not None:
            with loader._lock:
                loader._no_embed.discard(fp)
                for size in (28, 64):
                    loader._in_flight.discard((fp, size))

    def _edit_tags(self, page, row):
        track = page.tracks[row]
        # ── Pre-flight checks before opening the dialog ───────────────────────
        ext = Path(track.filepath).suffix.lower()
        try:
            with open(track.filepath, 'rb') as _f:
                _magic = _f.read(4)
        except OSError as _oe:
            QMessageBox.warning(self, 'Cannot Edit Tags',
                f'Cannot read file:\n{Path(track.filepath).name}\n\n{_oe}')
            return
        # WebM/MKV container (EBML magic bytes 1A 45 DF A3) — mutagen cannot write tags
        if _magic == b'\x1a\x45\xdf\xa3':
            msg = QMessageBox(self)
            msg.setWindowTitle('Cannot Edit Tags')
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(
                f'<b>{Path(track.filepath).name}</b> is stored in a '
                f'<b>WebM/MKV container</b>.<br><br>'
                f'Tag editing requires an Ogg container. '
                f'Re-mux with ffmpeg (no quality loss):<br><br>'
                f'<code>ffmpeg -i input.opus -c copy output.ogg</code>')
            msg.setTextFormat(Qt.TextFormat.RichText)
            msg.exec()
            return
        # Fragmented/DASH MP4 — mutagen can read but save() often fails
        if ext in ('.m4a', '.aac') and _magic[:8] in (
                b'\x00\x00\x00\x18ftypdash', b'\x00\x00\x00\x18ftypiso'):
            # Try anyway; error will be caught below with a clear message
            pass

        dlg = TagEditDialog(track, parent=self)
        dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        _ModalOverlay.show_for(dlg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_title, new_artist, new_album = dlg.get_tags()
        cover_action, cover_bytes = dlg.get_cover_result()
        # Write tags to file using mutagen
        try:
            af = _open_audio(track.filepath)
            if af is None:
                self._status.showMessage(
                    f'Could not open {Path(track.filepath).name} for tag writing', 3000)
                return
            if af.tags is None:
                af.add_tags()

            if ext == '.mp3':
                from mutagen.id3 import TIT2, TPE1, TALB
                # Only write non-empty values; empty = leave tag unchanged
                if new_title:  af.tags['TIT2'] = TIT2(encoding=3, text=new_title)
                if new_artist: af.tags['TPE1'] = TPE1(encoding=3, text=new_artist)
                if new_album:  af.tags['TALB'] = TALB(encoding=3, text=new_album)

            elif ext in ('.flac', '.ogg', '.opus'):
                # Vorbis comments: normalise to lowercase keys
                # First remove any uppercase duplicates so we don't double-write
                for k_old in ('TITLE', 'ARTIST', 'ALBUM'):
                    try:
                        if k_old in af.tags: del af.tags[k_old]
                    except Exception:
                        pass
                if new_title:  af.tags['title']  = [new_title]
                if new_artist: af.tags['artist'] = [new_artist]
                if new_album:  af.tags['album']  = [new_album]

            elif ext in ('.m4a', '.aac'):
                if new_title:  af.tags['\xa9nam'] = [new_title]
                if new_artist: af.tags['\xa9ART'] = [new_artist]
                if new_album:  af.tags['\xa9alb'] = [new_album]
            else:
                self._status.showMessage(f'Unsupported format: {ext}', 3000)
                return

            try:
                af.save()
            except Exception as _save_err:
                _save_msg = str(_save_err)
                if ext in ('.m4a', '.aac') and 'ftypdash' in _save_msg.lower():
                    _hint = ' (Fragmented/DASH MP4 — convert: ffmpeg -i in.m4a -c copy out.m4a)'
                else:
                    _hint = ''
                self._status.showMessage(
                    f'Tag could not be written: {Path(track.filepath).name} — {_save_msg}{_hint}', 8000)
                print(f'af.save() error [{ext}]: {_save_err}')
                return

            # Handle cover changes
            fp = track.filepath
            if cover_action == 'set' and cover_bytes:
                try:
                    _pre_embed_mtime = os.path.getmtime(fp)
                except Exception:
                    _pre_embed_mtime = None
                embed_cover_bytes(fp, cover_bytes)
                self._invalidate_cover_cache(fp, pre_embed_mtime=_pre_embed_mtime)
                # Build pixmaps synchronously NOW — before any _fill_row / populate call.
                # Write only the 220px master to disk; derive display sizes from it.
                src_raw = QPixmap()
                if src_raw.loadFromData(cover_bytes):
                    master_pm = _square_pixmap(src_raw, _COVER_MASTER_SIZE)
                    _cover_cache[(fp, _COVER_MASTER_SIZE)] = master_pm
                    try:
                        master_dkey = _cover_disk_key(fp)
                        master_disk_path = _COVER_DISK_DIR / f'{master_dkey}.jpg'
                        _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
                        master_pm.save(str(master_disk_path), 'JPEG', _COVER_JPEG_QUALITY)
                        _cover_disk_write_mtime(fp, master_disk_path)
                    except Exception:
                        pass
                    for size in (28, 64):
                        _cover_cache[(fp, size)] = _square_pixmap(master_pm, size)
                    _trim_cover_cache()
            elif cover_action == 'remove':
                try:
                    af2 = _open_audio(fp)
                    ext2 = Path(fp).suffix.lower()
                    if af2 and af2.tags:
                        if ext2 == '.mp3':               af2.tags.delall('APIC')
                        elif ext2 == '.flac':            af2.clear_pictures()
                        elif ext2 in ('.m4a', '.aac'):   af2.tags.pop('covr', None)
                        elif ext2 in ('.ogg', '.opus'):
                            af2.tags.pop('metadata_block_picture', None)
                        af2.save()
                except Exception:
                    pass
                # Invalidate and pre-populate with default so _fill_row sees it immediately
                self._invalidate_cover_cache(fp)
                for size in (28, 64):
                    _cover_cache[(fp, size)] = draw_default_cover(size)

            # Re-read metadata to reflect changes in UI
            updated_track = read_metadata(fp)

            def _update_page(pg, idx):
                pg.tracks[idx] = updated_track
                pg.table._fill_row(idx, updated_track)
                pm28 = _cover_cache.get((fp, 28))
                if pm28:
                    item = pg.table.item(idx, C_TIT)
                    if item:
                        item.setIcon(QIcon(pm28))
                # Gallery: repopulate and force repaint so async cover_loaded
                # is re-requested for the gallery's dynamic cover_sz key.
                pg.gallery.populate(pg.tracks, pg.playing_idx)
                # Invalidate the fp→position cache so _on_cover_loaded re-maps
                pg.gallery._fp_to_vis_positions = None
                # Force a full canvas repaint — triggers get_cover_pixmap for
                # the gallery's cover_sz, scheduling a new async load if needed.
                pg.gallery._canvas.update()

            _update_page(page, row)
            # Also update library page and any other playlist containing this track
            for pg in [self._lib_page] + self._playlists:
                if pg is page:
                    continue
                i = pg.table._fp_to_row.get(updated_track.filepath, -1)
                if i >= 0 and i < len(pg.tracks) and pg.tracks[i].filepath == updated_track.filepath:
                    _update_page(pg, i)
            # Update ctrlbar thumbnail only when the edited track is currently playing
            if (cover_action in ('set', 'remove')
                    and self._cur_track_mw is not None
                    and self._cur_track_mw.filepath == fp
                    and self._ctrlbar._cover_lbl.isVisible()):
                pm64 = _cover_cache.get((fp, 64))
                if pm64:
                    self._ctrlbar._cover_lbl.setPixmap(pm64)
            if self._cur_page is page and self._cur_idx == row:
                self._ctrlbar.set_track(updated_track)
                self.setWindowTitle(f'{updated_track.title}  —  VoidPulse')
                self._mpris.notify_track(updated_track)
                # Reload lyrics panel so edits to embedded lyrics are reflected immediately
                if self._lyrics_panel.isVisible():
                    self._lyrics_panel.set_track(updated_track)

            self._status.showMessage('Tags updated', 3000)
            self._save_config()
        except Exception as e:
            self._status.showMessage(f'Error saving tags: {e}', 5000)
            print(f'_edit_tags error: {e}')

    def _new_playlist_dialog(self):
        """Ask for name, create an empty M3U8 in the first known folder, load it."""
        name, ok = QInputDialog.getText(self, 'New Playlist', 'Playlist name:')
        if not ok or not name.strip():
            return
        name = name.strip()
        # Find a writable folder — prefer first known non-m3u folder
        save_dir = None
        for p in self._known_paths:
            if not p.endswith(('.m3u', '.m3u8')) and os.path.isdir(p):
                save_dir = p; break
        if save_dir is None:
            # No known folder: ask user
            save_dir = QFileDialog.getExistingDirectory(self, 'Select Playlist Folder')
            if not save_dir:
                return
        # Build safe filename
        safe = ''.join(c for c in name if c.isalnum() or c in ' _-').strip() or 'playlist'
        m3u_path = str(Path(save_dir) / f'{safe}.m3u8')
        # Write empty M3U8
        try:
            with open(m3u_path, 'w', encoding='utf-8') as f:
                f.write('#EXTM3U\n')
        except Exception as e:
            self._status.showMessage(f'Could not create M3U8: {e}', 4000); return
        # Create empty PlaylistPage directly (no scan needed — file is empty)
        page = PlaylistPage([], label=name)
        page.play_track.connect(self._play_from_page)
        page.ctx_requested.connect(self._show_ctx_menu)
        # Apply current view settings to the new playlist page
        pop = self._ctrlbar._ensure_settings_popup()
        page.set_view_mode(pop.view_mode())
        page.set_list_scale(pop.list_scale())
        page.set_gallery_scale(pop.gallery_scale())
        page.set_covers_on(pop.cover_on())

        self._playlists.append(page)
        ti = self._tabs.addTab(page, f' {name} ')
        self._sidebar.add_playlist(name)
        self._tabs.setCurrentIndex(ti)
        # Remember the m3u8 path so "Refresh" can re-scan it
        self._known_paths.add(m3u_path)
        # Store m3u path on page for later save
        page._m3u_path = m3u_path
        self._status.showMessage(f'"{name}" playlist created — {m3u_path}', 5000)
        self._save_config()

    def _add_folder_dialog(self):
        f = QFileDialog.getExistingDirectory(self, 'Select Music Folder', str(Path.home()))
        if f:
            self._known_paths.add(f); self._scan_path(f, False)

    def _import_m3u_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, 'Import Playlist', str(Path.home()),
            'Playlist (*.m3u *.m3u8);;All Files (*)')
        if f:
            self._known_paths.add(f); self._scan_path(f, True)

    def _export_m3u_dialog(self):
        """Export the currently visible playlist to an M3U8 file."""
        page = self._tabs.currentWidget()
        if not isinstance(page, PlaylistPage) or not page.tracks:
            self._status.showMessage('Nothing to export — open a playlist first.', 3000)
            return
        label = page.label or 'playlist'
        safe  = ''.join(c for c in label if c.isalnum() or c in ' _-').strip() or 'playlist'
        default_path = str(Path.home() / f'{safe}.m3u8')
        dest, _ = QFileDialog.getSaveFileName(
            self, 'Export Playlist as M3U8', default_path,
            'M3U Playlist (*.m3u8 *.m3u);;All Files (*)')
        if not dest:
            return
        try:
            lines = ['#EXTM3U\n']
            for t in page.tracks:
                lines.append(f'#EXTINF:{int(t.duration)},{t.artist} - {t.title}\n')
                lines.append(t.filepath + '\n')
            with open(dest, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            self._status.showMessage(
                f'Exported {len(page.tracks)} tracks → {dest}', 5000)
        except Exception as e:
            self._status.showMessage(f'Export failed: {e}', 5000)
            print(f'_export_m3u_dialog error: {e}')

    def _refresh_library(self):
        if not self._known_paths:
            self._status.showMessage('No folders added.', 3000); return
        self._status.showMessage('Refreshing library…')
        # Clear memory cache — disk cache keys include mtime so they go stale automatically
        _cover_cache.clear()
        for path in list(self._known_paths):
            if not path.endswith(('.m3u', '.m3u8')):
                self._scan_path(path, False, refresh=True)

    def _scan_path(self, path, is_m3u, refresh=False):
        self._status.showMessage('Scanning…')
        t = ScanThread(path, is_m3u)
        t.done.connect(lambda tracks, label, r=refresh, p=path:
                       self._on_scan_done(tracks, label, r, p))
        t.progress.connect(lambda m: self._status.showMessage(m))
        self._scan_threads.append(t); t.start()

    def _on_scan_done(self, tracks, label, refresh=False, path=''):
        if not tracks:
            self._status.showMessage('No supported audio files found.', 3000); return

        if refresh:
            for pl in self._playlists:
                if pl.label == label:
                    pl.set_tracks(tracks); self._rebuild_library()
                    self._status.showMessage(f'"{label}" refreshed — {len(tracks)} tracks', 4000)
                    self._save_config(); return

        page = PlaylistPage(tracks, label=label)
        page.play_track.connect(self._play_from_page)
        page.ctx_requested.connect(self._show_ctx_menu)
        page.col_widths_changed.connect(lambda w, p=page: self._on_col_widths_changed(w, p))
        page.set_tracks(tracks)
        # Restore saved column ratios to new page
        saved_ratios = getattr(self, '_last_col_widths', None) or TrackTable._DEFAULT_COL_RATIOS
        page.table.restore_col_widths(saved_ratios)
        # Apply current cover preference
        pop = self._ctrlbar._ensure_settings_popup()
        page.set_covers_on(pop.cover_on())
        # Apply current view mode + scale
        page.set_view_mode(pop.view_mode())
        page.set_list_scale(pop.list_scale())
        page.set_gallery_scale(pop.gallery_scale())
        self._playlists.append(page)
        ti = self._tabs.addTab(page, f' {label} ')
        self._sidebar.add_playlist(label)
        self._tabs.setCurrentIndex(ti)
        self._rebuild_library()
        self._status.showMessage(f'"{label}" — {len(tracks)} tracks loaded', 4000)
        self._save_config()

    def _rebuild_library(self):
        # ── one-time rename-tmp recovery (runs only on the first rebuild) ──────
        if not getattr(self, '_rename_recovery_done', False):
            self._rename_recovery_done = True
            all_tracks_for_recovery = []
            for pl in self._playlists:
                all_tracks_for_recovery.extend(pl.tracks)
            recovered = _recover_rename_temps(all_tracks_for_recovery)
            if recovered:
                # Update filepath on every Track object in every playlist so
                # the restored name is reflected immediately in the UI and on
                # the next _save_config() call.
                for pl in self._playlists:
                    for t in pl.tracks:
                        if t.filepath in recovered:
                            t.filepath = recovered[t.filepath]
                # Persist the corrected paths right away.
                QTimer.singleShot(0, self._save_config)
        # ── normal rebuild ───────────────────────────────────────────────────
        all_tracks = []
        for pl in self._playlists: all_tracks.extend(pl.tracks)
        seen = set(); dedup = []
        for t in all_tracks:
            if t.filepath not in seen: seen.add(t.filepath); dedup.append(t)
        dedup.sort(key=lambda t: t.sort_key())
        fp_to_idx = {t.filepath: i for i, t in enumerate(dedup)}
        # Resolve the playing row by the player's current filepath.
        # Using _cur_idx (cursor/selection) was wrong: it is unrelated to
        # which track is actually playing and goes stale after a rescan
        # replaces all Track objects (e.g. after a batch rename).
        pidx = -1
        player_fp = getattr(getattr(self, '_player', None), '_last_filepath', '')
        if player_fp:
            pidx = fp_to_idx.get(player_fp, -1)
        # Fall back to the existing lib-page playing_idx when nothing has
        # been played yet in this session (player_fp is empty).
        if pidx == -1 and 0 <= self._lib_page.playing_idx < len(self._lib_page.tracks):
            old_fp = self._lib_page.tracks[self._lib_page.playing_idx].filepath
            pidx = fp_to_idx.get(old_fp, -1)
        self._lib_page.set_tracks(dedup, pidx)
        # Re-apply saved col widths after populate resets them
        saved = getattr(self, '_last_col_widths', None)
        if saved:
            self._lib_page.table.restore_col_widths(saved)
        self._update_count()

    def _remove_playlist(self, idx):
        if not (0 <= idx < len(self._playlists)): return
        page = self._playlists.pop(idx)
        # Remove tab first (fast)
        for i in range(self._tabs.count()):
            if self._tabs.widget(i) is page:
                self._tabs.removeTab(i)
                break
        self._sidebar.remove_playlist(idx)
        # Defer library rebuild so the UI unblocks immediately
        QTimer.singleShot(0, lambda: (self._rebuild_library(), self._save_config()))

    def _rename_playlist(self, idx: int, new_label: str):
        if not (0 <= idx < len(self._playlists)): return
        page = self._playlists[idx]
        page.set_label(new_label)
        # Update the tab title
        tab_idx = idx + 1   # tab 0 is the library page
        if 0 < tab_idx < self._tabs.count():
            self._tabs.setTabText(tab_idx, f' {new_label} ')
        # Sidebar label is already updated by Sidebar._prompt_rename before emit
        self._save_config()

    def _move_playlist(self, from_idx: int, to_idx: int):
        n = len(self._playlists)
        if not (0 <= from_idx < n and 0 <= to_idx < n): return
        # Swap in the data list
        self._playlists[from_idx], self._playlists[to_idx] = (
            self._playlists[to_idx], self._playlists[from_idx])
        # Swap tab widgets (tabs: 0=library, 1..n=playlists)
        t_from = from_idx + 1
        t_to   = to_idx   + 1
        # QTabWidget has no direct swap — remove the higher-index one first to
        # avoid index shifting, then reinsert at the correct position.
        hi = max(t_from, t_to); lo = min(t_from, t_to)
        hi_widget = self._tabs.widget(hi)
        hi_label  = self._tabs.tabText(hi)
        lo_widget = self._tabs.widget(lo)
        lo_label  = self._tabs.tabText(lo)
        self._tabs.removeTab(hi)
        self._tabs.removeTab(lo)
        self._tabs.insertTab(lo, hi_widget, hi_label)
        self._tabs.insertTab(hi, lo_widget, lo_label)
        # Sidebar reorder
        self._sidebar.move_playlist_row(from_idx, to_idx)
        self._save_config()

    def _select_source(self, idx):
        if idx == -1: self._tabs.setCurrentIndex(0)
        else:
            ti = idx+1
            if ti < self._tabs.count(): self._tabs.setCurrentIndex(ti)

    # --- Playback ---
    def _play_from_page(self, page, row):
        self._cur_page = page; self._cur_idx = row; self._alsa_play()

    def _alsa_play(self) -> None:
        """High-level play entry point for normal play/pause/track-change.

        If the current output is PipeWire, plays directly via _start_playback().
        If the current output is ALSA, runs the hw:/plughw: probe on first use
        or after an error; subsequent plays use the confirmed device directly.
        """
        # If the user has selected PipeWire, never touch _alsa_device.
        if not self._player._is_hw_device(self._player._alsa_device):
            self._start_playback()
            return
        needs_probe = getattr(self, '_alsa_probe_needed', False)
        if not needs_probe and getattr(self, '_alsa_probe_error', ''):
            needs_probe = True
            self._alsa_probe_needed = True
        if needs_probe and self._cur_track_mw is not None:
            self._alsa_probe_needed = False
            self._alsa_probe_and_play()
            return
        confirmed = getattr(self, '_alsa_confirmed_device', None)
        if Player._is_hw_device(confirmed):
            self._player._alsa_device = confirmed
        self._start_playback()

    def _start_playback(self):
        if not self._cur_page: return
        tracks = self._cur_page.tracks
        if not tracks or not (0 <= self._cur_idx < len(tracks)): return
        t = tracks[self._cur_idx]
        self._player.load(t.filepath)
        self._ctrlbar.set_track(t); self._ctrlbar.set_play_icon(True)
        self._cur_track_mw = t
        # Clear overlay lyrics immediately — new track starts fresh
        self._blackout.set_lyrics_context('', '', '')
        if self._lyrics_panel.isVisible():
            deferred = not self.isActiveWindow() or self._blackout.isVisible()
            self._lyrics_panel.set_track(t, deferred=deferred)
        self._cur_page.set_playing(self._cur_idx)
        self.setWindowTitle(f'{t.title}  —  VoidPulse')
        self._status.showMessage(f'▶  {t.artist}  —  {t.title}', 0)
        self._mpris.notify_track(t); self._mpris.notify_status()
        self._blackout.set_track(t.title or Path(t.filepath).name, t.artist, t.album)

    def _navigate_track(self, play: bool):
        """Change track without altering play/pause state.

        If play=True  → loads and plays (same as _start_playback).
        If play=False → loads, then immediately pauses so the user sees
                        the new track info but audio does not start.
        """
        if not self._cur_page: return
        tracks = self._cur_page.tracks
        if not tracks or not (0 <= self._cur_idx < len(tracks)): return
        t = tracks[self._cur_idx]
        self._player.load(t.filepath)
        if not play:
            self._player.play_pause()   # load() always starts; pause immediately
        self._ctrlbar.set_track(t); self._ctrlbar.set_play_icon(play)
        self._cur_track_mw = t
        self._blackout.set_lyrics_context('', '', '')
        if self._lyrics_panel.isVisible():
            deferred = not self.isActiveWindow() or self._blackout.isVisible()
            self._lyrics_panel.set_track(t, deferred=deferred)
        self._cur_page.set_playing(self._cur_idx)
        self.setWindowTitle(f'{t.title}  —  VoidPulse')
        self._status.showMessage(f'▶  {t.artist}  —  {t.title}', 0)
        self._mpris.notify_track(t); self._mpris.notify_status()
        self._blackout.set_track(t.title or Path(t.filepath).name, t.artist, t.album)

    def _on_output_device_changed(self, dev_id: str) -> None:
        """Called when the user picks a new output device in SettingsPopup.

        set_output_device (connected first in ControlBar) has already destroyed
        the pipeline and saved position/_last_switch_was_playing by the time this
        fires.  For ALSA devices we run the hw:/plughw: probe to confirm the card
        works; for PipeWire the reload is handled entirely by set_output_device.
        """
        if not Player._is_hw_device(dev_id):
            return
        # Derive hw:X,Y from the selected plughw:X,Y for the probe's first attempt.
        self._alsa_confirmed_device = dev_id.replace('plughw:', 'hw:', 1)
        self._alsa_selected_plughw  = dev_id
        if self._cur_track_mw is not None:
            QTimer.singleShot(0, self._alsa_probe_and_play)
        else:
            self._alsa_probe_needed = True

    def _on_switch_to_pipewire(self) -> None:
        """Called when the user clicks 'Switch to PipeWire' in DeviceBusyPopup.
        Updates the player, syncs the SettingsPopup combobox, and saves config."""
        prev = self._player._alsa_device
        print(f'[AudioSwitch] user switched output: {prev!r} -> pipewire  (via DeviceBusyPopup)')
        self._player.set_output_device('pipewire')
        pop = self._ctrlbar._settings_popup
        if pop is not None:
            pop.set_output_device('pipewire')
            self._ctrlbar._refresh_audio_info()
        self._save_config()

    def _on_alsa_retry(self) -> None:
        """Called when the user clicks 'Retry' in DeviceBusyPopup."""
        print('[AudioSwitch] user clicked Retry — probing ALSA devices')
        if self._cur_track_mw is not None:
            self._alsa_probe_and_play()

    def _alsa_probe_and_play(self) -> None:
        """Probe hw:X,Y then plughw:X,Y to find a working ALSA device, then play.

        Called ONLY on:
          • initial launch (when an ALSA device is saved in config)
          • combobox device change
          • Retry button in DeviceBusyPopup

        Normal play/pause/track-change use _start_playback() directly with
        whatever device was confirmed by the last probe (_alsa_confirmed_device).

        Probe schedule: hw:, plughw:, hw:(+2s), plughw:(+2s), hw:(+4s), give up.
        Retrying the same device with increasing back-off gives PipeWire time to
        release its exclusive hold on the hw: node during async teardown.
        Seeking to the original position happens once in _confirm after success,
        not per-attempt, so position survives across retries.
        """
        PRIMARY  = self._player._alsa_device.replace('plughw:', 'hw:', 1) \
                   if self._player._is_hw_device(self._player._alsa_device) \
                   else getattr(self, '_alsa_selected_plughw', 'plughw:1,0').replace('plughw:', 'hw:', 1)
        FALLBACK = getattr(self, '_alsa_selected_plughw',
                           self._player._alsa_device or 'plughw:1,0')

        gen = getattr(self, '_alsa_probe_gen', 0) + 1
        self._alsa_probe_gen = gen
        self._alsa_probe_error = ''
        self._alsa_probe_active = True   # tells _on_player_error we're inside a probe

        # Consume saved position/state once; reused across all retries.
        _probe_pos_ms = getattr(self._player, '_last_switch_pos_ms', None)
        _probe_was_playing = getattr(self._player, '_last_switch_was_playing', True)
        if _probe_pos_ms is None:
            _probe_pos_ms = max(0, int(self._player.position_ms())) if self._player._last_filepath else 0
        if _probe_was_playing is None:
            _probe_was_playing = True
        self._player._last_switch_pos_ms      = None
        self._player._last_switch_was_playing = None

        print(f'[AudioSwitch] ALSA probe START: {PRIMARY!r} / {FALLBACK!r}'
              f'  (resume pos={_probe_pos_ms} ms, was_playing={_probe_was_playing})')

        _dev_label = FALLBACK.replace('plughw:', '').split(',')[0]
        self._status.showMessage(f'⏳  Probing ALSA device: {_dev_label} …', 0)
        self._ctrlbar.set_play_busy(True)

        def _hide_spinner():
            self._ctrlbar.set_play_busy(False)

        def _confirm(device: str):
            if self._alsa_probe_gen != gen:
                return
            print(f'[AudioSwitch] ALSA confirmed working device: {device!r}')
            self._alsa_confirmed_device = device
            self._alsa_probe_needed     = False
            self._alsa_probe_error      = ''
            self._alsa_probe_active     = False
            self._player._alsa_device   = device
            _hide_spinner()
            self._status.clearMessage()
            pop = self._ctrlbar._settings_popup
            if pop is not None:
                combo_dev = FALLBACK if Player._is_hw_device(device) else device
                pop.set_output_device(combo_dev)
                self._ctrlbar._refresh_audio_info()
            # Pipeline is PLAYING from position 0.  Mute, seek to original position,
            # then unmute — ALSA device stays open (needs audio flowing) but user
            # hears nothing from position 0.  After seek settles, restore play state.
            if _probe_pos_ms > 200 and self._player.has_pipe:
                self._player._pipe.set_property('volume', 0.0)
                self._player.seek(_probe_pos_ms)
                def _after_seek():
                    if not self._player.has_pipe:
                        return
                    self._player._pipe.set_property('volume', self._player._effective_volume())
                    if not _probe_was_playing and self._player.playing:
                        self._player.play_pause()
                    self._ctrlbar.set_play_icon(self._player.playing)
                QTimer.singleShot(450, _after_seek)
                return   # set_play_icon called inside _after_seek
            if not _probe_was_playing and self._player.playing:
                self._player.play_pause()
            self._ctrlbar.set_play_icon(self._player.playing)

        def _give_up():
            if self._alsa_probe_gen != gen:
                return
            err = self._alsa_probe_error or 'ALSA device unavailable'
            print(f'[AudioSwitch] ALSA probe exhausted. Last error: {err!r}')
            self._alsa_probe_active = False
            _hide_spinner()
            self._status.showMessage('⚠  ALSA device unavailable — try Retry or switch to PipeWire', 6000)
            self._device_busy_popup.show_error(err)

        # (device, delay_ms_before_attempt)
        # hw: first (bit-perfect); plughw: as immediate fallback if hw: busy;
        # then back off so PipeWire has time to release the hw: node.
        _schedule = [
            (PRIMARY,  0),
            (FALLBACK, 0),
            (PRIMARY,  2000),
            (FALLBACK, 2000),
            (PRIMARY,  4000),
        ]

        def _attempt(idx: int):
            if self._alsa_probe_gen != gen:
                return
            if idx >= len(_schedule):
                _give_up(); return
            device, delay = _schedule[idx]

            def _run():
                if self._alsa_probe_gen != gen:
                    return
                print(f'[AudioSwitch] ALSA probe attempt {idx + 1}/{len(_schedule)}: {device!r}')
                self._player._alsa_device = device
                self._alsa_probe_error = ''
                self._status.showMessage(
                    f'⏳  ALSA {idx + 1}/{len(_schedule)}: trying {device} …', 0)
                if self._cur_track_mw is not None:
                    # Load PLAYING — ALSA hw: closes the device when no audio flows,
                    # so paused=True would cause the pipeline to drop to NULL/READY
                    # and _confirm's play_pause() would hit the dead-pipe reload path.
                    # Anchor to the original position first so the seekbar doesn't
                    # snap to 0 during the probe window.
                    if _probe_pos_ms > 0:
                        self._player._anchor_now(float(_probe_pos_ms))
                    self._player.load(self._cur_track_mw.filepath)
                    self._ctrlbar.set_track(self._cur_track_mw)
                QTimer.singleShot(800, lambda: _check(idx, device))

            if delay > 0:
                self._status.showMessage(
                    f'⏳  ALSA: device busy — retrying in {delay // 1000}s …', 0)
                QTimer.singleShot(delay, _run)
            else:
                _run()

        def _check(idx: int, device: str):
            if self._alsa_probe_gen != gen:
                return
            if not self._alsa_probe_error:
                _confirm(device)
            else:
                print(f'[AudioSwitch] attempt {idx + 1} failed ({self._alsa_probe_error!r}), trying next')
                _attempt(idx + 1)

        _attempt(0)

    def _on_player_error(self, err: str) -> None:
        """Record ALSA probe errors; PipeWire errors fall through to status bar."""
        using_alsa = Player._is_hw_device(self._player._alsa_device)
        print(f'[AudioSwitch] player error (alsa={using_alsa}, device={self._player._alsa_device!r}): {err!r}')
        if using_alsa:
            self._alsa_probe_error = err
            self._alsa_probe_needed = True
            # If this error fired during normal playback (not inside an active probe
            # window), the pipeline is now dead and nobody will restart it.
            # Re-probe immediately so the user doesn't get stuck silently.
            # If a probe IS already running, _check() handles the error — don't
            # start a second probe (that would cancel the first via gen increment).
            probe_running = getattr(self, '_alsa_probe_active', False)
            if not probe_running and self._cur_track_mw is not None:
                # Save position before pipeline was destroyed so resume is accurate.
                if getattr(self._player, '_last_switch_pos_ms', None) is None:
                    saved = int(self._player._pos_anchor_ms)
                    if saved > 0:
                        self._player._last_switch_pos_ms      = saved
                        self._player._last_switch_was_playing = True
                self._alsa_probe_needed = False
                QTimer.singleShot(0, self._alsa_probe_and_play)
        else:
            self._status.showMessage(f'Error: {err}', 5000)

    def _on_player_busy(self, busy: bool):
        """Pipeline is reloading — show spinner on play button, disable MPRIS play/pause."""
        self._ctrlbar.set_play_busy(busy)
        self._mpris.set_pipeline_busy(busy)
        if not busy:
            # Sync play icon to actual state once reload is done
            self._ctrlbar.set_play_icon(self._player.playing)
            self._mpris.notify_status()

    def _on_shuffle_toggled(self, v: bool):
        self._shuffle = v
        if hasattr(self, '_mpris'):
            GLib.idle_add(self._mpris._emit, ['Shuffle'])

    def _on_repeat_changed(self, _mode):
        if hasattr(self, '_mpris'):
            GLib.idle_add(self._mpris._emit, ['LoopStatus'])

    def _play_pause(self):
        if not self._player.has_pipe:
            if self._cur_page and self._cur_page.tracks:
                if self._cur_idx < 0: self._cur_idx = 0
                self._alsa_play()
        else:
            self._player.play_pause()
            self._ctrlbar.set_play_icon(self._player.playing)
            self._mpris.notify_status()
        # Play/pause is an intentional user action — reset idle timer
        self._ctrlbar._reset_idle_timer()

    def _prev_track(self):
        self._sync_cur_idx()
        if self._cur_page and self._cur_idx > 0:
            was_playing = self._player.playing
            self._cur_idx -= 1
            self._navigate_track(was_playing)

    def _next_track(self): self._advance(forced=True)

    def _sync_cur_idx(self):
        """After a sort the page reorders _tracks; sync our _cur_idx to match."""
        if not self._cur_page: return
        pi = self._cur_page.playing_idx
        if pi >= 0:
            self._cur_idx = pi

    def _advance(self, forced=False):
        if not self._cur_page: return
        self._sync_cur_idx()          # always use the post-sort index
        n = len(self._cur_page.tracks)
        if n == 0: return
        repeat = self._ctrlbar.btn_rep.current_mode()
        if not forced and repeat == RepeatMode.ONE: self._alsa_play(); return
        if self._shuffle:
            if n > 1:
                # Pick random index != current without allocating a list
                skip = random.randrange(n - 1)
                self._cur_idx = skip if skip < self._cur_idx else skip + 1
            # n==1: only one track; replay it (choices would be empty)
            # repeat=NONE in shuffle mode: still play (no hard stop)
        else:
            self._cur_idx += 1
            if self._cur_idx >= n:
                if repeat == RepeatMode.ALL: self._cur_idx = 0
                else:
                    self._player.stop(); self._ctrlbar.set_play_icon(False)
                    self._mpris.notify_status(); return
        if forced:
            # Manual next: preserve playing/paused state
            self._navigate_track(self._player.playing)
        else:
            self._alsa_play()

    def _on_track_end(self): self._advance()

    # --- Focus handling ---
    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            if hasattr(self, '_titlebar'):
                # Sync restore/maximize icon with the actual post-change window state
                self._titlebar._btn_max.setText(
                    '❐' if self.isMaximized() else '□'
                )
        if e.type() == QEvent.Type.ActivationChange:
            # Don't pause viz just because EQ/Settings Tool window is focused
            eq_vis  = self._ctrlbar._eq_popup is not None and self._ctrlbar._eq_popup.isVisible()
            set_vis = self._ctrlbar._settings_popup is not None and self._ctrlbar._settings_popup.isVisible()
            blackout_vis = self._blackout.isVisible()
            app_active = self.isActiveWindow() or eq_vis or set_vis or blackout_vis
            was_active = getattr(self, '_was_active', False)
            if not app_active and not blackout_vis:
                self._ctrlbar.set_focus_paused(True)
                self._ctrlbar._idle_timer.stop()   # pause countdown while unfocused
                # Throttle position timer: unfocused playback only needs 1 s
                # resolution for MPRIS / stall-detection — saves ~3 Python wakeups/s.
                # Only throttle when not in a burst sequence (burst needs 100 ms).
                if self._player._pos_timer.isActive() and \
                        self._player._pos_timer_burst == 0:
                    self._player._pos_timer.setInterval(1000)
            elif app_active:
                self._ctrlbar.set_focus_paused(False)
                # Restore position timer to normal 250 ms rate on focus gain
                if self._player._pos_timer.isActive() and \
                        self._player._pos_timer_burst == 0:
                    self._player._pos_timer.setInterval(250)
                # Restart idle timer only on the rising edge (focus gain)
                if not was_active:
                    self._ctrlbar._idle_last_mouse = None   # reset mouse anchor on focus gain
                    self._ctrlbar._reset_idle_timer()
                # Trigger deferred lyrics fetch if panel is visible
                if self._lyrics_panel.isVisible():
                    self._lyrics_panel.on_focus_gained()
            self._was_active = app_active

    def eventFilter(self, obj, event):  # noqa: N802
        """Application-level filter: reset OLED idle timer on meaningful user activity.

        Design constraints (CPU / tick budget):
        - MouseMove: only reset when displacement from last-reset position > 5 px.
          We compare against _idle_last_mouse which is refreshed lazily; no per-frame
          math when the timer is disabled or the overlay is visible.
        - KeyPress: unconditional reset (cheap; infrequent relative to mouse events).
          Media keys (Play/Pause/Stop/Next/Prev) are also key events so they are
          covered here automatically — no separate hook needed.
        - TouchBegin/Update/End: reset on any finger/stylus touch contact.
        - TabletMove / TabletEnterProximity: reset on stylus hover over screen.
        - All other event types: zero-cost early return.
        - The filter never consumes events (always returns False / super).
        """
        etype = event.type()

        # ── Touch & stylus hover — reset idle unconditionally (cheap) ──────────
        if etype in (
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TabletMove,
            QEvent.Type.TabletEnterProximity,
        ):
            ctrlbar = self._ctrlbar
            if not ctrlbar._overlay_auto_open:
                return False
            bref = getattr(ctrlbar, '_blackout_ref', None)
            if bref is not None and bref.isVisible():
                return False
            ctrlbar._reset_idle_timer()
            return False

        if etype == QEvent.Type.MouseMove:
            ctrlbar = self._ctrlbar
            # Fast-path: bail immediately when feature is off or overlay is showing
            if not ctrlbar._overlay_auto_open:
                return False
            bref = getattr(ctrlbar, '_blackout_ref', None)
            if bref is not None and bref.isVisible():
                return False
            # Only react when our window is active
            if not self.isActiveWindow():
                return False
            pos = QCursor.pos()   # global screen coords — no widget mapping needed
            last = ctrlbar._idle_last_mouse
            if last is None:
                # First move after focus gain: anchor but don't reset yet
                ctrlbar._idle_last_mouse = pos
            else:
                dx = pos.x() - last.x()
                dy = pos.y() - last.y()
                if dx * dx + dy * dy > 25:   # 5² — integer math, no sqrt
                    ctrlbar._idle_last_mouse = pos
                    ctrlbar._reset_idle_timer()
            return False

        if etype == QEvent.Type.KeyPress:
            ctrlbar = self._ctrlbar
            if not ctrlbar._overlay_auto_open:
                return False
            bref = getattr(ctrlbar, '_blackout_ref', None)
            if bref is not None and bref.isVisible():
                return False
            if not self.isActiveWindow():
                return False
            ctrlbar._reset_idle_timer()
            return False

        return False

    # --- Search / tab ---
    def _apply_search(self, q):
        page = self._tabs.currentWidget()
        if isinstance(page, PlaylistPage): page.apply_filter(q)

    def _on_tab_change(self, idx):
        page = self._tabs.widget(idx)
        # _cur_page tracks the SOURCE playlist for playback (set in _play_from_page).
        # Switching tabs only changes the *view* — it must NOT redirect the queue.
        if isinstance(page, PlaylistPage): self._update_count(page)

    def _update_count(self, page=None):
        if page is None: page = self._tabs.currentWidget()
        if isinstance(page, PlaylistPage):
            self._count_lbl.setText(f'{len(page.tracks)} tracks')

    # --- Config ---
    def _on_col_widths_changed(self, widths: list, source_page=None):
        """User resized a column — sync to every OTHER page and save."""
        self._last_col_widths = widths
        for page in [self._lib_page] + self._playlists:
            if page is not None and page is not source_page:
                page.table.restore_col_widths(widths)
        self._save_config()

    def _save_config(self):
        # Don't save while the startup playlist loader is still running — _playlists
        # is only partially populated at that point, so writing config now would
        # silently discard every playlist that hasn't been emitted yet.
        if getattr(self, '_config_loader', None) is not None:
            # Re-arm the debounce timer so we retry shortly after the loader finishes.
            if hasattr(self, '_settings_save_timer'):
                self._settings_save_timer.start()
            return
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Build cfg with the four "quick-glance" keys at the top so they are
            # easy to find / hand-edit in the JSON file.  Python 3.7+ dicts preserve
            # insertion order; json.dumps() serialises in that order.
            # Backward compatibility is unaffected — keys are still read by name.
            cfg = {
                'lyrics_panel_open':             self._lyrics_panel.isVisible(),
                'cover_locked_paths':            list(self._cover_locked_paths),
                'lastfm_api_key':                _lastfm_api_key,
                'use_system_window_decorations': getattr(self, '_use_system_decorations', False),
            }
            cfg.update(self._ctrlbar.config_state())
            cfg['playlists'] = [{'label': pl.label, 'tracks': [t.filepath for t in pl.tracks]}
                                 for pl in self._playlists
                                 if pl.label != '__open_with__']
            cfg['known_paths'] = list(self._known_paths)
            # Persist active tab so it can be restored on next launch
            cur = self._tabs.currentWidget()
            if cur is self._lib_page:
                cfg['active_tab_label'] = '__library__'
            else:
                cfg['active_tab_label'] = (self._tabs.tabText(self._tabs.currentIndex())
                                           .strip())
            # Persist table column ratios (proportional, sum ≈ 1.0)
            total_w = sum(self._lib_page.table.columnWidth(c) for c in range(len(COLS)))
            if total_w > 0:
                cfg['table_col_widths'] = [self._lib_page.table.columnWidth(c) / total_w
                                           for c in range(len(COLS))]
            # Persist splitter sizes (sidebar / content / lyrics)
            body = self.findChild(QSplitter, 'body_splitter')
            if body:
                cfg['splitter_sizes'] = body.sizes()
            # Persist vertical splitter (content area / control bar)
            if hasattr(self, '_vsplit'):
                cfg['vsplit_sizes'] = self._vsplit.sizes()
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            # Write M3U8 for user-created playlists (those with _m3u_path attribute)
            for pl in self._playlists:
                if hasattr(pl, '_m3u_path'):
                    try:
                        lines = ['#EXTM3U\n']
                        for t in pl.tracks:
                            lines.append(f'#EXTINF:{int(t.duration)},{t.artist} - {t.title}\n')
                            lines.append(t.filepath + '\n')
                        with open(pl._m3u_path, 'w', encoding='utf-8') as f:
                            f.writelines(lines)
                    except Exception as e2:
                        print(f'M3U8 save error for {pl.label}: {e2}')
        except Exception as e:
            print(f'Config save error: {e}')

    def _close_splash(self):
        """Close startup splash if one was provided — safe to call multiple times."""
        sp = getattr(self, '_splash_ref', None)
        if sp is not None:
            self._splash_ref = None   # prevent double-close
            sp.close_overlay()
        # Handle "Open With" file after library is ready
        if getattr(self, '_open_with_path', None):
            QTimer.singleShot(0, self._handle_open_with)

    def _handle_open_with(self):
        """Add the file passed via 'Open With' / CLI arg to the library.

        The track is inserted into an internal hidden playlist so _rebuild_library
        picks it up naturally. The library tab is shown, the track is selected and
        highlighted, but playback is left paused so the user decides when to play.
        """
        path = getattr(self, '_open_with_path', None)
        if not path:
            return
        self._open_with_path = None

        fp = str(Path(path).resolve())
        ext = Path(fp).suffix.lower()
        if ext not in SUPPORTED_EXT:
            self._status.showMessage(
                f'Open With: unsupported format "{ext}" — {Path(fp).name}', 5000)
            return

        track = read_metadata(fp)

        # Use a dedicated hidden playlist that accumulates "open with" files.
        # Feeding into _playlists means _rebuild_library picks it up naturally.
        if not hasattr(self, '_open_with_pl'):
            self._open_with_pl = PlaylistPage([], label='__open_with__')
            self._open_with_pl.play_track.connect(self._play_from_page)
            self._open_with_pl.ctx_requested.connect(self._show_ctx_menu)
            self._playlists.append(self._open_with_pl)

        existing_fps = {t.filepath for t in self._open_with_pl.tracks}
        if fp not in existing_fps:
            tracks = list(self._open_with_pl.tracks)
            sk = track.sort_key()
            ins = bisect.bisect_left([t.sort_key() for t in tracks], sk)
            tracks.insert(ins, track)
            self._open_with_pl.set_tracks(tracks, -1)

        self._rebuild_library()

        try:
            row = next(i for i, t in enumerate(self._lib_page.tracks)
                       if t.filepath == fp)
        except StopIteration:
            return

        self._select_source(-1)

        self._cur_page = self._lib_page
        self._cur_idx = row

        # Update all UI elements to reflect the track WITHOUT touching the
        # GStreamer pipeline. Loading+immediately-pausing causes a state-change
        # race: if the user clicks another track before the pipeline settles,
        # the second load() blocks the UI thread. Keeping has_pipe=False means
        # _play_pause() will call _start_playback() cleanly when the user
        # decides to play.
        t = self._lib_page.tracks[row]
        self._cur_track_mw = t
        self._ctrlbar.set_track(t)
        self._ctrlbar.set_play_icon(False)
        self._lib_page.set_playing(row)
        self.setWindowTitle(f'{t.title}  —  VoidPulse')
        self._status.showMessage(f'⏸  {t.artist}  —  {t.title}', 0)
        self._blackout.set_track(t.title or Path(t.filepath).name, t.artist, t.album)
        self._blackout.set_lyrics_context('', '', '')
        self._mpris.notify_track(t)
        self._mpris.notify_status()

        self._lib_page.table.scrollTo(
            self._lib_page.table.model().index(row, 0))

    def _load_config(self):
        if not CONFIG_PATH.exists():
            QTimer.singleShot(0, self._rebuild_library)
            self._close_splash()
            return
        try:
            data = json.loads(CONFIG_PATH.read_text())
            for kp in data.get('known_paths', []):
                self._known_paths.add(kp)

            self._cover_locked_paths = set(data.get('cover_locked_paths', []))
            _cover_locked_set.update(self._cover_locked_paths)
            global _cover_fetch_on
            _cover_fetch_on = data.get('cover_fetch_on', True)
            global _lastfm_api_key
            _lastfm_api_key = data.get('lastfm_api_key', '')
            self._ctrlbar.init_from_config(data)
            # If light mode was restored from config, widget inline stylesheets
            # were baked with dark values during _build_ui. Re-apply now so
            # cbar_widget, play button, seek handle etc. pick up light colours.
            if not data.get('dark_mode', True):
                QTimer.singleShot(0, self._refresh_theme_no_overlay)
            # Window decoration mode — applied before showMaximized() so no flicker
            if data.get('use_system_window_decorations', False):
                self._apply_decoration_mode(True)
            if data.get('lyrics_panel_open', False):
                QTimer.singleShot(200, self._open_lyrics_panel_from_config)
            # Restore table column ratios (deferred so viewport is fully sized)
            col_widths = data.get('table_col_widths', [])
            if col_widths:
                self._last_col_widths = col_widths
                def _apply_saved_ratios(r=col_widths):
                    self._lib_page.table.restore_col_widths(r)
                    for pl in self._playlists:
                        pl.table.restore_col_widths(r)
                QTimer.singleShot(0, _apply_saved_ratios)
            # Restore splitter sizes
            splitter_sizes = data.get('splitter_sizes', [])
            if splitter_sizes and len(splitter_sizes) >= 2:
                body = self.findChild(QSplitter, 'body_splitter')
                if body:
                    QTimer.singleShot(100, lambda s=splitter_sizes: body.setSizes(s))
            # Restore vertical splitter (content / control bar)
            vsplit_sizes = data.get('vsplit_sizes', [])
            if vsplit_sizes and len(vsplit_sizes) == 2 and hasattr(self, '_vsplit'):
                QTimer.singleShot(100, lambda s=vsplit_sizes: self._vsplit.setSizes(s))

            # Remember which tab was active so _on_config_playlists_done can restore it
            self._restore_tab_label = data.get('active_tab_label', '__library__')
            # Load playlist track metadata asynchronously to avoid blocking the UI.
            # ConfigPlaylistLoader emits playlist_ready once per playlist in order.
            playlist_data = data.get('playlists', [])
            if playlist_data:
                self._status.showMessage('Loading playlists…')
                loader = ConfigPlaylistLoader(playlist_data)
                loader.playlist_ready.connect(self._on_config_playlist_ready)
                loader.all_done.connect(self._on_config_playlists_done)
                loader.all_done.connect(loader.deleteLater)
                # Wire splash-done BEFORE start() so the signal is never missed
                loader.all_done.connect(self._close_splash)
                # Keep a reference so the thread isn't garbage-collected mid-run
                self._config_loader = loader
                loader.start()
            else:
                QTimer.singleShot(0, self._rebuild_library)
                self._close_splash()
        except Exception as e:
            print(f'Config load error: {e}')
            QTimer.singleShot(0, self._rebuild_library)
            self._close_splash()

    def _on_config_playlist_ready(self, tracks: list, label: str):
        """Called on main thread for each playlist loaded by ConfigPlaylistLoader."""
        page = PlaylistPage(tracks, label=label)
        page.play_track.connect(self._play_from_page)
        page.ctx_requested.connect(self._show_ctx_menu)
        page.col_widths_changed.connect(lambda w, p=page: self._on_col_widths_changed(w, p))
        page.set_tracks(tracks)
        # Apply view settings (settings popup already initialised by init_from_config)
        pop = self._ctrlbar._settings_popup
        if pop is not None:
            page.set_view_mode(pop.view_mode())
            page.set_list_scale(pop.list_scale())
            page.set_gallery_scale(pop.gallery_scale())
            page.set_covers_on(pop.cover_on())
        # Restore saved column ratios
        saved = getattr(self, '_last_col_widths', None)
        if saved:
            page.table.restore_col_widths(saved)
        self._playlists.append(page)
        self._tabs.addTab(page, f' {label} ')
        self._sidebar.add_playlist(label)
        self._status.showMessage(f'Loaded "{label}" — {len(tracks)} tracks')

    def _on_config_playlists_done(self):
        """All playlists loaded — rebuild library index and finalize."""
        self._config_loader = None
        self._rebuild_library()
        self._status.showMessage('Library ready', 3000)
        # Restore the previously active tab
        label = getattr(self, '_restore_tab_label', '__library__')
        if label and label != '__library__':
            for i in range(self._tabs.count()):
                if self._tabs.tabText(i).strip() == label:
                    self._tabs.setCurrentIndex(i)
                    # i==0 is library; playlists start at tab 1 → sidebar idx i-1
                    self._sidebar.select_source(i - 1)
                    break
        else:
            self._sidebar.select_source(-1)   # highlight Library row
        # If _save_config was called while the loader was running (e.g. triggered
        # by settings_changed during init_from_config), flush it now that
        # _playlists is complete.
        if hasattr(self, '_settings_save_timer') and self._settings_save_timer.isActive():
            self._settings_save_timer.stop()
        QTimer.singleShot(0, self._save_config)

    # --- Keyboard ---
    def keyPressEvent(self, e):
        k, mod = e.key(), e.modifiers()
        if   k == Qt.Key.Key_Space:                                       self._play_pause()
        elif k == Qt.Key.Key_Left:   self._player.seek(max(0, self._player.position_ms()-5000))
        elif k == Qt.Key.Key_Right:  self._player.seek(self._player.position_ms()+5000)
        elif k in (Qt.Key.Key_BracketLeft,  Qt.Key.Key_MediaPrevious):   self._prev_track()
        elif k in (Qt.Key.Key_BracketRight, Qt.Key.Key_MediaNext):       self._next_track()
        elif k == Qt.Key.Key_MediaPlay:                                   self._play_pause()
        elif k == Qt.Key.Key_MediaStop:
            self._player.stop(); self._ctrlbar.set_play_icon(False); self._mpris.notify_status()
        elif k == Qt.Key.Key_F and mod == Qt.KeyboardModifier.ControlModifier:
            self._sidebar._search.setFocus(); self._sidebar._search.selectAll()
        else: super().keyPressEvent(e)

    def closeEvent(self, e):
        # Remove the hidden __open_with__ playlist before saving so it never
        # appears on next launch.  If it was the active source, clear _cur_page
        # to prevent a stale reference in the saved config.
        ow_pl = getattr(self, '_open_with_pl', None)
        if ow_pl is not None and ow_pl in self._playlists:
            if self._cur_page is ow_pl:
                self._cur_page = None
            self._playlists.remove(ow_pl)
        self._save_config()
        self._player.stop()
        super().closeEvent(e)

# ══════════════════════════════════════════════════════════════════════════════
