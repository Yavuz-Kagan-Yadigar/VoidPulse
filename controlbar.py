"""
VoidPulse — ControlBar: the bar under the track list holding the seek slider,
transport buttons, cover thumbnail, EQ/settings popups and the spectrum
visualiser it paints itself.

Its child widgets live in controlbar_widgets.py and the frameless window
titlebar in titlebar.py.
"""
from constants import *

from controlbar_widgets import (_ctrl, RepeatButton, _FullscreenBtn,
                                SpinningPlayButton, _RoundedCoverLabel)
from library import RenamePopup
from fetch_popups import (LyricsFetchPopup, TagFetchPopup, GainFetchPopup,
                          CoverFetchPopup, _BaseFetchPopup)
from widgets_base import _ModalOverlay, _SpinningOverlay
from constants import ACC, ACCH, BG, BG3, BG4, BORD, CONFIG_PATH, EQ_TYPE_PEAK, FG, FG2, GST_BANDS, MIN_DB, RAD_PCT, VIZ_BANDS, _DARK_MODE, _FRAME_MS, _FRAME_S, _r, apply_theme, apply_accent, make_stylesheet, is_system_qt_theme_active
from time import monotonic as _monotonic
import numpy as _np
import gc as _gc
from eq import EqPopup, _fmt_ms
from settings_popup import SettingsPopup
from alsa import probe_alsa_devices
from cover_art import (draw_default_cover,
                       get_cover_pixmap, _acc_lut_cache, _cover_cache,
                       _default_cover_mem_cache)
from player import Player
from resampler import HAVE_SOXR
from cover_art import Track
from views import SeekSlider



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
        # Recent viz frames, so the display can lag behind the audio to match
        # Bluetooth/DAC latency. It has to span the Delay slider's full 3000 ms
        # (~180 slots at 60 fps) or the "oldest slot >= delay_ms" scan finds
        # nothing and the display freezes; 200 leaves room for render jitter.
        _VIZ_RBUF_N = 200
        self._viz_rbuf_n    = _VIZ_RBUF_N
        self._viz_rbuf      = _np.zeros((_VIZ_RBUF_N, VIZ_BANDS), dtype=_np.float32)
        self._viz_rbuf_ts   = _np.zeros(_VIZ_RBUF_N, dtype=_np.float64)
        self._viz_rbuf_head = 0
        self._viz_rbuf_count= 0
        # The frame paintEvent reads, live or delayed
        self._viz_display_buf = _np.zeros(VIZ_BANDS, dtype=_np.float32)

        # Paint buffers, rebuilt by _precompute_bars and reused every frame
        self._paint_bar_px      = _np.zeros(VIZ_BANDS, dtype=_np.int32)
        # Pixel buffer for one drawImage per frame instead of 256+ fillRects
        self._px_buf:     object = None   # (ih, iw) uint32 numpy array
        self._px_qimg:    object = None   # QImage wrapping _px_buf
        self._px_shape:   tuple  = (0, 0) # (ih, iw) rebuilt on resize
        self._px_bg:      int    = 0      # BG as 0xAARRGGBB uint32
        self._px_bar:     int    = 0      # bar color as 0xAARRGGBB uint32
        self._px_bg_key:  object = None   # tracks BG global for cache invalidation
        self._px_bar_key: object = None   # tracks bar color for cache invalidation
        self._px_row_idx: object = None   # (ih, 1) int32 — row indices for broadcast
        self._px_m32:     object = None   # (ih, iw) uint32 scratch for the bar blend
        # Integer bar heights of the last repainted frame, to skip identical ones
        self._viz_px_cur:  object = _np.zeros(VIZ_BANDS, dtype=_np.int32)
        self._viz_px_last: object = _np.full(VIZ_BANDS, -1, dtype=_np.int32)
        self._viz_last_ih: int    = -1
        self._render_last_wt:    float = 0.0   # timestamp of last update() call
        # Cached pen/brush, rebuilt when BORD or BG changes rather than per frame
        self._paint_bord_key: object = None    # tracks BORD global
        self._paint_bord_pen: QPen   = QPen()  # QPen(BORD, 1) — rebuilt on demand
        self._paint_bg_brush: QBrush = QBrush()

        # Both popups are created on first use
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
        info_h = QHBoxLayout(info); info_h.setContentsMargins(8, 0, 0, 0); info_h.setSpacing(10)
        _COVER_SZ = 64
        # _RoundedCoverLabel clips to RAD_PCT, so the corners stay transparent
        # over the viz background.
        self._cover_lbl = _RoundedCoverLabel(_COVER_SZ)
        self._cover_lbl.setVisible(True)
        info_h.addWidget(self._cover_lbl)
        # Title pinned to cover top, artist pinned to cover bottom
        self._txt_w = txt_w = QWidget(); txt_w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        txt_w.setStyleSheet('background:transparent;'); txt_w.setFixedHeight(_COVER_SZ)
        il = QVBoxLayout(txt_w); il.setContentsMargins(0, 3, 0, 3); il.setSpacing(0)
        self._lbl_title  = QLabel('—'); self._lbl_title.setObjectName('now_title')
        self._lbl_artist = QLabel('');  self._lbl_artist.setObjectName('now_artist')
        for lbl in (self._lbl_title, self._lbl_artist):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            lbl.setStyleSheet('background:transparent;')
        self._lbl_title.setMaximumWidth(240); self._lbl_title.setWordWrap(False)
        self._lbl_title.setTextFormat(Qt.TextFormat.PlainText)
        self._lbl_artist.setMaximumWidth(240); self._lbl_artist.setWordWrap(False)
        # Un-elided originals; _apply_now_playing_text() elides them to fit
        self._now_title_raw  = '—'
        self._now_artist_raw = ''
        il.addWidget(self._lbl_title, 0, Qt.AlignmentFlag.AlignTop)
        il.addStretch(1)
        il.addWidget(self._lbl_artist, 0, Qt.AlignmentFlag.AlignBottom)
        info_h.addWidget(txt_w, 1)
        row2.addWidget(info, 3)
        # Responsive breakpoints used by resizeEvent:
        # (min_width, cover_size, title/artist max width, play button size)
        self._NOWPLAYING_BREAKPOINTS = (
            (900, 64, 240, 60),
            (700, 52, 170, 52),
            (560, 42, 120, 46),
            (0,   32, 80,  40),
        )

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
        # btn_play sizes itself in SpinningPlayButton.set_size()
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
        # Global mouse position, for the 5-px movement threshold
        self._idle_last_mouse: Optional[QPoint] = None

        # ── Viz repaint — fixed-rate Qt timer ───────────────────────────────
        # Spectrum frames arrive at whatever rate the codec produces; this timer
        # drives painting at a fixed FPS_CAP cadence instead, draining the queue
        # via Player._compute_viz_frame. A new sample rate needs new freq→bin
        # tables, hence the sig_fs_changed hookup.
        player.sig_fs_changed.connect(lambda _fs: self._precompute_bars())
        self._render_timer = QTimer(self)
        self._render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._render_timer.setInterval(_FRAME_MS)  # FPS_CAP fixed render cadence
        self._render_timer.timeout.connect(self._render_tick)
        # Bar layout needs a real widget width, so defer past the first layout pass
        QTimer.singleShot(0, self._precompute_bars)
        # Debounced so a resize drag does not recompute per pixel
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
            pop.balance_changed.connect(self._player.set_balance)
            pop.preamp_changed.connect(self._player.set_preamp_db)
            # Applies live through Player's preamp element, so it goes straight
            # to the player with no MainWindow handler in between.
            pop.loudness_norm_toggled.connect(self._player.set_loudness_norm)
            for sig in (pop.limiter_changed, pop.stereo_changed,
                        pop.stereo_width_changed, pop.balance_changed, pop.preamp_changed,
                        pop.loudness_norm_toggled):
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
        # The switches may be out of date if state changed without the popup open
        pop.set_limiter_enabled(self._player._limiter_enabled)
        pop.set_stereo_enabled(self._player._stereo_enabled)
        pop.set_stereo_width(self._player._stereo_width)
        pop.set_balance(self._player._balance)
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
            pop.gain_fetch_action.connect(self._on_gain_fetch_btn)
            pop.rename_toggled.connect(self._on_rename_btn)
            pop.radius_changed.connect(self._on_radius_change)
            pop.output_device_changed.connect(self._player.set_output_device)
            pop.output_device_changed.connect(lambda _: self._refresh_audio_info())
            # Keep the slider in step with volume changes made by the player
            self._player.sig_volume_changed.connect(pop.set_volume)
            # Connected here rather than in MainWindow.__init__: the popup does
            # not exist yet at that point.
            win = self.window()
            if win is not None and hasattr(win, '_on_output_device_changed'):
                pop.output_device_changed.connect(win._on_output_device_changed)
            if win is not None and hasattr(win, '_on_adaptive_rate_toggled'):
                pop.adaptive_rate_toggled.connect(win._on_adaptive_rate_toggled)
            if win is not None and hasattr(win, '_on_bg_opt_toggled'):
                pop.bg_opt_toggled.connect(win._on_bg_opt_toggled)
            if not self._player.has_spectrum:
                pop._viz_sw.setEnabled(False); pop._log_sw.setEnabled(False)
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
                pop.adaptive_rate_toggled, pop.bg_opt_toggled,
            ]
            for sig in _save_sigs:
                sig.connect(lambda *_: self.settings_changed.emit())
            # The theme switch has its own handler, so connect to the switch itself
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
            label = 'PipeWire'
        else:
            idx = pop._out_dev_combo.findData(dev)
            label = pop._out_dev_combo.itemText(idx) if idx >= 0 else dev
        # Cheap after the first call — the rate probes are cached in-process
        mode, target_rate = self._player._resolve_rate_plan()
        if mode == 'resample' and target_rate:
            # HAVE_SOXR only says the package imported, not that this particular
            # bin built; a per-instance fallback prints to the console instead.
            backend = 'SoX' if HAVE_SOXR else 'GST'
            label += f'  ·  {backend} {target_rate / 1000:.1f}k'
        elif mode == 'passthrough':
            label += '  ·  bit-perfect'
        pop._info_dev.setText(label)

    @property
    def lyrics_fetch_enabled(self) -> bool:
        pop = self._settings_popup
        return pop.lyrics_fetch_on() if pop else True

    def cover_on(self) -> bool:
        """Return current state of the Cover switch (default True if popup not yet created)."""
        pop = self._settings_popup
        return pop.cover_on() if pop else True

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
        # Only while the app is in the foreground
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
            # With the overlay open, this was the only reason left to render
            if self._overlay_open or not self._viz_on:
                self._stop_render_timer()
        elif self._overlay_open and self._player.playing and not self._viz_paused:
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
            # Fully covered with nothing to show — rendering would be wasted
            self._stop_render_timer()
        elif not open and self._viz_on and not self._viz_paused and self._player.playing:
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
        
        # Reuse the dialog if this fetch is already running in the background
        workers_list = _BaseFetchPopup._active_workers.get('CoverFetchPopup', [])
        if workers_list:
            old_instance, old_worker, old_thread = workers_list[-1]
            old_instance.show()
            old_instance.raise_()
            old_instance.activateWindow()
            return
        
        dlg = CoverFetchPopup(all_tracks, pages, self, parent=win)
        _ModalOverlay.show_for(dlg, watch_hide=True)   # non-blocking .show() dialog — see _ModalOverlay
        dlg.show()

    def _on_lyric_fetch_btn(self):
        """Open the LyricsFetchPopup — triggered by the Settings button."""
        win = self.window()
        all_tracks = list(win._lib_page.tracks) if hasattr(win, '_lib_page') and win._lib_page else []
        if not all_tracks:
            QMessageBox.information(win, 'No Tracks', 'Add a folder to the library first.')
            return
        if self._settings_popup: self._settings_popup.hide()
        
        # Reuse the dialog if this fetch is already running in the background
        workers_list = _BaseFetchPopup._active_workers.get('LyricsFetchPopup', [])
        if workers_list:
            old_instance, old_worker, old_thread = workers_list[-1]
            old_instance.show()
            old_instance.raise_()
            old_instance.activateWindow()
            return
        
        dlg = LyricsFetchPopup(all_tracks, parent=win)
        _ModalOverlay.show_for(dlg, watch_hide=True)   # non-blocking .show() dialog — see _ModalOverlay
        dlg.show()

    def _on_tag_fetch_btn(self):
        win = self.window()
        all_tracks = list(win._lib_page.tracks) if hasattr(win, '_lib_page') and win._lib_page else []
        if not all_tracks:
            QMessageBox.information(win, 'No Tracks', 'Add a folder to the library first.')
            return
        if self._settings_popup: self._settings_popup.hide()
        
        # Reuse the dialog if this fetch is already running in the background
        workers_list = _BaseFetchPopup._active_workers.get('TagFetchPopup', [])
        if workers_list:
            old_instance, old_worker, old_thread = workers_list[-1]
            old_instance.show()
            old_instance.raise_()
            old_instance.activateWindow()
            return
        
        dlg = TagFetchPopup(all_tracks, parent=win)
        dlg.tags_updated.connect(lambda fp, tags: win._on_tags_fetched(fp, tags))
        _ModalOverlay.show_for(dlg, watch_hide=True)   # non-blocking .show() dialog — see _ModalOverlay
        dlg.show()

    def _on_gain_fetch_btn(self):
        win = self.window()
        all_tracks = list(win._lib_page.tracks) if hasattr(win, '_lib_page') and win._lib_page else []
        if not all_tracks:
            QMessageBox.information(win, 'No Tracks', 'Add a folder to the library first.')
            return
        if self._settings_popup: self._settings_popup.hide()

        # Reuse the dialog if this fetch is already running in the background
        workers_list = _BaseFetchPopup._active_workers.get('GainFetchPopup', [])
        if workers_list:
            old_instance, old_worker, old_thread = workers_list[-1]
            old_instance.show()
            old_instance.raise_()
            old_instance.activateWindow()
            return

        dlg = GainFetchPopup(all_tracks, parent=win)
        _ModalOverlay.show_for(dlg, watch_hide=True)   # non-blocking .show() dialog — see _ModalOverlay
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

            # 2b. Move the live player state onto the new paths, or the rescan
            # cannot match the playing track (losing its highlight) and the
            # lyrics panel looks up a path that no longer exists.
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
        
        # Reuse the dialog if a rename is already running in the background
        existing = RenamePopup._active_worker
        if existing:
            old_instance, old_worker, old_thread = existing
            old_instance.show()
            old_instance.raise_()
            old_instance.activateWindow()
            return
        
        dlg = RenamePopup(all_tracks, parent=win)
        dlg._post_finish_cb = _on_rename_finished
        _ModalOverlay.show_for(dlg, watch_hide=True)   # non-blocking .show() dialog — see _ModalOverlay
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
        # One click can both close the popup (via the event filter) and re-fire
        # this handler, so ignore a toggle right after a hide. The two events
        # arrive ~1 ms apart; 150 ms is a generous window.
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
        # Numbers may come back from JSON as strings, so coerce them
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
        # Stored inverted: the config key predates the switch and names the opt-out.
        # setChecked() does not emit, so MainWindow's own copy of the flag — already
        # read by _load_config before we get here — is not clobbered.
        pop.set_bg_opt(not cfg.get('disable_background_optimizations', False))
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
        # get_cover_pixmap reads the flag from cover_art, so set it there.
        import cover_art as _cover_art_mod
        _cover_art_mod._COVER_ACC_ON = cover_acc
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
        pop.set_cover_fetch(cfg.get('cover_fetch_on', True))
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
            _available_ids = {dev_id for _, dev_id in probe_alsa_devices()}
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

        # Restore the toggle silently, and re-sync the config drop-in only if the
        # user had already opted in — never opt them in here.
        _adaptive = cfg.get('pipewire_adaptive_rate', False)
        pop.set_adaptive_rate_enabled(_adaptive)
        self._player.set_pipewire_adaptive_rate(_adaptive, reload=False)
        win = self.window()
        if _adaptive and win is not None and hasattr(win, '_sync_pipewire_adaptive_rate_file'):
            win._sync_pipewire_adaptive_rate_file(True)

        _loudness = cfg.get('loudness_norm', False)
        self._ensure_eq_popup().set_loudness_norm_enabled(_loudness)
        self._player.set_loudness_norm(_loudness)

        # Assume hw:X,Y works; the first _alsa_play() probe confirms it for real
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
        # Deferred so the pages exist by the time this runs
        QTimer.singleShot(0, lambda: self._apply_view_settings(_vm, _ls, _gs))

        eq_pop = self._ensure_eq_popup()
        raw_profiles = cfg.get('eq_profiles', {})
        eq_profiles = {}
        for k, v in raw_profiles.items():
            if isinstance(v, dict):
                eq_profiles[k] = {'bands':  self._coerce_bands(v.get('bands', [])),
                                   'preamp': float(v.get('preamp', 0.0))}
            else:
                # Older configs stored a bare band list
                eq_profiles[k] = {'bands': self._coerce_bands(v), 'preamp': 0.0}
        eq_pop.set_profiles(eq_profiles)

        default_bands   = self._coerce_bands(cfg.get('default_eq_bands', []))
        default_enabled = cfg.get('default_eq_enabled', True)
        default_name    = cfg.get('default_eq_profile', '')
        eq_pop.set_default(default_bands, default_enabled, default_name)
        eq_pop.set_bands(default_bands, default_enabled, default_name)
        self._player.set_eq_enabled(default_enabled)
        self._player.set_eq_bands(default_bands)

        _lim  = cfg.get('limiter_enabled', False)
        _ste  = cfg.get('stereo_enabled',  False)
        _stw  = int(float(cfg.get('stereo_width', 50)))
        eq_pop.set_limiter_enabled(_lim)
        eq_pop.set_stereo_enabled(_ste)
        eq_pop.set_stereo_width(_stw)
        self._player._limiter_enabled = _lim
        self._player._stereo_enabled  = _ste
        self._player._stereo_width    = _stw

        _bal  = int(float(cfg.get('balance', 0)))
        eq_pop.set_balance(_bal)
        self._player._balance = _bal

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
                    'output_device': pop.output_device(),
                    'pipewire_adaptive_rate': pop.adaptive_rate_enabled()})
        eq_pop = self._ensure_eq_popup()
        cfg['eq_profiles'] = eq_pop.get_profiles()
        default_bands, default_enabled = eq_pop.get_default()
        cfg['default_eq_bands'] = default_bands
        cfg['default_eq_enabled'] = default_enabled
        cfg['default_eq_profile'] = eq_pop.get_default_name()
        cfg['limiter_enabled']    = eq_pop.limiter_enabled()
        cfg['stereo_enabled']     = eq_pop.stereo_enabled()
        cfg['stereo_width']       = eq_pop.stereo_width()
        cfg['balance']            = eq_pop.balance()
        cfg['eq_preamp_db']       = eq_pop.preamp_db()
        cfg['loudness_norm']      = eq_pop.loudness_norm_enabled()
        return cfg

    def _precompute_bars(self):
        dpr = self.devicePixelRatio()
        iw = round(self.width() * dpr)
        if iw < 2: return

        # Equal-width bars with a 1px gap: bw*VIZ_BANDS + (VIZ_BANDS-1) columns
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
        # Constant for a given width, so bars mode never rebuilds them per frame
        self._col_no_bar   = ~self._col_has_bar
        self._col_h_buf    = _np.empty(iw, dtype=_np.int32)   # per-column bar height
        self._col_y0_buf   = _np.empty(iw, dtype=_np.int32)   # per-column body top row

        # ── Cap pixel offset arrays — fully vectorized ────────────────────────────
        # Round bar caps only above 50% corner radius
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
                # Per row ri the columns are xl_v[ri] .. xl_v[ri]+widths[ri]-1
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

        # ── Freq mapping tables ───────────────────────────────────────────────
        if getattr(self, '_log_scale', True):
            F_MIN = 20.0; F_MAX = 20000.0
            FS_HALF = self._player.current_fs / 2.0
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

        else:
            FS_HALF   = self._player.current_fs / 2.0
            lin_scale = (20000.0 / FS_HALF) * GST_BANDS / VIZ_BANDS

            # ── Vectorized linear interp ──────────────────────────────────────
            fracs_arr = _np.arange(VIZ_BANDS, dtype=_np.float64) * lin_scale
            ba_arr    = _np.clip(fracs_arr.astype(_np.int32), 0, GST_BANDS - 1)
            bb_arr    = _np.minimum(ba_arr + 1, GST_BANDS - 1)
            bt_arr    = (fracs_arr - ba_arr.astype(_np.float64)).astype(_np.float32)

        self._player.set_viz_tables(
            ba_arr, bb_arr, bt_arr, self._inertia,
            overlay_cb=self._overlay_cb if self._overlay_viz_enabled else None
        )

        self._paint_bar_px     = _np.zeros(VIZ_BANDS, dtype=_np.int32)

        # Line-mode scratch arrays. Constant for a given width, so building them
        # here leaves paintEvent's interpolation allocation-free.
        self._line_col_x_i = _np.arange(iw, dtype=_np.int32)   # column indices for buf[y, col]
        # float32 throughout: the interpolation only ever feeds an int32 pixel
        # row, so float64 doubled the memory traffic for no extra precision.
        self._line_cy_buf  = _np.empty(VIZ_BANDS, dtype=_np.float32)  # reusable (ih - bar_px) buf
        self._line_y_f     = _np.empty(iw, dtype=_np.float32)   # reusable interpolated y
        self._line_y_tmp   = _np.empty(iw, dtype=_np.float32)   # reusable gather scratch
        self._line_y_int   = _np.empty(iw, dtype=_np.int32)     # reusable per-column y output

        # Interpolation tables replacing a per-frame np.interp. The bar→column
        # mapping is uniform, so bin_f[x] = x * (VIZ_BANDS-1) / (iw-1) splits into
        # a cached integer floor and fraction; each frame is then two gathers and
        # one multiply-add.
        _bin_scale        = float(VIZ_BANDS - 1) / max(1, iw - 1)
        _bf               = _np.arange(iw, dtype=_np.float32) * _bin_scale
        self._line_bin_i  = _np.clip(_bf.astype(_np.int32), 0, VIZ_BANDS - 2)
        self._line_bin_i1 = self._line_bin_i + 1                         # (iw,) int32
        self._line_bin_f  = (_bf - self._line_bin_i).astype(_np.float32) # (iw,) frac [0,1)

    def _interp_line_y(self, bar_px_arr, ih):
        """Interpolate VIZ_BANDS bar heights into one pixel row per column.

        Returns the shared (iw,) int32 buffer, filled in place. np.take with
        out= replaces the fancy-index gathers, and the float32 scratch rows are
        reused, so a frame allocates nothing here.
        """
        cy = self._line_cy_buf
        _np.subtract(ih, bar_px_arr, out=cy, casting='unsafe')
        yf  = self._line_y_f
        tmp = self._line_y_tmp
        _np.take(cy, self._line_bin_i,  out=yf)
        _np.take(cy, self._line_bin_i1, out=tmp)
        _np.subtract(tmp, yf, out=tmp)
        _np.multiply(tmp, self._line_bin_f, out=tmp)
        _np.add(yf, tmp, out=yf)
        # Clamping in float before the truncating cast matches the previous
        # cast-then-clip: both saturate identically at either end.
        _np.clip(yf, 0.0, ih - 1, out=yf)
        out = self._line_y_int
        _np.copyto(out, yf, casting='unsafe')
        return out

    def _blend_rows(self, buf, y0_row, ih, iw, px_bg, px_fg):
        """Compose bg + (fg - bg) * mask into buf, mask being row >= y0_row.

        One arithmetic sweep over a reused uint32 scratch, replacing an
        (ih, iw) boolean mask allocation plus a masked scatter write — the
        scatter builds an index list over the whole buffer, so at 60 fps it
        dominated the frame. The delta is masked to 32 bits because fg < bg is
        normal in a light theme and numpy will not cast a negative Python int
        to uint32; wraparound makes the addition exact anyway.
        """
        m32 = self._px_m32
        if m32 is None or m32.shape != (ih, iw):
            m32 = self._px_m32 = _np.empty((ih, iw), dtype=_np.uint32)
        _np.greater_equal(self._px_row_idx, y0_row, out=m32, casting='unsafe')
        _np.multiply(m32, _np.uint32((px_fg - px_bg) & 0xFFFFFFFF), out=m32)
        _np.add(m32, _np.uint32(px_bg), out=buf)

    def _start_render_timer(self):
        """Start the fixed-rate render timer with a fresh deadline."""
        self._render_timer.setInterval(_FRAME_MS)
        _gc.disable()   # prevent GC pauses during render loop
        self._render_timer.start()

    def _stop_render_timer(self):
        """Stop the render timer and re-enable GC.

        Always paired with _start_render_timer: GC stays off for as long as the
        timer runs, so every stop path has to turn it back on or cyclic garbage
        is never collected again.
        """
        self._render_timer.stop()
        _gc.enable()

    def _on_viz_toggle(self, on: bool):
        self._viz_on = on
        self._player.set_viz_active(on and not self._viz_paused)
        if on and self._player.playing and not self._viz_paused:
            self._start_render_timer()
        else:
            if not self._overlay_viz_enabled:
                self._stop_render_timer()
            self._player._viz_spec[:] = MIN_DB
            self._player._viz_reset_queue()
        self.update()

    def _on_log_toggle(self, on: bool):
        self._log_scale = on
        # Flush stale bars so the old mapping does not bleed into the first frame
        self._player._viz_bar_buf[:] = 0.0
        self._player._viz_spec[:]    = MIN_DB
        self._player._viz_reset_queue()
        self._precompute_bars()
        self.update()

    def _on_delay_change(self, v: int):
        self._delay_ms = v
        # Drop frames buffered at the old delay. It refills in about a second;
        # until then _render_tick shows the live frame.
        self._viz_rbuf_head  = 0
        self._viz_rbuf_count = 0

    def _overlay_cb(self, bh_list):
        """Hand a finished, delay-adjusted viz frame to the blackout overlay.

        Called by _render_tick while overlay viz is active, with the same
        _viz_display_buf the docked bar paints from — so the overlay honours
        the Delay slider too instead of always showing the raw live frame.
        """
        _bref = getattr(self, '_blackout_ref', None)
        if _bref is not None:
            _bref.push_viz_frame(bh_list)

    def _on_inertia_change(self, v: int):
        # The slider value is the EMA alpha in percent
        self._inertia = v / 100.0
        self._player._viz_inertia = self._inertia

    def _on_brightness_change(self, v: int):
        self._brightness_v = v
        t = v / 100.0          # 0.0 → 1.0

        acc  = QColor(ACC)
        ah, as_, al, _ = acc.getHsvF()

        if _DARK_MODE:
            # Dim desaturated accent up to the vivid accent, never reaching black
            luma  = max(0.10, al * (0.15 + 0.85 * t))
            tint  = QColor()
            sat   = as_ * (0.50 + 0.50 * t)
            tint.setHsvF(ah, sat, luma)
        else:
            # Light mode runs from a background-tinted tint to a readable vivid
            # accent, never reaching pure white or black.
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
        # Force a fresh pixel buffer for the new style
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
        # Broadcast so _r() returns the new value everywhere
        _cm.RAD_PCT = RAD_PCT
        _cm._broadcast_palette()

        if not hasattr(self, '_radius_debounce'):
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(300)
            t.timeout.connect(self._radius_apply)
            self._radius_debounce = t

        win = self.window()
        if win is not None and win.isVisible():
            # Live drag: overlay once, then debounce the rebuild
            if not getattr(self, '_radius_overlay', None):
                ov = _SpinningOverlay(win)
                ov.show(); ov.raise_()
                QApplication.processEvents()   # let overlay paint before heavy work
                self._radius_overlay = ov
            self._radius_debounce.start()
        else:
            # Config restore, before the window is up — apply straight away
            self._radius_debounce.stop()
            self._radius_apply()

    def _radius_apply(self):
        """Heavy part: rebuild every radius-bearing stylesheet, then dismiss overlay."""
        global SS
        SS = make_stylesheet(ACC, ACCH)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(SS)
        # The seek slider's radius is inline, so the global sheet misses it
        self._seek.update_radius()
        _ts = (f'QPushButton#ctrl {{ background:transparent; border:none; color:{FG2};'
               f' font-size:20px; border-radius:{_r(22)}px; padding:0; text-align:center; }}'
               f'QPushButton#ctrl:hover {{ color:{FG}; background:{BG3}; }}'
               f'QPushButton#ctrl:checked {{ color:{ACC}; background:transparent; }}'
               f'QPushButton#ctrl:pressed {{ background:{BG4}; }}')
        for b in (self.btn_shuf, self.btn_prev, self.btn_next):
            b.setStyleSheet(_ts)
        self.btn_play.update()   # colors (BG3/ACC/ACCH/BG4) are read live in paintEvent
        pop = self._settings_popup
        if pop is not None:
            pop._accent_btn.setStyleSheet(
                f'QPushButton#accent_swatch {{'
                f'  background:{ACC}; border-radius:{_r(16)}px; border:2px solid #666;'
                f'  min-width:32px; max-width:32px; min-height:32px; max-height:32px;'
                f'  padding:0;'
                f'}}')
        # Bar cap geometry depends on RAD_PCT too
        self._precompute_bars()
        self.update()
        # Reaches the remaining inline-styled widgets (search box, sort buttons,
        # sidebar, combo boxes).
        self.accent_changed.emit(ACC)
        ov = getattr(self, '_radius_overlay', None)
        if ov is not None:
            ov.close_overlay()
            self._radius_overlay = None

    def _on_accent_change(self, color: str):
        # apply_accent() decides whether ACC really changes — under SYS mode it
        # only records the pick. Setting ACC/ACCH/SS here would bypass that.
        apply_accent(color)
        if is_system_qt_theme_active():
            # ACC did not change, so the cache clears, file deletions and
            # restyling below would all be wasted work on every startup.
            return
        self._on_brightness_change(self._brightness_v)
        _cover_cache.clear()
        _default_cover_mem_cache.clear()
        _acc_lut_cache.clear()   # accent hue changed — rebuild LUT on next paint
        self._cover_lbl._acc_pm = None
        # Drop the placeholder-cover files; they are keyed by the old accent
        for f in CONFIG_PATH.parent.glob('default_cover_*'):
            try: f.unlink()
            except Exception: pass
        # Transport buttons read the palette globals inline
        _ts = (f'QPushButton#ctrl {{ background:transparent; border:none; color:{FG2};'
               f' font-size:20px; border-radius:{_r(22)}px; padding:0; text-align:center; }}'
               f'QPushButton#ctrl:hover {{ color:{FG}; background:{BG3}; }}'
               f'QPushButton#ctrl:checked {{ color:{ACC}; background:transparent; }}'
               f'QPushButton#ctrl:pressed {{ background:{BG4}; }}')
        for b in (self.btn_shuf, self.btn_prev, self.btn_next):
            b.setStyleSheet(_ts)
        self.btn_play.update()   # colors (BG3/ACC/ACCH/BG4) are read live in paintEvent
        self.accent_changed.emit(color)
    def _on_cover_toggle(self, on: bool, _emit: bool = True):
        self._cover_lbl.setVisible(on)
        if on and self._cur_track:
            pm = get_cover_pixmap(self._cur_track.filepath, 64)
            self._cover_lbl.setPixmap(pm if pm is not None else draw_default_cover(64),
                                      self._cur_track.filepath)
        # Skipped when the overlay path will already update the pages
        if _emit:
            self.cover_on_changed.emit(on)

    def _on_cover_acc_toggle(self, on: bool):
        """Cover-accent switch toggled — set the flag and repaint all views."""
        import cover_art as _cover_art_mod
        self._cover_acc_on = on
        _cover_art_mod._COVER_ACC_ON = on   # get_cover_pixmap reads it from there
        _acc_lut_cache.clear()   # rebuild the LUT for the current accent
        _cover_art_mod._acc_lut_cache.clear()
        self._cover_lbl.set_cover_accent_mode(on)
        self.accent_changed.emit(ACC)   # triggers MainWindow gallery/list repaint

    def _on_seek_flush(self):
        """Mark viz as awaiting first post-seek frame."""
        self._player._viz_spec[:] = MIN_DB
        self._player._viz_reset_queue()
        self._player._viz_bar_buf[:] = 0.0
        # Drop spectrum frames for 150 ms so pre-seek audio never shows up
        self._player._viz_discard_until = _monotonic() + 0.15
        # Also drop the delay-compensation ring buffer, or a nonzero Delay
        # setting replays pre-seek frames for the next delay_ms. The display
        # buffer itself must be cleared too — an empty ring buffer makes
        # _render_tick fall back to "keep the previous frame" until a fresh
        # one ages past delay_ms, which would still be this stale one.
        self._viz_rbuf_head  = 0
        self._viz_rbuf_count = 0
        self._viz_display_buf[:] = 0.0
        self.update()

    def set_focus_paused(self, paused: bool):
        self._focus_paused = paused
        self._viz_paused = paused or not self._player.playing
        self._player.set_viz_active(self._viz_on and not paused)
        if self._overlay_viz_enabled:
            self._player.set_overlay_needs_spectrum(True)
        if self._viz_paused:
            self._stop_render_timer()
            self._player._viz_spec[:] = MIN_DB
            self._player._viz_reset_queue()
            self.update()
        elif (self._viz_on or self._overlay_viz_enabled) and self._player.playing:
            self._start_render_timer()

    def _render_tick(self):
        # Nothing to draw when the overlay covers the bar and its own viz is off
        needs_render = (self._viz_on and not self._overlay_open) or self._overlay_viz_enabled
        if not needs_render or self._viz_paused:
            self._stop_render_timer()
            return
        # Runs every tick: gating on message arrival would tie the frame rate to
        # the codec's block size. _compute_viz_frame paces the queue itself.
        self._player._compute_viz_frame()
        if not self._player._viz_has_any:
            # No spectrum has arrived for this track yet — stop if playback ended
            # or nothing needs rendering any more.
            if not self._player.playing or not needs_render:
                self._stop_render_timer()
                if self._viz_on:
                    self.update()
            return

        _now = _monotonic()
        if (_now - self._render_last_wt) < _FRAME_S * 0.85:
            return
        self._render_last_wt = _now

        # ── Delay: ring-buffer the viz frames, expose the one delay_ms in the past ─
        delay_ms = self._delay_ms
        src      = self._player._viz_bar_buf
        if delay_ms > 0:
            N    = self._viz_rbuf_n
            head = self._viz_rbuf_head
            self._viz_rbuf[head]   = src
            self._viz_rbuf_ts[head] = _now
            self._viz_rbuf_head    = (head + 1) % N
            self._viz_rbuf_count   = min(self._viz_rbuf_count + 1, N)
            # Newest frame that is already at least delay_ms old. Masking then
            # argmax keeps the timestamps in numpy instead of boxing each one.
            target_t = _now - delay_ms * 0.001
            count    = self._viz_rbuf_count
            ts       = self._viz_rbuf_ts[:count]
            eligible = ts <= target_t
            if eligible.any():
                best_idx = int(_np.argmax(_np.where(eligible, ts, -1.0)))
                _np.copyto(self._viz_display_buf, self._viz_rbuf[best_idx])
            # Otherwise the buffer is still filling — keep the previous frame
        else:
            self._viz_rbuf_head  = 0
            self._viz_rbuf_count = 0
            _np.copyto(self._viz_display_buf, src)

        if self._overlay_viz_enabled:
            # Delay-adjusted frame, so the OLED overlay's bars line up with the
            # docked bar's instead of racing ahead by delay_ms.
            cb = self._player._viz_overlay_cb
            if cb is not None:
                cb(self._viz_display_buf)

        if self._viz_on:
            # update() invalidates the whole bar, repainting every child widget on
            # top of the viz, which dominates a frame's cost. Comparing the integer
            # bar heights the painter uses skips identical frames and absorbs
            # sub-pixel drift, so quiet passages stop repainting altogether.
            ih  = round(self.height() * self.devicePixelRatio())
            cur = self._viz_px_cur
            _np.multiply(self._viz_display_buf, ih, out=cur, casting='unsafe')
            if ih != self._viz_last_ih or not _np.array_equal(cur, self._viz_px_last):
                self._viz_last_ih = ih
                _np.copyto(self._viz_px_last, cur)
                self.update()


    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Shrink the margins so content does not clip in a short bar
        h = self.height()
        v_margin = max(4, min(14, (h - 110) * 14 // 62))  # 0→4px at 110, 14px at 172+
        self._root_layout.setContentsMargins(18, v_margin, 18, v_margin)
        self._root_layout.setSpacing(max(2, min(10, (h - 110) * 10 // 62)))
        # The transport and icon buttons are already near their minimum, so at the
        # window's 480px floor they alone can overflow the row. Cover art, the
        # track-name column and the play button have headroom, so they shrink.
        w = self.width()
        cov_sz, title_max, play_sz = next(
            (c, t, p) for wmin, c, t, p in self._NOWPLAYING_BREAKPOINTS if w >= wmin)
        if cov_sz != self._cover_lbl._sz:
            self._cover_lbl.set_size(cov_sz)
            self._txt_w.setFixedHeight(cov_sz)
        if title_max != self._lbl_title.maximumWidth():
            self._lbl_title.setMaximumWidth(title_max)
            self._lbl_artist.setMaximumWidth(title_max)
            self._apply_now_playing_text()
        self.btn_play.set_size(play_sz)
        # The cached frame belongs to the old geometry — force a repaint
        self._viz_px_last[:] = -1
        # Debounced so a resize drag does not rebuild the tables per pixel
        self._resize_timer.start()

    def _apply_now_playing_text(self):
        """(Re-)elide title/artist against their current maximumWidth.
        Called on track change and whenever resizeEvent's responsive
        breakpoint changes that width, so text elides with '…' instead of
        being abruptly clipped mid-character at narrow window widths."""
        fm_t = QFontMetrics(self._lbl_title.font())
        fm_a = QFontMetrics(self._lbl_artist.font())
        self._lbl_title.setText(fm_t.elidedText(
            self._now_title_raw, Qt.TextElideMode.ElideRight, self._lbl_title.maximumWidth()))
        self._lbl_artist.setText(fm_a.elidedText(
            self._now_artist_raw, Qt.TextElideMode.ElideRight, self._lbl_artist.maximumWidth()))

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
        # Built before the viz branch so the paused fallback below always has
        # them, even on the very first paint.
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
                    # Reallocate the pixel buffer with the new colours
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

                    # Same precomputed interpolation tables as line mode
                    line_y_i = self._interp_line_y(bar_px_arr, ih)

                    # Background and bars composed in one sweep — this also
                    # writes every pixel, so no separate buf[:] = bg memset.
                    self._blend_rows(buf, line_y_i, ih, iw,
                                     self._px_bg, self._px_bar)

                    p.drawImage(0, 0, self._px_qimg)
                    p.setPen(self._paint_bord_pen)
                    p.drawLine(0, 0, iw, 0)
                    p.end()
                    return

                if self._viz_type == 'line':
                    # ── LINE MODE — pixel-buffer + Bresenham span fill ─────────
                    # Written straight into the pixel buffer, no antialiased
                    # QPainter work. Steep slopes get a vertical span so the line
                    # stays connected.
                    bar_px_arr = self._paint_bar_px
                    _np.multiply(bh, ih, out=bar_px_arr, casting='unsafe')

                    if len(self._col_has_bar) != iw:
                        p.end()
                        return

                    # ── Interpolation: VIZ_BANDS → iw y-positions ─────────────
                    line_y_i = self._interp_line_y(bar_px_arr, ih)

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
                    # Fill between adjacent y values wherever |Δy| > 1. Only a
                    # handful of columns are ever that steep.
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

                    line_y_i = self._interp_line_y(bar_px_arr, ih)

                    if self._px_shape != (ih, iw):
                        self._px_buf   = _np.full((ih, iw), self._px_bg, dtype=_np.uint32)
                        self._px_qimg  = QImage(self._px_buf.data, iw, ih,
                                                iw * 4, QImage.Format.Format_ARGB32_Premultiplied)
                        self._px_shape   = (ih, iw)
                        self._px_row_idx = _np.arange(ih, dtype=_np.int32)[:, _np.newaxis]

                    buf = self._px_buf

                    # Bar colour blended onto BG, recomputed only when either changes
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
                    # Also writes the background, so no separate memset above.
                    self._blend_rows(buf, line_y_i, ih, iw, self._px_bg, px_fill)

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

                cap_r    = self._cap_r_offsets   # (n_cap_pix,) int32
                cap_c    = self._cap_c_offsets   # (n_cap_pix,) int32
                radius   = self._cap_radius
                use_caps = radius > 0 and len(cap_r) > 0 and bw > 4

                # ── Body fill ─────────────────────────────────────────────────
                # Step 1: per-column bar height, gathered through the column map
                col_has  = self._col_has_bar
                cb_safe  = self._col_bar_safe
                # The column map can still be the old width if the debounced
                # _precompute_bars() has not run yet — skip rather than mismatch.
                if len(col_has) != iw:
                    p.end()
                    return
                # Written through preallocated buffers: the np.where/arithmetic
                # chain this replaces built six (iw,) temporaries every frame.
                col_h = self._col_h_buf
                _np.take(bar_px_arr, cb_safe, out=col_h)
                # Step 2: with caps on, the body starts below the cap. Empty
                # columns get a top row of ih+1, which no row can reach, folding
                # the "is there a bar" test into the same comparison.
                body_offset = radius if use_caps else 0
                _np.subtract(col_h, body_offset, out=col_h)
                _np.maximum(col_h, 0, out=col_h)
                col_y0_body = self._col_y0_buf
                _np.subtract(ih, col_h, out=col_y0_body)
                _np.copyto(col_y0_body, ih + 1, where=self._col_no_bar)
                # Step 3: compose background and bars in one arithmetic sweep
                self._blend_rows(buf, col_y0_body, ih, iw, px_bg, px_bar)

                # ── Cap fill ───────────────────────────────────────────────────
                # y0s/x0s are each eligible bar's top-left; cap_r/cap_c the offsets
                # within a cap. Broadcasting them gives the full index grid, and one
                # in-bounds mask flattens it to a single write.
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

        # Viz off or paused. iw/ih are physical pixels and the painter is scaled by
        # 1/dpr, so this rect covers the whole widget on a high-DPI screen.
        p.fillRect(QRectF(0, 0, iw, ih), self._paint_bg_brush)
        p.setPen(self._paint_bord_pen)
        p.drawLine(0, 0, iw, 0)
        p.end()

    def _on_playing_changed(self, playing: bool):
        if playing:
            _focus_paused = getattr(self, '_focus_paused', False)
            self._viz_paused = _focus_paused
            self._player.set_viz_active(self._viz_on and not _focus_paused)
            # Only start the timer when something needs rendering: _render_tick's
            # early exit cannot stop one that should never have started.
            if (self._viz_on or self._overlay_viz_enabled) and not _focus_paused:
                self._start_render_timer()
        else:
            self._viz_paused = True
            # Silence the spectrum element before _destroy() hands the dying
            # pipeline off for teardown, otherwise its FFT keeps running at
            # 30 fps while the new pipeline prerolls.
            self._player.set_viz_active(False)
            self._stop_render_timer()
            self._player._viz_spec[:] = MIN_DB
            self._player._viz_reset_queue()
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
            # seek() has already moved the anchor, so the UI can update now
            self._on_pos(self._player.position_ms())
        self._seeking = False

    def _on_moved(self, val):
        if self._dur_ms > 0: self._lbl_cur.setText(self._fmt(int(val*self._dur_ms/1000)))

    def _on_pos(self, ms):
        if self._seeking or self._seek.isSliderDown() or self._dur_ms == 0: return
        new_val = int(ms * 1000 / self._dur_ms)
        # Only touch the widgets on a real change, to avoid a repaint per tick
        if new_val != getattr(self, '_last_seek_val', -1):
            self._last_seek_val = new_val
            self._seek.setValue(new_val)
        new_txt = self._fmt(ms)
        if new_txt != getattr(self, '_last_time_txt', ''):
            self._last_time_txt = new_txt
            self._lbl_cur.setText(new_txt)
        # The AUDIO INFO rate label is a snapshot from load time. Under adaptive
        # rate another app can retune the shared graph, quietly invalidating it and
        # leaving a stale "bit-perfect" claim. Re-check every ~3 s while the popup
        # is open; the underlying lookups are cached for 5 s, so it is cheap.
        if self._settings_popup is not None and self._settings_popup.isVisible():
            now = _monotonic()
            if now - getattr(self, '_last_audio_info_refresh_wt', 0.0) >= 3.0:
                self._last_audio_info_refresh_wt = now
                self._refresh_audio_info()

    def _on_dur(self, ms): self._dur_ms = ms; self._lbl_tot.setText(self._fmt(ms))

    def refresh_theme(self):
        """Re-apply theme after a dark/light switch.
        Re-renders the cover label so it picks up the new background colour
        and, when cover-accent mode is on, rebuilds the LUT for the new mode
        (dark: black→accent, light: accent→white).
        """
        sz = self._cover_lbl._sz
        if self._cover_lbl._cover_acc_mode:
            # Drop the cached accent pixmap so it rebuilds with the new LUT
            self._cover_lbl._acc_pm = None
            self._cover_lbl._acc_pm_key = None
        if self._cover_lbl.isVisible() and self._cur_track is not None:
            pm = get_cover_pixmap(self._cur_track.filepath, sz)
            self._cover_lbl.setPixmap(pm if pm is not None else draw_default_cover(sz), self._cur_track.filepath)
        elif self._cover_lbl.isVisible():
            self._cover_lbl.setPixmap(draw_default_cover(sz))

    def set_track(self, t: Track):
        self._now_title_raw  = t.title or Path(t.filepath).name
        self._now_artist_raw = t.artist
        self._apply_now_playing_text()
        self._seek.setValue(0); self._lbl_cur.setText('0:00')
        self._dur_ms = int(t.duration*1000); self._lbl_tot.setText(t.dur_str())
        self._player._viz_spec[:] = MIN_DB
        self._player._viz_reset_queue()
        # Delay-compensation ring buffer holds frames from the old track — drop
        # them so a nonzero Delay setting does not replay the last track's viz
        # into the first delay_ms of the new one. _viz_display_buf itself must
        # go too: with the ring buffer empty, _render_tick finds nothing
        # eligible until a fresh frame ages past delay_ms and, until then,
        # falls back to "keep the previous frame" — which would still be this
        # stale one.
        self._viz_rbuf_head  = 0
        self._viz_rbuf_count = 0
        self._viz_display_buf[:] = 0.0
        if self._cover_lbl.isVisible():
            pm = get_cover_pixmap(t.filepath, 64)
            self._cover_lbl.setPixmap(pm if pm is not None else draw_default_cover(64), t.filepath)
        self._cur_track = t
        if self._settings_popup is not None and self._settings_popup.isVisible():
            self._refresh_audio_info()

    def set_play_icon(self, playing: bool):
        self.btn_play.set_playing_icon(playing)

    def set_play_busy(self, busy: bool):
        """Show/hide spinner on play button during pipeline reload."""
        self.btn_play.set_busy(busy)

    _fmt = staticmethod(_fmt_ms)   # alias for backward compatibility
