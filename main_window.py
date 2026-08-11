"""
VoidPulse — MainWindow: top-level QMainWindow, widget tree construction,
signal wiring, config save/restore, playback control, ALSA/PipeWire probing,
cover/theme reload, tag editing orchestration, "Open With" support.
"""
from constants import *

from time import monotonic as _monotonic
from constants import ACC, ACCH, BG3, BG4, CONFIG_PATH, FG, FG2, SUPPORTED_EXT, _open_audio, _r
import constants as _const_mod
from constants import is_system_qt_theme_active, resync_system_qt_theme, is_applying_own_palette, start_qt6ct_live_reload
from metadata_online import embed_cover_bytes
from cover_art import (
    Track, read_metadata, draw_default_cover,
    _ensure_async_cover_loader, _trim_cover_cache,
    _square_pixmap, _COVER_MASTER_SIZE, _cover_disk_key,
    _COVER_JPEG_QUALITY, _cover_disk_write_mtime, _COVER_DISK_DIR,
    _cover_cache, _cover_locked_set,
)
from player import Player, RepeatMode
from resampler import (invalidate_pipewire_rate_cache, invalidate_pipewire_sink_rate_cache,
                        invalidate_pipewire_allowed_rates_cache)
from mpris import MprisServer
from views import TrackTable, PlaylistPage, COLS, C_TIT
from sidebar import Sidebar
from controlbar import ControlBar
from titlebar import BlackTitleBar, _TB_H
from lyrics import LyricsPanel
from queue_panel import QueuePanel
from dialogs_edit import TagEditDialog
from library import ConfigPlaylistLoader, ScanThread, _recover_rename_temps
from remote import (NetworkShareDialog, RemoteMounter, SeekProbe, default_label,
                    share_local_path)
import remote_io
from blackout_overlay import BlackoutOverlay
# SettingsPopup is instantiated lazily inside ControlBar._ensure_settings_popup
from widgets_base import _ModalOverlay, DeviceBusyPopup, _SpinningOverlay

class MainWindow(QMainWindow):
    def __init__(self, splash=None, open_with: str = None):
        super().__init__()
        self._open_with_path = open_with   # file passed via "Open With" / CLI arg
        self._use_system_decorations = False  # overridden by _load_config if set
        self._use_system_qt_theme = False     # overridden by _load_config if set
        # An unfocused window normally throttles position polling and pauses viz
        # and lyrics highlighting to save CPU. Setting this keeps them running in
        # the background instead — the settings popup's "BCK. OP." switch, stored
        # inverted (switch on = optimizations on = this flag False).
        self._disable_background_optimizations = False  # overridden by _load_config if set
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
        # Saved network shares: [{'uri','user','domain','anonymous','label'}].
        # Passwords live in the desktop keyring, never in here — see remote.py.
        self._network_shares: list = []
        self._share_dialog: Optional[NetworkShareDialog] = None
        # uri → share dict awaiting a successful mount, so the entry is only
        # saved once the connection actually worked
        self._pending_share_meta: dict = {}
        self._cover_locked_paths: set = set()
        self._cur_track_mw: Track = None
        # Built in _build_ui; declared here because _advance() reads it and can
        # in principle run before the panel exists.
        self._queue:        Optional[QueuePanel] = None
        # Share of the right dock's height the lyrics panel gets when both it
        # and the queue are open. Halves until the user drags the divider.
        self._dock_ratio    = 0.5
        # The track playback took off the queue, held for as long as it plays.
        # It is already gone from the queue by then, so this is the only handle
        # on it — and the flag that says _cur_page/_cur_idx describe the page
        # position waiting underneath rather than what is coming out of the
        # speakers. None means playback is on the page, the ordinary case.
        self._queued_track: Optional[Track] = None
        self._blackout = BlackoutOverlay()
        self._config_loader = None   # ref to ConfigPlaylistLoader while running
        self._splash_ref = splash    # held so _close_splash can always reach it
        self._build_ui()
        self._connect_signals()
        self._load_config()
        # _splash_ref stays set here: ConfigPlaylistLoader.all_done fires later and
        # _close_splash reads it at that point, then drops the reference itself.
        self._mpris = MprisServer(self._player, self)
        self._mpris.set_cover_on(self._ctrlbar.cover_on())
        self._player.sig_seek.connect(self._mpris.notify_seeked)
        # One application-level filter feeds the idle timer with activity from every
        # child widget, instead of per-widget filters and mouse tracking everywhere.
        QApplication.instance().installEventFilter(self)

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Custom frameless titlebar
        self._titlebar = BlackTitleBar(self)
        root.addWidget(self._titlebar)

        # Debounced so config is written after the drag, not during it
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(400)
        self._splitter_save_timer.timeout.connect(self._save_config)

        body = QSplitter(Qt.Orientation.Horizontal); body.setHandleWidth(16)
        body.setObjectName('body_splitter')
        self._sidebar = Sidebar(); body.addWidget(self._sidebar)

        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(False)   # Tabs are never shown for playlists
        self._tabs.tabBar().setVisible(False)   # Hide tab bar entirely; nav via sidebar
        rl.addWidget(self._tabs, 1)
        body.addWidget(right)

        # One right-hand dock holds both side panels, stacked. Two columns made
        # the content area pay for the queue twice over and left it as a mostly
        # empty strip; sharing a column keeps the window's single-rail-each-side
        # shape whichever panel is open.
        self._right_dock = QSplitter(Qt.Orientation.Vertical)
        self._right_dock.setObjectName('right_dock')
        self._right_dock.setHandleWidth(16)
        self._right_dock.setChildrenCollapsible(False)
        self._right_dock.setVisible(False)

        # ctrlbar does not exist yet; wired up below
        self._lyrics_panel = LyricsPanel(self._player, ctrlbar=None)
        self._lyrics_panel.setVisible(False)
        self._right_dock.addWidget(self._lyrics_panel)

        self._queue = QueuePanel()
        self._queue.setVisible(False)
        self._queue.set_track_resolver(self._resolve_track)
        self._right_dock.addWidget(self._queue)

        # Equal stretch: a window resize keeps the share the user dragged to
        # rather than handing every new pixel to one of the two.
        self._right_dock.setStretchFactor(0, 1)
        self._right_dock.setStretchFactor(1, 1)
        self._right_dock.splitterMoved.connect(self._on_dock_split_moved)
        body.addWidget(self._right_dock)

        for i in range(body.count()):
            body.setStretchFactor(i, 1 if i == 1 else 0)
        body.setSizes([230, 1050, 0])
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

        # A 16px handle with a 1px border: thin line, comfortable touch target
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
        self._tabs.currentChanged.connect(self._on_tab_change)

        # Child of central so it floats above the content
        self._device_busy_popup = DeviceBusyPopup(central)

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
            self.setWindowFlags(Qt.WindowType.Window)
            self._titlebar.setFixedHeight(0)
            self._titlebar.hide()
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.Window
            )
            self._titlebar.setFixedHeight(_TB_H)
            self._titlebar.show()

        # setWindowFlags() hid the window — put it back as it was
        if was_visible:
            if was_maximized:
                self.showMaximized()
            else:
                self.show()

    def _on_system_palette_changed(self, new_palette=None):
        """Fired by QGuiApplication.paletteChanged whenever the platform theme
        plugin reports a new palette — e.g. the color scheme was switched in
        qt6ct, KDE System Settings, or any other desktop reachable through
        xdg-desktop-portal.

        Coalesced, not just debounced: every extra signal within the window
        restarts the timer instead of being dropped, so a burst of several
        paletteChanged emissions for one logical theme change (common with
        some platform themes / portal backends) still only triggers exactly
        one _refresh_all_theme_widgets() pass — the expensive part (walking
        every playlist page's widgets). The window is intentionally generous
        (600ms) since instant reaction isn't a goal here; avoiding redundant
        refresh passes is. No disk I/O and no polling are involved anywhere
        in this path — it only runs at all when Qt itself reports a change.

        `new_palette` is the QPalette Qt passes as the signal argument — we
        must use that directly rather than re-querying
        QApplication.instance().palette() later, since by the time the
        debounce timer fires, VoidPulse's own app.setPalette() call (from a
        previous theme refresh) may already have overwritten it.

        Does nothing unless "use system Qt theme" is currently enabled, and
        does nothing DE-specific — it only reacts to Qt's own palette signal,
        so it works the same way under Hyprland+qt6ct, KDE Plasma, or any
        other portal-backed desktop.
        """
        if not is_system_qt_theme_active():
            return
        if is_applying_own_palette():
            # Qt emits paletteChanged for VoidPulse's own setPalette() too. Acting
            # on that would loop, with colours chasing themselves.
            return
        if new_palette is not None:
            self._pending_system_palette = QPalette(new_palette)

        timer = getattr(self, '_palette_resync_timer', None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._do_system_palette_resync)
            self._palette_resync_timer = timer
        timer.start(600)   # (re)start — coalesces bursts into a single resync

    def _do_system_palette_resync(self):
        pal = getattr(self, '_pending_system_palette', None)
        resync_system_qt_theme(pal)
        self._refresh_theme_no_overlay()

    def _on_qt6ct_file_changed(self):
        """Called (via QFileSystemWatcher, inotify-backed — no polling) when
        qt6ct's config or active color-scheme file changes on disk. This
        covers tools like matugen or wallust-driven Hyprland scripts that
        rewrite the color-scheme file directly: qt6ct's own platform plugin
        never re-reads that file once running, so there's no Qt-level
        paletteChanged to catch here — watching the file ourselves is the
        only way to react without restarting VoidPulse. Coalesced the same
        way as the palette-changed path: rapid repeated writes (e.g. an
        editor's atomic save, or a generator script touching several files
        in a row) collapse into a single refresh.
        """
        if not is_system_qt_theme_active():
            return
        timer = getattr(self, '_qt6ct_file_resync_timer', None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._do_qt6ct_file_resync)
            self._qt6ct_file_resync_timer = timer
        timer.start(600)

    def _do_qt6ct_file_resync(self):
        # apply_theme() already prefers the freshly-parsed scheme file
        from constants import apply_theme, _DARK_MODE
        apply_theme(_DARK_MODE)
        self._refresh_theme_no_overlay()

    def _connect_signals(self):
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._on_system_palette_changed)
        start_qt6ct_live_reload(self._on_qt6ct_file_changed)
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
        self._sidebar.network_share_req.connect(self._network_share_dialog)

        self._mounter = RemoteMounter(self)
        self._mounter.started.connect(self._on_share_mount_started)
        self._mounter.mounted.connect(self._on_share_mounted)
        self._mounter.failed.connect(self._on_share_failed)

        # Sleep timer: one-shot stop, plus a 1 Hz tick that keeps the countdown
        # shown in the settings popup honest.
        self._sleep_deadline: float = 0.0
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.timeout.connect(self._on_sleep_expired)
        self._sleep_tick = QTimer(self)
        self._sleep_tick.setInterval(1000)
        self._sleep_tick.timeout.connect(self._update_sleep_status)

        self._player.sig_end.connect(self._on_track_end)
        self._player.sig_xfade_due.connect(self._on_crossfade_due)
        self._player.sig_err.connect(self._on_player_error)
        self._player.sig_busy.connect(self._on_player_busy)
        self._player.sig_buffering.connect(self._on_buffering)
        self._device_busy_popup.switch_to_pipewire.connect(self._on_switch_to_pipewire)
        self._device_busy_popup.retry.connect(self._on_alsa_retry)

        # _on_output_device_changed is connected from ControlBar when the settings
        # popup is first built — the popup does not exist yet here.
        self._ctrlbar.btn_play.clicked.connect(self._play_pause)
        self._ctrlbar.btn_prev.clicked.connect(self._prev_track)
        self._ctrlbar.btn_next.clicked.connect(self._next_track)
        self._ctrlbar.btn_shuf.toggled.connect(self._on_shuffle_toggled)
        self._ctrlbar.btn_rep.mode_changed.connect(self._on_repeat_changed)
        self._ctrlbar.btn_blackout.clicked.connect(self._blackout.show_blackout)
        # The overlay is hidden nearly all the time, so skip the call outright
        # rather than pay a dispatch per position tick.
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
        # sig_pos stops while paused, so refresh the seekbar directly on a
        # lyric-click seek.
        self._lyrics_panel.seek_requested.connect(self._ctrlbar._on_pos)
        self._lyrics_panel.lyrics_context.connect(self._blackout.set_lyrics_context)
        self._ctrlbar.btn_queue.clicked.connect(self._toggle_queue)
        # The queue is shaped like a PlaylistPage, so it feeds the same slot
        self._queue.play_track.connect(self._play_from_page)
        self._queue.queue_changed.connect(self._on_queue_changed)
        self._queue.status_msg.connect(lambda m: self._status.showMessage(m, 3000))
        self._ctrlbar.set_blackout_ref(self._blackout)

        pop = self._ctrlbar._ensure_settings_popup()
        pop.view_mode_changed.connect(self._on_view_mode_changed)
        pop.list_scale_changed.connect(self._on_list_scale_changed)
        pop.gallery_scale_changed.connect(self._on_gallery_scale_changed)
        # Any setting change schedules a debounced config save
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(500)
        self._settings_save_timer.timeout.connect(self._save_config)
        self._ctrlbar.settings_changed.connect(self._settings_save_timer.start)
        _ensure_async_cover_loader().cover_loaded.connect(self._on_cover_loaded_mw)

    def _on_cover_toggle(self, on: bool):
        self._lib_page.set_covers_on(on)
        for pl in self._playlists:
            pl.set_covers_on(on)
        if hasattr(self, '_mpris'):
            self._mpris.set_cover_on(on)

    def _on_cover_toggle_with_overlay(self, on: bool, _overlay=None):
        """Cover toggle with async processing and optional overlay."""
        self._lib_page.set_covers_on(on)
        
        playlists_to_process = list(self._playlists)
        
        def _process_playlists(idx: int):
            if idx >= len(playlists_to_process):
                if hasattr(self, '_mpris'):
                    self._mpris.set_cover_on(on)
                if _overlay is not None:
                    _overlay.close_overlay()
                return
            
            pl = playlists_to_process[idx]
            pl.set_covers_on(on)
            
            # One playlist per event-loop slot, so the UI keeps repainting
            QTimer.singleShot(16, lambda: _process_playlists(idx + 1))
        
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
            # Master arrived: drop the accent pixmap so it rebuilds from the cover
            if ctrlbar._cover_acc_on:
                ctrlbar._cover_lbl._acc_pm = None
                ctrlbar._cover_lbl.update()
            return

        if size == 64:
            pm = _cover_cache.get((fp, 64))
            if pm:
                ctrlbar._cover_lbl.setPixmap(pm, fp)
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
            # TrackTable keeps a filepath→row index
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
        # Step 1: the widgets the user sees first, done synchronously
        for lbl in (self._ctrlbar._lbl_title, self._ctrlbar._lbl_artist):
            lbl.setStyleSheet('background:transparent;')
        if self._cur_page is not None:
            self._cur_page.refresh_theme()
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
        if hasattr(self, '_device_busy_popup'):
            self._device_busy_popup.refresh_theme()
        QApplication.processEvents()

        # Step 2: lyrics + popups — deferred
        def _step2():
            self._lyrics_panel.set_accent(ACC)
            self._lyrics_panel.refresh_theme()
            self._queue.refresh_theme()
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
        # Shifted by the same Delay setting as the visualizer, so the highlighted
        # line changes in step with the (deliberately delayed) viz rather than
        # racing ahead of it. Skipped entirely when the panel is hidden, or when
        # unfocused with the overlay closed, since nothing would be visible.
        if not self._lyrics_panel.isVisible():
            return
        if (not getattr(self, '_was_active', True) and not self._blackout.isVisible()
                and not getattr(self, '_disable_background_optimizations', False)):
            return
        delay_ms = getattr(self._ctrlbar, '_delay_ms', 0)
        self._lyrics_panel.on_position(max(0, ms - delay_ms))

    # Body splitter layout: sidebar | content | right dock (lyrics over queue)
    _PANEL_DOCK   = 2
    _PANEL_W      = 290   # width the dock opens at, in px

    def _open_lyrics_panel_from_config(self):
        """Restore lyrics panel open state from config."""
        if not self._panel_open(self._lyrics_panel):
            self._toggle_lyrics()

    def _open_queue_panel_from_config(self):
        if not self._panel_open(self._queue):
            self._toggle_queue()

    @staticmethod
    def _panel_open(panel: QWidget) -> bool:
        """Is this panel switched on, whatever its ancestors are doing?

        isHidden(), not isVisible() or isVisibleTo(): both of those answer False
        while the dock around the panel is collapsed or the window is minimised,
        which reads as "closed" and flips the panel the wrong way on the next
        toggle — and, since the dock is only shown once a panel asks for it,
        would leave it collapsed forever.
        """
        return not panel.isHidden()

    def _toggle_side_panel(self, panel: QWidget, btn) -> bool:
        """Show/hide one of the two panels stacked in the right-hand dock.

        The dock itself only exists while at least one of them is up; its width
        comes out of (or goes back to) the content column, so the sidebar keeps
        whatever the user dragged it to. Returns True when the panel ended up
        open.
        """
        opening = not self._panel_open(panel)
        panel.setVisible(opening)
        if btn is not None:
            btn.setChecked(opening)
        self._sync_right_dock(grew=opening)
        return opening

    def _sync_right_dock(self, grew: bool = False):
        """Match the dock's presence and split to which panels are open."""
        dock = self._right_dock
        want = self._panel_open(self._lyrics_panel) or self._panel_open(self._queue)
        body = self.findChild(QSplitter, 'body_splitter')
        if body and want != self._panel_open(dock):
            dock.setVisible(want)
            sizes = body.sizes()
            if len(sizes) > self._PANEL_DOCK:
                if want:
                    # Never shrink the track list below a usable width for a panel
                    sizes[1] = max(100, sizes[1] - self._PANEL_W)
                    sizes[self._PANEL_DOCK] = self._PANEL_W
                else:
                    sizes[1] += sizes[self._PANEL_DOCK]
                    sizes[self._PANEL_DOCK] = 0
                body.setSizes(sizes)
        elif not want:
            dock.setVisible(False)
        if grew:
            # Deferred: the dock has just been shown and has no height yet.
            QTimer.singleShot(0, self._size_right_dock)

    def _size_right_dock(self):
        """Split the dock at _dock_ratio — half and half until it is dragged.

        Only run when a panel has just been opened; while both are up the
        divider is the user's, and _on_dock_split_moved records where they left
        it so reopening lands there again.
        """
        if not (self._panel_open(self._lyrics_panel) and self._panel_open(self._queue)):
            return   # a lone panel gets the whole dock from Qt
        h = self._right_dock.height() or sum(self._right_dock.sizes()) or 720
        top = int(h * self._dock_ratio)
        self._right_dock.setSizes([top, h - top])

    def _on_dock_split_moved(self, *_):
        """Remember the dragged divider as a share of the dock, not as pixels —
        the window it has to survive is rarely the height it was dragged at.

        Qt emits this for its own relayouts too, and one of those runs while a
        panel is still coming up, with sizes that mean nothing. A held mouse
        button is what separates a drag from that: nobody is dragging a handle
        without one down.
        """
        if QApplication.mouseButtons() == Qt.MouseButton.NoButton:
            return
        sizes = self._right_dock.sizes()
        total = sum(sizes)
        if len(sizes) == 2 and total > 0 \
                and self._panel_open(self._lyrics_panel) and self._panel_open(self._queue):
            self._dock_ratio = min(0.9, max(0.1, sizes[0] / total))
        self._splitter_save_timer.start()

    def _toggle_lyrics(self, _checked=False):
        opened = self._toggle_side_panel(self._lyrics_panel, self._ctrlbar.btn_lyrics)
        if opened and self._cur_track_mw:
            deferred = not self.isActiveWindow() or self._blackout.isVisible()
            self._lyrics_panel.set_track(self._cur_track_mw, deferred=deferred)

    def _toggle_queue(self, _checked=False):
        self._toggle_side_panel(self._queue, self._ctrlbar.btn_queue)

    def _resolve_track(self, filepath: str):
        """filepath → an already-scanned Track, or None if it is not in view.

        Used by the queue panel so a drop reuses metadata the library scan
        already paid for instead of re-reading tags off disk (which matters on a
        network share).
        """
        for page in (self._lib_page, *self._playlists):
            if page is None:
                continue
            for t in page.tracks:
                if t.filepath == filepath:
                    return t
        return None

    def _on_queue_changed(self):
        """The queue's contents changed — persist them.

        There is no index to fix up: the queue only ever holds what is still to
        come, so an edit (or the pop that happens on every transition) can only
        change what plays next. Debounced, because that pop fires this on every
        single track change and a config write per track is pure waste.
        """
        self._settings_save_timer.start()

    def _add_to_queue(self, tracks: list):
        """Append to the queue, opening the panel so the result is visible."""
        self._queue.add_tracks(tracks)
        if not self._panel_open(self._queue):
            self._toggle_queue()

    def _show_ctx_menu(self, src_page, row, pos):
        if not (0 <= row < len(src_page.tracks)): return
        track = src_page.tracks[row]; m = QMenu(self)
        m.addAction('▶  Play').triggered.connect(lambda: self._play_from_page(src_page, row))
        m.addAction('＋  Add to Queue').triggered.connect(
            lambda _=False, _t=track: self._add_to_queue([_t]))
        m.addSeparator()
        add_sub = m.addMenu("Add to Playlist")
        for pl in self._playlists:
            if pl is not src_page:
                def _add(_, _pl=pl, _tr=track):
                    fps = {t.filepath for t in _pl.tracks}
                    if _tr.filepath not in fps:
                        tracks = list(_pl.tracks)
                        # Insert in place rather than re-sorting the playlist
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

    def _invalidate_cover_cache(self, fp: str):
        """Remove all cached cover data for fp so the next paint reloads it.

        The disk key carries no mtime, so the cached file is simply deleted along
        with its sidecar and re-extracted on next access.
        """
        # Every cached size, including the gallery's dynamic cover_sz
        for key in [k for k in _cover_cache if k[0] == fp]:
            _cover_cache.pop(key, None)
        # The exact disk key, never a stem glob: the key includes a path hash
        # because filename stems are not unique across a library, and a stem glob
        # would delete every same-named track's cover too.
        cover_file = _COVER_DISK_DIR / f'{_cover_disk_key(fp)}.jpg'
        if cover_file.exists():
            try:
                cover_file.unlink()
                sidecar = Path(str(cover_file) + '.mtime')
                if sidecar.exists():
                    sidecar.unlink()
            except Exception:
                pass
        # Drop fp from the loader's "has no embedded cover" set so it retries.
        # Must go through _ensure_async_cover_loader(): the module-level
        # _async_cover_loader name was still None when this module was imported,
        # and that stale binding never sees the singleton created later.
        loader = _ensure_async_cover_loader()
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
        # EBML magic — mutagen cannot write tags into WebM/MKV
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
        # Fragmented/DASH MP4 reads fine but often fails to save. It is attempted
        # anyway; the af.save() handler below detects it and explains the fix.

        dlg = TagEditDialog(track, parent=self)
        dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        _ModalOverlay.show_for(dlg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_title, new_artist, new_album = dlg.get_tags()
        cover_action, cover_bytes = dlg.get_cover_result()
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
                # An empty field leaves the existing tag alone
                if new_title:  af.tags['TIT2'] = TIT2(encoding=3, text=new_title)
                if new_artist: af.tags['TPE1'] = TPE1(encoding=3, text=new_artist)
                if new_album:  af.tags['TALB'] = TALB(encoding=3, text=new_album)

            elif ext in ('.flac', '.ogg', '.opus'):
                # Keys are normalised to lowercase, so drop uppercase duplicates
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

            fp = track.filepath
            if cover_action == 'set' and cover_bytes:
                embed_cover_bytes(fp, cover_bytes)
                self._invalidate_cover_cache(fp)
                # Built synchronously, before any repopulate below reads the cache
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
                # Pre-fill with the placeholder so the rows below pick it up
                self._invalidate_cover_cache(fp)
                for size in (28, 64):
                    _cover_cache[(fp, size)] = draw_default_cover(size)

            updated_track = read_metadata(fp)

            def _update_page(pg, idx):
                pg.tracks[idx] = updated_track
                pg.table._fill_row(idx, updated_track)
                pm28 = _cover_cache.get((fp, 28))
                if pm28:
                    item = pg.table.item(idx, C_TIT)
                    if item:
                        item.setIcon(QIcon(pm28))
                # Repopulate so the gallery re-requests its own cover size
                pg.gallery.populate(pg.tracks, pg.playing_idx)
                pg.gallery._fp_to_vis_positions = None
                pg.gallery._canvas.update()

            _update_page(page, row)
            for pg in [self._lib_page] + self._playlists:
                if pg is page:
                    continue
                i = pg.table._fp_to_row.get(updated_track.filepath, -1)
                if i >= 0 and i < len(pg.tracks) and pg.tracks[i].filepath == updated_track.filepath:
                    _update_page(pg, i)
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
        # Prefer the first known folder that is not a playlist file
        save_dir = None
        for p in self._known_paths:
            if not p.endswith(('.m3u', '.m3u8')) and os.path.isdir(p):
                save_dir = p; break
        if save_dir is None:
            save_dir = QFileDialog.getExistingDirectory(self, 'Select Playlist Folder')
            if not save_dir:
                return
        safe = ''.join(c for c in name if c.isalnum() or c in ' _-').strip() or 'playlist'
        m3u_path = str(Path(save_dir) / f'{safe}.m3u8')
        try:
            with open(m3u_path, 'w', encoding='utf-8') as f:
                f.write('#EXTM3U\n')
        except Exception as e:
            self._status.showMessage(f'Could not create M3U8: {e}', 4000); return
        # The file is empty, so there is nothing to scan
        page = PlaylistPage([], label=name)
        page.play_track.connect(self._play_from_page)
        page.ctx_requested.connect(self._show_ctx_menu)
        pop = self._ctrlbar._ensure_settings_popup()
        page.set_view_mode(pop.view_mode())
        page.set_list_scale(pop.list_scale())
        page.set_gallery_scale(pop.gallery_scale())
        page.set_covers_on(pop.cover_on())

        self._playlists.append(page)
        ti = self._tabs.addTab(page, f' {name} ')
        self._sidebar.add_playlist(name)
        self._tabs.setCurrentIndex(ti)
        self._known_paths.add(m3u_path)
        # _save_config writes the playlist back to this path
        page._m3u_path = m3u_path
        self._status.showMessage(f'"{name}" playlist created — {m3u_path}', 5000)
        self._save_config()

    # ── Sleep timer ─────────────────────────────────────────────────────────

    def _on_sleep_timer_changed(self, minutes: int):
        """Slider moved: 0 cancels, anything else (re)starts the countdown."""
        self._sleep_timer.stop()
        self._sleep_tick.stop()
        if minutes <= 0:
            self._sleep_deadline = 0.0
            self._update_sleep_status()
            self._status.showMessage('Sleep timer off', 2500)
            return
        ms = minutes * 60_000
        self._sleep_deadline = _monotonic() + ms / 1000.0
        self._sleep_timer.start(ms)
        self._sleep_tick.start()
        self._update_sleep_status()
        h, m = divmod(minutes, 60)
        pretty = f'{h}h {m:02d}m' if h else f'{m}m'
        self._status.showMessage(f'Sleep timer set — playback stops in {pretty}', 4000)

    def _update_sleep_status(self):
        pop = self._ctrlbar._settings_popup
        if self._sleep_deadline <= 0.0:
            if pop is not None:
                pop.set_sleep_status('')
            return
        left = max(0, int(self._sleep_deadline - _monotonic()))
        h, r = divmod(left, 3600); m, s = divmod(r, 60)
        text = f'stops in {h}:{m:02d}:{s:02d}' if h else f'stops in {m}:{s:02d}'
        if pop is not None:
            pop.set_sleep_status(text)

    def _on_sleep_expired(self):
        """Countdown finished — fade out and stop, then reset the slider."""
        self._sleep_tick.stop()
        self._sleep_deadline = 0.0
        self._player.fade_stop()
        self._ctrlbar.set_play_icon(False)
        self._mpris.notify_status()
        pop = self._ctrlbar._settings_popup
        if pop is not None:
            pop.reset_sleep_minutes()
        self._status.showMessage('Sleep timer elapsed — playback stopped', 6000)

    # ── Network shares ──────────────────────────────────────────────────────

    def _network_share_dialog(self):
        dlg = NetworkShareDialog(self._network_shares, self)
        self._share_dialog = dlg
        dlg.connect_requested.connect(self._connect_share)
        dlg.forget_requested.connect(self._forget_share)
        dlg.exec()
        self._share_dialog = None

    def _connect_share(self, share: dict):
        uri = share.get('uri', '')
        if not uri:
            return
        share.setdefault('label', default_label(uri))
        self._pending_share_meta[uri] = dict(share)
        if self._share_dialog is not None:
            self._share_dialog.set_busy(True)
            self._share_dialog.set_status(f'Connecting to {uri} …')
        self._mounter.mount(share)

    def _forget_share(self, uri: str):
        self._network_shares = [s for s in self._network_shares if s.get('uri') != uri]
        remote_io.forget_share(uri)
        RemoteMounter.unmount(uri)
        if self._share_dialog is not None:
            self._share_dialog.set_saved(self._network_shares)
            self._share_dialog.set_status(f'Forgot {uri}.')
        self._status.showMessage(f'Network share removed — {uri}', 4000)
        self._save_config()

    def _on_share_mount_started(self, uri: str):
        self._status.showMessage(f'Connecting to {uri} …')

    def _on_share_mounted(self, uri: str, local_path: str):
        """Share is reachable at local_path — remember it and scan it as a folder.

        The password is dropped here rather than saved: the backend has already
        handed it to the keyring if it could, and keeping a copy in the config
        would put a plaintext credential in a world-readable JSON file.
        """
        pending = self._pending_share_meta.pop(uri, None)
        existing = next((s for s in self._network_shares if s.get('uri') == uri), None)
        if pending is not None:
            pending.pop('password', None)
            if existing is not None:
                existing.update(pending)
            else:
                self._network_shares.append(pending)
        if self._share_dialog is not None:
            self._share_dialog.set_busy(False)
            self._share_dialog.set_saved(self._network_shares)
            self._share_dialog.set_status(f'Connected — mounted at {local_path}')
        self._status.showMessage(f'Connected to {uri} — checking the connection…', 4000)
        # Probe first, scan second. Whether the mount can seek decides how every
        # tag on it is read (remote_io.SeekableProxy), so scanning before the
        # answer is in would read the whole share with the wrong strategy and
        # produce a library full of untagged, zero-length tracks.
        self._start_seek_probe(uri, local_path)
        self._save_config()

    def _start_seek_probe(self, uri: str, local_path: str):
        """Find out in the background whether this mount supports seeking."""
        probe = SeekProbe(uri, local_path, self)
        probe.done.connect(lambda u, s, lp=local_path: self._on_seek_probe_done(u, s, lp))
        probe.finished.connect(probe.deleteLater)
        self._seek_probes = [p for p in getattr(self, '_seek_probes', [])
                             if not p.isFinished()]
        self._seek_probes.append(probe)   # held so the thread is not collected
        probe.start()

    def _on_seek_probe_done(self, uri: str, seekable, local_path: str = ''):
        # Registering the share is what switches tag reads and playback onto the
        # non-seekable path, so it has to happen before the scan starts.
        if local_path:
            remote_io.register_share(uri, local_path, seekable)
        if local_path:
            self._status.showMessage(f'Connected to {uri} — scanning…', 4000)
            if local_path not in self._known_paths:
                self._known_paths.add(local_path)
                self._scan_path(local_path, False)
            else:
                self._scan_path(local_path, False, refresh=True)
        if seekable is not False:
            return   # True, or nothing to test — either way, nothing to explain
        msg = (f'{uri} is connected, but the protocol itself cannot seek.\n\n'
               'Tags and durations work anyway, and tracks play normally. The '
               'first time you drag the seek bar on a track, VoidPulse fetches '
               'it to disk — playback pauses for that, with progress in the '
               'status bar — and resumes at the point you asked for; seeking is '
               'then instant for the rest of the track. Nothing is downloaded '
               'for a track you only listen to. SMB or SFTP to the same server '
               'seeks directly, with no fetch at all.')
        print(f'[Remote] non-seekable mount, seeking will fetch on demand: {uri}')
        self._status.showMessage(
            f'{uri}: no native seek — the first seek on a track fetches it first',
            12000)
        if self._share_dialog is not None:
            self._share_dialog.set_status(msg)

    def _on_share_failed(self, uri: str, reason: str):
        self._pending_share_meta.pop(uri, None)
        msg = f'Could not connect to {uri}: {reason}' if uri else reason
        print(f'[Remote] {msg}')
        if self._share_dialog is not None:
            self._share_dialog.set_busy(False)
            self._share_dialog.set_status(reason)
        self._status.showMessage(msg, 8000)

    def _remount_saved_shares(self):
        """Reconnect saved shares at startup, before their folders are scanned."""
        for share in self._network_shares:
            uri = share.get('uri', '')
            if not uri:
                continue
            local = share_local_path(uri)
            if local:
                # gvfs kept the mount from a previous session. Go through the
                # same probe-then-scan path a fresh mount takes rather than
                # scanning straight away: until the probe answers, remote_io does
                # not know whether the share can seek, and reading its tags the
                # wrong way yields a library of untagged, zero-length tracks.
                self._start_seek_probe(uri, local)
                continue
            self._pending_share_meta.setdefault(uri, dict(share))
            self._mounter.mount(share)

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
        # Only the memory cache: the disk entries carry mtime sidecars
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
        saved_ratios = getattr(self, '_last_col_widths', None) or TrackTable._DEFAULT_COL_RATIOS
        page.table.restore_col_widths(saved_ratios)
        pop = self._ctrlbar._ensure_settings_popup()
        page.set_covers_on(pop.cover_on())
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
                # Point every Track at its restored name so the UI and the next
                # config save both reflect it.
                for pl in self._playlists:
                    for t in pl.tracks:
                        if t.filepath in recovered:
                            t.filepath = recovered[t.filepath]
                QTimer.singleShot(0, self._save_config)
        # ── normal rebuild ───────────────────────────────────────────────────
        all_tracks = []
        for pl in self._playlists: all_tracks.extend(pl.tracks)
        seen = set(); dedup = []
        for t in all_tracks:
            if t.filepath not in seen: seen.add(t.filepath); dedup.append(t)
        dedup.sort(key=lambda t: t.sort_key())
        fp_to_idx = {t.filepath: i for i, t in enumerate(dedup)}
        # The playing row comes from the player's filepath, not _cur_idx: that is
        # the selection, and it goes stale when a rescan replaces the Track objects.
        pidx = -1
        player_fp = getattr(getattr(self, '_player', None), '_last_filepath', '')
        if player_fp:
            pidx = fp_to_idx.get(player_fp, -1)
        # Nothing played yet this session — fall back to the page's own index
        if pidx == -1 and 0 <= self._lib_page.playing_idx < len(self._lib_page.tracks):
            old_fp = self._lib_page.tracks[self._lib_page.playing_idx].filepath
            pidx = fp_to_idx.get(old_fp, -1)
        self._lib_page.set_tracks(dedup, pidx)
        # populate() resets the column widths
        saved = getattr(self, '_last_col_widths', None)
        if saved:
            self._lib_page.table.restore_col_widths(saved)
        self._update_count()

    def _remove_playlist(self, idx):
        if not (0 <= idx < len(self._playlists)): return
        page = self._playlists.pop(idx)
        for i in range(self._tabs.count()):
            if self._tabs.widget(i) is page:
                self._tabs.removeTab(i)
                break
        self._sidebar.remove_playlist(idx)
        # Deferred so the UI unblocks immediately
        QTimer.singleShot(0, lambda: (self._rebuild_library(), self._save_config()))

    def _rename_playlist(self, idx: int, new_label: str):
        if not (0 <= idx < len(self._playlists)): return
        page = self._playlists[idx]
        page.set_label(new_label)
        tab_idx = idx + 1   # tab 0 is the library page
        if 0 < tab_idx < self._tabs.count():
            self._tabs.setTabText(tab_idx, f' {new_label} ')
        # Sidebar._prompt_rename already relabelled the row
        self._save_config()

    def _move_playlist(self, from_idx: int, to_idx: int):
        n = len(self._playlists)
        if not (0 <= from_idx < n and 0 <= to_idx < n): return
        self._playlists[from_idx], self._playlists[to_idx] = (
            self._playlists[to_idx], self._playlists[from_idx])
        # Tab 0 is the library, playlists start at 1
        t_from = from_idx + 1
        t_to   = to_idx   + 1
        # QTabWidget cannot swap, so remove the higher index first and reinsert
        hi = max(t_from, t_to); lo = min(t_from, t_to)
        hi_widget = self._tabs.widget(hi)
        hi_label  = self._tabs.tabText(hi)
        lo_widget = self._tabs.widget(lo)
        lo_label  = self._tabs.tabText(lo)
        self._tabs.removeTab(hi)
        self._tabs.removeTab(lo)
        self._tabs.insertTab(lo, hi_widget, hi_label)
        self._tabs.insertTab(hi, lo_widget, lo_label)
        self._sidebar.move_playlist_row(from_idx, to_idx)
        self._save_config()

    def _select_source(self, idx):
        if idx == -1: self._tabs.setCurrentIndex(0)
        else:
            ti = idx+1
            if ti < self._tabs.count(): self._tabs.setCurrentIndex(ti)

    # --- Playback ---
    def _play_from_page(self, page, row):
        """Start `row` of `page`, exactly where it sits.

        Nothing is injected anywhere. A page row moves the playback position
        onto that page and plays from there; whatever is queued stays queued and
        still goes next. A queue row is taken off the queue and played on the
        spot — it is starting, so it stops being "up next" — while _cur_page and
        _cur_idx keep pointing at the page position underneath, which is where
        playback lands once the queue runs dry.
        """
        if page is None or not (0 <= row < len(page.tracks)):
            return
        if page is self._queue:
            self._queued_track = self._queue.take_row(row)
        else:
            self._queued_track = None
            self._cur_page = page
            self._cur_idx  = row
        self._alsa_play()

    def _queue_ready(self) -> bool:
        """Does the queue have something to hand over at the next transition?

        A closed panel never does: with the queue switched off, playback follows
        the page it is on and the queue sits inert until it is opened again.
        """
        q = self._queue
        return q is not None and bool(q.tracks) and self._panel_open(q)

    def _playing_track(self) -> Optional[Track]:
        """The Track playback should be on: a queued one outranks the page row.

        Everything that loads audio goes through here, so a track pulled off the
        queue survives a repeat, a device switch or an ALSA re-probe — none of
        which can find it on a page, because it is not on one.
        """
        if self._queued_track is not None:
            return self._queued_track
        if not self._cur_page:
            return None
        tracks = self._cur_page.tracks
        if not (0 <= self._cur_idx < len(tracks)):
            return None
        return tracks[self._cur_idx]

    def _mark_playing(self, track):
        """Show `track` as the playing row everywhere it appears.

        The page playback is on gets the exact row it started, since a page can
        hold the same file twice and only one of those rows was double-clicked.
        Everywhere else — and on every page at all while a queued track plays,
        because that track has no row of ours — the match is by filepath, or no
        highlight when the file is not on that page.
        """
        exact = self._cur_page if self._queued_track is None else None
        if exact is not None:
            exact.set_playing(self._cur_idx)
        fp = track.filepath if track is not None else None
        for page in (self._lib_page, *self._playlists):
            if page is None or page is exact:
                continue
            idx = next((i for i, t in enumerate(page.tracks) if t.filepath == fp), -1)
            page.set_playing(idx)

    def _alsa_play(self) -> None:
        """High-level play entry point for normal play/pause/track-change.

        If the current output is PipeWire, plays directly via _start_playback().
        If the current output is ALSA, runs the hw:/plughw: probe on first use
        or after an error; subsequent plays use the confirmed device directly.
        """
        # PipeWire selected — nothing to probe
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
        t = self._playing_track()
        if t is None: return
        # No-op unless a crossfade is configured, possible and something is
        # already playing — in which case load() keeps the outgoing pipeline
        # alive as a fading ghost instead of cutting it off.
        self._player.arm_crossfade()
        # Hand over the Track the scan already produced: without it the player
        # re-reads the tags, which on a share that cannot seek means pulling the
        # whole file before playback starts.
        self._player.load(t.filepath, track=t)
        self._ctrlbar.set_track(t); self._ctrlbar.set_play_icon(True)
        self._cur_track_mw = t
        self._blackout.set_lyrics_context('', '', '')
        if self._lyrics_panel.isVisible():
            deferred = not self.isActiveWindow() or self._blackout.isVisible()
            self._lyrics_panel.set_track(t, deferred=deferred)
        self._mark_playing(t)
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
        t = self._playing_track()
        if t is None: return
        if play:
            self._player.arm_crossfade()
        self._player.load(t.filepath, track=t)
        if not play:
            # load() always starts, so pause immediately — and never through the
            # Fade slider, which would ramp down audio the user never asked to hear.
            self._player.play_pause(fade=False)
        self._ctrlbar.set_track(t); self._ctrlbar.set_play_icon(play)
        self._cur_track_mw = t
        self._blackout.set_lyrics_context('', '', '')
        if self._lyrics_panel.isVisible():
            deferred = not self.isActiveWindow() or self._blackout.isVisible()
            self._lyrics_panel.set_track(t, deferred=deferred)
        self._mark_playing(t)
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
        # The probe tries bare hw: first, derived from the selected plughw:
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

    _PW_ADAPTIVE_RATE_PATH = (Path.home() / '.config' / 'pipewire' / 'pipewire.conf.d'
                               / '99-voidpulse-adaptive-rate.conf')
    _PW_ADAPTIVE_RATE_CONTENT = (
        "# Written by VoidPulse — safe to delete.\n"
        "# Enables PipeWire's adaptive sample-rate feature so the whole graph\n"
        "# can switch to match a connected device's native rate. This affects\n"
        "# ALL applications sharing this PipeWire session, not just VoidPulse.\n"
        "context.properties = {\n"
        "    default.clock.allowed-rates = [ 44100 48000 88200 96000 176400 192000 ]\n"
        "}\n"
    )

    def _sync_pipewire_adaptive_rate_file(self, on: bool) -> None:
        """Write or remove the opt-in PipeWire adaptive-rate config drop-in.

        Only ever called from an explicit user toggle (_on_adaptive_rate_toggled)
        or, on startup, to re-sync the file with a *previously* saved opt-in
        (see ControlBar.init_from_config) — never to silently turn the feature
        on for a user who hasn't asked for it."""
        path = self._PW_ADAPTIVE_RATE_PATH
        try:
            if on:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists() or path.read_text() != self._PW_ADAPTIVE_RATE_CONTENT:
                    path.write_text(self._PW_ADAPTIVE_RATE_CONTENT)
            else:
                if path.exists():
                    path.unlink()
        except Exception as e:
            print(f'[Config] PipeWire adaptive-rate drop-in write failed: {e}')

    def _on_adaptive_rate_toggled(self, on: bool) -> None:
        """User toggled 'ADAPTIVE RATE' in Settings — explicit action only."""
        print(f'[AudioSwitch] PipeWire adaptive sample-rate -> {on}')
        self._sync_pipewire_adaptive_rate_file(on)
        self._player.set_pipewire_adaptive_rate(on)
        invalidate_pipewire_rate_cache()
        invalidate_pipewire_sink_rate_cache()
        invalidate_pipewire_allowed_rates_cache()
        verb = 'enabled' if on else 'disabled'
        # A dialog rather than a status message: the drop-in just written only
        # applies after PipeWire reloads, so this step is mandatory, and skipping it
        # silently is what makes adaptive rate look like it did nothing.
        msg = QMessageBox(self)
        msg.setWindowTitle('Adaptive Sample Rate')
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(
            f'<b>Adaptive sample-rate {verb}.</b><br><br>'
            f'This only takes effect after PipeWire and WirePlumber reload '
            f'their config — log out and back in, or restart them now:<br><br>'
            f'<code>systemctl --user restart pipewire pipewire-pulse wireplumber</code>'
            f'<br><br>Restarting drops audio for every app using PipeWire for a '
            f'moment, not just VoidPulse. Until it happens, PipeWire keeps '
            f'running at its previous allowed sample rate(s), and VoidPulse '
            f'will keep resampling to match — this is expected, not a bug.')
        msg.setTextFormat(Qt.TextFormat.RichText)
        restart_btn = msg.addButton('Restart PipeWire Now', QMessageBox.ButtonRole.ActionRole)
        msg.addButton(QMessageBox.StandardButton.Ok)
        msg.exec()
        if msg.clickedButton() is restart_btn:
            self._restart_pipewire()
        self._save_config()

    def _on_bg_opt_toggled(self, on: bool) -> None:
        """User toggled 'BCK. OP.' in Settings.

        Stored inverted, so the JSON key keeps naming the opt-out it always named.
        Turning optimizations off resumes right away instead of waiting for the
        next ActivationChange, which would only arrive once the window is
        re-focused — by then there is nothing left to resume.
        """
        self._disable_background_optimizations = not on
        if not on:
            self._ctrlbar.set_focus_paused(False)
            if self._player._pos_timer.isActive() and \
                    self._player._pos_timer_burst == 0:
                self._player._pos_timer.setInterval(250)
        self._save_config()

    def _restart_pipewire(self) -> None:
        """Restart the user PipeWire/WirePlumber services so the adaptive-rate
        config drop-in just written (or removed) actually takes effect,
        without requiring a full logout.

        systemctl blocks until the units report ready, and the restart itself
        kills every client's connection (ours included) for a moment, so this
        must run off the GUI thread — a blocking subprocess.run() here would
        freeze the whole window for the restart's duration.
        """
        self._status.showMessage('⏳  Restarting PipeWire/WirePlumber …', 0)

        def _run():
            try:
                r = subprocess.run(
                    host_cmd('systemctl', '--user', 'restart',
                             'pipewire', 'pipewire-pulse', 'wireplumber'),
                    capture_output=True, text=True, timeout=20)
                ok  = r.returncode == 0
                err = (r.stderr or r.stdout or '').strip()
            except Exception as e:
                ok, err = False, str(e)
            QTimer.singleShot(0, lambda: self._on_pipewire_restart_done(ok, err))

        threading.Thread(target=_run, daemon=True).start()

    def _on_pipewire_restart_done(self, ok: bool, err: str) -> None:
        invalidate_pipewire_rate_cache()
        invalidate_pipewire_sink_rate_cache()
        invalidate_pipewire_allowed_rates_cache()
        if not ok:
            print(f'[AudioSwitch] PipeWire restart failed: {err}')
            self._status.showMessage(f'⚠  PipeWire restart failed: {err[:120]}', 8000)
            return
        print('[AudioSwitch] PipeWire/WirePlumber restarted')
        self._status.showMessage('✓  PipeWire/WirePlumber restarted', 5000)
        # The restart tore down our own connection too, so reload rather than
        # leave a dead pipeline behind.
        if (self._player._out == 'pipewiresink' and not self._player._is_hw_device(self._player._alsa_device)
                and self._player._last_filepath):
            pos_ms = int(self._player.position_ms())
            was_playing = self._player._playing
            fp = self._player._last_filepath
            self._player._destroy()
            QTimer.singleShot(400, lambda: self._player._load_and_seek(
                fp, pos_ms, paused=not was_playing))

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

        # Read once and reused by every retry below
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
            # The pipeline is playing from 0. Mute, seek, unmute: an ALSA hw device
            # needs audio flowing to stay open, but none of it should be heard.
            if _probe_pos_ms > 200 and self._player.has_pipe:
                # Through the player's mute gate, not a raw volume write: a fade
                # ramp in flight would otherwise overwrite the 0.0 on its very
                # next tick and let the seek be heard.
                _tok = self._player._gate_mute()
                self._player.seek(_probe_pos_ms)
                def _after_seek(_tok=_tok):
                    if not self._player.has_pipe:
                        return
                    self._player._gate_release(_tok)
                    if not _probe_was_playing and self._player.playing:
                        self._player.play_pause()
                    self._ctrlbar.set_play_icon(self._player.ui_playing)
                QTimer.singleShot(450, _after_seek)
                return   # set_play_icon called inside _after_seek
            if not _probe_was_playing and self._player.playing:
                self._player.play_pause()
            self._ctrlbar.set_play_icon(self._player.ui_playing)

        def _give_up():
            if self._alsa_probe_gen != gen:
                return
            err = self._alsa_probe_error or 'ALSA device unavailable'
            print(f'[AudioSwitch] ALSA probe exhausted. Last error: {err!r}')
            self._alsa_probe_active = False
            _hide_spinner()
            self._status.showMessage('⚠  ALSA device unavailable — try Retry or switch to PipeWire', 6000)
            self._device_busy_popup.show_error(err)

        # (device, delay before the attempt). hw: first for bit-perfect output,
        # plughw: immediately after, then the same pair again with a back-off so
        # PipeWire has time to release the hw: node.
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
                    # Loaded playing: an ALSA hw device closes when no audio flows,
                    # which would drop the pipeline to NULL and send _confirm down
                    # the dead-pipe path. The anchor keeps the seekbar in place.
                    if _probe_pos_ms > 0:
                        self._player._anchor_now(float(_probe_pos_ms))
                    self._player.load(self._cur_track_mw.filepath,
                                      track=self._cur_track_mw)
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
            # Outside a probe window nothing else will restart the dead pipeline,
            # so re-probe here. During one, _check() already handles the error and a
            # second probe would cancel the first.
            probe_running = getattr(self, '_alsa_probe_active', False)
            if not probe_running and self._cur_track_mw is not None:
                # Keep the pre-teardown position so the resume is accurate
                if getattr(self._player, '_last_switch_pos_ms', None) is None:
                    saved = int(self._player._pos_anchor_ms)
                    if saved > 0:
                        self._player._last_switch_pos_ms      = saved
                        self._player._last_switch_was_playing = True
                self._alsa_probe_needed = False
                QTimer.singleShot(0, self._alsa_probe_and_play)
        else:
            self._status.showMessage(f'Error: {err}', 5000)

    def _on_buffering(self, pct: int):
        """Fetch progress while a seek on a non-seekable share is being served.

        This is the one moment the copy is user-visible: playback has stopped
        and will resume at the requested position once the track is on disk, so
        the percentage is the only thing explaining the wait.
        """
        if self._player._seek_fetch is None:
            return
        self._status.showMessage(
            f'Seeking on a share that cannot seek — fetching the track ({pct}%)', 3000)

    def _on_player_busy(self, busy: bool):
        """Pipeline is reloading — show spinner on play button, disable MPRIS play/pause."""
        self._ctrlbar.set_play_busy(busy)
        self._mpris.set_pipeline_busy(busy)
        if not busy:
            self._ctrlbar.set_play_icon(self._player.ui_playing)
            self._mpris.notify_status()

    def _on_shuffle_toggled(self, v: bool):
        self._shuffle = v
        if hasattr(self, '_mpris'):
            GLib.idle_add(self._mpris._emit, ['Shuffle'])

    def _on_repeat_changed(self, _mode):
        if hasattr(self, '_mpris'):
            GLib.idle_add(self._mpris._emit, ['LoopStatus'])

    def _pick_initial_source(self):
        """Choose which page the play button starts from when nothing has played.

        _cur_page is seeded with the library at construction, so a fresh launch
        used to answer the first play press with the library's first track even
        when a playlist tab was open. Prefer the tab being looked at, then the
        library it already points to.

        _cur_idx >= 0 means a track was picked earlier this session — after a
        stop, or an explicit double-click — so that choice is left alone.
        """
        if self._cur_idx >= 0:
            return
        page = self._tabs.currentWidget()
        if isinstance(page, PlaylistPage) and page.tracks:
            self._cur_page = page

    def _play_pause(self):
        if not self._player.has_pipe:
            cold = self._cur_idx < 0
            self._pick_initial_source()
            # Cold start with something queued: saying what plays next is the
            # queue's whole job, so it goes first. _pick_initial_source still
            # ran, and left _cur_idx at -1 — the page it chose is where playback
            # lands once the queue drains, one step on from -1, i.e. its top.
            if cold and self._queue_ready():
                self._queued_track = self._queue.pop_next()
                self._alsa_play()
                self._ctrlbar._reset_idle_timer()
                return
            if self._cur_page and self._cur_page.tracks:
                if self._cur_idx < 0: self._cur_idx = 0
                self._alsa_play()
        else:
            self._player.play_pause()
            # ui_playing, not playing: with a nonzero Fade the pipeline is still
            # PLAYING on return from a pause press and only pauses when the ramp
            # ends, so .playing here would leave the button showing ⏸.
            self._ctrlbar.set_play_icon(self._player.ui_playing)
            self._mpris.notify_status()
        self._ctrlbar._reset_idle_timer()

    def _prev_track(self):
        if self._queued_track is not None:
            # A queued track has nothing before it in the queue — it was never
            # in a list. "Previous" backs out of it to the page track it
            # interrupted, which is exactly where _cur_idx has been waiting.
            # The track is not put back: the user skipped past it on purpose.
            self._queued_track = None
            if not (self._cur_page and 0 <= self._cur_idx < len(self._cur_page.tracks)):
                return
        else:
            self._sync_cur_idx()
            if not (self._cur_page and self._cur_idx > 0):
                return
            self._cur_idx -= 1
        self._navigate_track(self._player.ui_playing)

    def _next_track(self): self._advance(forced=True)

    def _sync_cur_idx(self):
        """After a sort the page reorders _tracks; sync our _cur_idx to match."""
        if not self._cur_page: return
        pi = self._cur_page.playing_idx
        if pi >= 0:
            self._cur_idx = pi

    def _advance(self, forced=False, from_xfade=False):
        repeat = self._ctrlbar.btn_rep.current_mode()
        # An open queue with anything in it is the next thing to play, wherever
        # playback currently is — that is what makes it a queue rather than
        # another playlist. The track already playing is never cut short; only
        # what comes after it changes, so queueing something mid-track means
        # "after this one". Taking the track off the queue as it starts is what
        # lets Clear, a closed panel and a drained queue all end in the same
        # place: back on the page, whose position never moved meanwhile.
        #
        # This runs ahead of both repeat and shuffle. Queueing a track is an
        # explicit instruction about what comes next, and it has to outrank a
        # standing mode: under Repeat One the queue would otherwise never get a
        # turn at all, so the user's click would do nothing, forever.
        if self._queue_ready():
            self._queued_track = self._queue.pop_next()
            if forced:
                self._navigate_track(self._player.ui_playing)
            else:
                self._alsa_play()
            return
        # Nothing queued, so Repeat One means what it always did: hold whatever
        # is playing — including a track that came off the queue, which is why
        # this reloads through _playing_track() rather than a page row.
        if not forced and repeat == RepeatMode.ONE and self._playing_track() is not None:
            self._alsa_play(); return
        was_queued = self._queued_track is not None
        self._queued_track = None
        if not self._cur_page: return
        if not was_queued:
            # Always use the post-sort index — except when coming off a queued
            # track, which is what the page highlights, not our place on it.
            self._sync_cur_idx()
        n = len(self._cur_page.tracks)
        if n == 0: return
        if self._shuffle:
            if n > 1:
                cur = self._cur_idx
                if 0 <= cur < n:
                    # A random index other than the current one, without building
                    # a list: draw from n-1 and step over cur.
                    skip = random.randrange(n - 1)
                    self._cur_idx = skip if skip < cur else skip + 1
                else:
                    # No current track (-1 before the first play, or an index left
                    # past the end by a shrunken playlist). There is nothing to
                    # exclude, so draw from all n — the skip-over above would
                    # otherwise shift the range and strand one track permanently.
                    self._cur_idx = random.randrange(n)
            # A single track just repeats, and shuffle ignores repeat=NONE
        else:
            self._cur_idx += 1
            if self._cur_idx >= n:
                if repeat == RepeatMode.ALL: self._cur_idx = 0
                else:
                    if from_xfade:
                        # Nothing to fade into: rewind the index and let the last
                        # track play out to its real end, where EOS stops it.
                        self._cur_idx = n - 1
                        return
                    self._player.stop(); self._ctrlbar.set_play_icon(False)
                    self._mpris.notify_status(); return
        if forced:
            # Manual skip keeps the current playing/paused state — the one the
            # user asked for, so a skip during a pause fade stays paused.
            self._navigate_track(self._player.ui_playing)
        else:
            self._alsa_play()

    def _on_track_end(self): self._advance()

    def _on_crossfade_due(self):
        """The playing track reached its crossfade point — start the next one now.

        This is the same transition _on_track_end would make a few seconds later;
        the only difference is that the outgoing pipeline is still running, so
        load() overlaps them. When the transition would stop playback anyway
        (end of a non-repeating playlist) _advance() stops as usual and the
        current track simply plays out — there is nothing to fade into.
        """
        self._advance(from_xfade=True)

    # --- Focus handling ---
    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            if hasattr(self, '_titlebar'):
                self._titlebar._btn_max.setText(
                    '❐' if self.isMaximized() else '□'
                )
            # Minimizing is handled here as well as in ActivationChange: some
            # window managers minimize without dropping activation, which used
            # to leave the 60 fps render loop and the spectrum FFT running for
            # a window nobody can see.
            self._update_activity_state()
        if e.type() == QEvent.Type.ActivationChange:
            self._update_activity_state()

    def _update_activity_state(self):
        """Pause/resume the render loop, spectrum and pos timer for visibility.

        Driven by both ActivationChange and WindowStateChange, so it has to be
        idempotent — it recomputes the desired state from scratch rather than
        toggling, and the expensive calls below are themselves no-ops when the
        state already matches.
        """
        # WindowStateChange can arrive while the window is still being built,
        # before the control bar, player and overlay exist.
        if not hasattr(self, '_ctrlbar') or not hasattr(self, '_blackout') \
                or not hasattr(self, '_player'):
            return
        # A focused EQ or settings popup still counts as active
        eq_vis  = self._ctrlbar._eq_popup is not None and self._ctrlbar._eq_popup.isVisible()
        set_vis = self._ctrlbar._settings_popup is not None and self._ctrlbar._settings_popup.isVisible()
        blackout_vis = self._blackout.isVisible()
        # The OLED overlay is its own window and draws its own viz, so it keeps
        # the app active even when the main window is minimized behind it.
        app_active = blackout_vis or (
            not self.isMinimized()
            and (self.isActiveWindow() or eq_vis or set_vis))
        # The config-only opt-out keeps viz and polling running while
        # unfocused. The idle timer stops regardless: it schedules the OLED
        # overlay, which should not count down for an unwatched window.
        bg_opt_disabled = getattr(self, '_disable_background_optimizations', False)
        was_active = getattr(self, '_was_active', False)
        if not app_active and not blackout_vis:
            self._ctrlbar._idle_timer.stop()   # pause countdown while unfocused
            # Minimized is worth pausing for even with the opt-out set: the
            # opt-out is about an unfocused but visible window.
            if not bg_opt_disabled or self.isMinimized():
                self._ctrlbar.set_focus_paused(True)
                # Unfocused, 1 s resolution is enough for MPRIS and stall
                # detection. Never during a burst, which needs 100 ms.
                if self._player._pos_timer.isActive() and \
                        self._player._pos_timer_burst == 0:
                    self._player._pos_timer.setInterval(1000)
        elif app_active:
            self._ctrlbar.set_focus_paused(False)
            if self._player._pos_timer.isActive() and \
                    self._player._pos_timer_burst == 0:
                self._player._pos_timer.setInterval(250)
            # Only on the rising edge
            if not was_active:
                self._ctrlbar._idle_last_mouse = None   # reset mouse anchor on focus gain
                self._ctrlbar._reset_idle_timer()
            if self._lyrics_panel.isVisible():
                self._lyrics_panel.on_focus_gained()
        self._was_active = app_active

    def eventFilter(self, obj, event):
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
            # Nothing to do when the feature is off or the overlay is up
            if not ctrlbar._overlay_auto_open:
                return False
            bref = getattr(ctrlbar, '_blackout_ref', None)
            if bref is not None and bref.isVisible():
                return False
            if not self.isActiveWindow():
                return False
            pos = QCursor.pos()   # global screen coords — no widget mapping needed
            last = ctrlbar._idle_last_mouse
            if last is None:
                # First move after focus gain — anchor only
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
        # _cur_page is the playback source, set in _play_from_page. Switching tabs
        # changes the view only and must not redirect the queue.
        if isinstance(page, PlaylistPage): self._update_count(page)

    def _update_count(self, page=None):
        if page is None: page = self._tabs.currentWidget()
        if isinstance(page, PlaylistPage):
            page.set_track_count(len(page.tracks))

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
            # Build cfg with the "quick-glance" keys at the top so they are
            # easy to find / hand-edit in the JSON file.  Python 3.7+ dicts preserve
            # insertion order; json.dumps() serialises in that order.
            # Backward compatibility is unaffected — keys are still read by name.
            cfg = {
                # First: it has no slider anywhere in the UI, so the file is the
                # only place it can be changed. Written back on every save so it
                # is always present to edit, even on a config that predates it.
                'viz_gamma':                     self._player._viz_gamma,
                # Same story as viz_gamma: no switch in the UI, so they are
                # written back on every save to stay hand-editable even on a
                # config that predates them.
                'show_artist_on_gallery':        _const_mod.SHOW_ARTIST_ON_GALLERY,
                'show_albums_on_gallery':        _const_mod.SHOW_ALBUMS_ON_GALLERY,
                'show_file_info_on_gallery':     _const_mod.SHOW_FILE_INFO_ON_GALLERY,
                'lyrics_panel_open':             self._panel_open(self._lyrics_panel),
                'queue_panel_open':              self._panel_open(self._queue),
                'queue':                         [t.filepath for t in self._queue.tracks],
                'cover_locked_paths':            list(self._cover_locked_paths),
                'lastfm_api_key':                _const_mod._lastfm_api_key,
                'use_system_window_decorations': getattr(self, '_use_system_decorations', False),
                'use_system_qt_theme':           getattr(self, '_use_system_qt_theme', False),
                'disable_background_optimizations': getattr(self, '_disable_background_optimizations', False),
            }
            cfg.update(self._ctrlbar.config_state())
            cfg['playlists'] = [{'label': pl.label, 'tracks': [t.filepath for t in pl.tracks]}
                                 for pl in self._playlists
                                 if pl.label != '__open_with__']
            cfg['known_paths'] = list(self._known_paths)
            # Never includes a password — see remote.py / _on_share_mounted
            cfg['network_shares'] = [
                {k: v for k, v in s.items() if k != 'password'}
                for s in self._network_shares]
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
            # Persist the dock's own split (lyrics over queue) as a ratio
            cfg['right_dock_ratio'] = round(self._dock_ratio, 4)
            # Persist splitter sizes (sidebar / content / right dock)
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
            self._network_shares = [dict(s) for s in data.get('network_shares', [])
                                    if isinstance(s, dict) and s.get('uri')]
            # Deferred so the window is up before any mount prompt or timeout:
            # an unreachable server would otherwise stall behind the splash.
            if self._network_shares:
                QTimer.singleShot(600, self._remount_saved_shares)

            self._cover_locked_paths = set(data.get('cover_locked_paths', []))
            _cover_locked_set.update(self._cover_locked_paths)
            _const_mod._lastfm_api_key = data.get('lastfm_api_key', '')
            # Which lines a gallery card draws under its title. Set before the
            # first gallery paint, so no repaint is needed to apply them.
            for _key, _attr in (('show_artist_on_gallery',    'SHOW_ARTIST_ON_GALLERY'),
                                ('show_albums_on_gallery',    'SHOW_ALBUMS_ON_GALLERY'),
                                ('show_file_info_on_gallery', 'SHOW_FILE_INFO_ON_GALLERY')):
                setattr(_const_mod, _attr,
                        bool(data.get(_key, getattr(_const_mod, _attr))))
            # Must run before init_from_config() applies dark/light theme, so
            # apply_theme() picks system-derived colors when this is enabled.
            self._use_system_qt_theme = data.get('use_system_qt_theme', False)
            self._disable_background_optimizations = data.get(
                'disable_background_optimizations', False)
            if self._use_system_qt_theme:
                apply_system_qt_theme(True)
            self._ctrlbar.init_from_config(data)
            # If light mode was restored from config, widget inline stylesheets
            # were baked with dark values during _build_ui. Re-apply now so
            # cbar_widget, play button, seek handle etc. pick up light colours.
            if not data.get('dark_mode', True) or self._use_system_qt_theme:
                QTimer.singleShot(0, self._refresh_theme_no_overlay)
            # Window decoration mode — applied before showMaximized() so no flicker
            if data.get('use_system_window_decorations', False):
                self._apply_decoration_mode(True)
            if data.get('lyrics_panel_open', False):
                QTimer.singleShot(200, self._open_lyrics_panel_from_config)
            # The tracks themselves are restored in _on_config_playlists_done,
            # once the library is loaded and most of them resolve without I/O.
            self._restore_queue_paths = list(data.get('queue', []))
            if data.get('queue_panel_open', False):
                QTimer.singleShot(200, self._open_queue_panel_from_config)
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
                    # Configs written while lyrics and the queue were separate
                    # columns hold four sizes for three widgets (and older ones
                    # three for four): trim or pad, then hand the dock whatever
                    # width either panel had.
                    sizes = list(splitter_sizes)
                    if len(sizes) > body.count():
                        dock = max(sizes[body.count() - 1:])
                        sizes = sizes[:body.count() - 1] + [dock]
                    sizes += [0] * (body.count() - len(sizes))
                    # 300ms, after the panels themselves are restored at 200ms:
                    # opening one re-splits the body, and the sizes the user
                    # dragged are the ones that should survive that.
                    QTimer.singleShot(300, lambda s=sizes: body.setSizes(s))
            ratio = data.get('right_dock_ratio')
            if ratio is not None:
                # Applied by _size_right_dock when a panel opens (200ms), which
                # is why nothing is scheduled here.
                self._dock_ratio = min(0.9, max(0.1, float(ratio)))
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
                QTimer.singleShot(0, self._restore_queue)
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
        self._restore_queue()
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

    def _restore_queue(self):
        """Rebuild the saved queue in its saved order.

        Almost every entry resolves out of the just-loaded library for free;
        only tracks that are no longer in any playlist need their tags read, and
        paths that have disappeared are dropped. Order is the whole point of a
        queue, so nothing here sorts.
        """
        paths = getattr(self, '_restore_queue_paths', None)
        self._restore_queue_paths = None
        if not paths:
            return
        tracks = []
        for fp in paths:
            t = self._resolve_track(fp)
            if t is None:
                if not os.path.isfile(fp):
                    continue
                t = read_metadata(fp)
            tracks.append(t)
        if tracks:
            self._queue.set_tracks(tracks)

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
            self._player.fade_stop(); self._ctrlbar.set_play_icon(False)
            self._mpris.notify_status()
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
        self._player.shutdown()   # stop() + hand any reserved ALSA card back
        super().closeEvent(e)

# ══════════════════════════════════════════════════════════════════════════════
