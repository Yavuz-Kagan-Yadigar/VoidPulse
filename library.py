"""
VoidPulse — library management: filename sanitising, rename worker/popup,
scan_folder(), parse_m3u(), ScanThread, ConfigPlaylistLoader.
"""
from constants import *
from cover_art import (Track, _COVER_DISK_DIR, _cover_cache, _cover_disk_key,
                       read_metadata)
from constants import (ACC, B2, BG, BG3, FG, FG2, SUPPORTED_EXT,
                       _apply_scroller_properties, _sanitize_filename_part)
import re as _re
import concurrent.futures as _cf

# ══════════════════════════════════════════════════════════════════════════════
#  Library Rename Worker + Popup
# ══════════════════════════════════════════════════════════════════════════════

_PLACEHOLDER_RE = _re.compile(r'%[FATC]')


def _build_new_filename(pattern: str, track) -> str:
    """Build a new filename (without extension) from pattern + track metadata.

    Placeholders:
        %F  current filename stem
        %A  artist
        %T  title
        %C  album (Collection)
    All other characters (including punctuation, spaces, emoji, etc.) are kept
    as-is. Metadata values are sanitized so embedded '/' chars cannot break
    Path.with_name().

    A placeholder whose tag is missing expands to nothing, and the separator
    text that would have joined it to its neighbours (spaces, hyphens,
    underscores, dots) is dropped with it — so '%A - %T' on a track with no
    artist yields 'Title', not ' - Title'. Separators between two tags that are
    both present are preserved exactly as written.

    Returns an empty string when the pattern is empty or every tag is missing.
    """
    values = {
        '%F': _sanitize_filename_part(Path(track.filepath).stem),
        '%A': _sanitize_filename_part(track.artist or ''),
        '%T': _sanitize_filename_part(track.title  or ''),
        '%C': _sanitize_filename_part(track.album  or ''),
    }

    def _sep_only(s: str) -> bool:
        return not s.strip(' -_.')

    # Walk literal and placeholder pieces in turn, holding each literal back
    # until it is known to sit between two resolved values.
    out, pending, emitted = [], '', False
    pos = 0
    for m in _PLACEHOLDER_RE.finditer(pattern):
        pending += pattern[pos:m.start()]
        pos = m.end()
        val = values[m.group()]
        if not val:
            if _sep_only(pending):
                pending = ''      # dangling separator — drop it with the tag
            continue
        if emitted or not _sep_only(pending):
            out.append(pending)
        out.append(val)
        pending, emitted = '', True
    pending += pattern[pos:]
    if pending and not _sep_only(pending):
        out.append(pending)

    return ''.join(out).strip(' -_.')


def _validate_rename_pattern(pattern: str):
    """Return a list of invalid token strings found in *pattern*.

    A token starting with '%' but not in {%F,%A,%T,%C} is invalid.
    An empty pattern is also considered invalid (returns ['(empty)'] sentinel).
    """
    if not pattern.strip():
        return ['(empty)']
    bad = []
    for m in _re.finditer(r'%[^\s]?', pattern):
        tok = m.group()
        if tok not in ('%F', '%A', '%T', '%C'):
            bad.append(tok)
    return bad


_RENAME_TMP_SUFFIX = '.__vprename_tmp__'


def _recover_rename_temps(tracks: list) -> dict:
    """Scan *tracks* for files left in a tmp state by an interrupted rename.

    A file is in tmp state when its path ends with ``.__vprename_tmp__``.
    For every such file we restore it to its original name (i.e. strip the
    suffix) so the library stays consistent.  If the original name is already
    taken we keep the tmp name and leave it for the user to handle manually.

    Returns a mapping {tmp_path_str: restored_path_str} for every file that
    was successfully restored so callers can update their track lists.
    """
    recovered: dict = {}
    for t in tracks:
        p = Path(t.filepath)
        if not p.name.endswith(_RENAME_TMP_SUFFIX):
            continue
        original_name = p.name[: -len(_RENAME_TMP_SUFFIX)]
        original_path = p.with_name(original_name)
        if original_path.exists():
            print(f'[VoidPulse] rename-tmp recovery: cannot restore {p.name} '
                  f'(target already exists)')
            continue
        try:
            p.rename(original_path)
            recovered[str(p)] = str(original_path)
            print(f'[VoidPulse] rename-tmp recovery: {p.name} → {original_name}')
        except Exception as exc:
            print(f'[VoidPulse] rename-tmp recovery error for {p.name}: {exc}')
    return recovered


class LibraryRenameWorker(QObject):
    """Renames audio files on disk using a user-supplied pattern."""
    progress   = pyqtSignal(int, int, str)        # current, total, track_name
    track_done = pyqtSignal(str, str, bool)        # old_path, new_path, success
    finished   = pyqtSignal(int, int)              # renamed_count, total

    def __init__(self, tracks: list, pattern: str):
        super().__init__()
        self._tracks    = list(tracks)
        self._pattern   = pattern
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total   = len(self._tracks)
        renamed = 0
        _MAX_FILENAME_BYTES = 255
        _DEDUP_RESERVE = 12   # enough for "_(999).ext" worst case
        # One pass over the cache keys, so each rename below is a dict lookup
        _fp_to_sizes: dict = {}
        for (fp_key, sz_key) in _cover_cache.keys():
            _fp_to_sizes.setdefault(fp_key, []).append(sz_key)
        for i, t in enumerate(self._tracks):
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            self.progress.emit(i + 1, total, name)
            try:
                new_stem = _build_new_filename(self._pattern, t)
                if not new_stem.strip():
                    self.track_done.emit(t.filepath, '', False)
                    continue
                old_path = Path(t.filepath)
                ext = old_path.suffix  # e.g. '.m4a'

                # ── Enforce 255-byte filename limit (Linux/macOS/Windows all cap at 255) ──
                ext_bytes = ext.encode('utf-8')
                max_stem_bytes = _MAX_FILENAME_BYTES - len(ext_bytes) - _DEDUP_RESERVE
                stem_encoded = new_stem.encode('utf-8')
                if len(stem_encoded) > max_stem_bytes:
                    stem_encoded = stem_encoded[:max_stem_bytes]
                    # Back off to a UTF-8 character boundary
                    while stem_encoded and (stem_encoded[-1] & 0xC0) == 0x80:
                        stem_encoded = stem_encoded[:-1]
                    new_stem = stem_encoded.decode('utf-8', errors='ignore').rstrip()

                new_path = old_path.with_name(new_stem + ext)
                if old_path == new_path:
                    self.track_done.emit(str(old_path), str(new_path), True)
                    renamed += 1
                    continue
                # Never overwrite: append _(n) until the name is free
                counter = 1
                candidate = new_path
                try:
                    _exists = candidate.exists()
                except OSError:
                    _exists = False  # path too long or inaccessible — treat as free
                while _exists:
                    candidate = old_path.with_name(f'{new_stem}_({counter}){ext}')
                    counter += 1
                    try:
                        _exists = candidate.exists()
                    except OSError:
                        _exists = False
                # Via a temp name in the same directory: if the process dies
                # mid-way the file survives under one name or the other.
                tmp_path = old_path.with_name(old_path.name + '.__vprename_tmp__')
                old_path.rename(tmp_path)       # step 1: original → temp
                tmp_path.rename(candidate)      # step 2: temp → final
                renamed += 1
                # Move the cached cover to the new name so it survives the
                # rename. The disk key hashes the file's full path, so it has to
                # be recomputed from the new path — deriving it from the old key
                # would leave the file under a name nothing looks up again.
                old_fp_str = str(old_path)
                new_fp_str = str(candidate)
                try:
                    old_cover = _COVER_DISK_DIR / f'{_cover_disk_key(old_fp_str)}.jpg'
                    new_cover = _COVER_DISK_DIR / f'{_cover_disk_key(new_fp_str)}.jpg'
                    if old_cover != new_cover and old_cover.exists():
                        old_mtime = Path(str(old_cover) + '.mtime')
                        new_mtime = Path(str(new_cover) + '.mtime')
                        try:
                            old_cover.replace(new_cover)
                            if old_mtime.exists():
                                old_mtime.replace(new_mtime)
                        except Exception:
                            pass
                    for sz_key in _fp_to_sizes.pop(old_fp_str, ()):
                        pm = _cover_cache.pop((old_fp_str, sz_key), None)
                        if pm is not None:
                            _cover_cache[(new_fp_str, sz_key)] = pm
                except Exception:
                    pass
                self.track_done.emit(str(old_path), str(candidate), True)
            except Exception as exc:
                # A failure after step 1 leaves the file under the temp name
                tmp_path_maybe = Path(t.filepath).with_name(
                    Path(t.filepath).name + '.__vprename_tmp__')
                try:
                    _tmp_exists = tmp_path_maybe.exists()
                except OSError:
                    _tmp_exists = False
                if _tmp_exists:
                    try:
                        tmp_path_maybe.rename(Path(t.filepath))
                    except Exception:
                        pass
                self.track_done.emit(t.filepath, str(exc), False)
        self.finished.emit(renamed, total)


class RenamePopup(QDialog):
    """Modal dialog for batch-renaming the library with a filename pattern.

    Placeholders: %F=filename  %A=artist  %T=title  %C=album
    Any other characters (punctuation, spaces, emoji, etc.) are kept literally.

    After the dialog closes (finished OR cancelled), ``rename_map`` holds a dict
    of {old_path: new_path} for every file that was successfully renamed on disk.
    The caller (ControlBar._on_rename_btn) uses this to rescan and update M3Us.
    """

    _active_worker = None  # (instance, worker, thread) or None

    def __init__(self, tracks: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Rename Library Files')
        self.setMinimumWidth(660)
        self.setMinimumHeight(660)

        self._tracks   = list(tracks)
        self._thread   = None
        self._worker   = None
        self._running  = False
        # Filled in as the worker runs; readable once the dialog closes
        self.rename_map: dict = {}   # {old_path: new_path}
        # Mirrored so a reopened dialog can restore the running operation
        self._bg_progress = 0
        self._bg_total = len(tracks)
        self._bg_track_name = ''
        self._bg_log_items = []  # list of (text, ok_flag, old_name, new_name)
        self._bg_result = ''

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 18, 20, 18)

        title_lbl = QLabel('Rename Library Files')
        title_lbl.setStyleSheet(f'font-size:14px;font-weight:bold;color:{FG};')
        root.addWidget(title_lbl)

        desc = QLabel(
            'Enter a filename pattern. Any characters outside the placeholders are kept literally.<br>'
            '<b>%F</b> = current filename &nbsp; <b>%A</b> = artist &nbsp;'
            '<b>%T</b> = title &nbsp; <b>%C</b> = album'
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f'color:{FG2};font-size:12px;')
        root.addWidget(desc)

        pat_row = QHBoxLayout()
        pat_lbl = QLabel('Pattern:')
        pat_lbl.setStyleSheet(f'color:{FG};font-size:12px;')
        pat_lbl.setFixedWidth(60)
        self._pat_edit = QLineEdit()
        self._pat_edit.setPlaceholderText('e.g. %T-%C  or  %A - %T')
        self._ss_ok  = (f'QLineEdit {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
                        f' border-radius:5px; padding:4px 8px; font-size:13px; }}'
                        f'QLineEdit:focus {{ border-color:{ACC}; }}')
        self._ss_bad = (f'QLineEdit {{ background:{BG3}; color:#cc3333; border:1px solid #cc3333;'
                        f' border-radius:5px; padding:4px 8px; font-size:13px; }}')
        self._pat_edit.setStyleSheet(self._ss_ok)
        self._pat_edit.textChanged.connect(self._on_pattern_changed)
        pat_row.addWidget(pat_lbl)
        pat_row.addWidget(self._pat_edit, 1)
        root.addLayout(pat_row)

        self._valid_lbl = QLabel('')
        self._valid_lbl.setStyleSheet(f'color:{FG2};font-size:11px;')
        self._valid_lbl.setWordWrap(True)
        root.addWidget(self._valid_lbl)

        self._track_lbl = QLabel('')
        self._track_lbl.setStyleSheet(f'color:{FG};font-size:12px;')
        self._track_lbl.setWordWrap(True)
        root.addWidget(self._track_lbl)

        self._log = QListWidget()
        self._log.setFixedHeight(150)
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
        self._btn_start  = QPushButton('Start')
        self._btn_cancel = QPushButton('Cancel')
        self._btn_cancel.setEnabled(False)
        self._btn_close  = QPushButton('Background')
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

        self._btn_start.clicked.connect(self._start)
        self._btn_cancel.clicked.connect(self._cancel)
        self._btn_close.clicked.connect(self._on_close)

        self._on_pattern_changed('')
        self._update_close_btn()

        self._check_and_restore_background_rename()
        QApplication.instance().installEventFilter(self)

    # ── validation ────────────────────────────────────────────────────────────

    def eventFilter(self, obj, e: QEvent) -> bool:
        # geometry() is in parent coordinates, so compare in global ones
        if (self.isVisible() and
                e.type() == QEvent.Type.MouseButtonPress):
            try:
                gpt = e.globalPosition().toPoint()
                global_rect = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
                if not global_rect.contains(gpt):
                    self._on_close()
                    return True
            except Exception:
                pass
        return super().eventFilter(obj, e)

    def _update_close_btn(self):
        """Show 'Run in\nbackground' while running, 'Close' otherwise."""
        if self._running:
            self._btn_close.setText('Run in\nbackground')
        else:
            self._btn_close.setText('Close')

    def _on_pattern_changed(self, text: str):
        bad = _validate_rename_pattern(text)
        if bad:
            self._pat_edit.setStyleSheet(self._ss_bad)
            if bad == ['(empty)']:
                self._valid_lbl.setText('<span style="color:#cc3333;">Pattern cannot be empty.</span>')
            else:
                bads = ', '.join(bad)
                self._valid_lbl.setText(
                    f'<span style="color:#cc3333;">Invalid placeholders: {bads}. '
                    f'Only %F, %A, %T, %C are allowed.</span>')
            self._btn_start.setEnabled(False)
        else:
            self._pat_edit.setStyleSheet(self._ss_ok)
            if self._tracks:
                preview = _build_new_filename(text, self._tracks[0])
                ext = Path(self._tracks[0].filepath).suffix
                self._valid_lbl.setText(
                    f'<span style="color:{FG2};">Preview: <b>{preview}{ext}</b></span>')
            else:
                self._valid_lbl.setText('')
            self._btn_start.setEnabled(True)

    # ── worker ────────────────────────────────────────────────────────────────

    def _check_and_restore_background_rename(self):
        """Check if there's an existing rename worker running in background and auto-restore UI."""
        existing = RenamePopup._active_worker
        if existing:
            old_instance, old_worker, old_thread = existing
            self._thread = old_thread
            self._worker = old_worker
            self._running = True
            self._btn_start.setEnabled(False)
            self._btn_cancel.setEnabled(True)
            self._track_lbl.setText(f'[{old_instance._bg_progress}/{old_instance._bg_total}]  {old_instance._bg_track_name}')
            self._log.clear()
            for item_data in old_instance._bg_log_items:
                text, ok_flag, old_name, new_name = item_data
                if ok_flag:
                    item = QListWidgetItem(f'OK    {old_name}  →  {new_name}')
                    item.setForeground(QColor('#55bb55'))
                else:
                    item = QListWidgetItem(f'FAIL  {old_name}  ({new_name})')
                    item.setForeground(QColor('#bb3333'))
                self._log.addItem(item)
            self._log.scrollToBottom()
            if old_instance._bg_result:
                self._result_lbl.setText(old_instance._bg_result)
            self._emit_status_update_rename()
            self.show()
            # Detach the previous dialog first: leaving it connected would make
            # every worker signal arrive twice, duplicating log rows and running
            # _on_finished on both instances.
            try: old_worker.progress.disconnect(old_instance._on_progress)
            except Exception: pass
            try: old_worker.track_done.disconnect(old_instance._on_track_done)
            except Exception: pass
            try: old_worker.finished.disconnect(old_instance._on_finished)
            except Exception: pass
            self._worker.progress.connect(self._on_progress)
            self._worker.track_done.connect(self._on_track_done)
            self._worker.finished.connect(self._on_finished)
            # This dialog now owns the worker, so register it as the live one —
            # the next reopen must restore from state that is still being updated.
            RenamePopup._active_worker = (self, old_worker, old_thread)
            self._update_close_btn()

    def _emit_status_update_rename(self):
        """Emit rename progress status to main window status bar."""
        if self._running and hasattr(self, '_bg_progress') and hasattr(self, '_bg_total'):
            msg = f"Rename: [{self._bg_progress}/{self._bg_total}] {self._bg_track_name}"
            win = self.parent()
            while win and not hasattr(win, '_status'):
                win = win.parent()
            if win and hasattr(win, '_status'):
                old_lbl = getattr(win, '_fetch_rename_lbl', None)
                if old_lbl:
                    old_lbl.deleteLater()
                lbl = QLabel(msg)
                lbl.setStyleSheet(f'color:{FG}; font-size:11px; padding: 0 8px;')
                win._status.addPermanentWidget(lbl, 0)
                setattr(win, '_fetch_rename_lbl', lbl)

    def _clear_status_update_rename(self):
        """Clear rename status bar message when finished."""
        win = self.parent()
        while win and not hasattr(win, '_status'):
            win = win.parent()
        if win:
            old_lbl = getattr(win, '_fetch_rename_lbl', None)
            if old_lbl:
                old_lbl.deleteLater()
                setattr(win, '_fetch_rename_lbl', None)

    def _start(self):
        if self._running:
            return
        
        pattern = self._pat_edit.text()
        if _validate_rename_pattern(pattern):
            return
        self._running  = True
        self.rename_map = {}
        self._log.clear()
        self._result_lbl.setText('')
        self._track_lbl.setText('')
        self._btn_start.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._update_close_btn()

        worker = LibraryRenameWorker(self._tracks, pattern)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.track_done.connect(self._on_track_done)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(thread.quit)
        self._thread = thread
        self._worker = worker
        RenamePopup._active_worker = (self, worker, thread)
        thread.start()
        self._emit_status_update_rename()

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
            # Hide only — the rename worker keeps going in the background.
            # The filter must come off too, or the hidden dialog keeps eating
            # every mouse press in the application (see eventFilter above).
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
        self._track_lbl.setText(f'[{current}/{total}]  {name}')
        self._bg_progress = current
        self._bg_total = total
        self._bg_track_name = name

    def _on_track_done(self, old_path: str, new_path: str, ok: bool):
        old_name = Path(old_path).name
        if ok:
            new_name = Path(new_path).name if new_path else old_name
            item = QListWidgetItem(f'OK    {old_name}  →  {new_name}')
            item.setForeground(QColor('#55bb55'))
            if old_path != new_path:
                self.rename_map[old_path] = new_path
        else:
            item = QListWidgetItem(f'FAIL  {old_name}  ({new_path})')
            item.setForeground(QColor('#bb3333'))
        self._log.addItem(item)
        self._log.scrollToBottom()
        self._bg_log_items.append((item.text(), ok, old_name, new_path if ok else ''))

    def _on_finished(self, renamed: int, total: int):
        self._running = False
        RenamePopup._active_worker = None
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._track_lbl.setText('Done.')
        result_msg = f'{renamed} / {total} files renamed.'
        self._result_lbl.setText(result_msg)
        self._bg_result = result_msg
        self._thread = None
        self._worker = None
        self._clear_status_update_rename()
        self._update_close_btn()
        # Set by ControlBar._on_rename_btn to rescan the library afterwards
        cb = getattr(self, '_post_finish_cb', None)
        if cb:
            cb(renamed, total)



def scan_folder(folder: str) -> List[Track]:
    fps = []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for f in sorted(files):
            if Path(f).suffix.lower() in SUPPORTED_EXT:
                fps.append(os.path.join(root, f))
    if not fps:
        return []
    # 4 workers balances HDD seek latency against CPU saturation
    with _cf.ThreadPoolExecutor(max_workers=4) as pool:
        out = list(pool.map(read_metadata, fps))
    out.sort(key=lambda t: t.sort_key())
    return out

def parse_m3u(path: str) -> List[Track]:
    fps, base = [], os.path.dirname(path)
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#'): continue
                fp = line if os.path.isabs(line) else os.path.join(base, line)
                if os.path.isfile(fp) and Path(fp).suffix.lower() in SUPPORTED_EXT:
                    fps.append(fp)
    except Exception as e:
        print(f'M3U error: {e}')
    if not fps:
        return []
    with _cf.ThreadPoolExecutor(max_workers=4) as pool:
        out = list(pool.map(read_metadata, fps))
    out.sort(key=lambda t: t.sort_key())
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  Scanner thread
# ══════════════════════════════════════════════════════════════════════════════
class ScanThread(QThread):
    done     = pyqtSignal(list, str)
    progress = pyqtSignal(str)

    def __init__(self, path: str, is_m3u: bool = False):
        super().__init__()
        self._path, self._is_m3u = path, is_m3u

    def run(self):
        self.progress.emit(f'Scanning: {os.path.basename(self._path)} …')
        if self._is_m3u:
            tracks = parse_m3u(self._path); label = Path(self._path).stem
        else:
            tracks = scan_folder(self._path)
            label  = os.path.basename(self._path.rstrip('/\\'))
        self.done.emit(tracks, label)


class ConfigPlaylistLoader(QThread):
    """Non-blocking loader: reads track metadata for saved playlists in background.

    Emits playlist_ready once per playlist (in order) so MainWindow can add pages
    incrementally without blocking the event loop.  Uses a small thread pool to
    parallelise the per-track mutagen reads within each playlist.
    """
    playlist_ready = pyqtSignal(list, str)   # (tracks, label)
    all_done       = pyqtSignal()

    def __init__(self, playlist_data: list):
        """playlist_data: list of {'label': str, 'tracks': [filepath, ...]}"""
        super().__init__()
        self._playlist_data = playlist_data

    def run(self):
        for pd in self._playlist_data:
            label = pd.get('label', 'Playlist')
            fps   = [fp for fp in pd.get('tracks', []) if os.path.isfile(fp)]
            if not fps:
                continue
            with _cf.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(read_metadata, fps))
            tracks = sorted(results, key=lambda t: t.sort_key())
            if tracks:
                self.playlist_ready.emit(tracks, label)
        self.all_done.emit()

