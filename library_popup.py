"""
VoidPulse — LibraryPopup: the library-management actions (add folder,
import M3U, network share, new playlist, refresh, export) as a compact popup
styled after the playlist context menu: BG3 fill, 2px accent border, radius
off the global corner-radius percentage, and menu-like text rows.
"""
from constants import *
from constants import _r
import constants as _c   # live module ref: paintEvent reads the current palette


class LibraryPopup(QFrame):
    add_folder_req    = pyqtSignal()
    add_m3u_req       = pyqtSignal()
    network_share_req = pyqtSignal()
    new_playlist_req  = pyqtSignal()
    refresh_req       = pyqtSignal()
    export_m3u_req    = pyqtSignal()

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
        ]
        for pos, (text, tip, sig) in enumerate(specs):
            if pos == 3 or pos == 5:
                sep = QFrame(); sep.setFixedHeight(1)
                sep.setStyleSheet(f'background:{_c.B2}; margin:3px 8px;')
                self._seps.append(sep)
                v.addWidget(sep)
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(getattr(self, sig).emit)
            btn.clicked.connect(lambda *_: self.hide())
            self._btns.append(btn)
            v.addWidget(btn)

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
        # Drop any height cap from a previous show before measuring
        self.setMaximumHeight(16777215)
        self.adjustSize()
        b = btn.mapTo(win, QPoint(0, 0))
        x = b.x() + btn.width()//2 - self.width()//2
        above = b.y() - 8
        below = win.height() - (b.y() + btn.height()) - 8
        prefer_above = above >= self.height()
        avail = above if prefer_above else below
        if self.height() > avail:
            # Cap the height so the popup stays inside the window
            self.setMaximumHeight(max(80, avail))
            self.adjustSize()
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
