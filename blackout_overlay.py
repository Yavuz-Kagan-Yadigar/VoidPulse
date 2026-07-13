"""
VoidPulse — BlackoutOverlay: full-screen OLED burn-in protection overlay.
"""
from constants import *
from eq import _fmt_ms, _np_to_qpolygonf
from constants import ACC, BG3, OV_VIZ_H, RAD_PCT
import numpy as _np

class BlackoutOverlay(QWidget):
    """Full-screen OLED burn-in protection overlay.
    Shows time, track title/artist and a progress bar in red,
    fading in/out at random positions every ~10 seconds."""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.BypassWindowManagerHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)

        # Track / position state
        self._title  = ''
        self._artist = ''
        self._album  = ''   # received via set_track() — reserved for future use
        self._pos_ms = 0
        self._dur_ms = 0
        # Overlay feature flags
        self._ctrlbar_ref  = None
        self._ov_viz    = False
        self._ov_lyrics = False
        self._ov_clock  = True   # show clock by default
        # Visualization data (list of normalised 0..1 values, VIZ_BANDS long)
        self._viz_data = None   # ndarray (VIZ_BANDS,) or None when no frame received yet
        # Lyrics state (prev, cur, next)
        self._lyr_prev = ''; self._lyr_cur = ''; self._lyr_next = ''

        # Widget offset (randomised each cycle)
        self._ox = 0.3; self._oy = 0.35   # fractional position 0..1

        # Scale factor (set from SettingsPopup overlay scale slider, 50–200 %)
        self._scale = 1.0
        # Cached paint colors — rebuilt when ACC changes
        self._ov_paint_key: str = ''
        self._ov_colors: dict = {}

        # Fade animation (opacity effect on a child container)
        self._container = QWidget(self)
        self._container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._opacity_effect = QGraphicsOpacityEffect(self._container)
        self._opacity_effect.setOpacity(0.0)
        self._container.setGraphicsEffect(self._opacity_effect)

        self._anim = QPropertyAnimation(self._opacity_effect, b'opacity', self)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)

        # Clock refresh timer (every second)
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._container.update)

        # Cycle timer: visible 8s, then fade out, reposition, fade in
        self._cycle_timer = QTimer(self)
        self._cycle_timer.setSingleShot(True)
        self._cycle_timer.timeout.connect(self._start_fade_out)

    # ── public api ────────────────────────────────────────────────────────────
    def set_track(self, title: str, artist: str, album: str = ''):
        self._title = title; self._artist = artist; self._album = album
        if self.isVisible(): self._container.update()

    def set_pos(self, pos_ms: int, dur_ms: int):
        self._pos_ms = pos_ms; self._dur_ms = dur_ms
        if self.isVisible(): self._container.update()


    def set_overlay_viz(self, on: bool):
        self._ov_viz = on
        self._resize_container()
        if self.isVisible(): self._container.update()
        if self._ctrlbar_ref is not None:
            self._ctrlbar_ref._player._update_spec_active()

    def set_overlay_lyrics(self, on: bool):
        self._ov_lyrics = on
        self._resize_container()
        if self.isVisible(): self._container.update()

    def set_overlay_clock(self, on: bool):
        self._ov_clock = on
        if self.isVisible(): self._container.update()

    def set_scale(self, percent: int):
        """Called from SettingsPopup when the overlay scale slider changes (50–200)."""
        self._scale = max(0.5, min(2.0, percent / 100.0))
        self._resize_container()
        if self.isVisible(): self._container.update()

    def push_viz_frame(self, spec_normalised):
        """Called from Player._compute_viz_frame with the normalised (0..1) bar-height
        ndarray.  Direct assignment — no list copy.  BlackoutOverlay._paint_info only
        iterates the value, so ndarray and list are both valid.
        """
        self._viz_data = spec_normalised
        if self._ov_viz and self.isVisible():
            self._container.update()

    def set_lyrics_context(self, prev: str, cur: str, nxt: str):
        # Skip entirely when the overlay is hidden or lyrics overlay is off —
        # storing the strings and calling update() is pure overhead in that case.
        if not self.isVisible() or not self._ov_lyrics:
            return
        self._lyr_prev = prev; self._lyr_cur = cur; self._lyr_next = nxt
        self._container.update()

    # ── dismiss ───────────────────────────────────────────────────────────────
    def _dismiss(self):
        self._cycle_timer.stop(); self._clock_timer.stop()
        self._anim.stop()
        self.hide()
        if self._ctrlbar_ref is not None:
            # Resume ControlBar viz rendering now that overlay is gone,
            # then restart the idle countdown.
            self._ctrlbar_ref.set_overlay_open(False)
            self._ctrlbar_ref._reset_idle_timer()

    def mousePressEvent(self, e):
        # Consume the event — dismiss only, do not propagate to widgets beneath.
        self._dismiss()

    def keyPressEvent(self, e):
        self._dismiss()

    def event(self, e):
        t = e.type()
        if t == QEvent.Type.TouchBegin:
            # Consume the whole touch sequence that dismisses the overlay so
            # TouchUpdate / TouchEnd do not reach whatever is beneath.
            self._dismiss()
            return True
        if t in (QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd):
            return True  # swallow remainder of the dismissing touch sequence
        return super().event(e)

    # ── show / cycle ──────────────────────────────────────────────────────────
    def show_blackout(self):
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self._reposition()
        self.showFullScreen(); self.raise_(); self.activateWindow()
        self._clock_timer.start()
        self._start_fade_in()
        # Stop idle timer while overlay is visible
        if self._ctrlbar_ref is not None:
            self._ctrlbar_ref._idle_timer.stop()
        # Suppress ControlBar viz rendering while overlay is open (if overlay viz is off,
        # the ControlBar is completely covered and computing frames would be wasted).
        if self._ctrlbar_ref is not None:
            self._ctrlbar_ref.set_overlay_open(True)
        # Notify ControlBar so spectrum runs for overlay viz if needed
        if self._ov_viz and self._ctrlbar_ref is not None:
            self._ctrlbar_ref.ensure_overlay_spec()

    def _reposition(self):
        """Randomise container position (keep it well inside screen bounds)."""
        sw, sh = self.width() or 1920, self.height() or 1080
        cw, ch = self._container.width() or 320, self._container.height() or 120
        max_x = max(0, sw - cw); max_y = max(0, sh - ch)
        self._ox = random.randint(0, max(1, max_x))
        self._oy = random.randint(0, max(1, max_y))
        self._container.move(self._ox, self._oy)

    def _start_fade_in(self):
        self._reposition()
        self._anim.stop()
        self._anim.setDuration(800)
        self._anim.setStartValue(0.0); self._anim.setEndValue(1.0)
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.start()
        self._cycle_timer.start(8000)    # stay visible 8 s

    def _start_fade_out(self):
        self._anim.stop()
        self._anim.setDuration(600)
        self._anim.setStartValue(1.0); self._anim.setEndValue(0.0)
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.finished.connect(self._start_fade_in)
        self._anim.start()

    # ── layout / paint ────────────────────────────────────────────────────────
    def _resize_container(self):
        sw = self.width() or 1920
        sc = getattr(self, '_scale', 1.0)
        base_w = min(520, sw - 60)
        clock_h = 34 if getattr(self, '_ov_clock', True) else 0
        base_h = clock_h + 86 + (OV_VIZ_H if self._ov_viz else 0) + (62 if self._ov_lyrics else 0)
        self._container.setFixedSize(int(base_w * sc), int(base_h * sc))
        if self.isVisible(): self._reposition()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._resize_container()
        self._reposition()

    def paintEvent(self, _):
        # Full-screen solid black
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#000000'))
        p.end()

    # ── container paint (drawn inside the opacity-animated child) ─────────────
    def _paint_info(self, p: QPainter):
        sc = getattr(self, '_scale', 1.0)
        # Scale everything via a painter transform.  The container widget itself
        # is already sized to base_w*sc × base_h*sc (see _resize_container), so
        # the coordinate system is scaled to draw at the original base sizes.
        if sc != 1.0:
            p.save()
            p.scale(sc, sc)

        # Work in unscaled coordinates
        base_w = self._container.width()  / sc
        base_h = self._container.height() / sc
        r = QRectF(0, 0, base_w, base_h)
        w = r.width()
        if w < 10:
            if sc != 1.0: p.restore()
            return

        # Rebuild paint colors only when ACC or BG3 changes (not every frame)
        if self._ov_paint_key != (ACC, BG3):
            _c = QColor(ACC)
            _g = QColor(BG3)
            _a55 = QColor(ACC); _a55.setAlpha(55)
            _a70 = QColor(ACC); _a70.setAlpha(70)
            _a90 = QColor(ACC); _a90.setAlpha(90)
            _a200 = QColor(ACC); _a200.setAlpha(200)
            _a220 = QColor(ACC); _a220.setAlpha(220)
            self._ov_colors = {
                'RED': _c, 'GREY': _g,
                'a55': _a55, 'a70': _a70, 'a90': _a90,
                'a200': _a200, 'a220': _a220,
            }
            self._ov_paint_key = (ACC, BG3)
        _oc = self._ov_colors
        RED       = _oc['RED']
        GREY      = _oc['GREY']
        _acc_a55  = _oc['a55']
        _acc_a70  = _oc['a70']
        _acc_a90  = _oc['a90']
        _acc_a200 = _oc['a200']
        _acc_a220 = _oc['a220']
        CENT = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Layout
        LYR_H  = 20.0
        VIZ_H  = float(OV_VIZ_H)
        BAR_H  = 4.0
        BAR_W  = w - 20.0
        # Dynamic BAR_Y: artist bottom (84) + optional lyrics + 18px for time labels
        # Dynamic layout: when clock is hidden the title/artist block shifts up
        CLOCK_H = 34.0 if self._ov_clock else 0.0
        lyr_h_total = (3 * LYR_H) if self._ov_lyrics else 0.0
        BAR_Y = CLOCK_H + 50.0 + lyr_h_total + 18.0

        # ── Clock ─────────────────────────────────────────────────────────────
        if self._ov_clock:
            font = p.font(); font.setPixelSize(22); font.setBold(True); p.setFont(font)
            p.setPen(RED)
            p.drawText(QRectF(0, 0, w, 30), CENT,
                       QDateTime.currentDateTime().toString('HH:mm:ss'))
        else:
            font = p.font()

        # ── Title ─────────────────────────────────────────────────────────────
        font.setPixelSize(18); font.setBold(True); p.setFont(font)
        title = QFontMetrics(font).elidedText(
            self._title or '—', Qt.TextElideMode.ElideRight, int(w))
        p.setPen(RED)
        p.drawText(QRectF(0, CLOCK_H, w, 26), CENT, title)

        # ── Artist ────────────────────────────────────────────────────────────
        font.setPixelSize(14); font.setBold(False); p.setFont(font)
        artist = QFontMetrics(font).elidedText(
            self._artist or '', Qt.TextElideMode.ElideRight, int(w))
        p.drawText(QRectF(0, CLOCK_H + 28.0, w, 22), CENT, artist)

        # ── Overlay LYRICS (artist → lyrics → progress bar) ──────────────────
        if self._ov_lyrics:
            font.setPixelSize(13); p.setFont(font)
            fm3 = QFontMetrics(font)
            y = CLOCK_H + 52.0
            for txt, color in [
                (self._lyr_prev, GREY),
                (self._lyr_cur,  RED),
                (self._lyr_next, GREY),
            ]:
                etxt = fm3.elidedText(txt or '', Qt.TextElideMode.ElideRight, int(BAR_W))
                p.setPen(color)
                p.drawText(QRectF(10, y, BAR_W, LYR_H), CENT, etxt)
                y += LYR_H

        # ── Progress bar ──────────────────────────────────────────────────────
        frac = (max(0.0, min(1.0, self._pos_ms / self._dur_ms))
                if self._dur_ms > 0 else 0.0)
        font.setPixelSize(12); p.setFont(font)
        p.setPen(RED)
        p.drawText(QRectF(10, BAR_Y - 15, 60, 14),
                   Qt.AlignmentFlag.AlignLeft, _fmt_ms(self._pos_ms))
        p.drawText(QRectF(w - 70, BAR_Y - 15, 62, 14),
                   Qt.AlignmentFlag.AlignRight, _fmt_ms(self._dur_ms))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_acc_a55))
        p.drawRoundedRect(QRectF(10, BAR_Y, BAR_W, BAR_H), 2, 2)
        if frac > 0:
            p.setBrush(QBrush(RED))
            p.drawRoundedRect(QRectF(10, BAR_Y, BAR_W * frac, BAR_H), 2, 2)

        # ── Overlay VIZ (docked to bottom of progress bar) ─────────────────
        vd = self._viz_data
        if self._ov_viz and vd is not None and len(vd) > 0:
            viz_y = BAR_Y + BAR_H
            n_v  = len(vd)
            bw_v = BAR_W / max(1, n_v)
            bar_col = _acc_a200
            # Retrieve viz type from ctrlbar if available
            _vtype = 'bars'
            if self._ctrlbar_ref is not None:
                _vtype = getattr(self._ctrlbar_ref, '_viz_type', 'bars')

            if _vtype == 'fill':
                fill_col = _acc_a90
                cx_list = [10.0 + (i + 0.5) * bw_v for i in range(n_v)]
                cy_list = [viz_y + float(norm) * VIZ_H for norm in vd]
                poly = QPolygonF()
                poly.append(QPointF(cx_list[0], viz_y))
                for cx, cy in zip(cx_list, cy_list):
                    poly.append(QPointF(cx, cy))
                poly.append(QPointF(cx_list[-1], viz_y))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(fill_col))
                p.setClipRect(QRectF(10, viz_y, BAR_W, VIZ_H))
                p.drawPolygon(poly)
                p.setClipping(False)
            elif _vtype == 'line':
                cx_arr = 10.0 + (_np.arange(n_v) + 0.5) * bw_v
                cy_arr = viz_y + vd.astype(_np.float64) * VIZ_H
                line_col = _acc_a220
                pen = QPen(line_col, 1.5, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setClipRect(QRectF(10, viz_y, BAR_W, VIZ_H))
                p.drawPolyline(_np_to_qpolygonf(cx_arr, cy_arr))
                p.setClipping(False)
            elif _vtype == 'line+fill':
                cx_arr = 10.0 + (_np.arange(n_v) + 0.5) * bw_v
                cy_arr = viz_y + vd.astype(_np.float64) * VIZ_H
                # Fill polygon beneath the line
                fill_col = _acc_a70
                # Build fill polygon: first point at top-left, data points, last point at top-right
                fx = _np.empty(n_v + 2, dtype=_np.float64)
                fy = _np.empty(n_v + 2, dtype=_np.float64)
                fx[0]  = cx_arr[0];  fy[0]  = viz_y
                fx[1:-1] = cx_arr;   fy[1:-1] = cy_arr
                fx[-1] = cx_arr[-1]; fy[-1] = viz_y
                poly_fill = _np_to_qpolygonf(fx, fy)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(fill_col))
                p.setClipRect(QRectF(10, viz_y, BAR_W, VIZ_H))
                p.drawPolygon(poly_fill)
                # Line on top
                line_col = _acc_a220
                pen = QPen(line_col, 1.5, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolyline(_np_to_qpolygonf(cx_arr, cy_arr))
                p.setClipping(False)
            else:
                # Bars mode (original)
                bw_draw = max(1.0, bw_v)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(bar_col))
                p.setClipRect(QRectF(10, viz_y, BAR_W, VIZ_H))
                # Round caps on bar tops only when global corner-radius >= 50 %
                _bar_use_round = RAD_PCT >= 50
                # Iterate with explicit float() so both ndarray elements and plain
                # floats are handled safely without triggering ndarray truth-value errors.
                x = 10.0
                for norm in vd:
                    h = float(norm) * VIZ_H
                    if h >= 0.01 * VIZ_H:
                        if _bar_use_round:
                            cap_r = min(bw_draw / 2.0, h / 2.0)
                            p.drawRoundedRect(QRectF(x, viz_y, bw_draw, h), cap_r, cap_r)
                        else:
                            p.drawRect(QRectF(x, viz_y, bw_draw, h))
                    x += bw_v
                p.setClipping(False)

        if sc != 1.0:
            p.restore()

    def showEvent(self, e):
        super().showEvent(e)
        # Install once — showEvent fires every time the overlay is shown, and
        # installing the same filter repeatedly stacks duplicate registrations
        # (each open would add another, making eventFilter fire N times per event).
        if not getattr(self, '_container_filter_installed', False):
            self._container.installEventFilter(self)
            self._container_filter_installed = True

    def eventFilter(self, obj, e):
        if obj is self._container and e.type() == QEvent.Type.Paint:
            p = QPainter(self._container)
            self._paint_info(p)
            p.end()
            return True
        if e.type() in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate,
                        QEvent.Type.TouchEnd):
            self._dismiss(); return True
        return super().eventFilter(obj, e)

# ══════════════════════════════════════════════════════════════════════════════
