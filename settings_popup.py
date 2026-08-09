"""
VoidPulse — SettingsPopup: app settings panel (audio device, viz, EQ toggles, theme, cover).
"""
from constants import *

from player import Player
from eq import TouchComboBox
from constants import ACC, RAD_PCT, _r, apply_theme, apply_system_qt_theme
import constants as _c   # live module reference — paintEvent/refresh_theme read _c.ACC etc.
from widgets_base import ToggleSwitch, TriSwitch, JumpSlider, SliderRow, _SpinningOverlay
from alsa import probe_alsa_devices

class SettingsPopup(QFrame):
    viz_toggled    = pyqtSignal(bool)
    log_toggled    = pyqtSignal(bool)
    volume_changed = pyqtSignal(int)
    delay_changed  = pyqtSignal(int)
    inertia_changed    = pyqtSignal(int)
    brightness_changed = pyqtSignal(int)   # 0..100
    cover_toggled        = pyqtSignal(bool)
    cover_accent_toggled = pyqtSignal(bool)
    accent_changed       = pyqtSignal(str)
    lyrics_fetch_toggled = pyqtSignal(bool)
    overlay_viz_toggled    = pyqtSignal(bool)
    overlay_lyrics_toggled = pyqtSignal(bool)
    overlay_scale_changed  = pyqtSignal(int)  # 50..200 percent
    overlay_auto_open_toggled = pyqtSignal(bool)   # auto-open on idle
    overlay_timeout_changed   = pyqtSignal(int)    # idle seconds (10..300)
    overlay_clock_toggled     = pyqtSignal(bool)   # show/hide clock in overlay
    cover_fetch_toggled = pyqtSignal()   # emitted when user clicks "Fetch Covers" button
    lyric_fetch_action  = pyqtSignal()   # emitted when user clicks "Fetch Lyrics" button
    tag_fetch_toggled    = pyqtSignal()   # emitted when user clicks "Fetch Tags" button
    rename_toggled       = pyqtSignal()   # emitted when user clicks "Rename…" button
    gain_fetch_action    = pyqtSignal()   # emitted when user clicks "Fetch Gain" button
    view_mode_changed    = pyqtSignal(str)   # 'classic' | 'gallery_z' | 'gallery_s'
    list_scale_changed   = pyqtSignal(int)   # row height px
    gallery_scale_changed = pyqtSignal(int)  # card size px
    viz_type_changed     = pyqtSignal(str)   # 'bars' | 'line'
    radius_changed       = pyqtSignal(int)   # 0..100 corner-radius percentage
    output_device_changed = pyqtSignal(str)  # 'pipewire' | 'plughw:X,Y'
    adaptive_rate_toggled = pyqtSignal(bool)  # PipeWire adaptive sample-rate opt-in
    bg_opt_toggled        = pyqtSignal(bool)  # True = throttle viz/polling while unfocused
    crossfade_changed     = pyqtSignal(int)   # track-change overlap, ms (0 = off)
    fade_changed          = pyqtSignal(int)   # play/pause fade, ms (0 = off)
    sleep_timer_changed   = pyqtSignal(int)   # minutes until playback stops (0 = off)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('settings_popup')
        # A child widget, not a top-level one, so move() works on Wayland
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)
        self.hide()  # start hidden
        # When the last outside click hid the popup, so the button's own toggle
        # from that same click does not reopen it.
        self._hide_timestamp_ms: int = 0
        QApplication.instance().installEventFilter(self)


        # ── Outer root: title + two-column body ──────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(4)

        hdr = QLabel('SETTINGS'); hdr.setObjectName('popup_title')
        hdr.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(hdr)

        title_div = QFrame(); title_div.setFixedHeight(1)
        title_div.setStyleSheet(f'background:{_c.BORD}; margin:0;')
        root.addWidget(title_div)
        self._themed_dividers = []   # populated by _hdivider()/_vdivider() below
        self._section_lbls   = []   # populated by _section() below

        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.setAlignment(Qt.AlignmentFlag.AlignTop)
        root.addLayout(columns)

        # Collected so refresh_theme() can re-colour them
        def _vdivider():
            d = QFrame()
            d.setFrameShape(QFrame.Shape.VLine)
            d.setStyleSheet(f'color:{_c.BORD};')
            self._themed_dividers.append(d)
            return d

        def _hdivider():
            d = QFrame(); d.setFixedHeight(1)
            d.setStyleSheet(f'background:{_c.BORD}; margin:0;')
            self._themed_dividers.append(d)
            return d

        def _section(title):
            lbl = QLabel(title)
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lbl.setStyleSheet(
                f'color:{_c.FG2};font-size:9px;letter-spacing:2px;background:transparent;')
            self._section_lbls.append(lbl)
            return lbl

        # ── LEFT COLUMN: OVERLAY + VIEW ───────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(3)
        left.setAlignment(Qt.AlignmentFlag.AlignTop)
        columns.addLayout(left, 1)

        # OVERLAY section
        left.addWidget(_section('OVERLAY'))

        ov_row = QHBoxLayout(); ov_row.setSpacing(10)
        ov_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._ov_viz_sw    = ToggleSwitch('VIZ',    self)
        self._ov_lyrics_sw = ToggleSwitch('LYRICS', self)
        self._ov_clock_sw  = ToggleSwitch('CLOCK',  self)
        self._ov_viz_sw.setChecked(False); self._ov_lyrics_sw.setChecked(False)
        self._ov_clock_sw.setChecked(True)
        self._ov_viz_sw.toggled.connect(self.overlay_viz_toggled)
        self._ov_lyrics_sw.toggled.connect(self.overlay_lyrics_toggled)
        self._ov_clock_sw.toggled.connect(self.overlay_clock_toggled)
        ov_row.addWidget(self._ov_viz_sw)
        ov_row.addWidget(self._ov_lyrics_sw)
        ov_row.addWidget(self._ov_clock_sw)
        left.addLayout(ov_row)

        self._ov_scale_row = SliderRow('Scale', 50, 200, 100, lambda v: f'{v}%')
        self._ov_scale_row.valueChanged.connect(self.overlay_scale_changed)
        left.addWidget(self._ov_scale_row)

        auto_row = QHBoxLayout(); auto_row.setSpacing(10)
        auto_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._ov_auto_sw = ToggleSwitch('Auto Timeout Overlay', self)
        self._ov_auto_sw.setChecked(False)
        self._ov_auto_sw.toggled.connect(self.overlay_auto_open_toggled)
        auto_row.addWidget(self._ov_auto_sw)
        left.addLayout(auto_row)

        self._ov_timeout_row = SliderRow('Timeout', 10, 300, 60, lambda v: f'{v}s')
        self._ov_timeout_row.valueChanged.connect(self.overlay_timeout_changed)
        left.addWidget(self._ov_timeout_row)

        # VIEW section
        left.addWidget(_hdivider())
        left.addWidget(_section('VIEW'))

        view_combo_row = QHBoxLayout(); view_combo_row.setSpacing(8)
        view_combo_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        view_combo_lbl = QLabel('Layout'); view_combo_lbl.setObjectName('setting_lbl')
        view_combo_lbl.setFixedWidth(55)
        view_combo_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._view_combo = TouchComboBox()
        self._view_combo.addItem('Classic')
        self._view_combo.addItem('Gallery (Z)')
        self._view_combo.addItem('Gallery (S)')
        self._view_combo.currentTextChanged.connect(
            lambda t: self.view_mode_changed.emit(
                self._COMBO_TO_MODE.get(t, 'classic')))
        view_combo_row.addWidget(view_combo_lbl)
        view_combo_row.addWidget(self._view_combo, 1)
        left.addLayout(view_combo_row)

        self._list_scale_row = SliderRow('List size', 28, 80, 44, lambda v: f'{v}px')
        self._list_scale_row.valueChanged.connect(self.list_scale_changed)
        left.addWidget(self._list_scale_row)

        self._gallery_scale_row = SliderRow('Gallery size', 80, 220, 130, lambda v: f'{v}px', step=8)
        self._gallery_scale_row.valueChanged.connect(self.gallery_scale_changed)
        left.addWidget(self._gallery_scale_row)

        # Accent + theme + cover row. Four controls (swatch, DARK/LIGHT, SYS and
        # the cover TriSwitch) ask for more than the left column's ~300px at the
        # usual 10px spacing, and the shortfall used to make the SYS switch
        # overlap and cut off the 'LIGHT' label — hence the tight spacing and
        # the reduced label gap on the two switches below.
        acc_row = QHBoxLayout(); acc_row.setSpacing(4)
        acc_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._accent_color = ACC
        self._accent_btn = QPushButton()
        self._accent_btn.setObjectName('accent_swatch')
        self._accent_btn.setFixedSize(32, 32)
        self._accent_btn.setStyleSheet(
            f'QPushButton#accent_swatch {{' 
            f'  background:{ACC}; border-radius:{_r(16)}px; border:2px solid #666;'
            f'  min-width:32px; max-width:32px; min-height:32px; max-height:32px;'
            f'  padding:0;'
            f'}}')
        self._accent_btn.clicked.connect(self._pick_accent)
        self._theme_sw = ToggleSwitch('DARK', 'LIGHT', self, muted_labels=True,
                                      label_point_size=7, pad=3, track_w=36)
        self._theme_sw.setChecked(False)
        self._theme_sw.toggled.connect(self._on_theme_toggle)
        # When on, colours come from the desktop's live Qt palette instead of the
        # built-in dark/light ones. Works under any Qt-aware desktop.
        self._system_theme_sw = ToggleSwitch('', 'SYS', self, muted_labels=True,
                                             label_point_size=7, pad=3, track_w=36)
        self._system_theme_sw.setChecked(False)
        self._system_theme_sw.toggled.connect(self._on_system_theme_toggle)
        self._system_theme_sw.setToolTip(
            'SYS: follow the desktop\'s live Qt theme (colors, accent, live updates)\n'
            'Works via qt6ct (Hyprland, or any WM/DE) and xdg-desktop-portal\n'
            '(KDE Plasma, GNOME, etc.) — updates automatically if you change\n'
            'the system color scheme while VoidPulse is running.'
        )
        # 0 = no cover, 1 = cover, 2 = cover recoloured to the accent
        self._cover_tri = TriSwitch(self)
        self._cover_tri.setState(1)   # default: cover on, no accent
        self._cover_tri.stateChanged.connect(self._on_cover_tri_changed)
        acc_row.addWidget(self._accent_btn)
        acc_row.addWidget(self._theme_sw)
        acc_row.addWidget(self._system_theme_sw)
        acc_row.addWidget(self._cover_tri)
        left.addLayout(acc_row)

        self._radius_row = SliderRow('Corners', 0, 100, RAD_PCT, lambda v: f'{v}%')
        self._radius_row.valueChanged.connect(self.radius_changed)
        left.addWidget(self._radius_row)

        # ── AUDIO INFO ───────────────────────────────────────────────────────
        # ControlBar._refresh_audio_info() fills these in.
        left.addWidget(_hdivider())
        left.addWidget(_section('AUDIO INFO'))

        def _info_row(label_text, add_to_layout=True):
            row = QHBoxLayout(); row.setSpacing(4)
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label_text); lbl.setObjectName('setting_lbl')
            lbl.setFixedWidth(52)
            lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            val = QLabel('—'); val.setObjectName('setting_lbl')
            val.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(lbl); row.addWidget(val, 1)
            if add_to_layout:
                left.addLayout(row)
            return val, row

        self._info_fmt, _ = _info_row('Format')

        _dsp_stereo_row = QHBoxLayout(); _dsp_stereo_row.setSpacing(4)
        _dsp_stereo_row.setContentsMargins(0, 0, 0, 0)
        self._info_eq = QLabel('—'); self._info_eq.setObjectName('setting_lbl')
        self._info_eq.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._info_stereo = QLabel('—'); self._info_stereo.setObjectName('setting_lbl')
        self._info_stereo.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        _dsp_stereo_row.addWidget(self._info_eq, 1)
        _dsp_stereo_row.addWidget(self._info_stereo, 1)
        left.addLayout(_dsp_stereo_row)

        self._info_dev, _ = _info_row('Device')

        # Adaptive sample rate sits under AUDIO INFO rather than beside the
        # output-device combo: it belongs to the same subject, and the left
        # column has the spare height, so the popup stays shorter overall.
        left.addSpacing(6)
        adaptive_row = QHBoxLayout(); adaptive_row.setSpacing(8)
        adaptive_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._adaptive_sw = ToggleSwitch('Adaptive Sample Rate', self)
        self._adaptive_sw.setChecked(False)   # off by default — explicit opt-in
        self._adaptive_sw.setToolTip(
            "Lets PipeWire switch its whole audio graph to match a device's "
            "native sample rate (e.g. 44.1 kHz) instead of always running at "
            "48 kHz, so VoidPulse's resampler can do the full conversion in "
            "one pass. Affects ALL apps sharing PipeWire, not just VoidPulse. "
            "Writes ~/.config/pipewire/pipewire.conf.d/99-voidpulse-adaptive-rate.conf "
            "— requires restarting PipeWire/WirePlumber (or logging out and "
            "back in) to take effect.")
        self._adaptive_sw.toggled.connect(self.adaptive_rate_toggled)
        adaptive_row.addWidget(self._adaptive_sw)
        left.addLayout(adaptive_row)

        columns.addWidget(_vdivider())

        # ── RIGHT COLUMN: VISUALIZATION + FETCH + VOLUME ─────────────────────
        right = QVBoxLayout()
        right.setSpacing(3)
        right.setAlignment(Qt.AlignmentFlag.AlignTop)
        columns.addLayout(right, 1)

        # VISUALIZATION section
        right.addWidget(_section('VISUALIZATION'))

        # Same squeeze as the accent row on the left: at 16px spacing these three
        # switches ask for ~314px of a ~295px column, which ran 'Bck. Opt.' off
        # the popup's right edge.
        viz_sw_row = QHBoxLayout(); viz_sw_row.setSpacing(8)
        viz_sw_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._viz_sw = ToggleSwitch('VIZ', self, pad=4)
        self._log_sw = ToggleSwitch('LIN', 'LOG', self, muted_labels=True, pad=4)
        # Abbreviated so the third switch fits beside VIZ and LIN/LOG without
        # widening the popup. The tooltip carries the full name.
        self._bg_opt_sw = ToggleSwitch('Bck. Opt.', self, pad=4)
        self._bg_opt_sw.setToolTip(
            'Background optimizations.\n\n'
            'On (default): while the window is unfocused the visualizer and\n'
            'lyrics highlighting pause and position polling drops to 1 s, so an\n'
            'idle VoidPulse costs almost no CPU.\n\n'
            'Off: everything keeps running in the background — useful when the\n'
            'visualizer is captured by another app or shown on a second screen.'
        )
        self._viz_sw.setChecked(True); self._log_sw.setChecked(True)
        self._bg_opt_sw.setChecked(True)
        self._viz_sw.toggled.connect(self.viz_toggled)
        self._log_sw.toggled.connect(self.log_toggled)
        self._bg_opt_sw.toggled.connect(self.bg_opt_toggled)
        viz_sw_row.addWidget(self._viz_sw); viz_sw_row.addWidget(self._log_sw)
        viz_sw_row.addWidget(self._bg_opt_sw)
        right.addLayout(viz_sw_row)

        viz_type_row = QHBoxLayout(); viz_type_row.setSpacing(8)
        viz_type_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        viz_type_lbl = QLabel('Type'); viz_type_lbl.setObjectName('setting_lbl')
        viz_type_lbl.setFixedWidth(55)
        viz_type_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._viz_type_combo = TouchComboBox()
        self._viz_type_combo.addItem('Bars')
        self._viz_type_combo.addItem('Fill')
        self._viz_type_combo.addItem('Line')
        self._viz_type_combo.addItem('Line+Fill')
        self._viz_type_combo.setStyleSheet(self._viz_combo_ss())
        self._viz_type_combo.currentTextChanged.connect(
            lambda t: self.viz_type_changed.emit(
                'bars' if t == 'Bars' else
                'fill' if t == 'Fill' else
                'line+fill' if t == 'Line+Fill' else
                'line'))
        viz_type_row.addWidget(viz_type_lbl)
        viz_type_row.addWidget(self._viz_type_combo, 1)
        right.addLayout(viz_type_row)

        self._delay_row = SliderRow('Delay', 0, 3000, 0, lambda v: f'{v}ms')
        self._delay_row.valueChanged.connect(self.delay_changed)
        right.addWidget(self._delay_row)

        self._inertia_row = SliderRow('Inertia', 10, 100, 50, lambda v: f'{v}%')
        self._inertia_row.valueChanged.connect(self.inertia_changed)
        right.addWidget(self._inertia_row)

        self._bright_row = SliderRow('Brightness', 0, 100, 40, lambda v: f'{v}%')
        self._bright_row.valueChanged.connect(self.brightness_changed)
        right.addWidget(self._bright_row)

        # FETCH section
        right.addWidget(_hdivider())
        right.addWidget(_section('FETCH'))

        self._lyrics_fetch_sw = ToggleSwitch('AUTO LYRICS', self)
        self._lyrics_fetch_sw.setChecked(True)
        self._lyrics_fetch_sw.toggled.connect(self.lyrics_fetch_toggled)
        fetch_sw_row = QHBoxLayout(); fetch_sw_row.setSpacing(16)
        fetch_sw_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        fetch_sw_row.addWidget(self._lyrics_fetch_sw)
        right.addLayout(fetch_sw_row)

        action_row = QHBoxLayout(); action_row.setSpacing(4)
        self._btn_fetch_covers = QPushButton('Covers')
        self._btn_fetch_lyrics = QPushButton('Lyrics')
        self._btn_fetch_tags   = QPushButton('Tags')
        self._btn_fetch_gain   = QPushButton('Gain')
        self._btn_rename       = QPushButton('Rename')
        for b in (self._btn_fetch_covers, self._btn_fetch_lyrics,
                  self._btn_fetch_tags, self._btn_fetch_gain, self._btn_rename):
            b.setMinimumHeight(22); b.setMaximumHeight(26)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            # The global QPushButton rule sets min-height:36px, which beats
            # setMinimumHeight()/setMaximumHeight() unless a per-instance
            # stylesheet restates the size — so restate it. The radius is
            # computed from this button's own 26px height rather than
            # inheriting r_btn, which is calibrated for 36px buttons.
            b.setStyleSheet(
                f'font-size:10px; padding:1px 3px; min-height:22px; max-height:26px;'
                f' border-radius:{_r(13)}px;')
        self._btn_fetch_covers.clicked.connect(self.cover_fetch_toggled)
        self._btn_fetch_lyrics.clicked.connect(self.lyric_fetch_action)
        self._btn_fetch_tags.clicked.connect(self.tag_fetch_toggled)
        self._btn_fetch_gain.clicked.connect(self.gain_fetch_action)
        self._btn_rename.clicked.connect(self.rename_toggled)
        action_row.addWidget(self._btn_fetch_covers)
        action_row.addWidget(self._btn_fetch_lyrics)
        action_row.addWidget(self._btn_fetch_tags)
        action_row.addWidget(self._btn_fetch_gain)
        action_row.addWidget(self._btn_rename)
        right.addLayout(action_row)

        # ── PLAYBACK section ─────────────────────────────────────────────────
        right.addWidget(_hdivider())
        right.addWidget(_section('PLAYBACK'))

        self._crossfade_row = SliderRow('Crossfade', 0, 12000, 0, self._fmt_secs,
                                        step=250, snap=True)
        self._crossfade_row.setToolTip(
            'Overlap between tracks. 0 disables it.\n\n'
            'The outgoing track keeps playing while the next one fades in, so\n'
            'both streams are open at once — which the audio server has to mix.\n'
            'On an exclusive ALSA device (hw:/plughw:) only one stream can hold\n'
            'the card, so crossfading is skipped there and tracks change cleanly.')
        self._crossfade_row.valueChanged.connect(self.crossfade_changed)
        right.addWidget(self._crossfade_row)

        self._fade_row = SliderRow('Fade', 0, 5000, 0, self._fmt_ms_off,
                                   step=100, snap=True)
        self._fade_row.setToolTip(
            'Fade-in and fade-out length applied to every play and pause,\n'
            'including the sleep timer and media-key presses. 0 disables it.')
        self._fade_row.valueChanged.connect(self.fade_changed)
        right.addWidget(self._fade_row)

        self._sleep_row = SliderRow('Sleep Timer', 0, 360, 0, self._fmt_sleep,
                                    step=5, snap=True)
        self._sleep_row.setToolTip(
            'Stop playback after this long, in 5-minute steps up to 6 hours.\n'
            '0 disables the timer. Moving the slider restarts the countdown.')
        self._sleep_row.valueChanged.connect(self.sleep_timer_changed)
        right.addWidget(self._sleep_row)

        self._sleep_status = QLabel('')
        self._sleep_status.setObjectName('setting_lbl')
        self._sleep_status.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._sleep_status.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # Hidden while the timer is off so it costs no height in the common case
        self._sleep_status.setVisible(False)
        right.addWidget(self._sleep_status)

        # VOLUME (bottom of right column)
        vol_row = QHBoxLayout(); vol_row.setSpacing(6)
        vol_lbl = QLabel('Volume'); vol_lbl.setObjectName('setting_lbl')
        vol_lbl.setFixedWidth(55)
        vol_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._vol = JumpSlider(Qt.Orientation.Horizontal)
        self._vol.setRange(0, 100); self._vol.setValue(80); self._vol.setFixedHeight(22)
        self._vol.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._vol_lbl = QLabel('80%'); self._vol_lbl.setObjectName('setting_lbl')
        self._vol_lbl.setFixedWidth(36)
        self._vol_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._vol_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._vol.valueChanged.connect(lambda v: (
            self._vol_lbl.setText(f'{v}%'), self.volume_changed.emit(v)))
        vol_row.addWidget(vol_lbl); vol_row.addWidget(self._vol, 1); vol_row.addWidget(self._vol_lbl)
        right.addLayout(vol_row)

        # ── AUDIO OUTPUT (bottom of right column) ────────────────────────────
        right.addWidget(_hdivider())

        out_row = QHBoxLayout(); out_row.setSpacing(8)
        out_lbl = QLabel('Device'); out_lbl.setObjectName('setting_lbl')
        out_lbl.setFixedWidth(46)
        out_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._out_dev_combo = TouchComboBox()
        self._out_dev_combo.setStyleSheet(self._viz_combo_ss())
        # Signals blocked so addItem never fires the change handler
        self._out_dev_combo.blockSignals(True)
        # First entry is the software sink, whichever one was detected
        _sw_sink = Player._OUTS[0] if Player._OUTS else 'autoaudiosink'
        _sw_label = {'pulsesink': 'PulseAudio', 'pipewiresink': 'PipeWire'}.get(_sw_sink, _sw_sink)
        self._out_dev_combo.addItem(_sw_label, userData='pipewire')
        for _card_name, _card_id in probe_alsa_devices():
            self._out_dev_combo.addItem(_card_name, userData=_card_id)
        self._out_dev_combo.blockSignals(False)
        def _on_out_dev_changed(_):
            dev_id   = self._out_dev_combo.currentData()
            dev_name = self._out_dev_combo.currentText()
            print(f'[AudioSwitch] settings combo changed -> {dev_name!r} ({dev_id!r})')
            self.output_device_changed.emit(dev_id)
        self._out_dev_combo.currentIndexChanged.connect(_on_out_dev_changed)
        out_row.addWidget(out_lbl)
        out_row.addWidget(self._out_dev_combo, 1)
        right.addLayout(out_row)

        # Narrower than this clips the accent row's TriSwitch and the Type combo
        self.setFixedWidth(640)
        self.adjustSize()


    # ── PLAYBACK value formatting / accessors ───────────────────────────────

    @staticmethod
    def _fmt_secs(v: int) -> str:
        # %g drops the trailing zeros, so 250 ms reads "0.25s" and 6000 "6s"
        return 'Off' if v <= 0 else f'{v / 1000:g}s'

    @staticmethod
    def _fmt_ms_off(v: int) -> str:
        return 'Off' if v <= 0 else f'{v}ms'

    @staticmethod
    def _fmt_sleep(v: int) -> str:
        if v <= 0:
            return 'Off'
        h, m = divmod(v, 60)
        return f'{h}h{m:02d}' if h else f'{m}m'

    def crossfade_ms(self) -> int: return self._crossfade_row.value()
    def set_crossfade_ms(self, v: int): self._crossfade_row.setValue(max(0, min(12000, v)))
    def fade_ms(self) -> int: return self._fade_row.value()
    def set_fade_ms(self, v: int): self._fade_row.setValue(max(0, min(5000, v)))
    def sleep_minutes(self) -> int: return self._sleep_row.value()
    def set_sleep_minutes(self, v: int): self._sleep_row.setValue(max(0, min(360, v)))

    def reset_sleep_minutes(self):
        """Put the slider back to Off without re-arming the timer.

        The signal is blocked because MainWindow calls this from inside the
        timer's own expiry handler, where sleep_timer_changed(0) would only
        cancel a timer that has already fired and overwrite its status message.
        """
        self._sleep_row.blockSignals(True)
        self._sleep_row.setValue(0)
        self._sleep_row.blockSignals(False)
        self.set_sleep_status('')

    def set_sleep_status(self, text: str):
        """Show the live countdown (or '' when the timer is off)."""
        was = self._sleep_status.isVisible()
        self._sleep_status.setText(text)
        self._sleep_status.setVisible(bool(text))
        if bool(text) != was and self.isVisible():
            # The row appears/disappears under an already-open popup, so take
            # the height back rather than leaving a gap or a clipped bottom.
            # invalidate() first: a hidden child does not shrink the cached
            # layout hint on its own, so adjustSize() would keep the old height.
            self.layout().invalidate()
            self.layout().activate()
            self.adjustSize()

    def set_crossfade_available(self, ok: bool):
        """Grey the crossfade slider out on outputs that cannot overlap streams."""
        self._crossfade_row.setEnabled(ok)

    def output_device(self) -> str:
        """Return currently selected output device id: 'pipewire' or 'plughw:X,Y'."""
        return self._out_dev_combo.currentData() or 'pipewire'

    def set_output_device(self, device_id: str):
        """Set combobox to the given device_id without emitting the signal."""
        self._out_dev_combo.blockSignals(True)
        idx = self._out_dev_combo.findData(device_id)
        if idx >= 0:
            self._out_dev_combo.setCurrentIndex(idx)
        else:
            # The saved device is gone — fall back to the software sink
            self._out_dev_combo.setCurrentIndex(0)
        self._out_dev_combo.blockSignals(False)

    def adaptive_rate_enabled(self) -> bool:
        return self._adaptive_sw.isChecked()

    def set_adaptive_rate_enabled(self, on: bool):
        """Set the toggle without emitting the signal (config restore)."""
        self._adaptive_sw.blockSignals(True)
        self._adaptive_sw.setChecked(on)
        self._adaptive_sw.blockSignals(False)

    def _on_theme_toggle(self, light: bool):
        """Switch between dark (light=False) and light (light=True) themes."""
        apply_theme(dark=not light)
        win = self.window()
        if win and hasattr(win, '_refresh_all_theme_widgets'):
            overlay = _SpinningOverlay(win)
            overlay.show(); overlay.raise_()
            # Deferred so the overlay paints before the blocking refresh starts
            QTimer.singleShot(32, lambda: win._refresh_all_theme_widgets(_overlay=overlay))
        self.repaint()

    def _on_system_theme_toggle(self, use_system: bool):
        """Toggle 'derive palette from the system Qt theme' mode.

        When on, DARK/LIGHT is ignored in favour of colors sampled from the
        live system Qt palette (see constants.apply_system_qt_theme). The
        DARK/LIGHT switch is disabled while this is active since it has no
        effect, and re-enabled when system mode is turned back off.
        """
        apply_system_qt_theme(use_system)
        self._theme_sw.setEnabled(not use_system)
        self._accent_btn.setEnabled(not use_system)
        self._accent_btn.setToolTip(
            'Accent is following the system theme (SYS mode) — turn SYS off to pick manually.'
            if use_system else ''
        )
        win = self.window()
        if win and hasattr(win, '_refresh_all_theme_widgets'):
            overlay = _SpinningOverlay(win)
            overlay.show(); overlay.raise_()
            QTimer.singleShot(32, lambda: win._refresh_all_theme_widgets(_overlay=overlay))
        self.repaint()

    def _on_cover_tri_changed(self, state: int):
        """Handle 3-position cover switch.

        state 0 → cover off, accent off
        state 1 → cover on,  accent off
        state 2 → cover on,  accent on
        """
        cover_on = state >= 1
        acc_on   = state == 2
        win = self.window()
        if win and hasattr(win, '_on_cover_toggle_with_overlay'):
            # The overlay path updates the library and playlists itself, so the
            # ctrlbar label is set directly here; emitting cover_toggled would
            # cascade into MainWindow and update every playlist twice.
            ctrlbar = getattr(win, '_ctrlbar', None)
            if ctrlbar is not None:
                ctrlbar._on_cover_toggle(cover_on, _emit=False)
            overlay = _SpinningOverlay(win)
            overlay.show(); overlay.raise_()
            QTimer.singleShot(
                32, lambda: win._on_cover_toggle_with_overlay(cover_on, _overlay=overlay))
        else:
            # No overlay available, so let the normal signal path handle it
            self.cover_toggled.emit(cover_on)
        self.cover_accent_toggled.emit(acc_on)
        self.repaint()

    def _pick_accent(self):
        # Hidden first: with the popup still up, Qt closes the colour dialog at once
        saved_color = self._accent_color
        self.hide()
        dlg = QColorDialog(QColor(saved_color))
        dlg.setWindowTitle('Select Accent Color')
        dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            c = dlg.currentColor()
            if c.isValid():
                self._accent_color = c.name()
                self._accent_btn.setStyleSheet(
                    f'QPushButton#accent_swatch {{'
                    f'  background:{self._accent_color}; border-radius:{_r(16)}px; border:2px solid #666;'
                    f'  min-width:32px; max-width:32px; min-height:32px; max-height:32px;'
                    f'  padding:0;'
                    f'}}')
                self.accent_changed.emit(self._accent_color)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        cr = _r(11)   # respect global corner-radius percentage
        # Read live from the module so theme and accent changes show up
        p.setBrush(QBrush(QColor(_c.BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, cr, cr)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(_c.ACC), 3.0))
        p.drawRoundedRect(r, cr, cr)
        p.end()

    def volume(self)     -> int: return self._vol.value()
    def delay(self)      -> int: return self._delay_row.value()
    def inertia(self)    -> int: return self._inertia_row.value()
    def viz_on(self)     -> bool: return self._viz_sw.isChecked()
    def log_on(self)     -> bool: return self._log_sw.isChecked()
    def bg_opt_on(self)  -> bool: return self._bg_opt_sw.isChecked()

    def set_volume(self, v): self._vol.setValue(v)
    def set_delay(self, v):  self._delay_row.setValue(v)
    def set_inertia(self, v):self._inertia_row.setValue(v)
    def brightness(self) -> int: return self._bright_row.value()
    def set_brightness(self, v): self._bright_row.setValue(v)
    def cover_on(self) -> bool:        return self._cover_tri.state() >= 1
    def set_cover(self, v: bool):
        if not v:
            self._cover_tri.setState(0)
        elif self._cover_tri.state() == 0:
            self._cover_tri.setState(1)
    def cover_accent_on(self) -> bool: return self._cover_tri.state() == 2
    def set_cover_accent(self, v: bool):
        if v:
            self._cover_tri.setState(2)
        elif self._cover_tri.state() == 2:
            self._cover_tri.setState(1)
    def accent_color(self) -> str: return self._accent_color
    def set_accent_color(self, v: str):
        self._accent_color = v
        self._accent_btn.setStyleSheet(
            f'QPushButton#accent_swatch {{'
            f'  background:{v}; border-radius:{_r(16)}px; border:2px solid #666;'
            f'  min-width:32px; max-width:32px; min-height:32px; max-height:32px;'
            f'  padding:0;'
            f'}}')
    def radius(self) -> int: return self._radius_row.value()
    def set_radius(self, v: int): self._radius_row.setValue(max(0, min(100, v)))
    def set_viz(self, v):    self._viz_sw.setChecked(v)
    def set_log(self, v):    self._log_sw.setChecked(v)
    def set_bg_opt(self, v): self._bg_opt_sw.setChecked(v)
    def viz_type(self)   -> str:
        t = self._viz_type_combo.currentText()
        return ('bars' if t == 'Bars' else
                'fill' if t == 'Fill' else
                'line+fill' if t == 'Line+Fill' else
                'line')
    def set_viz_type(self, v: str):
        mapping = {'bars': 'Bars', 'fill': 'Fill', 'line': 'Line', 'line+fill': 'Line+Fill'}
        self._viz_type_combo.setCurrentText(mapping.get(v, 'Bars'))
    def dark_mode_on(self) -> bool: return not self._theme_sw.isChecked()
    def set_dark_mode(self, dark: bool):
        self._theme_sw.blockSignals(True)
        self._theme_sw.setChecked(not dark)  # True = light = checked
        self._theme_sw.blockSignals(False)
    def system_theme_on(self) -> bool: return self._system_theme_sw.isChecked()
    def set_system_theme(self, use_system: bool):
        self._system_theme_sw.blockSignals(True)
        self._system_theme_sw.setChecked(use_system)
        self._system_theme_sw.blockSignals(False)
        self._theme_sw.setEnabled(not use_system)
        self._accent_btn.setEnabled(not use_system)
        self._accent_btn.setToolTip(
            'Accent is following the system theme (SYS mode) — turn SYS off to pick manually.'
            if use_system else ''
        )
    def overlay_viz_on(self)    -> bool: return self._ov_viz_sw.isChecked()
    def overlay_lyrics_on(self) -> bool: return self._ov_lyrics_sw.isChecked()
    def overlay_clock_on(self)  -> bool: return self._ov_clock_sw.isChecked()
    def set_overlay_viz(self, v):    self._ov_viz_sw.setChecked(v)
    def set_overlay_lyrics(self, v): self._ov_lyrics_sw.setChecked(v)
    def set_overlay_clock(self, v):  self._ov_clock_sw.setChecked(v)
    def overlay_scale(self) -> int: return self._ov_scale_row.value()
    def set_overlay_scale(self, v): self._ov_scale_row.setValue(v)
    def overlay_auto_open(self) -> bool: return self._ov_auto_sw.isChecked()
    def set_overlay_auto_open(self, v: bool): self._ov_auto_sw.setChecked(v)
    def overlay_timeout(self) -> int: return self._ov_timeout_row.value()
    def set_overlay_timeout(self, v: int): self._ov_timeout_row.setValue(v)
    def lyrics_fetch_on(self) -> bool: return self._lyrics_fetch_sw.isChecked()
    def set_lyrics_fetch(self, v): self._lyrics_fetch_sw.setChecked(v)
    def cover_fetch_on(self) -> bool: return True   # UI toggle removed; always on
    def set_cover_fetch(self, v): pass              # config-compat no-op; value ignored

    _MODE_TO_COMBO = {'classic': 'Classic', 'gallery_z': 'Gallery (Z)', 'gallery_s': 'Gallery (S)'}
    _COMBO_TO_MODE = {'Classic': 'classic', 'Gallery (Z)': 'gallery_z', 'Gallery (S)': 'gallery_s'}

    def view_mode(self) -> str:
        return self._COMBO_TO_MODE.get(self._view_combo.currentText(), 'classic')

    def set_view_mode(self, v: str):
        text = self._MODE_TO_COMBO.get(v, 'Classic')
        idx = self._view_combo.findText(text)
        if idx >= 0:
            self._view_combo.blockSignals(True)
            self._view_combo.setCurrentIndex(idx)
            self._view_combo.blockSignals(False)
    def list_scale(self) -> int: return self._list_scale_row.value()
    def set_list_scale(self, v: int): self._list_scale_row.setValue(v)
    def gallery_scale(self) -> int: return self._gallery_scale_row.value()
    def set_gallery_scale(self, v: int): self._gallery_scale_row.setValue(v)

    @staticmethod
    def _viz_combo_ss() -> str:
        # Reads the live module globals so theme and accent changes show up at
        # once. The radius is restated to match the global QComboBox rule: a
        # per-instance stylesheet that sets padding but not border-radius does
        # not reliably inherit the global radius (see #eq_type_combo).
        return (f'QComboBox {{ background:{_c.BG3}; color:{_c.FG}; border:1px solid {_c.B2};'
                f' border-radius:{_r(15)}px; padding:4px 8px; font-size:12px; }}'
                f'QComboBox:hover {{ border-color:{_c.ACC}; }}'
                f'QComboBox::drop-down {{ border:none; width:20px; }}'
                f'QComboBox::down-arrow {{ color:{_c.FG2}; }}'
                f'QComboBox QAbstractItemView {{ background:{_c.BG3}; color:{_c.FG};'
                f' selection-background-color:{_c.SEL}; border:1px solid {_c.B2}; }}')

    def refresh_theme(self):
        """Re-apply inline stylesheets that bake palette globals at construction time."""
        self._viz_type_combo.setStyleSheet(self._viz_combo_ss())
        self._out_dev_combo.setStyleSheet(self._viz_combo_ss())
        for d in self._themed_dividers:
            shape = d.frameShape()
            if shape == QFrame.Shape.VLine:
                d.setStyleSheet(f'color:{_c.BORD};')
            else:
                d.setStyleSheet(f'background:{_c.BORD}; margin:0;')
        for lbl in self._section_lbls:
            lbl.setStyleSheet(
                f'color:{_c.FG2};font-size:9px;letter-spacing:2px;background:transparent;')
        self._accent_btn.setStyleSheet(
            f'QPushButton#accent_swatch {{'
            f'  background:{self._accent_color}; border-radius:{_r(16)}px; border:2px solid #666;'
            f'  min-width:32px; max-width:32px; min-height:32px; max-height:32px;'
            f'  padding:0;'
            f'}}')

    def eventFilter(self, obj, e: QEvent) -> bool:
        """Close settings popup on mouse press outside it."""
        if (self.isVisible() and
                e.type() == QEvent.Type.MouseButtonPress and
                QApplication.activePopupWidget() is None and
                obj is not self and
                not (isinstance(obj, QWidget) and self.isAncestorOf(obj))):
            # A combo box that just opened its dropdown must not close this popup.
            # On touch the dropdown can already be hidden by the time this arrives,
            # so the combo's open timestamp is what is checked.
            for combo in self.findChildren(QComboBox):
                if hasattr(combo, '_popup_opened_ms'):
                    if QDateTime.currentMSecsSinceEpoch() - combo._popup_opened_ms < 600:
                        return False
            try:
                gpt = e.globalPosition().toPoint()
                local = self.mapFromGlobal(gpt)
                if not self.rect().contains(local):
                    self.hide()
                    self._hide_timestamp_ms = QDateTime.currentMSecsSinceEpoch()
            except Exception:
                self.hide()
                self._hide_timestamp_ms = QDateTime.currentMSecsSinceEpoch()
        return False  # never swallow events

    def show_above(self, btn: QWidget):
        # Positioned inside the main window, which Wayland allows
        win = btn.window()
        if self.parent() is not win:
            self.setParent(win)
            self.setWindowFlags(Qt.WindowType.Widget)  # ensure child
        # Drop any height cap from a previous show before measuring
        self.setMaximumHeight(16777215)
        self.adjustSize()
        btn_in_win = btn.mapTo(win, QPoint(0, 0))
        x = btn_in_win.x() + btn.width()//2 - self.width()//2
        space_above = btn_in_win.y() - 8
        space_below = win.height() - (btn_in_win.y() + btn.height()) - 8
        prefer_above = space_above >= self.height()
        available = space_above if prefer_above else space_below
        if self.height() > available:
            # Cap the height so the popup stays inside the window
            self.setMaximumHeight(max(80, available))
            self.adjustSize()
        if prefer_above:
            y = btn_in_win.y() - self.height() - 6
        else:
            y = btn_in_win.y() + btn.height() + 6
        x = max(4, min(x, win.width()  - self.width()  - 4))
        y = max(4, min(y, win.height() - self.height() - 4))
        self.move(x, y)
        self.show()
        self.raise_()

# ══════════════════════════════════════════════════════════════════════════════
