"""
VoidPulse — base/utility widgets: ToggleSwitch, TriSwitch, JumpSlider, SliderRow,
DeviceBusyPopup, _ModalOverlay.
"""
from constants import *
from constants import ACC, ACCH, B2, BG, BG4, BORD, FG, FG2, _FRAME_MS, _r
class ToggleSwitch(QWidget):
    """Toggle switch with optional two-sided labels.

    Single label:  ToggleSwitch('LABEL', parent)  — label shown on right
    Two-sided:     ToggleSwitch('OFF', 'ON', parent) — left=off, right=on

    muted_labels=True: both labels always render in FG2 (grey) regardless of state.
    """
    toggled = pyqtSignal(bool)
    W, H, R = 42, 22, 11
    PAD = 6   # gap between label and switch track
    _KNOB_PAD = 3                    # inset on every side (constant for all instances)
    _KNOB_SZ  = H - 2 * _KNOB_PAD   # = 16 px knob side length

    def __init__(self, label_off: str = '', label_on_or_parent=None, parent=None,
                 muted_labels: bool = False, label_point_size: int = 0):
        # Resolve overloaded signature
        if isinstance(label_on_or_parent, str):
            self._lbl_off = label_off          # left side / off state
            self._lbl_on  = label_on_or_parent # right side / on state
        else:
            # Backward compat: single label shown on right
            self._lbl_off  = ''
            self._lbl_on   = label_off
            if label_on_or_parent is not None and parent is None:
                parent = label_on_or_parent

        super().__init__(parent)
        self._muted_labels     = muted_labels
        self._label_point_size = label_point_size  # 0 = inherit widget font size
        self._on = False; self._anim = 0.0
        self._timer = QTimer(self); self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._step)
        self._recalc_size()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Cached palette-derived colors — rebuilt by _rebuild_track_colors().
        # Keyed by (ACC, BG4, B2, FG, FG2) so any palette/accent change invalidates them.
        self._color_cache_key: tuple = ()
        self._track_on_rgb: tuple = (0, 0, 0)
        self._border_on_rgb: tuple = (0, 0, 0)
        self._off_rgb: tuple = (0, 0, 0)
        self._boff_rgb: tuple = (0, 0, 0)
        # Label colours (dim = FG2, bright = FG) — cached alongside track colours
        self._dim_rgb:    tuple = (0, 0, 0)
        self._bright_rgb: tuple = (0, 0, 0)

    def _label_font(self) -> 'QFont':
        """Return the font to use for label text. Smaller if label_point_size is set."""
        f = self.font()
        if self._label_point_size > 0:
            f = QFont(f)
            f.setPointSize(self._label_point_size)
        return f

    def _recalc_size(self):
        fm = QFontMetrics(self._label_font())
        lw_off = fm.horizontalAdvance(self._lbl_off) + self.PAD if self._lbl_off else 0
        lw_on  = fm.horizontalAdvance(self._lbl_on)  + self.PAD if self._lbl_on  else 0
        total_w = lw_off + self.W + lw_on
        self.setMinimumWidth(max(total_w, self.W))
        self.setFixedHeight(max(self.H, 18))
        self._lw_off = lw_off  # cached left-label pixel width (including pad)

    def showEvent(self, e):
        super().showEvent(e)
        self._recalc_size()  # re-measure with actual font after widget is realized

    def isChecked(self) -> bool: return self._on

    def setChecked(self, on: bool):
        self._on = on; self._anim = 1.0 if on else 0.0; self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._on = not self._on; self._timer.start(); self.toggled.emit(self._on)

    def _step(self):
        target = 1.0 if self._on else 0.0; delta = 0.15
        if abs(self._anim - target) < delta: self._anim = target; self._timer.stop()
        else: self._anim += delta if self._on else -delta
        self.update()

    def _rebuild_track_colors(self):
        """Recompute and cache HSV-derived track/border colours and label colours.
        Called lazily in paintEvent when the palette key has changed."""
        _acc = QColor(ACC)
        ah, as_, av, _ = _acc.getHsvF()
        ton = QColor(); ton.setHsvF(ah, as_ * 0.55, av * 0.38)
        bon = QColor(); bon.setHsvF(ah, as_ * 0.65, av * 0.55)
        _off  = QColor(BG4)
        _boff = QColor(B2)
        _dim    = QColor(FG2)
        _bright = QColor(FG)
        self._track_on_rgb  = (ton.red(),  ton.green(),  ton.blue())
        self._border_on_rgb = (bon.red(),  bon.green(),  bon.blue())
        self._off_rgb  = (_off.red(),  _off.green(),  _off.blue())
        self._boff_rgb = (_boff.red(), _boff.green(), _boff.blue())
        self._dim_rgb    = (_dim.red(),    _dim.green(),    _dim.blue())
        self._bright_rgb = (_bright.red(), _bright.green(), _bright.blue())
        self._color_cache_key = (ACC, BG4, B2, FG, FG2)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._anim
        h_c = self.height()
        lw_off = self._lw_off

        # ── Track ──────────────────────────────────────────────────────────────
        # Lazily rebuild cached colour tuples when palette/accent changes.
        if self._color_cache_key != (ACC, BG4, B2, FG, FG2):
            self._rebuild_track_colors()

        ton_r, ton_g, ton_b = self._track_on_rgb
        bon_r, bon_g, bon_b = self._border_on_rgb
        off_r, off_g, off_b = self._off_rgb
        boff_r, boff_g, boff_b = self._boff_rgb

        if self._muted_labels:
            tc = QColor(off_r, off_g, off_b)
            bc = QColor(boff_r, boff_g, boff_b)
        else:
            tc = QColor(
                int(off_r  + t * (ton_r  - off_r)),
                int(off_g  + t * (ton_g  - off_g)),
                int(off_b  + t * (ton_b  - off_b)))
            bc = QColor(
                int(boff_r + t * (bon_r  - boff_r)),
                int(boff_g + t * (bon_g  - boff_g)),
                int(boff_b + t * (bon_b  - boff_b)))
        track_x  = lw_off
        track_r  = _r(self.R)   # 0 = boxy, self.R = H//2 (full pill)
        p.setPen(QPen(bc, 1.5)); p.setBrush(QBrush(tc))
        p.drawRoundedRect(QRectF(track_x, (h_c-self.H)/2, self.W, self.H), track_r, track_r)

        # ── Knob ───────────────────────────────────────────────────────────────
        knob_sz   = self._KNOB_SZ
        kx = track_x + self._KNOB_PAD + t * (self.W - 2 * self._KNOB_PAD - knob_sz)
        ky = (h_c - self.H) / 2 + self._KNOB_PAD
        knob_r   = _r(knob_sz // 2)
        p.setPen(Qt.PenStyle.NoPen)
        knob_color = FG2 if self._muted_labels else (ACCH if self._on else FG2)
        p.setBrush(QBrush(QColor(knob_color)))
        p.drawRoundedRect(QRectF(kx, ky, knob_sz, knob_sz), knob_r, knob_r)

        # ── Labels ─────────────────────────────────────────────────────────────
        dim_r,    dim_g,    dim_b    = self._dim_rgb
        bright_r, bright_g, bright_b = self._bright_rgb
        lbl_font = self._label_font()

        if self._lbl_off:
            # Left label: bright when OFF, dim when ON — or always dim if muted
            if self._muted_labels:
                c = QColor(dim_r, dim_g, dim_b)
            else:
                mix = 1.0 - t   # 1=off, 0=on
                c = QColor(
                    int(dim_r + mix * (bright_r - dim_r)),
                    int(dim_g + mix * (bright_g - dim_g)),
                    int(dim_b + mix * (bright_b - dim_b)))
            p.setPen(c)
            p.setFont(lbl_font)
            p.drawText(QRectF(0, 0, lw_off - self.PAD, h_c),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       self._lbl_off)

        if self._lbl_on:
            # Right label: bright when ON, dim when OFF — or always dim if muted
            if self._muted_labels:
                c2 = QColor(dim_r, dim_g, dim_b)
            else:
                c2 = QColor(
                    int(dim_r + t * (bright_r - dim_r)),
                    int(dim_g + t * (bright_g - dim_g)),
                    int(dim_b + t * (bright_b - dim_b)))
            p.setPen(c2)
            p.setFont(lbl_font)
            rstart = track_x + self.W + self.PAD
            p.drawText(QRectF(rstart, 0, self.width()-rstart, h_c),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self._lbl_on)
        p.end()

# ══════════════════════════════════════════════════════════════════════════════
#  3-position cover switch  (no cover · cover · cover+accent)
# ══════════════════════════════════════════════════════════════════════════════
class TriSwitch(QWidget):
    """3-position segmented toggle for cover display mode.

    States
    ------
    0  — no cover
    1  — cover shown (no accent derivation)
    2  — cover shown + accent colour derived from cover art

    Labels are drawn INSIDE the track (segmented-control style) — widget height
    is exactly H=22 px (same as ToggleSwitch) so no vertical-alignment issues.
    """
    stateChanged = pyqtSignal(int)   # emits 0 / 1 / 2
    W, H, R = 90, 22, 11
    _LABELS   = ('OFF', 'COVER', 'ACC')

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: int = 1          # default: cover on, no accent
        self._anim:  float = 0.5      # 0.0=left  0.5=centre  1.0=right
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._step)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Cached palette colours — same pattern as ToggleSwitch
        self._color_cache_key: tuple = ()
        self._track_on_rgb:  tuple = (0, 0, 0)
        self._border_on_rgb: tuple = (0, 0, 0)
        self._off_rgb:  tuple = (0, 0, 0)
        self._boff_rgb: tuple = (0, 0, 0)
        self._dim_rgb:    tuple = (0, 0, 0)
        self._bright_rgb: tuple = (0, 0, 0)

    # ── Public API ─────────────────────────────────────────────────────────
    def state(self) -> int: return self._state

    def setState(self, s: int, animate: bool = False):
        self._state = max(0, min(2, s))
        if animate:
            self._timer.start()
        else:
            self._anim = self._state / 2.0
            self.update()

    # ── Interaction ────────────────────────────────────────────────────────
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            zone = max(0, min(2, int(e.position().x() / (self.W / 3))))
            if zone != self._state:
                self._state = zone
                self._timer.start()
                self.stateChanged.emit(self._state)

    # ── Animation ──────────────────────────────────────────────────────────
    def _anim_target(self) -> float:
        return self._state / 2.0

    def _step(self):
        target = self._anim_target()
        delta = 0.15
        if abs(self._anim - target) < delta:
            self._anim = target; self._timer.stop()
        else:
            self._anim += delta if self._anim < target else -delta
        self.update()

    # ── Colors ─────────────────────────────────────────────────────────────
    def _rebuild_colors(self):
        _acc = QColor(ACC)
        ah, as_, av, _ = _acc.getHsvF()
        ton = QColor(); ton.setHsvF(ah, as_ * 0.55, av * 0.38)
        bon = QColor(); bon.setHsvF(ah, as_ * 0.65, av * 0.55)
        _off  = QColor(BG4); _boff = QColor(B2)
        _dim = QColor(FG2);  _bright = QColor(FG)
        self._track_on_rgb  = (ton.red(),  ton.green(),  ton.blue())
        self._border_on_rgb = (bon.red(),  bon.green(),  bon.blue())
        self._off_rgb   = (_off.red(),   _off.green(),   _off.blue())
        self._boff_rgb  = (_boff.red(),  _boff.green(),  _boff.blue())
        self._dim_rgb    = (_dim.red(),    _dim.green(),    _dim.blue())
        self._bright_rgb = (_bright.red(), _bright.green(), _bright.blue())
        self._color_cache_key = (ACC, BG4, B2, FG, FG2)

    # ── Paint ──────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        if self._color_cache_key != (ACC, BG4, B2, FG, FG2):
            self._rebuild_colors()

        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._anim   # 0.0 → 0.5 → 1.0

        ton_r,  ton_g,  ton_b  = self._track_on_rgb
        bon_r,  bon_g,  bon_b  = self._border_on_rgb
        off_r,  off_g,  off_b  = self._off_rgb
        boff_r, boff_g, boff_b = self._boff_rgb
        dim_r,  dim_g,  dim_b  = self._dim_rgb
        br_r,   br_g,   br_b   = self._bright_rgb

        track_r = _r(self.R)
        zone_w  = self.W / 3.0

        # ── Clip all fill to rounded pill shape ────────────────────────────
        clip_path = QPainterPath()
        clip_path.addRoundedRect(QRectF(0, 0, self.W, self.H), track_r, track_r)
        p.setClipPath(clip_path)

        # Track background (always dim)
        p.fillRect(QRectF(0, 0, self.W, self.H), QColor(off_r, off_g, off_b))

        # Sliding active-zone highlight
        # hi_x: 0 at state 0, zone_w at state 1, 2*zone_w at state 2
        hi_x = t * (self.W - zone_w)
        t2   = min(1.0, t * 2)        # 0→1 once knob leaves leftmost zone
        hi_r = int(off_r + t2 * (ton_r - off_r))
        hi_g = int(off_g + t2 * (ton_g - off_g))
        hi_b = int(off_b + t2 * (ton_b - off_b))
        p.fillRect(QRectF(hi_x, 0, zone_w, self.H), QColor(hi_r, hi_g, hi_b))

        # ── Remove clip for crisp border / text ────────────────────────────
        p.setClipping(False)

        # Border
        bc = QColor(
            int(boff_r + t2 * (bon_r - boff_r)),
            int(boff_g + t2 * (bon_g - boff_g)),
            int(boff_b + t2 * (bon_b - boff_b)))
        p.setPen(QPen(bc, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.75, 0.75, self.W - 1.5, self.H - 1.5), track_r, track_r)

        # Zone dividers
        p.setPen(QPen(bc, 1.0))
        for frac in (1/3, 2/3):
            x = self.W * frac
            p.drawLine(QPointF(x, 3), QPointF(x, self.H - 3))

        # Labels inside track
        f = self.font(); f.setPointSize(7); p.setFont(f)
        for i, lbl in enumerate(self._LABELS):
            brightness = max(0.0, 1.0 - abs(t * 2 - i))
            c = QColor(
                int(dim_r + brightness * (br_r - dim_r)),
                int(dim_g + brightness * (br_g - dim_g)),
                int(dim_b + brightness * (br_b - dim_b)))
            p.setPen(c)
            p.drawText(QRectF(zone_w * i, 0, zone_w, self.H),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                       lbl)
        p.end()



# ══════════════════════════════════════════════════════════════════════════════
#  Slider row
# ══════════════════════════════════════════════════════════════════════════════
class JumpSlider(QSlider):
    """Slider that jumps immediately to click/touch position.

    Wheel events are intentionally ignored — the slider only responds to
    direct mouse press/drag and touch.  This prevents the corners slider (and
    any other SliderRow) from changing value when the user scrolls over the
    settings popup.
    """
    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        self._touch_active = False
        # Do not steal keyboard focus on click — avoids spurious value changes
        # when focus moves between widgets and Qt replays key events.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def _jump(self, x: float):
        v = QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), int(max(0, x)), self.width())
        self.setValue(v)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self._jump(e.position().x())
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton: self._jump(e.position().x())
        super().mouseMoveEvent(e)

    def wheelEvent(self, e):
        # Ignore scroll-wheel — avoids accidental radius/volume changes when
        # scrolling over the settings popup.
        e.ignore()

    def event(self, e: QEvent) -> bool:
        t = e.type()
        if t == QEvent.Type.TouchBegin:
            pts = e.points()
            if pts:
                self._touch_active = True
                self._jump(pts[0].position().x())
            e.accept(); return True
        if t == QEvent.Type.TouchUpdate:
            pts = e.points()
            if pts and self._touch_active:
                self._jump(pts[0].position().x())
            e.accept(); return True
        if t == QEvent.Type.TouchEnd:
            self._touch_active = False
            e.accept(); return True
        return super().event(e)

class SliderRow(QWidget):
    valueChanged = pyqtSignal(int)

    def __init__(self, label: str, lo: int, hi: int, val: int,
                 fmt=str, parent=None, step: int = 1):
        super().__init__(parent)
        self._fmt = fmt
        lay = QHBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(6)
        lbl = QLabel(label); lbl.setObjectName('setting_lbl')
        lbl.setFixedWidth(70)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._sl = JumpSlider(Qt.Orientation.Horizontal)
        self._sl.setRange(lo, hi); self._sl.setValue(val)
        self._sl.setSingleStep(step); self._sl.setPageStep(step * 4)
        self._sl.setFixedHeight(18)
        self._sl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._val_lbl = QLabel(fmt(val)); self._val_lbl.setObjectName('setting_lbl')
        self._val_lbl.setFixedWidth(46)
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._val_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._sl.valueChanged.connect(self._on_change)
        lay.addWidget(lbl); lay.addWidget(self._sl, 1); lay.addWidget(self._val_lbl)

    def _on_change(self, v):
        self._val_lbl.setText(self._fmt(v)); self.valueChanged.emit(v)

    def value(self) -> int: return self._sl.value()
    def setValue(self, v: int): self._sl.setValue(v)

# ══════════════════════════════════════════════════════════════════════════════

class DeviceBusyPopup(QFrame):
    """Popup shown when an ALSA device error occurs (busy, open-failed, etc.).

    Style matches SettingsPopup / EqPopup: BG fill + ACC 3 px rounded border,
    painted in paintEvent.  Centred inside the parent window (Wayland-safe
    child widget).  Auto-dismisses after AUTO_DISMISS_MS.

    Signals:
      switch_to_pipewire — user clicked 'Switch to PipeWire'
      retry              — user clicked 'Retry'
    """

    switch_to_pipewire = pyqtSignal()
    retry              = pyqtSignal()

    AUTO_DISMISS_MS = 10000

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName('device_busy_popup')
        # Transparent background: paintEvent draws BG + ACC border like other popups.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(False)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)

        # ── Layout ────────────────────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(10)

        # Title row (matches popup_title label style used by SettingsPopup / EqPopup)
        self._title_lbl = QLabel('AUDIO DEVICE ERROR')
        self._title_lbl.setObjectName('popup_title')
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self._title_lbl)

        # Divider
        div = QFrame(); div.setFixedHeight(1)
        div.setStyleSheet(f'background:{BORD}; margin:0;')
        root.addWidget(div)

        # Detail text (raw GStreamer message)
        self._detail = QLabel()
        self._detail.setWordWrap(True)
        self._detail.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._detail.setStyleSheet(
            f'color:{FG2}; font-size:11px; background:transparent;')
        self._detail.setFixedWidth(300)
        root.addWidget(self._detail)

        # Button row
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        def _mk_primary(text):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f'QPushButton {{ background:{ACC}; color:#fff;'
                f'  border:none; border-radius:{_r(6)}px;'
                f'  font-size:11px; font-weight:600; padding:6px 14px; }}'
                f'QPushButton:hover {{ background:{ACCH}; }}')
            return b

        def _mk_secondary(text):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f'QPushButton {{ background:transparent; color:{FG2};'
                f'  border:1px solid {BORD}; border-radius:{_r(6)}px;'
                f'  font-size:11px; padding:6px 14px; }}'
                f'QPushButton:hover {{ color:{FG}; border-color:{FG2}; }}')
            return b

        self._btn_retry   = _mk_primary('Retry')
        self._btn_switch  = _mk_secondary('Switch to PipeWire')
        self._btn_dismiss = _mk_secondary('Dismiss')

        self._btn_retry.clicked.connect(self._on_retry)
        self._btn_switch.clicked.connect(self._on_switch)
        self._btn_dismiss.clicked.connect(self._dismiss)

        btn_row.addWidget(self._btn_retry)
        btn_row.addWidget(self._btn_switch)
        btn_row.addWidget(self._btn_dismiss)
        root.addLayout(btn_row)

        self.hide()

    # ── paintEvent: same rounded-rect + ACC border as SettingsPopup / EqPopup ──
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.setBrush(QBrush(QColor(BG)))
        cr = _r(11)   # respect global corner-radius percentage
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, cr, cr)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(ACC), 3.0))
        p.drawRoundedRect(r, cr, cr)
        p.end()

    def show_error(self, gst_error: str) -> None:
        """Display the popup with the given GStreamer error string and
        restart the auto-dismiss timer.  Safe to call multiple times."""
        err_lower = gst_error.lower()
        if 'busy' in err_lower or 'ebusy' in err_lower:
            title = 'AUDIO DEVICE BUSY'
        else:
            title = 'AUDIO DEVICE ERROR'
        self._title_lbl.setText(title)

        msg = gst_error.strip()
        if len(msg) > 140:
            msg = msg[:137] + '…'
        self._detail.setText(msg)
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start(self.AUTO_DISMISS_MS)

    def _reposition(self) -> None:
        """Centre the popup inside the parent widget."""
        p = self.parent()
        if p is None:
            return
        self.adjustSize()
        x = max(4, (p.width()  - self.width())  // 2)
        y = max(4, (p.height() - self.height()) // 2)
        self.move(x, y)

    def _on_retry(self) -> None:
        self._dismiss()
        self.retry.emit()

    def _on_switch(self) -> None:
        self._dismiss()
        self.switch_to_pipewire.emit()

    def _dismiss(self) -> None:
        self._timer.stop()
        self.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.isVisible():
            self._reposition()


# ══════════════════════════════════════════════════════════════════════════════
#  Modal overlay — dark scrim + click-outside-to-close for all dialogs
# ══════════════════════════════════════════════════════════════════════════════
class _ModalOverlay(QWidget):
    """Full-window dark scrim that sits between the main window and a popup.

    • Darkens the entire main window with a semi-transparent black overlay.
    • A mouse press outside the attached popup closes/hides it.
    • Works with QDialog (calls reject()) and plain QWidget popups (calls hide()).
    • Automatically resizes when the parent window resizes.

    For QDialog: use finished signal only (Hide fires spuriously during exec() startup).
    For QWidget: watch Hide event (EQ, fetch popups, rename going to background).
    """

    def __init__(self, main_win: QWidget, popup: QWidget):
        super().__init__(main_win)
        self._popup = popup
        self._is_dialog = isinstance(popup, QDialog)
        self._done = False
        self.setGeometry(main_win.rect())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        self.raise_()
        if self._is_dialog:
            # finished fires when dialog closes — never during exec() startup
            popup.finished.connect(self._on_popup_done)
        else:
            # plain QWidget: watch Hide so background-dismiss works
            popup.installEventFilter(self)
        main_win.installEventFilter(self)
        # App-level filter catches clicks anywhere on screen
        QApplication.instance().installEventFilter(self)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 140))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dismiss()
        e.accept()

    def _dismiss(self):
        if self._is_dialog:
            self._popup.reject()
        else:
            self._popup.hide()

    def eventFilter(self, obj, e):
        if obj is self.parent() and e.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        elif (not self._is_dialog and
              obj is self._popup and e.type() == QEvent.Type.Hide):
            self._on_popup_done()
        elif (e.type() == QEvent.Type.MouseButtonPress and
              self.isVisible() and
              obj is not self and
              not (isinstance(obj, QWidget) and self._popup.isAncestorOf(obj)) and
              not self._popup.rect().contains(
                  self._popup.mapFromGlobal(e.globalPosition().toPoint()))):
            # Do not dismiss if a another dialog is currently active on top of
            # the popup (e.g. LyricsEditDialog opened from TagEditDialog).
            # On Wayland child QDialogs become true top-level windows and lose
            # their Qt parent(), so we cannot walk the parent chain.  Instead,
            # check whether the application's active window is any QDialog other
            # than self._popup — if so, that dialog "owns" the click.
            active = QApplication.activeWindow()
            if isinstance(active, QDialog) and active is not self._popup:
                pass  # click is inside a child/sibling dialog — keep popup open
            else:
                self._dismiss()
        return False

    def _on_popup_done(self):
        if self._done:
            return
        self._done = True
        # Remove all filters first so no further events reach this (about-to-die) overlay.
        QApplication.instance().removeEventFilter(self)
        self.parent().removeEventFilter(self)
        if not self._is_dialog:
            try:
                self._popup.removeEventFilter(self)
            except Exception:
                pass
        self.hide()
        self.deleteLater()

    @staticmethod
    def show_for(popup: QWidget) -> '_ModalOverlay':
        """Find the main window, create overlay, centre popup. Caller shows popup."""
        parent = popup.parent()
        win = parent
        while win is not None and not isinstance(win, QMainWindow):
            win = win.parent()
        if win is None:
            win = parent
        if win is None:
            return None
        overlay = _ModalOverlay(win, popup)
        overlay.show()
        overlay.raise_()
        popup.adjustSize()
        gp = win.mapToGlobal(QPoint(0, 0))
        cx = gp.x() + (win.width()  - popup.width())  // 2
        cy = gp.y() + (win.height() - popup.height()) // 2
        popup.move(cx, cy)
        popup.raise_()
        return overlay



# ══════════════════════════════════════════════════════════════════════════════
#  _SpinningOverlay — moved here from voidpulse.py to break circular import
# ══════════════════════════════════════════════════════════════════════════════
class _SpinningOverlay(QWidget):
    """Semi-transparent dark backdrop with a spinning red arc.

    Startup:  _SpinningOverlay.as_splash()   -> standalone top-level window
    Runtime:  _SpinningOverlay(parent=win)   -> sits on top of the parent window
    """

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        if parent:
            parent.installEventFilter(self)
            self._sync_to_parent()
            self.raise_()
        self._timer.start()

    def _sync_to_parent(self):
        p = self.parent()
        if p:
            self.setGeometry(p.rect())

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.WindowStateChange,
        ):
            self._sync_to_parent()
            self.raise_()
        return False

    @classmethod
    def as_splash(cls) -> '_SpinningOverlay':
        """Startup splash: standalone top-level window."""
        w = cls.__new__(cls)
        QWidget.__init__(w)
        w._angle = 0.0
        w._timer = QTimer(w)
        w._timer.setInterval(_FRAME_MS)
        w._timer.timeout.connect(w._tick)
        w.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool)
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        w.setFixedSize(360, 200)
        w._timer.start()
        return w

    def close_overlay(self):
        self._timer.stop()
        self.hide()
        self.deleteLater()

    def _tick(self):
        self._angle = (self._angle + 6.0) % 360.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(0, 0, 0, 200))
        cx, cy = w // 2, h // 2
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setWeight(QFont.Weight.Light)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.0)
        p.setFont(title_font)
        p.setPen(QColor('#f0f0f0'))
        p.drawText(QRect(0, cy - 80, w, 36),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                   'VoidPulse')
        r = 28
        spinner_cy = cy + 20
        pen = QPen(QColor(ACC), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(cx - r, spinner_cy - r, r * 2, r * 2,
                  int((90.0 - self._angle) * 16), int(260 * 16))
        p.end()
