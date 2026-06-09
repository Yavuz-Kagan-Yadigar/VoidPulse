"""
VoidPulse — library management: filename sanitising, rename worker/popup,
scan_folder(), parse_m3u(), ScanThread, ConfigPlaylistLoader.
"""
from constants import *
from cover_art import Track, _COVER_DISK_DIR, _cover_cache, read_metadata
from constants import ACC, B2, BG, BG3, FG, FG2, SUPPORTED_EXT
import re as _re
import concurrent.futures as _cf

# ══════════════════════════════════════════════════════════════════════════════
#  Library Rename Worker + Popup
# ══════════════════════════════════════════════════════════════════════════════

def _sanitize_filename_part(text: str) -> str:
    """Remove characters that are illegal in filenames on Linux/POSIX.

    Only '/' and null bytes are truly illegal on Linux, but we also strip
    leading/trailing dots and spaces to avoid edge cases with hidden files
    and Windows-incompatible names.
    """
    text = text.replace('/', '_').replace('\x00', '')
    return text.strip('. ')


def _build_new_filename(pattern: str, track) -> str:
    """Build a new filename (without extension) from pattern + track metadata.

    Placeholders:
        %F  current filename stem
        %A  artist
        %T  title
        %C  album (Collection)
    All other characters (including punctuation, spaces, emoji, etc.) are kept as-is.
    Metadata values are sanitized so embedded '/' chars cannot break Path.with_name().
    When a tag is missing its placeholder is replaced with an empty string and any
    surrounding separator characters (space, hyphen, underscore, dot) that would
    have connected it to adjacent tokens are collapsed away so the result stays clean.
    Returns empty string when the pattern is empty.
    """
    stem   = _sanitize_filename_part(Path(track.filepath).stem)
    result = pattern
    result = result.replace('%F', stem)
    result = result.replace('%A', _sanitize_filename_part(track.artist or ''))
    result = result.replace('%T', _sanitize_filename_part(track.title  or ''))
    result = result.replace('%C', _sanitize_filename_part(track.album  or ''))
    # Collapse sequences of separator-only characters left by empty placeholders,
    # e.g. " - " adjacent to another " - " or at the start/end of the string.
    result = _re.sub(r'[\s\-_\.]{2,}', lambda m: m.group(0)[0], result)
    result = result.strip(' -_.')
    return result


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
            # Cannot restore — original already exists; leave as-is.
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
        # Filename size limit constants (hoisted out of loop)
        _MAX_FILENAME_BYTES = 255
        _DEDUP_RESERVE = 12   # enough for "_(999).ext" worst case
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
                    # Truncate on byte boundary then decode losslessly.
                    stem_encoded = stem_encoded[:max_stem_bytes]
                    # Step back until we land on a valid UTF-8 boundary.
                    while stem_encoded and (stem_encoded[-1] & 0xC0) == 0x80:
                        stem_encoded = stem_encoded[:-1]
                    new_stem = stem_encoded.decode('utf-8', errors='ignore').rstrip()

                new_path = old_path.with_name(new_stem + ext)
                if old_path == new_path:
                    # Nothing to do
                    self.track_done.emit(str(old_path), str(new_path), True)
                    renamed += 1
                    continue
                # Avoid overwriting existing files — append _(n) suffix
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
                # Atomic rename via a temp name in the same directory.
                # If the process is killed mid-operation the file survives under
                # its original name or the temp name — never lost or truncated.
                tmp_path = old_path.with_name(old_path.name + '.__vprename_tmp__')
                old_path.rename(tmp_path)       # step 1: original → temp
                tmp_path.rename(candidate)      # step 2: temp → final
                renamed += 1
                # ── Rename cover disk-cache files to match new audio filename ──
                # Cover disk files are named <sanitized_stem>_<size>.jpg so
                # renaming the audio file means we rename the cover file(s) too.
                # This keeps the cache persistent across batch rename operations.
                try:
                    old_stem = _sanitize_filename_part(old_path.stem)
                    if len(old_stem) > 120: old_stem = old_stem[:120]
                    new_stem_san = _sanitize_filename_part(new_stem)
                    if len(new_stem_san) > 120: new_stem_san = new_stem_san[:120]
                    if old_stem != new_stem_san and _COVER_DISK_DIR.exists():
                        for cover_file in _COVER_DISK_DIR.glob(f'{old_stem}_*.jpg'):
                            # e.g. "old_stem_64.jpg" → "new_stem_64.jpg"
                            suffix_part = cover_file.stem[len(old_stem):]  # "_64"
                            new_cover = cover_file.with_name(f'{new_stem_san}{suffix_part}.jpg')
                            mtime_file = Path(str(cover_file) + '.mtime')
                            new_mtime  = Path(str(new_cover)  + '.mtime')
                            try:
                                cover_file.rename(new_cover)
                                if mtime_file.exists():
                                    mtime_file.rename(new_mtime)
                            except Exception:
                                pass
                    # Update in-memory cache keys
                    old_fp_str = str(old_path)
                    new_fp_str = str(candidate)
                    for (fp_key, sz_key) in list(_cover_cache.keys()):
                        if fp_key == old_fp_str:
                            pm = _cover_cache.pop((fp_key, sz_key), None)
                            if pm is not None:
                                _cover_cache[(new_fp_str, sz_key)] = pm
                except Exception:
                    pass
                self.track_done.emit(str(old_path), str(candidate), True)
            except Exception as exc:
                # If step 2 failed the file is still safe under tmp_path;
                # try to restore it to old_path so the library stays intact.
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

    # Class-level tracking of active rename worker
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
        # Collected as worker emits; available after exec() returns
        self.rename_map: dict = {}   # {old_path: new_path}
        # Store background state for restoration
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
        # Initialise close button to correct label (not running yet)
        self._update_close_btn()

        # Check if there's an existing rename worker running in background and auto-restore
        self._check_and_restore_background_rename()
        QApplication.instance().installEventFilter(self)

    # ── validation ────────────────────────────────────────────────────────────

    def eventFilter(self, obj, e: QEvent) -> bool:
        # Only intercept clicks while the dialog is actually visible.
        # self.geometry() is in parent-widget coords; convert our rect to global
        # screen coords before comparing with the event's global position.
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
            # Restore UI to show the existing running operation with full state
            self._thread = old_thread
            self._worker = old_worker
            self._running = True
            self._btn_start.setEnabled(False)
            self._btn_cancel.setEnabled(True)
            # Restore progress and track info from background state
            self._track_lbl.setText(f'[{old_instance._bg_progress}/{old_instance._bg_total}]  {old_instance._bg_track_name}')
            # Restore log items
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
            # Restore result label if present
            if old_instance._bg_result:
                self._result_lbl.setText(old_instance._bg_result)
            # Emit progress to main window status bar
            self._emit_status_update_rename()
            # Auto-show the dialog (it may have been hidden)
            self.show()
            # Connect signals to restore live updates
            self._worker.progress.connect(self._on_progress)
            self._worker.track_done.connect(self._on_track_done)
            self._worker.finished.connect(self._on_finished)
            self._update_close_btn()

    def _emit_status_update_rename(self):
        """Emit rename progress status to main window status bar."""
        if self._running and hasattr(self, '_bg_progress') and hasattr(self, '_bg_total'):
            msg = f"Rename: [{self._bg_progress}/{self._bg_total}] {self._bg_track_name}"
            # Find main window and update status bar
            win = self.parent()
            while win and not hasattr(win, '_status'):
                win = win.parent()
            if win and hasattr(win, '_status'):
                # Remove old widget if exists
                old_lbl = getattr(win, '_fetch_rename_lbl', None)
                if old_lbl:
                    old_lbl.deleteLater()
                # Create new permanent widget
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
        # Register this worker as active
        RenamePopup._active_worker = (self, worker, thread)
        thread.start()
        # Emit initial status update
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
            # Hide the dialog but keep the thread running in background.
            # Remove the application-wide event filter so the hidden dialog
            # does not continue swallowing all mouse events.
            QApplication.instance().removeEventFilter(self)
            self.hide()
        else:
            # Nothing is running — just close the dialog
            self._really_close()

    def closeEvent(self, e):
        if getattr(self, '_force_close', False) or not self._running:
            # Allow genuine close when not running.
            # Always remove the event filter on a real close.
            QApplication.instance().removeEventFilter(self)
            self._force_close = False
            e.accept()
        else:
            # Hide instead of closing — keeps thread alive.
            # Remove the event filter so the hidden dialog does not swallow mouse events.
            QApplication.instance().removeEventFilter(self)
            self.hide()
            e.ignore()

    def _on_progress(self, current: int, total: int, name: str):
        self._track_lbl.setText(f'[{current}/{total}]  {name}')
        # Store state for background restoration
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
        # Store log item for background restoration
        self._bg_log_items.append((item.text(), ok, old_name, new_path if ok else ''))

    def _on_finished(self, renamed: int, total: int):
        self._running = False
        # Clear active worker reference
        RenamePopup._active_worker = None
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._track_lbl.setText('Done.')
        result_msg = f'{renamed} / {total} files renamed.'
        self._result_lbl.setText(result_msg)
        # Store result for background restoration
        self._bg_result = result_msg
        # Clean up thread references
        self._thread = None
        self._worker = None
        # Clear status bar message
        self._clear_status_update_rename()
        self._update_close_btn()
        # Invoke post-finish callback if wired by caller (e.g. _on_rename_btn)
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
    # Parallel mutagen reads — 4 workers balances HDD seek latency vs CPU saturation.
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
            # Parallel mutagen reads — 4 workers is a good balance for HDDs and SSDs
            with _cf.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(read_metadata, fps))
            tracks = sorted(results, key=lambda t: t.sort_key())
            if tracks:
                self.playlist_ready.emit(tracks, label)
        self.all_done.emit()

# ══════════════════════════════════════════════════════════════════════════════
#  GStreamer Player with Parametric EQ (using audioiirfilter with coefficient calculation)
# ══════════════════════════════════════════════════════════════════════════════
