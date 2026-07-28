"""
VoidPulse — batch library operations run over many tracks at once, each with a
modal progress dialog: cover art, tags, lyrics and ReplayGain loudness.

_BaseFetchPopup holds the shared dialog behaviour (progress bar, scrolling log,
cancel/force handling, worker thread lifecycle); each concrete popup pairs a
QObject worker that does the network or disk work with a thin subclass that
formats the results.
"""
from constants import *
from constants import ACC, B2, BG, BG3, FG, FG2, _apply_scroller_properties
import constants as _const_mod
from metadata_online import (lookup_tags_online, embed_lyrics, write_tags_to_file,
                             write_replaygain_gain_tag, fetch_cover_online,
                             embed_cover_bytes)
from lyrics import (_extract_embedded_lyrics, _src_lrclib_exact, _src_lrclib_search,
                    _src_lyrics_ovh)
from cover_art import (extract_cover_bytes, _square_pixmap, _trim_cover_cache,
                       _cover_disk_key, _cover_disk_is_stale, _cover_disk_write_mtime,
                       _COVER_DISK_DIR, _COVER_JPEG_QUALITY, _COVER_MASTER_SIZE,
                       _cover_cache, _cover_locked_set)
from player_dsp import _run_rganalysis, _rg_gain_cache
import urllib.request as _urlreq
import urllib.parse as _urlparse

class _BaseFetchPopup(QDialog):
    """Shared base for CoverFetchPopup, TagFetchPopup, LyricsFetchPopup.

    Subclasses must implement:
        _make_worker()  -> QObject worker with .run(), .progress(int,int,str),
                           .track_done(...), .finished(int,int), .cancel()
        _on_track_done(fp, *args)
    And may override _on_finished(found, total) to customise the result label.
    """

    # Workers still running in the background, per popup type
    _active_workers = {}  # key: popup_type_name, value: list of (instance, worker, thread)

    def __init__(self, tracks: list, title: str, info_text: str, needs_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        self.setMinimumHeight(600)
        self._tracks   = list(tracks)
        self._thread   = None
        self._worker   = None
        self._running  = False
        self._popup_type = self.__class__.__name__
        # Mirrored so a reopened dialog can restore the running operation
        self._bg_progress = 0
        self._bg_total = needs_count
        self._bg_track_name = ''
        self._bg_log_items = []  # list of (text, ok_flag)
        self._bg_result = ''
        self._worker_id = None
        self._status_widget_key = None   # attribute name of our status-bar label

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 18, 20, 18)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f'font-size:14px;font-weight:bold;color:{FG};')
        root.addWidget(title_lbl)

        # ── Last.fm API key ───────────────────────────────────────────────────
        lfm_row = QHBoxLayout(); lfm_row.setSpacing(6)
        lfm_lbl = QLabel('Last.fm key:')
        lfm_lbl.setStyleSheet(f'color:{FG2};font-size:11px;')
        lfm_lbl.setFixedWidth(72)
        lfm_row.addWidget(lfm_lbl)
        self._lfm_edit = QLineEdit()
        self._lfm_edit.setPlaceholderText('API key (optional)')
        self._lfm_edit.setFixedHeight(22)
        self._lfm_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._lfm_edit.setText(_const_mod._lastfm_api_key)
        self._lfm_edit.setStyleSheet(
            f'QLineEdit{{background:{BG3};color:{FG};border:1px solid {B2};'
            f'border-radius:4px;padding:0 6px;font-size:11px;}}'
            f'QLineEdit:focus{{border-color:{ACC};}}'
        )
        lfm_row.addWidget(self._lfm_edit, 1)
        root.addLayout(lfm_row)

        self._lfm_edit.textChanged.connect(self._on_lfm_text_changed)
        if len(_const_mod._lastfm_api_key) == 32:
            self._set_lfm_border(True)

        info_lbl = QLabel(info_text)
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(f'color:{FG2};font-size:12px;')
        root.addWidget(info_lbl)

        self._track_lbl = QLabel('')
        self._track_lbl.setStyleSheet(f'color:{FG};font-size:12px;')
        self._track_lbl.setWordWrap(True)
        root.addWidget(self._track_lbl)

        self._progress = QProgressBar()
        self._progress.setRange(0, max(1, needs_count))
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFixedHeight(22)
        self._progress.setStyleSheet(
            f'QProgressBar{{background:{BG3};border:1px solid {B2};border-radius:4px;'
            f'color:{FG};font-size:11px;text-align:center;}}'
            f'QProgressBar::chunk{{background:{ACC};border-radius:3px;}}')
        root.addWidget(self._progress)

        self._log = QListWidget()
        self._log.setFixedHeight(140)
        self._log.setStyleSheet(
            'QListWidget{background:' + BG + ';border:1px solid ' + B2 + ';border-radius:4px;'
            'color:' + FG2 + ';font-size:10px;outline:none;}'
            'QListWidget::item{padding:1px 6px;border:none;}'
            'QListWidget::item:selected{background:transparent;color:' + FG2 + ';}'
        )
        self._log.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        QScroller.grabGesture(self._log.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        _apply_scroller_properties(self._log.viewport(), touch=False)
        root.addWidget(self._log)

        self._result_lbl = QLabel('')
        self._result_lbl.setStyleSheet(f'color:{FG2};font-size:11px;')
        root.addWidget(self._result_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._btn_start  = QPushButton('Start')
        self._btn_cancel = QPushButton('Cancel')
        self._btn_cancel.setEnabled(False)
        self._btn_close  = QPushButton('Close')
        self._force_cb   = QCheckBox('Force (re-fetch all)')
        self._force_cb.setStyleSheet(f'color:{FG2};font-size:11px;')
        
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addSpacing(8)
        btn_row.addWidget(self._force_cb)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

        self._btn_start.clicked.connect(self._start)
        self._btn_cancel.clicked.connect(self._cancel)
        self._btn_close.clicked.connect(self._on_close)
        self._force = False   # set just before _make_worker() is called
        # Close button starts as 'Close' — nothing is running yet
        self._update_close_btn()

        # Adopt a worker still running in the background, if there is one
        self._check_and_restore_background()
        # Registered so the filter can be removed symmetrically on close/hide.
        # The dialog does not override eventFilter, so nothing is intercepted;
        # click-outside dismissal comes from _ModalOverlay instead.
        QApplication.instance().installEventFilter(self)

    def _on_lfm_text_changed(self, text: str):
        """Verify the key once it reaches full length; clear the border before."""
        if len(text) == 32:
            self._test_lastfm_key()
        else:
            self._lfm_edit.setStyleSheet(
                f'QLineEdit{{background:{BG3};color:{FG};border:1px solid {B2};'
                f'border-radius:4px;padding:0 6px;font-size:11px;}}'
                f'QLineEdit:focus{{border-color:{ACC};}}'
            )

    def _test_lastfm_key(self):
        """Try the key against Last.fm, colour the border, and save it if it works."""
        key = self._lfm_edit.text().strip()
        if not key:
            self._set_lfm_border(False)
            return
        result = [None]

        def _check():
            try:
                q = _urlparse.quote('Radiohead'); tk = _urlparse.quote('Creep')
                url = (f'https://ws.audioscrobbler.com/2.0/?method=track.getinfo'
                       f'&artist={q}&track={tk}&api_key={key}&format=json')
                req = _urlreq.Request(url, headers={'User-Agent': 'VoidPulse/2.0'})
                with _urlreq.urlopen(req, timeout=6) as r:
                    d = json.loads(r.read())
                result[0] = 'error' not in d and 'track' in d
            except Exception:
                result[0] = False

        thr = threading.Thread(target=_check, daemon=True)
        thr.start()

        def _poll():
            if thr.is_alive():
                QTimer.singleShot(150, _poll)
                return
            if not self.isVisible(): return
            ok = result[0]
            self._set_lfm_border(ok)
            if ok:
                _const_mod._lastfm_api_key = key

        QTimer.singleShot(150, _poll)

    def _set_lfm_border(self, ok: bool):
        color = '#44bb44' if ok else '#bb3333'
        self._lfm_edit.setStyleSheet(
            f'QLineEdit{{background:{BG3};color:{FG};border:2px solid {color};'
            f'border-radius:4px;padding:0 6px;font-size:11px;}}'
        )

    def _make_worker(self):
        raise NotImplementedError

    def _on_track_done(self, *_args):
        raise NotImplementedError

    def _update_close_btn(self):
        """Show 'Run in\nbackground' while running, 'Close' otherwise."""
        if self._running:
            self._btn_close.setText('Run in\nbackground')
        else:
            self._btn_close.setText('Close')

    def _check_and_restore_background(self):
        """Adopt a worker left running by an earlier instance of this dialog."""
        workers_list = _BaseFetchPopup._active_workers.get(self._popup_type, [])
        if workers_list:
            old_instance, old_worker, old_thread = workers_list[-1]
            self._thread = old_thread
            self._worker = old_worker
            self._running = True
            self._worker_id = old_instance._worker_id
            self._status_widget_key = old_instance._status_widget_key
            self._btn_start.setEnabled(False)
            self._btn_cancel.setEnabled(True)
            self._progress.setValue(old_instance._bg_progress)
            self._track_lbl.setText(f'[{old_instance._bg_progress}/{old_instance._bg_total}]  {old_instance._bg_track_name}')
            self._log.clear()
            for text, ok_flag in old_instance._bg_log_items:
                item = QListWidgetItem(text)
                item.setForeground(QColor('#55bb55') if ok_flag else QColor('#bb3333'))
                self._log.addItem(item)
            self._log.scrollToBottom()
            if old_instance._bg_result:
                self._result_lbl.setText(old_instance._bg_result)
            self._emit_status_update()
            # The dialog was hidden while the worker ran on
            self.show()
            # Detach the previous dialog first, or every worker signal arrives
            # twice and _on_finished runs on both instances.
            try: old_worker.progress.disconnect(old_instance._on_progress)
            except Exception: pass
            try: old_worker.track_done.disconnect(old_instance._on_track_done)
            except Exception: pass
            try: old_worker.finished.disconnect(old_instance._on_finished)
            except Exception: pass
            self._worker.progress.connect(self._on_progress)
            self._worker.track_done.connect(self._on_track_done)
            self._worker.finished.connect(self._on_finished)
            # Take over the registration too, so a later reopen restores from
            # this dialog's state rather than the old one's frozen copy.
            workers_list[-1] = (self, old_worker, old_thread)
            self._update_close_btn()

    # ── common implementation ────────────────────────────────────────────────

    def _log_add(self, text: str, ok: bool):
        item = QListWidgetItem(text)
        item.setForeground(QColor('#55bb55') if ok else QColor('#bb3333'))
        self._log.addItem(item)
        self._log.scrollToBottom()
        self._bg_log_items.append((text, ok))

    def _start(self):
        if self._running:
            return
        
        self._running = True
        self._force   = self._force_cb.isChecked()   # subclasses read self._force in _make_worker
        self._log.clear()
        self._progress.setValue(0)
        self._result_lbl.setText('')
        self._btn_start.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._update_close_btn()

        worker = self._make_worker()
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.track_done.connect(self._on_track_done)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(thread.quit)
        self._thread = thread
        self._worker = worker
        if self._worker_id is None:
            self._worker_id = id(worker)
        if self._status_widget_key is None:
            self._status_widget_key = f"_fetch_widget_{self._worker_id}"
        if self._popup_type not in _BaseFetchPopup._active_workers:
            _BaseFetchPopup._active_workers[self._popup_type] = []
        _BaseFetchPopup._active_workers[self._popup_type].append((self, worker, thread))
        thread.start()
        self._emit_status_update()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
        self._btn_cancel.setEnabled(False)
        self._track_lbl.setText('Cancelling…')

    def _really_close(self):
        """Actually close the dialog (bypassing the hide-guard in closeEvent)."""
        self._force_close = True
        self.reject()

    def _on_close(self):
        if self._running:
            # Hide only — the worker thread keeps going in the background
            QApplication.instance().removeEventFilter(self)
            self.hide()
        else:
            self._really_close()

    def closeEvent(self, e):
        QApplication.instance().removeEventFilter(self)
        if getattr(self, '_force_close', False) or not self._running:
            self._force_close = False
            e.accept()
        else:
            # A running worker survives the dialog: hide instead of closing
            self.hide()
            e.ignore()

    def _on_progress(self, current: int, total: int, name: str):
        if self._progress.maximum() != max(1, total):
            self._progress.setRange(0, max(1, total))
        self._progress.setValue(current)
        self._track_lbl.setText(f'[{current}/{total}]  {name}')
        self._bg_progress = current
        self._bg_total = total
        self._bg_track_name = name
        self._emit_status_update()

    def _on_finished(self, found: int, total: int):
        self._running = False
        workers_list = _BaseFetchPopup._active_workers.get(self._popup_type, [])
        for i, (inst, wk, th) in enumerate(workers_list):
            if inst is self or wk is self._worker:
                workers_list.pop(i)
                break
        if not workers_list:
            _BaseFetchPopup._active_workers.pop(self._popup_type, None)
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._track_lbl.setText('Done.')
        self._progress.setValue(total)
        result_msg = self._finished_msg(found, total)
        self._result_lbl.setText(result_msg)
        self._bg_result = result_msg
        # The thread already quit via worker.finished
        self._thread = None
        self._worker = None
        self._emit_status_clear()
        self._update_close_btn()

    def _emit_status_update(self):
        """Show this fetch's progress in the main window's status bar.

        Each worker owns one permanent label, so several fetches can report at once.
        """
        if not self._running or not self._worker_id:
            return
        if not (hasattr(self, '_bg_progress') and hasattr(self, '_bg_total')):
            return
        
        _TYPE_LABELS = {
            'CoverFetchPopup':  'Covers',
            'TagFetchPopup':    'Tags',
            'LyricsFetchPopup': 'Lyrics',
        }
        type_label = _TYPE_LABELS.get(self._popup_type, 'Fetch')
        
        msg = f"{type_label}: [{self._bg_progress}/{self._bg_total}] {self._bg_track_name}"
        win = self.parent()
        while win and not hasattr(win, '_status'):
            win = win.parent()
        if win and hasattr(win, '_status'):
            widget_key = self._status_widget_key or f"_fetch_widget_{self._worker_id}"
            old_lbl = getattr(win, widget_key, None)
            if old_lbl:
                old_lbl.setText(msg)
            else:
                lbl = QLabel(msg)
                lbl.setStyleSheet(f'color:{FG}; font-size:11px; padding: 0 8px;')
                win._status.addPermanentWidget(lbl, 0)
                setattr(win, widget_key, lbl)

    def _emit_status_clear(self):
        """Remove this fetch's status-bar label."""
        widget_key = self._status_widget_key or f"_fetch_widget_{self._worker_id}"
        
        win = self.parent()
        while win and not hasattr(win, '_status'):
            win = win.parent()
        if win:
            old_lbl = getattr(win, widget_key, None)
            if old_lbl:
                old_lbl.deleteLater()
                setattr(win, widget_key, None)

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Processed {found} out of {total}.' 


# ══════════════════════════════════════════════════════════════════════════════
#  Library Cover Fetch Popup
# ══════════════════════════════════════════════════════════════════════════════
class LibraryCoverFetchWorker(QObject):
    """Fetches covers for an entire track list sequentially in a worker thread.
    Emits raw bytes per track so the UI thread builds QPixmap objects."""
    progress    = pyqtSignal(int, int, str)   # current_index, total, track_name
    track_done  = pyqtSignal(str, bytes, bool) # filepath, raw_bytes, found_flag
    finished    = pyqtSignal(int, int)        # found_count, total_count

    def __init__(self, tracks: list, force: bool = False):
        super().__init__()
        self._tracks    = list(tracks)
        self._force     = force
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # Without force, tracks that already have a cover are skipped
        if self._force:
            needs_fetch = [t for t in self._tracks if t.filepath not in _cover_locked_set]
        else:
            needs_fetch = [t for t in self._tracks
                           if extract_cover_bytes(t.filepath) is None
                           and t.filepath not in _cover_locked_set]
        total = len(needs_fetch)
        found = 0
        done  = 0
        for t in needs_fetch:
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            done += 1
            self.progress.emit(done, total, name)
            data = fetch_cover_online(t.artist or '', t.title or '', t.album or '',
                                      stop=lambda: self._cancelled)
            if data:
                found += 1
                self.track_done.emit(t.filepath, data, True)
            else:
                self.track_done.emit(t.filepath, b'', False)
        self.finished.emit(found, total)

class CoverFetchPopup(_BaseFetchPopup):
    """Modal dialog that fetches covers for tracks missing a cover."""

    def __init__(self, tracks: list, table_pages: list, ctrlbar, parent=None):
        self._pages   = table_pages
        self._ctrlbar = ctrlbar
        # No scan here: reading every file's tags would freeze the UI on a large
        # library. The worker reports the real count through its progress signal.
        info = (f'Checking <b>{len(tracks)}</b> tracks for missing covers…')
        super().__init__(tracks, 'Fetch Covers', info, len(tracks), parent)
        self._needs = list(tracks)   # placeholder until the worker reports

    def _make_worker(self):
        return LibraryCoverFetchWorker(self._tracks, force=self._force)

    def set_tracks(self, tracks: list):
        self._tracks = list(tracks)
        self._needs  = list(tracks)   # placeholder until the worker reports
        self._progress.setRange(0, max(1, len(self._needs)))

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Found covers for {found} out of {total} tracks.'

    def _on_track_done(self, fp: str, data: bytes, found: bool):
        name = Path(fp).stem
        if not found:
            self._log_add(f'FAIL  {name}', False)
            return
        self._log_add(f'OK    {name}', True)
        src_pm = QPixmap()
        if not src_pm.loadFromData(data):
            return
        master_pm = _square_pixmap(src_pm, _COVER_MASTER_SIZE)
        _cover_cache[(fp, _COVER_MASTER_SIZE)] = master_pm
        try:
            master_dkey = _cover_disk_key(fp)
            master_disk_path = _COVER_DISK_DIR / f'{master_dkey}.jpg'
            if not (master_disk_path.exists() and not _cover_disk_is_stale(fp, master_disk_path)):
                _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
                master_pm.save(str(master_disk_path), 'JPEG', _COVER_JPEG_QUALITY)
                _cover_disk_write_mtime(fp, master_disk_path)
        except Exception:
            pass
        for size in (28, 64):
            _cover_cache[(fp, size)] = _square_pixmap(master_pm, size)
        _trim_cover_cache()
        threading.Thread(target=embed_cover_bytes, args=(fp, data), daemon=True).start()
        for page in self._pages:
            tracks = page.tracks if hasattr(page, 'tracks') else []
            for r, t in enumerate(tracks):
                if t.filepath == fp and r < page.table.rowCount():
                    item = page.table.item(r, 1)  # 1 = C_TIT
                    pm28 = _cover_cache.get((fp, 28))
                    if item and pm28:
                        item.setIcon(QIcon(pm28))
                    break
        if self._ctrlbar and self._ctrlbar._cur_track:
            if self._ctrlbar._cur_track.filepath == fp:
                pm64 = _cover_cache.get((fp, 64))
                if pm64 and self._ctrlbar._cover_lbl.isVisible():
                    self._ctrlbar._cover_lbl.setPixmap(pm64)

# ══════════════════════════════════════════════════════════════════════════════
#  Library Tag Fetch Worker + Popup
# ══════════════════════════════════════════════════════════════════════════════

class LibraryTagFetchWorker(QObject):
    """Fetches missing tags (title/artist/album) for library tracks sequentially.
    Progress is based only on tracks that are missing at least one tag."""
    progress   = pyqtSignal(int, int, str)        # current, total, track_name
    track_done = pyqtSignal(str, dict, bool)       # filepath, tags_dict, found_flag
    finished   = pyqtSignal(int, int)              # updated_count, total_needs

    def __init__(self, tracks: list, force: bool = False):
        super().__init__()
        self._tracks    = list(tracks)
        self._force     = force
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # Without force, only tracks missing at least one tag are looked up
        if self._force:
            needs = list(self._tracks)
        else:
            needs = [t for t in self._tracks
                     if not (t.title.strip() and t.artist.strip() and t.album.strip())]
        total   = len(needs)
        updated = 0
        for i, t in enumerate(needs):
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            self.progress.emit(i + 1, total, name)
            tags = lookup_tags_online(t.artist or '', t.title or Path(t.filepath).stem,
                                      stop=lambda: self._cancelled)
            if tags:
                result = {}
                if not t.title.strip()  and tags.get('title'):  result['title']  = tags['title']
                if not t.artist.strip() and tags.get('artist'): result['artist'] = tags['artist']
                if not t.album.strip()  and tags.get('album'):  result['album']  = tags['album']
                if result:
                    updated += 1
                    self.track_done.emit(t.filepath, result, True)
                else:
                    self.track_done.emit(t.filepath, {}, False)
            else:
                self.track_done.emit(t.filepath, {}, False)
        self.finished.emit(updated, total)

class TagFetchPopup(_BaseFetchPopup):
    """Modal dialog that looks up missing tags for library tracks."""

    tags_updated = pyqtSignal(str, dict)

    def __init__(self, tracks: list, parent=None):
        needs = [t for t in tracks
                 if not (t.title.strip() and t.artist.strip() and t.album.strip())]
        info = (f'<b>{len(needs)}</b> tracks have at least one missing tag '
                f'(out of {len(tracks)} total — tracks with all tags are skipped).')
        super().__init__(tracks, 'Fetch Missing Tags', info, len(needs), parent)
        self._needs = needs

    def _make_worker(self):
        return LibraryTagFetchWorker(self._tracks, force=self._force)

    def set_tracks(self, tracks: list):
        self._tracks = list(tracks)
        self._needs  = [t for t in tracks
                        if not (t.title.strip() and t.artist.strip() and t.album.strip())]
        self._progress.setRange(0, max(1, len(self._needs)))

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Updated tags for {found} out of {total} tracks.'

    def _on_track_done(self, fp: str, tags: dict, found: bool):
        name = Path(fp).stem
        if not found or not tags:
            self._log_add(f'FAIL  {name}', False)
            return
        filled = ', '.join(f'{k}={v}' for k, v in tags.items())
        self._log_add(f'OK    {name}  [{filled}]', True)
        threading.Thread(target=write_tags_to_file, args=(fp, tags), daemon=True).start()
        self.tags_updated.emit(fp, tags)



# ══════════════════════════════════════════════════════════════════════════════
#  Library Lyrics Fetch Worker + Popup
# ══════════════════════════════════════════════════════════════════════════════

class LibraryLyricsFetchWorker(QObject):
    """Fetches and embeds lyrics for library tracks that have no embedded lyrics.
    Runs sequentially in a worker thread; emits per-track results back to the UI."""
    progress   = pyqtSignal(int, int, str)        # current, total, track_name
    track_done = pyqtSignal(str, bool)             # filepath, found_flag
    finished   = pyqtSignal(int, int)              # found_count, total_needs

    def __init__(self, tracks: list, force: bool = False):
        super().__init__()
        self._tracks    = list(tracks)
        self._force     = force
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # Force also overwrites lyrics that are already embedded
        if self._force:
            needs = list(self._tracks)
        else:
            needs = [t for t in self._tracks if not any(_extract_embedded_lyrics(t.filepath))]
        total = len(needs)
        found = 0
        for i, t in enumerate(needs):
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            self.progress.emit(i + 1, total, name)
            artist = (t.artist or '').strip()
            title  = (t.title  or '').strip()
            album  = (t.album  or '').strip()
            # The same sources LyricsFetcher uses, in the same order
            synced, plain = None, None
            for src_fn in [
                lambda: _src_lrclib_exact(artist, title, album, t.duration),
                lambda: _src_lrclib_search(artist, title),
                lambda: _src_lyrics_ovh(artist, title),
            ]:
                if self._cancelled:
                    break
                try:
                    s, p = src_fn()
                    if s:
                        synced = s; break
                    if p and not plain:
                        plain = p
                except Exception:
                    pass
            if synced or plain:
                ok = embed_lyrics(t.filepath, synced, plain)
                self.track_done.emit(t.filepath, ok)
                if ok:
                    found += 1
            else:
                self.track_done.emit(t.filepath, False)
        self.finished.emit(found, total)

class LyricsFetchPopup(_BaseFetchPopup):
    """Modal dialog that fetches and embeds lyrics for library tracks."""

    def __init__(self, tracks: list, parent=None):
        # No scan here: reading every file's tags would freeze the UI on a large
        # library, and the worker computes the same list anyway.
        info = (f'Checking <b>{len(tracks)}</b> tracks for missing lyrics…')
        super().__init__(tracks, 'Fetch Lyrics', info, len(tracks), parent)
        self._needs = list(tracks)  # placeholder only; not used for worker logic

    def _make_worker(self):
        return LibraryLyricsFetchWorker(self._tracks, force=self._force)

    def set_tracks(self, tracks: list):
        self._tracks = list(tracks)
        self._needs  = list(tracks)  # placeholder; corrected once the worker reports real total
        self._progress.setRange(0, max(1, len(self._needs)))

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Embedded lyrics for {found} out of {total} tracks.'

    def _on_track_done(self, fp: str, found: bool):
        name = Path(fp).stem
        self._log_add(f'{"OK  " if found else "FAIL"} {name}', found)


# ══════════════════════════════════════════════════════════════════════════════
#  Library Loudness (ReplayGain) Fetch Worker + Popup
# ══════════════════════════════════════════════════════════════════════════════
# The batch counterpart to Player's per-track analysis on first play. Running it
# once writes a real REPLAYGAIN_TRACK_GAIN tag for the whole library, so no track
# waits for analysis later and the tags work in other players too.

class LibraryGainFetchWorker(QObject):
    """Analyzes loudness for library tracks sequentially and writes the
    result back as a REPLAYGAIN_TRACK_GAIN tag. Skips tracks that already
    have a tag or a cached analysis result unless force is set."""
    progress   = pyqtSignal(int, int, str)        # current, total, track_name
    track_done = pyqtSignal(str, bool)             # filepath, ok_flag
    finished   = pyqtSignal(int, int)              # analyzed_count, total_needs

    def __init__(self, tracks: list, force: bool = False):
        super().__init__()
        self._tracks    = list(tracks)
        self._force     = force
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._force:
            needs = list(self._tracks)
        else:
            needs = [t for t in self._tracks
                     if t.rg_track_gain_db == 0.0 and t.filepath not in _rg_gain_cache]
        total    = len(needs)
        analyzed = 0
        for i, t in enumerate(needs):
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            self.progress.emit(i + 1, total, name)
            gain = _run_rganalysis(t.filepath)
            if gain is not None:
                _rg_gain_cache[t.filepath] = gain   # usable by Player at once,
                write_replaygain_gain_tag(t.filepath, gain)   # and persisted for next launch
                analyzed += 1
                self.track_done.emit(t.filepath, True)
            else:
                self.track_done.emit(t.filepath, False)
        self.finished.emit(analyzed, total)


class GainFetchPopup(_BaseFetchPopup):
    """Modal dialog that batch-analyzes loudness for library tracks."""

    def __init__(self, tracks: list, parent=None):
        needs = [t for t in tracks if t.rg_track_gain_db == 0.0 and t.filepath not in _rg_gain_cache]
        info = (f'<b>{len(needs)}</b> tracks have no loudness tag or cached analysis '
                f'(out of {len(tracks)} total — already-analyzed tracks are skipped). '
                f'Each track is decoded once at full speed (not real-time), typically '
                f'well under a second per track.')
        super().__init__(tracks, 'Analyze Loudness (ReplayGain)', info, len(needs), parent)
        self._needs = needs

    def _make_worker(self):
        return LibraryGainFetchWorker(self._tracks, force=self._force)

    def set_tracks(self, tracks: list):
        self._tracks = list(tracks)
        self._needs  = [t for t in tracks if t.rg_track_gain_db == 0.0 and t.filepath not in _rg_gain_cache]
        self._progress.setRange(0, max(1, len(self._needs)))

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Analyzed loudness for {found} out of {total} tracks.'

    def _on_track_done(self, fp: str, ok: bool):
        name = Path(fp).stem
        self._log_add(f'{"OK  " if ok else "FAIL"} {name}', ok)
