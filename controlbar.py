"""
VoidPulse — control bar and titlebar: _ctrl() factory, RepeatButton, _FullscreenBtn,
SpinningPlayButton, _RoundedCoverLabel, ControlBar (seek + transport + EQ/settings + viz
paintEvent), TitleBarButton, TitleBarCloseButton, BlackTitleBar.
"""
from constants import *

from library import RenamePopup
from fetch_popups import LyricsFetchPopup, TagFetchPopup
from widgets_base import _ModalOverlay, _SpinningOverlay
from constants import ACC, ACCH, BG, BG3, BG4, BORD, CONFIG_PATH, EQ_TYPE_PEAK, FG, FG2, GST_BANDS, MIN_DB, RAD_PCT, VIZ_BANDS, _DARK_MODE, _FRAME_MS, _FRAME_S, _r, apply_theme, apply_accent, make_stylesheet, is_system_qt_theme_active
from time import monotonic as _monotonic
import numpy as _np
import gc as _gc
from eq import EqPopup, _fmt_ms
from settings_popup import SettingsPopup
from cover_art import CoverFetchPopup, _BaseFetchPopup, _COVER_MASTER_SIZE, _COVER_SENTINEL, draw_default_cover, get_cover_pixmap, _acc_lut_cache, _corner_frame_cache, _cover_cache, _default_cover_mem_cache
from player import Player, RepeatMode
from cover_art import Track
from views import SeekSlider

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
        # Arrow size and margin
        m = 8.0; a = 5.0   # margin from edge, arrow arm length
        # outward arrows when fullscreen → "compress/exit"; inward when normal → "expand"
        # Note: corner (cx,cy) is at the edge; arm goes cx+dx*a, cy+dy*a
        # For the icon to read as "expand", arms at each corner should point INWARD
        # (toward center) because that's the conventional "go fullscreen" arrows.
        s = 1 if self._is_full else -1
        # Four corners: (cx, cy, dx, dy) where d = outward direction
        corners = [
            (m,      m,      -s,  -s),   # top-left
            (36-m,   m,       s,  -s),   # top-right
            (m,      36-m,   -s,   s),   # bottom-left
            (36-m,   36-m,    s,   s),   # bottom-right
        ]
        for cx, cy, dx, dy in corners:
            # L-shaped arrow: horizontal arm + vertical arm + diagonal tip
            p.drawLine(QPointF(cx, cy), QPointF(cx + dx*a, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + dy*a))
        p.end()

class SpinningPlayButton(QPushButton):
    """Play/pause button that shows a spinning arc while the pipeline is busy (reloading).

    States:
      • normal  — shows ▶ or ⏸ depending on playback state, fully interactive
      • busy    — shows a rotating arc overlay, click is blocked, MPRIS notified
    """

    def __init__(self, parent=None):
        super().__init__('▶', parent)
        self.setObjectName('play')
        self.setMinimumSize(52, 52)
        self.setMaximumSize(52, 52)
        self._busy       = False
        self._angle      = 0.0    # current arc start angle (degrees)
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(_FRAME_MS)
        self._spin_timer.timeout.connect(self._tick)

    # ── public API ────────────────────────────────────────────────────────────

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

    # ── internals ─────────────────────────────────────────────────────────────

    def _tick(self):
        self._angle = (self._angle + 8.0) % 360.0
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._busy:
            return
        # Draw spinning arc on top of the button face
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Semi-transparent dark overlay so the ▶/⏸ text fades back
        p.fillRect(self.rect(), QColor(0, 0, 0, 140))
        # Arc geometry — inset 6 px from border
        inset = 7
        rect  = QRectF(inset, inset, self.width() - 2*inset, self.height() - 2*inset)
        pen   = QPen(QColor(ACC), 3.0, Qt.PenStyle.SolidLine,
                     Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Qt angles: 0° = 3 o'clock, positive = counter-clockwise, units = 1/16 degree
        start_angle = int((90.0 - self._angle) * 16)   # top = 90°
        span_angle  = int(250 * 16)                     # 250° arc
        p.drawArc(rect, start_angle, span_angle)
        p.end()

class _RoundedCoverLabel(QWidget):
    """Cover thumbnail that clips its pixmap to a rounded rect matching the
    global corner radius (RAD_PCT).  The clip is applied via QPainterPath on
    every paintEvent — no cache needed because QPainterPath construction is
    O(1) and the painter clip is the only thing that makes the corners
    transparent against the viz background.

    Cover-accent mode (set_cover_accent_mode):
      When on, the 220px master is fetched from _cover_cache, each pixel's
      brightness is extracted and mapped onto the current accent hue+sat at
      that value level (black→darkAccent, white→brightAccent).  This is done
      with numpy on the raw ARGB32 buffer — no per-pixel Python loop.
      The recoloured pixmap is cached per (fp, acc_h, acc_s) and invalidated
      on track or accent change.
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

        Stride-correct numpy read (identical strategy to _recolor_pixmap so
        bytesPerLine padding never causes a reshape crash on any Qt build).
        Uses the shared _acc_lut_cache so the 256-QColor loop runs at most once
        per accent hue for the whole app instead of once per track change.
        The result is downscaled to self._sz and cached — paintEvent never
        rescales, eliminating a 60-fps QPixmap allocation.
        Cache key includes sz so the same instance can serve any target size.
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

        # ── Shared LUT (same as _recolor_pixmap; built once per accent hue + mode) ──
        lut_key = (acc_h, _DARK_MODE)
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

        # ── Stride-correct numpy read (bytesPerLine may exceed w*4) ──────────
        # Same approach as _recolor_pixmap; avoids reshape ValueError when Qt
        # adds row-alignment padding after convertToFormat on some builds.
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


class ControlBar(QFrame):
    cover_on_changed = pyqtSignal(bool)
    accent_changed   = pyqtSignal(str)
    settings_changed = pyqtSignal()   # emitted whenever a persistable setting changes

    def __init__(self, player: Player, parent=None):
        super().__init__(parent)
        self.setObjectName('ctrlbar')
        self.setMinimumHeight(110)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        self._player    = player
        self._dur_ms    = 0
        self._seeking   = False
        self._viz_on    = True
        self._overlay_viz_enabled = False
        self._overlay_open        = False   # True while BlackoutOverlay is visible
        self._log_scale = True
        self._viz_type  = 'bars'   # 'bars' | 'line'
        self._bar_x0    = _np.zeros(VIZ_BANDS, dtype=_np.int32)
        self._col_bar   = _np.full(1, -1, dtype=_np.int32)  # (iw,) rebuilt in _precompute_bars
        self._col_has_bar  = _np.zeros(1, dtype=bool)          # (iw,) precomputed mask
        self._col_bar_safe = _np.zeros(1, dtype=_np.int32)     # (iw,) 0-clamped for safe gather
        self._bar_bw       = 1
        self._cap_radius   = 0
        self._cap_r_offsets = _np.empty(0, dtype=_np.int32)  # (n_cap_pix,) row deltas
        self._cap_c_offsets = _np.empty(0, dtype=_np.int32)  # (n_cap_pix,) col deltas
        self._bar_color    = QColor(44, 36, 36)
        self._brightness_v = 40   # default brightness slider value (0–100)
        self._cur_track: Optional[Track] = None
        self._inertia   = 0.5
        self._viz_paused  = False
        self._focus_paused = False
        self._cover_acc_on: bool = False   # mirrors the "ACC" cover-accent toggle

        self._delay_ms    = 0
        # Numpy ring buffer for viz frame delay.
        # At 60 fps and max delay 1000 ms we need at most ~62 slots; 70 gives headroom.
        # Two pre-allocated arrays — no Python allocation per frame:
        #   _viz_rbuf   (70, VIZ_BANDS) float32  — circular frame storage
        #   _viz_rbuf_ts (70,)          float64  — wall-clock timestamp per slot
        # _viz_rbuf_head: next write slot (mod 70); _viz_rbuf_count: valid slots filled.
        _VIZ_RBUF_N = 70
        self._viz_rbuf_n    = _VIZ_RBUF_N
        self._viz_rbuf      = _np.zeros((_VIZ_RBUF_N, VIZ_BANDS), dtype=_np.float32)
        self._viz_rbuf_ts   = _np.zeros(_VIZ_RBUF_N, dtype=_np.float64)
        self._viz_rbuf_head = 0
        self._viz_rbuf_count= 0
        # Display buffer: delayed (or live) frame that paintEvent reads.
        self._viz_display_buf = _np.zeros(VIZ_BANDS, dtype=_np.float32)

        # Paint pre-allocation — rebuilt in _precompute_bars / resizeEvent, reused every frame
        self._paint_bar_px      = _np.zeros(VIZ_BANDS, dtype=_np.int32)
        # Pixel buffer for single-shot drawImage (avoids 256+ fillRect calls per frame)
        self._px_buf:     object = None   # (ih, iw) uint32 numpy array
        self._px_qimg:    object = None   # QImage wrapping _px_buf
        self._px_shape:   tuple  = (0, 0) # (ih, iw) rebuilt on resize
        self._px_bg:      int    = 0      # BG as 0xAARRGGBB uint32
        self._px_bar:     int    = 0      # bar color as 0xAARRGGBB uint32
        self._px_bg_key:  object = None   # tracks BG global for cache invalidation
        self._px_bar_key: object = None   # tracks bar color for cache invalidation
        self._px_row_idx: object = None   # (ih, 1) int32 — row indices for broadcast
        self._render_last_wt:    float = 0.0   # timestamp of last update() call
        # Cached QPen / QBrush objects for paintEvent — rebuilt when BORD/BG globals change.
        # Avoids constructing QPen(QColor(BORD), 1) on every 60-fps frame.
        self._paint_bord_key: object = None    # tracks BORD global
        self._paint_bord_pen: QPen   = QPen()  # QPen(BORD, 1) — rebuilt on demand
        self._paint_bg_brush: QBrush = QBrush()

        # Settings and EQ popups (lazy-created)
        self._settings_popup: Optional[SettingsPopup] = None
        self._eq_popup: Optional[EqPopup] = None

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(18,14,18,12); self._root_layout.setSpacing(10)
        root = self._root_layout

        # Row 1: seek
        row1 = QHBoxLayout(); row1.setSpacing(6)
        self._lbl_cur = QLabel('0:00'); self._lbl_cur.setObjectName('time_lbl')
        self._lbl_tot = QLabel('0:00'); self._lbl_tot.setObjectName('time_lbl')
        for lbl in (self._lbl_cur, self._lbl_tot):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            lbl.setStyleSheet('background:transparent;')
        self._lbl_cur.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_tot.setAlignment(Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter)
        self._seek = SeekSlider(self)
        row1.addWidget(self._lbl_cur); row1.addWidget(self._seek, 1); row1.addWidget(self._lbl_tot)
        root.addLayout(row1)

        # Row 2: now-playing | transport | right buttons
        row2 = QHBoxLayout(); row2.setSpacing(0)

        # Now-playing
        info = QWidget(); info.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        info.setStyleSheet('background:transparent;')
        # Horizontal layout: cover thumbnail (optional) + title/artist stack
        info_h = QHBoxLayout(info); info_h.setContentsMargins(8, 0, 0, 0); info_h.setSpacing(10)
        _COVER_SZ = 64
        # Cover thumbnail — rounded corners via _RoundedCoverLabel (clips to global RAD_PCT;
        # transparent corners show the viz background cleanly, computed per paintEvent, no cache)
        self._cover_lbl = _RoundedCoverLabel(_COVER_SZ)
        self._cover_lbl.setVisible(True)
        info_h.addWidget(self._cover_lbl)
        # Title pinned to cover top, artist pinned to cover bottom
        txt_w = QWidget(); txt_w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        txt_w.setStyleSheet('background:transparent;'); txt_w.setFixedHeight(_COVER_SZ)
        il = QVBoxLayout(txt_w); il.setContentsMargins(0, 3, 0, 3); il.setSpacing(0)
        self._lbl_title  = QLabel('—'); self._lbl_title.setObjectName('now_title')
        self._lbl_artist = QLabel('');  self._lbl_artist.setObjectName('now_artist')
        for lbl in (self._lbl_title, self._lbl_artist):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            lbl.setStyleSheet('background:transparent;')
        self._lbl_title.setMaximumWidth(240); self._lbl_title.setWordWrap(False)
        self._lbl_title.setTextFormat(Qt.TextFormat.PlainText)
        il.addWidget(self._lbl_title, 0, Qt.AlignmentFlag.AlignTop)
        il.addStretch(1)
        il.addWidget(self._lbl_artist, 0, Qt.AlignmentFlag.AlignBottom)
        info_h.addWidget(txt_w, 1)
        row2.addWidget(info, 3)

        # Transport
        centre_w = QWidget(); centre_w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        centre_w.setStyleSheet('background:transparent;')
        centre = QHBoxLayout(centre_w); centre.setSpacing(6); centre.setContentsMargins(0,0,0,0)
        centre.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.btn_shuf = _ctrl('⇌', checkable=True)
        self.btn_prev = _ctrl('⏮')
        self.btn_play = SpinningPlayButton(); self.btn_play.setObjectName('play')
        self.btn_next = _ctrl('⏭')
        self.btn_rep  = RepeatButton(self)
        _ts = (f'QPushButton#ctrl {{ background:transparent; border:none; color:{FG2};'
               f' font-size:20px; border-radius:{_r(22)}px; padding:0; text-align:center; }}'
               f'QPushButton#ctrl:hover {{ color:{FG}; background:{BG3}; }}'
               f'QPushButton#ctrl:checked {{ color:{ACC}; background:transparent; }}'
               f'QPushButton#ctrl:pressed {{ background:{BG4}; }}')
        for b in (self.btn_shuf, self.btn_prev, self.btn_next): b.setStyleSheet(_ts)
        self.btn_play.setStyleSheet(
            f'QPushButton#play {{ background:{BG3}; color:{ACC};'
            f' border:2px solid {ACC}; border-radius:{_r(26)}px;'
            f' min-width:52px; max-width:52px; min-height:52px; max-height:52px;'
            f' font-size:22px; padding:0 0 2px 5px; text-align:center; }}'
            f'QPushButton#play:hover {{ border-color:{ACCH}; color:{ACCH};'
            f' background:{BG4}; }}'
            f'QPushButton#play:pressed {{ background:{BG4}; }}')
        for b in (self.btn_shuf, self.btn_prev, self.btn_play, self.btn_next, self.btn_rep):
            centre.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        row2.addWidget(centre_w, 2)

        # Right: blackout, eq, settings
        right = QWidget(); right.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        right.setStyleSheet('background:transparent;')
        rl = QHBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(6)
        rl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.btn_blackout = QPushButton('⬛'); self.btn_blackout.setObjectName('icon_btn')
        self.btn_blackout.setToolTip('Dim Screen (OLED protection)')
        self.btn_eq = QPushButton('DSP'); self.btn_eq.setObjectName('icon_btn')
        self.btn_eq.setToolTip('DSP / Equalizer')
        self.btn_lyrics = QPushButton('≡'); self.btn_lyrics.setObjectName('icon_btn')
        self.btn_lyrics.setToolTip('Lyrics')
        self.btn_lyrics.setCheckable(True)
        self.btn_fullscreen = _FullscreenBtn(self)
        self.btn_fullscreen.setObjectName('icon_btn')
        self.btn_fullscreen.setToolTip('Fullscreen')
        self.btn_settings = QPushButton('...');  self.btn_settings.setObjectName('icon_btn')
        self.btn_settings.setToolTip('Settings')
        for b in (self.btn_blackout, self.btn_eq, self.btn_lyrics,
                  self.btn_fullscreen, self.btn_settings):
            b.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.btn_eq.clicked.connect(self._toggle_eq)
        self.btn_fullscreen.clicked.connect(self._toggle_fullscreen)
        self.btn_settings.clicked.connect(self._toggle_settings)
        rl.addWidget(self.btn_blackout); rl.addWidget(self.btn_eq)
        rl.addWidget(self.btn_lyrics)
        rl.addWidget(self.btn_fullscreen); rl.addWidget(self.btn_settings)
        row2.addWidget(right, 3)
        root.addLayout(row2)

        # signals
        player.sig_pos.connect(self._on_pos)
        player.sig_dur.connect(self._on_dur)
        player.sig_playing.connect(self._on_playing_changed)
        player.sig_seek_flush.connect(self._on_seek_flush)
        self._seek.sliderPressed.connect(self._on_press)
        self._seek.sliderReleased.connect(self._on_release)
        self._seek.sliderMoved.connect(self._on_moved)

        # ── Overlay auto-open idle timer ─────────────────────────────────────
        self._overlay_auto_open   = False
        self._overlay_timeout_ms  = 60_000   # default 60 s
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(self._overlay_timeout_ms)
        self._idle_timer.timeout.connect(self._on_idle_timeout)
        # Last mouse position for 5-px threshold (global screen coordinates)
        self._idle_last_mouse: Optional[QPoint] = None

        # ── Viz repaint — fixed-rate Qt timer ───────────────────────────────
        # GStreamer frames update _viz_bar_buf at whatever rate they arrive;
        # a separate Qt timer drives paintEvent at a fixed 16 ms cadence (FPS_CAP).
        # Each tick records its deadline and schedules the next tick relative to
        # that deadline so scheduling jitter does not accumulate.
        # _viz_has_new is the handshake between the GLib spectrum callback and the
        # render timer — no direct signal connection needed.
        # Recompute freq→bin mapping when track sample rate changes.
        player.sig_fs_changed.connect(lambda _fs: self._precompute_bars())
        self._render_timer = QTimer(self)
        self._render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._render_timer.setInterval(_FRAME_MS)  # FPS_CAP fixed render cadence
        self._render_timer.timeout.connect(self._render_tick)
        # Pre-compute bar layout once widget has a valid size (after first layout pass)
        QTimer.singleShot(0, self._precompute_bars)
        # Debounce timer for resize — avoids recomputing on every pixel change
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(40)
        self._resize_timer.timeout.connect(self._precompute_bars)

    # --- EQ popup ---
    def _ensure_eq_popup(self):
        if self._eq_popup is None:
            pop = EqPopup()
            pop.eq_changed.connect(self._on_eq_changed)
            pop.limiter_changed.connect(self._player.set_limiter_enabled)
            pop.stereo_changed.connect(self._player.set_stereo_enabled)
            pop.stereo_width_changed.connect(self._player.set_stereo_width)
            pop.preamp_changed.connect(self._player.set_preamp_db)
            # Auto-save on FX changes
            for sig in (pop.limiter_changed, pop.stereo_changed,
                        pop.stereo_width_changed, pop.preamp_changed):
                sig.connect(lambda *_: self.settings_changed.emit())
            self._eq_popup = pop
        return self._eq_popup

    def _toggle_eq(self):
        pop = self._ensure_eq_popup()
        now = QDateTime.currentMSecsSinceEpoch()
        if now - pop._hide_timestamp_ms < 150:
            pop._hide_timestamp_ms = 0
            return
        pop.set_bands(self._player._eq_bands, self._player._eq_enabled)
        # Sync FX switches from player state (in case they changed without UI)
        pop.set_limiter_enabled(self._player._limiter_enabled)
        pop.set_stereo_enabled(self._player._stereo_enabled)
        pop.set_stereo_width(self._player._stereo_width)
        pop.set_preamp_db(self._player._preamp_db)
        if pop.isVisible():
            pop.hide()
        else:
            win = self.window()
            if win and isinstance(win, QMainWindow):
                ov = _ModalOverlay(win, pop)
                ov.show()
                ov.raise_()
            pop.show_center()

    def _on_eq_changed(self, bands, enabled):
        self._player.set_eq_bands(bands)     # bands first: reload will use them immediately
        self._player.set_eq_enabled(enabled)

    # --- Settings popup ---
    def _ensure_settings_popup(self):
        if self._settings_popup is None:
            pop = SettingsPopup()
            pop.viz_toggled.connect(self._on_viz_toggle)
            pop.log_toggled.connect(self._on_log_toggle)
            pop.volume_changed.connect(lambda v: self._player.set_volume(v/100))
            pop.delay_changed.connect(self._on_delay_change)
            pop.inertia_changed.connect(self._on_inertia_change)
            pop.brightness_changed.connect(self._on_brightness_change)
            pop.viz_type_changed.connect(self._on_viz_type_change)
            pop.cover_toggled.connect(self._on_cover_toggle)
            pop.cover_accent_toggled.connect(self._on_cover_acc_toggle)
            pop.accent_changed.connect(self._on_accent_change)
            # lyrics_fetch_toggled gates LyricsPanel; no ControlBar handler needed
            pop.overlay_viz_toggled.connect(self.set_overlay_viz_enabled)
            pop.overlay_viz_toggled.connect(
                lambda on: getattr(self, '_blackout_ref', None) and
                           self._blackout_ref.set_overlay_viz(on))
            pop.overlay_lyrics_toggled.connect(
                lambda on: getattr(self, '_blackout_ref', None) and
                           self._blackout_ref.set_overlay_lyrics(on))
            pop.overlay_scale_changed.connect(
                lambda v: getattr(self, '_blackout_ref', None) and
                          self._blackout_ref.set_scale(v))
            pop.overlay_auto_open_toggled.connect(self._on_overlay_auto_open_toggle)
            pop.overlay_timeout_changed.connect(self._on_overlay_timeout_change)
            pop.overlay_clock_toggled.connect(
                lambda on: getattr(self, '_blackout_ref', None) and
                           self._blackout_ref.set_overlay_clock(on))
            pop.cover_fetch_toggled.connect(self._on_cover_fetch_btn)
            pop.lyric_fetch_action.connect(self._on_lyric_fetch_btn)
            pop.tag_fetch_toggled.connect(self._on_tag_fetch_btn)
            pop.rename_toggled.connect(self._on_rename_btn)
            pop.radius_changed.connect(self._on_radius_change)
            pop.output_device_changed.connect(self._player.set_output_device)
            pop.output_device_changed.connect(lambda _: self._refresh_audio_info())
            # Sync volume slider when Player changes volume programmatically (e.g. ALSA auto-vol)
            self._player.sig_volume_changed.connect(pop.set_volume)
            # Notify MainWindow to run the ALSA probe when the device changes.
            # Must be connected here (lazy popup creation) — MainWindow's __init__
            # guard `if _settings_popup is not None` always fails at startup.
            win = self.window()
            if win is not None and hasattr(win, '_on_output_device_changed'):
                pop.output_device_changed.connect(win._on_output_device_changed)
            if not self._player.has_spectrum:
                pop._viz_sw.setEnabled(False); pop._log_sw.setEnabled(False)
            # Auto-save on every setting change
            _save_sigs = [
                pop.viz_toggled, pop.log_toggled, pop.volume_changed,
                pop.delay_changed, pop.inertia_changed, pop.brightness_changed,
                pop.cover_toggled, pop.accent_changed, pop.lyrics_fetch_toggled,
                pop.overlay_viz_toggled, pop.overlay_lyrics_toggled,
                pop.overlay_clock_toggled,
                pop.overlay_scale_changed, pop.overlay_auto_open_toggled,
                pop.overlay_timeout_changed, pop.view_mode_changed,
                pop.list_scale_changed, pop.gallery_scale_changed,
                pop.radius_changed, pop.output_device_changed,
            ]
            for sig in _save_sigs:
                sig.connect(lambda *_: self.settings_changed.emit())
            # Theme switch emits via _on_theme_toggle → connect directly
            pop._theme_sw.toggled.connect(lambda *_: self.settings_changed.emit())
            self._settings_popup = pop
        return self._settings_popup

    def _refresh_audio_info(self):
        """Update the AUDIO INFO labels in SettingsPopup from current player state.

        Reads format/EQ/device from the Player and the current track; writes to
        the four _info_* QLabels that live in SettingsPopup's left column.
        Safe to call when the popup does not yet exist (no-op) or when no track
        is loaded (shows '—' placeholders).
        """
        pop = self._settings_popup
        if pop is None:
            return

        # ── Format ────────────────────────────────────────────────────────────
        track = self._cur_track   # set by ControlBar._on_track_change
        if track is not None:
            parts = []
            if track.sample_rate:
                parts.append(f'{track.sample_rate / 1000:.1f} kHz')
            if track.bit_depth:
                parts.append(f'{track.bit_depth}-bit')
            if track.filepath:
                ext = track.filepath.rsplit('.', 1)[-1].upper() if '.' in track.filepath else ''
                if ext:
                    parts.append(ext)
            fmt_str = '  ·  '.join(parts) if parts else '—'
        else:
            fmt_str = '—'
        pop._info_fmt.setText(fmt_str)

        # ── DSP (EQ + Limiter + Stereo, separated by |) ────────────────
        eq_pop = self._eq_popup
        eq_profile = getattr(eq_pop, '_current_profile', '') if eq_pop is not None else ''
        dsp_parts = []
        if self._player._eq_enabled:
            bands_str = f'{len(self._player._eq_bands)}b' if self._player._eq_bands else ''
            eq_str = f'EQ({bands_str})' if bands_str else 'EQ'
            if eq_profile:
                eq_str += f' · {eq_profile}'
            dsp_parts.append(eq_str)
        if self._player._limiter_enabled:
            dsp_parts.append('Lim')
        # Stereo Expand — added to dsp_parts so | separates everything
        if self._player._stereo_enabled:
            width = self._player._stereo_width
            width_str = f'+{width}' if width > 0 else str(width)
            dsp_parts.append(f'Exp · {width_str}')
        dsp_text = ' | '.join(dsp_parts) if dsp_parts else 'Off'
        pop._info_eq.setText(dsp_text)
        pop._info_stereo.setText('')   # now shown inside _info_eq

        # ── Output / Device ──────────────────────────────────────────
        dev = self._player._alsa_device
        if not self._player._is_hw_device(dev):
            pop._info_dev.setText('PipeWire')
        else:
            idx = pop._out_dev_combo.findData(dev)
            if idx >= 0:
                pop._info_dev.setText(pop._out_dev_combo.itemText(idx))
            else:
                pop._info_dev.setText(dev)

    @property
    def lyrics_fetch_enabled(self) -> bool:
        pop = self._settings_popup
        return pop.lyrics_fetch_on() if pop else True

    def cover_on(self) -> bool:
        """Return current state of the Cover switch (default True if popup not yet created)."""
        pop = self._settings_popup
        return pop.cover_on() if pop else True

    # lyrics_fetch_toggled merely gates LyricsPanel.set_track() — that method
    # reads self._ctrlbar.lyrics_fetch_enabled at call time, so no handler needed.

    def _on_overlay_auto_open_toggle(self, on: bool):
        self._overlay_auto_open = on
        if on:
            self._idle_timer.start()
        else:
            self._idle_timer.stop()

    def _on_overlay_timeout_change(self, secs: int):
        self._overlay_timeout_ms = secs * 1000
        self._idle_timer.setInterval(self._overlay_timeout_ms)

    def _reset_idle_timer(self):
        """Restart idle countdown — called on focus gain, mouse move >5px, key press,
        or play/pause action. No-op when overlay is visible or auto-open is disabled."""
        if not self._overlay_auto_open:
            return
        bref = getattr(self, '_blackout_ref', None)
        if bref is not None and bref.isVisible():
            return  # overlay is open; don't restart until dismissed
        self._idle_timer.start()   # start() on a running timer restarts it

    def _on_idle_timeout(self):
        """Fired when app has been focused and idle for the configured timeout."""
        bref = getattr(self, '_blackout_ref', None)
        if bref is None:
            return
        if bref.isVisible():
            return
        # Only auto-open while app is actually in the foreground
        win = self.window()
        if win and win.isActiveWindow():
            bref.show_blackout()

    def ensure_overlay_spec(self):
        """Called when overlay opens — restart spectrum if needed."""
        self._player.set_overlay_needs_spectrum(True)

    def set_overlay_viz_enabled(self, on: bool):
        self._overlay_viz_enabled = on
        self._player._viz_overlay_cb = self._overlay_cb if on else None
        if not on:
            self._player.set_overlay_needs_spectrum(False)
            # If overlay is currently open, we just lost the only reason to render
            if self._overlay_open or not self._viz_on:
                self._render_timer.stop()
        elif self._overlay_open and self._player.playing and not self._viz_paused:
            # Overlay viz just turned on while overlay is visible — start rendering
            self._start_render_timer()

    def set_overlay_open(self, open: bool):
        """Called by BlackoutOverlay on show/dismiss.

        When the overlay is open and overlay viz is disabled, the ControlBar is
        completely covered and there is nothing to render.  Stop the render timer
        to avoid running _compute_viz_frame + self.update() at 60 fps for zero
        visible effect.  Resume the timer when the overlay is dismissed so the
        main viz picks up immediately.
        """
        self._overlay_open = open
        if open and not self._overlay_viz_enabled:
            # Overlay covers everything and overlay viz is off — rendering is wasted
            self._render_timer.stop()
        elif not open and self._viz_on and not self._viz_paused and self._player.playing:
            # Overlay dismissed — restart main viz if it should be running
            self._start_render_timer()

    def set_blackout_ref(self, overlay):
        self._blackout_ref = overlay
        if overlay is not None:
            overlay._ctrlbar_ref = self

    def _on_cover_fetch_btn(self):
        """Open the CoverFetchPopup — triggered by the Settings button."""
        win = self.window()
        pages = []
        if hasattr(win, '_lib_page') and win._lib_page:
            pages = [win._lib_page] + list(getattr(win, '_playlists', []))
        all_tracks = list(win._lib_page.tracks) if hasattr(win, '_lib_page') and win._lib_page else []
        if not all_tracks:
            QMessageBox.information(win, 'No Tracks', 'Add a folder to the library first.')
            return
        if self._settings_popup: self._settings_popup.hide()
        
        # Check if there's already a cover fetch running in background
        workers_list = _BaseFetchPopup._active_workers.get('CoverFetchPopup', [])
        if workers_list:
            # Show the most recent existing popup instead of creating a new one
            old_instance, old_worker, old_thread = workers_list[-1]
            old_instance.show()
            old_instance.raise_()
            old_instance.activateWindow()
            return
        
        dlg = CoverFetchPopup(all_tracks, pages, self, parent=win)
        _ModalOverlay.show_for(dlg)
        dlg.show()

    def _on_lyric_fetch_btn(self):
        """Open the LyricsFetchPopup — triggered by the Settings button."""
        win = self.window()
        all_tracks = list(win._lib_page.tracks) if hasattr(win, '_lib_page') and win._lib_page else []
        if not all_tracks:
            QMessageBox.information(win, 'No Tracks', 'Add a folder to the library first.')
            return
        if self._settings_popup: self._settings_popup.hide()
        
        # Check if there's already a lyrics fetch running in background
        workers_list = _BaseFetchPopup._active_workers.get('LyricsFetchPopup', [])
        if workers_list:
            # Show the most recent existing popup instead of creating a new one
            old_instance, old_worker, old_thread = workers_list[-1]
            old_instance.show()
            old_instance.raise_()
            old_instance.activateWindow()
            return
        
        dlg = LyricsFetchPopup(all_tracks, parent=win)
        _ModalOverlay.show_for(dlg)
        dlg.show()

    def _on_tag_fetch_btn(self):
        win = self.window()
        all_tracks = list(win._lib_page.tracks) if hasattr(win, '_lib_page') and win._lib_page else []
        if not all_tracks:
            QMessageBox.information(win, 'No Tracks', 'Add a folder to the library first.')
            return
        if self._settings_popup: self._settings_popup.hide()
        
        # Check if there's already a tag fetch running in background
        workers_list = _BaseFetchPopup._active_workers.get('TagFetchPopup', [])
        if workers_list:
            # Show the most recent existing popup instead of creating a new one
            old_instance, old_worker, old_thread = workers_list[-1]
            old_instance.show()
            old_instance.raise_()
            old_instance.activateWindow()
            return
        
        dlg = TagFetchPopup(all_tracks, parent=win)
        dlg.tags_updated.connect(lambda fp, tags: win._on_tags_fetched(fp, tags))
        _ModalOverlay.show_for(dlg)
        dlg.show()

    def _on_rename_btn(self):
        """Open the RenamePopup — triggered by the Settings 'Rename…' button.

        After the dialog closes (finished OR cancelled) we:
          1. Update M3U8 files that reference any renamed path
          2. Save config (known_paths, playlists)
          3. Rescan every known folder/m3u so the library reflects new filenames
        """
        
        def _on_rename_finished(renamed, total):
            """Handle rename completion after dialog finishes."""
            win = self.window()
            rename_map = dlg.rename_map
            if not rename_map:
                return   # nothing was renamed — no need to rescan

            # 1. Rewrite any M3U8 files that reference renamed paths
            for pl in getattr(win, '_playlists', []):
                if not hasattr(pl, '_m3u_path'):
                    continue
                m3u_path = pl._m3u_path
                try:
                    with open(m3u_path, encoding='utf-8', errors='replace') as fh:
                        lines = fh.readlines()
                    new_lines = []
                    changed = False
                    for line in lines:
                        stripped = line.rstrip('\n\r')
                        if stripped in rename_map:
                            new_lines.append(rename_map[stripped] + '\n')
                            changed = True
                        else:
                            new_lines.append(line)
                    if changed:
                        with open(m3u_path, 'w', encoding='utf-8') as fh:
                            fh.writelines(new_lines)
                except Exception as exc:
                    print(f'M3U8 update error ({m3u_path}): {exc}')

            # 2. Update known_paths for any direct-file entries that were renamed
            for old, new in rename_map.items():
                if old in win._known_paths:
                    win._known_paths.discard(old)
                    win._known_paths.add(new)

            # 2b. Patch live player state so the playing track keeps its accent
            # indicator and lyrics panel after the rescan produces new Track objects.
            # Without this, _rebuild_library can't match the old filepath to the
            # rebuilt track list (pidx stays -1) and the lyrics panel fetches
            # lyrics for the now-gone old path ("does not contain lyrics").
            ctrlbar = getattr(win, '_ctrlbar', None)
            player  = getattr(win, '_player', None)
            if player and player._last_filepath in rename_map:
                player._last_filepath = rename_map[player._last_filepath]
            if ctrlbar and getattr(ctrlbar, '_cur_track', None):
                old_fp = ctrlbar._cur_track.filepath
                if old_fp in rename_map:
                    ctrlbar._cur_track.filepath = rename_map[old_fp]
            if getattr(win, '_cur_track_mw', None):
                old_fp = win._cur_track_mw.filepath
                if old_fp in rename_map:
                    win._cur_track_mw.filepath = rename_map[old_fp]

            # 3. Save config
            if hasattr(win, '_save_config'):
                win._save_config()

            # 4. Rescan all known paths to pick up renamed files
            win._status.showMessage('Rename complete — refreshing library…')
            _cover_cache.clear()
            if hasattr(win, '_refresh_library'):
                win._refresh_library()

        win = self.window()
        all_tracks = list(win._lib_page.tracks) if hasattr(win, '_lib_page') and win._lib_page else []
        if not all_tracks:
            QMessageBox.information(win, 'No Tracks', 'Add a folder to the library first.')
            return
        if self._settings_popup:
            self._settings_popup.hide()
        
        # Check if there's already a rename operation running in background
        existing = RenamePopup._active_worker
        if existing:
            old_instance, old_worker, old_thread = existing
            # Show the existing popup instead of creating a new one
            old_instance.show()
            old_instance.raise_()
            old_instance.activateWindow()
            return
        
        dlg = RenamePopup(all_tracks, parent=win)
        dlg._post_finish_cb = _on_rename_finished
        _ModalOverlay.show_for(dlg)
        dlg.show()

    def _toggle_fullscreen(self):
        win = self.window()
        if win.isFullScreen():
            win.showMaximized()
            self.btn_fullscreen.set_fullscreen(False)
        else:
            win.showFullScreen()
            self.btn_fullscreen.set_fullscreen(True)

    def _toggle_settings(self):
        pop = self._ensure_settings_popup()
        # If this toggle was triggered by the same click that closed the popup
        # (eventFilter hides it, then the button's clicked signal fires), suppress
        # the re-open.  150 ms is generous; the two events arrive within ~1 ms.
        now = QDateTime.currentMSecsSinceEpoch()
        if now - pop._hide_timestamp_ms < 150:
            pop._hide_timestamp_ms = 0
            return
        if pop.isVisible():
            pop.hide()
        else:
            self._refresh_audio_info()
            pop.show_above(self.btn_settings)

    @staticmethod
    def _coerce_bands(bands) -> list:
        """Coerces freq/gain/Q/type values to correct Python types.

        Accepts both legacy 3-element [freq, gain, Q] and new
        4-element [freq, gain, Q, type] band lists.  Missing type
        defaults to EQ_TYPE_PEAK (0).
        """
        result = []
        for b in bands:
            try:
                result.append([
                    float(b[0]),
                    float(b[1]),
                    float(b[2]),
                    int(b[3]) if len(b) >= 4 else EQ_TYPE_PEAK,
                ])
            except (TypeError, ValueError, IndexError):
                pass
        return result

    def init_from_config(self, cfg: dict):
        # Settings popup — safely coerce numeric values that JSON may deserialize as strings
        pop = self._ensure_settings_popup()
        volume  = int(float(cfg.get('volume',       80)))
        delay   = int(float(cfg.get('viz_delay_ms',  0)))
        _raw_inertia = int(float(cfg.get('inertia', 50)))
        inertia = max(10, min(100, _raw_inertia))
        bright  = int(float(cfg.get('brightness',    40)))
        pop.set_volume(volume)
        pop.set_delay(delay)
        pop.set_inertia(inertia)
        viz = cfg.get('viz_on', True); log = cfg.get('log_on', True)
        pop.set_viz(viz); pop.set_log(log)
        self._on_viz_toggle(viz); self._on_log_toggle(log)
        self._on_delay_change(delay)
        self._on_inertia_change(inertia)
        acc_color = cfg.get('accent_color', ACC)
        pop.set_accent_color(acc_color)
        if acc_color != '#e03030': self._on_accent_change(acc_color)
        pop.set_brightness(bright); self._on_brightness_change(bright)
        cover = cfg.get('cover_on', True)
        pop.set_cover(cover); self._on_cover_toggle(cover)
        cover_acc = cfg.get('cover_accent', False)
        pop.set_cover_accent(cover_acc)
        self._cover_acc_on = cover_acc
        global _COVER_ACC_ON; _COVER_ACC_ON = cover_acc
        import cover_art as _cover_art_mod; _cover_art_mod._COVER_ACC_ON = cover_acc
        if cover_acc:
            self._cover_lbl.set_cover_accent_mode(True)
        pop.set_lyrics_fetch(cfg.get('lyrics_fetch_on', True))
        _ov_viz = cfg.get('overlay_viz', False)
        _ov_lyr = cfg.get('overlay_lyrics', False)
        _ov_clk = cfg.get('overlay_clock', True)
        _ov_sc  = int(float(cfg.get('overlay_scale', 100)))
        _ov_auto = cfg.get('overlay_auto_open', False)
        _ov_tout = int(float(cfg.get('overlay_timeout', 60)))
        pop.set_overlay_viz(_ov_viz)
        pop.set_overlay_lyrics(_ov_lyr)
        pop.set_overlay_clock(_ov_clk)
        pop.set_overlay_scale(_ov_sc)
        pop.set_overlay_auto_open(_ov_auto)
        pop.set_overlay_timeout(_ov_tout)
        self.set_overlay_viz_enabled(_ov_viz)
        self._overlay_auto_open  = _ov_auto
        self._overlay_timeout_ms = _ov_tout * 1000
        self._idle_timer.setInterval(self._overlay_timeout_ms)
        if _ov_auto:
            self._idle_timer.start()   # restore: start timer immediately
        if hasattr(self, '_blackout_ref') and self._blackout_ref:
            self._blackout_ref.set_overlay_viz(_ov_viz)
            self._blackout_ref.set_overlay_lyrics(_ov_lyr)
            self._blackout_ref.set_overlay_clock(_ov_clk)
            self._blackout_ref.set_scale(_ov_sc)
        _cover_fetch = cfg.get('cover_fetch_on', True)
        pop.set_cover_fetch(_cover_fetch)
        global _cover_fetch_on; _cover_fetch_on = _cover_fetch
        self._player.set_volume(volume / 100)
        # Corner radius — restore before theme so the first stylesheet is correct
        _rad = int(float(cfg.get('corner_radius', RAD_PCT)))
        pop.set_radius(_rad)
        self._on_radius_change(_rad)

        # Theme (dark/light) — load before accent so the stylesheet is correct
        _vtype = cfg.get('viz_type', 'bars')
        pop.set_viz_type(_vtype)
        self._on_viz_type_change(_vtype)
        _dark = cfg.get('dark_mode', True)
        pop.set_dark_mode(_dark)
        if not _dark:
            apply_theme(dark=False)
        # System Qt theme override — actual apply_system_qt_theme() call
        # happens earlier in MainWindow._load_config (before init_from_config)
        # so palette globals are correct by the time widgets build; here we
        # just sync the popup's toggle to reflect that state.
        pop.set_system_theme(cfg.get('use_system_qt_theme', False))

        # View mode + scale sliders
        _vm = cfg.get('view_mode', 'classic')

        # Output device — restore silently (no pipeline reload during startup).
        # Re-probe available ALSA devices at startup; if the saved device id is
        # no longer present (card unplugged, renumbered) fall back to PipeWire
        # so the user is not left with a broken/silent sink on next launch.
        _saved_dev = cfg.get('output_device', 'pipewire')
        if Player._is_hw_device(_saved_dev):
            _available_ids = {dev_id for _, dev_id in SettingsPopup._probe_alsa_devices()}
            if _saved_dev not in _available_ids:
                print(f'[Config] saved output device {_saved_dev!r} not found — falling back to PipeWire')
                _saved_dev = 'pipewire'  # fallback sentinel
        # When an ALSA device is saved, start the pipeline on hw:X,Y derived from
        # the saved plughw:X,Y — so probe targets the correct card, not hw:0,0.
        # plughw:X,Y is used as the fallback if hw:X,Y fails.
        if Player._is_hw_device(_saved_dev):
            _pipeline_dev = _saved_dev.replace('plughw:', 'hw:', 1)
        else:
            _pipeline_dev = 'pipewire'
        pop.set_output_device(_saved_dev)          # combo shows saved card name
        self._player._alsa_device = _pipeline_dev  # pipeline starts on hw:X,Y
        print(f'[AudioSwitch] startup: combo={_saved_dev!r}, pipeline device={_pipeline_dev!r}')
        # Pre-confirm hw:X,Y as the optimistic default immediately.
        # The real probe runs on first _alsa_play() which validates it with audio.
        if Player._is_hw_device(_pipeline_dev):
            win = self.window()
            win._alsa_confirmed_device = _pipeline_dev   # hw:X,Y (correct card)
            win._alsa_selected_plughw  = _saved_dev      # plughw:X,Y (user's choice)
            win._alsa_probe_needed     = True            # probe on next play
        if _vm == 'gallery':
            _vm = 'gallery_z'
        _ls = int(float(cfg.get('list_scale', 44)))
        _gs = int(float(cfg.get('gallery_scale', 130)))
        pop.set_view_mode(_vm)
        pop.set_list_scale(_ls)
        pop.set_gallery_scale(_gs)
        # Propagate to pages (deferred so pages are fully built)
        QTimer.singleShot(0, lambda: self._apply_view_settings(_vm, _ls, _gs))

        # EQ popup profiles and default state
        eq_pop = self._ensure_eq_popup()
        raw_profiles = cfg.get('eq_profiles', {})
        eq_profiles = {}
        for k, v in raw_profiles.items():
            if isinstance(v, dict):
                # New format: {bands: [...], preamp: float}
                eq_profiles[k] = {'bands':  self._coerce_bands(v.get('bands', [])),
                                   'preamp': float(v.get('preamp', 0.0))}
            else:
                # Legacy format: plain band list
                eq_profiles[k] = {'bands': self._coerce_bands(v), 'preamp': 0.0}
        eq_pop.set_profiles(eq_profiles)

        # Load default EQ (if any) and apply it
        default_bands   = self._coerce_bands(cfg.get('default_eq_bands', []))
        default_enabled = cfg.get('default_eq_enabled', True)
        default_name    = cfg.get('default_eq_profile', '')
        eq_pop.set_default(default_bands, default_enabled, default_name)
        eq_pop.set_bands(default_bands, default_enabled, default_name)
        # Apply to player
        self._player.set_eq_enabled(default_enabled)
        self._player.set_eq_bands(default_bands)

        # Limiter, stereo enhance
        _lim  = cfg.get('limiter_enabled', False)
        _ste  = cfg.get('stereo_enabled',  False)
        _stw  = int(float(cfg.get('stereo_width', 50)))
        eq_pop.set_limiter_enabled(_lim)
        eq_pop.set_stereo_enabled(_ste)
        eq_pop.set_stereo_width(_stw)
        self._player._limiter_enabled = _lim
        self._player._stereo_enabled  = _ste
        self._player._stereo_width    = _stw

        _preamp = float(cfg.get('eq_preamp_db', 0.0))
        eq_pop.set_preamp_db(_preamp)
        self._player._preamp_db = _preamp

    def _apply_view_settings(self, mode: str, list_scale: int, gallery_scale: int):
        """Emit view signals so MainWindow can propagate to all pages."""
        pop = self._ensure_settings_popup()
        pop.view_mode_changed.emit(mode)
        pop.list_scale_changed.emit(list_scale)
        pop.gallery_scale_changed.emit(gallery_scale)

    def config_state(self) -> dict:
        cfg = {}
        pop = self._ensure_settings_popup()
        cfg.update({'volume': pop.volume(), 'viz_delay_ms': pop.delay(),
                    'viz_on': pop.viz_on(), 'log_on': pop.log_on(),
                    'overlay_viz': pop.overlay_viz_on(),
                    'overlay_lyrics': pop.overlay_lyrics_on(),
                    'overlay_clock': pop.overlay_clock_on(),
                    'overlay_scale': pop.overlay_scale(),
                    'overlay_auto_open': pop.overlay_auto_open(),
                    'overlay_timeout': pop.overlay_timeout(),
                    'inertia': pop.inertia(), 'brightness': pop.brightness(),
                    'cover_on': pop.cover_on(), 'accent_color': pop.accent_color(),
                    'cover_accent': pop.cover_accent_on(),
                    'lyrics_fetch_on': pop.lyrics_fetch_on(),
                    'cover_fetch_on': pop.cover_fetch_on(),
                    'view_mode': pop.view_mode(),
                    'list_scale': pop.list_scale(),
                    'gallery_scale': pop.gallery_scale(),
                    'dark_mode': pop.dark_mode_on(),
                    'use_system_qt_theme': pop.system_theme_on(),
                    'viz_type': pop.viz_type(),
                    'corner_radius': pop.radius(),
                    'output_device': pop.output_device()})
        eq_pop = self._ensure_eq_popup()
        cfg['eq_profiles'] = eq_pop.get_profiles()
        default_bands, default_enabled = eq_pop.get_default()
        cfg['default_eq_bands'] = default_bands
        cfg['default_eq_enabled'] = default_enabled
        cfg['default_eq_profile'] = eq_pop.get_default_name()
        cfg['limiter_enabled']    = eq_pop.limiter_enabled()
        cfg['stereo_enabled']     = eq_pop.stereo_enabled()
        cfg['stereo_width']       = eq_pop.stereo_width()
        cfg['eq_preamp_db']       = eq_pop.preamp_db()
        return cfg

    def _precompute_bars(self):
        dpr = self.devicePixelRatio()
        iw = round(self.width() * dpr)
        if iw < 2: return

        # ── Integer bar geometry: all bars same width, exactly 1px gap ─────────
        # bw * VIZ_BANDS + 1 * (VIZ_BANDS-1) = total_used
        bw = max(1, (iw - (VIZ_BANDS - 1)) // VIZ_BANDS)
        total_used = bw * VIZ_BANDS + (VIZ_BANDS - 1)
        offset = max(0, (iw - total_used) // 2)   # center the bar group

        # ── Bar x0 array — vectorized ─────────────────────────────────────────────
        bar_x0 = (_np.arange(VIZ_BANDS, dtype=_np.int32) * (bw + 1) + offset)
        self._bar_x0 = bar_x0
        self._bar_bw  = bw

        # ── Column→bar mapping — fully vectorized (no Python loop) ────────────────
        col_bar = _np.full(iw, -1, dtype=_np.int32)
        bar_cols = (bar_x0[:, None]
                    + _np.arange(bw, dtype=_np.int32)[None, :]).ravel()
        bar_ids  = _np.repeat(_np.arange(VIZ_BANDS, dtype=_np.int32), bw)
        in_bounds = bar_cols < iw
        col_bar[bar_cols[in_bounds]] = bar_ids[in_bounds]
        self._col_bar      = col_bar
        self._col_has_bar  = (col_bar >= 0)
        self._col_bar_safe = _np.maximum(col_bar, 0)

        # ── Cap pixel offset arrays — fully vectorized ────────────────────────────
        # Round caps are disabled when the global corner-radius is below 50 %
        radius = (bw // 2) if RAD_PCT >= 50 else 0
        if radius > 0 and bw >= 2:
            cx   = (bw - 1) * 0.5
            r2   = float(radius * radius)
            rows = _np.arange(radius, dtype=_np.float64)
            dy   = radius - rows - 0.5
            dx2  = r2 - dy * dy
            valid = dx2 > 0.0
            if valid.any():
                row_v = rows[valid].astype(_np.int32)
                dx_v  = _np.sqrt(dx2[valid])
                xl_v  = _np.maximum(0,  _np.ceil (cx - dx_v).astype(_np.int32))
                xr_v  = _np.minimum(bw, _np.floor(cx + dx_v).astype(_np.int32) + 1)
                widths = (xr_v - xl_v).astype(_np.int32)
                total  = int(widths.sum())
                # Build col offsets: for each row ri, cols = xl_v[ri] + [0..widths[ri]-1]
                cum = _np.zeros(len(widths) + 1, dtype=_np.int32)
                _np.cumsum(widths, out=cum[1:])
                col_range  = _np.arange(total, dtype=_np.int32)
                group_off  = _np.repeat(cum[:-1], widths)
                self._cap_r_offsets = _np.repeat(row_v, widths)
                self._cap_c_offsets = _np.repeat(xl_v, widths) + (col_range - group_off)
                self._cap_radius    = radius
            else:
                self._cap_r_offsets = _np.empty(0, dtype=_np.int32)
                self._cap_c_offsets = _np.empty(0, dtype=_np.int32)
                self._cap_radius    = 0
        else:
            self._cap_r_offsets = _np.empty(0, dtype=_np.int32)
            self._cap_c_offsets = _np.empty(0, dtype=_np.int32)
            self._cap_radius    = 0

        # ── Freq mapping and smooth tables ────────────────────────────────────
        if getattr(self, '_log_scale', True):
            F_MIN = 20.0; F_MAX = 20000.0
            FS_HALF = self._player.current_fs / 2.0
            FULL_HZ = 20.0; FADE_HZ = 60.0
            log_min = math.log10(F_MIN); log_max = math.log10(F_MAX)

            # ── Vectorized freq array ─────────────────────────────────────────
            d_arr     = _np.arange(VIZ_BANDS, dtype=_np.float64)
            log_range = log_max - log_min
            f_lo      = _np.power(10.0, log_min + d_arr / VIZ_BANDS * log_range)
            f_hi      = _np.power(10.0, log_min + (d_arr + 1) / VIZ_BANDS * log_range)
            fc_hz_arr = _np.sqrt(f_lo * f_hi)
            fracs_arr = fc_hz_arr * GST_BANDS / FS_HALF

            # ── Vectorized interp tables ──────────────────────────────────────
            ba_arr = _np.clip(fracs_arr.astype(_np.int32), 0, GST_BANDS - 1)
            bb_arr = _np.minimum(ba_arr + 1, GST_BANDS - 1)
            bt_arr = (fracs_arr - ba_arr.astype(_np.float64)).astype(_np.float32)

            # ── Vectorized run_len_at ─────────────────────────────────────────
            changes  = _np.concatenate(([True], ba_arr[1:] != ba_arr[:-1], [True]))
            run_ends = _np.flatnonzero(changes)         # boundaries between runs
            run_lens = _np.diff(run_ends)               # length of each run
            run_id   = (_np.searchsorted(run_ends[:-1],
                         _np.arange(VIZ_BANDS, dtype=_np.int32),
                         side='right') - 1)
            run_len_arr = run_lens[run_id]              # (VIZ_BANDS,) run length per bar

            fc_hz_list  = fc_hz_arr.tolist()
            run_len_list = run_len_arr.tolist()
            smooth_w = []
            for d in range(VIZ_BANDS):
                fc = fc_hz_list[d]; rl = run_len_list[d]
                if fc >= FADE_HZ or rl <= 1:
                    smooth_w.append(None)
                else:
                    strength = (1.0 if fc < FULL_HZ
                                else 1.0 - (fc - FULL_HZ) / (FADE_HZ - FULL_HZ))
                    hw = max(1, int((rl // 2) * strength))
                    lo = max(0, d - hw); hi = min(VIZ_BANDS - 1, d + hw)
                    n  = hi - lo + 1
                    smooth_w.append(tuple((nb, 1.0 / n) for nb in range(lo, hi + 1)))
        else:
            FS_HALF   = self._player.current_fs / 2.0
            lin_scale = (20000.0 / FS_HALF) * GST_BANDS / VIZ_BANDS

            # ── Vectorized linear interp ──────────────────────────────────────
            fracs_arr = _np.arange(VIZ_BANDS, dtype=_np.float64) * lin_scale
            ba_arr    = _np.clip(fracs_arr.astype(_np.int32), 0, GST_BANDS - 1)
            bb_arr    = _np.minimum(ba_arr + 1, GST_BANDS - 1)
            bt_arr    = (fracs_arr - ba_arr.astype(_np.float64)).astype(_np.float32)
            smooth_w  = []

        entries = []
        for d, sw in enumerate(smooth_w):
            if sw is not None:
                nb_arr = _np.array([nb for nb, _ in sw], dtype=_np.int32)
                wk_arr = _np.array([wk for _, wk in sw], dtype=_np.float32)
                entries.append((d, (nb_arr, wk_arr)))

        self._player.set_viz_tables(
            ba_arr, bb_arr, bt_arr, col_bar, entries,
            self._inertia,
            overlay_cb=self._overlay_cb if self._overlay_viz_enabled else None
        )

        self._paint_bar_px     = _np.zeros(VIZ_BANDS, dtype=_np.int32)

        # ── Line-mode: cache per-width arrays (avoid per-frame allocation) ────────
        # All of these are constant for a given widget width. Computed once here
        # (on resize/init) so paintEvent allocates nothing for the interpolation step.
        self._line_col_x_i = _np.arange(iw, dtype=_np.int32)   # column indices for buf[y, col]
        self._line_cy_buf  = _np.empty(VIZ_BANDS, dtype=_np.float64)  # reusable (ih - bar_px) buf
        self._line_y_int   = _np.empty(iw, dtype=_np.int32)     # reusable per-column y output

        # Precompute uniform linear-interp tables that replace np.interp per frame.
        # cx_arr = linspace(0, iw-1, VIZ_BANDS) is uniform, so the mapping
        #   bin_f[x] = x * (VIZ_BANDS-1) / (iw-1)
        # can be split into cached integer floor (bin_i) and fractional part (bin_f)
        # arrays — both of shape (iw,).  Per frame: two gathers + one fused-multiply-add.
        _bin_scale        = float(VIZ_BANDS - 1) / max(1, iw - 1)
        _bf               = _np.arange(iw, dtype=_np.float32) * _bin_scale
        self._line_bin_i  = _np.clip(_bf.astype(_np.int32), 0, VIZ_BANDS - 2)
        self._line_bin_i1 = self._line_bin_i + 1                         # (iw,) int32
        self._line_bin_f  = (_bf - self._line_bin_i).astype(_np.float32) # (iw,) frac [0,1)

    def _start_render_timer(self):
        """Start the fixed-rate render timer with a fresh deadline."""
        self._render_timer.setInterval(_FRAME_MS)
        _gc.disable()   # prevent GC pauses during render loop
        self._render_timer.start()

    def _on_viz_toggle(self, on: bool):
        self._viz_on = on
        # GStreamer spectrum stays active if either main viz or overlay viz needs it
        self._player.set_viz_active(on and not self._viz_paused)
        if on and self._player.playing and not self._viz_paused:
            self._start_render_timer()
        else:
            # Only stop the render timer if overlay viz is also off
            if not self._overlay_viz_enabled:
                self._render_timer.stop()
            self._player._viz_spec[:] = MIN_DB
        self.update()

    def _on_log_toggle(self, on: bool):
        self._log_scale = on
        # Flush stale bar data so the old mapping does not bleed into the first
        # frame rendered with the new freq->bin tables.
        self._player._viz_bar_buf[:] = 0.0
        self._player._viz_spec[:]    = MIN_DB
        self._precompute_bars()
        self.update()

    def _on_delay_change(self, v: int):
        self._delay_ms = v
        # Reset ring buffer so stale frames from the old delay don't linger.
        # The buffer will fill within ~70 frames (≈1 s at 60 fps); until then
        # _render_tick mirrors the live frame directly (best_idx == -1 path).
        self._viz_rbuf_head  = 0
        self._viz_rbuf_count = 0

    def _overlay_cb(self, bh_list):
        """Called from GLib thread when overlay viz is active."""
        _bref = getattr(self, '_blackout_ref', None)
        if _bref is not None:
            _bref.push_viz_frame(bh_list)

    def _on_inertia_change(self, v: int):
        # Slider value / 100.0 = alpha directly (40→0.40, 100→1.0)
        self._inertia = v / 100.0
        self._player._viz_inertia = self._inertia

    def _on_brightness_change(self, v: int):
        self._brightness_v = v
        t = v / 100.0          # 0.0 → 1.0

        acc  = QColor(ACC)
        ah, as_, al, _ = acc.getHsvF()

        if _DARK_MODE:
            # Dark: dim desaturated accent (t=0) → vivid accent (t=1)
            # Never goes to black — minimum luma is 15% of accent luma
            luma  = max(0.10, al * (0.15 + 0.85 * t))
            tint  = QColor()
            sat   = as_ * (0.50 + 0.50 * t)
            tint.setHsvF(ah, sat, luma)
        else:
            # Light mode: mix between bg-tinted desaturated accent (t=0)
            # and a readable vivid accent (t=1). Never pure white or pure black.
            # t=0: hue preserved, very low sat, value close to BG lightness
            bg_l  = QColor(BG).lightnessF()
            v0    = max(0.50, bg_l * 0.90)         # near-BG tone, never white
            s0    = as_ * 0.20
            v1    = max(0.30, al * 0.65)            # vivid but not too dark
            s1    = as_ * 0.85
            tint  = QColor()
            tint.setHsvF(ah, s0 + t * (s1 - s0), v0 + t * (v1 - v0))

        self._bar_color = tint
        self.update()

    def _on_viz_type_change(self, vtype: str):
        self._viz_type = vtype
        # Invalidate pixel buffer so line mode allocates a fresh ARGB buffer
        self._px_shape = (0, 0)
        self.update()

    def _on_radius_change(self, v: int):
        """User moved the Corners slider.

        During live interaction (window visible): show a full-screen overlay
        immediately, then debounce the heavy stylesheet rebuild so it fires
        once after the user stops dragging — not on every pixel.

        During config restore (window not yet visible): apply silently and
        immediately so the first paint already has the correct radii.
        """
        import constants as _cm
        global RAD_PCT
        RAD_PCT = max(0, min(100, v))
        # Broadcast into constants module and every other voidpulse module so
        # _r() calls in paintEvent / refresh_theme return the new value.
        _cm.RAD_PCT = RAD_PCT
        _cm._broadcast_palette()

        # Lazily create the debounce timer once
        if not hasattr(self, '_radius_debounce'):
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(300)
            t.timeout.connect(self._radius_apply)
            self._radius_debounce = t

        win = self.window()
        if win is not None and win.isVisible():
            # Live user interaction — show overlay on first touch, then debounce
            if not getattr(self, '_radius_overlay', None):
                ov = _SpinningOverlay(win)
                ov.show(); ov.raise_()
                QApplication.processEvents()   # let overlay paint before heavy work
                self._radius_overlay = ov
            self._radius_debounce.start()
        else:
            # Config restore / pre-show — apply immediately, no overlay
            self._radius_debounce.stop()
            self._radius_apply()

    def _radius_apply(self):
        """Heavy part: rebuild every radius-bearing stylesheet, then dismiss overlay."""
        global SS
        SS = make_stylesheet(ACC, ACCH)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(SS)
        # Rebuild seek slider QSS (has inline border-radius, not covered by global SS)
        self._seek.update_radius()
        # Inline play/ctrl button stylesheets — refresh with new radii
        _ts = (f'QPushButton#ctrl {{ background:transparent; border:none; color:{FG2};'
               f' font-size:20px; border-radius:{_r(22)}px; padding:0; text-align:center; }}'
               f'QPushButton#ctrl:hover {{ color:{FG}; background:{BG3}; }}'
               f'QPushButton#ctrl:checked {{ color:{ACC}; background:transparent; }}'
               f'QPushButton#ctrl:pressed {{ background:{BG4}; }}')
        for b in (self.btn_shuf, self.btn_prev, self.btn_next):
            b.setStyleSheet(_ts)
        self.btn_play.setStyleSheet(
            f'QPushButton#play {{ background:{BG3}; color:{ACC};'
            f' border:2px solid {ACC}; border-radius:{_r(26)}px;'
            f' min-width:52px; max-width:52px; min-height:52px; max-height:52px;'
            f' font-size:22px; padding:0 0 2px 5px; text-align:center; }}'
            f'QPushButton#play:hover {{ border-color:{ACCH}; color:{ACCH}; background:{BG4}; }}'
            f'QPushButton#play:pressed {{ background:{BG4}; }}')
        # Accent swatch border-radius
        pop = self._settings_popup
        if pop is not None:
            pop._accent_btn.setStyleSheet(
                f'QPushButton#accent_swatch {{'
                f'  background:{ACC}; border-radius:{_r(16)}px; border:2px solid #666;'
                f'  min-width:32px; max-width:32px; min-height:32px; max-height:32px;'
                f'  padding:0;'
                f'}}')
        # TagEditDialog is transient — no refresh needed here
        # All ToggleSwitch widgets repaint automatically from globals on next update()
        # Recompute bar cap geometry — cap radius depends on RAD_PCT
        self._precompute_bars()
        # Corner-frame overlays are radius-dependent — clear so they rebuild with new RAD_PCT.
        # Cover pixmaps themselves are untouched (radius-independent).
        _corner_frame_cache.clear()
        self.update()
        # Trigger full widget refresh so inline-styled widgets (search, sort buttons,
        # sidebar lib_btn, comboboxes, etc.) pick up new border-radius values.
        self.accent_changed.emit(ACC)
        # Dismiss overlay (present only during live user interaction)
        ov = getattr(self, '_radius_overlay', None)
        if ov is not None:
            ov.close_overlay()
            self._radius_overlay = None

    def _on_accent_change(self, color: str):
        # apply_accent() is the single source of truth for whether ACC should
        # actually change (it no-ops the visible ACC while SYS mode is on,
        # only remembering the user's pick in _USER_ACC for later). We must
        # NOT set ACC/ACCH/SS ourselves before calling it — doing so used to
        # bypass that guard entirely, which made picking any color (or even
        # just restoring a saved accent_color from config while SYS mode was
        # on) immediately stomp the system-derived accent, and then every
        # subsequent theme refresh (which recomputes ACC via apply_theme())
        # would race against config-restore recalling this method, producing
        # the "colors keep flipping / following the picker" symptom.
        apply_accent(color)
        if is_system_qt_theme_active():
            # ACC didn't actually change (apply_accent() no-op'd it) — skip
            # the cache clears, disk unlinks, and widget restyling below
            # entirely. Without this, restoring a saved accent_color from
            # config while SYS mode is on would still touch disk (unlinking
            # default_cover_*.jpg, clearing several in-memory caches) for no
            # visible effect every single startup.
            return
        self._on_brightness_change(self._brightness_v)
        _cover_cache.clear()
        _corner_frame_cache.clear()
        _default_cover_mem_cache.clear()
        _acc_lut_cache.clear()   # accent hue changed — rebuild LUT on next paint
        # Invalidate cover-accent recolour cache (accent hue changed)
        self._cover_lbl._acc_pm = None
        # Remove stale default cover disk cache (will regenerate with new color)
        for f in CONFIG_PATH.parent.glob('default_cover_*.jpg'):
            try: f.unlink()
            except Exception: pass
        # Refresh inline-styled widgets (transport buttons use palette globals directly)
        _ts = (f'QPushButton#ctrl {{ background:transparent; border:none; color:{FG2};'
               f' font-size:20px; border-radius:{_r(22)}px; padding:0; text-align:center; }}'
               f'QPushButton#ctrl:hover {{ color:{FG}; background:{BG3}; }}'
               f'QPushButton#ctrl:checked {{ color:{ACC}; background:transparent; }}'
               f'QPushButton#ctrl:pressed {{ background:{BG4}; }}')
        for b in (self.btn_shuf, self.btn_prev, self.btn_next):
            b.setStyleSheet(_ts)
        self.btn_play.setStyleSheet(
            f'QPushButton#play {{ background:{BG3}; color:{ACC};'
            f' border:2px solid {ACC}; border-radius:{_r(26)}px;'
            f' min-width:52px; max-width:52px; min-height:52px; max-height:52px;'
            f' font-size:22px; padding:0 0 2px 5px; text-align:center; }}'
            f'QPushButton#play:hover {{ border-color:{ACCH}; color:{ACCH};'
            f' background:{BG4}; }}'
            f'QPushButton#play:pressed {{ background:{BG4}; }}')
        self.accent_changed.emit(color)
    def _on_cover_toggle(self, on: bool, _emit: bool = True):
        self._cover_lbl.setVisible(on)
        if on and self._cur_track:
            pm = get_cover_pixmap(self._cur_track.filepath, 64)
            self._cover_lbl.setPixmap(pm if pm is not None else draw_default_cover(64),
                                      self._cur_track.filepath)
        # Propagate to main window via signal — suppressed when the overlay path
        # will handle the library/playlist update to avoid double-updating.
        if _emit:
            self.cover_on_changed.emit(on)

    def _on_cover_acc_toggle(self, on: bool):
        """Cover-accent switch toggled — set global flag and repaint all views."""
        import cover_art as _cover_art_mod
        global _COVER_ACC_ON
        self._cover_acc_on = on
        _COVER_ACC_ON = on
        _cover_art_mod._COVER_ACC_ON = on   # update source module — get_cover_pixmap reads this
        _acc_lut_cache.clear()   # force LUT rebuild with current accent
        _cover_art_mod._acc_lut_cache.clear()
        # Repaint cover label and emit so MainWindow can repaint library/gallery
        self._cover_lbl.set_cover_accent_mode(on)
        self.accent_changed.emit(ACC)   # triggers MainWindow gallery/list repaint

    def _on_seek_flush(self):
        """Mark viz as awaiting first post-seek frame."""
        self._player._viz_spec[:] = MIN_DB
        self._player._viz_bar_buf[:] = 0.0
        # Force 150ms discard window in GLib thread too
        self._player._viz_discard_until = _monotonic() + 0.15
        self.update()

    def set_focus_paused(self, paused: bool):
        self._focus_paused = paused
        self._viz_paused = paused or not self._player.playing
        self._player.set_viz_active(self._viz_on and not paused)
        if self._overlay_viz_enabled:
            self._player.set_overlay_needs_spectrum(True)
        if self._viz_paused:
            self._render_timer.stop()
            self._player._viz_spec[:] = MIN_DB
            self.update()
        elif (self._viz_on or self._overlay_viz_enabled) and self._player.playing:
            self._start_render_timer()

    def _render_tick(self):
        # Main viz is suppressed when the overlay is open but overlay viz is off:
        # ControlBar is completely hidden behind the overlay so updating it is wasted.
        needs_render = (self._viz_on and not self._overlay_open) or self._overlay_viz_enabled
        if not needs_render or self._viz_paused:
            self._render_timer.stop()
            _gc.enable()
            return
        # Only call _compute_viz_frame when new spectrum data has arrived.
        # This avoids redundant numpy work on every tick when GStreamer hasn't
        # delivered a new spectrum message yet (common during burst gaps).
        if self._player._viz_has_new:
            self._player._compute_viz_frame()
        if not self._player._viz_has_any:
            # No spectrum ever received for this track yet.
            # Stop if: not playing, OR nothing needs rendering (viz off, overlay viz off).
            # The needs_render guard here catches any stray timer starts when viz is
            # disabled — belt-and-suspenders on top of the _on_playing_changed guard.
            if not self._player.playing or not needs_render:
                self._render_timer.stop()
                _gc.enable()
                if self._viz_on:
                    self.update()
            return

        _now = _monotonic()
        if (_now - self._render_last_wt) < _FRAME_S * 0.85:
            return
        self._render_last_wt = _now

        # ── Delay: ring-buffer the viz frames, expose the one delay_ms in the past ─
        # Same offset as _on_pos_for_lyrics so viz and lyrics stay in sync.
        delay_ms = self._delay_ms
        src      = self._player._viz_bar_buf
        if delay_ms > 0:
            N    = self._viz_rbuf_n
            head = self._viz_rbuf_head
            # Write current frame into the ring buffer (in-place, no allocation).
            self._viz_rbuf[head]   = src
            self._viz_rbuf_ts[head] = _now
            self._viz_rbuf_head    = (head + 1) % N
            self._viz_rbuf_count   = min(self._viz_rbuf_count + 1, N)
            # Scan valid slots for the most-recent frame that is >= delay_ms old.
            # Scanning up to 70 slots at 60 fps is negligible vs the rest of render.
            target_t = _now - delay_ms * 0.001
            count    = self._viz_rbuf_count
            best_idx = -1
            best_t   = -1.0
            for i in range(count):
                slot_t = self._viz_rbuf_ts[i]
                if slot_t <= target_t and slot_t > best_t:
                    best_t   = slot_t
                    best_idx = i
            if best_idx >= 0:
                _np.copyto(self._viz_display_buf, self._viz_rbuf[best_idx])
            # else: buffer not filled enough yet — keep previous display frame
        else:
            # No delay — reset ring buffer and mirror live frame directly.
            self._viz_rbuf_head  = 0
            self._viz_rbuf_count = 0
            _np.copyto(self._viz_display_buf, src)

        if self._viz_on:
            self.update()


    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Scale vertical margins so content never clips when bar is short
        h = self.height()
        v_margin = max(4, min(14, (h - 110) * 14 // 62))  # 0→4px at 110, 14px at 172+
        self._root_layout.setContentsMargins(18, v_margin, 18, v_margin)
        self._root_layout.setSpacing(max(2, min(10, (h - 110) * 10 // 62)))
        # Recompute bar/cap geometry — debounced so resize drags don't thrash numpy
        self._resize_timer.start()

    def paintEvent(self, _):
        dpr = self.devicePixelRatio()
        iw = round(self.width() * dpr); ih = round(self.height() * dpr)
        if iw <= 0 or ih <= 0:
            return
        p = QPainter(self)
        if not p.isActive():
            return
        p.scale(1.0 / dpr, 1.0 / dpr)

        # ── Border pen / background brush cache — always valid, even in fallback ─
        # Initialised here (before the viz branch) so the stopped/paused fallback
        # path always has a valid QPen and QBrush even if the viz active path has
        # never executed (e.g. first paint while stopped at startup).
        if self._paint_bord_key != BORD:
            self._paint_bord_key = BORD
            self._paint_bord_pen = QPen(QColor(BORD), 1)
            self._paint_bg_brush = QBrush(QColor(BG))

        if self._viz_on and not self._viz_paused:
            bh = self._viz_display_buf

            if self._player._viz_has_any and len(bh) == VIZ_BANDS:
                bc = self._bar_color

                # ── Color cache — only rebuild uint32 colors on change ─────────
                bg_key  = BG
                bar_key = (bc.red(), bc.green(), bc.blue())
                if self._px_bg_key != bg_key or self._px_bar_key != bar_key:
                    self._px_bg_key  = bg_key
                    self._px_bar_key = bar_key
                    _bgc = QColor(BG)
                    self._px_bg  = (0xFF << 24 | _bgc.red() << 16
                                    | _bgc.green() << 8 | _bgc.blue())
                    self._px_bar = (0xFF << 24 | bc.red() << 16
                                    | bc.green() << 8 | bc.blue())
                    # Also keep QBrush for border line
                    # invalidate pixel buffer so it is reallocated with new colors
                    self._px_shape = (0, 0)
                if self._viz_type == 'fill':
                    # ── FILL MODE ─────────────────────────────────────────────
                    bar_px_arr = self._paint_bar_px
                    _np.multiply(bh, ih, out=bar_px_arr, casting='unsafe')

                    col_has = self._col_has_bar
                    if len(col_has) != iw:
                        p.end()
                        return

                    if self._px_shape != (ih, iw):
                        self._px_buf   = _np.full((ih, iw), self._px_bg, dtype=_np.uint32)
                        self._px_qimg  = QImage(self._px_buf.data, iw, ih,
                                                iw * 4, QImage.Format.Format_ARGB32_Premultiplied)
                        self._px_shape   = (ih, iw)
                        self._px_row_idx = _np.arange(ih, dtype=_np.int32)[:, _np.newaxis]

                    buf = self._px_buf
                    buf[:] = self._px_bg

                    # Use precomputed linear-interp tables (same as line mode) — zero allocation.
                    cy_buf = self._line_cy_buf
                    _np.subtract(ih, bar_px_arr, out=cy_buf, casting='unsafe')
                    line_y_f = (cy_buf[self._line_bin_i]
                                + self._line_bin_f * (cy_buf[self._line_bin_i1]
                                                      - cy_buf[self._line_bin_i]))
                    line_y_i = line_y_f.astype(_np.int32)
                    _np.clip(line_y_i, 0, ih - 1, out=line_y_i)

                    fill_mask = self._px_row_idx >= line_y_i
                    buf[fill_mask] = self._px_bar

                    p.drawImage(0, 0, self._px_qimg)
                    p.setPen(self._paint_bord_pen)
                    p.drawLine(0, 0, iw, 0)
                    p.end()
                    return

                if self._viz_type == 'line':
                    # ── LINE MODE — pixel-buffer + Bresenham span fill ─────────
                    # No AA QPainter overhead; gaps on steep slopes are filled by
                    # drawing a vertical span between each pair of consecutive y
                    # values (classic connected-line rasterisation).
                    # np.interp replaced by a cached-index manual lerp — zero
                    # extra allocation for the interpolation tables.
                    bar_px_arr = self._paint_bar_px
                    _np.multiply(bh, ih, out=bar_px_arr, casting='unsafe')

                    if len(self._col_has_bar) != iw:
                        p.end()
                        return

                    # ── Interpolation: VIZ_BANDS → iw y-positions ─────────────
                    # Manual lerp with pre-cached bin_i / bin_f / bin_i1 arrays.
                    # cy_buf reused in-place (no allocation).
                    cy_buf = self._line_cy_buf
                    _np.subtract(ih, bar_px_arr, out=cy_buf, casting='unsafe')
                    # line_y_f = cy[bin_i] + frac * (cy[bin_i+1] - cy[bin_i])
                    line_y_f = (cy_buf[self._line_bin_i]
                                + self._line_bin_f * (cy_buf[self._line_bin_i1]
                                                      - cy_buf[self._line_bin_i]))
                    line_y_i = line_y_f.astype(_np.int32)
                    _np.clip(line_y_i, 0, ih - 1, out=line_y_i)   # in-place, no alloc

                    # ── Pixel buffer — reallocate only on resize / color change ─
                    if self._px_shape != (ih, iw):
                        self._px_buf  = _np.empty((ih, iw), dtype=_np.uint32)
                        self._px_qimg = QImage(self._px_buf.data, iw, ih,
                                               iw * 4,
                                               QImage.Format.Format_ARGB32_Premultiplied)
                        self._px_shape = (ih, iw)

                    buf    = self._px_buf
                    col_i  = self._line_col_x_i
                    px_bar = self._px_bar
                    buf[:] = self._px_bg

                    # ── Main line: one pixel per column ───────────────────────
                    buf[line_y_i, col_i] = px_bar

                    # ── Gap fill: steep columns get a vertical span ────────────
                    # For every adjacent pair where |Δy| > 1, fill all rows
                    # between the two y values so the line is visually connected.
                    # In a smooth audio viz only a handful of columns are steep,
                    # so this Python loop runs very few iterations per frame.
                    dy    = _np.diff(line_y_i)                    # (iw-1,) int32
                    steep = _np.flatnonzero(_np.abs(dy) > 1)
                    for idx in steep:
                        y0 = int(line_y_i[idx])
                        y1 = int(line_y_i[idx + 1])
                        if y0 > y1: y0, y1 = y1, y0
                        buf[y0:y1 + 1, idx + 1] = px_bar

                    p.drawImage(0, 0, self._px_qimg)
                    p.setPen(self._paint_bord_pen)
                    p.drawLine(0, 0, iw, 0)
                    p.end()
                    return

                if self._viz_type == 'line+fill':
                    # ── LINE+FILL MODE — fill beneath the line + line on top ────
                    bar_px_arr = self._paint_bar_px
                    _np.multiply(bh, ih, out=bar_px_arr, casting='unsafe')

                    if len(self._col_has_bar) != iw:
                        p.end()
                        return

                    # Interpolate VIZ_BANDS → iw y-positions (same as line mode)
                    cy_buf = self._line_cy_buf
                    _np.subtract(ih, bar_px_arr, out=cy_buf, casting='unsafe')
                    line_y_f = (cy_buf[self._line_bin_i]
                                + self._line_bin_f * (cy_buf[self._line_bin_i1]
                                                      - cy_buf[self._line_bin_i]))
                    line_y_i = line_y_f.astype(_np.int32)
                    _np.clip(line_y_i, 0, ih - 1, out=line_y_i)

                    # Pixel buffer — reallocate only on resize / color change
                    if self._px_shape != (ih, iw):
                        self._px_buf   = _np.full((ih, iw), self._px_bg, dtype=_np.uint32)
                        self._px_qimg  = QImage(self._px_buf.data, iw, ih,
                                                iw * 4, QImage.Format.Format_ARGB32_Premultiplied)
                        self._px_shape   = (ih, iw)
                        self._px_row_idx = _np.arange(ih, dtype=_np.int32)[:, _np.newaxis]

                    buf = self._px_buf
                    buf[:] = self._px_bg

                    # Fill colour — semi-transparent version of bar color (40% alpha blend onto BG).
                    # Recompute only when bar color or BG changes (same key as px_bar/px_bg cache).
                    if getattr(self, '_px_fill_key', None) != (self._px_bg, self._px_bar_key):
                        _bc = self._bar_color
                        _bgc_r = (self._px_bg >> 16) & 0xFF
                        _bgc_g = (self._px_bg >> 8)  & 0xFF
                        _bgc_b =  self._px_bg         & 0xFF
                        _alpha = 0.38
                        _fill_r = int(_bgc_r + (_bc.red()   - _bgc_r) * _alpha)
                        _fill_g = int(_bgc_g + (_bc.green() - _bgc_g) * _alpha)
                        _fill_b = int(_bgc_b + (_bc.blue()  - _bgc_b) * _alpha)
                        self._px_fill     = (0xFF << 24 | _fill_r << 16 | _fill_g << 8 | _fill_b)
                        self._px_fill_key = (self._px_bg, self._px_bar_key)
                    px_fill = self._px_fill

                    # ── Fill: all rows at or below the line y ──────────────────
                    fill_mask = self._px_row_idx >= line_y_i
                    buf[fill_mask] = px_fill

                    # ── Line: one pixel per column on top of fill ──────────────
                    col_i  = self._line_col_x_i
                    px_bar = self._px_bar
                    buf[line_y_i, col_i] = px_bar

                    # ── Gap fill for steep columns ─────────────────────────────
                    dy    = _np.diff(line_y_i)
                    steep = _np.flatnonzero(_np.abs(dy) > 1)
                    for idx in steep:
                        y0 = int(line_y_i[idx])
                        y1 = int(line_y_i[idx + 1])
                        if y0 > y1: y0, y1 = y1, y0
                        buf[y0:y1 + 1, idx + 1] = px_bar

                    p.drawImage(0, 0, self._px_qimg)
                    p.setPen(self._paint_bord_pen)
                    p.drawLine(0, 0, iw, 0)
                    p.end()
                    return

                # ── BARS MODE (original pixel-buffer path) ────────────────────

                # ── Pixel buffer — reallocate only on resize or color change ───
                if self._px_shape != (ih, iw):
                    self._px_buf   = _np.full((ih, iw), self._px_bg, dtype=_np.uint32)
                    self._px_qimg  = QImage(self._px_buf.data, iw, ih,
                                            iw * 4, QImage.Format.Format_ARGB32_Premultiplied)
                    self._px_shape   = (ih, iw)
                    self._px_row_idx = _np.arange(ih, dtype=_np.int32)[:, _np.newaxis]  # (ih,1)

                buf    = self._px_buf
                px_bg  = self._px_bg
                px_bar = self._px_bar

                bar_x0     = self._bar_x0
                bw         = self._bar_bw
                bar_px_arr = self._paint_bar_px
                _np.multiply(bh, ih, out=bar_px_arr, casting='unsafe')
                buf[:] = px_bg

                cap_r    = self._cap_r_offsets   # (n_cap_pix,) int32
                cap_c    = self._cap_c_offsets   # (n_cap_pix,) int32
                radius   = self._cap_radius
                use_caps = radius > 0 and len(cap_r) > 0 and bw > 4

                # ── Body fill — fully vectorised 2-D broadcast ────────────────
                # Step 1: per-column bar height via O(1) gather (precomputed maps).
                col_has  = self._col_has_bar
                cb_safe  = self._col_bar_safe
                # Guard: precomputed column maps may be stale if _precompute_bars()
                # hasn't fired yet after a resize (debounced). Skip this frame to
                # avoid a shape mismatch crash between buf (iw) and col_has (iw_old).
                if len(col_has) != iw:
                    p.end()
                    return
                col_h    = _np.where(col_has, bar_px_arr[cb_safe], 0)
                # Step 2: body starts below cap top when caps are active.
                body_offset  = radius if use_caps else 0
                col_y0_body  = ih - _np.maximum(col_h - body_offset, 0)
                # Step 3: single 2-D boolean mask — one numpy write for all bars.
                fill_mask = col_has & (self._px_row_idx >= col_y0_body)
                buf[fill_mask] = px_bar

                # ── Cap fill — fully vectorised, zero Python loops ─────────────
                # For each eligible bar: y0s[i] is its top row, x0s[i] its left col.
                # cap_r / cap_c are precomputed (row, col) offsets within the cap.
                # Outer-product broadcast gives (n_elig × n_cap_pix) index grids;
                # a single in-bounds boolean mask collapses it to a flat assignment.
                if use_caps:
                    elig = bar_px_arr >= radius          # (VIZ_BANDS,) bool
                    if elig.any():
                        y0s  = (ih - bar_px_arr[elig]).astype(_np.int32)   # (n,)
                        x0s  = bar_x0[elig]                                # (n,)
                        row_idx = y0s[:, None] + cap_r   # (n, n_cap_pix)
                        col_idx = x0s[:, None] + cap_c   # (n, n_cap_pix)
                        ok = ((row_idx >= 0) & (row_idx < ih) &
                              (col_idx >= 0) & (col_idx < iw))
                        buf[row_idx[ok], col_idx[ok]] = px_bar

                # ── Single drawImage call — one Wayland surface write ──────────
                p.drawImage(0, 0, self._px_qimg)
                p.setPen(self._paint_bord_pen)
                p.drawLine(0, 0, iw, 0)
                p.end()
                return

        # Viz off / paused — fill with background color across the full physical rect
        # iw/ih are physical pixels (width * dpr); painter is pre-scaled by 1/dpr so
        # QRectF(0, 0, iw, ih) maps to the correct physical extent on high-DPI screens.
        p.fillRect(QRectF(0, 0, iw, ih), self._paint_bg_brush)
        p.setPen(self._paint_bord_pen)
        p.drawLine(0, 0, iw, 0)
        p.end()

    def _on_playing_changed(self, playing: bool):
        if playing:
            _focus_paused = getattr(self, '_focus_paused', False)
            self._viz_paused = _focus_paused
            self._player.set_viz_active(self._viz_on and not _focus_paused)
            # Only start the render timer when there is actually something to render.
            # Previously started unconditionally, which caused the 60 fps timer to
            # spin on every track change when viz was disabled — _viz_has_any is reset
            # to False in _destroy(), so _render_tick's early-exit path never stopped
            # it and the timer kept firing until the first spectrum message arrived.
            if (self._viz_on or self._overlay_viz_enabled) and not _focus_paused:
                self._start_render_timer()
        else:
            self._viz_paused = True
            # Silence the spectrum element immediately — before _destroy() hands the
            # dying pipeline to GLib.idle_add(set_state, NULL).  Without this,
            # the old pipeline's FFT can still be running at 30 fps during the
            # async NULL transition, wasting CPU while the new pipeline prerolls.
            self._player.set_viz_active(False)
            self._render_timer.stop()
            self._player._viz_spec[:] = MIN_DB
            self._player._viz_bar_buf[:] = 0.0
            self.update()
            _bref = getattr(self, '_blackout_ref', None)
            if _bref is not None and getattr(_bref, '_ov_viz', False):
                _bref.push_viz_frame(self._player._viz_bar_buf)  # already zeroed above

    def _on_press(self):   self._seeking = True
    def _on_release(self):
        if self._dur_ms > 0 and self._player.has_pipe:
            self._on_seek_flush()  # timestamp + clear spec
            seek_ms = int(self._seek.value() * self._dur_ms / 1000)
            self._player.seek(seek_ms)
            # Anchor is updated inside seek() immediately — emit UI update now
            self._on_pos(self._player.position_ms())
        self._seeking = False

    def _on_moved(self, val):
        if self._dur_ms > 0: self._lbl_cur.setText(self._fmt(int(val*self._dur_ms/1000)))

    def _on_pos(self, ms):
        if self._seeking or self._seek.isSliderDown() or self._dur_ms == 0: return
        new_val = int(ms * 1000 / self._dur_ms)
        # Only update slider and label when value actually changes — avoids
        # triggering a QSlider repaint and QString allocation on every tick
        if new_val != getattr(self, '_last_seek_val', -1):
            self._last_seek_val = new_val
            self._seek.setValue(new_val)
        new_txt = self._fmt(ms)
        if new_txt != getattr(self, '_last_time_txt', ''):
            self._last_time_txt = new_txt
            self._lbl_cur.setText(new_txt)

    def _on_dur(self, ms): self._dur_ms = ms; self._lbl_tot.setText(self._fmt(ms))

    def refresh_theme(self):
        """Re-apply theme after a dark/light switch.
        Re-renders the cover label so it picks up the new background colour
        and, when cover-accent mode is on, rebuilds the LUT for the new mode
        (dark: black→accent, light: accent→white).
        """
        sz = self._cover_lbl._sz
        if self._cover_lbl._cover_acc_mode:
            # Invalidate cached accent pixmap so _build_accent_pixmap rebuilds
            # with the correct dark/light LUT on next paint.
            self._cover_lbl._acc_pm = None
            self._cover_lbl._acc_pm_key = None
        if self._cover_lbl.isVisible() and self._cur_track is not None:
            pm = get_cover_pixmap(self._cur_track.filepath, sz)
            self._cover_lbl.setPixmap(pm if pm is not None else draw_default_cover(sz), self._cur_track.filepath)
        elif self._cover_lbl.isVisible():
            self._cover_lbl.setPixmap(draw_default_cover(sz))

    def set_track(self, t: Track):
        self._lbl_title.setText(t.title or Path(t.filepath).name)
        self._lbl_artist.setText(t.artist)
        self._seek.setValue(0); self._lbl_cur.setText('0:00')
        self._dur_ms = int(t.duration*1000); self._lbl_tot.setText(t.dur_str())
        self._player._viz_spec[:] = MIN_DB
        # Update cover thumbnail — always show whatever is in cache (or default)
        if self._cover_lbl.isVisible():
            pm = get_cover_pixmap(t.filepath, 64)
            self._cover_lbl.setPixmap(pm if pm is not None else draw_default_cover(64), t.filepath)
        self._cur_track = t
        # Keep AUDIO INFO labels current while the settings popup is open
        if self._settings_popup is not None and self._settings_popup.isVisible():
            self._refresh_audio_info()

    def set_play_icon(self, playing: bool):
        self.btn_play.setText('⏸' if playing else '▶')
        _pad = '0 0 2px 5px' if not playing else '0'
        # Rebuild from scratch so palette globals (BG3/ACC/ACCH) are always current.
        # Use _r(26) so the radius follows the global RAD_PCT setting instead of
        # hardcoding 26 px (which would revert the radius every time play/pause fires).
        self.btn_play.setStyleSheet(
            f'QPushButton#play {{ background:{BG3}; color:{ACC};'
            f' border:2px solid {ACC}; border-radius:{_r(26)}px;'
            f' min-width:52px; max-width:52px; min-height:52px; max-height:52px;'
            f' font-size:22px; padding:{_pad}; text-align:center; }}'
            f'QPushButton#play:hover {{ border-color:{ACCH}; color:{ACCH};'
            f' background:{BG4}; }}'
            f'QPushButton#play:pressed {{ background:{BG4}; }}')

    def set_play_busy(self, busy: bool):
        """Show/hide spinner on play button during pipeline reload."""
        self.btn_play.set_busy(busy)

    _fmt = staticmethod(_fmt_ms)   # alias for backward compatibility

# ══════════════════════════════════════════════════════════════════════════════
#  Titlebar constants
# ══════════════════════════════════════════════════════════════════════════════
_TB_BG      = '#000000'   # pure black background
_TB_FG      = '#666666'   # title text
_TB_ICO     = '#686868'   # window-control icons (visibly grey)
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
        bg_hover  = BG3   # use palette global so light theme picks it up
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

        # App icon (music note)
        self._ico_lbl = QLabel('♫')
        self._ico_lbl.setStyleSheet(
            f'color: {_TB_ICO}; font-size: 13px; background: transparent; padding-right: 6px;')
        lay.addWidget(self._ico_lbl)

        # Window title
        self._title_lbl = QLabel('VoidPulse')
        self._title_lbl.setStyleSheet(
            f'color: {_TB_FG}; font-size: 12px; font-weight: normal; background: transparent;')
        lay.addWidget(self._title_lbl)

        lay.addStretch(1)

        # Window-control buttons
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
            # Do not start a system-move drag when the press lands on a child
            # widget (minimize / maximize / close buttons).  childAt() returns
            # None when the click is on the bare titlebar background.
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

