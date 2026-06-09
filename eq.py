"""
VoidPulse — EQ / DSP: biquad coefficient functions (Peak/Shelf/Pass/Notch),
EQSliderCell, TouchComboBox, EqPopup (parametric EQ UI + preset manager),
_np_to_qpolygonf helper, _fmt_ms helper, EQGraph frequency-response widget.
"""
from constants import *
from widgets_base import JumpSlider, ToggleSwitch
from constants import ACC, ACCH, B2, BG, BG3, BG4, BORD, EQ_FREQ_MAX, EQ_FREQ_MIN, EQ_GAIN_MAX, EQ_GAIN_MAX_GRAPH, EQ_GAIN_MIN, EQ_Q_MAX, EQ_Q_MIN, EQ_TYPE_HIGHPASS, EQ_TYPE_HIGHSHELF, EQ_TYPE_LABELS, EQ_TYPE_LIST, EQ_TYPE_LOWPASS, EQ_TYPE_LOWSHELF, EQ_TYPE_NOTCH, EQ_TYPE_PEAK, FG, FG2, MAX_EQ_BANDS, _apply_scroller_properties, _r
import numpy as _np

class EQSliderCell(QWidget):
    valueChanged = pyqtSignal(int, str, float)  # band index, param, new value

    def __init__(self, param_type: str, min_val, max_val, val, band_idx, parent=None):
        super().__init__(parent)
        self._param = param_type  # 'freq', 'gain', 'q'
        self._band_idx = band_idx
        self._min = min_val
        self._max = max_val
        self._val = val

        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 8)
        self._slider = JumpSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setValue(self._to_slider(val))
        self._slider.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._slider.valueChanged.connect(self._on_slider)
        self._slider.setMinimumHeight(20)  # room for 16px handle without clipping
        self._apply_slider_qss()

        self._label = QLabel(self._format(val))
        self._label.setFixedWidth(60)
        self._label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._label.setStyleSheet(f'color:{FG2};')

        lay.addWidget(self._slider, 1)
        lay.addWidget(self._label)

    def _to_slider(self, val):
        if self._param == 'freq':
            # logarithmic mapping
            if val <= 0:
                return 0
            log_min = math.log10(EQ_FREQ_MIN)
            log_max = math.log10(EQ_FREQ_MAX)
            log_val = math.log10(val)
            pos = (log_val - log_min) / (log_max - log_min) * 1000
            return int(max(0, min(1000, pos)))
        else:
            # linear
            return int((val - self._min) / (self._max - self._min) * 1000)

    def _from_slider(self, pos):
        if self._param == 'freq':
            log_min = math.log10(EQ_FREQ_MIN)
            log_max = math.log10(EQ_FREQ_MAX)
            log_val = log_min + (pos / 1000.0) * (log_max - log_min)
            return 10.0 ** log_val
        else:
            return self._min + (pos / 1000.0) * (self._max - self._min)

    def _format(self, val):
        if self._param == 'freq':
            return f"{val:.0f} Hz"
        elif self._param == 'gain':
            return f"{val:+.1f} dB"
        else:
            return f"{val:.2f}"

    def _on_slider(self, pos):
        val = self._from_slider(pos)
        # clamp due to rounding
        val = max(self._min, min(self._max, val))
        self._val = val
        self._label.setText(self._format(val))
        self.valueChanged.emit(self._band_idx, self._param, val)

    def _apply_slider_qss(self):
        """Apply EQ-specific large-knob QSS to the inner slider."""
        r = _r(8)    # 16 px handle → max 8 px (circle)
        acc, acch, bord = ACC, ACCH, BORD
        bg4, bg3 = BG4, BG3
        r_grv = _r(2)
        enabled = self._slider.isEnabled()
        if enabled:
            self._slider.setStyleSheet(f"""
                QSlider {{ background: transparent; }}
                QSlider::groove:horizontal {{
                    background: {B2}; height: 4px; border-radius: {r_grv}px;
                }}
                QSlider::sub-page:horizontal {{
                    background: {acc}; border-radius: {r_grv}px 0 0 {r_grv}px;
                }}
                QSlider::handle:horizontal {{
                    background: {bg4}; border: 2px solid {acc};
                    width: 16px; height: 16px; border-radius: {r}px; margin: -6px 0;
                }}
                QSlider::handle:horizontal:hover {{
                    background: {bg4}; border: 3px solid {acch};
                    width: 16px; height: 16px; border-radius: {r}px; margin: -6px 0;
                }}
                QSlider::handle:horizontal:pressed {{
                    background: {bg4}; border: 3px solid {acch};
                    width: 16px; height: 16px; border-radius: {r}px; margin: -6px 0;
                }}
            """)
        else:
            self._slider.setStyleSheet(f"""
                QSlider {{ background: transparent; }}
                QSlider::groove:horizontal {{
                    background: {bord}; height: 4px; border-radius: {r_grv}px;
                }}
                QSlider::sub-page:horizontal {{
                    background: {bord}; border-radius: {r_grv}px 0 0 {r_grv}px;
                }}
                QSlider::handle:horizontal {{
                    background: {bg3}; border: 2px solid {bord};
                    width: 16px; height: 16px; border-radius: {r}px; margin: -6px 0;
                }}
            """)

    def setEnabled(self, enabled: bool):  # type: ignore[override]
        super().setEnabled(enabled)
        self._slider.setEnabled(enabled)
        self._apply_slider_qss()
        # Explicitly colour the label so it looks greyed-out even with
        # WA_TranslucentBackground (Qt doesn't propagate palette to transparent labels)
        self._label.setStyleSheet(f'color:{FG2 if enabled else BORD};')

# ══════════════════════════════════════════════════════════════════════════════

class TouchComboBox(QComboBox):
    """QComboBox that won't close its popup immediately after opening on touch."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup_opened_ms = 0

    def showPopup(self):
        self._popup_opened_ms = QDateTime.currentMSecsSinceEpoch()
        super().showPopup()

    def hidePopup(self):
        # Block immediate close within 400 ms of opening (touch double-fire)
        if QDateTime.currentMSecsSinceEpoch() - self._popup_opened_ms < 400:
            return
        super().hidePopup()

# ══════════════════════════════════════════════════════════════════════════════
#  EQ Popup – parametric equalizer with profiles
# ══════════════════════════════════════════════════════════════════════════════
class EqPopup(QFrame):
    eq_changed = pyqtSignal(list, bool)   # bands, enabled
    limiter_changed      = pyqtSignal(bool)
    stereo_changed       = pyqtSignal(bool)
    stereo_width_changed = pyqtSignal(int)
    preamp_changed       = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('eq_popup')
        # Tool window: does NOT auto-close when OSK or other windows take focus.
        # User dismisses via the EQ button toggle or the ✕ close button.
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(False)
        # Close when user clicks outside this window (anywhere in the app)
        QApplication.instance().installEventFilter(self)

        self._bands = []          # list of (freq, gain, Q)
        self._hide_timestamp_ms: int = 0
        self._enabled = True
        self._preamp_db: float = 0.0
        self._profiles = {}       # name -> list of bands
        self._current_profile = ""
        self._default_bands = []  # stored default (bands, enabled)
        self._default_enabled = True

        # Debounce timer for applying changes
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(300)  # 300 ms
        self._apply_timer.timeout.connect(self._apply)

        self._build_ui()
        self._update_graph()

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 8, 12, 10)
        main.setSpacing(4)

        hdr = QLabel('PARAMETRIC EQ'); hdr.setObjectName('popup_title')
        main.addWidget(hdr)

        # Profile management
        prof_layout = QHBoxLayout()

        self._NEW = '＋ New'   # sentinel — always first item
        self._profile_combo = TouchComboBox()
        self._profile_combo.setEditable(True)
        self._profile_combo.setMinimumWidth(110)
        self._profile_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._profile_combo.setCompleter(None)   # no autocomplete / no filter while typing
        if self._profile_combo.lineEdit():
            le = self._profile_combo.lineEdit()
            le.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
            le.setPlaceholderText('Profile name…')
        # Force item height via the popup list view
        combo_view = self._profile_combo.view()
        if combo_view:
            combo_view.setUniformItemSizes(True)
            combo_view.setSpacing(0)
        self._profile_combo.addItem(self._NEW)  # always first
        # ONLY load/react when user explicitly selects from dropdown
        self._profile_combo.activated.connect(self._on_profile_activated)
        prof_layout.addWidget(self._profile_combo)

        # Buttons sized to match the combo box height (min-height:30px from QComboBox style)
        _btn_ss = ('QPushButton { font-size:10px; padding:2px 7px;'
                   ' min-height:30px; max-height:30px; }')
        self._btn_save = QPushButton('Save')
        self._btn_save.setStyleSheet(_btn_ss)
        self._btn_save.clicked.connect(self._save_profile)
        self._btn_del = QPushButton('Delete')
        self._btn_del.setStyleSheet(_btn_ss)
        self._btn_del.clicked.connect(self._delete_profile)
        self._btn_default = QPushButton('Set Default')
        self._btn_default.setStyleSheet(_btn_ss)
        self._btn_default.clicked.connect(self._set_as_default)
        prof_layout.addWidget(self._btn_save)
        prof_layout.addWidget(self._btn_del)
        prof_layout.addWidget(self._btn_default)
        self._enable_sw = ToggleSwitch('EQ')
        self._enable_sw.setChecked(True)
        self._enable_sw.toggled.connect(self._on_enable_toggled)
        prof_layout.addWidget(self._enable_sw)

        # ── FX controls: Limiter + Stereo Enhance — inline, right of Set Default ─
        prof_layout.addSpacing(12)

        self._limiter_sw = ToggleSwitch('Limiter')
        self._limiter_sw.setChecked(False)
        self._limiter_sw.setToolTip('Hard brick-wall limiter at –0.9 dBFS\\n(prevents clipping on boosted EQ bands)')
        self._limiter_sw.toggled.connect(self._on_limiter_toggled)
        prof_layout.addWidget(self._limiter_sw)

        self._stereo_sw = ToggleSwitch('Stereo Enhance')
        self._stereo_sw.setChecked(False)
        self._stereo_sw.setToolTip('Widen the stereo field')
        self._stereo_sw.toggled.connect(self._on_stereo_toggled)
        prof_layout.addWidget(self._stereo_sw)

        stereo_lbl = QLabel('Width:')
        stereo_lbl.setObjectName('setting_lbl')
        prof_layout.addWidget(stereo_lbl)

        self._stereo_slider = QSlider(Qt.Orientation.Horizontal)
        self._stereo_slider.setRange(-100, 100)
        self._stereo_slider.setValue(0)
        self._stereo_slider.setFixedWidth(160)
        self._stereo_slider.setToolTip('Stereo width (-100 = mono, 0 = normal, +100 = wide)')
        self._stereo_slider.valueChanged.connect(self._on_stereo_width_changed)
        prof_layout.addWidget(self._stereo_slider)

        self._stereo_val_lbl = QLabel('0')
        self._stereo_val_lbl.setFixedWidth(30)
        prof_layout.addWidget(self._stereo_val_lbl)
        prof_layout.addStretch()
        main.addLayout(prof_layout)



        # Frequency response graph
        self._graph = EQGraph(self)
        self._graph.setFixedHeight(160)
        main.addWidget(self._graph)

        # Band table
        table_label = QLabel('Bands')
        table_label.setObjectName('setting_lbl')
        main.addWidget(table_label)

        self._band_table = QTableWidget(0, 4)
        self._band_table.setHorizontalHeaderLabels(['Type', 'Frequency', 'Gain', 'Q'])
        self._band_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._band_table.setColumnWidth(0, 110)
        self._band_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._band_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._band_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._band_table.verticalHeader().setVisible(False)
        self._band_table.verticalHeader().setDefaultSectionSize(44)
        self._band_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._band_table.setMinimumHeight(160)
        self._band_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        QScroller.grabGesture(self._band_table.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        _apply_scroller_properties(self._band_table.viewport(), touch=False)
        main.addWidget(self._band_table)

        # Add/Remove + JSON import/export buttons
        btn_row = QHBoxLayout()
        self._btn_add = QPushButton('+ Add Band')
        self._btn_add.clicked.connect(self._add_band)
        self._btn_remove = QPushButton('- Remove')
        self._btn_remove.clicked.connect(self._remove_selected_band)
        self._btn_import_json = QPushButton('⬇ Import JSON')
        self._btn_import_json.setToolTip(
            'Import EQ bands from a parametric EQ preset JSON file\n'
            '(PowerAmp / Wavelet / AutoEQ format)')
        self._btn_import_json.clicked.connect(self._import_json_profile)
        self._btn_export_json = QPushButton('⬆ Export JSON')
        self._btn_export_json.setToolTip(
            'Export current EQ bands as a parametric EQ preset JSON file\n'
            '(PowerAmp / Wavelet / AutoEQ compatible)')
        self._btn_export_json.clicked.connect(self._export_json_profile)
        # Preamp slider — next to the export JSON button
        self._preamp_lbl = QLabel('Preamp:')
        self._preamp_lbl.setObjectName('setting_lbl')
        self._preamp_slider = QSlider(Qt.Orientation.Horizontal)
        self._preamp_slider.setRange(-240, 240)   # tenths of dB → -24..+24 dB
        self._preamp_slider.setValue(0)
        self._preamp_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._preamp_slider.setToolTip('Pre-EQ gain (−24 to +24 dB). Raise to compensate for heavy cuts; lower to headroom before boosts.')
        self._preamp_slider.valueChanged.connect(self._on_preamp_changed)
        self._preamp_val_lbl = QLabel('0.0 dB')
        self._preamp_val_lbl.setFixedWidth(52)

        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_remove)
        btn_row.addSpacing(16)
        btn_row.addWidget(self._btn_import_json)
        btn_row.addWidget(self._btn_export_json)
        btn_row.addSpacing(20)
        btn_row.addWidget(self._preamp_lbl)
        btn_row.addWidget(self._preamp_slider)
        btn_row.addWidget(self._preamp_val_lbl)
        main.addLayout(btn_row)

        self.setFixedWidth(1056)
        self.setMinimumHeight(704)
        self.adjustSize()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cr = _r(11)   # respect global corner-radius percentage
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        # Fill background
        p.setBrush(QBrush(QColor(BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, cr, cr)
        # Accent border 3px
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(ACC), 3.0))
        p.drawRoundedRect(r, cr, cr)
        p.end()

    def _on_enable_toggled(self, on):
        self._enabled = on
        self._graph.set_enabled(on)
        self._apply_timer.stop()   # cancel any pending slider debounce
        self._apply()              # apply immediately — don't wait 300 ms

    def _add_band(self):
        if len(self._bands) >= MAX_EQ_BANDS:
            self._btn_add.setText(f'Max {MAX_EQ_BANDS} bands')
            self._btn_add.setEnabled(False)
            def _restore():
                self._btn_add.setText('+ Add Band')
                self._btn_add.setEnabled(True)
            QTimer.singleShot(2000, _restore)
            return
        # Default values: Peak, 1000 Hz, 0 dB, Q=1.0
        self._bands.append([1000.0, 0.0, 1.0, EQ_TYPE_PEAK])
        self._refresh_table()
        self._update_graph()
        self._apply_timer.start()

    def _remove_selected_band(self):
        row = self._band_table.currentRow()
        if row >= 0 and row < len(self._bands):
            del self._bands[row]
            self._refresh_table()
            self._update_graph()
            self._apply_timer.start()

    def _refresh_table(self):
        self._band_table.setRowCount(len(self._bands))
        for i, band in enumerate(self._bands):
            f    = float(band[0])
            g    = float(band[1])
            q    = float(band[2])
            ftype = int(band[3]) if len(band) >= 4 else EQ_TYPE_PEAK

            # Column 0 — filter type ComboBox
            type_combo = TouchComboBox()
            type_combo.setFixedHeight(32)
            for tid in EQ_TYPE_LIST:
                type_combo.addItem(EQ_TYPE_LABELS[tid], tid)
            # Select the current type
            ci = type_combo.findData(ftype)
            if ci < 0:
                ci = 0
            type_combo.blockSignals(True)
            type_combo.setCurrentIndex(ci)
            type_combo.blockSignals(False)
            # Keep gain cell enabled/disabled based on type
            type_combo.currentIndexChanged.connect(
                lambda _idx, row=i, combo=type_combo: self._on_type_changed(row, combo))
            self._band_table.setCellWidget(i, 0, type_combo)

            # Column 1 — Frequency
            freq_cell = EQSliderCell('freq', EQ_FREQ_MIN, EQ_FREQ_MAX, f, i)
            freq_cell.valueChanged.connect(self._on_slider_changed)
            self._band_table.setCellWidget(i, 1, freq_cell)

            # Column 2 — Gain (disabled for filter types that ignore gain)
            gain_cell = EQSliderCell('gain', EQ_GAIN_MIN, EQ_GAIN_MAX, g, i)
            gain_cell.valueChanged.connect(self._on_slider_changed)
            gain_cell.setEnabled(ftype in (EQ_TYPE_PEAK, EQ_TYPE_LOWSHELF, EQ_TYPE_HIGHSHELF))
            self._band_table.setCellWidget(i, 2, gain_cell)

            # Column 3 — Q
            q_cell = EQSliderCell('q', EQ_Q_MIN, EQ_Q_MAX, q, i)
            q_cell.valueChanged.connect(self._on_slider_changed)
            self._band_table.setCellWidget(i, 3, q_cell)

    def _on_type_changed(self, band_idx: int, combo: 'TouchComboBox'):
        """Called when the user changes the filter type ComboBox for a band."""
        if band_idx >= len(self._bands):
            return
        new_type = combo.currentData()
        if new_type is None:
            return
        new_type = int(new_type)
        band = list(self._bands[band_idx])
        while len(band) < 4:
            band.append(EQ_TYPE_PEAK)
        band[3] = new_type
        self._bands[band_idx] = band
        # Enable/disable the Gain cell depending on whether this type uses gain
        gain_cell = self._band_table.cellWidget(band_idx, 2)
        if gain_cell is not None:
            gain_cell.setEnabled(
                new_type in (EQ_TYPE_PEAK, EQ_TYPE_LOWSHELF, EQ_TYPE_HIGHSHELF))
        self._update_graph()
        self._apply_timer.start()

    def _on_slider_changed(self, band_idx, param, new_val):
        """Update the band in self._bands."""
        if band_idx >= len(self._bands):
            return
        band = list(self._bands[band_idx])
        while len(band) < 4:
            band.append(EQ_TYPE_PEAK)
        if param == 'freq':
            band[0] = new_val
        elif param == 'gain':
            band[1] = new_val
        elif param == 'q':
            band[2] = new_val
        self._bands[band_idx] = band
        # Update graph immediately
        self._update_graph()
        # Schedule apply after a short delay
        self._apply_timer.start()

    def _update_graph(self):
        self._graph.set_bands(self._bands)

    def _apply(self):
        """Emit eq_changed so the player updates.
        Also auto-syncs active bands into the current profile snapshot so
        band edits are persisted without requiring an explicit Save click.
        """
        # Mirror what _on_preamp_changed already does for preamp:
        # keep the profile snapshot in sync with live edits.
        if self._current_profile and self._current_profile in self._profiles:
            entry = self._profiles[self._current_profile]
            if isinstance(entry, dict):
                entry['bands'] = [list(b) for b in self._bands]
            else:
                self._profiles[self._current_profile] = {
                    'bands': [list(b) for b in self._bands],
                    'preamp': self._preamp_db,
                }
        self.eq_changed.emit(self._bands, self._enabled)

    def _on_profile_activated(self, index):
        """Called only when user explicitly picks an item from the dropdown."""
        name = self._profile_combo.itemText(index)
        if name == self._NEW:
            # Start fresh: clear bands, reset preamp, clear name field
            self._bands = []
            self._current_profile = ''
            self._profile_combo.lineEdit().clear()
            self.set_preamp_db(0.0)
            self.preamp_changed.emit(0.0)
            self._refresh_table()
            self._update_graph()
            self._apply_timer.start()
        elif name and name in self._profiles:
            entry = self._profiles[name]
            # Support both old format (plain list) and new format (dict with bands+preamp)
            if isinstance(entry, dict):
                raw_bands = entry.get('bands', [])
                preamp    = float(entry.get('preamp', 0.0))
            else:
                raw_bands = entry
                preamp    = 0.0
            self._bands = []
            for b in raw_bands:
                b = list(b)
                while len(b) < 4:
                    b.append(EQ_TYPE_PEAK)
                self._bands.append(b)
            self.set_preamp_db(preamp)
            self.preamp_changed.emit(preamp)
            self._refresh_table()
            self._update_graph()
            self._current_profile = name
            self._apply_timer.start()


    def _save_profile(self):
        name = self._profile_combo.currentText().strip()
        if not name or name == self._NEW:
            QMessageBox.warning(self, 'Error', 'Profile name cannot be empty.')
            return
        self._profiles[name] = {'bands': [list(b) for b in self._bands],
                                 'preamp': self._preamp_db}
        # Add after ＋New if new; keep ＋New always at index 0
        if self._profile_combo.findText(name) < 0:
            self._profile_combo.insertItem(1, name)   # insert at 1, after ＋New
        self._profile_combo.setCurrentText(name)
        self._current_profile = name

    def _delete_profile(self):
        name = self._profile_combo.currentText().strip()
        if name and name != self._NEW and name in self._profiles:
            del self._profiles[name]
            idx = self._profile_combo.findText(name)
            if idx >= 0:
                self._profile_combo.removeItem(idx)
            # Select ＋New, clear bands
            self._profile_combo.setCurrentIndex(0)
            self._profile_combo.lineEdit().clear()
            self._current_profile = ''
            self._bands = []
            self._refresh_table()
            self._update_graph()

    def _set_as_default(self):
        """Save current bands and enabled as default."""
        self._default_bands = [list(b) for b in self._bands]  # deep copy
        self._default_enabled = self._enabled
        self._default_profile_name = self._current_profile
        # Sync into profile snapshot too (same as _apply does for band edits)
        if self._current_profile and self._current_profile in self._profiles:
            entry = self._profiles[self._current_profile]
            if isinstance(entry, dict):
                entry['bands'] = [list(b) for b in self._bands]
            else:
                self._profiles[self._current_profile] = {
                    'bands': [list(b) for b in self._bands],
                    'preamp': self._preamp_db,
                }
        QToolTip.showText(self.mapToGlobal(QPoint(0,0)), 'Saved as default')

    # ── JSON import / export ────────────────────────────────────────────────

    # Map from the PowerAmp/Wavelet/AutoEQ JSON band-type integers to VoidPulse
    # EQ_TYPE_* constants.  The external format uses:
    #   0 = Low Shelf, 1 = High Shelf, 2 = Low Pass, 3 = Peak/Bell,
    #   4 = High Pass, 5 = High Shelf (variant), 6 = Notch
    # VoidPulse internal: 0=Peak, 1=LowShelf, 2=HighShelf, 3=LowPass,
    #                     4=HighPass, 5=Notch
    _JSON_TO_VOIDPULSE_TYPE = {
        0: EQ_TYPE_LOWSHELF,
        1: EQ_TYPE_HIGHSHELF,
        2: EQ_TYPE_LOWPASS,
        3: EQ_TYPE_PEAK,
        4: EQ_TYPE_HIGHPASS,
        5: EQ_TYPE_HIGHSHELF,   # alternate high-shelf code used by some exporters
        6: EQ_TYPE_NOTCH,
    }
    # Reverse map for export: VoidPulse → JSON type integer (canonical values)
    _VOIDPULSE_TO_JSON_TYPE = {
        EQ_TYPE_PEAK:      3,
        EQ_TYPE_LOWSHELF:  0,
        EQ_TYPE_HIGHSHELF: 1,
        EQ_TYPE_LOWPASS:   2,
        EQ_TYPE_HIGHPASS:  4,
        EQ_TYPE_NOTCH:     6,
    }

    def _import_json_profile(self):
        """Open a parametric EQ JSON preset file and load its bands.

        Supports the PowerAmp / Wavelet / AutoEQ export format:
          [{"name": "...", "preamp": 0.0, "bands": [
              {"type": 3, "frequency": 1000, "q": 1.0, "gain": -3.0, ...}, ...
          ]}]
        """
        self._file_dialog_active = True
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, 'Import EQ Preset JSON',
                str(Path.home()),
                'JSON Files (*.json);;All Files (*)')
        finally:
            self._file_dialog_active = False
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
        except Exception as e:
            QMessageBox.critical(self, 'Import Error',
                                 f'Could not read JSON file:\n{e}')
            return

        # Accept both a bare dict (single preset) and a list of presets
        if isinstance(raw, dict):
            presets = [raw]
        elif isinstance(raw, list) and raw:
            presets = raw
        else:
            QMessageBox.warning(self, 'Import Error',
                                'JSON file does not contain a valid EQ preset.')
            return

        # If multiple presets, let the user pick one
        preset = presets[0]
        if len(presets) > 1:
            names = [p.get('name', f'Preset {i+1}') for i, p in enumerate(presets)]
            chosen, ok = QInputDialog.getItem(
                self, 'Select Preset',
                'Multiple presets found — choose one to import:',
                names, 0, False)
            if not ok:
                return
            preset = presets[names.index(chosen)]

        bands_raw = preset.get('bands', [])
        if not bands_raw:
            QMessageBox.warning(self, 'Import Error',
                                'The selected preset contains no bands.')
            return

        new_bands = []
        skipped = 0
        for b in bands_raw:
            try:
                freq  = float(b['frequency'])
                gain  = float(b.get('gain', 0.0))
                q     = float(b.get('q', 1.0))
                jtype = int(b.get('type', 3))
                vtype = self._JSON_TO_VOIDPULSE_TYPE.get(jtype, EQ_TYPE_PEAK)
                # Clamp to VoidPulse's supported ranges
                freq = max(EQ_FREQ_MIN, min(EQ_FREQ_MAX, freq))
                gain = max(EQ_GAIN_MIN, min(EQ_GAIN_MAX, gain))
                q    = max(EQ_Q_MIN,    min(EQ_Q_MAX,    q))
                new_bands.append([freq, gain, q, vtype])
            except (KeyError, TypeError, ValueError):
                skipped += 1
                continue

        if not new_bands:
            QMessageBox.warning(self, 'Import Error',
                                'No valid bands could be parsed from the preset.')
            return

        # Enforce MAX_EQ_BANDS cap
        truncated = 0
        if len(new_bands) > MAX_EQ_BANDS:
            truncated = len(new_bands) - MAX_EQ_BANDS
            new_bands = new_bands[:MAX_EQ_BANDS]

        # Use preset name as the suggested profile name if the combo is empty
        preset_name = preset.get('name', '').strip()
        if preset_name:
            current_text = self._profile_combo.currentText().strip()
            if not current_text or current_text == self._NEW:
                le = self._profile_combo.lineEdit()
                if le:
                    le.setText(preset_name)

        self._bands = new_bands
        self._refresh_table()
        self._update_graph()
        self._apply_timer.start()

        # Build a user-facing summary tooltip
        msg_parts = [f'Imported {len(new_bands)} band(s)']
        if skipped:
            msg_parts.append(f'{skipped} skipped (invalid)')
        if truncated:
            msg_parts.append(f'{truncated} truncated (max {MAX_EQ_BANDS})')
        preamp = float(preset.get('preamp', 0.0))
        if preamp != 0.0:
            self.set_preamp_db(preamp)
            self.preamp_changed.emit(self._preamp_db)
            msg_parts.append(f'preamp {preamp:+.1f} dB applied')
        QToolTip.showText(
            self._btn_import_json.mapToGlobal(QPoint(0, -28)),
            ' · '.join(msg_parts))

    def _export_json_profile(self):
        """Save current EQ bands as a parametric EQ preset JSON file.

        Output is compatible with the PowerAmp / Wavelet / AutoEQ format.
        """
        if not self._bands:
            QMessageBox.information(self, 'Export', 'No bands to export.')
            return

        profile_name = (self._profile_combo.currentText().strip()
                        or 'VoidPulse EQ')
        if profile_name == self._NEW:
            profile_name = 'VoidPulse EQ'

        safe_name = ''.join(c if c.isalnum() or c in ' _-.' else '_'
                            for c in profile_name).strip()
        default_path = str(Path.home() / f'{safe_name}.json')

        self._file_dialog_active = True
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, 'Export EQ Preset JSON',
                default_path,
                'JSON Files (*.json);;All Files (*)')
        finally:
            self._file_dialog_active = False
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'

        bands_out = []
        n_bands = len(self._bands)
        for idx, band in enumerate(self._bands):
            freq  = float(band[0])
            gain  = float(band[1])
            q     = float(band[2])
            vtype = int(band[3]) if len(band) >= 4 else EQ_TYPE_PEAK
            jtype = self._VOIDPULSE_TO_JSON_TYPE.get(vtype, 3)
            # Derive the same per-band colour used in EQGraph (HSV, saturation=0.8, value=1.0)
            # and encode as ARGB integer (0xFF_RR_GG_BB) for PowerAmp/Wavelet compatibility.
            hue   = (idx * 360 / max(1, n_bands)) % 360
            color = QColor.fromHsvF(hue / 360.0, 0.8, 1.0)
            argb  = (0xFF << 24) | (color.red() << 16) | (color.green() << 8) | color.blue()
            # Python int is unsigned; JSON serialiser may emit negative for values > 0x7FFFFFFF.
            # Convert to signed 32-bit so PowerAmp parses it correctly.
            if argb > 0x7FFFFFFF:
                argb -= 0x100000000
            bands_out.append({
                'type':      jtype,
                'channels':  0,
                'frequency': round(freq, 6),
                'q':         round(q,    9),
                'gain':      round(gain, 9),
                'color':     argb,
            })

        preset = [{
            'name':       profile_name,
            'preamp':     round(self._preamp_db, 2),
            'parametric': True,
            'bands':      bands_out,
        }]

        try:
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(preset, fh, indent='\t', ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, 'Export Error',
                                 f'Could not write JSON file:\n{e}')
            return

        QToolTip.showText(
            self._btn_export_json.mapToGlobal(QPoint(0, -28)),
            f'Exported {len(bands_out)} band(s) → {Path(path).name}')

    # Public methods to set/get state
    def set_bands(self, bands, enabled, name=''):
        # Normalise to 4-element lists, defaulting missing type to EQ_TYPE_PEAK
        self._bands = []
        for b in bands:
            b = list(b)
            while len(b) < 4:
                b.append(EQ_TYPE_PEAK)
            self._bands.append(b)
        self._enabled = enabled
        self._enable_sw.setChecked(enabled)
        self._refresh_table()
        self._update_graph()
        if name:
            self._current_profile = name
            idx = self._profile_combo.findText(name)
            if idx >= 0:
                self._profile_combo.blockSignals(True)
                self._profile_combo.setCurrentIndex(idx)
                self._profile_combo.blockSignals(False)
            elif self._profile_combo.lineEdit():
                self._profile_combo.lineEdit().setText(name)
        self.eq_changed.emit(self._bands, self._enabled)

    def set_profiles(self, profiles):
        # Normalise: old format stores {name: [bands]}, new format {name: {bands,preamp}}
        normalised = {}
        for k, v in profiles.items():
            if isinstance(v, dict):
                normalised[k] = v
            else:
                normalised[k] = {'bands': list(v), 'preamp': 0.0}
        self._profiles = normalised
        self._profile_combo.clear()
        self._profile_combo.addItem(self._NEW)  # always first
        for name in sorted(normalised.keys()):
            self._profile_combo.addItem(name)
        if self._current_profile:
            idx = self._profile_combo.findText(self._current_profile)
            if idx >= 0:
                self._profile_combo.blockSignals(True)
                self._profile_combo.setCurrentIndex(idx)
                self._profile_combo.blockSignals(False)

    def get_profiles(self):
        return self._profiles

    def set_default(self, bands, enabled, name=''):
        self._default_bands = [list(b) for b in bands]
        self._default_enabled = enabled
        self._default_profile_name = name

    def get_default_name(self) -> str:
        return getattr(self, '_default_profile_name', '')

    def get_default(self):
        return self._default_bands, self._default_enabled

    def _on_limiter_toggled(self, on: bool):
        self.limiter_changed.emit(on)

    def _on_stereo_toggled(self, on: bool):
        self.stereo_changed.emit(on)

    def _on_stereo_width_changed(self, v: int):
        self._stereo_val_lbl.setText(f'+{v}' if v > 0 else str(v))
        self.stereo_width_changed.emit(v)

    # FX getters
    def limiter_enabled(self) -> bool:
        return self._limiter_sw.isChecked()

    def stereo_enabled(self) -> bool:
        return self._stereo_sw.isChecked()

    def stereo_width(self) -> int:
        return self._stereo_slider.value()

    # FX setters (used by config restore)
    def set_limiter_enabled(self, on: bool):
        self._limiter_sw.blockSignals(True)
        self._limiter_sw.setChecked(on)
        self._limiter_sw.blockSignals(False)

    def set_stereo_enabled(self, on: bool):
        self._stereo_sw.blockSignals(True)
        self._stereo_sw.setChecked(on)
        self._stereo_sw.blockSignals(False)

    def set_stereo_width(self, v: int):
        self._stereo_slider.blockSignals(True)
        self._stereo_slider.setValue(v)
        self._stereo_val_lbl.setText(f'+{v}' if v > 0 else str(v))
        self._stereo_slider.blockSignals(False)

    # ── Preamp ──────────────────────────────────────────────────────────────────
    def _on_preamp_changed(self, tenths: int):
        db = tenths / 10.0
        self._preamp_db = db
        sign = '+' if db > 0 else ''
        self._preamp_val_lbl.setText(f'{sign}{db:.1f} dB')
        self.preamp_changed.emit(db)
        # Auto-save preamp into the active profile immediately (no Save button needed)
        if self._current_profile and self._current_profile in self._profiles:
            entry = self._profiles[self._current_profile]
            if isinstance(entry, dict):
                entry['preamp'] = db
            else:
                self._profiles[self._current_profile] = {
                    'bands': list(entry), 'preamp': db}

    def preamp_db(self) -> float:
        return self._preamp_db

    def set_preamp_db(self, db: float):
        db = max(-24.0, min(24.0, float(db)))
        self._preamp_db = db
        self._preamp_slider.blockSignals(True)
        self._preamp_slider.setValue(round(db * 10))
        sign = '+' if db > 0 else ''
        self._preamp_val_lbl.setText(f'{sign}{db:.1f} dB')
        self._preamp_slider.blockSignals(False)

    def show_above(self, btn: QWidget):
        gpos = btn.mapToGlobal(QPoint(0, 0))
        self.adjustSize()
        x = gpos.x() + btn.width()//2 - self.width()//2
        y = gpos.y() - self.height() - 6
        screen = QApplication.primaryScreen().availableGeometry()
        x = max(screen.left()+4, min(x, screen.right()-self.width()-4))
        y = max(screen.top()+4, y)
        self.move(x, y)
        self.show(); self.raise_()

    def eventFilter(self, obj, e: QEvent) -> bool:
        """Close EQ popup on click outside it (within the application).
        Suppressed while a native file dialog is open so Import/Export JSON
        can open the system file manager without instantly closing the popup."""
        if getattr(self, '_file_dialog_active', False):
            return False
        if (self.isVisible() and
                e.type() == QEvent.Type.MouseButtonPress and
                QApplication.activePopupWidget() is None and
                obj is not self and
                not (isinstance(obj, QWidget) and self.isAncestorOf(obj)) and
                not self.rect().contains(
                    self.mapFromGlobal(e.globalPosition().toPoint()))):
            self.hide()
            self._hide_timestamp_ms = QDateTime.currentMSecsSinceEpoch()
        return False

    def show_center(self):
        """Show popup in the center of the screen."""
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.center().x() - self.width() // 2
        y = screen.center().y() - self.height() // 2
        x = max(screen.left() + 4, min(x, screen.right() - self.width() - 4))
        y = max(screen.top() + 4, min(y, screen.bottom() - self.height() - 4))
        self.move(x, y)
        self.show()
        self.raise_()


def _np_to_qpolygonf(xs, ys) -> QPolygonF:
    """Convert two equal-length numpy arrays to a QPolygonF efficiently.
    Interleaves x/y into a contiguous float64 buffer then builds QPointF list
    without redundant Python-level float() boxing."""
    pts = _np.empty(len(xs) * 2, dtype=_np.float64)
    pts[0::2] = xs
    pts[1::2] = ys
    return QPolygonF([QPointF(pts[i], pts[i + 1]) for i in range(0, len(pts), 2)])


def _fmt_ms(ms: int) -> str:
    t = ms // 1000; h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


class EQGraph(QWidget):
    """Widget to draw frequency response of the current EQ bands."""

    # Frequency grid: label text → Hz value (shown as vertical lines)
    _FREQ_GRID = [
        ('20',   20),   ('50',   50),   ('100', 100),
        ('200',  200),  ('500',  500),  ('1k',  1000),
        ('2k',   2000), ('5k',   5000), ('10k', 10000),
        ('20k',  20000),
    ]
    _LOG_MIN = math.log10(20.0)
    _LOG_MAX = math.log10(22000.0)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bands = []
        self._enabled = True
        self._eq_graph_cache = None   # invalidated by set_bands(); checked in paintEvent
        self._hover_x: int = -1       # -1 = no hover
        self.setMinimumHeight(100)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)

    # ── x pixel ↔ frequency conversion ───────────────────────────────────────
    def _x_to_freq(self, x: float, w: int) -> float:
        if w <= 0:
            return 20.0
        log_f = self._LOG_MIN + (x / w) * (self._LOG_MAX - self._LOG_MIN)
        return 10.0 ** log_f

    def _freq_to_x(self, freq: float, w: int) -> float:
        if freq <= 0:
            return 0.0
        return w * (math.log10(freq) - self._LOG_MIN) / (self._LOG_MAX - self._LOG_MIN)

    def set_bands(self, bands):
        self._bands = bands
        self._eq_graph_cache = None  # invalidate numpy cache
        self.update()

    def set_enabled(self, en):
        self._enabled = en
        self.update()

    # ── Mouse / touch tracking ────────────────────────────────────────────────
    def mouseMoveEvent(self, e: QMouseEvent):
        new_x = int(e.position().x())
        if new_x != self._hover_x:
            self._hover_x = new_x
            self.update()

    def leaveEvent(self, _):
        if self._hover_x != -1:
            self._hover_x = -1
            self.update()

    def event(self, e: QEvent) -> bool:
        t = e.type()
        if t in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate):
            pts = e.points()
            if pts:
                new_x = int(pts[0].position().x())
                if new_x != self._hover_x:
                    self._hover_x = new_x
                    self.update()
            e.accept()
            return True
        if t == QEvent.Type.TouchEnd:
            self._hover_x = -1
            self.update()
            e.accept()
            return True
        return super().event(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if w < 10 or h < 10:
            return

        # ── Compute curves first so we can auto-scale the amplitude axis ──────
        cache_key = (w, tuple(tuple(b) for b in self._bands))
        cached = self._eq_graph_cache
        if self._bands and (cached is None or cached[0] != cache_key):
            steps = w
            fs    = 44100.0   # reference sample rate for display
            xs_np = _np.arange(steps, dtype=_np.float32)
            # Logarithmically spaced frequencies 20 Hz → 22 kHz
            freqs_np = (20.0 * (22000.0 / 20.0) ** (xs_np / (steps - 1))).astype(_np.float64)
            n_bands = len(self._bands)
            band_gains_np = _np.zeros((n_bands, steps), dtype=_np.float32)

            for idx, band in enumerate(self._bands):
                f0    = float(band[0])
                g     = float(band[1])
                q     = float(band[2])
                ftype = int(band[3]) if len(band) >= 4 else EQ_TYPE_PEAK
                if f0 <= 0.0:
                    continue

                # Gain-only filters: skip if gain is 0 (no effect)
                is_gain_type = ftype in (EQ_TYPE_PEAK, EQ_TYPE_LOWSHELF, EQ_TYPE_HIGHSHELF)
                if is_gain_type and g == 0.0:
                    continue

                coeffs = eq_band_coefficients(fs, f0, g, max(q, 0.01), ftype)
                if coeffs is None:
                    continue
                b0, b1, b2, a1, a2 = coeffs

                # Evaluate H(e^jw) at each display frequency using the bilinear
                # substitution: z = e^(j*w) where w = 2*pi*f/fs
                w_rad = (2.0 * math.pi / fs) * freqs_np          # shape (steps,)
                z_inv = _np.exp(-1j * w_rad)                      # z^-1
                z_inv2 = z_inv * z_inv                            # z^-2
                H_num = b0 + b1 * z_inv + b2 * z_inv2
                H_den = 1.0 + a1 * z_inv + a2 * z_inv2
                # Avoid divide-by-zero near stability boundaries
                mag = _np.abs(H_num / (_np.where(_np.abs(H_den) < 1e-12, 1e-12, H_den)))
                # Convert magnitude to dB
                mag_db = 20.0 * _np.log10(_np.maximum(mag, 1e-12))
                band_gains_np[idx] = mag_db.astype(_np.float32)

            total_gains_np = band_gains_np.sum(axis=0)
            self._eq_graph_cache = (cache_key, xs_np, band_gains_np, total_gains_np)
        elif cached is not None and cached[0] == cache_key:
            _, xs_np, band_gains_np, total_gains_np = cached
        else:
            xs_np = band_gains_np = total_gains_np = None

        # ── Auto-scale: find peak absolute gain, snap to next even-dB ceiling ─
        # LP/HP/Notch filters produce large negative dB values in the stop-band;
        # clamp those to ±60 dB so they don't blow out the vertical scale.
        # Minimum range ±3 dB so the graph never looks absurd on tiny boosts.
        if total_gains_np is not None:
            finite_vals = total_gains_np[_np.isfinite(total_gains_np)]
            if len(finite_vals):
                clamped = _np.clip(finite_vals, -60.0, 60.0)
                peak = float(max(abs(clamped.max()), abs(clamped.min())))
            else:
                peak = 0.0
        else:
            peak = 0.0
        peak = max(peak, 3.0)                          # floor at ±3 dB
        # Round up to the nearest even number of dB (gives clean 2-dB grid steps)
        db_range = math.ceil(peak / 2) * 2
        db_range = min(db_range, int(EQ_GAIN_MAX_GRAPH))  # hard cap at ±10 dB

        # ── Grid step: choose 1 or 2 dB depending on available height ─────────
        # Aim for roughly 20–30 px per grid line; fall back to 2-dB steps.
        db_step = 1 if (h / (db_range * 2)) >= 18 else 2

        # ── Background ────────────────────────────────────────────────────────
        p.fillRect(self.rect(), QColor(BG))

        lbl_font = QFont()
        lbl_font.setPixelSize(9)
        p.setFont(lbl_font)
        fm = QFontMetrics(lbl_font)
        lbl_h = fm.height()

        half_h = h / 2.0
        scale  = half_h / db_range          # pixels per dB

        # ── Horizontal dB grid lines + labels ─────────────────────────────────
        db_values = list(range(-db_range, db_range + 1, db_step))
        for db in db_values:
            y = half_h - db * scale
            if not (0 <= y <= h):
                continue
            is_zero = (db == 0)
            line_color = QColor(FG2) if is_zero else QColor(BORD)
            p.setPen(QPen(line_color, 1))
            p.drawLine(0, int(y), w, int(y))
            # Label — skip 0 dB (centre line, obvious), skip labels too close to edges
            if db != 0 and lbl_h / 2 < y < h - lbl_h / 2:
                lbl = f'{db:+d}'
                lbl_w = fm.horizontalAdvance(lbl)
                txt_x = 3
                txt_y = int(y - lbl_h / 2)
                pad = 2
                bg_rect = QRect(txt_x - pad, txt_y, lbl_w + pad * 2, lbl_h)
                p.fillRect(bg_rect, QColor(BG))
                p.setPen(QColor(FG2))
                p.drawText(txt_x, txt_y + fm.ascent(), lbl)

        # ── Vertical frequency grid lines + labels ─────────────────────────────
        freq_lbl_font = QFont()
        freq_lbl_font.setPixelSize(9)
        p.setFont(freq_lbl_font)
        fm_f = QFontMetrics(freq_lbl_font)

        for lbl_txt, freq in self._FREQ_GRID:
            x = self._freq_to_x(freq, w)
            if not (0 <= x <= w):
                continue
            xi = int(x)
            p.setPen(QPen(QColor(BORD), 1))
            p.drawLine(xi, 0, xi, h)
            # Label at bottom, background pill so it stays readable over curves
            lbl_w = fm_f.horizontalAdvance(lbl_txt)
            txt_x = xi - lbl_w // 2
            txt_x = max(1, min(w - lbl_w - 1, txt_x))   # clamp to widget edges
            txt_y = h - lbl_h - 2
            pad = 2
            bg_rect = QRect(txt_x - pad, txt_y, lbl_w + pad * 2, lbl_h)
            p.fillRect(bg_rect, QColor(BG))
            p.setPen(QColor(FG2))
            p.drawText(txt_x, txt_y + fm_f.ascent(), lbl_txt)

        if not self._enabled:
            p.setPen(QColor(FG2))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'EQ disabled')
            return

        if total_gains_np is None:
            return

        # ── Per-band dashed curves ─────────────────────────────────────────────
        n_bands = len(self._bands)
        for idx in range(n_bands):
            gains = band_gains_np[idx]
            # Skip bands that have no effect (all-zero in dB = no contribution)
            if _np.all(gains == 0.0):
                continue
            hue   = (idx * 360 / max(1, n_bands)) % 360
            color = QColor.fromHsvF(hue / 360.0, 0.8, 1.0, 0.4)
            pen   = QPen(color, 1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            ys_clipped = _np.clip(band_gains_np[idx], -db_range, db_range)
            p.drawPolyline(_np_to_qpolygonf(xs_np, half_h - ys_clipped * scale))

        # ── Total curve ────────────────────────────────────────────────────────
        total_clipped = _np.clip(total_gains_np, -db_range, db_range)
        p.setPen(QPen(QColor(FG), 2))
        p.drawPolyline(_np_to_qpolygonf(xs_np, half_h - total_clipped * scale))

        # ── Hover crosshair + tooltip ─────────────────────────────────────────
        hx = self._hover_x
        if 0 <= hx < w and total_gains_np is not None:
            # Sample the total gain at the cursor pixel column
            sample_idx = max(0, min(len(total_gains_np) - 1, hx))
            gain_db = float(total_gains_np[sample_idx])
            freq_hz = self._x_to_freq(hx, w)
            gain_clamped = max(-db_range, min(db_range, gain_db))
            dot_y = half_h - gain_clamped * scale

            # Vertical crosshair line
            pen_cross = QPen(QColor(FG2), 1)
            pen_cross.setStyle(Qt.PenStyle.DotLine)
            p.setPen(pen_cross)
            p.drawLine(hx, 0, hx, h)

            # Dot on the curve
            p.setPen(QPen(QColor(FG), 1))
            p.setBrush(QBrush(QColor(ACC)))
            p.drawEllipse(QPointF(hx, dot_y), 4, 4)
            p.setBrush(Qt.BrushStyle.NoBrush)

            # Tooltip text: format frequency
            if freq_hz >= 1000:
                freq_str = f'{freq_hz / 1000:.1f}kHz'
            else:
                freq_str = f'{freq_hz:.0f}Hz'
            if abs(gain_db) < 60.0:
                tip_txt = f'{freq_str}  {gain_db:+.1f}dB'
            else:
                tip_txt = freq_str

            tip_font = QFont()
            tip_font.setPixelSize(10)
            tip_font.setBold(True)
            p.setFont(tip_font)
            fm_tip = QFontMetrics(tip_font)
            tip_w = fm_tip.horizontalAdvance(tip_txt) + 10
            tip_h = fm_tip.height() + 6

            # Position: follow cursor, flip sides at edges, stay above the dot
            tip_x = hx + 8
            tip_y = int(dot_y) - tip_h - 6
            if tip_x + tip_w > w:
                tip_x = hx - tip_w - 8
            tip_y = max(2, min(h - tip_h - 2, tip_y))

            # Background pill
            tip_rect = QRectF(tip_x, tip_y, tip_w, tip_h)
            tip_bg = QColor(BG3)
            tip_bg.setAlpha(220)
            p.setPen(QPen(QColor(BORD), 1))
            p.setBrush(QBrush(tip_bg))
            p.drawRoundedRect(tip_rect, 4, 4)

            # Text
            p.setPen(QColor(FG))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawText(tip_rect.adjusted(5, 3, -5, -3),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       tip_txt)


def peaking_coefficients(fs, f0, gain_db, Q):
    """Biquad coefficients for a peaking (bell) filter."""
    A     = 10.0 ** (gain_db / 40.0)
    w0    = 2.0 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2.0 * Q)
    cos_w = math.cos(w0)
    b0 =  1.0 + alpha * A
    b1 = -2.0 * cos_w
    b2 =  1.0 - alpha * A
    a0 =  1.0 + alpha / A
    a1 =  b1
    a2 =  1.0 - alpha / A
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def lowshelf_coefficients(fs, f0, gain_db, Q):
    """Biquad coefficients for a low-shelf filter."""
    A     = 10.0 ** (gain_db / 40.0)
    w0    = 2.0 * math.pi * f0 / fs
    cos_w = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * Q)
    sq    = 2.0 * math.sqrt(A) * alpha
    b0 =  A * ((A + 1.0) - (A - 1.0) * cos_w + sq)
    b1 =  2.0 * A * ((A - 1.0) - (A + 1.0) * cos_w)
    b2 =  A * ((A + 1.0) - (A - 1.0) * cos_w - sq)
    a0 =       (A + 1.0) + (A - 1.0) * cos_w + sq
    a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cos_w)
    a2 =        (A + 1.0) + (A - 1.0) * cos_w - sq
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def highshelf_coefficients(fs, f0, gain_db, Q):
    """Biquad coefficients for a high-shelf filter."""
    A     = 10.0 ** (gain_db / 40.0)
    w0    = 2.0 * math.pi * f0 / fs
    cos_w = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * Q)
    sq    = 2.0 * math.sqrt(A) * alpha
    b0 =  A * ((A + 1.0) + (A - 1.0) * cos_w + sq)
    b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cos_w)
    b2 =  A * ((A + 1.0) + (A - 1.0) * cos_w - sq)
    a0 =       (A + 1.0) - (A - 1.0) * cos_w + sq
    a1 =  2.0 * ((A - 1.0) - (A + 1.0) * cos_w)
    a2 =        (A + 1.0) - (A - 1.0) * cos_w - sq
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def lowpass_coefficients(fs, f0, Q):
    """Biquad coefficients for a 2nd-order Butterworth low-pass filter."""
    w0    = 2.0 * math.pi * f0 / fs
    cos_w = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * Q)
    b0 = (1.0 - cos_w) / 2.0
    b1 =  1.0 - cos_w
    b2 = (1.0 - cos_w) / 2.0
    a0 =  1.0 + alpha
    a1 = -2.0 * cos_w
    a2 =  1.0 - alpha
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def highpass_coefficients(fs, f0, Q):
    """Biquad coefficients for a 2nd-order Butterworth high-pass filter."""
    w0    = 2.0 * math.pi * f0 / fs
    cos_w = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * Q)
    b0 =  (1.0 + cos_w) / 2.0
    b1 = -(1.0 + cos_w)
    b2 =  (1.0 + cos_w) / 2.0
    a0 =   1.0 + alpha
    a1 =  -2.0 * cos_w
    a2 =   1.0 - alpha
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def notch_coefficients(fs, f0, Q):
    """Biquad coefficients for a notch (band-stop) filter."""
    w0    = 2.0 * math.pi * f0 / fs
    cos_w = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * Q)
    b0 =  1.0
    b1 = -2.0 * cos_w
    b2 =  1.0
    a0 =  1.0 + alpha
    a1 =  b1
    a2 =  1.0 - alpha
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def eq_band_coefficients(fs, f0, gain_db, Q, filter_type: int):
    """Dispatch to the correct biquad function for *filter_type*.

    Returns (b0, b1, b2, a1, a2) normalised to a0=1, or None on error.
    Low-pass, high-pass and notch filters ignore *gain_db*.
    """
    try:
        if filter_type == EQ_TYPE_PEAK:
            return peaking_coefficients(fs, f0, gain_db, Q)
        elif filter_type == EQ_TYPE_LOWSHELF:
            return lowshelf_coefficients(fs, f0, gain_db, Q)
        elif filter_type == EQ_TYPE_HIGHSHELF:
            return highshelf_coefficients(fs, f0, gain_db, Q)
        elif filter_type == EQ_TYPE_LOWPASS:
            return lowpass_coefficients(fs, f0, Q)
        elif filter_type == EQ_TYPE_HIGHPASS:
            return highpass_coefficients(fs, f0, Q)
        elif filter_type == EQ_TYPE_NOTCH:
            return notch_coefficients(fs, f0, Q)
        else:
            # Unknown type — fall back to peak
            return peaking_coefficients(fs, f0, gain_db, Q)
    except Exception:
        return None

# ══════════════════════════════════════════════════════════════════════════════

