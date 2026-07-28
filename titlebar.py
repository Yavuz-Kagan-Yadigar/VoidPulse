"""
VoidPulse — custom frameless titlebar: TitleBarButton, TitleBarCloseButton and
BlackTitleBar.

Used when the window is configured to draw its own decorations instead of the
system ones (an OLED-friendly pure-black bar).
"""
from constants import *


# ══════════════════════════════════════════════════════════════════════════════
#  Titlebar constants
# ══════════════════════════════════════════════════════════════════════════════
_TB_FG      = '#666666'   # title text
_TB_ICO     = '#686868'   # window-control icons
_TB_ICO_HOV = '#aaaaaa'   # brighter on hover
_TB_CLOSE_H = '#cc3333'   # close-button hover
_TB_H       = 32          # titlebar height in px

class TitleBarButton(QPushButton):
    """Minimal frameless window-control button."""
    def __init__(self, symbol: str, hover_color: str = _TB_ICO_HOV, parent=None):
        super().__init__(symbol, parent)
        self._hover_col = hover_color
        self.setFixedSize(46, _TB_H)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._refresh_style(_TB_ICO)

    def _refresh_style(self, fg: str):
        bg_hover  = BG3
        bg_press  = BG4
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {fg};
                font-size: 14px;
                border-radius: 0;
                padding: 0;
            }}
            QPushButton:hover  {{ background: {bg_hover}; color: {self._hover_col}; }}
            QPushButton:pressed {{ background: {bg_press}; }}
        """)

class TitleBarCloseButton(TitleBarButton):
    def __init__(self, parent=None):
        super().__init__('✕', _TB_CLOSE_H, parent)

class BlackTitleBar(QWidget):
    """
    Frameless custom title bar — adapts to dark/light theme via BG global.
    """

    def __init__(self, window: QWidget, parent=None):
        super().__init__(parent)
        self._win = window
        self.setFixedHeight(_TB_H)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_bg()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(0)

        self._ico_lbl = QLabel('♫')
        self._ico_lbl.setStyleSheet(
            f'color: {_TB_ICO}; font-size: 13px; background: transparent; padding-right: 6px;')
        lay.addWidget(self._ico_lbl)

        self._title_lbl = QLabel('VoidPulse')
        self._title_lbl.setStyleSheet(
            f'color: {_TB_FG}; font-size: 12px; font-weight: normal; background: transparent;')
        lay.addWidget(self._title_lbl)

        lay.addStretch(1)

        self._btn_min   = TitleBarButton('―')
        self._btn_max   = TitleBarButton('□')
        self._btn_close = TitleBarCloseButton()

        for btn in (self._btn_min, self._btn_max, self._btn_close):
            lay.addWidget(btn)

        self._btn_min.clicked.connect(self._win.showMinimized)
        self._btn_max.clicked.connect(self._toggle_max)
        self._btn_close.clicked.connect(self._win.close)

    def set_title(self, text: str):
        self._title_lbl.setText(text)

    def _apply_bg(self):
        """Apply current BG global to titlebar background."""
        self.setStyleSheet(f'background: {BG}; border: none;')

    def refresh_theme(self):
        """Called by MainWindow after a theme switch to repaint titlebar."""
        self._apply_bg()
        self._title_lbl.setStyleSheet(
            f'color: {FG2}; font-size: 12px; font-weight: normal; background: transparent;')
        for btn in (self._btn_min, self._btn_max, self._btn_close):
            btn._refresh_style(_TB_ICO)
        self.repaint()

    def _toggle_max(self):
        if self._win.isMaximized():
            self._win.showNormal()
            self._btn_max.setText('□')   # maximize icon
        else:
            self._win.showMaximized()
            self._btn_max.setText('❐')  # restore-down icon

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            # A press on one of the buttons must not start a window drag;
            # childAt() returns None only on the bare titlebar.
            if self.childAt(e.position().toPoint()) is None:
                handle = self._win.windowHandle()
                if handle:
                    handle.startSystemMove()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()
        super().mouseDoubleClickEvent(e)

# ══════════════════════════════════════════════════════════════════════════════
