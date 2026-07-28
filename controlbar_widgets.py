"""
VoidPulse — standalone control-bar widgets used by ControlBar.

RepeatButton (three-state repeat icon), _FullscreenBtn, SpinningPlayButton
(play/pause with a busy spinner), _RoundedCoverLabel (cover thumbnail with
rounded corners and accent recolouring), and the _ctrl() button factory.
"""
from constants import *
from constants import _DARK_MODE, _FRAME_MS, _r
from cover_art import _COVER_MASTER_SIZE, _COVER_SENTINEL, _acc_lut_cache, _cover_cache
from player import RepeatMode
import numpy as _np


def _ctrl(text, checkable=False, sz=44):
    b = QPushButton(text); b.setObjectName('ctrl')
    b.setCheckable(checkable); b.setMinimumSize(sz,sz); b.setMaximumSize(sz,sz)
    return b

class RepeatButton(QAbstractButton):
    mode_changed = pyqtSignal(RepeatMode)
    _TIPS  = ['No repeat', 'Repeat all', 'Repeat one']
    _MODES = [RepeatMode.NONE, RepeatMode.ALL, RepeatMode.ONE]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44,44); self._idx = 0
        self.clicked.connect(self._cycle)
        self.setCursor(Qt.CursorShape.PointingHandCursor); self.setToolTip(self._TIPS[0])

    def _cycle(self):
        self._idx = (self._idx+1)%3; self.setToolTip(self._TIPS[self._idx])
        self.update(); self.mode_changed.emit(self._MODES[self._idx])

    def set_mode(self, m): self._idx = self._MODES.index(m); self.setToolTip(self._TIPS[self._idx]); self.update()
    def current_mode(self): return self._MODES[self._idx]

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        idx = self._idx; col = QColor(ACC if idx > 0 else FG2)
        cx, cy, r = self.width()//2, self.height()//2, 7
        if self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(BG3)))
            p.drawEllipse(QRectF(0, 0, self.width(), self.height()))
        pen = QPen(col, 2.0); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(cx-r, cy-r, r*2, r*2, 60*16, 300*16)
        ang = math.radians(60); tx = cx+r*math.cos(ang); ty = cy-r*math.sin(ang)
        L, W = 4.5, 2.0; bx, by = 0.866, 0.5; px, py = -0.5, 0.866
        p.drawLine(QPointF(tx,ty), QPointF(tx+L*bx+W*px, ty+L*by+W*py))
        p.drawLine(QPointF(tx,ty), QPointF(tx+L*bx-W*px, ty+L*by-W*py))
        if idx == 2:
            f = QFont(p.font()); f.setPixelSize(8); f.setBold(True); p.setFont(f)
            p.setPen(col); p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '1')
        p.end()

# ══════════════════════════════════════════════════════════════════════════════
#  Full-screen toggle button
# ══════════════════════════════════════════════════════════════════════════════
class _FullscreenBtn(QAbstractButton):
    """Draws 4 outward-pointing corner arrows; toggles on click."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_full = False
        self.setFixedSize(36, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


    def set_fullscreen(self, v: bool):
        self._is_full = v
        self.setToolTip('Exit Fullscreen' if v else 'Fullscreen')
        self.update()

    def sizeHint(self): return QSize(36, 36)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Background on hover
        if self.underMouse():
            p.setBrush(QBrush(QColor(BG3)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(0, 0, 36, 36))
        col = QColor(FG) if self.underMouse() else QColor(FG2)
        pen = QPen(col, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        m = 8.0; a = 5.0   # margin from edge, arm length
        # Arms point inward while windowed ("expand") and outward while fullscreen
        # ("collapse"); s flips the direction for all four corners at once.
        s = 1 if self._is_full else -1
        corners = [
            (m,      m,      -s,  -s),   # top-left
            (36-m,   m,       s,  -s),   # top-right
            (m,      36-m,   -s,   s),   # bottom-left
            (36-m,   36-m,    s,   s),   # bottom-right
        ]
        for cx, cy, dx, dy in corners:
            # L-shaped bracket: one horizontal arm plus one vertical arm
            p.drawLine(QPointF(cx, cy), QPointF(cx + dx*a, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + dy*a))
        p.end()

class SpinningPlayButton(QPushButton):
    """Play/pause button that shows a spinning arc while the pipeline is busy (reloading).

    States:
      • normal  — shows a ▶/⏸ glyph depending on playback state, fully interactive
      • busy    — shows a rotating arc overlay, click is blocked, MPRIS notified

    Both the circle and the ▶/⏸ glyph are hand-painted (paintEvent/_paint_icon)
    rather than sized by QSS, for two reasons:

      1. QPushButton sizes itself around its text. At font-size 22px Qt's
         sizeFromContents() demands 61×58px for a '▶' whatever the stylesheet
         says, because min/max-width constrain the content box, not the border
         box. The widget was therefore never square, and a border-radius meant
         for a square box never closed into a circle.
      2. The playing-state pulse changes the drawn diameter continuously. Driving
         that through setMinimumSize/setMaximumSize would resize the widget every
         animation frame and reflow the whole transport row; painting a smaller
         circle inside a fixed bounding box does not.

    drawRoundedRect() with radius = _r(d/2) on a square rect then follows RAD_PCT
    exactly: 0% is square, 100% gives d/2, which is what drawEllipse() would use.
    """

    _BORDER_W  = 2   # px, circle outline
    _SHRINK_PX = 6   # px smaller (diameter) while actually playing vs paused

    def __init__(self, parent=None):
        super().__init__('', parent)
        self.setObjectName('play')
        self.setStyleSheet('QPushButton#play { background:transparent; border:none; padding:0; }')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._busy       = False
        self._is_playing = False
        self._size       = 60     # bounding-box size (ControlBar's responsive shrink)
        self._pulse      = 0.0    # 0=paused diameter, 1=playing (shrunk) diameter
        self._angle      = 0.0    # current arc start angle (degrees)
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(_FRAME_MS)
        self._spin_timer.timeout.connect(self._tick)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(_FRAME_MS)
        self._pulse_timer.timeout.connect(self._pulse_step)
        self.setMinimumSize(self._size, self._size)
        self.setMaximumSize(self._size, self._size)

    # ── public API ────────────────────────────────────────────────────────────

    def set_size(self, sz: int):
        """Resize the button (ControlBar's narrow-window responsive shrink)."""
        if sz == self._size:
            return
        self._size = sz
        self.setMinimumSize(sz, sz)
        self.setMaximumSize(sz, sz)
        self.update()

    def set_playing_icon(self, playing: bool):
        if playing == self._is_playing:
            return
        self._is_playing = playing
        self._pulse_timer.start()

    # ── internals ─────────────────────────────────────────────────────────────

    def _tick(self):
        self._angle = (self._angle + 8.0) % 360.0
        self.update()

    def _pulse_step(self):
        target = 1.0 if self._is_playing else 0.0
        delta  = 0.2
        if abs(self._pulse - target) < delta:
            self._pulse = target
            self._pulse_timer.stop()
        else:
            self._pulse += delta if self._is_playing else -delta
        self.update()

    def set_busy(self, busy: bool):
        """Enter/leave busy (reloading) state."""
        if busy == self._busy:
            return
        self._busy = busy
        if busy:
            self._angle = 0.0
            self._spin_timer.start()
        else:
            self._spin_timer.stop()
        self.setEnabled(not busy)
        self.update()

    def enterEvent(self, e):
        super().enterEvent(e)
        self.update()   # hover color is read live in paintEvent, not QSS-driven

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.update()

    def _paint_icon(self, p: QPainter, d: float, color: QColor):
        cx, cy = self.width() / 2.0, self.height() / 2.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        icon_h = d * 0.34
        if self._is_playing:
            bar_w = icon_h * 0.34
            gap   = icon_h * 0.26
            rad   = bar_w * 0.3
            for x in (cx - gap / 2 - bar_w, cx + gap / 2):
                p.drawRoundedRect(QRectF(x, cy - icon_h / 2, bar_w, icon_h), rad, rad)
        else:
            side = icon_h * 1.05
            path = QPainterPath()
            path.moveTo(cx - side * 0.42, cy - side / 2)
            path.lineTo(cx - side * 0.42, cy + side / 2)
            path.lineTo(cx + side * 0.58, cy)
            path.closeSubpath()
            p.drawPath(path)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = self.underMouse() and not self._busy
        # The trailing -1 makes d odd (self._size is even at every breakpoint), so
        # the margin lands on a half pixel. On a whole-pixel margin the circle's
        # tangent points sit exactly on the pixel grid and rasterise without
        # antialiasing while the curves between them do not, making one pen look
        # like two thicknesses.
        d = self._size - self._SHRINK_PX * self._pulse - self._BORDER_W - 1
        rect = QRectF((self.width() - d) / 2.0, (self.height() - d) / 2.0, d, d)
        border_c = QColor(ACCH if hovered else ACC)
        bg_c     = QColor(BG4 if (hovered or self.isDown()) else BG3)
        p.setPen(QPen(border_c, self._BORDER_W))
        p.setBrush(QBrush(bg_c))
        # Rounded rect rather than an ellipse so the button follows the global
        # RAD_PCT slider: 0% is square, 100% gives _r(d/2) == d/2, a true circle.
        radius = _r(int(d / 2))
        p.drawRoundedRect(rect, radius, radius)
        self._paint_icon(p, d, border_c)
        if self._busy:
            # Semi-transparent dark overlay so the icon fades back, then the
            # spinning arc on top of that.
            p.fillRect(self.rect(), QColor(0, 0, 0, 140))
            inset = 7
            arc_rect = QRectF(inset, inset, self.width() - 2*inset, self.height() - 2*inset)
            pen = QPen(QColor(ACC), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Qt angles: 0° = 3 o'clock, positive = counter-clockwise, units = 1/16 degree
            start_angle = int((90.0 - self._angle) * 16)   # top = 90°
            span_angle  = int(250 * 16)                     # 250° arc
            p.drawArc(arc_rect, start_angle, span_angle)
        p.end()

class _RoundedCoverLabel(QWidget):
    """Cover thumbnail clipped to a rounded rect matching the global RAD_PCT.

    The clip is rebuilt on each paintEvent — QPainterPath construction is cheap,
    and the clip is what leaves the corners transparent over the viz background.

    Cover-accent mode (set_cover_accent_mode) maps each pixel's brightness onto
    the current accent hue and saturation (black → dark accent, white → bright
    accent) using numpy over the raw ARGB32 buffer. The result is cached per
    (fp, accent, size, theme) and dropped on track or accent change.
    """

    def __init__(self, size: int, parent=None):
        super().__init__(parent)
        self._sz  = size
        self._pm: QPixmap | None = None
        self._fp: str | None = None          # filepath of current track
        self._cover_acc_mode: bool = False
        self._acc_pm: QPixmap | None = None  # cached recoloured pixmap
        self._acc_pm_key: tuple = ()         # (fp, acc_h, acc_s) → invalidation key
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_size(self, size: int):
        """Resize the thumbnail (ControlBar's narrow-window responsive shrink).
        paintEvent already rescales whatever pixmap it holds to self._sz on
        every paint, so no re-fetch is needed here — just the new box size."""
        if size == self._sz:
            return
        self._sz = size
        self.setFixedSize(size, size)
        self.update()

    def setPixmap(self, pm: QPixmap | None, fp: str | None = None):
        self._pm = pm
        self._fp = fp
        self._acc_pm = None   # invalidate recoloured cache on new pixmap
        self.update()

    def clear(self):
        self._pm = None
        self._fp = None
        self._acc_pm = None
        self.update()

    def set_cover_accent_mode(self, on: bool):
        self._cover_acc_mode = on
        self._acc_pm = None   # force rebuild on next paint
        self.update()

    def _build_accent_pixmap(self) -> QPixmap | None:
        """Recolour the 220px master: each pixel's brightness → accent colour.

        Reads the image stride-correctly (as _recolor_pixmap does) so row padding
        never breaks the reshape, and shares _acc_lut_cache so the 256-entry
        QColor loop runs once per accent for the whole app.

        The result is scaled to self._sz and cached, so paintEvent never rescales.
        The key includes the size, letting one instance serve any target size.
        """
        fp = self._fp
        if not fp:
            return None
        # Pull 220px master already in RAM — no I/O
        master = _cover_cache.get((fp, _COVER_MASTER_SIZE), _COVER_SENTINEL)
        if master is _COVER_SENTINEL or master is None:
            return None

        acc_h, acc_s, _, _ = QColor(ACC).getHsv()
        sz  = self._sz
        # Include _DARK_MODE in key: light mode maps accent→white, dark maps black→accent
        key = (fp, acc_h, acc_s, sz, _DARK_MODE)
        if self._acc_pm_key == key and self._acc_pm is not None:
            return self._acc_pm   # still valid

        # Shared with _recolor_pixmap; keyed the same way (hue, saturation, mode).
        lut_key = (acc_h, acc_s, _DARK_MODE)
        lut = _acc_lut_cache.get(lut_key)
        if lut is None:
            lut_r = _np.empty(256, dtype=_np.uint8)
            lut_g = _np.empty(256, dtype=_np.uint8)
            lut_b = _np.empty(256, dtype=_np.uint8)
            _c = QColor()
            if _DARK_MODE:
                for v in range(256):
                    _c.setHsv(acc_h, acc_s, v)
                    lut_r[v] = _c.red()
                    lut_g[v] = _c.green()
                    lut_b[v] = _c.blue()
            else:
                for v in range(256):
                    sat = 255 - v
                    _c.setHsv(acc_h, sat, 255)
                    lut_r[v] = _c.red()
                    lut_g[v] = _c.green()
                    lut_b[v] = _c.blue()
            lut = (lut_r, lut_g, lut_b)
            _acc_lut_cache[lut_key] = lut
        lut_r, lut_g, lut_b = lut

        # bytesPerLine can exceed w*4: Qt may pad rows for alignment, so read the
        # full stride and slice the pixel columns out (as _recolor_pixmap does).
        img = master.toImage().convertToFormat(QImage.Format.Format_RGB32)
        w, h = img.width(), img.height()
        stride = img.bytesPerLine()
        ptr = img.bits()
        ptr.setsize(h * stride)
        raw = _np.frombuffer(ptr, dtype=_np.uint8).reshape(h, stride).copy()
        del img  # release QImage ASAP — data already copied
        arr = raw[:, : w * 4].reshape(h * w, 4)   # strip row padding

        # Qt RGB32 LE layout: [B, G, R, 0xFF] — BT.601 integer luminance
        y8 = ((arr[:, 2].astype(_np.uint16) * 2 +
               arr[:, 1].astype(_np.uint16) * 5 +
               arr[:, 0].astype(_np.uint16)) >> 3).clip(0, 255).astype(_np.uint8)

        out = arr.copy()
        out[:, 0] = lut_b[y8]
        out[:, 1] = lut_g[y8]
        out[:, 2] = lut_r[y8]
        # out[:, 3] stays 0xFF (opaque)

        acc_pm = QPixmap.fromImage(
            QImage(out.tobytes(), w, h, w * 4, QImage.Format.Format_RGB32))

        # ── Downscale to widget size once, cache the result ───────────────────
        if acc_pm.size() != QSize(sz, sz):
            acc_pm = acc_pm.scaled(sz, sz,
                                   Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            ox = (acc_pm.width()  - sz) // 2
            oy = (acc_pm.height() - sz) // 2
            acc_pm = acc_pm.copy(ox, oy, sz, sz)

        self._acc_pm     = acc_pm
        self._acc_pm_key = key
        return acc_pm

    def paintEvent(self, _):
        if self._pm is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        radius = _r(self._sz // 2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self._sz, self._sz), radius, radius)
        p.setClipPath(path)
        # Choose source pixmap
        if self._cover_acc_mode:
            pm = self._build_accent_pixmap() or self._pm
        else:
            pm = self._pm
        # Scale/crop to widget size if needed
        if pm.size() != QSize(self._sz, self._sz):
            pm = pm.scaled(self._sz, self._sz,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
            ox = (pm.width()  - self._sz) // 2
            oy = (pm.height() - self._sz) // 2
            pm = pm.copy(ox, oy, self._sz, self._sz)
        # Cover-accent mode: draw fully opaque (the recoloured image IS the bg).
        # Normal mode: 65% so the viz bars bleed through.
        p.setOpacity(1.0 if self._cover_acc_mode else 0.65)
        p.drawPixmap(0, 0, pm)
        p.end()
