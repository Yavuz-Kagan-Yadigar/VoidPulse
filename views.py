"""
VoidPulse — track browsing views.

SeekSlider and LongPressFilter are shared input helpers; _TouchHeaderView and
_CoverTitleDelegate support TrackTable (the touch-aware list view); GalleryView
is the virtual-scrolling card grid; PlaylistPage stacks the two views and owns
the track list they show.

The playlist sidebar lives in sidebar.py.
"""
from constants import *
from constants import ACC, ACCH, B2, BG, BG2, BG3, BG4, BORD, FG, FG2, SEL, _r, _apply_scroller_properties
from time import monotonic as _monotonic
from cover_art import get_cover_pixmap, draw_default_cover, _draw_cover_rounded, _ensure_async_cover_loader

COLS  = ['Length', 'Title', 'Artist', 'Album', 'Sample Rate', 'Bit Depth', 'Type']
C_LEN=0; C_TIT=1; C_ART=2; C_ALB=3; C_SR=4; C_BD=5; C_TYP=6
_HEADER_GRAB = 14   # px either side of a column boundary = 28px total touch target

# Drag payload for tracks moved between views (table → queue panel): UTF-8,
# one absolute filepath per line. It lives here rather than in queue_panel.py
# because TrackTable produces it and queue_panel imports this module.
QUEUE_MIME = 'application/x-voidpulse-tracks'


def tracks_mime_data(filepaths: list) -> QMimeData:
    """Build the drag payload for a set of tracks.

    text/uri-list rides along so a drag that lands outside VoidPulse — a file
    manager, another player — still carries something usable.
    """
    md = QMimeData()
    md.setData(QUEUE_MIME, '\n'.join(filepaths).encode('utf-8'))
    md.setUrls([QUrl.fromLocalFile(fp) for fp in filepaths])
    return md


def is_touch_pointer(e) -> bool:
    """True when a mouse event was synthesized from a touchscreen contact.

    Qt turns unconsumed touch events into mouse events, so every mouse handler
    on a touch device sees a press/move/release stream that looks exactly like
    a real one.  The pointing device behind it is still the touchscreen, which
    is the only way to tell the two apart.
    """
    dev = getattr(e, 'pointingDevice', None)
    if dev is None:
        return False
    d = dev()
    return d is not None and d.type() == QInputDevice.DeviceType.TouchScreen


class TouchDrag(QObject):
    """Finger-driven drag and drop, standing in for QDrag on a touchscreen.

    QDrag.exec() hands the gesture to the platform's drag manager, which follows
    the *mouse* pointer.  A touch that Qt synthesized mouse events from never
    moves that pointer, so the drag pixmap is painted wherever the cursor
    happens to sit and stays there for the whole gesture — the finger drags
    nothing.  This does the job by hand instead: a ghost that tracks the finger,
    plus drag/drop events posted to whatever widget lies under it.

    It reads the gesture from an **application-wide** event filter rather than
    from the widget the drag started on.  Which object Qt delivers a finger's
    events to changes halfway through one: QScroller claims the touch stream the
    moment the contact travels, and Qt stops synthesizing mouse events for a
    sequence it considers handled — so the starting widget can go completely
    silent mid-drag, leaving the ghost frozen.  Application filters run before
    every per-object filter, on events bound for widgets and windows alike, so
    that is the one vantage point which sees the whole gesture.

    The ghost is a child of the top-level window rather than a window of its
    own, because Wayland does not let a client place its own windows; that also
    confines drops to VoidPulse, which is where the only drop target — the queue
    panel — lives anyway.
    """

    GHOST_ALPHA = 0.85
    GHOST_MAX_W = 220
    # Nothing at all for this long means the gesture was lost (the compositor
    # took the contact, the window went away).  Rather than leave a ghost pinned
    # to the window, give up.
    WATCHDOG_MS = 6000

    def __init__(self, source: QWidget, mime: QMimeData, pixmap: QPixmap,
                 gpos: QPoint, on_finish=None):
        super().__init__(source)
        self._mime   = mime                 # kept alive for the whole gesture
        self._win    = source.window()
        self._target = None                 # widget currently under the finger
        self._ok     = False                # …and whether it took the payload
        self._start  = QPoint(gpos)
        self._last   = QPoint(gpos)
        self._moved  = False                # travelled past startDragDistance
        self._done   = False
        self._on_finish = on_finish         # (dropped, moved, gpos)
        pm = self._ghost_pixmap(pixmap)
        self._ghost = QLabel(self._win)
        # childAt() skips transparent children, so the ghost never hides the
        # drop target it is hovering over.
        self._ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._ghost.setPixmap(pm)
        dpr = pm.devicePixelRatio() or 1.0
        self._ghost.resize(int(pm.width() / dpr), int(pm.height() / dpr))
        self._hot = QPoint(self._ghost.width() // 2, self._ghost.height() // 2)
        self._ghost.show()
        self._ghost.raise_()
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(self.WATCHDOG_MS)
        self._watchdog.timeout.connect(lambda: self.finish(None))
        self.move(gpos)
        QApplication.instance().installEventFilter(self)

    # ── the gesture, read off the whole application ──────────────────────────

    def eventFilter(self, obj, e):
        if self._done:
            return False
        t = e.type()
        if t == QEvent.Type.TouchUpdate:
            pts = e.points()
            if pts:
                self.move(pts[0].globalPosition().toPoint())
            # Consumed for widgets so QScroller cannot pan the view out from
            # under the drag; left alone for the window, whose touch bookkeeping
            # has to stay consistent for the release to arrive at all.
            return isinstance(obj, QWidget)
        if t == QEvent.Type.TouchEnd:
            pts = e.points()
            self.finish(pts[0].globalPosition().toPoint() if pts else self._last)
            return isinstance(obj, QWidget)
        if t == QEvent.Type.TouchCancel:
            self.finish(None)
            return False
        if t == QEvent.Type.MouseMove:
            self.move(e.globalPosition().toPoint())
            return False
        if t == QEvent.Type.MouseButtonRelease:
            self.finish(e.globalPosition().toPoint())
            return False
        if t in (QEvent.Type.MouseButtonPress, QEvent.Type.TouchBegin):
            self.finish(None)         # a new gesture always wins
            return False
        return False

    @classmethod
    def _ghost_pixmap(cls, pm: QPixmap) -> QPixmap:
        """Scale the grabbed card/row down and make it semi-transparent."""
        dpr = pm.devicePixelRatio() or 1.0
        if pm.width() / dpr > cls.GHOST_MAX_W:
            pm = pm.scaledToWidth(int(cls.GHOST_MAX_W * dpr),
                                  Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
        out = QPixmap(pm.size())
        out.setDevicePixelRatio(dpr)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setOpacity(cls.GHOST_ALPHA)
        p.drawPixmap(0, 0, pm)
        p.end()
        return out

    def move(self, gpos: QPoint):
        """Follow the finger and keep the widget under it informed."""
        if self._done:
            return
        self._watchdog.start()
        self._last = QPoint(gpos)
        if (gpos - self._start).manhattanLength() >= QApplication.startDragDistance():
            self._moved = True
        self._ghost.move(self._win.mapFromGlobal(gpos) - self._hot)
        w = self._target_at(gpos)
        if w is not self._target:
            self._leave()
            self._target = w
            self._ok = self._send(w, QEvent.Type.DragEnter, gpos) if w is not None else False
        elif w is not None and self._ok:
            self._send(w, QEvent.Type.DragMove, gpos)

    def finish(self, gpos):
        """End the gesture: drop it if the finger travelled, else abandon it.

        `gpos` None abandons it outright (cancel, watchdog, a fresh gesture).
        """
        if self._done:
            return False
        if gpos is not None:
            self.move(gpos)            # bring the target under the release point
        self._done = True
        self._watchdog.stop()
        QApplication.instance().removeEventFilter(self)
        dropped = False
        if gpos is not None and self._moved:
            target, ok = self._target, self._ok
            self._target = None        # no DragLeave: the drop ends the gesture
            if target is not None and ok:
                dropped = self._send(target, QEvent.Type.Drop, gpos)
        else:
            self._leave()
        self._close()
        cb, self._on_finish = self._on_finish, None
        if cb is not None:
            cb(dropped, self._moved, gpos if gpos is not None else self._last)
        return dropped

    def _close(self):
        self._ghost.hide()
        self._ghost.setParent(None)
        self._ghost.deleteLater()
        self.deleteLater()

    def _leave(self):
        if self._target is not None and self._ok:
            QApplication.sendEvent(self._target, QDragLeaveEvent())
        self._target = None
        self._ok = False

    # ── plumbing ─────────────────────────────────────────────────────────────

    def _target_at(self, gpos: QPoint):
        """Deepest widget under the finger that accepts drops, if any."""
        pos = self._win.mapFromGlobal(gpos)
        if not self._win.rect().contains(pos):
            return None
        w = self._win.childAt(pos) or self._win
        while w is not None and not w.acceptDrops():
            w = w.parentWidget()
        return w

    def _send(self, w: QWidget, etype, gpos: QPoint) -> bool:
        """Post one hand-built drag event to `w`; True when it accepted it."""
        pos  = w.mapFromGlobal(gpos)
        act  = Qt.DropAction.CopyAction
        btn  = Qt.MouseButton.LeftButton
        mod  = Qt.KeyboardModifier.NoModifier
        if etype == QEvent.Type.DragEnter:
            ev = QDragEnterEvent(pos, act, self._mime, btn, mod)
        elif etype == QEvent.Type.DragMove:
            ev = QDragMoveEvent(pos, act, self._mime, btn, mod)
        else:
            ev = QDropEvent(QPointF(pos), act, self._mime, btn, mod)
        QApplication.sendEvent(w, ev)
        return ev.isAccepted()


class SeekSlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName('seek'); self.setRange(0, 1000)
        self.setMinimumHeight(26)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        self._pressed = False
        self._apply_seek_style(ACC, ACCH)

    def _seek_qss(self, acc: str, acch: str) -> str:
        r_grv = _r(2)   # groove 4 px tall → max 2 px
        r_hdl = _r(9)   # handle 18 px → max 9 px (circle)
        return f"""
            QSlider           {{ background: transparent; }}
            QSlider::groove:horizontal {{
                background: rgba(80,80,80,160); height: 4px; border-radius: {r_grv}px;
            }}
            QSlider::sub-page:horizontal {{
                background: {acc};
                border-top-left-radius: {r_grv}px; border-bottom-left-radius: {r_grv}px;
                border-top-right-radius: 0; border-bottom-right-radius: 0;
            }}
            QSlider::handle:horizontal {{
                background: {BG4}; border: 2px solid {acc};
                width: 18px; height: 18px; border-radius: {r_hdl}px; margin: -7px 0;
            }}
            QSlider::handle:horizontal:hover {{
                background: {BG4}; border: 3px solid {acch};
                width: 18px; height: 18px; border-radius: {r_hdl}px; margin: -7px 0;
            }}
            QSlider::handle:horizontal:pressed {{
                background: {BG4}; border: 3px solid {acch};
                width: 18px; height: 18px; border-radius: {r_hdl}px; margin: -7px 0;
            }}
        """

    def _apply_seek_style(self, acc: str, acch: str):
        self.setStyleSheet(self._seek_qss(acc, acch))

    def _val_at(self, x: float) -> int:
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), int(max(0.0, x)), self.width())

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.sliderPressed.emit()
            val = self._val_at(e.position().x())
            self.setValue(val)
            self.sliderMoved.emit(val)
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._pressed:
            val = self._val_at(e.position().x())
            self.setValue(val)
            self.sliderMoved.emit(val)
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            val = self._val_at(e.position().x())
            self.setValue(val)
            self.sliderReleased.emit()
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    def update_accent(self, acc: str, acch: str):
        self._apply_seek_style(acc, acch)

    def update_radius(self):
        """Rebuild QSS when RAD_PCT changes."""
        self._apply_seek_style(ACC, ACCH)

    def event(self, e: QEvent) -> bool:
        t = e.type()
        if t == QEvent.Type.TouchBegin:
            e.accept(); pts = e.points()
            if pts:
                self._pressed = True
                self.sliderPressed.emit()
                val = self._val_at(pts[0].position().x())
                self.setValue(val); self.sliderMoved.emit(val)
            return True
        if t == QEvent.Type.TouchUpdate:
            e.accept(); pts = e.points()
            if pts and self._pressed:
                val = self._val_at(pts[0].position().x())
                self.setValue(val); self.sliderMoved.emit(val)
            return True
        if t == QEvent.Type.TouchEnd:
            e.accept(); pts = e.points()
            if pts and self._pressed:
                val = self._val_at(pts[0].position().x())
                self.setValue(val)
            self._pressed = False
            self.sliderReleased.emit()
            return True
        return super().event(e)

# ══════════════════════════════════════════════════════════════════════════════

class DoubleTapTracker:
    """Recognises 'two clean taps on the same item' without Qt's double-click.

    QScroller takes the touch/press stream over as soon as a view can actually
    scroll, and from that point Qt no longer delivers the synthesized
    MouseButtonDblClick both library views used to start a track — so a library
    long enough to scroll could not be started by double-clicking while a short
    one could.  Pairing the taps here, from events the scroller cannot take
    away, makes activation independent of all that.

    A tap only counts when the pointer stayed put between press and release, so
    a flick that happens to end on a card never starts playback.
    """
    DRIFT_PX = 10

    def __init__(self):
        self._item  = -1          # item id of the pending first tap
        self._ms    = 0
        self._start = QPoint()    # press position of the tap in progress
        self._down  = False

    def press(self, pos: QPoint):
        self._start = QPoint(pos); self._down = True

    def cancel(self):
        """Pointer drifted / gesture taken over — the tap in progress is void."""
        self._down = False

    def release(self, pos: QPoint, item: int) -> bool:
        """Register a release; True when it completes a double-tap on `item`."""
        moved = (pos - self._start).manhattanLength() > self.DRIFT_PX
        down  = self._down
        self._down = False
        if item < 0 or not down or moved:
            self._item = -1
            return False
        now = QDateTime.currentMSecsSinceEpoch()
        if item == self._item and (now - self._ms) < QApplication.doubleClickInterval():
            self._item = -1
            return True
        self._item, self._ms = item, now
        return False


class LongPressFilter(QObject):
    """The whole pointer gesture set for a TrackTable viewport.

    Mouse: Qt's own machinery starts drags and double-clicks; this adds the
    long press.  Touch: everything is driven from the touch branches, because
    the mouse events Qt synthesizes from a contact are a second, misleading
    stream — a QDrag started from one follows the mouse cursor, which the finger
    never moved, so the drag pixmap would sit still in the wrong place.

      tap, tap            → play the row
      flick               → scroll (QScroller, untouched)
      hold                → the row lifts under the finger
      hold, then move     → drag it to the queue panel
      hold, then let go   → context menu

    A lifted row belongs to TouchDrag from then on: it reads the rest of the
    gesture off the application, which is the only place it stays visible.
    """
    triggered = pyqtSignal(int, QPoint)
    DELAY_MS = 550; DRIFT_PX = 10

    _MOUSE_TYPES = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                    QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick)

    def __init__(self, table):
        super().__init__(table)
        self._table = table; self._row = -1; self._gpos = QPoint(); self._start = QPoint()
        self._timer = QTimer(self); self._timer.setSingleShot(True)
        self._timer.setInterval(self.DELAY_MS); self._timer.timeout.connect(self._fire)
        self._taps = DoubleTapTracker()
        # Touch drag state
        self._tdrag       = None      # TouchDrag in progress, if any
        self._touch_mouse = False     # last mouse event came from a finger
        self._t_start_g   = QPoint()  # global position the contact started at
        self._t_row       = -1        # row under the finger
        self._lift = QTimer(self); self._lift.setSingleShot(True)
        self._lift.setInterval(self.DELAY_MS); self._lift.timeout.connect(self._on_lift)

    @property
    def touch_active(self) -> bool:
        """True while the pointer stream in progress belongs to a finger."""
        return self._touch_mouse or self._tdrag is not None

    def _drag_done(self, dropped: bool, moved: bool, gpos: QPoint, row: int):
        """A lifted row was let go: dropped, or put back and its menu shown.

        The menu runs its own event loop, so it is posted rather than opened
        here — this is called while the release is still being dispatched.
        """
        self._tdrag = None
        if not moved:
            QTimer.singleShot(0, lambda: self.triggered.emit(row, gpos))

    def eventFilter(self, obj, event):
        t = event.type()
        if t in self._MOUSE_TYPES:
            if is_touch_pointer(event):
                self._touch_mouse = True
                return False          # the touch branches already handled it
            self._touch_mouse = False
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            item = self._table.itemAt(event.pos())
            self._row = item.row() if item else -1
            self._taps.press(event.pos())
            if self._row >= 0:
                self._start = QPoint(event.pos())
                self._gpos  = self._table.viewport().mapToGlobal(event.pos())
                self._timer.start()
        elif t == QEvent.Type.MouseMove:
            if self._timer.isActive():
                d = event.pos() - self._start
                if abs(d.x())+abs(d.y()) > self.DRIFT_PX: self._timer.stop(); self._row = -1
        elif t == QEvent.Type.MouseButtonRelease:
            self._timer.stop()
            if event.button() == Qt.MouseButton.LeftButton:
                self._on_tap_release(event.pos())
        elif t == QEvent.Type.MouseButtonDblClick:
            self._timer.stop()
            self._taps.cancel()   # Qt's own event drives this one; see TrackTable
        # Touch: the press/release pair arrives without a synthesized double-click
        elif t == QEvent.Type.TouchBegin:
            pts = event.points()
            if pts:
                vp_pos = pts[0].position().toPoint()
                self._taps.press(vp_pos)
                self._t_start_g = pts[0].globalPosition().toPoint()
                item = self._table.itemAt(vp_pos)
                self._t_row = item.row() if item else -1
                if self._t_row >= 0:
                    self._lift.start()
        elif t == QEvent.Type.TouchUpdate:
            pts = event.points()
            if pts and self._lift.isActive() \
                    and self._t_moved(pts[0].globalPosition().toPoint()):
                # Travelled before the row was picked up → it's a scroll
                self._lift.stop(); self._t_row = -1
        elif t == QEvent.Type.TouchEnd:
            self._lift.stop()
            pts = event.points()
            self._t_row = -1
            if pts and self._tdrag is None:
                self._on_tap_release(pts[0].position().toPoint())
        elif t == QEvent.Type.TouchCancel:
            self._lift.stop(); self._taps.cancel(); self._t_row = -1
        return False

    def _on_tap_release(self, pos: QPoint):
        """Second clean tap on a row starts it, the way a double-click would."""
        item = self._table.itemAt(pos)
        if self._taps.release(pos, item.row() if item else -1):
            self._table.activate_row(item.row())

    def _fire(self):
        if self._row >= 0:
            self.triggered.emit(self._row, self._gpos); self._row = -1
            self._taps.cancel()   # a long press is not the first half of a tap pair

    # ── touch drag ───────────────────────────────────────────────────────────

    def _t_moved(self, gpos: QPoint) -> bool:
        return (gpos - self._t_start_g).manhattanLength() >= QApplication.startDragDistance()

    def _row_pixmap(self, row: int) -> QPixmap:
        """Grab of the row, full viewport width, for the drag ghost."""
        vp = self._table.viewport()
        r  = self._table.visualRect(self._table.model().index(row, C_TIT))
        if not r.isValid():
            return QPixmap()
        return vp.grab(QRect(0, r.y(), vp.width(), r.height()))

    def _on_lift(self):
        """Finger held still on a row — pick it up, ghost under the finger."""
        row = self._t_row
        if row < 0 or self._tdrag is not None:
            return
        item = self._table.item(row, C_TIT)
        fp   = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not fp:
            return
        self._taps.cancel()          # a pick-up is not half of a tap pair
        self._timer.stop()           # …nor a mouse long press
        vp = self._table.viewport()
        QScroller.scroller(vp).stop()
        self._tdrag = TouchDrag(
            vp, tracks_mime_data([fp]), self._row_pixmap(row), self._t_start_g,
            on_finish=lambda dropped, moved, gpos, row=row:
                self._drag_done(dropped, moved, gpos, row))

# ══════════════════════════════════════════════════════════════════════════════

class _TouchHeaderView(QHeaderView):
    """Horizontal header with a wider touch grab zone for column resize handles.

    Qt hard-codes the resize grip margin to ~4 px.  We intercept mouse/touch
    press+move+release and remap any pointer that lands within _HEADER_GRAB px
    of a section boundary to a resize drag, giving a 28 px wide invisible
    touch target centred on the visible 1 px divider line.
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._drag_col   = -1   # section being resized (-1 = none)
        self._drag_start = 0    # global x at drag start
        self._drag_orig  = 0    # section width at drag start
        self.setMouseTracking(True)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _section_at_boundary(self, local_x: int):
        """Return (section_index, boundary_x) if local_x is near a boundary, else (-1, 0)."""
        for col in range(self.count() - 1):   # last section has no right boundary to drag
            bx = self.sectionViewportPosition(col) + self.sectionSize(col)
            if abs(local_x - bx) <= _HEADER_GRAB:
                return col, bx
        return -1, 0

    def _update_cursor(self, local_x: int):
        col, _ = self._section_at_boundary(local_x)
        if col >= 0:
            self.setCursor(Qt.CursorShape.SplitHCursor)
        else:
            self.unsetCursor()

    # ── events ────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            col, _ = self._section_at_boundary(e.position().toPoint().x())
            if col >= 0 and self.sectionResizeMode(col) == QHeaderView.ResizeMode.Interactive:
                self._drag_col   = col
                self._drag_start = e.globalPosition().toPoint().x()
                self._drag_orig  = self.sectionSize(col)
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_col >= 0:
            delta = e.globalPosition().toPoint().x() - self._drag_start
            new_w = max(self.minimumSectionSize(), self._drag_orig + delta)
            self.resizeSection(self._drag_col, new_w)
            e.accept()
            return
        self._update_cursor(e.position().toPoint().x())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag_col >= 0 and e.button() == Qt.MouseButton.LeftButton:
            self._drag_col = -1
            self._update_cursor(e.position().toPoint().x())
            e.accept()
            return
        super().mouseReleaseEvent(e)


class _CoverTitleDelegate(QStyledItemDelegate):
    """Delegate for the Title column (C_TIT) in TrackTable.

    Bypasses Qt's QIcon rendering pipeline entirely (which applies style-based
    icon effects — KDE Breeze selected/active modes, dithered patterns — that
    corrupt accent-recoloured covers and produce random noise patterns).

    Instead, covers are drawn directly via _draw_cover_rounded() using the same
    get_cover_pixmap() call that GalleryView uses.  Both views share identical
    cover infrastructure; neither goes through QIcon.
    """

    def __init__(self, table: 'TrackTable'):
        super().__init__(table)
        self._table = table

    def paint(self, painter: QPainter, option: 'QStyleOptionViewItem', index) -> None:
        table = self._table

        # ── Background (selection, hover, etc.) via the item-view primitive ──
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else QApplication.style()
        opt.showDecorationSelected = True
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, opt.widget)

        r   = option.rect
        pad = 4

        # ── Cover ─────────────────────────────────────────────────────────────
        cover_sz = table._icon_sz if table._covers_on else 0
        if cover_sz > 0:
            fp = index.data(Qt.ItemDataRole.UserRole)
            pm = get_cover_pixmap(fp, cover_sz) if fp else None
            if pm is None:
                pm = draw_default_cover(cover_sz)
            if pm is not None:
                cy = r.top() + (r.height() - cover_sz) // 2
                _draw_cover_rounded(painter, pm,
                                    r.left() + pad, cy, cover_sz, _r(4))
            text_x = r.left() + pad + cover_sz + 6
        else:
            text_x = r.left() + pad

        # ── Title text ────────────────────────────────────────────────────────
        # setForeground() stores a QBrush, not a QColor
        fg_data = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(fg_data, QBrush):
            painter.setPen(fg_data.color())
        elif isinstance(fg_data, QColor):
            painter.setPen(fg_data)
        else:
            painter.setPen(QColor(FG))

        font_data = index.data(Qt.ItemDataRole.FontRole)
        painter.setFont(font_data if font_data is not None else option.font)

        title = index.data(Qt.ItemDataRole.DisplayRole) or ''
        text_w = r.right() - text_x - pad
        text_rect = QRect(text_x, r.top(), text_w, r.height())
        fm = painter.fontMetrics()
        elided = fm.elidedText(title, Qt.TextElideMode.ElideRight, max(0, text_w))
        painter.drawText(text_rect,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         elided)

    def sizeHint(self, option: 'QStyleOptionViewItem', index) -> QSize:
        return QSize(200, self._table._row_h)


class TrackTable(QTableWidget):
    row_activated  = pyqtSignal(int)
    ctx_requested  = pyqtSignal(int, QPoint)
    col_widths_changed = pyqtSignal(list)   # emitted after user resizes a column

    # Proportional column widths, summing to 1.0
    _DEFAULT_COL_RATIOS = [w / 928 for w in (72, 260, 180, 180, 92, 82, 62)]  # 928 = sum

    _POPULATE_CHUNK = 200   # rows filled synchronously on first pass / per deferred tick
    _GALLERY_CHUNK  = 80    # rows per deferred tick in GalleryView

    _CELL_ALIGN = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft



    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(COLS)); self.setHorizontalHeaderLabels(COLS)
        # Wider resize grab zone for touch
        th = _TouchHeaderView(self)
        self.setHorizontalHeader(th)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False); self.setAlternatingRowColors(False); self.setWordWrap(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        # Rows can be dragged into the queue panel. DragOnly: nothing is ever
        # dropped back into a library or playlist view, whose order is the
        # sort's to decide. A drag needs a press plus startDragDistance of
        # movement, so it cannot be confused with the tap pairing that starts a
        # track, and QScroller only claims touch events, not mouse ones.
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self._emit_ctx(pos))
        hh = self.horizontalHeader()
        hh.setSectionsMovable(False)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # Interactive plus no cascading: dragging a divider resizes only that column
        # and its right neighbour, leaving the rest alone.
        for col in range(len(COLS)):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        hh.setCascadingSectionResizes(False)
        hh.setMinimumSectionSize(30)
        hh.setStretchLastSection(False)
        # resizeEvent turns these ratios into pixel widths
        self._col_ratios = list(self._DEFAULT_COL_RATIOS)
        self._user_dragging = False   # True while user is actively dragging a column divider
        self._last_vp_w = -1          # last viewport width seen in resizeEvent
        self._row_h = 44   # tracks current desired row height; re-applied after setRowCount resets
        self.verticalHeader().setDefaultSectionSize(44)
        # The delegate draws covers the same way GalleryView does, avoiding Qt's
        # QIcon pipeline, whose style effects corrupt accent-recoloured pixmaps.
        self.setItemDelegateForColumn(C_TIT, _CoverTitleDelegate(self))
        QScroller.grabGesture(self.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        _apply_scroller_properties(self.viewport())
        # Installed after grabGesture() so this filter is called before the
        # scroller's — Qt runs event filters newest first.
        self._lp = LongPressFilter(self); self.viewport().installEventFilter(self._lp)
        self._lp.triggered.connect(self.ctx_requested)
        self._last_act_row = -1; self._last_act_ms = 0
        self.doubleClicked.connect(lambda idx: self.activate_row(idx.row()))
        # QScroller can swallow the viewport's double-click on some platforms, so a
        # filter catches MouseButtonDblClick directly as a fallback.
        self.viewport().installEventFilter(self)
        # Sorting is manual: _tracks follows the visual order, so row indices hold
        self._sort_col = -1; self._sort_asc = True
        hh.sectionClicked.connect(self._on_header_clicked)
        hh.sectionResized.connect(self._on_section_resized)
        self._covers_on = True
        self._col_resize_timer = QTimer(self)
        self._col_resize_timer.setSingleShot(True)
        self._col_resize_timer.setInterval(400)
        self._col_resize_timer.timeout.connect(self._emit_col_widths)
        self._fp_to_row: dict = {}   # filepath → row index, O(1) cover-loaded lookup
        _ensure_async_cover_loader().cover_loaded.connect(self._on_cover_loaded)

    @property
    def _icon_sz(self) -> int:
        """Cover icon size derived from row height — scales proportionally."""
        return max(16, self._row_h - 16)

    def activate_row(self, row: int):
        """Sole entry point for 'start this row'.

        Several paths can report the same gesture — Qt's doubleClicked signal,
        the viewport's MouseButtonDblClick filter and the tap pairing in
        LongPressFilter — so a repeat of the same row inside one double-click
        interval is treated as that one gesture and dropped.
        """
        if row < 0:
            return
        now = QDateTime.currentMSecsSinceEpoch()
        if row == self._last_act_row and (now - self._last_act_ms) < QApplication.doubleClickInterval():
            return
        self._last_act_row, self._last_act_ms = row, now
        self.row_activated.emit(row)

    def eventFilter(self, obj, event) -> bool:
        """Catch MouseButtonDblClick on the viewport — QScroller may suppress
        the normal doubleClicked signal on some platforms/Qt versions."""
        if (obj is self.viewport() and
                event.type() == QEvent.Type.MouseButtonDblClick and
                event.button() == Qt.MouseButton.LeftButton):
            item = self.itemAt(event.pos())
            if item is not None:
                self.activate_row(item.row())
                return True   # consumed — prevents duplicate from doubleClicked
        return super().eventFilter(obj, event)

    def startDrag(self, actions):
        """Mouse only.  Qt's drag pixmap is painted at the cursor, which a
        finger never moves; touch gets LongPressFilter's hand-driven TouchDrag,
        started by holding a row rather than by this.
        """
        if self._lp.touch_active:
            return
        super().startDrag(actions)

    def mimeData(self, items):
        """Payload for a drag out of the table: the filepaths of the picked rows.

        Selection is per-row, so `items` holds every column of each row; the
        filepath only lives on the Title cell (put there by _fill_row for the
        cover delegate), and rows are de-duplicated in visual order.
        """
        seen, paths = set(), []
        for it in sorted(items, key=lambda i: i.row()):
            if it.column() != C_TIT or it.row() in seen:
                continue
            fp = it.data(Qt.ItemDataRole.UserRole)
            if fp:
                seen.add(it.row()); paths.append(fp)
        return tracks_mime_data(paths)

    def _on_cover_loaded(self, fp: str, size: int):
        """Repaint the Title cell whose cover just arrived from the async loader."""
        if not self._covers_on:
            return
        r = self._fp_to_row.get(fp, -1)
        if r < 0:
            return
        # Only the title cell; the delegate picks the cover up on its next paint
        item = self.item(r, C_TIT)
        if item is not None:
            self.viewport().update(self.visualRect(self.indexFromItem(item)))

    def _on_section_resized(self, _logical, _old, _new):
        # Flags the drag so resizeEvent does not restore stored ratios over it
        self._user_dragging = True
        self._col_resize_timer.start()

    def _emit_col_widths(self):
        """Convert current pixel widths to ratios and emit."""
        total = sum(self.columnWidth(c) for c in range(len(COLS)))
        if total <= 0:
            return
        ratios = [self.columnWidth(c) / total for c in range(len(COLS))]
        self._col_ratios = ratios
        self._user_dragging = False   # drag finished, ratios committed
        self.col_widths_changed.emit(ratios)

    def _apply_ratios(self):
        """Apply stored ratios to actual pixel widths based on viewport width."""
        vp_w = self.viewport().width()
        if vp_w <= 0:
            return
        ratios = self._col_ratios
        if not ratios or len(ratios) != len(COLS):
            ratios = self._DEFAULT_COL_RATIOS
        # The last column absorbs the rounding remainder
        widths = [max(30, int(r * vp_w)) for r in ratios]
        diff = vp_w - sum(widths)
        widths[-1] = max(30, widths[-1] + diff)
        hh = self.horizontalHeader()
        hh.sectionResized.disconnect(self._on_section_resized)
        try:
            for col, w in enumerate(widths):
                self.setColumnWidth(col, w)
        finally:
            hh.sectionResized.connect(self._on_section_resized)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Never overwrite an in-progress drag, and ignore resizes that did not
        # change the viewport width.
        if self._user_dragging:
            return
        vp_w = self.viewport().width()
        if vp_w == self._last_vp_w:
            return
        self._last_vp_w = vp_w
        self._apply_ratios()

    def restore_col_widths(self, ratios: list):
        """Restore column ratios (list of floats, sum ≈ 1.0) and apply."""
        if not ratios or len(ratios) != len(COLS):
            return
        total = sum(ratios)
        if total <= 0:
            return
        self._col_ratios = [r / total for r in ratios]
        self._apply_ratios()

    def _emit_ctx(self, pos):
        item = self.itemAt(pos)
        if item: self.ctx_requested.emit(item.row(), self.viewport().mapToGlobal(pos))

    def populate(self, tracks, playing_idx=-1):
        self.setSortingEnabled(False)
        self.setRowCount(0); self.setRowCount(len(tracks))
        # setRowCount(0) resets defaultSectionSize to the style default
        self.verticalHeader().setDefaultSectionSize(self._row_h)
        # filepath → row, for cover callbacks
        self._fp_to_row = {t.filepath: r for r, t in enumerate(tracks)}
        CHUNK = self._POPULATE_CHUNK
        # First chunk synchronously, so rows appear at once
        end = min(CHUNK, len(tracks))
        for r in range(end):
            self._fill_row(r, tracks[r])
        self.set_playing_row(playing_idx)
        # The rest in deferred chunks, keeping the event loop responsive
        if len(tracks) > CHUNK:
            self._populate_deferred(tracks, playing_idx, CHUNK)

    def _populate_deferred(self, tracks, playing_idx, start):
        CHUNK = self._POPULATE_CHUNK
        def _chunk(s):
            end = min(s + CHUNK, len(tracks))
            for r in range(s, end):
                self._fill_row(r, tracks[r])
            if end < len(tracks):
                QTimer.singleShot(0, lambda s2=end: _chunk(s2))
        QTimer.singleShot(0, lambda: _chunk(start))

    def _on_header_clicked(self, col: int):
        """Sort the underlying PlaylistPage._tracks via the page reference."""
        page = self.parent()
        while page and not isinstance(page, PlaylistPage):
            page = page.parent()
        if page is None:
            return
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col; self._sort_asc = True
        def sort_key(t):
            if col == C_LEN: return t.duration
            if col == C_TIT: return t.title.lower()
            if col == C_ART: return t.artist.lower()
            if col == C_ALB: return t.album.lower()
            if col == C_SR:  return t.sample_rate
            if col == C_BD:  return t.bit_depth
            if col == C_TYP: return t.file_type.lower()
            return ''
        # The playing row moves with the sort
        cur_fp = None
        if 0 <= page.playing_idx < len(page.tracks):
            cur_fp = page.tracks[page.playing_idx].filepath
        sorted_tracks = sorted(page.tracks, key=sort_key, reverse=not self._sort_asc)
        new_playing = next((i for i, t in enumerate(sorted_tracks) if t.filepath == cur_fp), -1)
        page.set_tracks(sorted_tracks, new_playing)
        hh = self.horizontalHeader()
        hh.setSortIndicatorShown(True)
        hh.setSortIndicator(col, Qt.SortOrder.AscendingOrder if self._sort_asc
                                  else Qt.SortOrder.DescendingOrder)

    def _fill_row(self, row, t):
        for col, txt in enumerate([t.dur_str(), t.title, t.artist, t.album,
                                    t.sr_str(), t.bd_str(), t.file_type]):
            item = QTableWidgetItem(txt)
            if col == C_TIT:
                # The delegate reads the filepath from here and draws the cover
                # itself, so no QIcon is set.
                item.setData(Qt.ItemDataRole.UserRole, t.filepath)
            item.setTextAlignment(self._CELL_ALIGN); self.setItem(row, col, item)

    def set_covers_on(self, on: bool, tracks: list):
        self._covers_on = on
        # The delegate reads _covers_on on every paint, so a repaint is enough
        self.viewport().update()

    def set_playing_row(self, row):
        # Only the two affected rows
        prev = getattr(self, '_playing_row', -1)
        self._playing_row = row
        for r in (prev, row):
            if r < 0 or r >= self.rowCount():
                continue
            pl = (r == row)
            color = QColor(ACC if pl else FG)
            for c in range(self.columnCount()):
                item = self.item(r, c)
                if not item:
                    continue
                item.setForeground(color)
                f = item.font(); f.setBold(pl); item.setFont(f)

    def filter(self, query, tracks):
        q = query.lower().strip()
        for r in range(self.rowCount()):
            if r >= len(tracks): self.setRowHidden(r, True); continue
            t = tracks[r]
            ok = (not q or q in t.title.lower() or q in t.artist.lower()
                  or q in t.album.lower() or q in Path(t.filepath).name.lower())
            self.setRowHidden(r, not ok)

# ══════════════════════════════════════════════════════════════════════════════

class GalleryView(QWidget):
    """
    High-performance gallery: all cards drawn in a single paintEvent.
    Virtual scroll — only computes geometry, never creates per-card widgets.
    Cover pixmaps come from the existing get_cover_pixmap LRU cache.
    """
    row_activated = pyqtSignal(int)
    ctx_requested = pyqtSignal(int, QPoint)

    CARD_H_MIN = 80
    CARD_H_MAX = 220
    GAP        = 8
    MARGIN     = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks:       list  = []
        self._playing_idx:  int   = -1
        self._cover_on:     bool  = True
        self._card_h:       int   = 130
        self._filter_query: str   = ''
        self._vis_idx:      list  = []
        self._sort_col:     str   = ''
        self._sort_asc:     bool  = True
        self._layout_mode:  str   = 'gallery_z'  # 'gallery_z' | 'gallery_s'
        self._layout_ready: bool  = False         # True after first real viewport measure

        self._n_cols:       int   = 1
        self._card_h_act:   int   = 130
        self._card_w_act:   int   = 260
        self._total_h:      int   = 0
        self._cover_sz_cached: int = 118  # canonical cover_sz (snapped to 8px); set by _recompute_layout

        self._hovered_idx:  int   = -1
        self._press_pos:    QPoint = QPoint()
        self._press_vis_pos: int  = -1   # visual pos (into _vis_idx) at press
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.setInterval(600)
        self._long_press_timer.timeout.connect(self._on_long_press)

        # Set when populate() runs while hidden, replayed on show
        self._pending_populate: bool = False

        # track index → (title, artist, format), built during paint
        self._str_cache:    dict  = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        # ── Sort bar ─────────────────────────────────────────────────────────
        self._sort_bar = QWidget()
        sort_bar = self._sort_bar
        sort_bar.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        sort_bar.setFixedHeight(36)
        sbl = QHBoxLayout(sort_bar); sbl.setContentsMargins(12, 0, 12, 0); sbl.setSpacing(4)
        self._sort_lbl = QLabel('Sort by:')
        self._sort_lbl.setStyleSheet(f'color:{FG2}; font-size:11px; background:transparent;')
        sbl.addWidget(self._sort_lbl)
        self._sort_btns = {}
        _btn_ss = self._sort_btn_ss()
        for key, label in [('title','Title'),('artist','Artist'),
                            ('album','Album'),('duration','Length'),('type','Type')]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(26); btn.setMaximumHeight(28)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet(_btn_ss)
            btn.clicked.connect(lambda _, k=key: self._on_sort(k))
            self._sort_btns[key] = btn
            sbl.addWidget(btn)
        sbl.addStretch()
        self._count_lbl = QLabel('')
        self._count_lbl.setStyleSheet(f'color:{FG2}; font-size:11px; background:transparent;')
        sbl.addWidget(self._count_lbl)
        outer.addWidget(sort_bar)

        # ── Canvas inside QScrollArea ─────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setWidgetResizable(False)

        self._canvas = QWidget()
        self._canvas.setStyleSheet(f'background:{BG};')
        self._canvas.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._canvas.setMouseTracking(True)
        self._canvas.paintEvent        = self._canvas_paint
        self._canvas.mousePressEvent   = self._canvas_mouse_press
        self._canvas.mouseReleaseEvent = self._canvas_mouse_release
        self._canvas.mouseDoubleClickEvent = self._canvas_dblclick
        self._canvas.mouseMoveEvent    = self._canvas_mouse_move
        self._canvas.leaveEvent        = self._canvas_leave

        self._scroll.setWidget(self._canvas)
        outer.addWidget(self._scroll, 1)

        QScroller.grabGesture(self._scroll.viewport(),
                              QScroller.ScrollerGestureType.TouchGesture)
        sp = QScrollerProperties()
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor, 0.35)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.MaximumVelocity,    0.8)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.VerticalOvershootPolicy,
                           QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy,
                           QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        QScroller.scroller(self._scroll.viewport()).setScrollerProperties(sp)

        # Card activation. The canvas' own mouseDoubleClickEvent only arrives
        # while Qt is synthesizing mouse events from touch, which it stops doing
        # once the scroller claims the gesture — i.e. as soon as the gallery is
        # long enough to scroll. So the tap pair is tracked here as well, on the
        # viewport (installed after grabGesture so it is filtered first) for
        # touch and in the canvas handlers for the mouse.
        self._taps = DoubleTapTracker()
        self._last_act_ti = -1; self._last_act_ms = 0
        self._scroll.viewport().installEventFilter(self)

        # Touch drag: hold a card still to lift it, then drag it to the queue.
        # Moving before the timer fires leaves the gesture to QScroller, so a
        # flick still scrolls.
        self._tdrag     = None       # TouchDrag in progress, if any
        self._t_start_g = QPoint()   # global position of the touch that started it
        self._t_vis_pos = -1         # visual position of the card under the finger
        self._t_lift_timer = QTimer(self)
        self._t_lift_timer.setSingleShot(True)
        self._t_lift_timer.setInterval(LongPressFilter.DELAY_MS)
        self._t_lift_timer.timeout.connect(self._on_touch_lift)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(80)
        self._resize_timer.timeout.connect(self._on_resize_done)

        # Debounces the card-size slider
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.setInterval(60)
        self._scale_timer.timeout.connect(self._on_scale_done)
        self._scale_spinner_on = False

        _ensure_async_cover_loader().cover_loaded.connect(self._on_cover_loaded)

    # ── Public API ────────────────────────────────────────────────────────────

    def populate(self, tracks: list, playing_idx: int = -1):
        self._tracks      = list(tracks)
        self._playing_idx = playing_idx
        self._str_cache   = {}
        self._hovered_idx = -1
        # Geometry needs a real viewport width, so showEvent does it when hidden
        if self.isVisible():
            self._apply_filter_and_layout()
        else:
            self._pending_populate = True

    def set_playing(self, idx: int):
        old = self._playing_idx
        self._playing_idx = idx
        self._invalidate_track(old)
        self._invalidate_track(idx)

    def set_covers_on(self, on: bool):
        self._cover_on = on
        self._canvas.update()

    def set_card_height(self, h: int):
        h = max(self.CARD_H_MIN, min(self.CARD_H_MAX, h))
        if h == self._card_h: return
        self._card_h = h
        # Spinner now, relayout once the slider settles
        if not self._scale_spinner_on:
            self._scale_spinner_on = True
            self._canvas.update()
        self._scale_timer.start()

    def _on_scale_done(self):
        """Called ~60 ms after the last set_card_height — do the real recompute."""
        self._recompute_layout()
        self._scale_spinner_on = False
        self._canvas.update()

    def set_layout_mode(self, mode: str):
        """'gallery_z' = left-to-right row fill, 'gallery_s' = boustrophedon rows."""
        if mode == self._layout_mode: return
        self._layout_mode = mode
        self._canvas.update()

    def filter(self, query: str, tracks: list):
        self._filter_query = query.lower().strip()
        self._apply_filter_and_layout()

    # ── Geometry ──────────────────────────────────────────────────────────────

    def _recompute_layout(self):
        vp_w = self._scroll.viewport().width()
        if vp_w <= 0:
            return
        self._layout_ready = True
        gap = self.GAP; margin = self.MARGIN
        avail = vp_w - margin * 2

        # The slider sets the height; a 2:1 nominal width decides the column count,
        # then cards stretch to fill the row exactly.
        card_h_desired = max(self.CARD_H_MIN, min(self.CARD_H_MAX, self._card_h))
        card_w_nominal = card_h_desired * 2  # approximate 2:1 aspect

        n_cols = max(1, (avail + gap) // (card_w_nominal + gap))
        card_w_act = (avail - gap * (n_cols - 1)) // n_cols
        card_w_act = max(self.CARD_H_MIN * 2, card_w_act)

        # Height follows the real width's 2:1 ratio, capped by the slider
        card_h_act = min(card_h_desired, max(self.CARD_H_MIN, card_w_act // 2))

        self._n_cols     = n_cols
        self._card_h_act = card_h_act
        self._card_w_act = card_w_act

        # Snapped to 8 px so nearby card sizes share one cache key; otherwise every
        # pixel of resize or slider drag adds another scaled copy per track.
        _cover_pad = 4
        _raw_sz = card_h_act - _cover_pad * 2 - 4
        self._cover_sz_cached = max(8, (_raw_sz + 4) // 8 * 8)  # round to nearest 8px

        n_vis  = len(self._vis_idx)
        n_rows = max(1, (n_vis + n_cols - 1) // n_cols)
        self._total_h = margin * 2 + n_rows * card_h_act + max(0, n_rows - 1) * gap
        self._canvas.setFixedSize(vp_w, self._total_h)
        self._canvas.update()

    def _visual_col(self, row: int, logical_col: int) -> int:
        """Return the X-column index for a given (row, logical_col) pair.
        Z-mode: left-to-right every row.
        U-mode: left-to-right on even rows, right-to-left on odd rows (boustrophedon).
        """
        if self._layout_mode == 'gallery_s' and (row % 2 == 1):
            return self._n_cols - 1 - logical_col
        return logical_col

    def _card_rect(self, pos: int) -> QRect:
        margin = self.MARGIN; gap = self.GAP
        row = pos // self._n_cols
        logical_col = pos % self._n_cols
        col = self._visual_col(row, logical_col)
        x = margin + col * (self._card_w_act + gap)
        y = margin + row * (self._card_h_act + gap)
        return QRect(x, y, self._card_w_act, self._card_h_act)

    def _pos_at(self, pt: QPoint) -> int:
        """Visual position index into _vis_idx at canvas point, or -1."""
        margin = self.MARGIN; gap = self.GAP
        x = pt.x() - margin; y = pt.y() - margin
        if x < 0 or y < 0: return -1
        denom_w = self._card_w_act + gap
        denom_h = self._card_h_act + gap
        if denom_w <= 0 or denom_h <= 0: return -1
        col = x // denom_w
        row = y // denom_h
        if col >= self._n_cols: return -1
        if x - col * denom_w >= self._card_w_act: return -1
        if y - row * denom_h >= self._card_h_act: return -1
        # Odd rows run right-to-left in S mode, so invert the column
        logical_col = (self._n_cols - 1 - col
                       if self._layout_mode == 'gallery_s' and (row % 2 == 1)
                       else col)
        pos = row * self._n_cols + logical_col
        return pos if pos < len(self._vis_idx) else -1

    def _track_idx_at(self, pt: QPoint) -> int:
        pos = self._pos_at(pt)
        return self._vis_idx[pos] if pos >= 0 else -1

    def _invalidate_track(self, ti: int):
        if ti < 0: return
        # track index → visual position, built on demand per layout
        rmap = getattr(self, '_ti_to_vis_pos', None)
        if rmap is None:
            rmap = {track_idx: pos for pos, track_idx in enumerate(self._vis_idx)}
            self._ti_to_vis_pos = rmap
        pos = rmap.get(ti, -1)
        if pos < 0: return
        self._canvas.update(self._card_rect(pos))

    # ── Filter ────────────────────────────────────────────────────────────────

    def _apply_filter_and_layout(self):
        q = self._filter_query
        if q:
            self._vis_idx = [
                i for i, t in enumerate(self._tracks)
                if (q in t.title.lower() or q in t.artist.lower()
                    or q in t.album.lower()
                    or q in Path(t.filepath).name.lower())]
        else:
            self._vis_idx = list(range(len(self._tracks)))
        # Both lazy position maps belong to the old layout
        self._fp_to_vis_positions = None
        self._ti_to_vis_pos       = None
        self._recompute_layout()

    # ── Show / resize ─────────────────────────────────────────────────────────

    def showEvent(self, e):
        super().showEvent(e)
        if self._pending_populate:
            self._pending_populate = False
            self._apply_filter_and_layout()
            return
        # Now that the viewport has a real width, remeasure. _layout_ready holds
        # painting off until then, which avoids a one-frame single-column flash.
        self._layout_ready = False
        QTimer.singleShot(0, self._recompute_layout)

    # ── Painting ──────────────────────────────────────────────────────────────

    def _canvas_paint(self, event):
        p = QPainter(self._canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = event.rect()
        gap = self.GAP; margin = self.MARGIN

        # Nothing is drawn until the layout has seen a real viewport width
        if not self._layout_ready or self._card_h_act <= 0 or self._n_cols <= 0:
            p.fillRect(clip, QColor(BG)); p.end(); return
        p.fillRect(clip, QColor(BG))

        row_stride = self._card_h_act + gap
        first_row  = max(0, (clip.top()    - margin) // row_stride)
        last_row   =        (clip.bottom() - margin) // row_stride

        pen_border  = QPen(QColor(BORD), 1.2)
        pen_hover   = QPen(QColor(B2),  1.2)
        pen_playing = QPen(QColor(ACC), 1.5)
        brush_sel   = QBrush(QColor(SEL))
        brush_bg3   = QBrush(QColor(BG3))
        brush_bg2   = QBrush(QColor(BG2))
        col_fg      = QColor(FG)
        col_fg2     = QColor(FG2)
        col_acc     = QColor(ACC)

        h = self._card_h_act
        title_sz  = max(12, min(16, h // 9 + 1))
        artist_sz = max(10, min(13, h // 11 + 1))
        info_sz   = max(9,  min(12, h // 13 + 1))

        f_base   = p.font()
        f_title  = QFont(f_base); f_title.setPixelSize(title_sz);  f_title.setBold(True)
        f_artist = QFont(f_base); f_artist.setPixelSize(artist_sz)
        f_info   = QFont(f_base); f_info.setPixelSize(info_sz)
        fm_title  = QFontMetrics(f_title)
        fm_artist = QFontMetrics(f_artist)

        cover_pad = 4          # padding around cover image inside card
        cover_sz  = self._cover_sz_cached   # canonical (8px-snapped); set by _recompute_layout
        # Both radii scale with the element, so RAD_PCT=100 reaches a true pill
        cover_r   = _r(cover_sz // 2)
        card_r    = _r(h // 2)

        for row in range(first_row, last_row + 1):
            for logical_col in range(self._n_cols):
                pos = row * self._n_cols + logical_col
                if pos >= len(self._vis_idx): break
                ti = self._vis_idx[pos]
                t  = self._tracks[ti]
                col = self._visual_col(row, logical_col)
                x  = margin + col * (self._card_w_act + gap)
                y  = margin + row * row_stride
                rect = QRectF(x + 0.5, y + 0.5, self._card_w_act - 1, h - 1)

                playing = (ti == self._playing_idx)
                hovered = (ti == self._hovered_idx)
                if playing:
                    fill_brush = brush_sel;  pen = pen_playing
                elif hovered:
                    fill_brush = brush_bg3;  pen = pen_hover
                else:
                    fill_brush = brush_bg2;  pen = pen_border
                # Fill only: the cover sits close enough to the rounded edge to
                # paint over the outline, which is stroked again after it.
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fill_brush)
                p.drawRoundedRect(rect, card_r, card_r)

                # Fixed left pad, vertically centred: the cover does not always
                # fill the card's height.
                cover_x = x + cover_pad + 2
                cover_y = y + (h - cover_sz) // 2
                text_x  = x + 10
                if self._cover_on:
                    pm = get_cover_pixmap(t.filepath, cover_sz)
                    if pm is None:
                        pm = draw_default_cover(cover_sz)
                    if pm is not None:
                        _draw_cover_rounded(p, pm, cover_x, cover_y, cover_sz, cover_r)
                    text_x = cover_x + cover_sz + 8

                # Border last, over the cover
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rect, card_r, card_r)

                if ti not in self._str_cache:
                    sr_khz = f'{t.sample_rate/1000:.1f}kHz' if t.sample_rate else ''
                    bd_s   = f'{t.bit_depth}bit' if t.bit_depth else ''
                    parts  = [t.file_type.upper()]
                    if sr_khz: parts.append(sr_khz)
                    if bd_s:   parts.append(bd_s)
                    self._str_cache[ti] = (
                        t.title or Path(t.filepath).stem,
                        t.artist or '',
                        '  '.join(q2 for q2 in parts if q2))
                title_s, artist_s, fmt_s = self._str_cache[ti]

                text_w  = max(10, x + self._card_w_act - text_x - 8)
                show_fmt = h >= 60 and bool(fmt_s)
                block_h  = title_sz + 4 + artist_sz + (4 + info_sz if show_fmt else 0)
                ty       = y + (h - block_h) // 2

                p.setFont(f_title)
                p.setPen(col_acc if playing else col_fg)
                p.drawText(QRect(int(text_x), ty, text_w, title_sz + 2),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           fm_title.elidedText(title_s, Qt.TextElideMode.ElideRight, text_w))

                p.setFont(f_artist)
                p.setPen(col_fg2)
                p.drawText(QRect(int(text_x), ty + title_sz + 4, text_w, artist_sz + 2),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           fm_artist.elidedText(artist_s, Qt.TextElideMode.ElideRight, text_w))

                if show_fmt:
                    p.setFont(f_info)
                    p.drawText(QRect(int(text_x),
                                     ty + title_sz + 4 + artist_sz + 4,
                                     text_w, info_sz + 2),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                               fmt_s)

        # ── Scale-change spinner overlay ──────────────────────────────────────
        if getattr(self, '_scale_spinner_on', False):
            vp = self._scroll.viewport()
            vw = vp.width(); vh = vp.height()
            p.fillRect(0, self._scroll.verticalScrollBar().value(),
                       vw, vh, QColor(0, 0, 0, 90))
            cx = vw // 2
            cy = self._scroll.verticalScrollBar().value() + vh // 2
            r = 22
            angle = int((_monotonic() * 360)) % 360
            p.setPen(QPen(QColor(ACC), 3, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawArc(cx - r, cy - r, r * 2, r * 2,
                      angle * 16, 270 * 16)
            QTimer.singleShot(16, self._canvas.update)

        p.end()

    # ── Input ─────────────────────────────────────────────────────────────────

    def activate_track(self, ti: int):
        """Sole entry point for 'start this track' — see TrackTable.activate_row."""
        if ti < 0:
            return
        now = QDateTime.currentMSecsSinceEpoch()
        if ti == self._last_act_ti and (now - self._last_act_ms) < QApplication.doubleClickInterval():
            return
        self._last_act_ti, self._last_act_ms = ti, now
        self.row_activated.emit(ti)

    def eventFilter(self, obj, event) -> bool:
        """Own the whole touch gesture on the scroll viewport.

        Touch never reaches the canvas' mouse handlers once QScroller claims the
        stream, so tap pairing, the long press and the pick-up all live here:

          tap, tap            → play the track
          flick               → scroll (QScroller, untouched)
          hold                → the card lifts under the finger
          hold, then move     → drag it to the queue panel
          hold, then let go   → context menu

        Once a card is lifted the gesture belongs to TouchDrag, which reads it
        off the application rather than this viewport — see its docstring for
        why the viewport cannot be trusted to keep receiving it.
        """
        if obj is self._scroll.viewport():
            t = event.type()
            if t == QEvent.Type.TouchBegin:
                pts = event.points()
                if pts:
                    cpos = self._to_canvas(pts[0].position().toPoint())
                    self._taps.press(cpos)
                    self._t_start_g = pts[0].globalPosition().toPoint()
                    self._t_vis_pos = self._pos_at(cpos)
                    if self._t_vis_pos >= 0:
                        self._t_lift_timer.start()
            elif t == QEvent.Type.TouchUpdate:
                pts = event.points()
                if pts and self._t_lift_timer.isActive() \
                        and self._t_moved(pts[0].globalPosition().toPoint()):
                    # Travelled before the card was picked up → it's a scroll
                    self._t_lift_timer.stop()
                    self._t_vis_pos = -1
            elif t == QEvent.Type.TouchEnd:
                self._t_lift_timer.stop()
                pts = event.points()
                self._t_vis_pos = -1
                if pts and self._tdrag is None:
                    pos = self._to_canvas(pts[0].position().toPoint())
                    if self._taps.release(pos, self._track_idx_at(pos)):
                        self.activate_track(self._track_idx_at(pos))
            elif t == QEvent.Type.TouchCancel:
                self._t_lift_timer.stop()
                self._taps.cancel()
                self._t_vis_pos = -1
        return super().eventFilter(obj, event)

    def _t_moved(self, gpos: QPoint) -> bool:
        return (gpos - self._t_start_g).manhattanLength() >= QApplication.startDragDistance()

    def _on_touch_lift(self):
        """Finger held still on a card — pick it up, ghost under the finger."""
        pos = self._t_vis_pos
        if not (0 <= pos < len(self._vis_idx)) or self._tdrag is not None:
            return
        self._taps.cancel()          # a pick-up is not half of a tap pair
        QScroller.scroller(self._scroll.viewport()).stop()
        ti = self._vis_idx[pos]
        self._tdrag = TouchDrag(
            self._canvas, tracks_mime_data([self._tracks[ti].filepath]),
            self._card_pixmap(pos), self._t_start_g,
            on_finish=lambda dropped, moved, gpos, ti=ti:
                self._touch_drag_done(dropped, moved, gpos, ti))

    def _touch_drag_done(self, dropped: bool, moved: bool, gpos: QPoint, ti: int):
        """A lifted card was let go: dropped, or put back and its menu shown.

        The menu runs its own event loop, so it is posted rather than opened
        here — this is called while the release is still being dispatched.
        """
        self._tdrag = None
        if not moved:
            QTimer.singleShot(0, lambda: self.ctx_requested.emit(ti, gpos))

    def _to_canvas(self, vp_pos: QPoint) -> QPoint:
        """Scroll-viewport point → canvas point (the canvas slides under it)."""
        return self._canvas.mapFrom(self._scroll.viewport(), vp_pos)

    def _canvas_mouse_press(self, e: QMouseEvent):
        # Touch is driven entirely from eventFilter's touch branch; the mouse
        # events Qt synthesizes from it are a duplicate stream and would start a
        # second long press and a QDrag that cannot follow the finger.
        if is_touch_pointer(e):
            return
        self._long_press_timer.stop()
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos      = e.pos()
            self._press_vis_pos  = self._pos_at(e.pos())
            self._taps.press(e.pos())
            if self._press_vis_pos >= 0:
                self._long_press_timer.start()
        elif e.button() == Qt.MouseButton.RightButton:
            ti = self._track_idx_at(e.pos())
            if ti >= 0:
                self.ctx_requested.emit(ti, e.globalPosition().toPoint())

    def _canvas_mouse_release(self, e: QMouseEvent):
        if is_touch_pointer(e):
            return
        self._long_press_timer.stop()
        self._press_vis_pos = -1
        if e.button() == Qt.MouseButton.LeftButton:
            ti = self._track_idx_at(e.pos())
            if self._taps.release(e.pos(), ti):
                self.activate_track(ti)

    def _canvas_dblclick(self, e: QMouseEvent):
        if is_touch_pointer(e):
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._taps.cancel()   # this event already stands for the pair
            self.activate_track(self._track_idx_at(e.pos()))

    def _canvas_mouse_move(self, e: QMouseEvent):
        if is_touch_pointer(e):
            return
        if (e.pos() - self._press_pos).manhattanLength() > 8:
            self._long_press_timer.stop()
        if (e.buttons() & Qt.MouseButton.LeftButton) and self._press_vis_pos >= 0 \
                and (e.pos() - self._press_pos).manhattanLength() \
                    >= QApplication.startDragDistance():
            self._start_card_drag()
            return
        pos = self._pos_at(e.pos())
        ti  = self._vis_idx[pos] if pos >= 0 else -1
        if ti != self._hovered_idx:
            old = self._hovered_idx
            self._hovered_idx = ti
            self._invalidate_track(old)
            self._invalidate_track(ti)

    def _canvas_leave(self, e):
        old = self._hovered_idx
        self._hovered_idx = -1
        self._invalidate_track(old)

    def _card_pixmap(self, pos: int) -> QPixmap:
        """Grab of the card at visual `pos`, scaled down for a drag ghost."""
        rect = self._card_rect(pos)
        if not rect.isValid():
            return QPixmap()
        pm = self._canvas.grab(rect)
        if pm.width() > 200:
            pm = pm.scaledToWidth(200, Qt.TransformationMode.SmoothTransformation)
        return pm

    def _start_card_drag(self):
        """Drag the pressed card out of the gallery (→ the queue panel).

        The canvas is a single painted widget, not an item view, so there is no
        Qt drag machinery to enable — the drag is started by hand once the
        pointer has moved past startDragDistance with a card under the press.
        Touch takes _on_touch_lift instead: a QDrag pixmap is painted at the
        cursor, which a finger never moves.
        """
        pos = self._press_vis_pos
        self._long_press_timer.stop()
        self._taps.cancel()          # a drag is not half of a tap pair
        self._press_vis_pos = -1
        if not (0 <= pos < len(self._vis_idx)):
            return
        fp = self._tracks[self._vis_idx[pos]].filepath
        pm = self._card_pixmap(pos)
        drag = QDrag(self._canvas)
        drag.setMimeData(tracks_mime_data([fp]))
        if not pm.isNull():
            drag.setPixmap(pm)
            drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
        drag.exec(Qt.DropAction.CopyAction)
        # No mouse-release reaches the canvas after a drag, so drop the hover
        # highlight the pointer left behind.
        old, self._hovered_idx = self._hovered_idx, -1
        self._invalidate_track(old)

    def _on_long_press(self):
        pos = self._press_vis_pos
        if pos >= 0 and pos < len(self._vis_idx):
            ti = self._vis_idx[pos]
            self._taps.cancel()   # a long press is not the first half of a tap pair
            self.ctx_requested.emit(ti, self._canvas.mapToGlobal(self._press_pos))

    def _on_cover_loaded(self, fp: str, size: int):
        """Repaint any visible cards whose cover just arrived from the async loader."""
        # filepath → visual positions, built on demand and dropped per layout
        fp_map = getattr(self, '_fp_to_vis_positions', None)
        if fp_map is None:
            fp_map = {}
            for pos, ti in enumerate(self._vis_idx):
                key = self._tracks[ti].filepath
                fp_map.setdefault(key, []).append(pos)
            self._fp_to_vis_positions = fp_map
        for pos in fp_map.get(fp, []):
            self._canvas.update(self._card_rect(pos))

    # ── Sort ─────────────────────────────────────────────────────────────────

    def _sort_btn_ss(self) -> str:
        return (
            f'QPushButton {{ background:{BG3}; color:{FG2}; border:1px solid {B2};'
            # Radius from the button's own 28px height, for a full pill at 100%
            f' border-radius:{_r(14)}px; padding:2px 8px; font-size:11px;'
            f' min-height:26px; max-height:28px; }}'
            f'QPushButton:hover {{ border-color:{ACC}; color:{FG}; }}'
            f'QPushButton:checked {{ color:{ACC}; border-color:{ACC}; background:{BG3}; }}')

    def update_accent(self):
        """Refresh sort-bar button stylesheet after accent color change."""
        ss = self._sort_btn_ss()
        for btn in self._sort_btns.values():
            btn.setStyleSheet(ss)
        self._canvas.update()

    def refresh_theme(self):
        """Re-apply all palette globals after a dark/light switch."""
        self._sort_bar.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        self._sort_lbl.setStyleSheet(f'color:{FG2}; font-size:11px; background:transparent;')
        self._count_lbl.setStyleSheet(f'color:{FG2}; font-size:11px; background:transparent;')
        self._canvas.setStyleSheet(f'background:{BG};')
        self.update_accent()   # refresh sort buttons too
        self._canvas.update()

    def _on_sort(self, key: str):
        if self._sort_col == key:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = key; self._sort_asc = True
        for k, b in self._sort_btns.items():
            b.setChecked(k == self._sort_col)
            base = k.capitalize()
            b.setText(base + (' ▲' if self._sort_asc else ' ▼') if k == self._sort_col else base)

        def sort_fn(t):
            if key == 'title':    return t.title.lower()
            if key == 'artist':   return t.artist.lower()
            if key == 'album':    return t.album.lower()
            if key == 'duration': return t.duration
            if key == 'type':     return t.file_type.lower()
            return ''

        cur_fp = None
        if 0 <= self._playing_idx < len(self._tracks):
            cur_fp = self._tracks[self._playing_idx].filepath
        self._tracks = sorted(self._tracks, key=sort_fn, reverse=not self._sort_asc)
        self._str_cache = {}
        new_playing = next(
            (i for i, t in enumerate(self._tracks) if t.filepath == cur_fp), -1)
        self._playing_idx = new_playing
        self._apply_filter_and_layout()

        page = self.parent()
        while page and not isinstance(page, PlaylistPage):
            page = page.parent()
        if page:
            # Repopulate the table so classic view shows the same order.
            # set_tracks() would relayout the already-sorted gallery again.
            page._tracks = self._tracks  # already a fresh list from sorted(), no need to copy again
            page._playing_idx = new_playing
            page.table.populate(page._tracks, new_playing)

    # ── Resize ───────────────────────────────────────────────────────────────

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._resize_timer.start()

    def _on_resize_done(self):
        self._recompute_layout()

# ══════════════════════════════════════════════════════════════════════════════

class PlaylistPage(QWidget):
    play_track    = pyqtSignal(object, int)
    ctx_requested = pyqtSignal(object, int, QPoint)
    col_widths_changed = pyqtSignal(list)   # forwarded from TrackTable

    def __init__(self, tracks=None, label='', parent=None):
        super().__init__(parent)
        self._tracks = list(tracks or []); self._label = label; self._playing_idx = -1
        self._view_mode = 'classic'   # 'classic' | 'gallery_z' | 'gallery_s'

        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        self._stack = QStackedWidget()
        self.table = TrackTable(self)
        self.gallery = GalleryView(self)
        self._stack.addWidget(self.table)    # index 0 = classic
        self._stack.addWidget(self.gallery)  # index 1 = gallery
        lay.addWidget(self._stack)

        self.table.row_activated.connect(lambda r: self.play_track.emit(self, r))
        self.table.ctx_requested.connect(lambda r, pos: self.ctx_requested.emit(self, r, pos))
        self.table.col_widths_changed.connect(self.col_widths_changed)
        self.gallery.row_activated.connect(lambda r: self.play_track.emit(self, r))
        self.gallery.ctx_requested.connect(lambda r, pos: self.ctx_requested.emit(self, r, pos))

    @property
    def tracks(self):      return self._tracks
    @property
    def label(self):       return self._label
    @property
    def playing_idx(self): return self._playing_idx

    def set_tracks(self, tracks, playing_idx=-1):
        self._tracks = list(tracks); self._playing_idx = playing_idx
        self.table.populate(self._tracks, playing_idx)
        self.gallery.populate(self._tracks, playing_idx)
        self.set_track_count(len(self._tracks))

    def set_track_count(self, n: int):
        """Update the track-count label embedded in the sort bar."""
        self.gallery._count_lbl.setText(f'{n} tracks' if n != 1 else '1 track')

    def set_playing(self, idx):
        self._playing_idx = idx
        self.table.set_playing_row(idx)
        self.gallery.set_playing(idx)

    def set_covers_on(self, on: bool):
        self.table.set_covers_on(on, self._tracks)
        self.gallery.set_covers_on(on)

    def apply_filter(self, query):
        self.table.filter(query, self._tracks)
        self.gallery.filter(query, self._tracks)

    def set_view_mode(self, mode: str):
        """Switch between 'classic', 'gallery_z' and 'gallery_s'."""
        self._view_mode = mode
        if mode in ('gallery_z', 'gallery_s'):
            self.gallery.set_layout_mode(mode)
            self._stack.setCurrentIndex(1)
            # populate() defers itself while hidden, so this is cheap either way
            self.gallery.populate(self._tracks, self._playing_idx)
        else:
            self._stack.setCurrentIndex(0)

    def set_list_scale(self, row_h: int):
        """Set classic-view row height and scale cover icons proportionally."""
        self.table._row_h = row_h
        self.table.verticalHeader().setDefaultSectionSize(row_h)
        for r in range(self.table.rowCount()):
            self.table.setRowHeight(r, row_h)
        # The delegate derives the cover size from _row_h on every paint
        self.table.viewport().update()

    def set_gallery_scale(self, card_h: int):
        """Set gallery card height."""
        self.gallery.set_card_height(card_h)

    def refresh_theme(self):
        """Propagate theme refresh to child views."""
        self.gallery.refresh_theme()
        # The delegate re-reads get_cover_pixmap() on every paint, so one repaint
        # carries any accent or theme change into the list view.
        self.table.viewport().update()

    def set_label(self, new_label: str):
        """Update the playlist's display label (used by rename)."""
        self._label = new_label

# ══════════════════════════════════════════════════════════════════════════════
#  Sidebar
# ══════════════════════════════════════════════════════════════════════════════
