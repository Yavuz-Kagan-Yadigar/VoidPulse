"""
VoidPulse — LibraryPopup: the library-management actions (add folder,
import M3U, network share, new playlist, refresh, export, and the batch fetch
jobs that used to sit in the settings popup) as a compact popup
styled after the playlist context menu: BG3 fill, 2px accent border, radius
off the global corner-radius percentage, and menu-like text rows.
"""
from constants import *
from constants import _apply_scroller_properties, _r
import constants as _c   # live module ref: paintEvent reads the current palette


class LibraryPopup(QFrame):
    add_folder_req    = pyqtSignal()
    add_m3u_req       = pyqtSignal()
    network_share_req = pyqtSignal()
    new_playlist_req  = pyqtSignal()
    refresh_req       = pyqtSignal()
    export_m3u_req    = pyqtSignal()
    # Batch library jobs the settings popup used to carry; the handlers
    # stayed in ControlBar, where the fetch dialogs live.
    fetch_covers_req  = pyqtSignal()
    fetch_lyrics_req  = pyqtSignal()
    fetch_tags_req    = pyqtSignal()
    fetch_gain_req    = pyqtSignal()
    rename_batch_req  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('library_popup')
        # A child widget, not a top-level one, so move() works on Wayland
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(False)
        self._btns = []
        self._seps = []
        # Set when a click outside hid the popup, so the toggle that same
        # click fires does not immediately reopen it.
        self._hide_timestamp_ms = 0
        self._build_ui()
        self.hide()
        QApplication.instance().installEventFilter(self)

    def _build_ui(self):
        # Mirrors the QMenu stylesheet: padding 4px 0 item rows, thin B2
        # separators with a little side margin, everything content-sized.
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 8)
        v.setSpacing(2)
        self._vbox = v

        self._title = QLabel('LIBRARY MANAGEMENT')
        self._title.setObjectName('popup_title')
        self._title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self._title)

        self._div = QFrame(); self._div.setFixedHeight(1)
        self._div.setStyleSheet(f'background:{_c.B2}; margin:3px 8px;')
        self._seps.append(self._div)
        v.addWidget(self._div)

        # The rows live in a scroll body. Folded the fetches in, the menu is
        # tall enough that a short window cannot fit it above the button, and
        # show_above() then trims the popup - which would clip the last rows
        # off the frame. Scrolled, it stays whole at any window height.
        self._inner = QWidget()
        self._inner.setStyleSheet('background:transparent;')
        il = QVBoxLayout(self._inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(2)
        self._inner_layout = il
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet('background:transparent; border:none;')
        QScroller.grabGesture(self._scroll.viewport(),
                                QScroller.ScrollerGestureType.TouchGesture)
        _apply_scroller_properties(self._scroll.viewport())
        self._scroll.setWidget(self._inner)
        v.addWidget(self._scroll, 1)

        specs = [
            ('+  Add Folder', 'Add a folder to the library', 'add_folder_req'),
            ('+  Import M3U / M3U8', 'Import a playlist file', 'add_m3u_req'),
            ('⇄  Network Share…', 'Connect a Samba/SMB, FTP, FTPS or SFTP share'
             ' and add it to the library', 'network_share_req'),
            ('+ Create New Playlist', 'Create an empty playlist and save as'
             ' M3U8', 'new_playlist_req'),
            ('↺  Refresh Library', 'Rescan all saved folders', 'refresh_req'),
            ('↑  Export as M3U8', 'Export current playlist to an M3U8 file',
             'export_m3u_req'),
            ('⇩  Fetch Covers', 'Fetch cover art for every track in the library',
             'fetch_covers_req'),
            ('⇩  Fetch Lyrics', 'Fetch lyrics for every track in the library',
             'fetch_lyrics_req'),
            ('⇩  Fetch Tags', 'Fetch tags for every track in the library',
             'fetch_tags_req'),
            ('⇩  Fetch Gain', 'Measure ReplayGain for every track in the library',
             'fetch_gain_req'),
            ('✎  Rename…', 'Batch-rename the library files from a pattern',
             'rename_batch_req'),
        ]
        for pos, (text, tip, sig) in enumerate(specs):
            if pos in (3, 6, 10):   # add | playlist ops | fetches | rename
                sep = QFrame(); sep.setFixedHeight(1)
                sep.setStyleSheet(f'background:{_c.B2}; margin:3px 8px;')
                self._seps.append(sep)
                il.addWidget(sep)
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            # Hidden first, then relayed: a handler that opens a modal
            # fetch dialog would otherwise find this menu still raised
            # over the window while its dialog runs.
            btn.clicked.connect(lambda *_: self.hide())
            btn.clicked.connect(getattr(self, sig).emit)
            self._btns.append(btn)
            il.addWidget(btn)

        self.setMinimumWidth(206)
        self._apply_item_style()

    def _item_ss(self) -> str:
        r = _r(4)
        return (
            f'QPushButton {{ background:transparent; color:{FG}; border:none;'
            f' border-radius:{r}px; text-align:left; padding:3px 14px;'
            f' font-size:12px; min-height:26px; max-height:26px; }}'
            f'QPushButton:hover {{ background:{SEL}; color:{ACC}; }}'
            f'QPushButton:pressed {{ background:{SEL}; color:{ACC}; }}')

    def _apply_item_style(self):
        ss = self._item_ss()
        for btn in self._btns:
            btn.setStyleSheet(ss)

    def refresh_theme(self):
        # Menu separator uses B2, not BORD, matching QMenu::separator.
        for sep in self._seps:
            sep.setStyleSheet(f'background:{_c.B2}; margin:3px 8px;')
        self._apply_item_style()
        # paintEvent reads _c.BG3/_c.ACC live, so a repaint is all the frame needs
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        cr = _r(12)   # respect global corner-radius percentage
        p.setBrush(QBrush(QColor(_c.BG3)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, cr, cr)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(_c.ACC), 2.0))
        p.drawRoundedRect(r, cr, cr)
        p.end()

    def eventFilter(self, obj, e: QEvent) -> bool:
        if (self.isVisible() and
                e.type() == QEvent.Type.MouseButtonPress and
                QApplication.activePopupWidget() is None and
                obj is not self and
                not (isinstance(obj, QWidget) and self.isAncestorOf(obj))):
            try:
                local = self.mapFromGlobal(e.globalPosition().toPoint())
                if not self.rect().contains(local):
                    self.hide()
                    self._hide_timestamp_ms = QDateTime.currentMSecsSinceEpoch()
            except Exception:
                self.hide()
                self._hide_timestamp_ms = QDateTime.currentMSecsSinceEpoch()
        return False  # never swallow events

    def show_above(self, btn: QWidget):
        win = btn.window()
        if self.parent() is not win:
            self.setParent(win)
            self.setWindowFlags(Qt.WindowType.Widget)  # ensure child
        # Drop any cap left over from a previous show, then measure the popup
        # at the height the rows actually want.
        self.setMaximumHeight(16777215)
        self._scroll.setMinimumHeight(self._inner.sizeHint().height())
        self.adjustSize()
        chrome = self.height() - self._scroll.height()
        b = btn.mapTo(win, QPoint(0, 0))
        x = b.x() + btn.width()//2 - self.width()//2
        above = b.y() - 8
        below = win.height() - (b.y() + btn.height()) - 8
        # Whichever side has the most room gets the menu. The button sits at
        # the bottom of the sidebar, so "below" is usually nothing at all and
        # an exact fit test against it would drop the menu to the wrong side.
        room = max(above, below)
        prefer_above = above >= below
        if self.height() > room:
            # Trim the scroll body, not the frame: the accent border keeps its
            # shape and the rows past the fold are one flick away.
            self._scroll.setMinimumHeight(max(72, room - chrome))
            self.setMaximumHeight(max(100, room))
            self.resize(self.width(), max(100, room))
        y = b.y() - self.height() - 6 if prefer_above else b.y() + btn.height() + 6
        x = max(4, min(x, win.width() - self.width() - 4))
        y = max(4, min(y, win.height() - self.height() - 4))
        self.move(x, y)
        self.show()
        self.raise_()

    def toggle_above(self, btn: QWidget):
        now = QDateTime.currentMSecsSinceEpoch()
        if now - self._hide_timestamp_ms < 150:
            self._hide_timestamp_ms = 0
            return
        if self.isVisible():
            self.hide()
        else:
            self.show_above(btn)
