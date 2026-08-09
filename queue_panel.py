"""
VoidPulse — QueuePanel: the play-queue side panel, opened next to (or instead
of) the lyrics panel.

It holds an explicitly ordered list of tracks that playback follows. Tracks
arrive by dragging rows out of any track table or through the "Add to Queue"
context-menu entry; they are reordered by dragging inside the list or through
the per-item ▲/▼ actions, and removed with ✕.

The panel deliberately exposes the same small surface as views.PlaylistPage —
`tracks`, `label`, `playing_idx`, `set_tracks()`, `set_playing()` and a
`play_track(page, row)` signal — so MainWindow's existing playback machinery
(_play_from_page, _start_playback, _navigate_track, _advance) drives it without
special cases.
"""
from constants import *
from constants import _apply_scroller_properties, _r
import constants as _c

from cover_art import read_metadata
from views import DoubleTapTracker, QUEUE_MIME, is_touch_pointer, tracks_mime_data

_ROW_H = 46


def _paths_from_mime(md: QMimeData) -> list:
    """Extract playable local filepaths from a drop, ours or a file manager's."""
    if md.hasFormat(QUEUE_MIME):
        raw = bytes(md.data(QUEUE_MIME)).decode('utf-8', 'replace')
        return [line for line in raw.split('\n') if line]
    out = []
    for url in md.urls():
        fp = url.toLocalFile()
        if fp and Path(fp).suffix.lower() in SUPPORTED_EXT and os.path.isfile(fp):
            out.append(fp)
    return out


class _QueueList(QListWidget):
    """The list itself: internal drag-reorder plus drops from outside."""
    reordered      = pyqtSignal()
    paths_dropped  = pyqtSignal(list, int)   # (filepaths, insert row; -1 = append)
    row_activated  = pyqtSignal(int)
    ctx_requested  = pyqtSignal(int, QPoint)

    _LONG_PRESS_MS = 550
    _DRIFT_PX      = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('queue_list')
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        # DragDrop rather than InternalMove: the same view has to accept both a
        # reorder from itself and a fresh track list from a table or file manager.
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)
        QScroller.grabGesture(self.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        _apply_scroller_properties(self.viewport())
        # Installed after grabGesture() so it runs first — Qt calls filters newest
        # first, and the scroller would otherwise swallow the press stream.
        self.viewport().installEventFilter(self)

        self._taps = DoubleTapTracker()
        self._touch_mouse = False   # last press came from a finger, not a mouse
        self._lp_row   = -1
        self._lp_gpos  = QPoint()
        self._lp_start = QPoint()
        self._lp_timer = QTimer(self)
        self._lp_timer.setSingleShot(True)
        self._lp_timer.setInterval(self._LONG_PRESS_MS)
        self._lp_timer.timeout.connect(self._fire_long_press)

    # ── touch / mouse gestures ──────────────────────────────────────────────

    def _row_at(self, pos: QPoint) -> int:
        item = self.itemAt(pos)
        return self.row(item) if item is not None else -1

    def eventFilter(self, obj, event):
        if obj is not self.viewport():
            return super().eventFilter(obj, event)
        t = event.type()
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._touch_mouse = is_touch_pointer(event)
            pos = event.pos()
            self._taps.press(pos)
            self._lp_row = self._row_at(pos)
            if self._lp_row >= 0:
                self._lp_start = QPoint(pos)
                self._lp_gpos  = self.viewport().mapToGlobal(pos)
                self._lp_timer.start()
        elif t == QEvent.Type.MouseMove:
            if self._lp_timer.isActive():
                d = event.pos() - self._lp_start
                if abs(d.x()) + abs(d.y()) > self._DRIFT_PX:
                    self._lp_timer.stop(); self._lp_row = -1
        elif t == QEvent.Type.MouseButtonRelease:
            self._lp_timer.stop()
            if event.button() == Qt.MouseButton.LeftButton:
                self._on_tap_release(event.pos())
        elif t == QEvent.Type.MouseButtonDblClick:
            self._lp_timer.stop()
            self._taps.cancel()   # Qt's own double-click drives activation here
            row = self._row_at(event.pos())
            if row >= 0:
                self.row_activated.emit(row)
        elif t == QEvent.Type.TouchBegin:
            pts = event.points()
            if pts:
                self._taps.press(pts[0].position().toPoint())
        elif t == QEvent.Type.TouchEnd:
            pts = event.points()
            if pts:
                self._on_tap_release(pts[0].position().toPoint())
        elif t == QEvent.Type.TouchCancel:
            self._taps.cancel()
        return False   # never swallow: the view still needs its own handling

    def _on_tap_release(self, pos: QPoint):
        row = self._row_at(pos)
        if self._taps.release(pos, row) and row >= 0:
            self.row_activated.emit(row)

    def _fire_long_press(self):
        if self._lp_row >= 0:
            self.ctx_requested.emit(self._lp_row, self._lp_gpos)
            self._lp_row = -1
            self._taps.cancel()   # a long press is not half of a tap pair

    def contextMenuEvent(self, e):
        row = self._row_at(e.pos())
        if row >= 0:
            self.ctx_requested.emit(row, e.globalPos())

    # ── drag & drop ─────────────────────────────────────────────────────────

    def startDrag(self, actions):
        """Mouse only.  Qt's drag pixmap follows the mouse cursor, which a
        finger never moves, so a touch-started reorder drags a frozen ghost
        parked wherever the cursor was.  Touch reorders the queue through the
        row context menu instead.
        """
        if self._touch_mouse:
            return
        super().startDrag(actions)

    def mimeData(self, items):
        return tracks_mime_data(
            [it.data(Qt.ItemDataRole.UserRole) for it in items
             if it.data(Qt.ItemDataRole.UserRole)])

    def _accepts(self, e) -> bool:
        return e.source() is self or e.mimeData().hasFormat(QUEUE_MIME) \
            or e.mimeData().hasUrls()

    def dragEnterEvent(self, e):
        if self._accepts(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._accepts(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.source() is self:
            # Let the view move the item, then read the new visual order back.
            super().dropEvent(e)
            self.reordered.emit()
            return
        paths = _paths_from_mime(e.mimeData())
        if not paths:
            e.ignore(); return
        pos = e.position().toPoint()
        row = self.indexAt(pos).row()
        if row < 0:
            row = -1                      # dropped past the last row → append
        elif self._below_midpoint(pos, row):
            row += 1                      # dropped on a row's lower half → after it
        e.setDropAction(Qt.DropAction.CopyAction)
        e.accept()
        self.paths_dropped.emit(paths, row)

    def _below_midpoint(self, pos: QPoint, row: int) -> bool:
        rect = self.visualRect(self.model().index(row, 0))
        return pos.y() >= rect.center().y()


class QueuePanel(QWidget):
    """Side panel wrapper — the PlaylistPage-shaped object MainWindow talks to."""
    play_track    = pyqtSignal(object, int)   # (self, row) — matches PlaylistPage
    queue_changed = pyqtSignal()              # something to persist changed
    status_msg    = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks: list = []
        self._playing_idx  = -1
        self._label        = '__queue__'
        # Set by MainWindow: filepath → Track, using the already-scanned library
        # so a drop does not re-read tags that are known.
        self._resolver = None

        self.setObjectName('queue_panel')
        self.setMinimumWidth(180)
        self.setMaximumWidth(600)
        # The list handles drops over its own rows; the panel catches the rest
        # (the header, and the "Drag tracks here" hint that covers the empty
        # queue) so aiming anywhere inside the panel works.
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QWidget(); hdr.setFixedHeight(28)
        self._hdr_widget = hdr
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 0, 6, 0); hl.setSpacing(6)
        self._hdr_lbl = QLabel('Queue')
        self._count_lbl = QLabel('')
        self._btn_clear = QPushButton('Clear')
        self._btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_clear.setToolTip('Empty the queue')
        self._btn_clear.clicked.connect(self.clear_queue)
        hl.addWidget(self._hdr_lbl, 1)
        hl.addWidget(self._count_lbl)
        hl.addWidget(self._btn_clear)
        root.addWidget(hdr)

        self._list = _QueueList(self)
        self._list.row_activated.connect(lambda r: self.play_track.emit(self, r))
        self._list.ctx_requested.connect(self._show_item_menu)
        self._list.reordered.connect(self._on_reordered)
        self._list.paths_dropped.connect(self._on_paths_dropped)
        root.addWidget(self._list, 1)

        self._hint = QLabel('Drag tracks here, or use “Add to Queue”.')
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        self.refresh_theme()

    # ── drops that miss the list ────────────────────────────────────────────

    def dragEnterEvent(self, e):
        if _paths_from_mime(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if _paths_from_mime(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        paths = _paths_from_mime(e.mimeData())
        if not paths:
            e.ignore(); return
        e.setDropAction(Qt.DropAction.CopyAction)
        e.accept()
        self._on_paths_dropped(paths, -1)   # append: no row was aimed at

    # ── PlaylistPage-shaped surface ─────────────────────────────────────────

    @property
    def tracks(self):      return self._tracks

    @property
    def label(self):       return self._label

    @property
    def playing_idx(self): return self._playing_idx

    def set_tracks(self, tracks, playing_idx=-1):
        self._tracks = list(tracks)
        self._playing_idx = playing_idx if 0 <= playing_idx < len(self._tracks) else -1
        self._rebuild()

    def set_playing(self, idx):
        self._playing_idx = idx if 0 <= idx < len(self._tracks) else -1
        self._restyle_rows()
        if self._playing_idx >= 0:
            self._list.scrollToItem(self._list.item(self._playing_idx),
                                    QAbstractItemView.ScrollHint.EnsureVisible)

    def set_track_count(self, n: int):
        """No-op: the count label follows _tracks directly (PlaylistPage parity)."""

    # ── queue editing ───────────────────────────────────────────────────────

    def set_track_resolver(self, fn):
        """fn(filepath) -> Track | None, used to turn dropped paths into tracks."""
        self._resolver = fn

    def add_tracks(self, tracks, at: int = -1, quiet: bool = False):
        """Insert tracks at `at` (-1 appends). Duplicates are allowed: queueing
        the same track twice on purpose is a normal thing to want.

        `quiet` suppresses the status-bar note, for inserts the user did not ask
        for explicitly — playing a track drops it on top of the queue, and its
        own "▶ artist — title" message is the one worth reading."""
        tracks = [t for t in tracks if t is not None]
        if not tracks:
            return
        if at < 0 or at > len(self._tracks):
            at = len(self._tracks)
        # The playing row keeps its identity across an insert above it
        if 0 <= self._playing_idx and at <= self._playing_idx:
            self._playing_idx += len(tracks)
        self._tracks[at:at] = tracks
        self._rebuild()
        self.queue_changed.emit()
        if not quiet:
            n = len(tracks)
            self.status_msg.emit(f'{n} track{"" if n == 1 else "s"} added to the queue')

    def remove_row(self, row: int):
        if not (0 <= row < len(self._tracks)):
            return
        self._tracks.pop(row)
        if row == self._playing_idx:
            # The queue entry being played is gone; nothing is highlighted, but
            # playback continues — MainWindow re-syncs on the next transition.
            self._playing_idx = -1
        elif 0 <= self._playing_idx and row < self._playing_idx:
            self._playing_idx -= 1
        self._rebuild()
        self.queue_changed.emit()

    def move_row(self, row: int, delta: int):
        new = row + delta
        if not (0 <= row < len(self._tracks)) or not (0 <= new < len(self._tracks)):
            return
        self._tracks[row], self._tracks[new] = self._tracks[new], self._tracks[row]
        if   self._playing_idx == row: self._playing_idx = new
        elif self._playing_idx == new: self._playing_idx = row
        self._rebuild()
        self._list.setCurrentRow(new)
        self.queue_changed.emit()

    def clear_queue(self):
        if not self._tracks:
            return
        self._tracks = []
        self._playing_idx = -1
        self._rebuild()
        self.queue_changed.emit()
        self.status_msg.emit('Queue cleared')

    # ── internals ───────────────────────────────────────────────────────────

    def _on_reordered(self):
        """The view moved an item; rebuild _tracks from the visual order.

        Row order is read back through the filepaths stored on each item rather
        than tracked during the drag, so it stays correct however Qt chose to
        implement the move.
        """
        playing_fp = (self._tracks[self._playing_idx].filepath
                      if 0 <= self._playing_idx < len(self._tracks) else None)
        by_fp = {}
        for t in self._tracks:
            by_fp.setdefault(t.filepath, []).append(t)
        new_tracks = []
        for r in range(self._list.count()):
            fp = self._list.item(r).data(Qt.ItemDataRole.UserRole)
            bucket = by_fp.get(fp)
            if bucket:
                new_tracks.append(bucket.pop(0))
        if len(new_tracks) != len(self._tracks):
            # Something did not round-trip — leave the model alone and redraw
            # from it rather than silently dropping entries.
            self._rebuild()
            return
        self._tracks = new_tracks
        if playing_fp is not None:
            self._playing_idx = next(
                (i for i, t in enumerate(self._tracks) if t.filepath == playing_fp), -1)
        self._rebuild()
        self.queue_changed.emit()

    def _on_paths_dropped(self, paths: list, row: int):
        resolved = []
        for fp in paths:
            t = self._resolver(fp) if self._resolver else None
            if t is None:
                if not os.path.isfile(fp):
                    continue
                t = read_metadata(fp)
            resolved.append(t)
        self.add_tracks(resolved, row)

    def _rebuild(self):
        self._list.blockSignals(True)
        self._list.clear()
        for i, t in enumerate(self._tracks):
            title  = t.title or Path(t.filepath).name
            artist = t.artist or '—'
            item = QListWidgetItem(f'{i + 1}.  {title}\n     {artist} · {t.dur_str()}')
            item.setData(Qt.ItemDataRole.UserRole, t.filepath)
            item.setSizeHint(QSize(0, _ROW_H))
            item.setToolTip(t.filepath)
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._restyle_rows()
        n = len(self._tracks)
        self._count_lbl.setText(f'{n} track{"" if n == 1 else "s"}' if n else '')
        self._hint.setVisible(n == 0)
        self._btn_clear.setEnabled(n > 0)

    def _restyle_rows(self):
        for r in range(self._list.count()):
            item = self._list.item(r)
            playing = (r == self._playing_idx)
            item.setForeground(QColor(_c.ACC if playing else _c.FG))
            f = item.font(); f.setBold(playing); item.setFont(f)

    def _show_item_menu(self, row: int, gpos: QPoint):
        if not (0 <= row < len(self._tracks)):
            return
        menu = QMenu(self)
        menu.setStyleSheet(self._menu_ss())
        act_play = menu.addAction('▶  Play')
        menu.addSeparator()
        act_top  = menu.addAction('⤒  Move to Top')
        act_up   = menu.addAction('▲  Move Up')
        act_down = menu.addAction('▼  Move Down')
        act_bot  = menu.addAction('⤓  Move to Bottom')
        menu.addSeparator()
        act_rem  = menu.addAction('✕  Remove from Queue')
        act_clr  = menu.addAction('✕  Clear Queue')
        act_top.setEnabled(row > 0)
        act_up.setEnabled(row > 0)
        act_down.setEnabled(row < len(self._tracks) - 1)
        act_bot.setEnabled(row < len(self._tracks) - 1)
        chosen = menu.exec(gpos)
        if   chosen is act_play: self.play_track.emit(self, row)
        elif chosen is act_up:   self.move_row(row, -1)
        elif chosen is act_down: self.move_row(row, +1)
        elif chosen is act_top:  self._move_to(row, 0)
        elif chosen is act_bot:  self._move_to(row, len(self._tracks) - 1)
        elif chosen is act_rem:  self.remove_row(row)
        elif chosen is act_clr:  self.clear_queue()

    def _move_to(self, row: int, dest: int):
        if not (0 <= row < len(self._tracks)) or row == dest:
            return
        playing_fp = (self._tracks[self._playing_idx].filepath
                      if 0 <= self._playing_idx < len(self._tracks) else None)
        t = self._tracks.pop(row)
        self._tracks.insert(dest, t)
        if playing_fp is not None:
            self._playing_idx = next(
                (i for i, x in enumerate(self._tracks) if x.filepath == playing_fp), -1)
        self._rebuild()
        self._list.setCurrentRow(dest)
        self.queue_changed.emit()

    # ── theming ─────────────────────────────────────────────────────────────

    @staticmethod
    def _menu_ss() -> str:
        return (f'QMenu {{ background:{_c.BG3}; color:{_c.FG}; border:2px solid {_c.ACC};'
                f' border-radius:{_r(12)}px; padding:4px 0; font-size:12px; }}'
                f'QMenu::item {{ padding:6px 20px; }}'
                f'QMenu::item:selected {{ background:{_c.SEL}; color:{_c.ACC}; }}'
                f'QMenu::item:disabled {{ color:{_c.FG2}; }}'
                f'QMenu::separator {{ height:1px; background:{_c.B2}; margin:3px 8px; }}')

    def refresh_theme(self):
        """Re-apply palette globals after a dark/light, accent or radius change."""
        self._hdr_widget.setStyleSheet(
            f'background:{_c.BG2}; border-bottom:1px solid {_c.BORD};')
        self._hdr_lbl.setStyleSheet(
            f'color:{_c.FG2};font-size:11px;background:transparent;')
        self._count_lbl.setStyleSheet(
            f'color:{_c.FG2};font-size:10px;background:transparent;')
        self._btn_clear.setStyleSheet(
            f'QPushButton {{ background:transparent; border:none; color:{_c.ACC};'
            f' font-size:10px; padding:2px 6px; min-height:18px; max-height:20px;'
            f' border-radius:{_r(10)}px; }}'
            f'QPushButton:hover {{ background:{_c.BG4}; color:{_c.ACCH}; }}'
            f'QPushButton:disabled {{ color:{_c.FG2}; }}')
        self._hint.setStyleSheet(
            f'color:{_c.FG2};font-size:11px;background:transparent;padding:18px 14px;')
        self._list.setStyleSheet(
            f'QListWidget#queue_list {{ background:{_c.BG}; border:none;'
            f' outline:none; font-size:12px; padding:2px; }}'
            f'QListWidget#queue_list::item {{ color:{_c.FG}; padding:4px 10px;'
            f' border-radius:{_r(8)}px; }}'
            f'QListWidget#queue_list::item:hover {{ background:{_c.BG3}; }}'
            f'QListWidget#queue_list::item:selected {{ background:{_c.SEL}; }}'
            f'QScrollBar:vertical {{ background:{_c.BG}; width:3px; border-radius:1px; }}'
            f'QScrollBar::handle:vertical {{ background:{_c.B2}; border-radius:1px;'
            f' min-height:20px; }}'
            f'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{ height:0; }}')
        self._restyle_rows()

    def update_accent(self):
        self.refresh_theme()

# ══════════════════════════════════════════════════════════════════════════════
