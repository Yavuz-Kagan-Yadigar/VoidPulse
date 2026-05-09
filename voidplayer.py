#!/usr/bin/env python3
"""
VoidPulse  —  Dark music player
Wayland · GNOME/KDE Integration · PipeWire · GStreamer spectrum viz
MPRIS2 D-Bus  ·  Bit-perfect audio  ·  OLED blackout overlay

═══════════════════════════════════════════════════════════════════
 MODULE STRUCTURE  (actual line numbers — auto-verified)
═══════════════════════════════════════════════════════════════════
 PALETTE & THEME
   apply_theme()               L206   Switch dark/light palette globals + rebuild SS
   _apply_app_palette()        L220   Sync QPalette with current globals
   make_acch()                 L240   Derive highlight colour from accent
   make_stylesheet()           L269   Build global QSS string

 CONSTANTS & GLOBALS
   SUPPORTED_EXT, CONFIG_PATH, VIZ_BANDS, GST_BANDS, EQ_*, RAD …

 WIDGETS
   ToggleSwitch                L417   Animated two-state toggle (single/two-label)
   JumpSlider                  L560   QSlider that jumps to click/touch position
   SliderRow                   L598   Label + JumpSlider + value label row
   SettingsPopup               L630   Settings panel popup (child widget, Wayland-safe)
   TagEditDialog               L1014  Modal tag editor with cover management
     _pick_cover_file()        L1114  Open file dialog → set cover bytes
     _search_cover_online()    L1130  Background cover search → update preview
     _fetch_tags_online()      L1175  Background tag lookup → fill empty fields
     _fetch_lyrics_online()    L1211  Force-fetch lyrics (all APIs, synced priority) → embed
   EQSliderCell                L1227  Table cell widget for a single EQ parameter
   TouchComboBox               L2168  QComboBox immune to touch double-fire close
   EqPopup                     L2187  Parametric EQ popup + preset management
   EQGraph                     L2542  Frequency response curve widget
   BlackoutOverlay             L2651  Full-screen OLED burn-in protection overlay
   SeekSlider                  L5738  Touch-aware seek slider
   LongPressFilter             L5850  Event filter: long-press → context menu
   RepeatButton                L7044  Tri-state repeat cycle button
   _FullscreenBtn              L7088  Painted 4-arrow fullscreen toggle button
   SpinningPlayButton          L7136  Play/pause button with spinning reload indicator
   TitleBarButton              L8291  Frameless window-control button
   TitleBarCloseButton         L8316  Close variant (red hover)
   BlackTitleBar               L8320  Custom frameless titlebar
   _SpinningOverlay            L9638  Semi-transparent blocking overlay with spinner

 LYRICS
   _lrc_parse()                L1592  Parse LRC timestamp lines → [(ms, text)]
   _extract_embedded_lyrics()  L1603  Read USLT/Vorbis/M4A lyrics from file
   _get() / _get_json()        L1644  HTTP helpers for online sources
   _src_lrclib_exact/search()  L1668  LrcLib API sources
   _src_lyrics_ovh()           L1696  Lyrics.ovh fallback source
   ClickableLyricLine          L1818  QLabel that emits clicked(ms)
   LyricsFetcher               L1926  Worker: embedded → 9 APIs parallel, early-exit on first synced
   LyricsPanel                 L2026  Scrollable lyric display with sync highlight (touch scroll enabled)

 COVER ART
   _trim_cover_cache()         L3078  Evict oldest entries when cache exceeds limit
   _rounded_pixmap()           L3116  Scale + crop + round-corner mask
   draw_default_cover()        L3140  Render clef placeholder pixmap
   _cover_disk_key()           L3186  SHA1 hash for disk cache filename
   get_cover_pixmap()          L3194  Non-blocking async cover lookup (paint path)
   get_cover_pixmap_sync()     L3212  Blocking cover lookup (worker threads)
   _CoverTask                  L3247  QRunnable for one cover load
   AsyncCoverLoader            L3288  QThreadPool-based async cover loader
   _ensure_async_cover_loader() L3380 Module singleton factory
   _clear_cover_disk_cache()   L3386  Wipe disk + memory cover caches
   _BaseFetchPopup             L3515  Shared base class for fetch popups (supports multiple concurrent workers)
     closeEvent()              L3702  Hide dialog, keep worker running in background
     mousePressEvent()         L3707  Click outside → hide (run in background)
     _emit_status_update()     L3757  Show each fetch instance progress as permanent widget on status bar left
   LibraryCoverFetchWorker     L3801  Sequential per-track cover fetcher
   CoverFetchPopup             L3842  Modal "fetch covers for library" dialog (multiple concurrent supported)

 TAGS / METADATA
   fetch_cover_online()        L1371  Try iTunes/Deezer/MusicBrainz/LastFM
   lookup_tags_online()        L1446  Parallel MusicBrainz/iTunes/LastFM tag lookup
   write_tags_to_file()        L1474  Write title/artist/album via mutagen
   embed_cover_bytes()         L1503  Write cover into audio tags
   embed_lyrics()              L1544  Write lyrics into audio tags
   _open_audio()               L3016  Open audio file with mutagen (fallback chain)
   _tag() / _vtag()            L2998  Tag value helpers (case-insensitive Vorbis)
   extract_cover_bytes()       L3091  Read raw cover bytes from audio tags
   read_metadata()             L3042  Build Track from mutagen
   LibraryTagFetchWorker       L3857  Sequential per-track tag fetcher
   TagFetchPopup               L3956  Modal "fetch missing tags for library" dialog
   LibraryLyricsFetchWorker    L4054  Sequential per-track lyrics fetcher
   LyricsFetchPopup            L4054  Modal "fetch lyrics for library" dialog
   _sanitize_filename_part()   L4032  Strip illegal filename chars (/,\0,edge dots)
   _build_new_filename()       L4043  Build new filename stem from pattern + metadata
   LibraryRenameWorker         L4080  Sequential per-track file renamer
   RenamePopup                 L4183  Modal "batch rename library" dialog (run-in-bg)
     closeEvent()              L4400  Hide dialog, keep worker running in background

 PLAYER
   RepeatMode                  L4238  Enum: NONE / ALL / ONE
   peaking_coefficients()      L4241  Biquad peaking filter coefficients
   Player                      L4264  GStreamer playbin wrapper + EQ + spectrum viz
     load()                    L4402  Load URI, build sink bin, start playback
     play_pause()              L4450  Toggle play/pause with PipeWire resilience
     _load_and_seek()          L4537  Load + seek after dead-pipe recovery
     _resume_with_reload()     L4589  Reload pipeline at current position
     _reload_at_pos()          L4629  WARNING-path pipeline reload (separate guard)
     seek()                    L4673  Flush-accurate seek + anchor update
     _apply_eq_to_filters_glib() L4861 Update biquad coefficients (GLib idle)
     _make_sink_bin()          L4889  Build EQ + spectrum + sink bin
     _create_eq_bin()          L4963  Build MAX_EQ_BANDS audioiirfilter chain
     _tick_pos()               L5102  Pos timer: interpolated pos + drift schedule
     _drift_query_glib()       L5164  GLib thread: non-blocking position query for drift
     _apply_drift_correction() L5194  Qt thread: anchor + stall detection (real GST pos)
     _store_spectrum()         L5398  GLib-thread: burst-safe magnitude merge + el accumulate
     _compute_viz_frame()      L5514  Main-thread smoothed bar computation (alpha^N EMA)

 MPRIS
   MprisServer                 L5471  MPRIS2 D-Bus interface (GLib thread)

 LIBRARY
   Track                       L2973  @dataclass: filepath + metadata
   scan_folder()               L4312  Walk directory tree → [Track]  (parallel, 4 workers)
   parse_m3u()                 L4327  Parse M3U/M3U8 → [Track]      (parallel, 4 workers)
   ScanThread                  L4349  QThread wrapper for scan_folder/parse_m3u
   ConfigPlaylistLoader        L4367  Non-blocking playlist loader for config restore

 VIEWS
   TrackTable                  L5902  QTableWidget with covers + sort + touch scroll
   GalleryView                 L6163  Virtual-scroll card gallery (Z/S layout modes)
   PlaylistPage                L6712  QStackedWidget: TrackTable + GalleryView
   _PlaylistRowWidget          L6794  Sidebar playlist row (label + delete button)
   Sidebar                     L6858  Left panel: search + library nav + playlist list (touch scroll enabled)

 CONTROL BAR
   ControlBar                  L7222  Seek bar + transport + viz + settings/EQ toggles
     _ensure_eq_popup()        L7416  Lazy-create EqPopup singleton
     _ensure_settings_popup()  L7441  Lazy-create SettingsPopup singleton
     _reset_idle_timer()       L7520  Reset OLED overlay idle countdown
     _on_idle_timeout()        L7530  Fire overlay when idle threshold reached
     init_from_config()        L7714  Apply saved config dict to all sub-widgets
     config_state()            L7806  Collect current state → config dict
     _precompute_bars()        L7835  Freq→bin map + bar geometry + cap offset arrays
     paintEvent()              L8125  Fully vectorised numpy pixel-buffer rendering

 MAIN WINDOW
   MainWindow                  L8433  QMainWindow: layout, signals, config I/O
     _build_ui()               L8473  Construct widget tree
     _connect_signals()        L8537  Wire all cross-widget signals
     _refresh_all_theme_widgets() L8642 Async theme switch + overlay
     _edit_tags()              L8829  Tag-edit dialog + mutagen write-back
     _start_playback()         L9161  Load track + update all UI state
     _advance()                L9243  Next track (shuffle/repeat logic)
     _save_config()            L9399  JSON config persistence (skips __open_with__)
     _load_config()            L9515  JSON config restore
     _handle_open_with()       L9444  Load file-manager / CLI "Open With" track
     closeEvent()              L9619  Purge __open_with__ playlist, then save + stop

 ENTRY POINT
   main()                      L9744
═══════════════════════════════════════════════════════════════════
"""
import sys, os, json, threading, enum, random, math, hashlib, bisect, gc as _gc, shutil, base64
import concurrent.futures as _cf
from time import monotonic as _monotonic

import numpy as _np
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List

from PyQt6.QtWidgets import *
from PyQt6.QtCore    import *
from PyQt6.QtGui     import *

import gi
gi.require_version('Gst', '1.0')
gi.require_version('Gio', '2.0')
from gi.repository import Gst, GLib, Gio
Gst.init(None)

from mutagen import File as MutagenFile

# ══════════════════════════════════════════════════════════════════════════════
#  Performance constants
# ══════════════════════════════════════════════════════════════════════════════
FPS_CAP       = 60           # render timer target fps
_FRAME_MS     = 1000 // FPS_CAP          # 16 ms
_FRAME_S      = 1.0 / FPS_CAP


# ══════════════════════════════════════════════════════════════════════════════
#  Palette
# ══════════════════════════════════════════════════════════════════════════════
_DARK_MODE = True  # global theme flag

# Dark palette
_DARK = dict(
    BG='#000000', BG2='#0a0a0a', BG3='#141414', BG4='#1e1e1e',
    BORD='#222222', B2='#333333', FG='#f0f0f0', FG2='#909090', SEL='#181818',
)
# Light palette
_LIGHT = dict(
    BG='#f4f4f4', BG2='#e8e8e8', BG3='#dcdcdc', BG4='#d0d0d0',
    BORD='#c0c0c0', B2='#aaaaaa', FG='#111111', FG2='#555555', SEL='#e0e0e0',
)

BG   = _DARK['BG']
BG2  = _DARK['BG2']
BG3  = _DARK['BG3']
BG4  = _DARK['BG4']
BORD = _DARK['BORD']
B2   = _DARK['B2']
ACC  = '#e03030'
ACCH = '#ff4444'
FG   = _DARK['FG']
FG2  = _DARK['FG2']
SEL  = _DARK['SEL']

def apply_theme(dark: bool) -> None:
    """Switch all palette globals between dark and light, then rebuild stylesheet."""
    global _DARK_MODE, BG, BG2, BG3, BG4, BORD, B2, FG, FG2, SEL, SS
    _DARK_MODE = dark
    pal = _DARK if dark else _LIGHT
    BG = pal['BG']; BG2 = pal['BG2']; BG3 = pal['BG3']; BG4 = pal['BG4']
    BORD = pal['BORD']; B2 = pal['B2']; FG = pal['FG']; FG2 = pal['FG2']
    SEL = pal['SEL']
    SS = make_stylesheet(ACC, ACCH)
    app = QApplication.instance()
    if app:
        app.setStyleSheet(SS)
        _apply_app_palette(app)

def _apply_app_palette(app):
    """Sync QPalette with current BG/FG globals."""
    pal = QPalette()
    for role, col in [
        (QPalette.ColorRole.Window,          BG),
        (QPalette.ColorRole.WindowText,      FG),
        (QPalette.ColorRole.Base,            BG),
        (QPalette.ColorRole.AlternateBase,   BG2),
        (QPalette.ColorRole.Text,            FG),
        (QPalette.ColorRole.Button,          BG3),
        (QPalette.ColorRole.ButtonText,      FG),
        (QPalette.ColorRole.Highlight,       SEL),
        (QPalette.ColorRole.HighlightedText, FG),
        (QPalette.ColorRole.Link,            ACC),
        (QPalette.ColorRole.ToolTipBase,     BG3),
        (QPalette.ColorRole.ToolTipText,     FG),
    ]:
        pal.setColor(role, QColor(col))
    app.setPalette(pal)

def make_acch(acc_hex: str) -> str:
    c = QColor(acc_hex)
    h, s, v, _ = c.getHsvF()
    c2 = QColor(); c2.setHsvF(h, max(0.0, s-0.15), min(1.0, v+0.25))
    return c2.name()

SUPPORTED_EXT = frozenset({
    '.flac', '.mp3', '.opus', '.m4a', '.aac', '.ogg',
    '.wav', '.wave', '.aiff', '.aif',
})
CONFIG_PATH   = Path.home() / '.config' / 'voidpulse' / 'config.json'
VIZ_BANDS     = 256
GST_BANDS     = 2048  # high-res spectrum for better log/lin mapping
OV_VIZ_H      = 60    # overlay visualization height px
MIN_DB        = -70.0
RAD           = 10   # global corner radius

# EQ constants
MAX_EQ_BANDS  = 10
EQ_FREQ_MIN   = 20.0
EQ_FREQ_MAX   = 22000.0
EQ_GAIN_MIN   = -10.0
EQ_GAIN_MAX   = 10.0
EQ_Q_MIN      = 0.1
EQ_Q_MAX      = 10.0
EQ_GAIN_MAX_GRAPH = 10.0   # graph vertical range ±10 dB
# ══════════════════════════════════════════════════════════════════════════════
#  Stylesheet — uses current BG/FG globals (dark or light)
# ══════════════════════════════════════════════════════════════════════════════
def make_stylesheet(acc: str = None, acch: str = None) -> str:
    if acc  is None: acc  = ACC
    if acch is None: acch = ACCH
    return f"""
* {{ outline: none; }}
QWidget     {{ background:{BG};  color:{FG};  font-size:13px; }}
QMainWindow {{ background:{BG}; }}
QDialog     {{ background:{BG}; border-radius:{RAD}px; }}
QWidget#sidebar {{ background:{BG2}; border-right:1px solid {BORD}; }}

QPushButton {{
    background:{BG3}; color:{FG}; border:1px solid {B2};
    border-radius:{RAD}px; padding:8px 14px; min-height:36px; text-align:center;
}}
QPushButton:hover   {{ border-color:{acc}; }}
QPushButton:pressed {{ background:{BG4}; }}
QPushButton:checked {{ color:{acc}; border-color:{acc}; background:{BG3}; }}
QPushButton:disabled {{ color:{B2}; border-color:{BORD}; }}

QPushButton#play {{
    background:{BG3}; color:{acc}; border:2px solid {acc}; border-radius:26px;
    min-width:52px; max-width:52px; min-height:52px; max-height:52px;
    font-size:22px; padding:0; text-align:center;
}}
QPushButton#play:hover   {{ border-color:{acch}; color:{acch}; background:{BG4}; }}
QPushButton#play:pressed {{ background:{BG4}; }}

QPushButton#ctrl {{
    background:transparent; border:none; color:{FG2}; font-size:20px;
    min-width:44px; max-width:44px; min-height:44px; max-height:44px;
    border-radius:22px; padding:0; text-align:center;
}}
QPushButton#ctrl:hover   {{ color:{FG};  background:{BG3}; }}
QPushButton#ctrl:checked {{ color:{acc}; background:transparent; }}
QPushButton#ctrl:pressed {{ background:{BG4}; }}

QPushButton#icon_btn {{
    background:transparent; border:none; color:{FG2}; font-size:18px;
    min-width:36px; max-width:36px; min-height:36px; max-height:36px;
    border-radius:18px; padding:0; text-align:center;
}}
QPushButton#icon_btn:hover   {{ color:{FG}; background:{BG3}; }}
QPushButton#icon_btn:pressed {{ background:{BG4}; }}

QSlider {{
    background: transparent;
}}
QSlider::groove:horizontal {{ background:{B2}; height:4px; border-radius:2px; }}
QSlider::sub-page:horizontal {{ background:{acc}; border-radius:2px; }}
QSlider::handle:horizontal {{
    background:{BG4}; border:2px solid {acc};
    width:14px; height:14px; border-radius:7px; margin:-5px 0;
}}
QSlider::handle:horizontal:hover {{
    background:{BG4}; border:3px solid {acch};
    width:14px; height:14px; border-radius:7px; margin:-5px 0;
}}
QSlider::handle:horizontal:pressed {{
    background:{BG4}; border:3px solid {acch};
    width:14px; height:14px; border-radius:7px; margin:-5px 0;
}}

QTableWidget {{
    background:{BG}; color:{FG}; border:none; gridline-color:transparent;
    selection-background-color:{SEL}; selection-color:{FG};
    border-radius:{RAD}px;
}}
QTableWidget::item {{ padding:6px 8px; border-bottom:1px solid {BORD}; }}
QTableWidget::item:selected {{ background:{SEL}; color:{FG}; }}
QHeaderView {{ background:{BG2}; border:none; }}
QHeaderView::section {{
    background:{BG2}; color:{FG2}; border:none;
    border-right:1px solid {BORD}; border-bottom:1px solid {BORD};
    padding:7px 8px; font-size:11px; text-align:left;
}}
QHeaderView::section:last {{ border-right:none; }}

QTabWidget::pane {{ border:none; border-top:1px solid {BORD}; }}
QTabBar {{ background:{BG2}; }}
QTabBar::tab {{
    background:{BG2}; color:{FG2};
    border:1px solid {BORD}; border-bottom:none;
    border-top-left-radius:6px; border-top-right-radius:6px;
    padding:5px 10px; min-width:50px; margin-right:2px; margin-top:3px;
    font-size:12px;
}}
QTabBar::tab:selected {{
    background:{BG}; color:{acc};
    border-color:{BORD}; border-top:2px solid {acc};
    border-bottom:1px solid {BG}; margin-bottom:-1px; margin-top:2px;
}}
QTabBar::tab:hover:!selected {{ color:{FG}; background:{BG3}; }}

QLineEdit {{
    background:{BG3}; color:{FG}; border:1px solid {B2};
    border-radius:18px; padding:8px 16px; min-height:36px; max-height:36px;
}}
QLineEdit:focus {{ border-color:{acc}; }}

QListWidget {{ background:{BG2}; border:none; color:{FG}; border-radius:{RAD}px; }}
QListWidget::item {{ padding:12px 14px; border-bottom:1px solid {BORD}; font-size:12px; }}
QListWidget::item:selected {{ background:{SEL}; color:{acc}; border-radius:6px; }}
QListWidget::item:hover:!selected {{ background:{BG3}; border-radius:6px; }}

QScrollBar {{ background:{BG}; border:none; }}
QScrollBar:vertical   {{ width:5px; margin:0; }}
QScrollBar:horizontal {{ height:5px; margin:0; }}
QScrollBar::handle {{ background:{B2}; border-radius:2px; min-height:20px; }}
QScrollBar::handle:hover {{ background:{acc}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
QScrollBar::add-page,  QScrollBar::sub-page {{ background:none; }}

QSplitter::handle {{ background:{BORD}; }}
QSplitter::handle:horizontal {{ width:1px; }}

QMenu {{ background:{BG3}; border:1px solid {B2}; border-radius:{RAD}px; padding:4px 0; }}
QMenu::item {{ padding:9px 22px; color:{FG}; }}
QMenu::item:selected {{ background:{SEL}; color:{acc}; }}
QMenu::separator {{ height:1px; background:{BORD}; margin:4px 0; }}

QLabel#now_title  {{ font-size:14px; font-weight:bold; color:{FG}; }}
QLabel#now_artist {{ font-size:12px; color:{FG2}; }}
QLabel#time_lbl   {{ font-size:11px; color:{FG2}; font-family:monospace;
                     min-width:38px; background:transparent; }}
QLabel#sect_lbl   {{ font-size:10px; color:{FG2}; letter-spacing:2px;
                     padding:12px 14px 5px 14px; }}
QLabel#popup_title{{ font-size:12px; font-weight:bold; color:{FG2};
                     letter-spacing:1px; background:transparent; }}
QLabel#setting_lbl{{ font-size:11px; color:{FG2}; background:transparent; }}

QStatusBar {{ background:{BG2}; color:{FG2}; font-size:11px; border-top:1px solid {BORD}; }}
QToolTip   {{ background:{BG3}; border:1px solid {B2}; color:{FG}; padding:5px 9px;
              border-radius:6px; }}
QFrame#ctrlbar {{ border-top:1px solid {BORD}; }}

/* Settings & EQ popups – background drawn by paintEvent */
QFrame#settings_popup,
QFrame#eq_popup {{
    background: transparent;
    border: none;
}}
"""

SS = make_stylesheet()  # initial

# ══════════════════════════════════════════════════════════════════════════════
#  Toggle switch (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
class ToggleSwitch(QWidget):
    """Toggle switch with optional two-sided labels.

    Single label:  ToggleSwitch('LABEL', parent)  — label shown on right
    Two-sided:     ToggleSwitch('OFF', 'ON', parent) — left=off, right=on

    muted_labels=True: both labels always render in FG2 (grey) regardless of state.
    """
    toggled = pyqtSignal(bool)
    W, H, R = 42, 22, 11
    PAD = 6   # gap between label and switch track

    def __init__(self, label_off: str = '', label_on_or_parent=None, parent=None,
                 muted_labels: bool = False):
        # Resolve overloaded signature
        if isinstance(label_on_or_parent, str):
            self._lbl_off = label_off          # left side / off state
            self._lbl_on  = label_on_or_parent # right side / on state
            self._two_sided = True
        else:
            # Backward compat: single label shown on right
            self._lbl_off  = ''
            self._lbl_on   = label_off
            self._two_sided = False
            if label_on_or_parent is not None and parent is None:
                parent = label_on_or_parent

        super().__init__(parent)
        self._muted_labels = muted_labels
        self._on = False; self._anim = 0.0
        self._timer = QTimer(self); self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._step)
        self._recalc_size()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _recalc_size(self):
        fm = QFontMetrics(self.font())
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

    def setCheckedSignal(self, on: bool):
        self.setChecked(on); self.toggled.emit(on)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._on = not self._on; self._timer.start(); self.toggled.emit(self._on)

    def _step(self):
        target = 1.0 if self._on else 0.0; delta = 0.15
        if abs(self._anim - target) < delta: self._anim = target; self._timer.stop()
        else: self._anim += delta if self._on else -delta
        self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._anim
        h_c = self.height()
        lw_off = self._lw_off

        # ── Track ──────────────────────────────────────────────────────────────
        _acc = QColor(ACC)
        ah, as_, av, _ = _acc.getHsvF()
        _track_on = QColor(); _track_on.setHsvF(ah, as_*0.55, av*0.38)
        _border_on = QColor(); _border_on.setHsvF(ah, as_*0.65, av*0.55)
        _off  = QColor(BG4)   # adapts to theme
        _boff = QColor(B2)    # adapts to theme
        if self._muted_labels:
            # Always use neutral grey track regardless of state
            tc = _off
            bc = _boff
        else:
            tc = QColor(
                int(_off.red()   + t*(_track_on.red()   - _off.red())),
                int(_off.green() + t*(_track_on.green() - _off.green())),
                int(_off.blue()  + t*(_track_on.blue()  - _off.blue())))
            bc = QColor(
                int(_boff.red()   + t*(_border_on.red()   - _boff.red())),
                int(_boff.green() + t*(_border_on.green() - _boff.green())),
                int(_boff.blue()  + t*(_border_on.blue()  - _boff.blue())))
        track_x = lw_off
        p.setPen(QPen(bc, 1.5)); p.setBrush(QBrush(tc))
        p.drawRoundedRect(QRectF(track_x, (h_c-self.H)/2, self.W, self.H), self.R, self.R)

        # ── Knob ───────────────────────────────────────────────────────────────
        kx = track_x + 3 + t*(self.W - 2*self.R - 2)
        ky = (h_c - self.H)/2 + (self.H - self.R*2)/2
        p.setPen(Qt.PenStyle.NoPen)
        knob_color = FG2 if self._muted_labels else (ACCH if self._on else FG2)
        p.setBrush(QBrush(QColor(knob_color)))
        p.drawEllipse(QRectF(kx, ky, self.R*2, self.R*2))

        # ── Labels ─────────────────────────────────────────────────────────────
        f = p.font(); p.setFont(f)
        DIM  = QColor(FG2)
        BRIGHT = QColor(FG)

        if self._lbl_off:
            # Left label: bright when OFF, dim when ON — or always dim if muted
            if self._muted_labels:
                c = DIM
            else:
                mix = 1.0 - t   # 1=off, 0=on
                c = QColor(
                    int(DIM.red()   + mix*(BRIGHT.red()   - DIM.red())),
                    int(DIM.green() + mix*(BRIGHT.green() - DIM.green())),
                    int(DIM.blue()  + mix*(BRIGHT.blue()  - DIM.blue())))
            p.setPen(c)
            p.drawText(QRectF(0, 0, lw_off - self.PAD, h_c),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       self._lbl_off)

        if self._lbl_on:
            # Right label: bright when ON, dim when OFF — or always dim if muted
            if self._muted_labels:
                c2 = DIM
            else:
                c2 = QColor(
                    int(DIM.red()   + t*(BRIGHT.red()   - DIM.red())),
                    int(DIM.green() + t*(BRIGHT.green() - DIM.green())),
                    int(DIM.blue()  + t*(BRIGHT.blue()  - DIM.blue())))
            p.setPen(c2)
            rstart = track_x + self.W + self.PAD
            p.drawText(QRectF(rstart, 0, self.width()-rstart, h_c),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self._lbl_on)
        p.end()

# ══════════════════════════════════════════════════════════════════════════════
#  Inline slider row (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
class JumpSlider(QSlider):
    """Slider that jumps immediately to click/touch position."""
    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        self._touch_active = False

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
                 fmt=lambda v: str(v), parent=None, step: int = 1):
        super().__init__(parent)
        self._fmt = fmt
        lay = QHBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(6)
        lbl = QLabel(label); lbl.setObjectName('setting_lbl')
        lbl.setFixedWidth(70)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._sl = JumpSlider(Qt.Orientation.Horizontal)
        self._sl.setRange(lo, hi); self._sl.setValue(val)
        self._sl.setSingleStep(step); self._sl.setPageStep(step * 4)
        self._sl.setFixedHeight(22)
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
#  Settings popup (sliders now have transparent background)
# ══════════════════════════════════════════════════════════════════════════════
class SettingsPopup(QFrame):
    viz_toggled    = pyqtSignal(bool)
    log_toggled    = pyqtSignal(bool)
    volume_changed = pyqtSignal(int)
    delay_changed  = pyqtSignal(int)
    inertia_changed    = pyqtSignal(int)
    brightness_changed = pyqtSignal(int)   # 0..100
    cover_toggled      = pyqtSignal(bool)
    accent_changed     = pyqtSignal(str)
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
    view_mode_changed    = pyqtSignal(str)   # 'classic' | 'gallery_z' | 'gallery_s'
    list_scale_changed   = pyqtSignal(int)   # row height px
    gallery_scale_changed = pyqtSignal(int)  # card size px

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('settings_popup')
        # Child widget (no top-level flags) — works on Wayland with move()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)
        self.hide()  # start hidden
        self._hidden_by_outside = False
        # Timestamp of last outside-click hide; used to suppress the toggle
        # that fires on the same click (avoids the "double-tap to open" bug).
        self._hide_timestamp_ms: int = 0
        # Close when user clicks outside the popup
        QApplication.instance().installEventFilter(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16); root.setSpacing(10)
        root.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        hdr = QLabel('SETTINGS'); hdr.setObjectName('popup_title')
        hdr.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(hdr)

        def _divider():
            d = QFrame(); d.setFixedHeight(1)
            d.setStyleSheet(f'background:{BORD}; margin:0;')
            return d

        def _section(title):
            lbl = QLabel(title)
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lbl.setStyleSheet(f'color:{FG2};font-size:9px;letter-spacing:2px;background:transparent;')
            return lbl

        root.addWidget(_divider())

        # ── OVERLAY ──────────────────────────────────────────────────────────
        root.addWidget(_section('OVERLAY'))
        ov_row = QHBoxLayout(); ov_row.setSpacing(16)
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
        root.addLayout(ov_row)
        self._ov_scale_row = SliderRow('Scale', 50, 200, 100, lambda v: f'{v}%')
        self._ov_scale_row.valueChanged.connect(self.overlay_scale_changed)
        root.addWidget(self._ov_scale_row)

        # Auto-open: toggle + timeout slider
        auto_row = QHBoxLayout(); auto_row.setSpacing(16)
        auto_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._ov_auto_sw = ToggleSwitch('Auto Timeout Overlay', self)
        self._ov_auto_sw.setChecked(False)
        self._ov_auto_sw.toggled.connect(self.overlay_auto_open_toggled)
        auto_row.addWidget(self._ov_auto_sw)
        root.addLayout(auto_row)
        self._ov_timeout_row = SliderRow('Timeout', 10, 300, 60, lambda v: f'{v}s')
        self._ov_timeout_row.valueChanged.connect(self.overlay_timeout_changed)
        root.addWidget(self._ov_timeout_row)

        # ── VIEW ─────────────────────────────────────────────────────────────
        root.addWidget(_divider())
        root.addWidget(_section('VIEW'))

        view_combo_row = QHBoxLayout(); view_combo_row.setSpacing(8)
        view_combo_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        view_combo_lbl = QLabel('Layout'); view_combo_lbl.setObjectName('setting_lbl')
        view_combo_lbl.setFixedWidth(55)
        view_combo_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._view_combo = QComboBox()
        self._view_combo.addItem('Classic')
        self._view_combo.addItem('Gallery (Z)')
        self._view_combo.addItem('Gallery (S)')
        self._view_combo.setStyleSheet(
            f'QComboBox {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:6px; padding:4px 8px; font-size:12px; }}'
            f'QComboBox:hover {{ border-color:{ACC}; }}'
            f'QComboBox::drop-down {{ border:none; width:20px; }}'
            f'QComboBox::down-arrow {{ color:{FG2}; }}'
            f'QComboBox QAbstractItemView {{ background:{BG3}; color:{FG};'
            f' selection-background-color:{SEL}; border:1px solid {B2}; }}')
        self._view_combo.currentTextChanged.connect(
            lambda t: self.view_mode_changed.emit(
                self._COMBO_TO_MODE.get(t, 'classic')))
        view_combo_row.addWidget(view_combo_lbl)
        view_combo_row.addWidget(self._view_combo, 1)
        root.addLayout(view_combo_row)

        self._list_scale_row = SliderRow('List size', 28, 80, 44, lambda v: f'{v}px')
        self._list_scale_row.valueChanged.connect(self.list_scale_changed)
        root.addWidget(self._list_scale_row)

        self._gallery_scale_row = SliderRow('Gallery size', 80, 220, 130, lambda v: f'{v}px', step=8)
        self._gallery_scale_row.valueChanged.connect(self.gallery_scale_changed)
        root.addWidget(self._gallery_scale_row)

        # Accent color swatch + theme switch + cover switch (same row)
        acc_row = QHBoxLayout(); acc_row.setSpacing(12)
        acc_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._accent_color = ACC
        self._accent_btn = QPushButton()
        self._accent_btn.setObjectName('accent_swatch')
        self._accent_btn.setFixedSize(32, 32)
        self._accent_btn.setStyleSheet(
            f'QPushButton#accent_swatch {{'
            f'  background:{ACC}; border-radius:16px; border:2px solid #666;'
            f'  min-width:32px; max-width:32px; min-height:32px; max-height:32px;'
            f'  padding:0;'
            f'}}')
        self._accent_btn.clicked.connect(self._pick_accent)
        # Dark/Light theme switch — muted (both labels grey like LIN/LOG)
        self._theme_sw = ToggleSwitch('DARK', 'LIGHT', self, muted_labels=True)
        self._theme_sw.setChecked(False)  # False = DARK
        self._theme_sw.toggled.connect(self._on_theme_toggle)
        # Cover switch
        self._cover_sw = ToggleSwitch('COVER', self)
        self._cover_sw.setChecked(True)
        self._cover_sw.toggled.connect(self.cover_toggled)
        acc_row.addWidget(self._accent_btn)
        acc_row.addWidget(self._theme_sw)
        acc_row.addWidget(self._cover_sw)
        root.addLayout(acc_row)

        # ── VISUALIZATION ─────────────────────────────────────────────────────
        root.addWidget(_divider())
        root.addWidget(_section('VISUALIZATION'))

        viz_sw_row = QHBoxLayout(); viz_sw_row.setSpacing(16)
        viz_sw_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._viz_sw = ToggleSwitch('VIZ',     self)
        self._log_sw = ToggleSwitch('LIN', 'LOG', self, muted_labels=True)
        self._viz_sw.setChecked(True); self._log_sw.setChecked(True)
        self._viz_sw.toggled.connect(self.viz_toggled)
        self._log_sw.toggled.connect(self.log_toggled)
        viz_sw_row.addWidget(self._viz_sw); viz_sw_row.addWidget(self._log_sw)
        root.addLayout(viz_sw_row)

        self._delay_row = SliderRow('Delay', 0, 1000, 0, lambda v: f'{v}ms')
        self._delay_row.valueChanged.connect(self.delay_changed)
        root.addWidget(self._delay_row)

        self._inertia_row = SliderRow('Inertia', 10, 100, 50, lambda v: f'{v}%')
        self._inertia_row.valueChanged.connect(self.inertia_changed)
        root.addWidget(self._inertia_row)

        self._bright_row = SliderRow('Brightness', 0, 100, 40, lambda v: f'{v}%')
        self._bright_row.valueChanged.connect(self.brightness_changed)
        root.addWidget(self._bright_row)

        # ── FETCH ─────────────────────────────────────────────────────────────
        root.addWidget(_divider())
        root.addWidget(_section('FETCH'))

        self._lyrics_fetch_sw = ToggleSwitch('AUTO LYRICS', self)
        self._lyrics_fetch_sw.setChecked(True)
        self._lyrics_fetch_sw.toggled.connect(self.lyrics_fetch_toggled)
        fetch_sw_row = QHBoxLayout(); fetch_sw_row.setSpacing(16)
        fetch_sw_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        fetch_sw_row.addWidget(self._lyrics_fetch_sw)
        root.addLayout(fetch_sw_row)

        action_row = QHBoxLayout(); action_row.setSpacing(4)
        self._btn_fetch_covers = QPushButton('Covers')
        self._btn_fetch_lyrics = QPushButton('Lyrics')
        self._btn_fetch_tags   = QPushButton('Tags')
        self._btn_rename       = QPushButton('Rename')
        for b in (self._btn_fetch_covers, self._btn_fetch_lyrics, self._btn_fetch_tags, self._btn_rename):
            b.setMinimumHeight(28); b.setMaximumHeight(36)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            b.setStyleSheet('font-size:12px;')
        self._btn_fetch_covers.clicked.connect(self.cover_fetch_toggled)
        self._btn_fetch_lyrics.clicked.connect(self.lyric_fetch_action)
        self._btn_fetch_tags.clicked.connect(self.tag_fetch_toggled)
        self._btn_rename.clicked.connect(self.rename_toggled)
        action_row.addWidget(self._btn_fetch_covers)
        action_row.addWidget(self._btn_fetch_lyrics)
        action_row.addWidget(self._btn_fetch_tags)
        action_row.addWidget(self._btn_rename)
        root.addLayout(action_row)

        # ── VOLUME (bottom) ───────────────────────────────────────────────────
        root.addWidget(_divider())
        vol_row = QHBoxLayout(); vol_row.setSpacing(6)
        vol_lbl = QLabel('Volume'); vol_lbl.setObjectName('setting_lbl')
        vol_lbl.setFixedWidth(70)
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
        root.addLayout(vol_row)

        self.setFixedWidth(310)
        self.setMaximumHeight(800)
        self.adjustSize()

    def _on_theme_toggle(self, light: bool):
        """Switch between dark (light=False) and light (light=True) themes."""
        apply_theme(dark=not light)
        win = self.window()
        if win and hasattr(win, '_refresh_all_theme_widgets'):
            # Create overlay, place over window, start async refresh
            overlay = _SpinningOverlay(win)
            overlay.show(); overlay.raise_()
            # Defer work until after the overlay's first paint so it is
            # visible before the (blocking) stylesheet refresh begins.
            QTimer.singleShot(32, lambda: win._refresh_all_theme_widgets(_overlay=overlay))
        self.repaint()

    def _pick_accent(self):
        # Must hide the Popup window before showing QColorDialog;
        # otherwise the Popup flag causes Qt to close the dialog immediately.
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
                    f'  background:{self._accent_color}; border-radius:16px; border:2px solid #666;'
                    f'  min-width:32px; max-width:32px; min-height:32px; max-height:32px;'
                    f'  padding:0;'
                    f'}}')
                self.accent_changed.emit(self._accent_color)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QBrush(QColor(BG)))
        p.setPen(QPen(QColor(B2), 1.0))
        p.drawRoundedRect(r, 12, 12)
        p.end()

    def volume(self)     -> int: return self._vol.value()
    def delay(self)      -> int: return self._delay_row.value()
    def inertia(self)    -> int: return self._inertia_row.value()
    def viz_on(self)     -> bool: return self._viz_sw.isChecked()
    def log_on(self)     -> bool: return self._log_sw.isChecked()

    def set_volume(self, v): self._vol.setValue(v)
    def set_delay(self, v):  self._delay_row.setValue(v)
    def set_inertia(self, v):self._inertia_row.setValue(v)
    def brightness(self) -> int: return self._bright_row.value()
    def set_brightness(self, v): self._bright_row.setValue(v)
    def cover_on(self) -> bool: return self._cover_sw.isChecked()
    def set_cover(self, v):     self._cover_sw.setChecked(v)
    def accent_color(self) -> str: return self._accent_color
    def set_accent_color(self, v: str):
        self._accent_color = v
        self._accent_btn.setStyleSheet(
            f'QPushButton#accent_swatch {{'
            f'  background:{v}; border-radius:16px; border:2px solid #666;'
            f'  min-width:32px; max-width:32px; min-height:32px; max-height:32px;'
            f'  padding:0;'
            f'}}')
    def set_viz(self, v):    self._viz_sw.setChecked(v)
    def set_log(self, v):    self._log_sw.setChecked(v)
    def dark_mode_on(self) -> bool: return not self._theme_sw.isChecked()
    def set_dark_mode(self, dark: bool):
        self._theme_sw.blockSignals(True)
        self._theme_sw.setChecked(not dark)  # True = light = checked
        self._theme_sw.blockSignals(False)
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
    def cover_fetch_on(self) -> bool: return True   # always enabled; user triggers manually
    def set_cover_fetch(self, v): pass              # no-op — kept for config compat

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

    def eventFilter(self, obj, e: QEvent) -> bool:
        """Close settings popup on mouse press outside it."""
        if (self.isVisible() and
                e.type() == QEvent.Type.MouseButtonPress and
                QApplication.activePopupWidget() is None and
                obj is not self and
                not (isinstance(obj, QWidget) and self.isAncestorOf(obj))):
            # For child widget: map click to our coords
            try:
                gpt = e.globalPosition().toPoint()
                local = self.mapFromGlobal(gpt)
                if not self.rect().contains(local):
                    self.hide()
                    self._hidden_by_outside = True
                    self._hide_timestamp_ms = QDateTime.currentMSecsSinceEpoch()
            except Exception:
                self.hide()
                self._hidden_by_outside = True
                self._hide_timestamp_ms = QDateTime.currentMSecsSinceEpoch()
        return False  # never swallow events

    def show_above(self, btn: QWidget):
        # Position as a child widget inside the main window — works on Wayland
        win = btn.window()
        if self.parent() is not win:
            self.setParent(win)
            self.setWindowFlags(Qt.WindowType.Widget)  # ensure child
        self.adjustSize()
        btn_in_win = btn.mapTo(win, QPoint(0, 0))
        x = btn_in_win.x() + btn.width()//2 - self.width()//2
        # Prefer above the button; if not enough room, show below
        y_above = btn_in_win.y() - self.height() - 6
        y_below = btn_in_win.y() + btn.height() + 6
        y = y_above if y_above >= 4 else y_below
        # clamp inside window
        x = max(4, min(x, win.width()  - self.width()  - 4))
        y = max(4, min(y, win.height() - self.height() - 4))
        self.move(x, y)
        self.show()
        self.raise_()

# ══════════════════════════════════════════════════════════════════════════════
#  Tag edit dialog
# ══════════════════════════════════════════════════════════════════════════════
class TagEditDialog(QDialog):
    """Tag editor with cover art management."""
    def __init__(self, track: 'Track', locked_paths: set = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Edit Tags')
        self.setModal(True)
        self.setMinimumWidth(420)
        self._track    = track
        self._locked   = track.filepath in (locked_paths or set())
        self._cover_action = 'keep'   # 'keep' | 'remove' | 'set'
        self._new_cover_bytes: Optional[bytes] = None
        self._locked_changed = False

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Cover row ──────────────────────────────────────────────────────
        cover_row = QHBoxLayout(); cover_row.setSpacing(12)
        self._cover_lbl = QLabel()
        self._cover_lbl.setFixedSize(96, 96)
        self._cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_lbl.setStyleSheet(
            f'background:{BG3}; border:1px solid {B2}; border-radius:6px;')
        # Load current cover
        raw = extract_cover_bytes(track.filepath)
        if raw:
            pm = QPixmap(); pm.loadFromData(raw)
            self._cover_lbl.setPixmap(
                pm.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation).copy(0,0,96,96))
        else:
            self._cover_lbl.setText('No Cover')
            self._cover_lbl.setStyleSheet(
                f'background:{BG3}; border:1px solid {B2}; border-radius:6px;'
                f' color:{FG2}; font-size:11px;')
        cover_row.addWidget(self._cover_lbl)

        cover_btns = QVBoxLayout(); cover_btns.setSpacing(4)
        self._btn_cover_file   = QPushButton('Set from File…')
        self._btn_cover_search = QPushButton('Search Cover…')
        self._btn_cover_remove = QPushButton('Remove Cover')
        self._btn_cover_lock   = QPushButton('Locked' if self._locked else 'Unlocked')
        self._btn_cover_lock.setCheckable(True)
        self._btn_cover_lock.setChecked(self._locked)
        self._btn_cover_lock.setToolTip('Locked: auto-fetch will not replace this cover')
        _tag_btn_ss = (
            f'QPushButton {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:5px; padding:1px 6px; min-height:0; font-size:11px; }}'
            f'QPushButton:hover {{ border-color:{ACC}; }}'
            f'QPushButton:pressed {{ background:{BG4}; }}'
            f'QPushButton:checked {{ color:{ACC}; border-color:{ACC}; }}'
        )
        for b in (self._btn_cover_file, self._btn_cover_search,
                  self._btn_cover_remove, self._btn_cover_lock):
            b.setFixedHeight(18)
            b.setStyleSheet(_tag_btn_ss)
            cover_btns.addWidget(b)
        # Tag fetch button below divider
        div2 = QFrame(); div2.setFrameShape(QFrame.Shape.HLine)
        div2.setStyleSheet(f'color:{BORD}; margin:2px 0;')
        cover_btns.addWidget(div2)
        self._btn_tag_fetch = QPushButton('Auto-fill Tags…')
        self._btn_tag_fetch.setFixedHeight(18)
        self._btn_tag_fetch.setStyleSheet(_tag_btn_ss)
        cover_btns.addWidget(self._btn_tag_fetch)
        self._btn_lyrics_fetch = QPushButton('Fetch Lyrics…')
        self._btn_lyrics_fetch.setFixedHeight(18)
        self._btn_lyrics_fetch.setStyleSheet(_tag_btn_ss)
        cover_btns.addWidget(self._btn_lyrics_fetch)
        cover_btns.addStretch()
        cover_row.addLayout(cover_btns)
        layout.addLayout(cover_row)

        self._btn_cover_file.clicked.connect(self._pick_cover_file)
        self._btn_cover_search.clicked.connect(self._search_cover_online)
        self._btn_cover_remove.clicked.connect(self._remove_cover)
        self._btn_cover_lock.toggled.connect(self._on_lock_toggled)
        self._btn_tag_fetch.clicked.connect(self._fetch_tags_online)
        self._btn_lyrics_fetch.clicked.connect(self._fetch_lyrics_online)

        # Divider
        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f'color:{BORD};'); layout.addWidget(div)

        # ── Text tags ──────────────────────────────────────────────────────
        for label, attr in [('Title', 'title'), ('Artist', 'artist'), ('Album', 'album')]:
            row = QHBoxLayout()
            lbl = QLabel(f'{label}:'); lbl.setFixedWidth(50)
            row.addWidget(lbl)
            edit = QLineEdit(getattr(track, attr))
            setattr(self, f'_{attr}_edit', edit)
            row.addWidget(edit)
            layout.addLayout(row)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _pick_cover_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select Cover Image', '',
            'Images (*.jpg *.jpeg *.png *.webp *.bmp)')
        if not path: return
        with open(path, 'rb') as f:
            data = f.read()
        pm = QPixmap()
        if pm.loadFromData(data):
            self._new_cover_bytes = data
            self._cover_action = 'set'
            self._cover_lbl.setPixmap(
                pm.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation).copy(0,0,96,96))
            self._cover_lbl.setText('')

    def _search_cover_online(self):
        """Fetch cover from online sources for this specific track in a background thread."""
        self._btn_cover_search.setEnabled(False)
        self._btn_cover_search.setText('Searching…')
        artist = self._artist_edit.text().strip() or self._track.artist
        title  = self._title_edit.text().strip()  or self._track.title
        album  = self._album_edit.text().strip()  or self._track.album

        # Run network fetch in a daemon thread; update UI via QTimer
        result = [None]

        def _fetch():
            result[0] = fetch_cover_online(artist, title, album)

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()

        def _poll():
            if t.is_alive():
                QTimer.singleShot(200, _poll)
                return
            data = result[0]
            self._btn_cover_search.setEnabled(True)
            self._btn_cover_search.setText('Search Cover…')
            if data:
                pm = QPixmap()
                if pm.loadFromData(data):
                    self._new_cover_bytes = data
                    self._cover_action    = 'set'
                    self._cover_lbl.setPixmap(
                        pm.scaled(96, 96,
                                  Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation).copy(0, 0, 96, 96))
                    self._cover_lbl.setText('')
                    self._cover_lbl.setStyleSheet(
                        f'background:{BG3};border:1px solid {B2};border-radius:6px;')
                else:
                    self._cover_lbl.setText('Load error')
            else:
                self._btn_cover_search.setText('Not found')
                QTimer.singleShot(2000,
                    lambda: self._btn_cover_search.setText('Search Cover…'))

        QTimer.singleShot(200, _poll)

    def _fetch_tags_online(self):
        """Look up missing title/artist/album for this track and fill the edit fields."""
        self._btn_tag_fetch.setEnabled(False)
        self._btn_tag_fetch.setText('Searching…')
        artist = self._artist_edit.text().strip() or self._track.artist
        title  = self._title_edit.text().strip()  or self._track.title or Path(self._track.filepath).stem

        result = [{}]
        def _fetch():
            result[0] = lookup_tags_online(artist, title)

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()

        def _poll():
            if t.is_alive():
                QTimer.singleShot(200, _poll)
                return
            self._btn_tag_fetch.setEnabled(True)
            tags = result[0]
            if tags:
                # Fill only empty fields
                if not self._title_edit.text().strip()  and tags.get('title'):
                    self._title_edit.setText(tags['title'])
                if not self._artist_edit.text().strip() and tags.get('artist'):
                    self._artist_edit.setText(tags['artist'])
                if not self._album_edit.text().strip()  and tags.get('album'):
                    self._album_edit.setText(tags['album'])
                self._btn_tag_fetch.setText('Auto-fill Tags…')
            else:
                self._btn_tag_fetch.setText('Not found')
                QTimer.singleShot(2000,
                    lambda: self._btn_tag_fetch.setText('Auto-fill Tags…'))

        QTimer.singleShot(200, _poll)

    def _fetch_lyrics_online(self):
        """Force-fetch lyrics from all online sources, ignoring any embedded tags.

        All APIs are queried in parallel; the worker waits for every future to
        settle so a synced result that arrives late still beats an early plain
        one.  On success the best result (synced preferred) is written back into
        the audio file's tags via embed_lyrics.  The button label tracks
        progress so the user has live feedback.
        """
        self._btn_lyrics_fetch.setEnabled(False)
        self._btn_lyrics_fetch.setText('Searching…')

        track  = self._track
        artist = self._artist_edit.text().strip()  or track.artist
        title  = self._title_edit.text().strip()   or track.title
        album  = self._album_edit.text().strip()   or track.album
        dur    = getattr(track, 'duration', 0) or 0

        result = [None, None]   # [synced, plain]

        def _fetch():
            sources = [
                ('LrcLib (exact)',  lambda: _src_lrclib_exact(artist, title, album, dur)),
                ('LrcLib (search)', lambda: _src_lrclib_search(artist, title)),
                ('Lyrics.ovh',      lambda: _src_lyrics_ovh(artist, title)),
                ('Musixmatch',      lambda: _src_musixmatch(artist, title)),
                ('Genius',          lambda: _src_genius_search(artist, title)),
                ('AZLyrics',        lambda: _src_azlyrics(artist, title)),
                ('SongLyrics',      lambda: _src_songlyrics(artist, title)),
                ('ChartLyrics',     lambda: _src_chartlyrics(artist, title)),
                ('Letras.mus.br',   lambda: _src_letras(artist, title)),
            ]
            lock        = threading.Lock()
            best_synced = [None]
            best_plain  = [None]

            def _run(fn):
                try:
                    s, p = fn()
                except Exception:
                    return
                with lock:
                    if s and best_synced[0] is None:
                        best_synced[0] = s
                    if p and best_plain[0] is None:
                        best_plain[0] = p

            # Fire all sources in parallel and wait for EVERY future to finish.
            # This guarantees a synced result found late beats a plain one found
            # early — unlike the player's LyricsFetcher which short-circuits on
            # the first synced hit for latency.  Here the user has explicitly
            # requested a full search, so accuracy takes priority over speed.
            with _cf.ThreadPoolExecutor(max_workers=len(sources)) as pool:
                futs = [pool.submit(_run, fn) for _, fn in sources]
                _cf.wait(futs)

            result[0] = best_synced[0]
            result[1] = best_plain[0]

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()

        def _poll():
            if t.is_alive():
                QTimer.singleShot(200, _poll)
                return

            synced = result[0]
            plain  = result[1]
            self._btn_lyrics_fetch.setEnabled(True)

            if synced or plain:
                # Embed result into the audio file so the player panel picks it
                # up on the next track load without another network round-trip.
                threading.Thread(
                    target=embed_lyrics,
                    args=(track.filepath, synced, plain or ''),
                    daemon=True,
                ).start()
                kind = 'synced' if synced else 'plain'
                self._btn_lyrics_fetch.setText(f'Saved ({kind})')
                QTimer.singleShot(2500,
                    lambda: self._btn_lyrics_fetch.setText('Fetch Lyrics…'))
            else:
                self._btn_lyrics_fetch.setText('Not found')
                QTimer.singleShot(2000,
                    lambda: self._btn_lyrics_fetch.setText('Fetch Lyrics…'))

        QTimer.singleShot(200, _poll)

    def _remove_cover(self):
        self._cover_action = 'remove'
        self._new_cover_bytes = None
        self._cover_lbl.clear()
        self._cover_lbl.setText('Removed')

    def _on_lock_toggled(self, locked: bool):
        self._locked = locked
        self._locked_changed = True
        self._btn_cover_lock.setText('Locked' if locked else 'Unlocked')

    def get_tags(self):
        return self._title_edit.text(), self._artist_edit.text(), self._album_edit.text()

    def get_cover_result(self):
        """Returns (action, bytes|None, locked)."""
        return self._cover_action, self._new_cover_bytes, self._locked

# ══════════════════════════════════════════════════════════════════════════════
#  Custom slider cell for EQ table
# ══════════════════════════════════════════════════════════════════════════════
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
        lay.setContentsMargins(6, 6, 6, 6)
        self._slider = JumpSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setValue(self._to_slider(val))
        self._slider.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._slider.valueChanged.connect(self._on_slider)

        self._label = QLabel(self._format(val))
        self._label.setFixedWidth(60)
        self._label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

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

    def set_value(self, val):
        self._val = val
        self._slider.setValue(self._to_slider(val))
        self._label.setText(self._format(val))

    def set_band_index(self, idx):
        self._band_idx = idx

# ══════════════════════════════════════════════════════════════════════════════
#  Cover art fetching + embedding
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_cover_itunes(artist: str, title: str) -> Optional[bytes]:
    try:
        q = _urlparse.quote(f'{artist} {title}')
        d = _get_json(f'https://itunes.apple.com/search?term={q}'
                      f'&media=music&entity=song&limit=5')
        for item in d.get('results', []):
            url = item.get('artworkUrl100', '')
            if url:
                url = url.replace('100x100bb', '600x600bb')
                data = _get(url)
                if isinstance(data, str): data = data.encode('latin1')
                if data and len(data) > 1000: return data
    except Exception: pass
    return None

def _fetch_cover_deezer(artist: str, title: str) -> Optional[bytes]:
    try:
        q = _urlparse.quote(f'artist:"{artist}" track:"{title}"')
        d = _get_json(f'https://api.deezer.com/search?q={q}&limit=3')
        for item in d.get('data', []):
            url = item.get('album', {}).get('cover_xl', '') or \
                  item.get('album', {}).get('cover_big', '')
            if url:
                data = _get(url)
                if isinstance(data, str): data = data.encode('latin1')
                if data and len(data) > 1000: return data
    except Exception: pass
    return None

def _fetch_cover_musicbrainz(artist: str, album: str) -> Optional[bytes]:
    try:
        q = _urlparse.quote(f'artist:"{artist}" AND release:"{album}"')
        d = _get_json(
            f'https://musicbrainz.org/ws/2/release/?query={q}&limit=5&fmt=json',
            headers={'Accept': 'application/json'})
        for rel in d.get('releases', [])[:3]:
            mbid = rel.get('id', '')
            if not mbid: continue
            url = f'https://coverartarchive.org/release/{mbid}/front-500'
            try:
                req = _urlreq.Request(url, headers={'User-Agent': 'VoidPulse/2.0'})
                with _urlreq.urlopen(req, timeout=8) as r:
                    data = r.read()
                if data and len(data) > 1000: return data
            except Exception: pass
    except Exception: pass
    return None

def _fetch_cover_lastfm(artist: str, album: str) -> Optional[bytes]:
    # Uses public lastfm API with community key
    try:
        a = _urlparse.quote(artist); al = _urlparse.quote(album)
        url = (f'https://ws.audioscrobbler.com/2.0/?method=album.getinfo'
               f'&artist={a}&album={al}&api_key=f24e79dab45bed5e3d35c47e1f3e3bda&format=json')
        d = _get_json(url)
        images = d.get('album', {}).get('image', [])
        for img in reversed(images):
            img_url = img.get('#text', '')
            if img_url and 'noimage' not in img_url:
                data = _get(img_url)
                if isinstance(data, str): data = data.encode('latin1')
                if data and len(data) > 1000: return data
    except Exception: pass
    return None

def fetch_cover_online(artist: str, title: str, album: str) -> Optional[bytes]:
    """Try multiple sources, return raw image bytes or None."""
    for fn in [
        lambda: _fetch_cover_itunes(artist, title),
        lambda: _fetch_cover_deezer(artist, title),
        lambda: _fetch_cover_musicbrainz(artist, album),
        lambda: _fetch_cover_lastfm(artist, album),
    ]:
        try:
            data = fn()
            if data: return data
        except Exception: pass
    return None

# ══════════════════════════════════════════════════════════════════════════════
#  Online tag / metadata lookup
# ══════════════════════════════════════════════════════════════════════════════

def _lookup_tags_musicbrainz(artist: str, title: str) -> dict:
    """Query MusicBrainz for recording metadata. Returns dict with keys:
    title, artist, album, date. All values may be empty strings."""
    try:
        q = _urlparse.quote(f'recording:"{title}" AND artist:"{artist}"')
        d = _get_json(
            f'https://musicbrainz.org/ws/2/recording/?query={q}&limit=5&fmt=json',
            headers={'Accept': 'application/json'})
        for rec in d.get('recordings', [])[:5]:
            t = rec.get('title', '').strip()
            rels = rec.get('releases', [])
            alb = rels[0].get('title', '').strip() if rels else ''
            date = rels[0].get('date', '')[:4] if rels else ''
            art_list = rec.get('artist-credit', [])
            art = art_list[0].get('artist', {}).get('name', '').strip() if art_list else ''
            if t or art:
                return {'title': t, 'artist': art, 'album': alb, 'date': date}
    except Exception:
        pass
    return {}

def _lookup_tags_itunes(artist: str, title: str) -> dict:
    """Query iTunes Search API for track metadata."""
    try:
        q = _urlparse.quote(f'{artist} {title}')
        d = _get_json(
            f'https://itunes.apple.com/search?term={q}&media=music&entity=song&limit=5')
        for item in d.get('results', []):
            return {
                'title':  item.get('trackName', '').strip(),
                'artist': item.get('artistName', '').strip(),
                'album':  item.get('collectionName', '').strip(),
                'date':   str(item.get('releaseDate', ''))[:4],
            }
    except Exception:
        pass
    return {}

def _lookup_tags_lastfm(artist: str, title: str) -> dict:
    """Query Last.fm track.getInfo for metadata."""
    try:
        a = _urlparse.quote(artist); t = _urlparse.quote(title)
        url = (f'https://ws.audioscrobbler.com/2.0/?method=track.getinfo'
               f'&artist={a}&track={t}&api_key=f24e79dab45bed5e3d35c47e1f3e3bda&format=json')
        d = _get_json(url)
        tr = d.get('track', {})
        alb = tr.get('album', {}).get('title', '').strip()
        return {
            'title':  tr.get('name', '').strip(),
            'artist': tr.get('artist', {}).get('name', '').strip() if isinstance(tr.get('artist'), dict) else tr.get('artist', '').strip(),
            'album':  alb,
            'date':   '',
        }
    except Exception:
        pass
    return {}

def lookup_tags_online(artist: str, title: str) -> dict:
    """Try multiple sources; return best result dict with title/artist/album keys.
    Only fields that are non-empty in the result should be used to fill gaps."""
    results = [{}]
    lock = threading.Lock()

    def _try(fn):
        try:
            r = fn()
            if r.get('album') or r.get('artist'):
                with lock:
                    # Merge: keep first non-empty value found per key
                    for k, v in r.items():
                        if v and not results[0].get(k):
                            results[0][k] = v
        except Exception:
            pass

    sources = [
        lambda: _lookup_tags_musicbrainz(artist, title),
        lambda: _lookup_tags_itunes(artist, title),
        lambda: _lookup_tags_lastfm(artist, title),
    ]
    with _cf.ThreadPoolExecutor(max_workers=3) as pool:
        _cf.wait([pool.submit(_try, fn) for fn in sources])

    return results[0]

def write_tags_to_file(fp: str, tags: dict) -> bool:
    """Write title/artist/album from tags dict into the audio file. Returns True on success."""
    try:
        ext = Path(fp).suffix.lower()
        af  = _open_audio(fp)
        if af is None: return False
        if af.tags is None: af.add_tags()

        if ext == '.mp3':
            from mutagen.id3 import TIT2, TPE1, TALB
            if tags.get('title'):  af.tags['TIT2'] = TIT2(encoding=3, text=tags['title'])
            if tags.get('artist'): af.tags['TPE1'] = TPE1(encoding=3, text=tags['artist'])
            if tags.get('album'):  af.tags['TALB'] = TALB(encoding=3, text=tags['album'])
        elif ext in ('.flac', '.ogg', '.opus'):
            if tags.get('title'):  af.tags['title']  = [tags['title']]
            if tags.get('artist'): af.tags['artist'] = [tags['artist']]
            if tags.get('album'):  af.tags['album']  = [tags['album']]
        elif ext in ('.m4a', '.aac'):
            if tags.get('title'):  af.tags['\xa9nam'] = [tags['title']]
            if tags.get('artist'): af.tags['\xa9ART'] = [tags['artist']]
            if tags.get('album'):  af.tags['\xa9alb'] = [tags['album']]
        else:
            return False
        af.save()
        return True
    except Exception as e:
        print(f'write_tags_to_file error: {e}')
        return False

def embed_cover_bytes(fp: str, data: bytes) -> bool:
    """Write cover bytes into the audio file tags. Returns True on success."""
    try:
        ext = Path(fp).suffix.lower()
        af  = _open_audio(fp)
        if af is None: return False

        if ext == '.mp3':
            from mutagen.id3 import APIC
            if af.tags is None: af.add_tags()
            mime = 'image/jpeg' if data[:3] == b'\xff\xd8\xff' else 'image/png'
            af.tags.delall('APIC')
            af.tags.add(APIC(encoding=3, mime=mime, type=3,
                             desc='Cover', data=data))

        elif ext == '.flac':
            from mutagen.flac import Picture
            pic = Picture()
            pic.type = 3; pic.mime = 'image/jpeg' if data[:3] == b'\xff\xd8\xff' else 'image/png'
            pic.desc = 'Cover'; pic.data = data
            af.clear_pictures(); af.add_picture(pic)

        elif ext in ('.m4a', '.aac'):
            from mutagen.mp4 import MP4Cover
            fmt = MP4Cover.FORMAT_JPEG if data[:3] == b'\xff\xd8\xff' else MP4Cover.FORMAT_PNG
            af.tags['covr'] = [MP4Cover(data, imageformat=fmt)]

        elif ext in ('.ogg', '.opus'):
            from mutagen.flac import Picture
            pic = Picture()
            pic.type = 3; pic.mime = 'image/jpeg' if data[:3] == b'\xff\xd8\xff' else 'image/png'
            pic.desc = 'Cover'; pic.data = data
            encoded = base64.b64encode(pic.write()).decode('ascii')
            af.tags['metadata_block_picture'] = [encoded]
        else:
            return False

        af.save(); return True
    except Exception as e:
        print(f'embed_cover_bytes error: {e}'); return False

def embed_lyrics(fp: str, synced, plain: str) -> bool:
    """Write lyrics into audio file tags. Returns True on success."""
    try:
        ext = Path(fp).suffix.lower()
        af  = _open_audio(fp)
        if af is None: return False

        if synced:
            lrc_lines = [f'[{ms//60000:02d}:{(ms%60000)/1000:05.2f}]{txt}'
                         for ms, txt in synced]
            lrc_text = '\n'.join(lrc_lines)
        else:
            lrc_text = None

        text_to_write = lrc_text if lrc_text else plain

        if ext == '.mp3':
            from mutagen.id3 import USLT
            if af.tags is None: af.add_tags()
            af.tags.delall('USLT'); af.tags.delall('SYLT')
            af.tags.add(USLT(encoding=3, lang='eng', desc='', text=text_to_write))

        elif ext in ('.flac', '.ogg', '.opus'):
            if af.tags is None: af.add_tags()
            af.tags['LYRICS'] = [text_to_write]

        elif ext in ('.m4a', '.aac'):
            if af.tags is None: af.add_tags()
            af.tags['\xa9lyr'] = [text_to_write]

        else:
            return False

        af.save(); return True
    except Exception as e:
        print(f'embed_lyrics error: {e}'); return False

# ══════════════════════════════════════════════════════════════════════════════
#  Lyrics — fetch, parse, display
# ══════════════════════════════════════════════════════════════════════════════
import re          as _re
import html        as _html
import urllib.request as _urlreq
import urllib.parse   as _urlparse

# ── LRC parser ────────────────────────────────────────────────────────────────
_LRC_LINE_RE = _re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)')

def _lrc_parse(text: str):
    lines = []
    for raw in text.splitlines():
        m = _LRC_LINE_RE.match(raw.strip())
        if m:
            mm, ss_str, txt = m.groups()
            ms = int(mm) * 60000 + round(float(ss_str) * 1000)
            lines.append((ms, txt.strip()))
    return sorted(lines, key=lambda x: x[0]) if lines else None

# ── Embedded tags ─────────────────────────────────────────────────────────────
def _extract_embedded_lyrics(fp: str):
    try:
        af = _open_audio(fp)
        if af is None or af.tags is None:
            return None, None
        ext = Path(fp).suffix.lower()
        if ext == '.mp3':
            from mutagen.id3 import USLT, SYLT
            for tag in af.tags.values():
                if isinstance(tag, SYLT):
                    lines = sorted([(ms, t) for t, ms in tag.text if t.strip()],
                                   key=lambda x: x[0])
                    if lines: return lines, None
            for tag in af.tags.values():
                if isinstance(tag, USLT) and tag.text.strip():
                    p = _lrc_parse(tag.text)
                    return (p, None) if p else (None, tag.text.strip())
        else:
            tg = af.tags
            # Check synced-lyrics tags first (stored by LRC-aware taggers)
            for key in ('syncedlyrics', 'SYNCEDLYRICS'):
                v = tg.get(key)
                if v:
                    text = str(v[0]) if isinstance(v, list) else str(v)
                    if text.strip():
                        p = _lrc_parse(text)
                        if p:
                            return p, None
            # Fall back to plain/unsynced tags; try LRC parse in case they contain timestamps
            for key in ('lyrics', 'LYRICS', 'unsyncedlyrics', 'UNSYNCEDLYRICS'):
                v = tg.get(key)
                if v:
                    text = str(v[0]) if isinstance(v, list) else str(v)
                    if text.strip():
                        p = _lrc_parse(text)
                        return (p, None) if p else (None, text.strip())
    except Exception:
        pass
    return None, None

# ── Network helpers ───────────────────────────────────────────────────────────
def _get(url, timeout=8, headers=None):
    h = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) VoidPulse/2.0'}
    if headers: h.update(headers)
    req = _urlreq.Request(url, headers=h)
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')

def _get_json(url, timeout=8, headers=None):
    return json.loads(_get(url, timeout, headers))

def _apply_scroller_properties(widget):
    """Apply standard kinetic scroll properties to a viewport widget."""
    sp = QScrollerProperties()
    sp.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor,         0.35)
    sp.setScrollMetric(QScrollerProperties.ScrollMetric.MaximumVelocity,            0.8)
    sp.setScrollMetric(QScrollerProperties.ScrollMetric.VerticalOvershootPolicy,
                       QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
    sp.setScrollMetric(QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy,
                       QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
    QScroller.scroller(widget).setScrollerProperties(sp)


# ── Source functions — each returns (synced|None, plain|None) or (None, text) ─

def _src_lrclib_exact(artist, title, album, dur):
    try:
        p = _urlparse.urlencode({'artist_name': artist, 'track_name': title,
                                  'album_name': album, 'duration': int(dur)})
        d = _get_json(f'https://lrclib.net/api/get?{p}')
        sl = d.get('syncedLyrics') or ''
        pl = d.get('plainLyrics')  or ''
        if sl.strip():
            lrc = _lrc_parse(sl)
            if lrc: return lrc, None
        if pl.strip(): return None, pl.strip()
    except Exception: pass
    return None, None

def _src_lrclib_search(artist, title):
    try:
        q = _urlparse.quote(f'{artist} {title}')
        results = _get_json(f'https://lrclib.net/api/search?q={q}')
        for item in results[:6]:
            sl = item.get('syncedLyrics') or ''
            pl = item.get('plainLyrics')  or ''
            if sl.strip():
                lrc = _lrc_parse(sl)
                if lrc: return lrc, None
            if pl.strip(): return None, pl.strip()
    except Exception: pass
    return None, None

def _src_lyrics_ovh(artist, title):
    try:
        a = _urlparse.quote(artist); t = _urlparse.quote(title)
        d = _get_json(f'https://api.lyrics.ovh/v1/{a}/{t}')
        txt = (d.get('lyrics') or '').strip()
        if txt: return None, txt
    except Exception: pass
    return None, None

def _src_chartlyrics(artist, title):
    try:
        a = _urlparse.quote(artist); t = _urlparse.quote(title)
        xml = _get(f'http://api.chartlyrics.com/apiv1.asmx/SearchLyricDirect?artist={a}&song={t}')
        m = _re.search(r'<Lyric>(.*?)</Lyric>', xml, _re.DOTALL)
        if m:
            txt = _html.unescape(m.group(1)).strip()
            if txt and len(txt) > 30: return None, txt
    except Exception: pass
    return None, None

def _src_musixmatch(artist, title):
    # Unofficial Musixmatch community token (no auth required for search)
    try:
        token = 'community'
        a = _urlparse.quote(artist); t = _urlparse.quote(title)
        base = 'https://api.musixmatch.com/ws/1.1'
        # search track
        d = _get_json(f'{base}/track.search?q_artist={a}&q_track={t}'
                      f'&apikey={token}&page_size=3&f_has_lyrics=1')
        items = (d.get('message', {}).get('body', {})
                   .get('track_list', []))
        for item in items[:3]:
            tid = item.get('track', {}).get('track_id')
            if not tid: continue
            d2 = _get_json(f'{base}/track.lyrics.get?track_id={tid}&apikey={token}')
            body = d2.get('message', {}).get('body', {})
            lyr = body.get('lyrics', {}).get('lyrics_body', '').strip()
            if lyr and '******* This Lyrics' not in lyr:
                return None, lyr
            # Also try subtitle (synced)
            d3 = _get_json(f'{base}/track.subtitle.get?track_id={tid}&apikey={token}')
            sub = (d3.get('message', {}).get('body', {})
                      .get('subtitle', {}).get('subtitle_body', ''))
            if sub.strip():
                lrc = _lrc_parse(sub)
                if lrc: return lrc, None
    except Exception: pass
    return None, None

def _src_genius_search(artist, title):
    # Genius web scraping — no API key
    try:
        q = _urlparse.quote(f'{artist} {title}')
        html_txt = _get(f'https://genius.com/search?q={q}',
                        headers={'Accept': 'text/html'})
        # Find first hit URL
        m = _re.search(r'"url":"(https://genius\.com/[^"]+lyrics[^"]*)"', html_txt)
        if not m: return None, None
        url = m.group(1)
        page = _get(url, headers={'Accept': 'text/html'})
        # Extract lyrics containers
        parts = _re.findall(
            r'<div[^>]*data-lyrics-container[^>]*>(.*?)</div>',
            page, _re.DOTALL)
        if not parts: return None, None
        lines = []
        for part in parts:
            clean = _re.sub(r'<br\s*/?>', '\n', part)
            clean = _re.sub(r'<[^>]+>', '', clean)
            lines.append(_html.unescape(clean).strip())
        txt = '\n'.join(lines).strip()
        if txt and len(txt) > 30: return None, txt
    except Exception: pass
    return None, None

def _src_azlyrics(artist, title):
    try:
        a = _re.sub(r'[^a-z0-9]', '', artist.lower())
        t = _re.sub(r'[^a-z0-9]', '', title.lower())
        url = f'https://www.azlyrics.com/lyrics/{a}/{t}.html'
        page = _get(url, headers={'Accept': 'text/html'}, timeout=9)
        m = _re.search(
            r'<!-- Usage of azlyrics.*?-->\s*(.*?)\s*</div>',
            page, _re.DOTALL)
        if m:
            raw = _re.sub(r'<[^>]+>', '', m.group(1))
            txt = _html.unescape(raw).strip()
            if txt and len(txt) > 30: return None, txt
    except Exception: pass
    return None, None

def _src_songlyrics(artist, title):
    try:
        a = _re.sub(r'[^a-z0-9-]', '-', artist.lower()).strip('-')
        t = _re.sub(r'[^a-z0-9-]', '-', title.lower()).strip('-')
        url = f'https://www.songlyrics.com/{a}/{t}-lyrics/'
        page = _get(url, headers={'Accept': 'text/html'})
        m = _re.search(r'<p id="songLyricsDiv"[^>]*>(.*?)</p>', page, _re.DOTALL)
        if m:
            raw = _re.sub(r'<[^>]+>', '', m.group(1))
            txt = _html.unescape(raw).strip()
            if txt and 'not found' not in txt.lower() and len(txt) > 30:
                return None, txt
    except Exception: pass
    return None, None

def _src_letras(artist, title):
    try:
        a = _re.sub(r'[^a-z0-9-]', '-', artist.lower()).strip('-')
        t = _re.sub(r'[^a-z0-9-]', '-', title.lower()).strip('-')
        url = f'https://www.letras.mus.br/{a}/{t}/'
        page = _get(url, headers={'Accept': 'text/html'})
        m = _re.search(r'<div class="lyric-original">(.*?)</div>', page, _re.DOTALL)
        if m:
            raw = _re.sub(r'<br\s*/?>', '\n', m.group(1))
            raw = _re.sub(r'<[^>]+>', '', raw)
            txt = _html.unescape(raw).strip()
            if txt and len(txt) > 30: return None, txt
    except Exception: pass
    return None, None

# ── Fetcher — sequential sources with status callbacks ────────────────────────
class ClickableLyricLine(QLabel):
    clicked = pyqtSignal(int)  # emits timestamp ms

    def __init__(self, text: str, ms: int, parent=None):
        super().__init__(text, parent)
        self._ms = ms
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._ms)
        super().mousePressEvent(e)

class LyricsFetcher(QObject):
    finished = pyqtSignal(object, object)   # synced|None, plain|None
    status   = pyqtSignal(str)              # progress message

    def __init__(self, track, fetch_online: bool = True):
        super().__init__()
        self._t = track
        self._fetch_online = fetch_online
        self.was_online = False   # set True if result came from network

    def run(self):
        t = self._t
        artist = (t.artist or '').strip()
        title  = (t.title  or '').strip()
        album  = (t.album  or '').strip()

        # 1. Embedded tags — instant, no network needed
        self.status.emit('Checking embedded tags…')
        synced, plain = _extract_embedded_lyrics(t.filepath)
        if synced or plain:
            self.finished.emit(synced, plain); return

        if not self._fetch_online:
            self.status.emit('')
            self.finished.emit(None, None); return

        # 2. All online sources fired in parallel; return as soon as a synced
        #    result arrives — don't wait for slower sources to finish.
        #    If no synced result comes, keep the best plain result seen so far
        #    and return once every future has settled.
        #
        #    Source order doubles as priority: LrcLib (the only reliable synced
        #    provider) is first so it almost always wins the synced slot before
        #    the scraping sources even get a response back.
        sources = [
            ('LrcLib (exact)',   lambda: _src_lrclib_exact(artist, title, album, t.duration)),
            ('LrcLib (search)',  lambda: _src_lrclib_search(artist, title)),
            ('Lyrics.ovh',       lambda: _src_lyrics_ovh(artist, title)),
            ('Musixmatch',       lambda: _src_musixmatch(artist, title)),
            ('Genius',           lambda: _src_genius_search(artist, title)),
            ('AZLyrics',         lambda: _src_azlyrics(artist, title)),
            ('SongLyrics',       lambda: _src_songlyrics(artist, title)),
            ('ChartLyrics',      lambda: _src_chartlyrics(artist, title)),
            ('Letras.mus.br',    lambda: _src_letras(artist, title)),
        ]

        self.status.emit('Searching lyrics…')

        result_lock = threading.Lock()
        best_synced = [None]
        best_plain  = [None]

        def _run_source(fn):
            # Each worker checks the shared synced flag before doing network I/O.
            # This prevents queued-but-not-yet-started tasks from making requests
            # after a synced result has already been found.
            if best_synced[0] is not None:
                return
            try:
                s, p = fn()
            except Exception:
                return
            with result_lock:
                if s and best_synced[0] is None:
                    best_synced[0] = s
                elif p and best_plain[0] is None:
                    best_plain[0] = p

        pool = _cf.ThreadPoolExecutor(max_workers=len(sources))
        try:
            futs = [pool.submit(_run_source, fn) for _, fn in sources]
            # Iterate completions as they arrive; bail out the moment we have a
            # synced result — cancel all pending futures so slow scrapers (Genius,
            # AZLyrics, Letras) never block the return path.
            for fut in _cf.as_completed(futs):
                fut.result()   # re-raise any unexpected exception into this thread
                if best_synced[0] is not None:
                    for f in futs:
                        f.cancel()
                    break
        finally:
            # cancel_futures=True (py3.9+) tells the pool not to start queued
            # tasks; already-running I/O threads finish naturally in the background.
            pool.shutdown(wait=False, cancel_futures=True)

        if best_synced[0] or best_plain[0]:
            self.was_online = True
            self.finished.emit(best_synced[0], best_plain[0])
            return

        self.status.emit('')
        self.finished.emit(None, None)

# ── Panel ─────────────────────────────────────────────────────────────────────
class LyricsPanel(QWidget):
    status_msg = pyqtSignal(str)   # forwarded to status bar
    seek_requested = pyqtSignal(int)          # seek to ms
    lyrics_context = pyqtSignal(str, str, str)  # prev, cur, next

    _LINE_H  = 38
    _LINE_SP = 4

    def __init__(self, player, ctrlbar=None, parent=None):
        super().__init__(parent)
        self._player   = player
        self._ctrlbar  = ctrlbar  # for lyrics_fetch_enabled flag
        self._synced   = []
        self._plain    = ''
        self._cur_idx  = -1
        self._track    = None
        self._thread: QThread  = None
        self._fetcher: LyricsFetcher = None   # keep ref to prevent GC
        self._pending_track = None
        self._fetch_id: int = 0   # incremented on each new fetch; guards stale callbacks

        self.setObjectName('lyrics_panel')
        self.setMinimumWidth(180)
        self.setMaximumWidth(600)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QWidget(); hdr.setFixedHeight(28)
        self._hdr_widget = hdr
        hdr.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 0, 8, 0)
        self._hdr_lbl = QLabel('Lyrics')
        self._hdr_lbl.setStyleSheet(f'color:{FG2};font-size:11px;background:transparent;')
        self._src_lbl = QLabel('')
        self._src_lbl.setStyleSheet(f'color:{FG2};font-size:10px;background:transparent;')
        hl.addWidget(self._hdr_lbl, 1); hl.addWidget(self._src_lbl)
        root.addWidget(hdr)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f'QScrollArea{{border:none;background:transparent;}}'
            f'QScrollBar:vertical{{background:{BG};width:3px;border-radius:1px;}}'
            f'QScrollBar::handle:vertical{{background:{B2};border-radius:1px;min-height:20px;}}'
            f'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}')
        
        # Enable touch scrolling
        QScroller.grabGesture(self._scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        sp = QScrollerProperties()
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor,           0.35)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.MaximumVelocity,              0.8)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.AcceleratingFlickMaximumTime, 0.15)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.DragStartDistance,            0.005)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.VerticalOvershootPolicy,
                           QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy,
                           QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        QScroller.scroller(self._scroll.viewport()).setScrollerProperties(sp)

        self._cont = QWidget()
        self._cont.setStyleSheet('background:transparent;')
        self._cl = QVBoxLayout(self._cont)
        self._cl.setContentsMargins(14, 18, 14, 18)
        self._cl.setSpacing(self._LINE_SP)
        self._scroll.setWidget(self._cont)
        root.addWidget(self._scroll, 1)

        self._lbls: list = []
        # Lyrics position is driven by on_position() called from sig_pos (100 ms).
        # No separate timer needed — avoids a redundant query_position() call per 80 ms.

    # ── public ──────────────────────────────────────────────────────────────

    def set_track(self, track, deferred=False):
        # Increment fetch_id before aborting so any in-flight _done callback is discarded
        self._fetch_id += 1
        self._track = track
        self._synced = []; self._plain = ''; self._cur_idx = -1
        self._abort()
        if track:
            self._hdr_lbl.setText(track.title or '')
            fetch_ok = (self._ctrlbar is None or self._ctrlbar.lyrics_fetch_enabled)
            if deferred:
                self._pending_track = track
                self._show_status('Waiting for focus…')
            else:
                self._pending_track = None
                self._show_status('Searching…')
                self._start(track, fetch_ok)
        else:
            self._pending_track = None
            self._hdr_lbl.setText('Lyrics')
            self._show_status('')

    def on_focus_gained(self):
        """Call when app regains focus — starts deferred fetch if pending."""
        if self._pending_track and self._fetcher is None:
            track = self._pending_track
            self._pending_track = None
            self._show_status('Searching…')
            fetch_ok = (self._ctrlbar is None or self._ctrlbar.lyrics_fetch_enabled)
            self._start(track, fetch_ok)

    def on_position(self, ms: int):
        if self._synced:
            self._highlight(ms)

    def set_accent(self, _acc: str):
        if 0 <= self._cur_idx < len(self._lbls):
            self._style_lbl(self._lbls[self._cur_idx], True)

    def refresh_theme(self):
        """Re-apply palette globals after dark/light switch."""
        self._hdr_widget.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        self._hdr_lbl.setStyleSheet(f'color:{FG2};font-size:11px;background:transparent;')
        self._src_lbl.setStyleSheet(f'color:{FG2};font-size:10px;background:transparent;')
        self._scroll.setStyleSheet(
            f'QScrollArea{{border:none;background:transparent;}}'
            f'QScrollBar:vertical{{background:{BG};width:3px;border-radius:1px;}}'
            f'QScrollBar::handle:vertical{{background:{B2};border-radius:1px;min-height:20px;}}'
            f'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}')
        # Re-style all lyric line labels
        for i, lbl in enumerate(self._lbls):
            self._style_lbl(lbl, i == self._cur_idx)

    # ── internal ────────────────────────────────────────────────────────────

    def _abort(self):
        thread   = self._thread
        self._thread  = None
        self._fetcher = None   # drop ref before quit so GC doesn't race
        if thread is not None:
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(300)
            except RuntimeError:
                pass  # C++ object already deleted

    def _start(self, track, fetch_online: bool = True):
        # Capture the generation id set by set_track() — any in-flight callback
        # with an older id will be discarded by the stale-guard in _done().
        my_id = self._fetch_id
        thread  = QThread(self)
        fetcher = LyricsFetcher(track, fetch_online=fetch_online)
        fetcher.moveToThread(thread)
        thread.started.connect(fetcher.run)
        # Wrap _done with the current fetch_id so stale callbacks are ignored
        fetcher.finished.connect(lambda s, p, fid=my_id: self._done(s, p, fid))
        fetcher.finished.connect(thread.quit)
        fetcher.status.connect(self.status_msg)   # forward to status bar
        thread.finished.connect(thread.deleteLater)
        self._thread  = thread
        self._fetcher = fetcher   # prevent GC!
        thread.start()

    def _done(self, synced, plain, fetch_id: int = -1):
        # Ignore callbacks from previous fetch cycles (stale results)
        if fetch_id != self._fetch_id:
            return
        fetcher = self._fetcher; self._fetcher = None
        if self._track is None: return
        if synced:
            self._synced = synced
            self._src_lbl.setText('synced')
            self._build_synced()
            # Jump to current playback position immediately
            try:
                ok, p = self._player._pipe.query_position(Gst.Format.TIME)
                if ok: self._highlight(p // Gst.MSECOND)
            except Exception:
                pass
        elif plain:
            self._plain = plain
            self._src_lbl.setText('')
            self._build_plain()
        else:
            fetch_off = self._ctrlbar and not self._ctrlbar.lyrics_fetch_enabled
            msg = 'File does not contain lyrics.' if fetch_off else 'Lyrics not found.'
            self._show_status(msg)
            self._src_lbl.setText('')
            return
        # Embed into file if fetched from network (fetcher flag) and not already embedded
        if fetcher and fetcher.was_online and self._track:
            fp = self._track.filepath
            threading.Thread(
                target=embed_lyrics, args=(fp, synced, plain or ''),
                daemon=True).start()

    def _clear(self):
        while self._cl.count():
            it = self._cl.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        self._lbls = []
        self._synced_ts = None   # invalidate bisect index

    def _show_status(self, msg):
        self._clear()
        if not msg: return
        lbl = QLabel(msg)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f'color:{FG2};font-size:13px;background:transparent;')
        self._cl.addStretch(); self._cl.addWidget(lbl); self._cl.addStretch()

    def _style_lbl(self, lbl, active: bool):
        if active:
            lbl.setStyleSheet(
                f'color:{ACC};font-size:16px;font-weight:600;'
                f'padding:0 2px;background:transparent;')
        else:
            lbl.setStyleSheet(
                f'color:{FG2};font-size:14px;padding:0 2px;background:transparent;')

    def _build_synced(self):
        self._clear()
        for ms, txt in self._synced:
            lbl = ClickableLyricLine(txt if txt else '·', ms)
            lbl.setWordWrap(True)
            lbl.setFixedHeight(self._LINE_H)
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            self._style_lbl(lbl, False)
            lbl.clicked.connect(self.seek_requested)
            self._lbls.append(lbl)
            self._cl.addWidget(lbl)
        self._cl.addStretch()
        # Pre-build sorted timestamp list for O(log N) binary search in _highlight
        self._synced_ts = [t for t, _ in self._synced]

    def _build_plain(self):
        self._clear()
        lbl = QLabel(self._plain)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        lbl.setStyleSheet(
            f'color:{FG2};font-size:14px;line-height:1.7;background:transparent;')
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._cl.addWidget(lbl); self._cl.addStretch()

    def _highlight(self, ms: int):
        if not self._synced or not self._lbls: return
        # O(log N) binary search — replaces O(N) linear scan called every 250 ms
        ts = getattr(self, '_synced_ts', None)
        if ts is None:
            return
        pos = bisect.bisect_right(ts, ms) - 1
        idx = max(0, pos)
        if idx == self._cur_idx: return
        if 0 <= self._cur_idx < len(self._lbls):
            self._style_lbl(self._lbls[self._cur_idx], False)
        self._cur_idx = idx
        self._style_lbl(self._lbls[idx], True)
        prev_t = self._synced[idx-1][1] if idx > 0 else ''
        cur_t  = self._synced[idx][1]
        nxt_t  = self._synced[idx+1][1] if idx < len(self._synced)-1 else ''
        self.lyrics_context.emit(prev_t, cur_t, nxt_t)
        # Stop any previous scroll animation before starting a new one
        if hasattr(self, '_scroll_anim') and self._scroll_anim is not None:
            self._scroll_anim.stop()
            self._scroll_anim = None
        step   = self._LINE_H + self._LINE_SP
        target = idx * step - self._scroll.height() // 2 + self._LINE_H // 2
        target = max(0, target)
        bar = self._scroll.verticalScrollBar()
        anim = QPropertyAnimation(bar, b'value', self)
        anim.setDuration(300)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        self._scroll_anim = anim
        anim.finished.connect(lambda: setattr(self, '_scroll_anim', None))
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

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
        self._hidden_by_outside = False
        self._hide_timestamp_ms: int = 0
        self._enabled = True
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
        main.setContentsMargins(16, 10, 16, 12)
        main.setSpacing(7)

        hdr = QLabel('PARAMETRIC EQ'); hdr.setObjectName('popup_title')
        main.addWidget(hdr)

        # Profile management
        prof_layout = QHBoxLayout()
        prof_label = QLabel('Profile:')
        prof_layout.addWidget(prof_label)

        self._NEW = '＋ New'   # sentinel — always first item
        self._profile_combo = TouchComboBox()
        self._profile_combo.setEditable(True)
        self._profile_combo.setMinimumWidth(150)
        self._profile_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._profile_combo.setCompleter(None)   # no autocomplete / no filter while typing
        self._profile_combo.setStyleSheet(
            f'QComboBox {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:6px; padding:4px 8px 4px 8px; min-height:30px; }}'
            f'QComboBox:focus {{ border-color:{ACC}; }}'
            f'QComboBox::drop-down {{ width:44px; border-left:1px solid {B2};'
            f' background:{BG2}; border-radius:0 6px 6px 0; }}'
            f'QComboBox::down-arrow {{ width:16px; height:16px; }}'
            f'QComboBox QAbstractItemView {{ background:{BG3}; color:{FG};'
            f' selection-background-color:{SEL}; border:1px solid {B2}; }}'
            f'QComboBox QAbstractItemView::item {{ min-height:35px; padding:0 8px; }}')
        if self._profile_combo.lineEdit():
            le = self._profile_combo.lineEdit()
            le.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
            le.setPlaceholderText('Profile name…')
        # Force item height via the popup list viewf
        combo_view = self._profile_combo.view()
        if combo_view:
            combo_view.setUniformItemSizes(True)
            combo_view.setSpacing(0)
        self._profile_combo.addItem(self._NEW)  # always first
        # ONLY load/react when user explicitly selects from dropdown
        self._profile_combo.activated.connect(self._on_profile_activated)
        prof_layout.addWidget(self._profile_combo)

        self._btn_save = QPushButton('Save')
        self._btn_save.clicked.connect(self._save_profile)
        self._btn_del = QPushButton('Delete')
        self._btn_del.clicked.connect(self._delete_profile)
        prof_layout.addWidget(self._btn_save)
        prof_layout.addWidget(self._btn_del)
        self._enable_sw = ToggleSwitch('EQ')
        self._enable_sw.setChecked(True)
        self._enable_sw.toggled.connect(self._on_enable_toggled)
        prof_layout.addWidget(self._enable_sw)
        self._btn_default = QPushButton('Set Default')
        self._btn_default.clicked.connect(self._set_as_default)
        prof_layout.addWidget(self._btn_default)
        prof_layout.addStretch()
        main.addLayout(prof_layout)

        # Frequency response graph
        self._graph = EQGraph(self)
        self._graph.setFixedHeight(200)
        main.addWidget(self._graph)

        # Band table
        table_label = QLabel('Bands')
        table_label.setObjectName('setting_lbl')
        main.addWidget(table_label)

        self._band_table = QTableWidget(0, 3)
        self._band_table.setHorizontalHeaderLabels(['Frequency', 'Gain', 'Q', ''])
        # Set column widths: last column fixed 40px, others stretch
        self._band_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._band_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._band_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._band_table.verticalHeader().setVisible(False)
        self._band_table.verticalHeader().setDefaultSectionSize(46)
        self._band_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._band_table.setMinimumHeight(240)
        self._band_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        QScroller.grabGesture(self._band_table.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        _apply_scroller_properties(self._band_table.viewport())
        main.addWidget(self._band_table)

        # Add/Remove buttons
        btn_row = QHBoxLayout()
        self._btn_add = QPushButton('+ Add Band')
        self._btn_add.clicked.connect(self._add_band)
        self._btn_remove = QPushButton('- Remove')
        self._btn_remove.clicked.connect(self._remove_selected_band)
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_remove)
        btn_row.addStretch()
        main.addLayout(btn_row)

        self.setFixedWidth(960)
        self.setMinimumHeight(640)
        self.adjustSize()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QBrush(QColor(BG)))
        p.setPen(QPen(QColor(B2), 1.0))
        p.drawRoundedRect(r, 12, 12)
        p.end()

    def _on_enable_toggled(self, on):
        self._enabled = on
        self._graph.set_enabled(on)
        self._apply_timer.start()  # apply after toggle


    def _add_band(self):
        if len(self._bands) >= MAX_EQ_BANDS:
            self._btn_add.setText(f'Max {MAX_EQ_BANDS} bands')
            self._btn_add.setEnabled(False)
            def _restore():
                self._btn_add.setText('+ Add Band')
                self._btn_add.setEnabled(True)
            QTimer.singleShot(2000, _restore)
            return
        # Default values: 1000 Hz, 0 dB, Q=1.0
        self._bands.append((1000.0, 0.0, 1.0))
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
        for i, (f, g, q) in enumerate(self._bands):
            # Frequency slider cell
            freq_cell = EQSliderCell('freq', EQ_FREQ_MIN, EQ_FREQ_MAX, f, i)
            freq_cell.valueChanged.connect(self._on_slider_changed)
            self._band_table.setCellWidget(i, 0, freq_cell)

            # Gain slider cell
            gain_cell = EQSliderCell('gain', EQ_GAIN_MIN, EQ_GAIN_MAX, g, i)
            gain_cell.valueChanged.connect(self._on_slider_changed)
            self._band_table.setCellWidget(i, 1, gain_cell)

            # Q slider cell
            q_cell = EQSliderCell('q', EQ_Q_MIN, EQ_Q_MAX, q, i)
            q_cell.valueChanged.connect(self._on_slider_changed)
            self._band_table.setCellWidget(i, 2, q_cell)

    def _on_slider_changed(self, band_idx, param, new_val):
        """Update the band in self._bands."""
        if band_idx >= len(self._bands):
            return
        f, g, q = self._bands[band_idx]
        if param == 'freq':
            f = new_val
        elif param == 'gain':
            g = new_val
        elif param == 'q':
            q = new_val
        self._bands[band_idx] = (f, g, q)
        # Update graph immediately
        self._update_graph()
        # Schedule apply after a short delay
        self._apply_timer.start()

    def _update_graph(self):
        self._graph.set_bands(self._bands)

    def _apply(self):
        """Emit eq_changed so the player updates."""
        self.eq_changed.emit(self._bands, self._enabled)

    def _on_profile_activated(self, index):
        """Called only when user explicitly picks an item from the dropdown."""
        name = self._profile_combo.itemText(index)
        if name == self._NEW:
            # Start fresh: clear bands, clear name field so user can type new name
            self._bands = []
            self._current_profile = ''
            self._profile_combo.lineEdit().clear()
            self._refresh_table()
            self._update_graph()
            self._apply_timer.start()
        elif name and name in self._profiles:
            self._bands = [list(b) for b in self._profiles[name]]
            self._refresh_table()
            self._update_graph()
            self._current_profile = name
            self._apply_timer.start()


    def _save_profile(self):
        name = self._profile_combo.currentText().strip()
        if not name or name == self._NEW:
            QMessageBox.warning(self, 'Error', 'Profile name cannot be empty.')
            return
        self._profiles[name] = [b for b in self._bands]
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
        self._default_bands = [b for b in self._bands]
        self._default_enabled = self._enabled
        self._default_profile_name = self._current_profile
        QToolTip.showText(self.mapToGlobal(QPoint(0,0)), 'Saved as default')

    # Public methods to set/get state
    def set_bands(self, bands, enabled, name=''):
        self._bands = [list(b) for b in bands]
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
        self._profiles = profiles
        self._profile_combo.clear()
        self._profile_combo.addItem(self._NEW)  # always first
        for name in sorted(profiles.keys()):
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
        """Close EQ popup on click outside it (within the application)."""
        if (self.isVisible() and
                e.type() == QEvent.Type.MouseButtonPress and
                QApplication.activePopupWidget() is None and
                obj is not self and
                not (isinstance(obj, QWidget) and self.isAncestorOf(obj)) and
                not self.rect().contains(
                    self.mapFromGlobal(e.globalPosition().toPoint()))):
            self.hide()
            self._hidden_by_outside = True
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

class EQGraph(QWidget):
    """Widget to draw frequency response of the current EQ bands."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bands = []
        self._enabled = True
        self._eq_graph_cache = None   # invalidated by set_bands(); checked in paintEvent
        self.setMinimumHeight(100)

    def set_bands(self, bands):
        self._bands = bands
        self._eq_graph_cache = None  # invalidate numpy cache
        self.update()

    def set_enabled(self, en):
        self._enabled = en
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if w < 10 or h < 10:
            return

        # Background
        p.fillRect(self.rect(), QColor(BG))

        # Draw grid
        p.setPen(QPen(QColor(BORD), 1))
        # Horizontal lines (every 2 dB)
        for db in range(-10, 11, 2):
            y = h/2 - (db * (h/2) / EQ_GAIN_MAX_GRAPH)
            if 0 <= y <= h:
                p.drawLine(0, int(y), w, int(y))
        # Vertical lines (decades)
        for decade in range(1, 5):
            freq = 10**decade  # 10,100,1000,10000
            x = w * (math.log10(freq) - math.log10(20)) / (math.log10(22000)-math.log10(20))
            if 0 <= x <= w:
                p.drawLine(int(x), 0, int(x), h)

        if not self._enabled:
            # Draw bypass text
            p.setPen(QColor(FG2))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'EQ disabled')
            return

        if not self._bands:
            return

        # Numpy-based curve computation — cache per-widget-size + bands state
        # to avoid recomputing on every paintEvent when nothing changed.
        cache_key = (w, tuple(tuple(b) for b in self._bands))
        cached = self._eq_graph_cache
        if cached is None or cached[0] != cache_key:
            steps = w
            xs_np = _np.arange(steps, dtype=_np.float32)
            # Log-spaced frequencies across [20, 22000] Hz
            freqs_np = (20.0 * (22000.0 / 20.0) ** (xs_np / (steps - 1))).astype(_np.float32)

            # Per-band gains: shape (n_bands, steps)
            n_bands = len(self._bands)
            band_gains_np = _np.zeros((n_bands, steps), dtype=_np.float32)
            for idx, (f0, g, q) in enumerate(self._bands):
                if g == 0.0 or f0 <= 0.0:
                    continue
                bw = 1.0 / max(q, 0.01)
                octave_diff = _np.log2(freqs_np / f0)
                weight = _np.exp(-(octave_diff / bw) ** 2)
                band_gains_np[idx] = g * weight

            total_gains_np = band_gains_np.sum(axis=0)
            self._eq_graph_cache = (cache_key, xs_np, band_gains_np, total_gains_np)
        else:
            _, xs_np, band_gains_np, total_gains_np = cached

        half_h = h / 2.0
        scale  = half_h / EQ_GAIN_MAX_GRAPH

        # Draw each band's curve — PyQt6 drawPolyline requires QPolygonF
        n_bands = len(self._bands)
        for idx in range(n_bands):
            gains = band_gains_np[idx]
            if gains.max() == 0.0:
                continue
            hue   = (idx * 360 / max(1, n_bands)) % 360
            color = QColor.fromHsvF(hue / 360.0, 0.8, 1.0, 0.4)
            pen   = QPen(color, 1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            ys = half_h - gains * scale
            poly = QPolygonF([QPointF(float(xs_np[i]), float(ys[i])) for i in range(len(xs_np))])
            p.drawPolyline(poly)

        # Draw total curve
        total_clipped = _np.clip(total_gains_np, -EQ_GAIN_MAX_GRAPH, EQ_GAIN_MAX_GRAPH)
        ys_total = half_h - total_clipped * scale
        poly_total = QPolygonF([QPointF(float(xs_np[i]), float(ys_total[i])) for i in range(len(xs_np))])
        p.setPen(QPen(QColor(FG), 2))
        p.drawPolyline(poly_total)

def _fmt_ms(ms: int) -> str:
    t = ms // 1000; h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'

# ══════════════════════════════════════════════════════════════════════════════
#  Blackout overlay
# ══════════════════════════════════════════════════════════════════════════════
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
        self._album  = ''
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
        self._lyr_prev = prev; self._lyr_cur = cur; self._lyr_next = nxt
        if self.isVisible() and self._ov_lyrics: self._container.update()

    # ── dismiss ───────────────────────────────────────────────────────────────
    def _dismiss(self):
        self._cycle_timer.stop(); self._clock_timer.stop()
        self._anim.stop()
        self.hide()
        # Resume ControlBar viz rendering now that overlay is gone
        if self._ctrlbar_ref is not None:
            self._ctrlbar_ref.set_overlay_open(False)
        # Restart idle countdown after overlay is dismissed
        if self._ctrlbar_ref is not None:
            self._ctrlbar_ref._reset_idle_timer()

    def mousePressEvent(self, e): self._dismiss()
    def keyPressEvent(self, e):   self._dismiss()

    def event(self, e):
        if e.type() in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate,
                        QEvent.Type.TouchEnd):
            self._dismiss(); return True
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
    # We override the container's paintEvent via an event filter
    def _paint_info(self, p: QPainter):
        sc = getattr(self, '_scale', 1.0)
        # Scale everything via a painter transform.  The container widget itself
        # is already sized to base_w*sc × base_h*sc (see _resize_container), so
        # we simply scale the coordinate system and draw at the original base sizes.
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

        RED  = QColor(ACC)
        GREY = QColor(BG3)
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
        dark = QColor(ACC); dark.setAlpha(55)
        p.setBrush(QBrush(dark))
        p.drawRoundedRect(QRectF(10, BAR_Y, BAR_W, BAR_H), 2, 2)
        if frac > 0:
            p.setBrush(QBrush(RED))
            p.drawRoundedRect(QRectF(10, BAR_Y, BAR_W * frac, BAR_H), 2, 2)

        # ── Overlay VIZ (docked to bottom of progress bar, bars hang down) ──
        vd = self._viz_data
        if self._ov_viz and vd is not None and len(vd) > 0:
            viz_y = BAR_Y + BAR_H
            n_v  = len(vd)
            bw_v = BAR_W / max(1, n_v)
            bw_draw = max(1.0, bw_v)
            p.setPen(Qt.PenStyle.NoPen)
            bar_col = QColor(ACC); bar_col.setAlpha(200)
            p.setBrush(QBrush(bar_col))
            p.setClipRect(QRectF(10, viz_y, BAR_W, VIZ_H))
            # Iterate with explicit float() so both ndarray elements and plain
            # floats are handled safely without triggering ndarray truth-value errors.
            x = 10.0
            for norm in vd:
                h = float(norm) * VIZ_H
                if h >= 0.01 * VIZ_H:
                    p.drawRect(QRectF(x, viz_y, bw_draw, h))
                x += bw_v
            p.setClipping(False)

        if sc != 1.0:
            p.restore()

    def showEvent(self, e):
        super().showEvent(e)
        # Install event filter on container to intercept paintEvent
        self._container.installEventFilter(self)

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
#  Data model (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Track:
    filepath:    str
    title:       str   = ''
    artist:      str   = ''
    album:       str   = ''
    duration:    float = 0.0
    sample_rate: int   = 0
    bit_depth:   int   = 0
    file_type:   str   = ''

    def dur_str(self):
        t = int(self.duration); h, r = divmod(t, 3600); m, s = divmod(r, 60)
        return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'

    def sr_str(self):
        if not self.sample_rate: return ''
        k = self.sample_rate/1000
        return f'{k:.1f} kHz' if k % 1 else f'{int(k)} kHz'

    def bd_str(self): return f'{self.bit_depth}-bit' if self.bit_depth else ''

    def sort_key(self):
        return (self.artist.lower() or '\xff', self.album.lower() or '\xff',
                self.title.lower() or '\xff')

def _tag(tags, *keys):
    for k in keys:
        v = tags.get(k)
        if v: return str(v[0]) if isinstance(v, list) else str(v)
    return ''

def _vtag(tags, *keys):
    """Case-insensitive tag lookup for Vorbis comment tags (FLAC/OGG/OPUS).
    Avoids rebuilding a lowercase dict by iterating tags directly.
    For the small tag sets typical of audio files this is faster.
    """
    for k in keys:
        kl = k.lower()
        for tk, tv in tags.items():
            if tk.lower() == kl:
                return str(tv[0]) if isinstance(tv, list) else str(tv)
    return ''

def _open_audio(fp: str):
    """Open an audio file with mutagen, trying format-specific classes as fallback.
    Returns a mutagen File object or None."""
    af = MutagenFile(fp, easy=False)
    if af is not None:
        return af
    ext = Path(fp).suffix.lower()
    try:
        if ext == '.opus':
            from mutagen.oggopus import OggOpus;    return OggOpus(fp)
        if ext == '.ogg':
            from mutagen.oggvorbis import OggVorbis; return OggVorbis(fp)
        if ext == '.flac':
            from mutagen.flac import FLAC;           return FLAC(fp)
        if ext == '.mp3':
            from mutagen.mp3 import MP3;             return MP3(fp)
        if ext in ('.m4a', '.aac'):
            from mutagen.mp4 import MP4;             return MP4(fp)
        if ext in ('.wav', '.wave'):
            from mutagen.wave import WAVE;           return WAVE(fp)
        if ext in ('.aiff', '.aif'):
            from mutagen.aiff import AIFF;           return AIFF(fp)
    except Exception:
        pass
    return None

def read_metadata(fp: str) -> Track:
    p = Path(fp); ext = p.suffix.lower()
    tr = Track(filepath=fp, title=p.stem, file_type=ext.lstrip('.').upper())
    try:
        af = _open_audio(fp)
        if af is None: return tr
        i = af.info
        tr.duration    = getattr(i, 'length', 0.0)
        tr.sample_rate = getattr(i, 'sample_rate', 0)
        for a in ('bits_per_sample', 'bits_per_raw_sample'):
            v = getattr(i, a, 0)
            if v: tr.bit_depth = v; break
        tg = af.tags
        if tg is None: return tr
        if ext == '.mp3':
            tr.title  = _tag(tg, 'TIT2') or tr.title
            tr.artist = _tag(tg, 'TPE1', 'TPE2'); tr.album = _tag(tg, 'TALB')
        elif ext in ('.flac', '.opus', '.ogg'):
            tr.title  = _vtag(tg, 'title') or tr.title
            tr.artist = _vtag(tg, 'artist', 'albumartist')
            tr.album  = _vtag(tg, 'album')
        elif ext in ('.m4a', '.aac'):
            tr.title  = _tag(tg, '\xa9nam') or tr.title
            tr.artist = _tag(tg, '\xa9ART', 'aART'); tr.album = _tag(tg, '\xa9alb')
        else:
            tr.title  = _tag(tg, 'title',  'TITLE') or tr.title
            tr.artist = _tag(tg, 'artist', 'ARTIST'); tr.album = _tag(tg, 'album', 'ALBUM')
    except Exception:
        pass
    return tr

# ── Cover art ─────────────────────────────────────────────────────────────────
_cover_cache: dict = {}   # (fp, size, radius) → QPixmap  (insertion-ordered, Python 3.7+)
_COVER_SENTINEL = object()  # distinguishes cache miss from cached None
_COVER_CACHE_MAX = 8000     # max entries before trimming (each ~10-70 KB on screen)

def _trim_cover_cache() -> None:
    """Evict oldest quarter of entries when cache exceeds _COVER_CACHE_MAX.

    Python dicts are insertion-ordered (3.7+).  Trimming from the front evicts
    the least-recently-inserted entries.  Good enough for a cover cache where
    recency roughly correlates with 'currently visible in gallery/table'.
    """
    overflow = len(_cover_cache) - _COVER_CACHE_MAX
    if overflow > 0:
        trim = overflow + _COVER_CACHE_MAX // 4   # remove 25% extra to avoid thrash
        for key in list(_cover_cache.keys())[:trim]:
            _cover_cache.pop(key, None)

def extract_cover_bytes(fp: str) -> Optional[bytes]:
    """Return raw cover bytes from embedded tags, or None."""
    try:
        ext = Path(fp).suffix.lower()
        af = _open_audio(fp)
        if af is None: return None
        if ext == '.mp3':
            from mutagen.id3 import APIC
            for tag in af.tags.values():
                if isinstance(tag, APIC): return tag.data
        elif ext == '.flac':
            if hasattr(af, 'pictures') and af.pictures:
                return af.pictures[0].data
        elif ext in ('.m4a', '.aac'):
            covr = af.tags.get('covr')
            if covr: return bytes(covr[0])
        elif ext in ('.ogg', '.opus'):
            from mutagen.flac import Picture
            pics = af.tags.get('metadata_block_picture', [])
            if pics:
                return Picture(base64.b64decode(pics[0])).data
    except Exception:
        pass
    return None

def _rounded_pixmap(pm: QPixmap, size: int, radius: int) -> QPixmap:
    """Scale pm to size×size with rounded corners."""
    pm = pm.scaled(size, size,
                   Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                   Qt.TransformationMode.SmoothTransformation)
    # Crop to exact square from centre
    x = (pm.width()  - size) // 2
    y = (pm.height() - size) // 2
    pm = pm.copy(x, y, size, size)
    # Apply rounded mask
    out = QPixmap(size, size); out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(pm)); p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, radius, radius)
    p.end()
    return out

def _default_cover_disk_path(acc: str, size: int, radius: int) -> Path:
    safe = acc.lstrip('#')
    return CONFIG_PATH.parent / f'default_cover_{safe}_{size}_{radius}.jpg'

_default_cover_mem_cache: dict = {}   # (acc, size, radius) -> QPixmap

def draw_default_cover(size: int, radius: int) -> QPixmap:
    mem_key = (ACC, size, radius)
    if mem_key in _default_cover_mem_cache:
        return _default_cover_mem_cache[mem_key]
    # Check disk cache first
    disk = _default_cover_disk_path(ACC, size, radius)
    if disk.exists():
        pm = QPixmap()
        if pm.load(str(disk)):
            _default_cover_mem_cache[mem_key] = pm
            return pm
    # Render
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(BG)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, radius, radius)
    p.setPen(QPen(QColor(ACC), 1))
    font = p.font()
    font.setPixelSize(int(size * 0.67))
    font.setFamily('Segoe UI Symbol, FreeSerif, Symbola, Arial Unicode MS')
    p.setFont(font)
    p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, '𝄞')
    p.end()
    _default_cover_mem_cache[mem_key] = pm
    # Save to disk cache
    try:
        disk.parent.mkdir(parents=True, exist_ok=True)
        pm.save(str(disk), 'JPEG', 90)
    except Exception:
        pass
    return pm

_COVER_DISK_DIR  = CONFIG_PATH.parent / 'covers'
_cover_fetch_on  = True   # module-level flag — updated by ControlBar
_cover_locked_set: set = set()   # filepaths that must not auto-fetch
_COVER_JPEG_QUALITY = 80

# Pre-create cover cache dir; non-fatal if it fails (e.g. read-only Flatpak sandbox)
try:
    _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

def _cover_disk_key(fp: str, size: int, radius: int) -> str:
    """Hash of filepath+mtime to detect stale covers."""
    try:
        mtime = str(os.path.getmtime(fp))
    except Exception:
        mtime = '0'
    return hashlib.sha1(f'{fp}:{mtime}:{size}:{radius}'.encode()).hexdigest()

def get_cover_pixmap(fp: str, size: int = 48, radius: int = 4) -> Optional[QPixmap]:
    """Return cached rounded QPixmap (memory-only, non-blocking).

    Cache hits (non-None) return immediately.
    Cache misses schedule an async loader — caller never blocks on disk/mutagen.
    The async loader writes the QPixmap into _cover_cache and emits cover_loaded
    so the gallery can repaint just the affected cards.
    """
    key = (fp, size, radius)
    cached = _cover_cache.get(key, _COVER_SENTINEL)
    if cached is not _COVER_SENTINEL:
        return cached  # may be a valid QPixmap; None is never stored here

    # Schedule async load (deduplicates by key internally)
    _ensure_async_cover_loader().request(fp, size, radius)
    return None

# ── Synchronous cover loader (used outside the paint path) ────────────────────
def get_cover_pixmap_sync(fp: str, size: int = 48, radius: int = 4) -> Optional[QPixmap]:
    """Blocking version — only call from worker threads or startup code."""
    key = (fp, size, radius)
    if key in _cover_cache:
        return _cover_cache[key]

    dkey = _cover_disk_key(fp, size, radius)
    disk_path = _COVER_DISK_DIR / f'{dkey}.jpg'
    if disk_path.exists():
        pm = QPixmap()
        if pm.load(str(disk_path)):
            _cover_cache[key] = pm
            _trim_cover_cache()
            return pm

    data = extract_cover_bytes(fp)
    if data:
        raw = QPixmap()
        if raw.loadFromData(data):
            pm = _rounded_pixmap(raw, size, radius)
            _cover_cache[key] = pm
            _trim_cover_cache()
            try:
                _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
                pm.save(str(disk_path), 'JPEG', _COVER_JPEG_QUALITY)
            except Exception:
                pass
            return pm

    if _cover_fetch_on and fp not in _cover_locked_set:
        return None
    default = draw_default_cover(size, radius)
    _cover_cache[key] = default
    return default

class _CoverTask(QRunnable):
    """One cover-load task. Reads disk/mutagen on a pool thread, posts result
    back to the main thread via a queued signal on the loader QObject."""
    def __init__(self, loader, fp, size, radius):
        super().__init__()
        self.setAutoDelete(True)
        self._loader = loader
        self._fp = fp; self._size = size; self._radius = radius

    def run(self):
        fp, size, radius = self._fp, self._size, self._radius
        try:
            dkey = _cover_disk_key(fp, size, radius)
            disk_path = _COVER_DISK_DIR / f'{dkey}.jpg'

            # L2: disk cache — already scaled + rounded, just read raw bytes
            if disk_path.exists():
                try:
                    with open(str(disk_path), 'rb') as f:
                        raw = f.read()
                    if raw:
                        # Post bytes directly — skip scale/crop/encode entirely
                        self._loader._raw_ready.emit(fp, size, radius, raw, '')
                        return
                except Exception:
                    pass  # fall through to full load

            # L3: embedded cover — full scale + encode path
            data = extract_cover_bytes(fp)
            if data:
                img = QImage()
                img.loadFromData(data)
                if not img.isNull():
                    self._loader._post_image(fp, size, radius, img, str(disk_path))
                    return

            # Nothing found
            self._loader._post_miss(fp, size, radius)
        except Exception:
            self._loader._post_miss(fp, size, radius)

class AsyncCoverLoader(QObject):
    """
    Non-blocking cover loader for the gallery paint path.
    Uses QThreadPool so tasks run on pool threads managed by Qt.
    Results are delivered back to the main thread via a queued signal
    (Qt auto-selects queued connection when emitter and receiver are in
    different threads).
    """
    # emitted on main thread after QPixmap is built
    cover_loaded = pyqtSignal(str, int, int)   # fp, size, radius
    # internal signal — worker posts raw bytes, main thread builds QPixmap
    _raw_ready   = pyqtSignal(str, int, int, bytes, str)   # fp,sz,rad,data,disk_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._in_flight: set = set()
        self._no_embed:  set = set()
        self._lock = threading.Lock()
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max(2, self._pool.maxThreadCount()))
        # Connect internal signal with queued connection → always runs on main thread
        self._raw_ready.connect(self._on_raw_ready, Qt.ConnectionType.QueuedConnection)

    def request(self, fp: str, size: int, radius: int):
        key = (fp, size, radius)
        with self._lock:
            if key in _cover_cache or key in self._in_flight or fp in self._no_embed:
                return
            self._in_flight.add(key)
        task = _CoverTask(self, fp, size, radius)
        self._pool.start(task)

    # called from worker thread — emit queued signal to marshal to main thread
    def _post_image(self, fp, size, radius, img: QImage, disk_path: str):
        # Scale + crop on worker thread (QImage pixel ops are thread-safe in Qt6)
        img = img.scaled(size, size,
                         Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.SmoothTransformation)
        cx = (img.width()  - size) // 2
        cy = (img.height() - size) // 2
        img = img.copy(cx, cy, size, size)
        # Encode to JPEG bytes on the worker thread — smaller payload over the
        # queued signal and faster decode on the main thread than RGBA raw.
        buf    = QByteArray()
        buf_io = QBuffer(buf)
        buf_io.open(QIODeviceBase.OpenModeFlag.WriteOnly)
        img.save(buf_io, 'JPEG', _COVER_JPEG_QUALITY)
        buf_io.close()
        self._raw_ready.emit(fp, size, radius, bytes(buf), disk_path or '')

    def _post_miss(self, fp, size, radius):
        with self._lock:
            self._no_embed.add(fp)
            self._in_flight.discard((fp, size, radius))

    # ── main thread (called via queued connection) ────────────────────────────
    def _on_raw_ready(self, fp: str, size: int, radius: int, data: bytes, disk_path: str):
        key = (fp, size, radius)
        with self._lock:
            self._in_flight.discard(key)
        if not data:
            with self._lock:
                self._no_embed.add(fp)
            return
        # Decode JPEG back to QPixmap (main thread — safe for QPainter)
        pm_raw = QPixmap()
        if not pm_raw.loadFromData(data, 'JPEG') or pm_raw.isNull():
            with self._lock:
                self._no_embed.add(fp)
            return
        # Apply rounded corners
        out = QPixmap(pm_raw.size()); out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(pm_raw)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, pm_raw.width(), pm_raw.height(), radius, radius)
        p.end()
        _cover_cache[key] = out
        _trim_cover_cache()  # evict oldest entries when cache grows large
        # Disk cache: write the already-encoded JPEG bytes directly — no re-encode needed
        if disk_path:
            try:
                _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
                with open(disk_path, 'wb') as f:
                    f.write(data)
            except Exception:
                pass
        self.cover_loaded.emit(fp, size, radius)

# Module-level singleton — created once, shared by all gallery views
_async_cover_loader: Optional['AsyncCoverLoader'] = None

def _ensure_async_cover_loader() -> 'AsyncCoverLoader':
    global _async_cover_loader
    if _async_cover_loader is None:
        _async_cover_loader = AsyncCoverLoader()
    return _async_cover_loader

def _clear_cover_disk_cache():
    """Wipe disk + memory cover caches."""
    _cover_cache.clear()
    try:
        if _COVER_DISK_DIR.exists():
            shutil.rmtree(_COVER_DISK_DIR)
    except Exception:
        pass

class _BaseFetchPopup(QDialog):
    """Shared base for CoverFetchPopup, TagFetchPopup, LyricsFetchPopup.

    Subclasses must implement:
        _make_worker()  -> QObject worker with .run(), .progress(int,int,str),
                           .track_done(...), .finished(int,int), .cancel()
        _on_track_done(fp, *args)
    And may override _on_finished(found, total) to customise the result label.
    """

    # Class-level tracking of active workers per popup type (supports multiple concurrent workers)
    _active_workers = {}  # key: popup_type_name, value: list of (instance, worker, thread)

    def __init__(self, tracks: list, title: str, info_text: str, needs_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(300)
        self._tracks   = list(tracks)
        self._thread   = None
        self._worker   = None
        self._running  = False
        self._found    = 0
        self._popup_type = self.__class__.__name__
        # Store background state for restoration
        self._bg_progress = 0
        self._bg_total = needs_count
        self._bg_track_name = ''
        self._bg_log_items = []  # list of (text, ok_flag)
        self._bg_result = ''
        self._worker_id = id(self)  # Unique ID for this instance's worker

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 18, 20, 18)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f'font-size:14px;font-weight:bold;color:{FG};')
        root.addWidget(title_lbl)

        info_lbl = QLabel(info_text)
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(f'color:{FG2};font-size:12px;')
        root.addWidget(info_lbl)

        self._track_lbl = QLabel('')
        self._track_lbl.setStyleSheet(f'color:{FG};font-size:12px;')
        self._track_lbl.setWordWrap(True)
        root.addWidget(self._track_lbl)

        self._progress = QProgressBar()
        self._progress.setRange(0, max(1, needs_count))
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFixedHeight(22)
        self._progress.setStyleSheet(
            f'QProgressBar{{background:{BG3};border:1px solid {B2};border-radius:4px;'
            f'color:{FG};font-size:11px;text-align:center;}}'
            f'QProgressBar::chunk{{background:{ACC};border-radius:3px;}}')
        root.addWidget(self._progress)

        self._log = QListWidget()
        self._log.setFixedHeight(140)
        self._log.setStyleSheet(
            'QListWidget{background:' + BG + ';border:1px solid ' + B2 + ';border-radius:4px;'
            'color:' + FG2 + ';font-size:10px;outline:none;}'
            'QListWidget::item{padding:1px 6px;border:none;}'
            'QListWidget::item:selected{background:transparent;color:' + FG2 + ';}'
        )
        self._log.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        QScroller.grabGesture(self._log.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        _apply_scroller_properties(self._log.viewport())
        root.addWidget(self._log)

        self._result_lbl = QLabel('')
        self._result_lbl.setStyleSheet(f'color:{FG2};font-size:11px;')
        root.addWidget(self._result_lbl)

        btn_row = QHBoxLayout()
        self._btn_start  = QPushButton('Start')
        self._btn_cancel = QPushButton('Cancel')
        self._btn_cancel.setEnabled(False)
        self._btn_close  = QPushButton('Run in Background')
        self._force_cb   = QCheckBox('Force (re-fetch all)')
        self._force_cb.setStyleSheet(f'color:{FG2};font-size:11px;')
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addSpacing(8)
        btn_row.addWidget(self._force_cb)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

        self._btn_start.clicked.connect(self._start)
        self._btn_cancel.clicked.connect(self._cancel)
        self._btn_close.clicked.connect(self._on_close)
        self._force = False   # set just before _make_worker() is called
        
        # Check if there's an existing worker running in background and auto-start
        self._check_and_restore_background()

    def _make_worker(self):
        raise NotImplementedError

    def _on_track_done(self, *args):
        raise NotImplementedError

    def _check_and_restore_background(self):
        """Check if there's an existing worker running in background and auto-restore UI."""
        workers_list = _BaseFetchPopup._active_workers.get(self._popup_type, [])
        if workers_list:
            # Find the most recent worker for this popup type
            old_instance, old_worker, old_thread = workers_list[-1]
            # Restore UI to show the existing running operation with full state
            self._thread = old_thread
            self._worker = old_worker
            self._running = True
            self._btn_start.setEnabled(False)
            self._btn_cancel.setEnabled(True)
            # Restore progress, log, and track info from background state
            self._progress.setValue(old_instance._bg_progress)
            self._track_lbl.setText(f'[{old_instance._bg_progress}/{old_instance._bg_total}]  {old_instance._bg_track_name}')
            # Restore log items
            self._log.clear()
            for text, ok_flag in old_instance._bg_log_items:
                item = QListWidgetItem(text)
                item.setForeground(QColor('#55bb55') if ok_flag else QColor('#bb3333'))
                self._log.addItem(item)
            self._log.scrollToBottom()
            # Restore result label if present
            if old_instance._bg_result:
                self._result_lbl.setText(old_instance._bg_result)
            # Emit progress to main window status bar
            self._emit_status_update()
            # Auto-show the dialog (it may have been hidden) - but don't auto-start since it's already running
            self.show()
            # Connect signals to restore live updates
            self._worker.progress.connect(self._on_progress)
            self._worker.track_done.connect(self._on_track_done)
            self._worker.finished.connect(self._on_finished)

    # ── common implementation ────────────────────────────────────────────────

    def _log_add(self, text: str, ok: bool):
        item = QListWidgetItem(text)
        item.setForeground(QColor('#55bb55') if ok else QColor('#bb3333'))
        self._log.addItem(item)
        self._log.scrollToBottom()
        # Store log item for background restoration
        self._bg_log_items.append((text, ok))

    def _start(self):
        if self._running:
            return
        
        self._running = True
        self._found   = 0
        self._force   = self._force_cb.isChecked()   # subclasses read self._force in _make_worker
        self._log.clear()
        self._progress.setValue(0)
        self._result_lbl.setText('')
        self._btn_start.setEnabled(False)
        self._btn_cancel.setEnabled(True)

        worker = self._make_worker()
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.track_done.connect(self._on_track_done)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(thread.quit)
        self._thread = thread
        self._worker = worker
        # Register this worker as active for this popup type (support multiple concurrent workers)
        if self._popup_type not in _BaseFetchPopup._active_workers:
            _BaseFetchPopup._active_workers[self._popup_type] = []
        _BaseFetchPopup._active_workers[self._popup_type].append((self, worker, thread))
        thread.start()
        # Emit initial status update
        self._emit_status_update()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
        self._btn_cancel.setEnabled(False)
        self._track_lbl.setText('Cancelling…')

    def _on_close(self):
        # Hide the dialog but keep the thread running in background
        self.hide()

    def closeEvent(self, e):
        # Hide instead of closing - keeps thread alive
        self.hide()
        e.ignore()

    def mousePressEvent(self, e):
        # Clicking outside the popup (on the modal backdrop) hides it like "Run in Background"
        if e.button() == Qt.MouseButton.LeftButton:
            # Check if click is outside the dialog's geometry
            if not self.rect().contains(e.pos()):
                self.hide()
                e.ignore()
                return
        super().mousePressEvent(e)

    def _on_progress(self, current: int, total: int, name: str):
        self._progress.setValue(current)
        self._track_lbl.setText(f'[{current}/{total}]  {name}')
        # Store state for background restoration
        self._bg_progress = current
        self._bg_total = total
        self._bg_track_name = name
        # Emit progress to main window status bar
        self._emit_status_update()

    def _on_finished(self, found: int, total: int):
        self._running = False
        # Remove this specific worker from active workers list
        workers_list = _BaseFetchPopup._active_workers.get(self._popup_type, [])
        # Find and remove this worker by identity
        for i, (inst, wk, th) in enumerate(workers_list):
            if inst is self or wk is self._worker:
                workers_list.pop(i)
                break
        # Clean up empty lists
        if not workers_list:
            _BaseFetchPopup._active_workers.pop(self._popup_type, None)
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._track_lbl.setText('Done.')
        self._progress.setValue(total)
        result_msg = self._finished_msg(found, total)
        self._result_lbl.setText(result_msg)
        # Store result for background restoration
        self._bg_result = result_msg
        # Clean up thread references but don't quit (already quit via signal)
        self._thread = None
        self._worker = None
        # Clear status bar message
        self._emit_status_clear()

    def _emit_status_update(self):
        """Emit progress status to main window status bar - shows all concurrent fetches."""
        if self._running and hasattr(self, '_bg_progress') and hasattr(self, '_bg_total'):
            # Determine fetch type label based on popup class
            if isinstance(self, CoverFetchPopup):
                type_label = "Covers"
            elif isinstance(self, TagFetchPopup):
                type_label = "Tags"
            elif isinstance(self, LyricsFetchPopup):
                type_label = "Lyrics"
            else:
                type_label = "Fetch"
            
            msg = f"{type_label}: [{self._bg_progress}/{self._bg_total}] {self._bg_track_name}"
            # Find main window and update status bar
            win = self.parent()
            while win and not isinstance(win, MainWindow):
                win = win.parent()
            if win and hasattr(win, '_status'):
                # Create unique widget key for this specific instance
                widget_key = f"_fetch_widget_{self._worker_id}"
                # Remove old widget if exists
                old_lbl = getattr(win, widget_key, None)
                if old_lbl:
                    old_lbl.deleteLater()
                # Create new permanent widget
                lbl = QLabel(msg)
                lbl.setStyleSheet(f'color:{FG}; font-size:11px; padding: 0 8px;')
                win._status.addPermanentWidget(lbl, 0)
                setattr(win, widget_key, lbl)

    def _emit_status_clear(self):
        """Clear status bar message for this specific fetch instance when finished."""
        # Use unique widget key for this instance
        widget_key = f"_fetch_widget_{self._worker_id}"
        
        win = self.parent()
        while win and not isinstance(win, MainWindow):
            win = win.parent()
        if win:
            old_lbl = getattr(win, widget_key, None)
            if old_lbl:
                old_lbl.deleteLater()
                setattr(win, widget_key, None)

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Processed {found} out of {total}.' 


# ══════════════════════════════════════════════════════════════════════════════
#  Library Cover Fetch Popup
# ══════════════════════════════════════════════════════════════════════════════
class LibraryCoverFetchWorker(QObject):
    """Fetches covers for an entire track list sequentially in a worker thread.
    Emits raw bytes per track so the UI thread builds QPixmap objects."""
    progress    = pyqtSignal(int, int, str)   # current_index, total, track_name
    track_done  = pyqtSignal(str, bytes, bool) # filepath, raw_bytes, found_flag
    finished    = pyqtSignal(int, int)        # found_count, total_count

    def __init__(self, tracks: list, force: bool = False):
        super().__init__()
        self._tracks    = list(tracks)
        self._force     = force
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # In force mode, process all tracks; otherwise skip tracks that already have a cover.
        if self._force:
            needs_fetch = [t for t in self._tracks if t.filepath not in _cover_locked_set]
        else:
            needs_fetch = [t for t in self._tracks
                           if extract_cover_bytes(t.filepath) is None
                           and t.filepath not in _cover_locked_set]
        total = len(needs_fetch)
        found = 0
        done  = 0
        for t in needs_fetch:
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            done += 1
            self.progress.emit(done, total, name)
            data = fetch_cover_online(t.artist or '', t.title or '', t.album or '')
            if data:
                found += 1
                self.track_done.emit(t.filepath, data, True)
            else:
                self.track_done.emit(t.filepath, b'', False)
        self.finished.emit(found, total)

class CoverFetchPopup(_BaseFetchPopup):
    """Modal dialog that fetches covers for tracks missing a cover."""

    def __init__(self, tracks: list, table_pages: list, ctrlbar, parent=None):
        self._pages   = table_pages
        self._ctrlbar = ctrlbar
        needs = [t for t in tracks
                 if extract_cover_bytes(t.filepath) is None
                 and t.filepath not in _cover_locked_set]
        info = (f'<b>{len(needs)}</b> tracks need a cover '
                f'(out of {len(tracks)} total — tracks with embedded covers skipped).')
        super().__init__(tracks, 'Fetch Covers', info, len(needs), parent)
        self._needs = needs

    def _make_worker(self):
        return LibraryCoverFetchWorker(self._tracks, force=self._force)

    def set_tracks(self, tracks: list):
        self._tracks = list(tracks)
        self._needs  = [t for t in tracks
                        if extract_cover_bytes(t.filepath) is None
                        and t.filepath not in _cover_locked_set]
        self._progress.setRange(0, max(1, len(self._needs)))

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Found covers for {found} out of {total} tracks.'

    def _on_track_done(self, fp: str, data: bytes, found: bool):
        name = Path(fp).stem
        if not found:
            self._log_add(f'FAIL  {name}', False)
            return
        self._log_add(f'OK    {name}', True)
        for size, radius in [(28, 4), (64, 8)]:
            key = (fp, size, radius)
            raw = QPixmap()
            if raw.loadFromData(data):
                pm = _rounded_pixmap(raw, size, radius)
                _cover_cache[key] = pm
                try:
                    dkey = _cover_disk_key(fp, size, radius)
                    disk_path = _COVER_DISK_DIR / f'{dkey}.jpg'
                    _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
                    pm.save(str(disk_path), 'JPEG', _COVER_JPEG_QUALITY)
                except Exception:
                    pass
        threading.Thread(target=embed_cover_bytes, args=(fp, data), daemon=True).start()
        for page in self._pages:
            tracks = page.tracks if hasattr(page, 'tracks') else []
            for r, t in enumerate(tracks):
                if t.filepath == fp and r < page.table.rowCount():
                    item = page.table.item(r, C_TIT)
                    pm28 = _cover_cache.get((fp, 28, 4))
                    if item and pm28:
                        item.setIcon(QIcon(pm28))
                    break
        if self._ctrlbar and self._ctrlbar._cur_track:
            if self._ctrlbar._cur_track.filepath == fp:
                pm64 = _cover_cache.get((fp, 64, 8))
                if pm64 and self._ctrlbar._cover_lbl.isVisible():
                    self._ctrlbar._cover_lbl.setPixmap(pm64)
        self._found += 1



# ══════════════════════════════════════════════════════════════════════════════
#  Library Tag Fetch Worker + Popup
# ══════════════════════════════════════════════════════════════════════════════

class LibraryTagFetchWorker(QObject):
    """Fetches missing tags (title/artist/album) for library tracks sequentially.
    Progress is based only on tracks that are missing at least one tag."""
    progress   = pyqtSignal(int, int, str)        # current, total, track_name
    track_done = pyqtSignal(str, dict, bool)       # filepath, tags_dict, found_flag
    finished   = pyqtSignal(int, int)              # updated_count, total_needs

    def __init__(self, tracks: list, force: bool = False):
        super().__init__()
        self._tracks    = list(tracks)
        self._force     = force
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # In force mode, attempt a tag lookup for every track.
        if self._force:
            needs = list(self._tracks)
        else:
            needs = [t for t in self._tracks
                     if not (t.title.strip() and t.artist.strip() and t.album.strip())]
        total   = len(needs)
        updated = 0
        for i, t in enumerate(needs):
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            self.progress.emit(i + 1, total, name)
            tags = lookup_tags_online(t.artist or '', t.title or Path(t.filepath).stem)
            if tags:
                result = {}
                if not t.title.strip()  and tags.get('title'):  result['title']  = tags['title']
                if not t.artist.strip() and tags.get('artist'): result['artist'] = tags['artist']
                if not t.album.strip()  and tags.get('album'):  result['album']  = tags['album']
                if result:
                    updated += 1
                    self.track_done.emit(t.filepath, result, True)
                else:
                    self.track_done.emit(t.filepath, {}, False)
            else:
                self.track_done.emit(t.filepath, {}, False)
        self.finished.emit(updated, total)

class TagFetchPopup(_BaseFetchPopup):
    """Modal dialog that looks up missing tags for library tracks."""

    tags_updated = pyqtSignal(str, dict)

    def __init__(self, tracks: list, parent=None):
        needs = [t for t in tracks
                 if not (t.title.strip() and t.artist.strip() and t.album.strip())]
        info = (f'<b>{len(needs)}</b> tracks have at least one missing tag '
                f'(out of {len(tracks)} total — tracks with all tags are skipped).')
        super().__init__(tracks, 'Fetch Missing Tags', info, len(needs), parent)
        self._needs = needs

    def _make_worker(self):
        return LibraryTagFetchWorker(self._tracks, force=self._force)

    def set_tracks(self, tracks: list):
        self._tracks = list(tracks)
        self._needs  = [t for t in tracks
                        if not (t.title.strip() and t.artist.strip() and t.album.strip())]
        self._progress.setRange(0, max(1, len(self._needs)))

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Updated tags for {found} out of {total} tracks.'

    def _on_track_done(self, fp: str, tags: dict, found: bool):
        name = Path(fp).stem
        if not found or not tags:
            self._log_add(f'FAIL  {name}', False)
            return
        filled = ', '.join(f'{k}={v}' for k, v in tags.items())
        self._log_add(f'OK    {name}  [{filled}]', True)
        threading.Thread(target=write_tags_to_file, args=(fp, tags), daemon=True).start()
        self._found += 1
        self.tags_updated.emit(fp, tags)



# ══════════════════════════════════════════════════════════════════════════════
#  Library Lyrics Fetch Worker + Popup
# ══════════════════════════════════════════════════════════════════════════════

class LibraryLyricsFetchWorker(QObject):
    """Fetches and embeds lyrics for library tracks that have no embedded lyrics.
    Runs sequentially in a worker thread; emits per-track results back to the UI."""
    progress   = pyqtSignal(int, int, str)        # current, total, track_name
    track_done = pyqtSignal(str, bool)             # filepath, found_flag
    finished   = pyqtSignal(int, int)              # found_count, total_needs

    def __init__(self, tracks: list, force: bool = False):
        super().__init__()
        self._tracks    = list(tracks)
        self._force     = force
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # In force mode, process every track (overwrite existing embedded lyrics too).
        if self._force:
            needs = list(self._tracks)
        else:
            needs = [t for t in self._tracks if not any(_extract_embedded_lyrics(t.filepath))]
        total = len(needs)
        found = 0
        for i, t in enumerate(needs):
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            self.progress.emit(i + 1, total, name)
            artist = (t.artist or '').strip()
            title  = (t.title  or '').strip()
            album  = (t.album  or '').strip()
            # Run the same multi-source fetch used by LyricsFetcher
            synced, plain = None, None
            for src_fn in [
                lambda: _src_lrclib_exact(artist, title, album, t.duration),
                lambda: _src_lrclib_search(artist, title),
                lambda: _src_lyrics_ovh(artist, title),
            ]:
                try:
                    s, p = src_fn()
                    if s:
                        synced = s; break
                    if p and not plain:
                        plain = p
                except Exception:
                    pass
            if synced or plain:
                ok = embed_lyrics(t.filepath, synced, plain)
                self.track_done.emit(t.filepath, ok)
                if ok:
                    found += 1
            else:
                self.track_done.emit(t.filepath, False)
        self.finished.emit(found, total)

class LyricsFetchPopup(_BaseFetchPopup):
    """Modal dialog that fetches and embeds lyrics for library tracks."""

    def __init__(self, tracks: list, parent=None):
        needs = [t for t in tracks if not any(_extract_embedded_lyrics(t.filepath))]
        info = (f'<b>{len(needs)}</b> tracks have no embedded lyrics '
                f'(out of {len(tracks)} total — tracks with embedded lyrics are skipped).')
        super().__init__(tracks, 'Fetch Lyrics', info, len(needs), parent)
        self._needs = needs

    def _make_worker(self):
        return LibraryLyricsFetchWorker(self._tracks, force=self._force)

    def set_tracks(self, tracks: list):
        self._tracks = list(tracks)
        self._needs  = [t for t in tracks if not any(_extract_embedded_lyrics(t.filepath))]
        self._progress.setRange(0, max(1, len(self._needs)))

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Embedded lyrics for {found} out of {total} tracks.'

    def _on_track_done(self, fp: str, found: bool):
        name = Path(fp).stem
        self._log_add(f'{"OK  " if found else "FAIL"} {name}', found)
        if found:
            self._found += 1


# ══════════════════════════════════════════════════════════════════════════════
#  Library Rename Worker + Popup
# ══════════════════════════════════════════════════════════════════════════════

def _sanitize_filename_part(text: str) -> str:
    """Remove characters that are illegal in filenames on Linux/POSIX.

    Only '/' and null bytes are truly illegal on Linux, but we also strip
    leading/trailing dots and spaces to avoid edge cases with hidden files
    and Windows-incompatible names.
    """
    text = text.replace('/', '_').replace('\x00', '')
    return text.strip('. ')


def _build_new_filename(pattern: str, track) -> str:
    """Build a new filename (without extension) from pattern + track metadata.

    Placeholders:
        %F  current filename stem
        %A  artist
        %T  title
        %C  album (Collection)
    All other characters (including punctuation, spaces, emoji, etc.) are kept as-is.
    Metadata values are sanitized so embedded '/' chars cannot break Path.with_name().
    Returns empty string when the pattern is empty.
    """
    stem   = _sanitize_filename_part(Path(track.filepath).stem)
    result = pattern
    result = result.replace('%F', stem)
    result = result.replace('%A', _sanitize_filename_part(track.artist or ''))
    result = result.replace('%T', _sanitize_filename_part(track.title  or ''))
    result = result.replace('%C', _sanitize_filename_part(track.album  or ''))
    return result


def _validate_rename_pattern(pattern: str):
    """Return a list of invalid token strings found in *pattern*.

    A token starting with '%' but not in {%F,%A,%T,%C} is invalid.
    An empty pattern is also considered invalid (returns ['(empty)'] sentinel).
    """
    if not pattern.strip():
        return ['(empty)']
    bad = []
    for m in _re.finditer(r'%[^\s]?', pattern):
        tok = m.group()
        if tok not in ('%F', '%A', '%T', '%C'):
            bad.append(tok)
    return bad


class LibraryRenameWorker(QObject):
    """Renames audio files on disk using a user-supplied pattern."""
    progress   = pyqtSignal(int, int, str)        # current, total, track_name
    track_done = pyqtSignal(str, str, bool)        # old_path, new_path, success
    finished   = pyqtSignal(int, int)              # renamed_count, total

    def __init__(self, tracks: list, pattern: str):
        super().__init__()
        self._tracks    = list(tracks)
        self._pattern   = pattern
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total   = len(self._tracks)
        renamed = 0
        for i, t in enumerate(self._tracks):
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            self.progress.emit(i + 1, total, name)
            try:
                new_stem = _build_new_filename(self._pattern, t)
                if not new_stem.strip():
                    self.track_done.emit(t.filepath, '', False)
                    continue
                old_path = Path(t.filepath)
                new_path = old_path.with_name(new_stem + old_path.suffix)
                if old_path == new_path:
                    # Nothing to do
                    self.track_done.emit(str(old_path), str(new_path), True)
                    renamed += 1
                    continue
                # Avoid overwriting existing files — append _(n) suffix
                counter = 1
                candidate = new_path
                while candidate.exists():
                    candidate = old_path.with_name(f'{new_stem}_({counter}){old_path.suffix}')
                    counter += 1
                old_path.rename(candidate)
                renamed += 1
                self.track_done.emit(str(old_path), str(candidate), True)
            except Exception as exc:
                self.track_done.emit(t.filepath, str(exc), False)
        self.finished.emit(renamed, total)


class RenamePopup(QDialog):
    """Modal dialog for batch-renaming the library with a filename pattern.

    Placeholders: %F=filename  %A=artist  %T=title  %C=album
    Any other characters (punctuation, spaces, emoji, etc.) are kept literally.

    After the dialog closes (finished OR cancelled), ``rename_map`` holds a dict
    of {old_path: new_path} for every file that was successfully renamed on disk.
    The caller (ControlBar._on_rename_btn) uses this to rescan and update M3Us.
    """

    # Class-level tracking of active rename worker
    _active_worker = None  # (instance, worker, thread) or None

    def __init__(self, tracks: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Rename Library Files')
        self.setModal(True)
        self.setMinimumWidth(440)

        self._tracks   = list(tracks)
        self._thread   = None
        self._worker   = None
        self._running  = False
        self._renamed  = 0
        # Collected as worker emits; available after exec() returns
        self.rename_map: dict = {}   # {old_path: new_path}
        # Store background state for restoration
        self._bg_progress = 0
        self._bg_total = len(tracks)
        self._bg_track_name = ''
        self._bg_log_items = []  # list of (text, ok_flag, old_name, new_name)
        self._bg_result = ''

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 18, 20, 18)

        title_lbl = QLabel('Rename Library Files')
        title_lbl.setStyleSheet(f'font-size:14px;font-weight:bold;color:{FG};')
        root.addWidget(title_lbl)

        desc = QLabel(
            'Enter a filename pattern. Any characters outside the placeholders are kept literally.<br>'
            '<b>%F</b> = current filename &nbsp; <b>%A</b> = artist &nbsp;'
            '<b>%T</b> = title &nbsp; <b>%C</b> = album'
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f'color:{FG2};font-size:12px;')
        root.addWidget(desc)

        pat_row = QHBoxLayout()
        pat_lbl = QLabel('Pattern:')
        pat_lbl.setStyleSheet(f'color:{FG};font-size:12px;')
        pat_lbl.setFixedWidth(60)
        self._pat_edit = QLineEdit()
        self._pat_edit.setPlaceholderText('e.g. %T-%C  or  %A - %T')
        self._ss_ok  = (f'QLineEdit {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
                        f' border-radius:5px; padding:4px 8px; font-size:13px; }}'
                        f'QLineEdit:focus {{ border-color:{ACC}; }}')
        self._ss_bad = (f'QLineEdit {{ background:{BG3}; color:#cc3333; border:1px solid #cc3333;'
                        f' border-radius:5px; padding:4px 8px; font-size:13px; }}')
        self._pat_edit.setStyleSheet(self._ss_ok)
        self._pat_edit.textChanged.connect(self._on_pattern_changed)
        pat_row.addWidget(pat_lbl)
        pat_row.addWidget(self._pat_edit, 1)
        root.addLayout(pat_row)

        self._valid_lbl = QLabel('')
        self._valid_lbl.setStyleSheet(f'color:{FG2};font-size:11px;')
        self._valid_lbl.setWordWrap(True)
        root.addWidget(self._valid_lbl)

        self._track_lbl = QLabel('')
        self._track_lbl.setStyleSheet(f'color:{FG};font-size:12px;')
        self._track_lbl.setWordWrap(True)
        root.addWidget(self._track_lbl)

        self._log = QListWidget()
        self._log.setFixedHeight(150)
        self._log.setStyleSheet(
            'QListWidget{background:' + BG + ';border:1px solid ' + B2 + ';border-radius:4px;'
            'color:' + FG2 + ';font-size:10px;outline:none;}'
            'QListWidget::item{padding:1px 6px;border:none;}'
            'QListWidget::item:selected{background:transparent;color:' + FG2 + ';}'
        )
        self._log.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        QScroller.grabGesture(self._log.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        _apply_scroller_properties(self._log.viewport())
        root.addWidget(self._log)

        self._result_lbl = QLabel('')
        self._result_lbl.setStyleSheet(f'color:{FG2};font-size:11px;')
        root.addWidget(self._result_lbl)

        btn_row = QHBoxLayout()
        self._btn_start  = QPushButton('Start')
        self._btn_cancel = QPushButton('Cancel')
        self._btn_cancel.setEnabled(False)
        self._btn_close  = QPushButton('Run in Background')
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

        self._btn_start.clicked.connect(self._start)
        self._btn_cancel.clicked.connect(self._cancel)
        self._btn_close.clicked.connect(self._on_close)

        self._on_pattern_changed('')
        
        # Check if there's an existing rename worker running in background and auto-restore
        self._check_and_restore_background_rename()

    # ── validation ────────────────────────────────────────────────────────────

    def _on_pattern_changed(self, text: str):
        bad = _validate_rename_pattern(text)
        if bad:
            self._pat_edit.setStyleSheet(self._ss_bad)
            if bad == ['(empty)']:
                self._valid_lbl.setText('<span style="color:#cc3333;">Pattern cannot be empty.</span>')
            else:
                bads = ', '.join(bad)
                self._valid_lbl.setText(
                    f'<span style="color:#cc3333;">Invalid placeholders: {bads}. '
                    f'Only %F, %A, %T, %C are allowed.</span>')
            self._btn_start.setEnabled(False)
        else:
            self._pat_edit.setStyleSheet(self._ss_ok)
            if self._tracks:
                preview = _build_new_filename(text, self._tracks[0])
                ext = Path(self._tracks[0].filepath).suffix
                self._valid_lbl.setText(
                    f'<span style="color:{FG2};">Preview: <b>{preview}{ext}</b></span>')
            else:
                self._valid_lbl.setText('')
            self._btn_start.setEnabled(True)

    # ── worker ────────────────────────────────────────────────────────────────

    def _check_and_restore_background_rename(self):
        """Check if there's an existing rename worker running in background and auto-restore UI."""
        existing = RenamePopup._active_worker
        if existing:
            old_instance, old_worker, old_thread = existing
            # Restore UI to show the existing running operation with full state
            self._thread = old_thread
            self._worker = old_worker
            self._running = True
            self._btn_start.setEnabled(False)
            self._btn_cancel.setEnabled(True)
            # Restore progress and track info from background state
            self._track_lbl.setText(f'[{old_instance._bg_progress}/{old_instance._bg_total}]  {old_instance._bg_track_name}')
            # Restore log items
            self._log.clear()
            for item_data in old_instance._bg_log_items:
                text, ok_flag, old_name, new_name = item_data
                if ok_flag:
                    item = QListWidgetItem(f'OK    {old_name}  →  {new_name}')
                    item.setForeground(QColor('#55bb55'))
                else:
                    item = QListWidgetItem(f'FAIL  {old_name}  ({new_name})')
                    item.setForeground(QColor('#bb3333'))
                self._log.addItem(item)
            self._log.scrollToBottom()
            # Restore result label if present
            if old_instance._bg_result:
                self._result_lbl.setText(old_instance._bg_result)
            # Emit progress to main window status bar
            self._emit_status_update_rename()
            # Auto-show the dialog (it may have been hidden)
            self.show()
            # Connect signals to restore live updates
            self._worker.progress.connect(self._on_progress)
            self._worker.track_done.connect(self._on_track_done)
            self._worker.finished.connect(self._on_finished)

    def _emit_status_update_rename(self):
        """Emit rename progress status to main window status bar."""
        if self._running and hasattr(self, '_bg_progress') and hasattr(self, '_bg_total'):
            msg = f"Rename: [{self._bg_progress}/{self._bg_total}] {self._bg_track_name}"
            # Find main window and update status bar
            win = self.parent()
            while win and not isinstance(win, MainWindow):
                win = win.parent()
            if win and hasattr(win, '_status'):
                # Remove old widget if exists
                old_lbl = getattr(win, '_fetch_rename_lbl', None)
                if old_lbl:
                    old_lbl.deleteLater()
                # Create new permanent widget
                lbl = QLabel(msg)
                lbl.setStyleSheet(f'color:{FG}; font-size:11px; padding: 0 8px;')
                win._status.addPermanentWidget(lbl, 0)
                setattr(win, '_fetch_rename_lbl', lbl)

    def _clear_status_update_rename(self):
        """Clear rename status bar message when finished."""
        win = self.parent()
        while win and not isinstance(win, MainWindow):
            win = win.parent()
        if win:
            old_lbl = getattr(win, '_fetch_rename_lbl', None)
            if old_lbl:
                old_lbl.deleteLater()
                setattr(win, '_fetch_rename_lbl', None)

    def _start(self):
        if self._running:
            return
        
        pattern = self._pat_edit.text()
        if _validate_rename_pattern(pattern):
            return
        self._running  = True
        self._renamed  = 0
        self.rename_map = {}
        self._log.clear()
        self._result_lbl.setText('')
        self._track_lbl.setText('')
        self._btn_start.setEnabled(False)
        self._btn_cancel.setEnabled(True)

        worker = LibraryRenameWorker(self._tracks, pattern)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.track_done.connect(self._on_track_done)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(thread.quit)
        self._thread = thread
        self._worker = worker
        # Register this worker as active
        RenamePopup._active_worker = (self, worker, thread)
        thread.start()
        # Emit initial status update
        self._emit_status_update_rename()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
        self._btn_cancel.setEnabled(False)
        self._track_lbl.setText('Cancelling…')

    def _stop_thread(self):
        """Cancel worker and wait for thread to finish (called before closing)."""
        if self._worker:
            self._worker.cancel()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None

    def _on_close(self):
        # Hide the dialog but keep the thread running in background
        self.hide()

    def closeEvent(self, e):
        # Hide instead of closing - keeps thread alive
        self.hide()
        e.ignore()

    def mousePressEvent(self, e):
        # Clicking outside the popup (on the modal backdrop) hides it like "Run in Background"
        if e.button() == Qt.MouseButton.LeftButton:
            # Check if click is outside the dialog's geometry
            if not self.rect().contains(e.pos()):
                self.hide()
                e.ignore()
                return
        super().mousePressEvent(e)

    def _on_progress(self, current: int, total: int, name: str):
        self._track_lbl.setText(f'[{current}/{total}]  {name}')
        # Store state for background restoration
        self._bg_progress = current
        self._bg_total = total
        self._bg_track_name = name

    def _on_track_done(self, old_path: str, new_path: str, ok: bool):
        old_name = Path(old_path).name
        if ok:
            new_name = Path(new_path).name if new_path else old_name
            item = QListWidgetItem(f'OK    {old_name}  →  {new_name}')
            item.setForeground(QColor('#55bb55'))
            self._renamed += 1
            if old_path != new_path:
                self.rename_map[old_path] = new_path
        else:
            item = QListWidgetItem(f'FAIL  {old_name}  ({new_path})')
            item.setForeground(QColor('#bb3333'))
        self._log.addItem(item)
        self._log.scrollToBottom()
        # Store log item for background restoration
        self._bg_log_items.append((item.text(), ok, old_name, new_path if ok else new_path))

    def _on_finished(self, renamed: int, total: int):
        self._running = False
        # Clear active worker reference
        RenamePopup._active_worker = None
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._track_lbl.setText('Done.')
        result_msg = f'{renamed} / {total} files renamed.'
        self._result_lbl.setText(result_msg)
        # Store result for background restoration
        self._bg_result = result_msg
        # Clean up thread references
        self._thread = None
        self._worker = None
        # Clear status bar message
        self._clear_status_update_rename()



def scan_folder(folder: str) -> List[Track]:
    fps = []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for f in sorted(files):
            if Path(f).suffix.lower() in SUPPORTED_EXT:
                fps.append(os.path.join(root, f))
    if not fps:
        return []
    # Parallel mutagen reads — 4 workers balances HDD seek latency vs CPU saturation.
    with _cf.ThreadPoolExecutor(max_workers=4) as pool:
        out = list(pool.map(read_metadata, fps))
    out.sort(key=lambda t: t.sort_key())
    return out

def parse_m3u(path: str) -> List[Track]:
    fps, base = [], os.path.dirname(path)
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#'): continue
                fp = line if os.path.isabs(line) else os.path.join(base, line)
                if os.path.isfile(fp) and Path(fp).suffix.lower() in SUPPORTED_EXT:
                    fps.append(fp)
    except Exception as e:
        print(f'M3U error: {e}')
    if not fps:
        return []
    with _cf.ThreadPoolExecutor(max_workers=4) as pool:
        out = list(pool.map(read_metadata, fps))
    out.sort(key=lambda t: t.sort_key())
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  Scanner thread (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
class ScanThread(QThread):
    done     = pyqtSignal(list, str)
    progress = pyqtSignal(str)

    def __init__(self, path: str, is_m3u: bool = False):
        super().__init__()
        self._path, self._is_m3u = path, is_m3u

    def run(self):
        self.progress.emit(f'Scanning: {os.path.basename(self._path)} …')
        if self._is_m3u:
            tracks = parse_m3u(self._path); label = Path(self._path).stem
        else:
            tracks = scan_folder(self._path)
            label  = os.path.basename(self._path.rstrip('/\\'))
        self.done.emit(tracks, label)


class ConfigPlaylistLoader(QThread):
    """Non-blocking loader: reads track metadata for saved playlists in background.

    Emits playlist_ready once per playlist (in order) so MainWindow can add pages
    incrementally without blocking the event loop.  Uses a small thread pool to
    parallelise the per-track mutagen reads within each playlist.
    """
    playlist_ready = pyqtSignal(list, str)   # (tracks, label)
    all_done       = pyqtSignal()

    def __init__(self, playlist_data: list):
        """playlist_data: list of {'label': str, 'tracks': [filepath, ...]}"""
        super().__init__()
        self._playlist_data = playlist_data

    def run(self):
        for pd in self._playlist_data:
            label = pd.get('label', 'Playlist')
            fps   = [fp for fp in pd.get('tracks', []) if os.path.isfile(fp)]
            if not fps:
                continue
            # Parallel mutagen reads — 4 workers is a good balance for HDDs and SSDs
            with _cf.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(read_metadata, fps))
            tracks = sorted(results, key=lambda t: t.sort_key())
            if tracks:
                self.playlist_ready.emit(tracks, label)
        self.all_done.emit()

# ══════════════════════════════════════════════════════════════════════════════
#  GStreamer Player with Parametric EQ (using audioiirfilter with coefficient calculation)
# ══════════════════════════════════════════════════════════════════════════════
class RepeatMode(enum.Enum):
    NONE = 0; ALL = 1; ONE = 2

def peaking_coefficients(fs, f0, gain_db, Q):
    """Return biquad coefficients (b0,b1,b2,a1,a2) for a peaking filter."""
    A = 10.0**(gain_db/40.0)
    w0 = 2.0 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2.0 * Q)

    b0 = 1.0 + alpha * A
    b1 = -2.0 * math.cos(w0)
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * math.cos(w0)
    a2 = 1.0 - alpha / A

    # Normalize to a0
    b0 /= a0
    b1 /= a0
    b2 /= a0
    a1 /= a0
    a2 /= a0
    # a0 is now 1

    return (b0, b1, b2, a1, a2)

class Player(QObject):
    sig_pos       = pyqtSignal(int)
    sig_dur       = pyqtSignal(int)
    sig_end       = pyqtSignal()
    sig_err       = pyqtSignal(str)
    sig_seek_flush = pyqtSignal()
    sig_playing   = pyqtSignal(bool)
    sig_seek     = pyqtSignal()
    sig_busy      = pyqtSignal(bool)   # True = pipeline reloading; False = done
    sig_fs_changed = pyqtSignal(int)   # emitted when track sample rate changes (main thread)
    _sig_drift_gst_ms = pyqtSignal(float, float)  # GLib thread → main thread: (gst_pos_ms, query_wall_t)
    _sig_dur_gst_ms   = pyqtSignal(int)           # GLib thread → main thread: confirmed duration (ms)

    _SPEC_INTERVAL_NS = int(1_000_000_000 / 30)  # 30fps spectrum — reduces GIL contention vs 60fps

    # (pre-spectrum chain, output sink)
    # 0=direct(bit-perfect) 1=audioconvert(format only, no rate) 2=+audioresample
    _CHAINS   = ['', 'audioconvert', 'audioconvert ! audioresample']
    _OUTS     = ['pipewiresink', 'pipewiresink', 'pipewiresink']
    _FALLBACK = ('audioconvert ! audioresample', 'autoaudiosink')

    def __init__(self):
        super().__init__()
        self._pipe:    Optional[Gst.Element] = None
        self._spec_el: Optional[Gst.Element] = None
        self._playing: bool  = False
        self._volume:  float = 0.8
        self._viz_on:  bool  = True
        self._dur_ms_cached: int = 0
        self._pause_ts: float = 0.0   # set on pause; 0 = never paused (safe)
        self._last_filepath: str = ''  # last loaded file path; used for dead-pipe recovery
        self._spec_serial = 0
        self._seek_target_ns = 0
        self._seek_wall_t: float = 0.0

        # ── Interpolated position tracking ────────────────────────────────────
        # Instead of asking GStreamer on every tick (which lags after seek/pause),
        # we maintain a wall-clock anchor: pos = _pos_anchor_ms + elapsed_since_anchor.
        # The anchor is updated immediately on load/seek/play/pause so position()
        # responds at zero latency.  A periodic drift-correction step queries
        # GStreamer and nudges the anchor to stay accurate over long play sessions.
        self._pos_anchor_ms: float = 0.0   # reference position in ms
        self._pos_anchor_wt: float = 0.0   # wall-clock time of that reference
        self._pos_playing:   bool  = False  # local copy of playing state for anchor math

        # Viz computation state — written by GLib thread, read by main thread render_timer
        # All numpy arrays; CPython object reference assignment is atomic under GIL.
        self._viz_spec = _np.full(GST_BANDS, MIN_DB, dtype=_np.float32)  # inertia state
        # Viz mapping tables — set by ControlBar.set_viz_tables(), read by GLib thread
        self._viz_ba: object = None          # int32 (VIZ_BANDS,)
        self._viz_bb: object = None
        self._viz_bt: object = None
        self._viz_inertia: float = 0.5
        self._viz_overlay_cb: object = None  # callable(list) for overlay frames
        self._viz_discard_until: float = 0.0  # wall-clock: discard frames before this
        self._viz_last_stream_time: int = -1  # last spectrum stream-time (ns), frame skip detection
        self._viz_accumulated_el: int = 0     # total elapsed frames across burst messages since last render
        self._viz_has_new: bool = False       # GLib thread set; main thread clear
        self._viz_has_any: bool = False       # True once first spectrum arrives after load
        self._viz_frame_pending: bool = False # GLib set; Qt clear — prevents queue buildup
        self._viz_mag_buf = _np.full(GST_BANDS, MIN_DB, dtype=_np.float32)  # latest raw magnitude
        self._viz_bh_pre  = _np.empty(VIZ_BANDS, dtype=_np.float32)         # work buffer
        self._viz_tmp_pre = _np.empty(VIZ_BANDS, dtype=_np.float32)         # work buffer
        self._viz_bar_buf = _np.zeros(VIZ_BANDS, dtype=_np.float32)  # published bar heights (pre-alloc)
        self._viz_col_buf = _np.zeros(1, dtype=_np.float32)           # iw-sized, rebuilt in set_viz_tables
        self._overlay_needs_spec: bool = False
        self._last_parsed_serial: object = None
        self._viz_mag_field_idx: int = -1   # cached 'magnitude' field index in spectrum structure
        # Vectorised smooth arrays — populated by set_viz_tables (main thread)
        self._viz_sm_d  = _np.empty(0, dtype=_np.int32)
        self._viz_sm_nb = _np.empty((0, 1), dtype=_np.int32)
        self._viz_sm_wk = _np.empty((0, 1), dtype=_np.float32)
        self._reloading: bool = False
        self._reload_guard: bool = False
        self._silent_recovery: bool = False  # True during invisible stall recovery
        self._seek_retries: int = 0
        self._pos_timer_burst: int = 0
        self._last_advance_wt: float = -1.0   # -1 = not yet set (legacy, kept for _play_pause reset)
        self._last_advance_pos: float = -1.0  # -1 = not yet set (legacy)
        # Real GStreamer position stall tracking — uses actual queried values, not interpolated.
        # _apply_drift_correction updates these; detects pipeline freeze in ~700 ms.
        self._gst_pos_adv_ms: float = -1.0   # last GST query that showed genuine forward movement
        self._gst_pos_adv_wt: float = -1.0   # wall-clock time of that query

        # EQ related
        self._eq_enabled = True
        self._eq_bands = []               # list of (freq, gain, Q)
        self._eq_filters = []              # list of Gst.Element for each band (size MAX_EQ_BANDS)
        self._current_fs = 48000           # default sample rate, will update from track

        self._chain, self._out = self._detect_chain()
        print(f'[Player] chain: "{self._chain or "(none)"}" → {self._out}')

        self._has_spec = Gst.ElementFactory.find('spectrum') is not None
        print(f'[Player] spectrum: {"OK" if self._has_spec else "not found"}')

        self._glib_loop = GLib.MainLoop()
        threading.Thread(target=self._glib_loop.run, daemon=True, name='glib').start()

        self._pos_timer  = QTimer(self)
        self._pos_timer.setInterval(250)
        self._pos_timer.timeout.connect(self._tick_pos)
        # After seek/resume, fire more frequently for the first few ticks
        self._pos_timer_burst = 0   # countdown: ticks remaining at fast (100ms) rate
        self._tick_n = 0
        # GLib-thread drift correction: one idle query in flight at a time
        # _drift_pending guards both position and duration queries (single GLib slot).
        self._drift_pending: bool = False
        self._drift_sched_wt: float = 0.0
        self._tick_last_wt:   float = -1.0
        self._resume_wt:      float = 0.0
        self._play_start_wt:  float = 0.0   # wall-clock of last play — for relative timestamps
        self._sig_drift_gst_ms.connect(self._apply_drift_correction)
        self._sig_dur_gst_ms.connect(self._on_dur_from_glib)

    @staticmethod
    def _detect_chain():
        for chain, out in zip(Player._CHAINS, Player._OUTS):
            desc = f'{chain} ! {out}' if chain else out
            try:
                b = Gst.parse_bin_from_description(desc, True)
                b.set_state(Gst.State.NULL); return chain, out
            except Exception:
                continue
        return Player._FALLBACK

    def load(self, filepath: str):
        self._last_filepath = filepath   # remember for dead-pipe recovery in play_pause
        self._destroy()
        self._spec_serial += 1
        self._pipe = Gst.ElementFactory.make('playbin', None)
        if not self._pipe:
            self.sig_err.emit('playbin unavailable'); return
        self._pipe.set_property('uri', Path(filepath).as_uri())
        self._pipe.set_property('volume', self._volume)

        # Get sample rate from track metadata; emit sig_fs_changed so ControlBar
        # recomputes freq→bin mapping tables with the correct Nyquist frequency.
        track = read_metadata(filepath)
        self._current_fs = track.sample_rate if track.sample_rate > 0 else 48000
        self.sig_fs_changed.emit(self._current_fs)

        # Build sink bin with EQ and spectrum
        sink_bin, eq_filters = self._make_sink_bin()
        if sink_bin:
            self._pipe.set_property('audio-sink', sink_bin)
            self._eq_filters = eq_filters
            if self._has_spec:
                self._spec_el = sink_bin.get_by_name('bp_spec')
                if self._spec_el:
                    _need = self._viz_on or self._overlay_needs_spec
                    self._spec_el.set_property('post-messages', bool(_need))
            # Apply current EQ settings
            self._apply_eq_to_filters()

        bus = self._pipe.get_bus()
        bus.add_signal_watch(); bus.connect('message', self._on_msg)
        self._pipe.set_state(Gst.State.PLAYING)
        self._playing = True; self._pos_timer.start()
        self._tick_n = 0
        self._start_pos_burst(8)  # fast updates while prerolling
        if not self._silent_recovery:
            self._pos_playing = True
            self._anchor_now(0.0)   # start at 0; confirmed below once prerolled
        # Once the pipeline has prerolled (~300–600 ms), re-anchor from GStreamer
        # so any startup latency is absorbed and the display stays accurate.
        def _post_load_confirm():
            if not self._pipe or not self._playing:
                return
            self._anchor_from_gst()
        QTimer.singleShot(600, _post_load_confirm)
        if not self._silent_recovery:
            self.sig_playing.emit(True)

    def play_pause(self):
        if not self._pipe:
            # Pipeline was destroyed (e.g. after a GST ERROR).  If we know the last
            # file, reload it so the user's Play press is not silently swallowed.
            if self._last_filepath:
                pos_ms = int(self._pos_anchor_ms)
                self._load_and_seek(self._last_filepath, pos_ms)
            return
        if not self._playing:
            self._play_start_wt = _monotonic()
        if self._playing:
            self._pipe.set_state(Gst.State.PAUSED)
            # Freeze anchor at current interpolated position before stopping clock
            frozen = self.position_ms()
            self._playing = False; self._pos_timer.stop()
            self._pos_playing = False
            self._anchor_now(frozen)   # anchor is now the paused position
            self._pause_ts = _monotonic()   # record pause time
            self.sig_playing.emit(False)
        else:
            # Non-blocking state query — avoids blocking the main (UI) thread.
            # VOID_PENDING means a transition is in progress; treat like PAUSED.
            _, st, pending = self._pipe.get_state(timeout=0)
            eff_st = pending if (st == Gst.State.VOID_PENDING
                                 and pending != Gst.State.VOID_PENDING) else st

            # Pipeline dead — reload immediately, no further probing needed.
            if eff_st in (Gst.State.NULL, Gst.State.READY):
                self._resume_with_reload(fallback_ms=int(self._pos_anchor_ms))
                return

            pause_dur = (_monotonic() - self._pause_ts) if self._pause_ts > 0.0 else 0.0
            if pause_dur > 2.0:
                # Long pause: PipeWire may have reclaimed the sink.  Attempt resume;
                # if position doesn't advance within 800 ms the stall detector will
                # catch and reload automatically.
                print(f'[Player] resuming after {pause_dur:.1f}s pause — stall watcher armed')
            self._pipe.set_state(Gst.State.PLAYING)

            self._playing = True; self._pos_timer.start()
            self._resume_wt = _monotonic()   # gate drift correction for 1.5 s after resume
            # ── DRIFT FIX ────────────────────────────────────────────────────
            # The anchor ms is the frozen pause position (correct), but _pos_anchor_wt
            # was set when we *paused*, so elapsed = now - pause_wt = pause_duration,
            # which would instantly jump the position forward by the entire pause gap.
            # Reset wt to *now* so elapsed starts from 0 and interpolation picks up
            # exactly where we froze.
            self._pos_anchor_wt = _monotonic()
            self._pos_playing = True
            self._tick_n = 0
            # Reset stall tracking so detection window starts fresh after resume.
            self._last_advance_wt  = _monotonic()
            self._last_advance_pos = self.position_ms()
            self._gst_pos_adv_ms   = -1.0   # re-initialise on first post-resume drift query
            self._gst_pos_adv_wt   = -1.0
            # Fast pos updates for 2 s after resume so seekbar snaps immediately
            self._start_pos_burst(8)
            # Discard stale spectrum frames that were buffered during the pause.
            # This prevents viz from jumping to the wrong position right after resume.
            self._viz_discard_until = _monotonic() + 0.15
            self.sig_playing.emit(True)
            # Defer anchor reconfirmation: query_position immediately after
            # set_state(PLAYING) is unreliable — the GStreamer clock hasn't fully
            # restarted yet, causing 1–2 s of drift until the 500 ms tick corrects it.
            # 150 ms is enough for the clock to stabilise; anchor_from_gst then
            # resets the interpolation baseline and drift disappears immediately.
            def _deferred_anchor():
                if self._pipe and self._playing:
                    if not self._anchor_from_gst():
                        # Pipeline not ready yet — try once more after another 150 ms
                        QTimer.singleShot(150, lambda: self._pipe and self._playing
                                          and self._anchor_from_gst())
            QTimer.singleShot(150, _deferred_anchor)
            # Short pauses (<2 s): the drift-correction loop and the real-position
            # stall detector in _apply_drift_correction cover those cases.
            # The active stall watcher was removed — it caused false reloads on
            # Bluetooth where position query latency mimics a stalled pipeline.

    def _load_and_seek(self, filepath: str, pos_ms: int, silent: bool = False):
        """Load filepath and seek to pos_ms after preroll. Used for dead-pipe recovery.

        Args:
            silent: When True (stall auto-recovery), the UI is not notified — no busy
                    spinner, no play/pause icon flip, no viz clear.  The seekbar keeps
                    interpolating from the saved anchor and the user sees nothing.
        """
        self._silent_recovery = silent
        # Always anchor to the intended position so the seekbar doesn't snap to 0.
        self._anchor_now(float(max(0, pos_ms)))

        if silent:
            # Keep _pos_playing=True so anchor interpolation continues.
            # Discard viz frames for a short window so glitchy frames don't show.
            self._viz_discard_until = _monotonic() + 0.6   # 600 ms discard
        else:
            self.sig_busy.emit(True)
            self._pos_playing = False   # interpolation off until pipeline is live
            # Clear viz state so old frames don't bleed into the new pipeline
            self._viz_bar_buf[:] = 0.0
            self._viz_col_buf[:] = 0.0
            self._viz_spec[:] = MIN_DB
            self._viz_discard_until = _monotonic() + 0.5   # 500 ms discard post-load

        self.load(filepath)
        self._pause_ts = 0.0
        # Reset stall tracking — grace period comes from _reloading=True (1000 ms) set
        # by _resume_with_reload, which prevents _apply_drift_correction from firing.
        self._last_advance_wt  = _monotonic() + 3.0   # legacy field; keep for play_pause reset
        self._last_advance_pos = float(max(0, pos_ms))
        self._gst_pos_adv_ms   = -1.0   # re-initialise on first drift query after reload
        self._gst_pos_adv_wt   = -1.0

        if pos_ms > 200:
            def _do_seek(p=pos_ms, _sil=silent):
                self.seek(p)
                def _after_seek(_sil=_sil):
                    self._anchor_from_gst()   # re-anchor so seekbar is accurate
                    if not _sil:
                        self.sig_busy.emit(False)
                    self._silent_recovery = False
                QTimer.singleShot(350, _after_seek)
            QTimer.singleShot(400, _do_seek)
        else:
            def _after_preroll(_sil=silent):
                self._anchor_from_gst()
                if not _sil:
                    self.sig_busy.emit(False)
                self._silent_recovery = False
            QTimer.singleShot(500, _after_preroll)

    def _resume_with_reload(self, fallback_ms: int = 0):
        """Reload pipeline at current position, reacquiring the PipeWire sink.

        Args:
            fallback_ms: Seek target if GStreamer query_position returns 0 (pipeline
                         may already be NULL/READY).  Pass int(self._pos_anchor_ms).
        """
        # Guard against re-entrant calls (e.g. WARNING + ERROR arriving together,
        # or _check_sink_health firing while a reload is already in progress).
        # Without this the pipeline gets reloaded twice, producing a double-seek
        # that makes the slider bounce back and forth.
        if self._reloading:
            return
        self._reloading = True

        # Prefer _last_filepath (always up-to-date); fall back to URI property.
        fp = self._last_filepath
        if not fp:
            uri = ''
            try: uri = (self._pipe and self._pipe.get_property('uri')) or ''
            except Exception: pass
            if not uri:
                self._reloading = False
                return
            fp = _urlparse.unquote(uri.replace('file://', ''))

        # query_position is unreliable when pipeline is not PAUSED/PLAYING.
        # Prefer caller-supplied anchor; use GStreamer only when it returns >200 ms.
        gst_ms = 0
        if self._pipe:
            ok, pos = self._pipe.query_position(Gst.Format.TIME)
            gst_ms = pos // Gst.MSECOND if ok and pos > 0 else 0
        pos_ms = gst_ms if gst_ms > 200 else fallback_ms

        self._load_and_seek(fp, pos_ms, silent=True)
        # Release the guard after the pipeline has had time to preroll and seek.
        QTimer.singleShot(1000, lambda: setattr(self, '_reloading', False))

    def stop(self): self._destroy()

    def _reload_at_pos(self, fallback_ms: int = 0):
        """Reload the current file at the current position, preserving playback.
        Safe to call from main thread only; may be called multiple times (idempotent).
        Uses _reload_guard (separate from _reloading) so WARNING-triggered reloads
        don't block ERROR/sink-stolen recovery paths.

        Args:
            fallback_ms: Seek target if GStreamer query_position returns 0 (pipeline
                         may already be degraded).  Pass int(self._pos_anchor_ms).
        """
        if not self._pipe:
            return
        # Use a separate guard from _resume_with_reload so WARNING and ERROR
        # recovery paths don't mutually block each other.
        if self._reload_guard:
            return
        self._reload_guard = True
        try:
            ok, pos = self._pipe.query_position(Gst.Format.TIME)
            gst_ms  = pos // Gst.MSECOND if ok and pos > 0 else 0
            pos_ms  = gst_ms if gst_ms > 200 else fallback_ms
            fp = self._last_filepath
            if not fp:
                return
            self._silent_recovery = True
            self.load(fp)
            self._pause_ts = 0.0
            if pos_ms > 200:
                # Same as _resume_with_reload: wait for preroll before seeking.
                def _do_seek_silent(p=pos_ms):
                    self.seek(p)
                    def _finish():
                        self._anchor_from_gst()
                        self._silent_recovery = False
                    QTimer.singleShot(350, _finish)
                QTimer.singleShot(400, _do_seek_silent)
            else:
                QTimer.singleShot(500, lambda: setattr(self, '_silent_recovery', False))
        finally:
            QTimer.singleShot(600, lambda: setattr(self, '_reload_guard', False))

    def seek(self, ms: int):
        if not self._pipe:
            return
        # Only seek when the pipeline is in PAUSED or PLAYING state to avoid hangs/crashes.
        # timeout=0 is non-blocking — we already have _seek_retries for the case where
        # the pipeline hasn't reached a seekable state yet, so a blocking wait is not needed.
        _, state, _pending = self._pipe.get_state(timeout=0)
        if state not in (Gst.State.PAUSED, Gst.State.PLAYING):
            # Defer seek, but limit retries to prevent infinite loop
            _retry = self._seek_retries
            if _retry < 6:
                self._seek_retries = _retry + 1
                QTimer.singleShot(100, lambda: self.seek(ms))
            return
        self._seek_retries = 0
        try:
            target_ns = max(0, ms) * Gst.MSECOND
            self._seek_target_ns = target_ns
            self._seek_wall_t    = _monotonic()   # wall-clock anchor for timeout fallback
            # Set position anchor immediately to seek target — UI updates at zero latency
            # even before GStreamer has finished the seek.
            self._anchor_now(float(max(0, ms)))
            # Increment serial BEFORE seek so old GLib bus messages arriving after
            # the serial bump are tagged with the new serial and can be filtered.
            self._spec_serial += 1
            self._viz_spec[:] = MIN_DB
            self._viz_col_buf[:] = 0.0
            self._viz_bar_buf[:] = 0.0
            self._viz_discard_until = _monotonic() + 0.15   # skip buffered pre-seek frames
            self._pipe.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                target_ns)
            if self._playing:
                self._pipe.set_state(Gst.State.PLAYING)
                self._start_pos_burst(8)
            # Schedule a single anchor re-confirmation once GStreamer has settled.
            # ACCURATE seeks may land a few ms off target; this corrects the anchor
            # without any visible jump (drift correction threshold is 80 ms).
            # Runs on the GLib thread to avoid any main-thread blocking.
            _seek_ms = float(max(0, ms))
            def _confirm_anchor_glib(seek_target=_seek_ms):
                try:
                    pipe = self._pipe
                    if not pipe or not self._playing:
                        return False
                    ok2, p2 = pipe.query_position(Gst.Format.TIME)
                    if ok2 and p2 >= 0:
                        confirmed_ms = p2 / Gst.MSECOND
                        if abs(confirmed_ms - seek_target) < 80:
                            self._sig_drift_gst_ms.emit(confirmed_ms, _monotonic())
                except Exception:
                    pass
                return False
            def _schedule_confirm_anchor():
                GLib.idle_add(_confirm_anchor_glib)
            QTimer.singleShot(250, _schedule_confirm_anchor)
            self.sig_seek_flush.emit()
        except Exception as ex:
            print(f'[Player] seek error: {ex}')
        self.sig_seek.emit()

    def set_volume(self, v: float):
        self._volume = max(0.0, min(1.0, v))
        if self._pipe: self._pipe.set_property('volume', self._volume)

    def set_viz_tables(self, ba, bb, bt, col_idx, smooth_entries, inertia,
                       overlay_cb=None):
        """Called from ControlBar (main thread) to update viz mapping tables.

        Pre-computes every per-frame lookup so _compute_viz_frame is purely
        in-place numpy with zero Python-level allocation per call.
        """
        self._viz_ba      = ba
        self._viz_bb      = bb
        self._viz_bt      = bt
        self._viz_inertia = inertia
        self._viz_overlay_cb = overlay_cb
        self._viz_spec[:] = MIN_DB   # reset inertia on table change

        if col_idx is not None:
            iw = len(col_idx)
            self._viz_col_buf  = _np.zeros(iw, dtype=_np.float32)
        else:
            self._viz_col_buf  = _np.zeros(1, dtype=_np.float32)

        # Build smooth entries as contiguous arrays once — avoid per-frame attribute
        # lookup and list iteration inside _compute_viz_frame.
        # _viz_smooth_d   : (M,)   int32  — destination bar indices
        # _viz_smooth_nb  : (M, K) int32  — neighbour indices (ragged → padded)
        # _viz_smooth_wk  : (M, K) float32 — neighbour weights
        # For M=0 (no smoothing) all are empty; _compute_viz_frame checks once.
        if smooth_entries:
            _d_list, _nb_list, _wk_list = [], [], []
            max_k = max(len(nb) for _, (nb, _) in smooth_entries)
            for d, (nb_arr, wk_arr) in smooth_entries:
                k = len(nb_arr)
                # Pad to max_k with the last valid entry (weight 0 → no contribution)
                if k < max_k:
                    nb_pad = _np.concatenate([nb_arr,
                        _np.full(max_k - k, nb_arr[-1], dtype=_np.int32)])
                    wk_pad = _np.concatenate([wk_arr,
                        _np.zeros(max_k - k, dtype=_np.float32)])
                else:
                    nb_pad = nb_arr; wk_pad = wk_arr
                _d_list.append(d); _nb_list.append(nb_pad); _wk_list.append(wk_pad)
            self._viz_sm_d  = _np.array(_d_list,  dtype=_np.int32)
            self._viz_sm_nb = _np.array(_nb_list, dtype=_np.int32)   # (M, K)
            self._viz_sm_wk = _np.array(_wk_list, dtype=_np.float32) # (M, K)
        else:
            self._viz_sm_d  = _np.empty(0, dtype=_np.int32)
            self._viz_sm_nb = _np.empty((0, 1), dtype=_np.int32)
            self._viz_sm_wk = _np.empty((0, 1), dtype=_np.float32)

    def set_viz_active(self, on: bool):
        self._viz_on = on
        self._update_spec_active()

    def set_overlay_needs_spectrum(self, on: bool):
        self._overlay_needs_spec = on
        self._update_spec_active()

    def _update_spec_active(self):
        # Enable/disable GStreamer spectrum FFT.
        # post-messages=false suppresses message delivery, but audioconvert still
        # converts every buffer to F32LE even when viz is off.  Setting interval
        # to a very large value stops the spectrum element from accumulating
        # samples, eliminating audioconvert CPU overhead when viz is inactive.
        need = self._viz_on or self._overlay_needs_spec
        if self._spec_el:
            self._spec_el.set_property('post-messages', bool(need))
            # interval: active=60 fps; inactive=~1 hour (effectively never fires)
            # inactive: 1 s — low enough overhead but fast to wake when re-enabled
            interval = self._SPEC_INTERVAL_NS if need else 1_000_000_000
            self._spec_el.set_property('interval', interval)
    def set_eq_enabled(self, enabled: bool):
        if self._eq_enabled == enabled:
            return
        self._eq_enabled = enabled
        # Rebuild the pipeline so EQ filters are added/removed (bit-perfect when off)
        if self._pipe:
            self._reload_current()
        else:
            self._apply_eq_to_filters()

    def _reload_current(self):
        """Reload the currently-playing track to rebuild the pipeline."""
        if not self._pipe:
            return
        ok, pos = self._pipe.query_position(Gst.Format.TIME)
        pos_ms = pos // Gst.MSECOND if ok else 0
        was_playing = self._playing
        fp = self._last_filepath
        if not fp:
            return
        self._destroy()
        self.load(fp)
        # Seek to saved position
        if pos_ms > 0:
            QTimer.singleShot(200, lambda: self.seek(pos_ms))
        if not was_playing:
            QTimer.singleShot(250, self.play_pause)

    def set_eq_bands(self, bands: List[tuple]):
        """bands: list of (freq, gain, Q)"""
        self._eq_bands = bands[:MAX_EQ_BANDS]  # truncate if too many
        self._apply_eq_to_filters()

    def _apply_eq_to_filters(self):
        """Update the properties of existing EQ filter elements (from GLib thread)."""
        if not self._eq_filters:
            return
        GLib.idle_add(self._apply_eq_to_filters_glib)

    def _apply_eq_to_filters_glib(self):
        if not self._eq_filters:
            return False
        fs = self._current_fs
        for i, filt in enumerate(self._eq_filters):
            if i < len(self._eq_bands) and self._eq_enabled:
                f0, gain, q = self._eq_bands[i]
                if gain == 0.0:
                    # Bypass: set coefficients for unit gain
                    b = [1.0, 0.0, 0.0]
                    a = [1.0, 0.0, 0.0]
                else:
                    try:
                        b0, b1, b2, a1, a2 = peaking_coefficients(fs, f0, gain, q)
                        b = [b0, b1, b2]
                        a = [1.0, a1, a2]
                    except Exception:
                        b = [1.0, 0.0, 0.0]
                        a = [1.0, 0.0, 0.0]
            else:
                # Bypass
                b = [1.0, 0.0, 0.0]
                a = [1.0, 0.0, 0.0]
            # Set coefficients using Python lists (GStreamer will convert)
            filt.set_property('b', b)
            filt.set_property('a', a)
        return False

    def _make_sink_bin(self):
        """Create a bin containing EQ (if any), spectrum (if available), and sink.
           Returns (bin, list_of_eq_filter_elements)."""
        elements = []
        eq_bin, eq_filters = self._create_eq_bin()
        if eq_bin:
            elements.append(eq_bin)

        if self._has_spec:
            # Burst messages from large FLAC decode blocks (libFLAC 1.5.0 at 44.1 kHz/16-bit
            # emits ~3 spectrum messages per 104 ms block) are handled in software:
            # _store_spectrum accumulates elapsed frames; _compute_viz_frame applies
            # alpha^N in one EMA step.  audiobuffersplit is intentionally omitted — it
            # causes caps-negotiation failures on some format/codec combinations that
            # result in silence, and its state-change locking can trigger pipeline crashes
            # when tracks are switched or focus is lost.
            spec_desc = (
                f'audioconvert ! audio/x-raw,format=F32LE '
                f'! spectrum name=bp_spec bands={GST_BANDS} '
                f'threshold={int(MIN_DB)} interval={self._SPEC_INTERVAL_NS} '
                f'post-messages=false message-magnitude=true message-phase=false'
            )
            try:
                spec = Gst.parse_bin_from_description(spec_desc, True)
                elements.append(spec)
            except Exception as e:
                print(f'[Player] spectrum creation failed: {e}')

        try:
            sink = Gst.parse_bin_from_description(self._out, True)
            elements.append(sink)
        except Exception as e:
            print(f'[Player] sink creation failed: {e}')
            return None, []

        if len(elements) == 1:
            # Only sink — wrap it with a ghost pad
            outer = Gst.Bin.new()
            outer.add(elements[0])
            sink_pad = elements[0].get_static_pad('sink')
            if not sink_pad:
                print('[Player] sink has no sink pad')
                return None, []
            ghost = Gst.GhostPad.new('sink', sink_pad)
            outer.add_pad(ghost)
            return outer, eq_filters

        # Chain elements: link src pad of element[i] to sink pad of element[i+1]
        outer = Gst.Bin.new()
        for el in elements:
            outer.add(el)
        for i in range(len(elements) - 1):
            src_pad  = elements[i].get_static_pad('src')
            sink_pad = elements[i + 1].get_static_pad('sink')
            if not src_pad or not sink_pad:
                print(f'[Player] linking error between element {i} and {i+1}: '
                      f'src={src_pad}, sink={sink_pad}')
                return None, []
            if src_pad.link(sink_pad) != Gst.PadLinkReturn.OK:
                print(f'[Player] pad link failed between element {i} and {i+1}')
                return None, []

        # Ghost pad on the first element's sink pad
        first_sink = elements[0].get_static_pad('sink')
        if not first_sink:
            print('[Player] first element has no sink pad')
            return None, []
        ghost = Gst.GhostPad.new('sink', first_sink)
        if not ghost:
            print('[Player] ghost pad creation failed')
            return None, []
        outer.add_pad(ghost)
        return outer, eq_filters

    def _create_eq_bin(self):
        """Create a bin containing MAX_EQ_BANDS audioiirfilter in series.
           Returns (bin, list_of_filters). Returns (None, []) when EQ is disabled
           so the pipeline remains bit-perfect (no float conversion forced)."""
        if MAX_EQ_BANDS == 0 or not self._eq_enabled:
            return None, []
        bin = Gst.Bin.new('eq_bin')
        filters = []
        prev = None
        for i in range(MAX_EQ_BANDS):
            filt = Gst.ElementFactory.make('audioiirfilter', f'eq_filter_{i}')
            if not filt:
                print('[Player] could not create audioiirfilter')
                return None, []
            # Default settings (bypassed) using Python lists
            filt.set_property('b', [1.0, 0.0, 0.0])
            filt.set_property('a', [1.0, 0.0, 0.0])
            bin.add(filt)
            filters.append(filt)
            if prev:
                # Link previous filter's src to this filter's sink
                prev_src = prev.get_static_pad('src')
                this_sink = filt.get_static_pad('sink')
                prev_src.link(this_sink)
            prev = filt

        # Add ghost pads
        if filters:
            sink_pad = filters[0].get_static_pad('sink')
            src_pad = filters[-1].get_static_pad('src')
            if sink_pad:
                ghost_sink = Gst.GhostPad.new('sink', sink_pad)
                bin.add_pad(ghost_sink)
            if src_pad:
                ghost_src = Gst.GhostPad.new('src', src_pad)
                bin.add_pad(ghost_src)
        return bin, filters

    @property
    def playing(self)     -> bool: return self._playing
    @property
    def has_pipe(self)    -> bool: return self._pipe is not None
    @property
    def has_spectrum(self)-> bool: return self._has_spec
    @property
    def current_fs(self)  -> int:  return self._current_fs
    @property
    def glib_loop(self)         : return self._glib_loop

    # ── Position anchor helpers ───────────────────────────────────────────────

    def _anchor_now(self, pos_ms: float):
        """Set anchor to pos_ms at the current wall-clock instant."""
        self._pos_anchor_ms = float(pos_ms)
        self._pos_anchor_wt = _monotonic()

    def _anchor_from_gst(self) -> bool:
        """Query GStreamer and update anchor. Returns True on success.
        Skips the query if the pipeline is not in a steady PLAYING state to
        avoid blocking the main thread during preroll or seek transitions."""
        if not self._pipe:
            return False
        _, st, pending = self._pipe.get_state(timeout=0)
        if st not in (Gst.State.PLAYING, Gst.State.PAUSED) or \
                pending != Gst.State.VOID_PENDING:
            return False
        ok, p = self._pipe.query_position(Gst.Format.TIME)
        if ok and p >= 0:
            self._anchor_now(p / Gst.MSECOND)
            return True
        return False

    def position_ms(self) -> int:
        """Return current playback position in ms.

        When playing, interpolates from the last anchor using the wall clock —
        this gives zero-latency, jitter-free updates immediately after seek,
        play, and pause events.  GStreamer is only queried periodically for
        drift correction (see _tick_pos).
        """
        if not self._pipe:
            return 0
        if self._pos_playing:
            elapsed = _monotonic() - self._pos_anchor_wt
            pos = self._pos_anchor_ms + elapsed * 1000.0
            # Clamp to [0, duration] when duration is known
            if self._dur_ms_cached > 0:
                pos = max(0.0, min(pos, float(self._dur_ms_cached)))
            return int(pos)
        else:
            # Paused: anchor holds the frozen position; no elapsed needed
            return int(self._pos_anchor_ms)

    def duration_ms(self) -> int:
        # Always return the cached value; the async GLib-thread query in
        # _drift_query_glib populates _dur_ms_cached without blocking the main thread.
        return self._dur_ms_cached

    def _destroy(self):
        was_playing = self._playing
        if self._pipe:
            self._pipe.set_state(Gst.State.NULL); self._pipe = None
        self._spec_el = None; self._playing = False; self._pos_timer.stop()
        if not self._silent_recovery:
            self._pos_playing   = False
            self._pos_anchor_ms = 0.0
            self._pos_anchor_wt = 0.0
        self._tick_n        = 0
        self._eq_filters = []
        self._dur_ms_cached = 0
        self._seek_target_ns = 0
        self._seek_wall_t    = 0.0
        self._pause_ts       = 0.0   # reset — prevent reload loop after ERROR/EOS
        self._reloading      = False  # reset — prevent guard staying locked after stop/error
        self._reload_guard   = False  # reset — WARNING-path guard
        if not self._silent_recovery:
            self._viz_bar_buf[:] = 0.0
            self._viz_col_buf[:] = 0.0
            self._viz_spec[:] = MIN_DB
            self._viz_discard_until = 0.0
        self._viz_last_stream_time = -1
        self._viz_accumulated_el = 0
        self._viz_has_new = False
        self._viz_has_any = False
        self._viz_mag_field_idx = -1   # reset field cache — new pipeline may differ
        self._last_advance_wt  = -1.0
        self._last_advance_pos = -1.0
        self._gst_pos_adv_ms   = -1.0
        self._gst_pos_adv_wt   = -1.0
        if was_playing and not self._silent_recovery:
            self.sig_playing.emit(False)

    def _start_pos_burst(self, n: int = 8):
        """Fire pos_timer at 100 ms for the next n ticks (after seek / resume),
        then revert to the normal 250 ms interval."""
        self._pos_timer_burst = n
        self._pos_timer.setInterval(100)

    def _tick_pos(self):
        """Pos timer tick: emit interpolated position and schedule drift correction.

        Normally fires at 250 ms.  After seek/resume, _start_pos_burst() switches
        it to 100 ms for a short window so the seekbar snaps quickly.
        Stall detection runs in _apply_drift_correction (real GStreamer positions).
        """
        _t0 = _monotonic()

        # Burst management — revert to slow rate when burst is exhausted
        burst = self._pos_timer_burst
        if burst > 0:
            self._pos_timer_burst = burst - 1
            if self._pos_timer_burst == 0:
                self._pos_timer.setInterval(250)
        # Always emit the interpolated value — zero latency
        pos = self.position_ms()
        self.sig_pos.emit(pos)

        _t1 = _monotonic()
        _tick_ms = (_t1 - _t0) * 1000.0

        # Detect late tick — Qt timer fired significantly after its scheduled interval
        _last = getattr(self, '_tick_last_wt', _t1)
        _interval = self._pos_timer.interval()
        _actual_gap_ms = (_t1 - _last) * 1000.0
        if _actual_gap_ms > _interval + 60:
            _pt = (_t1 - self._play_start_wt)
            print(f'[DIAG][tick] play+{_pt:.3f}s  LATE FIRE: expected={_interval}ms actual={_actual_gap_ms:.1f}ms'
                  f'  tick_work={_tick_ms:.2f}ms  pos={pos}ms', flush=True)
        self._tick_last_wt = _t1

        # Duration + drift correction — schedule a combined query on the GLib thread
        # every ~1000 ms (every 4th tick at 250 ms base).
        # query_duration and query_position are both potentially blocking under
        # PipeWire / TLP power management and must NOT run on the Qt main thread.
        # GLib.idle_add posts the query to the GLib main loop where GStreamer
        # natively operates.  Results come back via queued pyqtSignals
        # (_sig_dur_gst_ms, _sig_drift_gst_ms) which are thread-safe and deliver
        # to their handlers on the Qt main thread with zero blocking.
        # _drift_pending prevents overlapping queries if GLib is briefly busy.
        tick_n = self._tick_n + 1
        self._tick_n = tick_n
        if self._playing and self._pipe \
                and self._pos_timer_burst == 0 and not self._drift_pending:
            self._drift_pending = True
            self._drift_sched_wt = _t1   # record when we enqueued for round-trip measurement
            # timeout_add(1) instead of idle_add: schedules the callback to run
            # after the current GLib dispatch cycle completes (minimum 1 ms).
            # idle_add with PRIORITY_DEFAULT or HIGH can fire within the same
            # PipeWire bus message handler that triggered _tick_pos via the Qt
            # signal delivery, causing spa/loop.c recursion and 'loop_unlock' crash.
            # A 1 ms timeout guarantees we exit the current callback stack first.
            GLib.timeout_add(1, self._drift_query_glib)

        # ── Passive stall detection ───────────────────────────────────────────
        # Catches cases where the pipeline silently dies (audio device change,
        # Stall detection has moved to _apply_drift_correction which operates on
        # real GStreamer-queried positions.  Checking position_ms() here was broken:
        # that function returns an interpolated value that always advances while
        # _pos_playing=True, so frozen pipelines were never detected.

    def _drift_query_glib(self):
        """GLib thread: query pipeline position (drift) and duration if not yet cached."""

        _t0 = _monotonic()
        try:
            pipe = self._pipe
            if pipe and self._playing:
                _, st, pending = pipe.get_state(timeout=0)
                if st == Gst.State.PLAYING and pending == Gst.State.VOID_PENDING:
                    if self._dur_ms_cached == 0:
                        ok_d, d = pipe.query_duration(Gst.Format.TIME)
                        if ok_d and d > 0:
                            self._sig_dur_gst_ms.emit(d // Gst.MSECOND)
                    ok, p = pipe.query_position(Gst.Format.TIME)
                    _query_wt = _monotonic()
                    if ok and p >= 0:
                        _qms = (_query_wt - _t0) * 1000.0
                        if _qms > 30:
                            _pt = _query_wt - self._play_start_wt
                            print(f'[DIAG][drift_glib] play+{_pt:.3f}s  SLOW query={_qms:.1f}ms', flush=True)
                        self._sig_drift_gst_ms.emit(p / Gst.MSECOND, _query_wt)
        except Exception as _e:
            print(f'[DIAG][drift_glib] exception: {_e}')
        finally:
            _total = (_monotonic() - _t0) * 1000.0
            if _total > 50:
                print(f'[DIAG][drift_glib] TOTAL BLOCKED={_total:.1f}ms')
            self._drift_pending = False
        return False

    def _apply_drift_correction(self, gst_ms: float, query_wt: float):
        """Qt main thread: apply anchor correction if position has drifted."""
        if not self._pos_playing:
            return
        now = _monotonic()
        signal_latency_ms = (now - query_wt) * 1000.0
        gst_now_ms  = gst_ms + signal_latency_ms
        interp_ms   = self._pos_anchor_ms + (now - self._pos_anchor_wt) * 1000.0
        drift_ms    = gst_now_ms - interp_ms
        since_resume_ms = (now - self._resume_wt) * 1000.0
        if abs(drift_ms) > 100 and since_resume_ms > 1500:
            self._anchor_now(gst_now_ms)

        # ── Real-position stall detection ────────────────────────────────────
        # position_ms() is interpolated and always advances while _pos_playing=True,
        # so it cannot reveal a frozen pipeline.  GStreamer-queried values (gst_ms)
        # reflect actual playback state and freeze when the pipeline stalls.
        # Fires every ~250 ms in steady state (each _tick_pos non-burst cycle sends
        # one GLib query); a 700 ms no-advance window means detection within ~1 s.
        if not self._reloading and not self._reload_guard:
            if self._gst_pos_adv_ms < 0:
                # First query after load/resume — just initialise, don't compare yet.
                self._gst_pos_adv_ms = gst_ms
                self._gst_pos_adv_wt = query_wt
            elif gst_ms - self._gst_pos_adv_ms > 150:   # >150 ms forward = genuine progress
                self._gst_pos_adv_ms = gst_ms
                self._gst_pos_adv_wt = query_wt
            elif (query_wt - self._gst_pos_adv_wt) > 0.7:   # frozen for >700 ms
                print(f'[Player] GST position stalled at {gst_ms:.0f} ms — reloading pipeline')
                # Reset tracking before reload so the guard flip in _resume_with_reload
                # doesn't race with the next drift query.
                self._gst_pos_adv_ms = gst_ms
                self._gst_pos_adv_wt = query_wt
                _fb = int(self._pos_anchor_ms)
                self._resume_with_reload(fallback_ms=_fb)

    def _on_dur_from_glib(self, dur_ms: int):
        """Qt main thread: store duration received from GLib thread.

        Receives the GStreamer-confirmed duration from _drift_query_glib via
        the _sig_dur_gst_ms queued signal.  Only stores and emits once — after
        the first successful query _dur_ms_cached stays set and _drift_query_glib
        skips the duration call automatically.
        """
        if self._dur_ms_cached == 0 and dur_ms > 0:
            self._dur_ms_cached = dur_ms
            self.sig_dur.emit(dur_ms)

    def _on_msg(self, _bus, msg):
        if msg.type == Gst.MessageType.EOS:
            self._playing = False; self._pos_timer.stop()
            self._pos_playing = False
            # Freeze anchor at end of track
            if self._dur_ms_cached > 0:
                self._anchor_now(float(self._dur_ms_cached))
            # Notify UI that playback stopped (viz must freeze immediately).
            # sig_playing and sig_end are both thread-safe pyqtSignals — they
            # are delivered queued to the main thread.
            # We intentionally do NOT touch the pipeline here; _advance() →
            # load() → _destroy() may run immediately on receipt of sig_end,
            # and any concurrent GLib idle touching the old pipeline causes
            # crashes (Repeat ONE, Shuffle, pipeline-NULL recovery, etc.).
            self.sig_playing.emit(False)
            self.sig_end.emit()
        elif msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            err_str = str(err)
            dbg_str = (dbg or '').lower()
            self._playing = False
            self._pos_playing = False
            self.sig_playing.emit(False)

            # "all buffers have been removed" (gst-resource-error-quark code 3) means
            # PipeWire reclaimed its buffers while we were PAUSED (another app grabbed
            # the sink, Bluetooth reconnect, etc.).  The pipeline is still structurally
            # alive — just reload it at the current position instead of destroying it.
            _is_buffers_removed = (
                'buffers have been removed' in err_str.lower() or
                'buffers have been removed' in dbg_str or
                ('resource' in err_str.lower() and '(3)' in err_str)
            )
            if _is_buffers_removed:
                print(f'[Player] sink buffers removed — reloading pipeline: {err_str}')
                _fb = int(self._pos_anchor_ms)
                QTimer.singleShot(0, lambda: self._resume_with_reload(fallback_ms=_fb))
                return

            # All other errors: tear down pipeline and surface to UI.
            # _destroy() calls pipeline.set_state(NULL) — must run on main thread.
            def _do_destroy():
                self._destroy()
                self.sig_err.emit(err_str)
            QTimer.singleShot(0, _do_destroy)
        elif msg.type == Gst.MessageType.WARNING:
            try:
                warn, dbg = msg.parse_warning()
                txt = (str(warn) + ' ' + (dbg or '')).lower()
                if any(k in txt for k in ('resource', 'write', 'open', 'pipewire',
                                           'pulse', 'alsa', 'sink', 'output')):
                    print(f'[Player] audio sink warning — reloading: {warn}')
                    _fb = int(self._pos_anchor_ms)
                    QTimer.singleShot(0, lambda: self._reload_at_pos(fallback_ms=_fb))
            except Exception:
                pass
        elif msg.type == Gst.MessageType.ELEMENT:
            need = self._viz_on or self._overlay_needs_spec
            if not need: return
            s = msg.get_structure()
            if s and s.get_name() == 'spectrum': self._store_spectrum(s)

    def _store_spectrum(self, s):
        """GLib thread: copy the latest spectrum magnitude data into the shared buffer.

        Called from _on_msg (GLib bus callback).  All writes are to pre-allocated
        numpy arrays; reference assignments are atomic under the GIL so no lock
        is needed between this thread and the Qt main thread's _compute_viz_frame.

        Design notes:
        - serial guard: reset inertia when a new track loads mid-stream.
        - discard window: suppress the first 150 ms after load/seek to avoid
          decoding artefacts.
        - stream-time delta: detect libFLAC 1.3+ 2-6× message gaps so inertia
          normalisation stays perceptually constant.
        - magnitude extraction: try fast GstValueList path first; fall back to
          s.to_string() parsing only when the binding doesn't expose __len__/n_values.
        """
        # ── Serial guard — new track resets inertia ───────────────────────────
        serial = self._spec_serial
        if serial != self._last_parsed_serial:
            self._last_parsed_serial = serial
            self._viz_spec[:] = MIN_DB
            self._viz_accumulated_el = 0
            self._viz_discard_until = _monotonic() + 0.15
            self._viz_has_new = False
            return

        # ── Discard window ────────────────────────────────────────────────────
        now = _monotonic()
        if now < self._viz_discard_until:
            return

        # ── Elapsed-frame estimation from stream-time ─────────────────────────
        # stream-time reflects *decode* time, not audio output time.  We use
        # only the delta to count spectrum messages, never as a position anchor.
        _elapsed = 1
        try:
            ok_st, _st_ns = s.get_uint64('stream-time')
            if ok_st and _st_ns >= 0:
                _st_ns = int(_st_ns)
                _last  = self._viz_last_stream_time
                if _last >= 0 and _st_ns > _last:
                    _elapsed = max(1, round((_st_ns - _last) / self._SPEC_INTERVAL_NS))
                self._viz_last_stream_time = _st_ns
        except Exception:
            pass
        # Accumulate elapsed frames across burst messages (libFLAC 1.5.0 at 44.1 kHz/16-bit
        # posts several spectrum messages in rapid succession from one large decode block).
        # _compute_viz_frame reads the total and applies alpha^N in a single EMA step,
        # giving the correct perceptual speed regardless of burst size.
        # Accumulate _elapsed directly here — no intermediary attribute — so that if
        # magnitude extraction fails below and we return early the count is still banked.
        self._viz_accumulated_el += _elapsed

        # ── Magnitude extraction ──────────────────────────────────────────────
        # Fast path: GstValueList via PyGObject (avoids full s.to_string()).
        # _viz_mag_field_idx caches the field index across calls (same structure
        # layout for every spectrum message on the same pipeline).
        raw = None
        try:
            # Use cached field index when available
            fi = getattr(self, '_viz_mag_field_idx', -1)
            if fi < 0:
                n_fields = s.n_fields()
                for i in range(n_fields):
                    if s.nth_field_name(i) == 'magnitude':
                        fi = i; break
                self._viz_mag_field_idx = fi
            if fi >= 0:
                val_list = s.get_value(s.nth_field_name(fi))
                if hasattr(val_list, '__len__'):
                    raw = _np.asarray(val_list, dtype=_np.float32)
                elif hasattr(val_list, 'n_values'):
                    raw = _np.fromiter(
                        (val_list.get_nth(i) for i in range(val_list.n_values)),
                        dtype=_np.float32, count=val_list.n_values)
                else:
                    raw = _np.array(list(val_list), dtype=_np.float32)
        except Exception:
            raw = None

        # Fallback: parse s.to_string() — slow but universally compatible
        if raw is None:
            try:
                txt = s.to_string()
                i0 = txt.find('magnitude=(float)')
                if i0 >= 0:
                    c     = txt[i0 + 17]
                    close = '}' if c == '{' else '>'
                    i1    = i0 + 17
                    i2    = txt.find(close, i1)
                    if i2 > i1:
                        raw = _np.fromstring(txt[i1 + 1:i2], dtype=_np.float32, sep=',')
            except Exception:
                pass

        if raw is None:
            return

        n = min(GST_BANDS, len(raw))
        if n <= 0:
            return

        # Merge raw magnitude into the shared buffer using element-wise maximum so that
        # every burst message from a single large libFLAC decode block contributes its
        # peak energy rather than the last message overwriting all previous ones.
        # _viz_accumulated_el was already incremented above (before this point), so the
        # EMA in _compute_viz_frame will apply alpha^N correctly for the full burst.
        _np.maximum(self._viz_mag_buf[:n], raw[:n], out=self._viz_mag_buf[:n])
        if n < GST_BANDS:
            self._viz_mag_buf[n:] = MIN_DB

        self._viz_has_new = True
        self._viz_has_any = True
        # Render timer (PreciseTimer, 16 ms) polls _viz_has_new each tick.
        # Flag handshake avoids 60 QueuedConnection deliveries/s through Qt's event loop.

    def _compute_viz_frame(self):
        """Main thread: called exclusively by _render_tick (60 fps).

        Reads the spectrum magnitude buffer written by the GLib thread and
        produces smoothed, normalised bar heights published into _viz_bar_buf.

        Everything runs in-place on pre-allocated numpy arrays — zero Python
        allocation per frame, zero GC pressure.

        Pipeline:
          1. Inertia (exponential moving average with alpha^N gap normalisation)
             N = total elapsed frames across all burst messages since last render,
             keeping perceptual speed constant regardless of FLAC block size.
          2. Linear interpolation from GST_BANDS FFT bins → VIZ_BANDS display bars
          3. Clip + normalise dB to [0, 1]
          4. Power-law perceptual gamma (0.38)
          5. Vectorised box smooth for low-frequency bars (avoids smearing)
          6. Publish to _viz_bar_buf; optional overlay callback
        """
        ba = self._viz_ba
        bb = self._viz_bb
        bt = self._viz_bt
        if ba is None or not self._viz_has_new:
            return
        self._viz_has_new = False

        try:
            sp    = self._viz_spec
            bh    = self._viz_bh_pre     # (VIZ_BANDS,) work buffer
            tmp   = self._viz_tmp_pre    # (VIZ_BANDS,) work buffer
            alpha = max(0.0, min(1.0, float(self._viz_inertia)))

            # ── 1. Inertia: alpha^N EMA with burst-accumulated N ──────────────
            # _viz_accumulated_el sums the elapsed-frame values of every spectrum
            # message that arrived since the last render tick.  For most codecs
            # el=1 per message; for libFLAC 1.5.0 at 44.1 kHz/16-bit a single
            # 104 ms decode block triggers ~3 messages, so el accumulates to ~3.
            # Applying alpha^N once (rather than alpha^1 three times) keeps the
            # animation speed identical to a codec that delivers single messages.
            el = max(1, min(self._viz_accumulated_el, 8))
            self._viz_accumulated_el = 0   # reset — count only messages since this render
            n = min(GST_BANDS, len(self._viz_mag_buf))
            if n > 0:
                ea        = alpha if (el <= 1 or alpha >= 1.0) else alpha ** el
                one_minus = 1.0 - ea
                sp[:n] *= ea
                sp[:n] += one_minus * self._viz_mag_buf[:n]
                # Reset the magnitude buffer back to floor so burst-accumulated peaks
                # from this render cycle do not bleed into the next frame.
                self._viz_mag_buf[:n] = MIN_DB

            # ── 2. Freq mapping: linear interpolation (GST_BANDS → VIZ_BANDS) ─
            # bh[d] = sp[ba[d]] + (sp[bb[d]] - sp[ba[d]]) * bt[d]
            _np.subtract(sp[bb], sp[ba], out=tmp)
            _np.multiply(tmp, bt, out=tmp)
            _np.add(sp[ba], tmp, out=bh)

            # ── 3. Clip + normalise dB → [0, 1] ──────────────────────────────
            _np.clip(bh, MIN_DB, 0.0, out=bh)
            bh -= MIN_DB          # shift: [MIN_DB, 0] → [0, -MIN_DB]
            bh *= (-1.0 / MIN_DB) # scale: → [0, 1]
            _np.clip(bh, 0.0, 1.0, out=bh)

            # ── 4. Perceptual gamma ───────────────────────────────────────────
            _np.power(bh, 0.38, out=bh)

            # ── 5. Box smooth (vectorised) ────────────────────────────────────
            # _viz_sm_d  (M,)   — destination bar indices
            # _viz_sm_nb (M, K) — neighbour indices (padded to uniform width K)
            # _viz_sm_wk (M, K) — neighbour weights
            # Result: bh[d] = dot(bh[neighbours], weights)  for each smoothed bar.
            sm_d  = self._viz_sm_d
            if len(sm_d):
                sm_nb = self._viz_sm_nb   # (M, K) int32
                sm_wk = self._viz_sm_wk   # (M, K) float32
                # bh[sm_nb] → (M, K) float32 gather; multiply weights; sum over K
                _np.einsum('mk,mk->m', bh[sm_nb], sm_wk, out=bh[sm_d])

            # ── 6. Publish + overlay callback ─────────────────────────────────
            _np.copyto(self._viz_bar_buf, bh)

            cb = self._viz_overlay_cb
            if cb is not None:
                # Pass the ndarray directly — BlackoutOverlay._paint_info only iterates it.
                # Avoids tolist() heap allocation on every 60 Hz frame.
                cb(self._viz_bar_buf)
        except Exception as _ve:
            print(f'[VizFrame] {type(_ve).__name__}: {_ve}')

class MprisServer(QObject):
    _MPRIS_XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/> <method name="Quit"/>
    <property name="CanQuit"             type="b"  access="read"/>
    <property name="CanRaise"            type="b"  access="read"/>
    <property name="HasTrackList"        type="b"  access="read"/>
    <property name="Identity"            type="s"  access="read"/>
    <property name="DesktopEntry"        type="s"  access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes"  type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>  <method name="Previous"/>
    <method name="Pause"/> <method name="PlayPause"/>
    <method name="Stop"/>  <method name="Play"/>
    <method name="Seek">
      <arg name="Offset"   type="x" direction="in"/>
    </method>
    <method name="SetPosition">
      <arg name="TrackId"  type="o" direction="in"/>
      <arg name="Position" type="x" direction="in"/>
    </method>
    <method name="OpenUri"><arg name="Uri" type="s" direction="in"/></method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s"     access="read"/>
    <property name="LoopStatus"     type="s"     access="readwrite"/>
    <property name="Rate"           type="d"     access="readwrite"/>
    <property name="Shuffle"        type="b"     access="readwrite"/>
    <property name="Metadata"       type="a{sv}" access="read"/>
    <property name="Volume"         type="d"     access="readwrite"/>
    <property name="Position"       type="x"     access="read"/>
    <property name="MinimumRate"    type="d"     access="read"/>
    <property name="MaximumRate"    type="d"     access="read"/>
    <property name="CanGoNext"      type="b"     access="read"/>
    <property name="CanGoPrevious"  type="b"     access="read"/>
    <property name="CanPlay"        type="b"     access="read"/>
    <property name="CanPause"       type="b"     access="read"/>
    <property name="CanSeek"        type="b"     access="read"/>
    <property name="CanControl"     type="b"     access="read"/>
  </interface>
</node>
"""
    def __init__(self, player: Player, win: 'MainWindow', parent=None):
        super().__init__(parent)
        self._player = player; self._win = win
        self._conn: Optional[Gio.DBusConnection] = None
        self._reg_ids: list = []
        self._cur_track: Optional[Track] = None
        self._track_serial = 0
        self._cover_on: bool = True          # mirrors the Settings cover toggle
        self._art_tmp_path: Optional[str] = None   # last written temp cover file
        self._cached_art_uri: Optional[str] = None  # built in Qt thread
        self._pipeline_busy: bool = False    # True while pipeline is reloading
        GLib.idle_add(self._setup)

    def set_pipeline_busy(self, busy: bool):
        """Called when a pipeline reload starts/finishes. Disables MPRIS play/pause."""
        self._pipeline_busy = busy
        if busy:
            # Only hide play/pause capability — don't touch PlaybackStatus so
            # MPRIS clients (GNOME Shell, KDE) don't remove the player widget.
            GLib.idle_add(self._emit, ['CanPlay', 'CanPause'])
        else:
            # Reload done: restore capabilities and sync playback status together.
            GLib.idle_add(self._emit, ['CanPlay', 'CanPause', 'PlaybackStatus'])

    # Called by MainWindow whenever the cover switch is toggled
    def set_cover_on(self, enabled: bool):
        self._cover_on = enabled
        # Rebuild art URI with new setting (in Qt thread — safe for disk I/O)
        self._cached_art_uri = self._build_art_uri(self._cur_track)
        GLib.idle_add(self._emit, ['Metadata'])

    def _setup(self):
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(MprisServer._MPRIS_XML)
            for iface in node.interfaces:
                # Use only the new API (PyGObject >= 3.51) - old register_object is deprecated
                if hasattr(self._conn, 'register_object_with_closures'):
                    rid = self._conn.register_object_with_closures(
                        '/org/mpris/MediaPlayer2', iface,
                        self._handle_method, self._handle_get, self._handle_set)
                    self._reg_ids.append(rid)
                else:
                    # Skip registration if new API not available to avoid deprecation warning
                    print('[MPRIS] register_object_with_closures not available, skipping MPRIS registration')
                    return False
            Gio.bus_own_name_on_connection(self._conn,
                'org.mpris.MediaPlayer2.voidpulse',
                Gio.BusNameOwnerFlags.NONE, None, None)
        except Exception as e:
            print(f'[MPRIS] {e}')
        return False

    def _handle_method(self, conn, sender, obj, iface, method, params, inv):
        inv.return_value(None)
        QTimer.singleShot(0, lambda m=method, p=params: self._dispatch(m, p))

    def _dispatch(self, method, params):
        w = self._win; p = self._player
        # While pipeline is reloading, ignore transport commands to avoid
        # re-entrant reloads. CanPlay/CanPause already signal False to the client.
        if self._pipeline_busy and method in ('PlayPause', 'Play', 'Pause'):
            return
        if   method == 'PlayPause': w._play_pause()
        elif method == 'Play':
            if not p.playing: w._play_pause()
        elif method == 'Pause':
            if p.playing: w._play_pause()
        elif method == 'Stop':
            p.stop(); w._ctrlbar.set_play_icon(False); self.notify_status()
            w._ctrlbar._reset_idle_timer()
        elif method == 'Next':   w._next_track(); w._ctrlbar._reset_idle_timer()
        elif method == 'Previous': w._prev_track(); w._ctrlbar._reset_idle_timer()
        elif method == 'Raise':  w.raise_(); w.activateWindow()
        elif method == 'Quit':   w.close()
        elif method == 'Seek':   p.seek(max(0, p.position_ms()+params[0]//1000))
        elif method == 'SetPosition': p.seek(params[1]//1000)

    def _handle_get(self, conn, sender, obj, iface, prop):
        if iface == 'org.mpris.MediaPlayer2':
            d = {'CanQuit': GLib.Variant('b', True), 'CanRaise': GLib.Variant('b', True),
                 'HasTrackList': GLib.Variant('b', False),
                 'Identity': GLib.Variant('s', 'VoidPulse'),
                 'DesktopEntry': GLib.Variant('s', 'voidpulse'),
                 'SupportedUriSchemes': GLib.Variant('as', ['file']),
                 'SupportedMimeTypes': GLib.Variant('as',
                    ['audio/mpeg','audio/flac','audio/ogg','audio/opus','audio/mp4'])}
            return d.get(prop)
        if iface == 'org.mpris.MediaPlayer2.Player':
            return self._pp(prop)
        return None

    def _pp(self, prop):
        p = self._player; w = self._win
        if prop == 'PlaybackStatus':
            return GLib.Variant('s',
                'Playing' if p.playing else 'Paused' if p.has_pipe else 'Stopped')
        if prop == 'LoopStatus':
            m = w._ctrlbar.btn_rep.current_mode()
            return GLib.Variant('s', 'Track' if m==RepeatMode.ONE
                                else 'Playlist' if m==RepeatMode.ALL else 'None')
        if prop == 'Rate':        return GLib.Variant('d', 1.0)
        if prop == 'Shuffle':     return GLib.Variant('b', w._shuffle)
        if prop == 'Metadata':    return self._meta()
        if prop == 'Volume':      return GLib.Variant('d', p._volume)
        if prop == 'Position':    return GLib.Variant('x', p.position_ms()*1000)
        if prop in ('MinimumRate','MaximumRate'): return GLib.Variant('d', 1.0)
        if prop in ('CanGoNext','CanGoPrevious','CanSeek','CanControl'):
            return GLib.Variant('b', True)
        if prop in ('CanPlay', 'CanPause'):
            return GLib.Variant('b', not self._pipeline_busy)
        return None

    def _meta(self):
        tid = f'/org/voidpulse/track/{self._track_serial}'; t = self._cur_track
        if t is None:
            return GLib.Variant('a{sv}', {'mpris:trackid': GLib.Variant('o', tid)})
        d = {
            'mpris:trackid': GLib.Variant('o', tid),
            'xesam:title':   GLib.Variant('s', t.title or ''),
            'xesam:artist':  GLib.Variant('as', [t.artist] if t.artist else []),
            'xesam:album':   GLib.Variant('s', t.album or ''),
            'mpris:length':  GLib.Variant('x', int(t.duration*1_000_000)),
            'xesam:url':     GLib.Variant('s', Path(t.filepath).as_uri()),
        }
        art_uri = self._art_url_for(t)
        if art_uri:
            d['mpris:artUrl'] = GLib.Variant('s', art_uri)
        return GLib.Variant('a{sv}', d)

    def _art_ext(self, raw: bytes) -> str:
        """Detect image format from magic bytes."""
        if raw[:4] == b'\x89PNG':
            return 'png'
        return 'jpg'

    def _build_art_uri(self, t: Optional['Track']) -> Optional[str]:
        """
        Build a file:// URI for cover art. Called from Qt main thread so
        blocking disk I/O (mutagen) is safe and doesn't block the GLib loop.
        """
        if not self._cover_on or t is None:
            self._delete_art_tmp()
            return None
        raw = extract_cover_bytes(t.filepath)
        if not raw:
            self._delete_art_tmp()
            return None
        import tempfile
        ext    = self._art_ext(raw)
        digest = hashlib.md5(raw).hexdigest()[:12]
        tmp_path = os.path.join(tempfile.gettempdir(),
                                f'voidpulse_cover_{digest}.{ext}')
        if not os.path.exists(tmp_path):
            self._delete_art_tmp()
            try:
                with open(tmp_path, 'wb') as fh:
                    fh.write(raw)
            except OSError as e:
                print(f'[MPRIS] cover temp write failed: {e}')
                return None
        self._art_tmp_path = tmp_path
        return Path(tmp_path).as_uri()

    def _art_url_for(self, t: 'Track') -> Optional[str]:
        """Return cached art URI (built in Qt thread). Kept for backward compat."""
        return getattr(self, '_cached_art_uri', None)

    def _delete_art_tmp(self):
        if self._art_tmp_path and os.path.exists(self._art_tmp_path):
            try:
                os.unlink(self._art_tmp_path)
            except OSError:
                pass
        self._art_tmp_path = None

    def _handle_set(self, conn, sender, obj, iface, prop, value):
        if iface != 'org.mpris.MediaPlayer2.Player': return
        if prop == 'Volume':
            QTimer.singleShot(0, lambda v=value.unpack(): self._player.set_volume(v))
        elif prop == 'Shuffle':
            QTimer.singleShot(0, lambda v=value.unpack(): setattr(self._win, '_shuffle', v))

    def notify_track(self, track: Optional[Track]):
        self._cur_track = track; self._track_serial += 1
        # Build art URI in Qt main thread — extract_cover_bytes does disk I/O
        # via mutagen; doing it here avoids blocking the GLib main loop.
        self._cached_art_uri = self._build_art_uri(track)
        GLib.idle_add(self._emit, ['Metadata', 'PlaybackStatus'])

    def notify_status(self):
        # Emit only PlaybackStatus so MPRIS clients update the transport state
        # without triggering a full metadata refresh (which causes some clients
        # to temporarily hide the player widget).
        GLib.idle_add(self._emit, ['PlaybackStatus', 'CanPlay', 'CanPause'])

    def notify_seeked(self):
        """Emit the MPRIS Seeked signal so clients update their seekbars."""
        GLib.idle_add(self._emit_seeked)

    def _emit_seeked(self):
        if not self._conn: return False
        try:
            pos_us = self._player.position_ms() * 1000
            self._conn.emit_signal(None, '/org/mpris/MediaPlayer2',
                'org.mpris.MediaPlayer2.Player', 'Seeked',
                GLib.Variant('(x)', (pos_us,)))
        except Exception: pass
        return False

    def _emit(self, props):
        if not self._conn: return False
        try:
            changed = {p: v for p in props if (v := self._pp(p)) is not None}
            if changed:
                self._conn.emit_signal(None, '/org/mpris/MediaPlayer2',
                    'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                    GLib.Variant('(sa{sv}as)', ('org.mpris.MediaPlayer2.Player', changed, [])))
        except Exception: pass
        return False

# ══════════════════════════════════════════════════════════════════════════════
#  Seek slider (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
class SeekSlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName('seek'); self.setRange(0, 1000)
        self.setMinimumHeight(26)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        self._pressed = False
        self.setStyleSheet(f"""
            QSlider           {{ background: transparent; }}
            QSlider::groove:horizontal {{
                background: rgba(80,80,80,160); height: 4px; border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{ background: {ACC}; border-radius: 2px; }}
            QSlider::handle:horizontal {{
                background: {BG4}; border: 2px solid {ACC};
                width: 18px; height: 18px; border-radius: 9px; margin: -7px 0;
            }}
            QSlider::handle:horizontal:hover {{
                background: {BG4}; border: 3px solid {ACCH};
                width: 18px; height: 18px; border-radius: 9px; margin: -7px 0;
            }}
            QSlider::handle:horizontal:pressed {{
                background: {BG4}; border: 3px solid {ACCH};
                width: 18px; height: 18px; border-radius: 9px; margin: -7px 0;
            }}
        """)

    def _val_at(self, x: float) -> int:
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), int(max(0.0, x)), self.width())

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.sliderPressed.emit()
            val = self._val_at(e.position().x())
            self.setValue(val)
            self.sliderMoved.emit(val)
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._pressed:
            val = self._val_at(e.position().x())
            self.setValue(val)
            self.sliderMoved.emit(val)
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            val = self._val_at(e.position().x())
            self.setValue(val)
            self.sliderReleased.emit()
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    def update_accent(self, acc: str, acch: str):
        self.setStyleSheet(f"""
            QSlider           {{ background: transparent; }}
            QSlider::groove:horizontal {{
                background: rgba(80,80,80,160); height: 4px; border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{ background: {acc}; border-radius: 2px; }}
            QSlider::handle:horizontal {{
                background: {BG4}; border: 2px solid {acc};
                width: 18px; height: 18px; border-radius: 9px; margin: -7px 0;
            }}
            QSlider::handle:horizontal:hover {{
                background: {BG4}; border: 3px solid {acch};
                width: 18px; height: 18px; border-radius: 9px; margin: -7px 0;
            }}
            QSlider::handle:horizontal:pressed {{
                background: {BG4}; border: 3px solid {acch};
                width: 18px; height: 18px; border-radius: 9px; margin: -7px 0;
            }}
        """)

    def event(self, e: QEvent) -> bool:
        t = e.type()
        if t == QEvent.Type.TouchBegin:
            e.accept(); pts = e.points()
            if pts:
                self._pressed = True
                self.sliderPressed.emit()
                val = self._val_at(pts[0].position().x())
                self.setValue(val); self.sliderMoved.emit(val)
            return True
        if t == QEvent.Type.TouchUpdate:
            e.accept(); pts = e.points()
            if pts and self._pressed:
                val = self._val_at(pts[0].position().x())
                self.setValue(val); self.sliderMoved.emit(val)
            return True
        if t == QEvent.Type.TouchEnd:
            e.accept(); pts = e.points()
            if pts and self._pressed:
                val = self._val_at(pts[0].position().x())
                self.setValue(val)
            self._pressed = False
            self.sliderReleased.emit()
            return True
        return super().event(e)

# ══════════════════════════════════════════════════════════════════════════════
#  Long-press filter (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
class LongPressFilter(QObject):
    triggered = pyqtSignal(int, QPoint)
    DELAY_MS = 550; DRIFT_PX = 10

    def __init__(self, table):
        super().__init__(table)
        self._table = table; self._row = -1; self._gpos = QPoint(); self._start = QPoint()
        self._timer = QTimer(self); self._timer.setSingleShot(True)
        self._timer.setInterval(self.DELAY_MS); self._timer.timeout.connect(self._fire)
        # Touch double-tap detection
        self._last_tap_row = -1; self._last_tap_ms = 0

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            item = self._table.itemAt(event.pos())
            self._row = item.row() if item else -1
            if self._row >= 0:
                self._start = QPoint(event.pos())
                self._gpos  = self._table.viewport().mapToGlobal(event.pos())
                self._timer.start()
        elif t == QEvent.Type.MouseMove:
            if self._timer.isActive():
                d = event.pos() - self._start
                if abs(d.x())+abs(d.y()) > self.DRIFT_PX: self._timer.stop(); self._row = -1
        elif t in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            self._timer.stop()
        # Touch tap → synthesise double-click via rapid second tap on same row
        elif t == QEvent.Type.TouchEnd:
            pts = event.points()
            if pts:
                pos = pts[0].position().toPoint()
                item = self._table.itemAt(pos)
                row = item.row() if item else -1
                if row >= 0:
                    now = QDateTime.currentMSecsSinceEpoch()
                    if row == self._last_tap_row and (now - self._last_tap_ms) < 400:
                        self._table.row_activated.emit(row)
                        self._last_tap_row = -1
                    else:
                        self._last_tap_row = row; self._last_tap_ms = now
        return False

    def _fire(self):
        if self._row >= 0: self.triggered.emit(self._row, self._gpos); self._row = -1

# ══════════════════════════════════════════════════════════════════════════════
#  Track table (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
COLS  = ['Length', 'Title', 'Artist', 'Album', 'Sample Rate', 'Bit Depth', 'Type']
C_LEN=0; C_TIT=1; C_ART=2; C_ALB=3; C_SR=4; C_BD=5; C_TYP=6

class TrackTable(QTableWidget):
    row_activated  = pyqtSignal(int)
    ctx_requested  = pyqtSignal(int, QPoint)
    col_widths_changed = pyqtSignal(list)   # emitted after user resizes a column

    # Default column ratios (sum = 1.0); used for proportional sizing.
    _DEFAULT_COL_RATIOS = [72, 260, 180, 180, 92, 82, 62]  # raw weights
    _DEFAULT_COL_RATIOS = list(map(lambda w: w / 928, _DEFAULT_COL_RATIOS))  # 928 = sum

    # Current ratios (may be updated by user dragging or config restore)
    _col_ratios: list = []  # instance attribute set in __init__

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(COLS)); self.setHorizontalHeaderLabels(COLS)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False); self.setAlternatingRowColors(False); self.setWordWrap(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self._emit_ctx(pos))
        self.setIconSize(QSize(28, 28))
        hh = self.horizontalHeader()
        hh.setSectionsMovable(False)
        # Left-align all header labels
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # All columns Interactive — user can resize any column with the mouse.
        # setSectionResizeMode(Interactive) + cascadingSectionResizes(False) means
        # only the dragged column and its right neighbour change size; all others stay fixed.
        for col in range(len(COLS)):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        hh.setCascadingSectionResizes(False)
        hh.setMinimumSectionSize(30)
        hh.setStretchLastSection(False)
        # Ratios initialised to defaults; actual pixel widths applied in resizeEvent
        self._col_ratios = list(self._DEFAULT_COL_RATIOS)
        self._row_h = 44   # tracks current desired row height; re-applied after setRowCount resets
        self.verticalHeader().setDefaultSectionSize(44)
        QScroller.grabGesture(self.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        sp = QScrollerProperties()
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor,           0.35)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.MaximumVelocity,              0.8)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.AcceleratingFlickMaximumTime, 0.15)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.DragStartDistance,            0.005)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.VerticalOvershootPolicy,
                           QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy,
                           QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        QScroller.scroller(self.viewport()).setScrollerProperties(sp)
        self._lp = LongPressFilter(self); self.viewport().installEventFilter(self._lp)
        self._lp.triggered.connect(self.ctx_requested)
        self.doubleClicked.connect(lambda idx: self.row_activated.emit(idx.row()))
        # Manual sort — we keep _tracks in sync with visual order so row index is always correct
        self._sort_col = -1; self._sort_asc = True
        hh.sectionClicked.connect(self._on_header_clicked)
        # Emit col widths after user finishes dragging a section separator
        hh.sectionResized.connect(self._on_section_resized)
        self._covers_on = True
        self._col_resize_timer = QTimer(self)
        self._col_resize_timer.setSingleShot(True)
        self._col_resize_timer.setInterval(400)
        self._col_resize_timer.timeout.connect(self._emit_col_widths)
        self._tracks_ref = []
        self._fp_to_row: dict = {}   # filepath → row index, O(1) cover-loaded lookup
        _ensure_async_cover_loader().cover_loaded.connect(self._on_cover_loaded)

    def _on_cover_loaded(self, fp: str, size: int, radius: int):
        """Update table icon when an async cover arrives."""
        if size != 28 or not self._covers_on:
            return
        r = self._fp_to_row.get(fp, -1)
        if r < 0:
            return
        pm = _cover_cache.get((fp, 28, 4))
        item = self.item(r, C_TIT)
        if item and pm:
            item.setIcon(QIcon(pm))

    def _on_section_resized(self, _logical, _old, _new):
        # Debounce: only emit after user stops dragging for 400 ms
        self._col_resize_timer.start()

    def _emit_col_widths(self):
        """Convert current pixel widths to ratios and emit."""
        total = sum(self.columnWidth(c) for c in range(len(COLS)))
        if total <= 0:
            return
        ratios = [self.columnWidth(c) / total for c in range(len(COLS))]
        self._col_ratios = ratios
        self.col_widths_changed.emit(ratios)

    def _apply_ratios(self):
        """Apply stored ratios to actual pixel widths based on viewport width."""
        vp_w = self.viewport().width()
        if vp_w <= 0:
            return
        ratios = self._col_ratios
        if not ratios or len(ratios) != len(COLS):
            ratios = self._DEFAULT_COL_RATIOS
        # Distribute pixels; last column gets the remainder to avoid gaps
        widths = [max(30, int(r * vp_w)) for r in ratios]
        diff = vp_w - sum(widths)
        widths[-1] = max(30, widths[-1] + diff)
        hh = self.horizontalHeader()
        hh.sectionResized.disconnect(self._on_section_resized)
        for col, w in enumerate(widths):
            self.setColumnWidth(col, w)
        hh.sectionResized.connect(self._on_section_resized)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_ratios()

    def restore_col_widths(self, ratios: list):
        """Restore column ratios (list of floats, sum ≈ 1.0) and apply."""
        if not ratios or len(ratios) != len(COLS):
            return
        total = sum(ratios)
        if total <= 0:
            return
        self._col_ratios = [r / total for r in ratios]
        self._apply_ratios()

    def _emit_ctx(self, pos):
        item = self.itemAt(pos)
        if item: self.ctx_requested.emit(item.row(), self.viewport().mapToGlobal(pos))

    def populate(self, tracks, playing_idx=-1):
        self.setSortingEnabled(False)
        self.setRowCount(0); self.setRowCount(len(tracks))
        # Qt6 resets defaultSectionSize to the style default on setRowCount(0).
        # Re-apply our desired height so newly created rows get the correct size.
        self.verticalHeader().setDefaultSectionSize(self._row_h)
        self._tracks_ref = tracks  # keep ref so cover_ready can find the row
        # Build O(1) reverse index: filepath → row
        self._fp_to_row = {t.filepath: r for r, t in enumerate(tracks)}
        CHUNK = 200
        # Fill first chunk synchronously so rows appear immediately
        end = min(CHUNK, len(tracks))
        for r in range(end):
            self._fill_row(r, tracks[r])
        self.set_playing_row(playing_idx)
        # Fill the rest in deferred chunks so the event loop stays alive
        if len(tracks) > CHUNK:
            self._populate_deferred(tracks, playing_idx, CHUNK)

    def _populate_deferred(self, tracks, playing_idx, start):
        CHUNK = 200
        def _chunk(s):
            end = min(s + CHUNK, len(tracks))
            for r in range(s, end):
                self._fill_row(r, tracks[r])
            if end < len(tracks):
                QTimer.singleShot(0, lambda s2=end: _chunk(s2))
        QTimer.singleShot(0, lambda: _chunk(start))

    def _on_header_clicked(self, col: int):
        """Sort the underlying PlaylistPage._tracks via the page reference."""
        # Find the PlaylistPage parent
        page = self.parent()
        while page and not isinstance(page, PlaylistPage):
            page = page.parent()
        if page is None:
            return
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col; self._sort_asc = True
        # Key functions per column
        def sort_key(t):
            if col == C_LEN: return t.duration
            if col == C_TIT: return t.title.lower()
            if col == C_ART: return t.artist.lower()
            if col == C_ALB: return t.album.lower()
            if col == C_SR:  return t.sample_rate
            if col == C_BD:  return t.bit_depth
            if col == C_TYP: return t.file_type.lower()
            return ''
        # Remember currently playing track so we can update its index
        cur_fp = None
        if 0 <= page.playing_idx < len(page.tracks):
            cur_fp = page.tracks[page.playing_idx].filepath
        sorted_tracks = sorted(page.tracks, key=sort_key, reverse=not self._sort_asc)
        new_playing = next((i for i, t in enumerate(sorted_tracks) if t.filepath == cur_fp), -1)
        page.set_tracks(sorted_tracks, new_playing)
        # Update header indicator
        hh = self.horizontalHeader()
        hh.setSortIndicatorShown(True)
        hh.setSortIndicator(col, Qt.SortOrder.AscendingOrder if self._sort_asc
                                  else Qt.SortOrder.DescendingOrder)

    def _fill_row(self, row, t):
        for col, txt in enumerate([t.dur_str(), t.title, t.artist, t.album,
                                    t.sr_str(), t.bd_str(), t.file_type]):
            item = QTableWidgetItem(txt)
            if col == C_TIT and self._covers_on:
                pm = get_cover_pixmap(t.filepath, 28, 4)
                # pm is None when cover fetch is enabled but no embedded cover yet;
                # show the default clef placeholder in that case.
                if pm is None:
                    pm = draw_default_cover(28, 4)
                item.setIcon(QIcon(pm))
            align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            item.setTextAlignment(align); self.setItem(row, col, item)

    def set_covers_on(self, on: bool, tracks: list):
        self._covers_on = on
        self._tracks_ref = tracks  # keep ref for cover_ready slot
        self.setIconSize(QSize(28, 28) if on else QSize(0, 0))
        # Process in small chunks so the event loop stays responsive
        CHUNK = 80
        total = min(self.rowCount(), len(tracks))

        def _process_chunk(start: int):
            end = min(start + CHUNK, total)
            for r in range(start, end):
                t = tracks[r]
                item = self.item(r, C_TIT)
                if item:
                    if on:
                        pm = get_cover_pixmap(t.filepath, 28, 4)
                        item.setIcon(QIcon(pm if pm is not None else draw_default_cover(28, 4)))
                    else:
                        item.setIcon(QIcon())
            if end < total:
                QTimer.singleShot(0, lambda s=end: _process_chunk(s))

        if total > 0:
            _process_chunk(0)

    def set_playing_row(self, row):
        # Only repaint old and new rows — O(1) instead of O(n).
        prev = getattr(self, '_playing_row', -1)
        self._playing_row = row
        for r in (prev, row):
            if r < 0 or r >= self.rowCount():
                continue
            pl = (r == row)
            color = QColor(ACC if pl else FG)
            for c in range(self.columnCount()):
                item = self.item(r, c)
                if not item:
                    continue
                item.setForeground(color)
                f = item.font(); f.setBold(pl); item.setFont(f)

    def filter(self, query, tracks):
        q = query.lower().strip()
        for r in range(self.rowCount()):
            if r >= len(tracks): self.setRowHidden(r, True); continue
            t = tracks[r]
            ok = (not q or q in t.title.lower() or q in t.artist.lower()
                  or q in t.album.lower() or q in Path(t.filepath).name.lower())
            self.setRowHidden(r, not ok)

# ══════════════════════════════════════════════════════════════════════════════
#  Gallery view — virtual scroll, fully custom-painted (no per-card QWidget)
# ══════════════════════════════════════════════════════════════════════════════

class GalleryView(QWidget):
    """
    High-performance gallery: all cards drawn in a single paintEvent.
    Virtual scroll — only computes geometry, never creates per-card widgets.
    Cover pixmaps come from the existing get_cover_pixmap LRU cache.
    """
    row_activated = pyqtSignal(int)
    ctx_requested = pyqtSignal(int, QPoint)

    CARD_H_MIN = 80
    CARD_H_MAX = 220
    GAP        = 8
    MARGIN     = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks:       list  = []
        self._playing_idx:  int   = -1
        self._cover_on:     bool  = True
        self._card_h:       int   = 130
        self._filter_query: str   = ''
        self._vis_idx:      list  = []
        self._sort_col:     str   = ''
        self._sort_asc:     bool  = True
        self._layout_mode:  str   = 'gallery_z'  # 'gallery_z' | 'gallery_s'
        self._layout_ready: bool  = False         # True after first real viewport measure

        # Layout cache
        self._n_cols:       int   = 1
        self._card_h_act:   int   = 130
        self._card_w_act:   int   = 260
        self._total_h:      int   = 0

        # Interaction
        self._hovered_idx:  int   = -1
        self._press_pos:    QPoint = QPoint()
        self._press_vis_pos: int  = -1   # visual pos (into _vis_idx) at press
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.setInterval(600)
        self._long_press_timer.timeout.connect(self._on_long_press)

        # Deferred populate: set True when populate() called while hidden
        self._pending_populate: bool = False

        # String cache: track_idx -> (title, artist, fmt)
        self._str_cache:    dict  = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        # ── Sort bar ─────────────────────────────────────────────────────────
        self._sort_bar = QWidget()
        sort_bar = self._sort_bar
        sort_bar.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        sort_bar.setFixedHeight(36)
        sbl = QHBoxLayout(sort_bar); sbl.setContentsMargins(12, 0, 12, 0); sbl.setSpacing(4)
        self._sort_lbl = QLabel('Sort by:')
        self._sort_lbl.setStyleSheet(f'color:{FG2}; font-size:11px; background:transparent;')
        sbl.addWidget(self._sort_lbl)
        self._sort_btns = {}
        _btn_ss = self._sort_btn_ss()
        for key, label in [('title','Title'),('artist','Artist'),
                            ('album','Album'),('duration','Length'),('type','Type')]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(26); btn.setMaximumHeight(28)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet(_btn_ss)
            btn.clicked.connect(lambda _, k=key: self._on_sort(k))
            self._sort_btns[key] = btn
            sbl.addWidget(btn)
        sbl.addStretch()
        outer.addWidget(sort_bar)

        # ── Canvas inside QScrollArea ─────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setWidgetResizable(False)

        self._canvas = QWidget()
        self._canvas.setStyleSheet(f'background:{BG};')
        self._canvas.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._canvas.setMouseTracking(True)
        self._canvas.paintEvent        = self._canvas_paint
        self._canvas.mousePressEvent   = self._canvas_mouse_press
        self._canvas.mouseReleaseEvent = self._canvas_mouse_release
        self._canvas.mouseDoubleClickEvent = self._canvas_dblclick
        self._canvas.mouseMoveEvent    = self._canvas_mouse_move
        self._canvas.leaveEvent        = self._canvas_leave

        self._scroll.setWidget(self._canvas)
        outer.addWidget(self._scroll, 1)

        QScroller.grabGesture(self._scroll.viewport(),
                              QScroller.ScrollerGestureType.TouchGesture)
        sp = QScrollerProperties()
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor, 0.35)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.MaximumVelocity,    0.8)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.VerticalOvershootPolicy,
                           QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy,
                           QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        QScroller.scroller(self._scroll.viewport()).setScrollerProperties(sp)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(80)
        self._resize_timer.timeout.connect(self._on_resize_done)

        # Debounce timer for gallery-scale slider — fires after user stops dragging
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.setInterval(60)
        self._scale_timer.timeout.connect(self._on_scale_done)
        self._scale_spinner_on = False

        # Connect to async cover loader — repaint cards as covers arrive
        _ensure_async_cover_loader().cover_loaded.connect(self._on_cover_loaded)

    # ── Public API ────────────────────────────────────────────────────────────

    def populate(self, tracks: list, playing_idx: int = -1):
        self._tracks      = list(tracks)
        self._playing_idx = playing_idx
        self._str_cache   = {}
        self._hovered_idx = -1
        # Only recompute geometry when actually visible.
        # showEvent will call _apply_filter_and_layout when we become visible.
        if self.isVisible():
            self._apply_filter_and_layout()
        else:
            self._pending_populate = True

    def set_playing(self, idx: int):
        old = self._playing_idx
        self._playing_idx = idx
        self._invalidate_track(old)
        self._invalidate_track(idx)

    def set_covers_on(self, on: bool):
        self._cover_on = on
        self._canvas.update()

    def set_card_height(self, h: int):
        h = max(self.CARD_H_MIN, min(self.CARD_H_MAX, h))
        if h == self._card_h: return
        self._card_h = h
        # Show spinner overlay and defer layout until slider is idle
        if not self._scale_spinner_on:
            self._scale_spinner_on = True
            self._canvas.update()
        self._scale_timer.start()

    def _on_scale_done(self):
        """Called ~60 ms after the last set_card_height — do the real recompute."""
        self._recompute_layout()
        self._scale_spinner_on = False
        self._canvas.update()

    def set_layout_mode(self, mode: str):
        """'gallery_z' = left-to-right row fill, 'gallery_s' = boustrophedon rows."""
        if mode == self._layout_mode: return
        self._layout_mode = mode
        self._canvas.update()

    def filter(self, query: str, tracks: list):
        self._filter_query = query.lower().strip()
        self._apply_filter_and_layout()

    # ── Geometry ──────────────────────────────────────────────────────────────

    def _recompute_layout(self):
        vp_w = self._scroll.viewport().width()
        if vp_w <= 0:
            return
        self._layout_ready = True
        gap = self.GAP; margin = self.MARGIN
        avail = vp_w - margin * 2

        # Slider controls desired height. Derive a target aspect-ratio width (2:1)
        # then find how many columns fit, then stretch cards to fill the row exactly.
        card_h_desired = max(self.CARD_H_MIN, min(self.CARD_H_MAX, self._card_h))
        card_w_nominal = card_h_desired * 2  # approximate 2:1 aspect

        n_cols = max(1, (avail + gap) // (card_w_nominal + gap))
        # Each card gets exactly 1/n_cols of available width (fills the row perfectly)
        card_w_act = (avail - gap * (n_cols - 1)) // n_cols
        card_w_act = max(self.CARD_H_MIN * 2, card_w_act)

        # Height: keep the natural aspect ratio of the computed width (÷2), but
        # honour the slider as the upper bound so the slider still has visible effect.
        card_h_act = min(card_h_desired, max(self.CARD_H_MIN, card_w_act // 2))

        self._n_cols     = n_cols
        self._card_h_act = card_h_act
        self._card_w_act = card_w_act

        n_vis  = len(self._vis_idx)
        n_rows = max(1, (n_vis + n_cols - 1) // n_cols)
        self._total_h = margin * 2 + n_rows * card_h_act + max(0, n_rows - 1) * gap
        self._canvas.setFixedSize(vp_w, self._total_h)
        self._canvas.update()

    def _visual_col(self, row: int, logical_col: int) -> int:
        """Return the X-column index for a given (row, logical_col) pair.
        Z-mode: left-to-right every row.
        U-mode: left-to-right on even rows, right-to-left on odd rows (boustrophedon).
        """
        if self._layout_mode == 'gallery_s' and (row % 2 == 1):
            return self._n_cols - 1 - logical_col
        return logical_col

    def _card_rect(self, pos: int) -> QRect:
        margin = self.MARGIN; gap = self.GAP
        row = pos // self._n_cols
        logical_col = pos % self._n_cols
        col = self._visual_col(row, logical_col)
        x = margin + col * (self._card_w_act + gap)
        y = margin + row * (self._card_h_act + gap)
        return QRect(x, y, self._card_w_act, self._card_h_act)

    def _pos_at(self, pt: QPoint) -> int:
        """Visual position index into _vis_idx at canvas point, or -1."""
        margin = self.MARGIN; gap = self.GAP
        x = pt.x() - margin; y = pt.y() - margin
        if x < 0 or y < 0: return -1
        denom_w = self._card_w_act + gap
        denom_h = self._card_h_act + gap
        if denom_w <= 0 or denom_h <= 0: return -1
        col = x // denom_w
        row = y // denom_h
        if col >= self._n_cols: return -1
        if x - col * denom_w >= self._card_w_act: return -1
        if y - row * denom_h >= self._card_h_act: return -1
        # In U-mode odd rows are drawn right-to-left, so invert col to get logical pos
        logical_col = (self._n_cols - 1 - col
                       if self._layout_mode == 'gallery_s' and (row % 2 == 1)
                       else col)
        pos = row * self._n_cols + logical_col
        return pos if pos < len(self._vis_idx) else -1

    def _track_idx_at(self, pt: QPoint) -> int:
        pos = self._pos_at(pt)
        return self._vis_idx[pos] if pos >= 0 else -1

    def _invalidate_track(self, ti: int):
        if ti < 0: return
        try:    pos = self._vis_idx.index(ti)
        except ValueError: return
        self._canvas.update(self._card_rect(pos))

    # ── Filter ────────────────────────────────────────────────────────────────

    def _apply_filter_and_layout(self):
        q = self._filter_query
        if q:
            self._vis_idx = [
                i for i, t in enumerate(self._tracks)
                if (q in t.title.lower() or q in t.artist.lower()
                    or q in t.album.lower()
                    or q in Path(t.filepath).name.lower())]
        else:
            self._vis_idx = list(range(len(self._tracks)))
        # Invalidate the filepath→position lookup used by _on_cover_loaded
        self._fp_to_vis_positions = None
        self._recompute_layout()

    # ── Show / resize ─────────────────────────────────────────────────────────

    def showEvent(self, e):
        super().showEvent(e)
        # Process any populate() call that arrived while we were hidden
        if self._pending_populate:
            self._pending_populate = False
            self._apply_filter_and_layout()
            return
        # Recompute as soon as widget becomes visible so the viewport has a real width.
        # This eliminates the brief single-column flash when switching to gallery mode.
        # Set _layout_ready=False so paintEvent suppresses rendering until geometry is set.
        self._layout_ready = False
        QTimer.singleShot(0, self._recompute_layout)

    # ── Painting ──────────────────────────────────────────────────────────────

    def _canvas_paint(self, event):
        p = QPainter(self._canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = event.rect()
        gap = self.GAP; margin = self.MARGIN

        # Suppress all painting until the layout has been measured against a real
        # viewport width.  Without this guard the cards flash in a single column
        # for one frame while Qt is still sizing the widget.
        if not self._layout_ready or self._card_h_act <= 0 or self._n_cols <= 0:
            p.fillRect(clip, QColor(BG)); p.end(); return
        p.fillRect(clip, QColor(BG))

        row_stride = self._card_h_act + gap
        first_row  = max(0, (clip.top()    - margin) // row_stride)
        last_row   =        (clip.bottom() - margin) // row_stride

        pen_border  = QPen(QColor(BORD), 1.2)
        pen_hover   = QPen(QColor(B2),  1.2)
        pen_playing = QPen(QColor(ACC), 1.5)

        h = self._card_h_act
        title_sz  = max(12, min(16, h // 9 + 1))
        artist_sz = max(10, min(13, h // 11 + 1))
        info_sz   = max(9,  min(12, h // 13 + 1))

        f_base   = p.font()
        f_title  = QFont(f_base); f_title.setPixelSize(title_sz);  f_title.setBold(True)
        f_artist = QFont(f_base); f_artist.setPixelSize(artist_sz)
        f_info   = QFont(f_base); f_info.setPixelSize(info_sz)
        fm_title  = QFontMetrics(f_title)
        fm_artist = QFontMetrics(f_artist)

        cover_pad = 4          # padding around cover image inside card
        cover_sz  = h - cover_pad * 2 - 4; cover_r = 4

        for row in range(first_row, last_row + 1):
            for logical_col in range(self._n_cols):
                pos = row * self._n_cols + logical_col
                if pos >= len(self._vis_idx): break
                ti = self._vis_idx[pos]
                t  = self._tracks[ti]
                col = self._visual_col(row, logical_col)
                x  = margin + col * (self._card_w_act + gap)
                y  = margin + row * row_stride
                rect = QRectF(x + 0.5, y + 0.5, self._card_w_act - 1, h - 1)

                playing = (ti == self._playing_idx)
                hovered = (ti == self._hovered_idx)
                if playing:
                    p.setBrush(QBrush(QColor(SEL)));  p.setPen(pen_playing)
                elif hovered:
                    p.setBrush(QBrush(QColor(BG3)));  p.setPen(pen_hover)
                else:
                    p.setBrush(QBrush(QColor(BG2)));  p.setPen(pen_border)
                p.drawRoundedRect(rect, 8, 8)

                # Cover — drawn with uniform padding on all sides
                cover_x = x + cover_pad + 2
                cover_y = y + cover_pad + 2
                text_x  = x + 10
                if self._cover_on:
                    pm = get_cover_pixmap(t.filepath, cover_sz, cover_r)
                    if pm is None:
                        pm = draw_default_cover(cover_sz, cover_r)
                    if pm is not None:
                        p.drawPixmap(cover_x, cover_y, cover_sz, cover_sz, pm)
                    text_x = cover_x + cover_sz + 8

                # Text
                if ti not in self._str_cache:
                    sr_khz = f'{t.sample_rate/1000:.1f}kHz' if t.sample_rate else ''
                    bd_s   = f'{t.bit_depth}bit' if t.bit_depth else ''
                    parts  = [t.file_type.upper()]
                    if sr_khz: parts.append(sr_khz)
                    if bd_s:   parts.append(bd_s)
                    self._str_cache[ti] = (
                        t.title or Path(t.filepath).stem,
                        t.artist or '',
                        '  '.join(q2 for q2 in parts if q2))
                title_s, artist_s, fmt_s = self._str_cache[ti]

                text_w  = max(10, x + self._card_w_act - text_x - 8)
                show_fmt = h >= 60 and bool(fmt_s)
                block_h  = title_sz + 4 + artist_sz + (4 + info_sz if show_fmt else 0)
                ty       = y + (h - block_h) // 2

                p.setFont(f_title)
                p.setPen(QColor(ACC if playing else FG))
                p.drawText(QRect(int(text_x), ty, text_w, title_sz + 2),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           fm_title.elidedText(title_s, Qt.TextElideMode.ElideRight, text_w))

                p.setFont(f_artist)
                p.setPen(QColor(FG2))
                p.drawText(QRect(int(text_x), ty + title_sz + 4, text_w, artist_sz + 2),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           fm_artist.elidedText(artist_s, Qt.TextElideMode.ElideRight, text_w))

                if show_fmt:
                    p.setFont(f_info)
                    p.drawText(QRect(int(text_x),
                                     ty + title_sz + 4 + artist_sz + 4,
                                     text_w, info_sz + 2),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                               fmt_s)

        # ── Scale-change spinner overlay ──────────────────────────────────────
        if getattr(self, '_scale_spinner_on', False):
            vp = self._scroll.viewport()
            vw = vp.width(); vh = vp.height()
            # Dim the visible area
            p.fillRect(0, self._scroll.verticalScrollBar().value(),
                       vw, vh, QColor(0, 0, 0, 90))
            # Spinning arc centred in viewport
            cx = vw // 2
            cy = self._scroll.verticalScrollBar().value() + vh // 2
            r = 22
            angle = int((_monotonic() * 360)) % 360
            p.setPen(QPen(QColor(ACC), 3, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawArc(cx - r, cy - r, r * 2, r * 2,
                      angle * 16, 270 * 16)
            # Schedule another repaint to animate
            QTimer.singleShot(16, self._canvas.update)

        p.end()

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def _canvas_mouse_press(self, e: QMouseEvent):
        self._long_press_timer.stop()
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos      = e.pos()
            self._press_vis_pos  = self._pos_at(e.pos())
            if self._press_vis_pos >= 0:
                self._long_press_timer.start()
        elif e.button() == Qt.MouseButton.RightButton:
            ti = self._track_idx_at(e.pos())
            if ti >= 0:
                self.ctx_requested.emit(ti, e.globalPosition().toPoint())

    def _canvas_mouse_release(self, e: QMouseEvent):
        self._long_press_timer.stop()
        self._press_vis_pos = -1

    def _canvas_dblclick(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            ti = self._track_idx_at(e.pos())
            if ti >= 0:
                self.row_activated.emit(ti)

    def _canvas_mouse_move(self, e: QMouseEvent):
        if (e.pos() - self._press_pos).manhattanLength() > 8:
            self._long_press_timer.stop()
        pos = self._pos_at(e.pos())
        ti  = self._vis_idx[pos] if pos >= 0 else -1
        if ti != self._hovered_idx:
            old = self._hovered_idx
            self._hovered_idx = ti
            self._invalidate_track(old)
            self._invalidate_track(ti)

    def _canvas_leave(self, e):
        old = self._hovered_idx
        self._hovered_idx = -1
        self._invalidate_track(old)

    def _on_long_press(self):
        pos = self._press_vis_pos
        if pos >= 0 and pos < len(self._vis_idx):
            ti = self._vis_idx[pos]
            self.ctx_requested.emit(ti, self._canvas.mapToGlobal(self._press_pos))

    def _on_cover_loaded(self, fp: str, size: int, radius: int):
        """Repaint any visible cards whose cover just arrived from the async loader."""
        # Build a filepath -> list-of-positions map lazily on first use per layout.
        # Invalidated whenever _vis_idx changes (in _apply_filter_and_layout).
        fp_map = getattr(self, '_fp_to_vis_positions', None)
        if fp_map is None:
            fp_map = {}
            for pos, ti in enumerate(self._vis_idx):
                key = self._tracks[ti].filepath
                fp_map.setdefault(key, []).append(pos)
            self._fp_to_vis_positions = fp_map
        for pos in fp_map.get(fp, []):
            self._canvas.update(self._card_rect(pos))

    # ── Sort ─────────────────────────────────────────────────────────────────

    def _sort_btn_ss(self) -> str:
        return (
            f'QPushButton {{ background:{BG3}; color:{FG2}; border:1px solid {B2};'
            f' border-radius:5px; padding:2px 8px; font-size:11px;'
            f' min-height:26px; max-height:28px; }}'
            f'QPushButton:hover {{ border-color:{ACC}; color:{FG}; }}'
            f'QPushButton:checked {{ color:{ACC}; border-color:{ACC}; background:{BG3}; }}')

    def update_accent(self):
        """Refresh sort-bar button stylesheet after accent color change."""
        ss = self._sort_btn_ss()
        for btn in self._sort_btns.values():
            btn.setStyleSheet(ss)
        self._canvas.update()

    def refresh_theme(self):
        """Re-apply all palette globals after a dark/light switch."""
        self._sort_bar.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        self._sort_lbl.setStyleSheet(f'color:{FG2}; font-size:11px; background:transparent;')
        self._canvas.setStyleSheet(f'background:{BG};')
        self.update_accent()   # refresh sort buttons too
        self._canvas.update()

    def _on_sort(self, key: str):
        if self._sort_col == key:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = key; self._sort_asc = True
        for k, b in self._sort_btns.items():
            b.setChecked(k == self._sort_col)
            base = k.capitalize()
            b.setText(base + (' ▲' if self._sort_asc else ' ▼') if k == self._sort_col else base)

        def sort_fn(t):
            if key == 'title':    return t.title.lower()
            if key == 'artist':   return t.artist.lower()
            if key == 'album':    return t.album.lower()
            if key == 'duration': return t.duration
            if key == 'type':     return t.file_type.lower()
            return ''

        cur_fp = None
        if 0 <= self._playing_idx < len(self._tracks):
            cur_fp = self._tracks[self._playing_idx].filepath
        self._tracks = sorted(self._tracks, key=sort_fn, reverse=not self._sort_asc)
        self._str_cache = {}
        new_playing = next(
            (i for i, t in enumerate(self._tracks) if t.filepath == cur_fp), -1)
        self._playing_idx = new_playing
        self._apply_filter_and_layout()

        page = self.parent()
        while page and not isinstance(page, PlaylistPage):
            page = page.parent()
        if page:
            # Sync PlaylistPage internal state and repopulate the TABLE so it
            # reflects the new sort order if the user switches to classic view.
            # Do NOT call page.set_tracks() — it would re-run gallery.populate()
            # on an already-sorted gallery, causing a redundant full relayout.
            page._tracks = list(self._tracks)
            page._playing_idx = new_playing
            page.table.populate(page._tracks, new_playing)

    # ── Resize ───────────────────────────────────────────────────────────────

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._resize_timer.start()

    def _on_resize_done(self):
        self._recompute_layout()

# ══════════════════════════════════════════════════════════════════════════════
#  Playlist page  — supports classic (table) and gallery view modes
# ══════════════════════════════════════════════════════════════════════════════
class PlaylistPage(QWidget):
    play_track    = pyqtSignal(object, int)
    ctx_requested = pyqtSignal(object, int, QPoint)
    col_widths_changed = pyqtSignal(list)   # forwarded from TrackTable

    def __init__(self, tracks=None, label='', parent=None):
        super().__init__(parent)
        self._tracks = list(tracks or []); self._label = label; self._playing_idx = -1
        self._view_mode = 'classic'   # 'classic' | 'gallery_z' | 'gallery_s'

        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        self._stack = QStackedWidget()
        self.table = TrackTable(self)
        self.gallery = GalleryView(self)
        self._stack.addWidget(self.table)    # index 0 = classic
        self._stack.addWidget(self.gallery)  # index 1 = gallery
        lay.addWidget(self._stack)

        self.table.row_activated.connect(lambda r: self.play_track.emit(self, r))
        self.table.ctx_requested.connect(lambda r, pos: self.ctx_requested.emit(self, r, pos))
        self.table.col_widths_changed.connect(self.col_widths_changed)
        self.gallery.row_activated.connect(lambda r: self.play_track.emit(self, r))
        self.gallery.ctx_requested.connect(lambda r, pos: self.ctx_requested.emit(self, r, pos))

    @property
    def tracks(self):      return self._tracks
    @property
    def label(self):       return self._label
    @property
    def playing_idx(self): return self._playing_idx

    def set_tracks(self, tracks, playing_idx=-1):
        self._tracks = list(tracks); self._playing_idx = playing_idx
        self.table.populate(self._tracks, playing_idx)
        self.gallery.populate(self._tracks, playing_idx)

    def set_playing(self, idx):
        self._playing_idx = idx
        self.table.set_playing_row(idx)
        self.gallery.set_playing(idx)

    def set_covers_on(self, on: bool):
        self.table.set_covers_on(on, self._tracks)
        self.gallery.set_covers_on(on)

    def apply_filter(self, query):
        self.table.filter(query, self._tracks)
        self.gallery.filter(query, self._tracks)

    def set_view_mode(self, mode: str):
        """Switch between 'classic', 'gallery_z' and 'gallery_s'."""
        self._view_mode = mode
        if mode in ('gallery_z', 'gallery_s'):
            self.gallery.set_layout_mode(mode)
            self._stack.setCurrentIndex(1)
            # gallery.populate() already defers work when hidden; calling it here
            # only triggers a full layout recompute if the gallery is now visible.
            self.gallery.populate(self._tracks, self._playing_idx)
        else:
            self._stack.setCurrentIndex(0)

    def set_list_scale(self, row_h: int):
        """Set classic-view row height."""
        self.table._row_h = row_h
        self.table.verticalHeader().setDefaultSectionSize(row_h)
        # Resize existing rows
        for r in range(self.table.rowCount()):
            self.table.setRowHeight(r, row_h)

    def set_gallery_scale(self, card_h: int):
        """Set gallery card height."""
        self.gallery.set_card_height(card_h)

    def refresh_theme(self):
        """Propagate theme refresh to child views."""
        self.gallery.refresh_theme()
        self.table.update()

# ══════════════════════════════════════════════════════════════════════════════
#  Sidebar (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
class _PlaylistRowWidget(QWidget):
    """A sidebar playlist row: [label] [X btn] — delete button on the far right."""
    delete_clicked = pyqtSignal()
    select_clicked = pyqtSignal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(28)
        self.setMaximumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 4, 8, 4)
        lay.setSpacing(4)

        self._lbl = QLabel(label)
        self._lbl.setStyleSheet(f'color:{FG}; font-size:13px; background:transparent;')

        # Accent-coloured X button on the far right
        self._del_btn = QPushButton('✕')
        self._del_btn.setMinimumSize(24, 24)
        self._del_btn.setMaximumSize(28, 28)
        self._del_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._del_btn.setStyleSheet(
            f'QPushButton {{ background:transparent; border:none; color:{ACC};'
            f' font-size:12px; font-weight:bold; border-radius:13px; padding:0; }}'
            f'QPushButton:hover {{ background:{BG4}; color:{ACCH}; }}'
            f'QPushButton:pressed {{ background:{BG3}; }}')
        self._del_btn.setToolTip('Remove playlist')
        self._del_btn.clicked.connect(self.delete_clicked)

        lay.addWidget(self._lbl, 1)
        lay.addWidget(self._del_btn)

    def set_selected(self, on: bool):
        c = ACC if on else FG
        self._selected = on
        self._lbl.setStyleSheet(f'color:{c}; font-size:13px; font-weight:{"bold" if on else "normal"}; background:transparent;')

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.select_clicked.emit()
        super().mousePressEvent(e)

    def update_accent(self):
        self._del_btn.setStyleSheet(
            f'QPushButton {{ background:transparent; border:none; color:{ACC};'
            f' font-size:12px; font-weight:bold; border-radius:11px; padding:0; }}'
            f'QPushButton:hover {{ background:{BG4}; color:{ACCH}; }}'
            f'QPushButton:pressed {{ background:{BG3}; }}')
        # Re-apply selected highlight with updated accent color
        if getattr(self, '_selected', False):
            self._lbl.setStyleSheet(
                f'color:{ACC}; font-size:13px; font-weight:bold; background:transparent;')

    def refresh_theme(self):
        """Re-apply FG/BG colours after a dark/light theme switch."""
        self.update_accent()
        # Unselected label uses FG which changes between dark and light
        if not getattr(self, '_selected', False):
            self._lbl.setStyleSheet(
                f'color:{FG}; font-size:13px; font-weight:normal; background:transparent;')

class Sidebar(QWidget):
    add_folder_req    = pyqtSignal()
    add_m3u_req       = pyqtSignal()
    new_playlist_req  = pyqtSignal()
    refresh_req       = pyqtSignal()
    remove_req        = pyqtSignal(int)
    source_selected   = pyqtSignal(int)
    search_changed    = pyqtSignal(str)
    export_m3u_req    = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('sidebar')
        self.setMinimumWidth(140)
        self.setMaximumWidth(400)
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        logo = QLabel('VoidPulse')
        self._logo_lbl = logo
        logo.setObjectName('logo_lbl')
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f'color:{ACC}; font-size:15px; font-weight:900;'
                           f' letter-spacing:5px; padding:16px 0 10px 0; background:{BG2};')
        root.addWidget(logo)

        sf = QWidget(); sf.setStyleSheet(f'background:{BG2};')
        self._sf = sf
        sfl = QHBoxLayout(sf); sfl.setContentsMargins(10,3,10,6)
        self._search = QLineEdit()
        self._search.setPlaceholderText('Search…'); self._search.setClearButtonEnabled(True)
        # Max height: double original (36px × 2 = 72, capped at 40 for compact look)
        self._search.setMaximumHeight(40)
        self._search.setStyleSheet(
            f'QLineEdit {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:10px; padding:3px 10px; font-size:12px; }}'
            f'QLineEdit:focus {{ border-color:{ACC}; }}')
        self._search.textChanged.connect(self.search_changed)
        sfl.addWidget(self._search); root.addWidget(sf)

        div = QFrame(); div.setFixedHeight(1); div.setStyleSheet(f'background:{BORD};')
        root.addWidget(div)

        lbl1 = QLabel('LIBRARY'); lbl1.setObjectName('sect_lbl'); root.addWidget(lbl1)

        self._lib_btn = QPushButton('  All Tracks')
        self._lib_btn.setStyleSheet(
            f'QPushButton {{ background:{BG3}; color:{ACC}; border:none;'
            f' border-left:3px solid {ACC}; border-radius:6px; text-align:left;'
            f' padding:6px 16px; font-weight:bold; font-size:12px; }}'
            f'QPushButton:hover {{ background:{BG4}; }}')
        self._lib_btn.setMaximumHeight(56)
        self._lib_btn.clicked.connect(lambda: self.source_selected.emit(-1))
        root.addWidget(self._lib_btn)

        lbl2 = QLabel("PLAYLISTS"); lbl2.setObjectName('sect_lbl'); root.addWidget(lbl2)

        # Scrollable playlist list using a QScrollArea with custom row widgets
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet('background:transparent; border:none;')
        # Enable touch scrolling for sidebar playlist area
        QScroller.grabGesture(scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        sp = QScrollerProperties()
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor,           0.35)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.MaximumVelocity,              0.8)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.AcceleratingFlickMaximumTime, 0.15)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.DragStartDistance,            0.005)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.VerticalOvershootPolicy,
                           QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        sp.setScrollMetric(QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy,
                           QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        QScroller.scroller(scroll.viewport()).setScrollerProperties(sp)
        self._pl_container = QWidget(); self._pl_container.setStyleSheet('background:transparent;')
        self._pl_layout = QVBoxLayout(self._pl_container)
        self._pl_layout.setContentsMargins(0,0,0,0); self._pl_layout.setSpacing(0)
        self._pl_layout.addStretch()
        scroll.setWidget(self._pl_container)
        root.addWidget(scroll, 1)

        self._pl_rows: list = []   # list of _PlaylistRowWidget
        self._selected_pl_idx = -1

        bdiv = QFrame(); bdiv.setFixedHeight(1); bdiv.setStyleSheet(f'background:{BORD};')
        root.addWidget(bdiv)

        bf = QWidget(); bf.setStyleSheet(f'background:{BG2};')
        self._bf = bf
        bfl = QVBoxLayout(bf); bfl.setContentsMargins(10,6,10,8); bfl.setSpacing(3)
        add_f    = QPushButton('＋  Add Folder')
        add_m    = QPushButton('＋  Import M3U / M3U8')
        new_pl   = QPushButton('+ Create New Playlist')
        new_pl.setToolTip('Create an empty playlist and save as M3U8')
        refresh  = QPushButton('↺  Refresh Library')
        refresh.setToolTip('Rescan all saved folders')
        export_m = QPushButton('↑  Export as M3U8')
        export_m.setToolTip('Export current playlist to an M3U8 file')
        add_f.clicked.connect(self.add_folder_req); add_m.clicked.connect(self.add_m3u_req)
        new_pl.clicked.connect(self.new_playlist_req)
        refresh.clicked.connect(self.refresh_req)
        export_m.clicked.connect(self.export_m3u_req)
        self._action_btns = [add_f, add_m, new_pl, refresh, export_m]
        # Responsive buttons — min 28px, max 36px (2× original); shrink gracefully
        for b in self._action_btns:
            b.setMinimumHeight(28)
            b.setMaximumHeight(36)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            b.setStyleSheet(
                f'QPushButton {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
                f' border-radius:5px; padding:2px 8px; font-size:11px; }}'
                f'QPushButton:hover {{ border-color:{ACC}; }}'
                f'QPushButton:pressed {{ background:{BG4}; }}')
            bfl.addWidget(b)
        root.addWidget(bf)

    def add_playlist(self, label: str):
        row = _PlaylistRowWidget(label)
        idx = len(self._pl_rows)
        self._pl_rows.append(row)
        # Insert before the trailing stretch
        self._pl_layout.insertWidget(self._pl_layout.count() - 1, row)
        row.select_clicked.connect(lambda i=idx: self._on_select(i))
        row.delete_clicked.connect(lambda i=idx: self._on_delete_clicked(i))

    def remove_playlist(self, idx: int):
        if not (0 <= idx < len(self._pl_rows)): return
        row = self._pl_rows.pop(idx)
        self._pl_layout.removeWidget(row); row.deleteLater()
        # Re-wire indices for remaining rows
        for i, r in enumerate(self._pl_rows):
            try: r.select_clicked.disconnect()
            except Exception: pass
            try: r.delete_clicked.disconnect()
            except Exception: pass
            r.select_clicked.connect(lambda _i=i: self._on_select(_i))
            r.delete_clicked.connect(lambda _i=i: self._on_delete_clicked(_i))
        if self._selected_pl_idx >= len(self._pl_rows):
            self._selected_pl_idx = -1

    def _on_select(self, idx: int):
        if self._selected_pl_idx >= 0 and self._selected_pl_idx < len(self._pl_rows):
            self._pl_rows[self._selected_pl_idx].set_selected(False)
        self._selected_pl_idx = idx
        self._pl_rows[idx].set_selected(True)
        self.source_selected.emit(idx)

    def update_accent(self):
        """Re-apply accent color to all inline-styled sidebar widgets."""
        self._lib_btn.setStyleSheet(
            f'QPushButton {{ background:{BG3}; color:{ACC}; border:none;'
            f' border-left:3px solid {ACC}; border-radius:6px; text-align:left;'
            f' padding:6px 16px; font-weight:bold; font-size:12px; }}'
            f'QPushButton:hover {{ background:{BG4}; }}')
        self._search.setStyleSheet(
            f'QLineEdit {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:10px; padding:3px 10px; font-size:12px; }}'
            f'QLineEdit:focus {{ border-color:{ACC}; }}')
        logo = self.findChild(QLabel, 'logo_lbl')
        if logo:
            logo.setStyleSheet(
                f'color:{ACC}; font-size:15px; font-weight:900;'
                f' letter-spacing:5px; padding:16px 0 10px 0; background:{BG2};')
        for row in self._pl_rows:
            row.update_accent()

    def refresh_theme(self):
        """Re-apply all palette globals after a dark/light switch."""
        self._sf.setStyleSheet(f'background:{BG2};')
        self._bf.setStyleSheet(f'background:{BG2};')
        for b in self._action_btns:
            b.setStyleSheet(
                f'QPushButton {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
                f' border-radius:5px; padding:2px 8px; font-size:11px; }}'
                f'QPushButton:hover {{ border-color:{ACC}; }}'
                f'QPushButton:pressed {{ background:{BG4}; }}')
        self.update_accent()   # logo, lib_btn, search
        for row in self._pl_rows:
            row.refresh_theme()   # also updates FG for unselected labels

    def _on_delete_clicked(self, idx: int):
        if not (0 <= idx < len(self._pl_rows)): return
        name = self._pl_rows[idx]._lbl.text()
        reply = QMessageBox.question(
            self, 'Remove Playlist',
            f'Remove "{name}" from the player?\n(Files will not be deleted)',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.remove_req.emit(idx)

# ══════════════════════════════════════════════════════════════════════════════
#  Repeat button (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
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
#  Control bar (with EQ button)
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
#  Full-screen toggle button (painted 4 outward arrows)
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

    @property
    def is_busy(self) -> bool:
        return self._busy

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

class ControlBar(QFrame):
    cover_on_changed = pyqtSignal(bool)
    accent_changed   = pyqtSignal(str)
    settings_changed = pyqtSignal()   # emitted whenever a persistable setting changes

    def __init__(self, player: Player, parent=None):
        super().__init__(parent)
        self.setObjectName('ctrlbar'); self.setFixedHeight(172)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        self._player    = player
        self._dur_ms    = 0
        self._seeking   = False
        self._viz_on    = True
        self._overlay_viz_enabled = False
        self._overlay_open        = False   # True while BlackoutOverlay is visible
        self._log_scale = True
        self._bar_x0    = _np.zeros(VIZ_BANDS, dtype=_np.int32)
        self._col_bar   = _np.full(1, -1, dtype=_np.int32)  # (iw,) rebuilt in _precompute_bars
        self._col_has_bar  = _np.zeros(1, dtype=bool)          # (iw,) precomputed mask
        self._col_bar_safe = _np.zeros(1, dtype=_np.int32)     # (iw,) 0-clamped for safe gather
        self._bar_bw       = 1
        self._cap_radius   = 0
        self._cap_r_offsets = _np.empty(0, dtype=_np.int32)  # (n_cap_pix,) row deltas
        self._cap_c_offsets = _np.empty(0, dtype=_np.int32)  # (n_cap_pix,) col deltas
        self._bar_color = QColor(44, 36, 36)
        self._cur_track: Optional[Track] = None
        self._inertia   = 0.5
        self._viz_paused  = False
        self._focus_paused = False

        self._seek_pending = False
        self._seek_gen    = 0
        self._delay_ms    = 0

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
        self._px_col_y0:  object = None   # (iw,) int32 — bar top row per column
        self._px_row_idx: object = None   # (ih, 1) int32 — row indices for broadcast
        self._render_last_wt:    float = 0.0   # timestamp of last update() call

        # Settings and EQ popups (lazy-created)
        self._settings_popup: Optional[SettingsPopup] = None
        self._eq_popup: Optional[EqPopup] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18,14,18,12); root.setSpacing(10)

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
        # Cover thumbnail — uses CSS opacity instead of QGraphicsOpacityEffect
        self._cover_lbl = QLabel()
        self._cover_lbl.setFixedSize(_COVER_SZ, _COVER_SZ)
        self._cover_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._cover_lbl.setStyleSheet(
            'background:transparent; opacity:0.65;'
        )
        self._cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
               f' font-size:20px; border-radius:22px; padding:0; text-align:center; }}'
               f'QPushButton#ctrl:hover {{ color:{FG}; background:{BG3}; }}'
               f'QPushButton#ctrl:checked {{ color:{ACC}; background:transparent; }}'
               f'QPushButton#ctrl:pressed {{ background:{BG4}; }}')
        for b in (self.btn_shuf, self.btn_prev, self.btn_next): b.setStyleSheet(_ts)
        self.btn_play.setStyleSheet(
            f'QPushButton#play {{ background:{BG3}; color:{ACC};'
            f' border:2px solid {ACC}; border-radius:26px;'
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
        self.btn_eq = QPushButton('EQ'); self.btn_eq.setObjectName('icon_btn')
        self.btn_eq.setToolTip('Equalizer')
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
        self._viz_bg_key:    object = None
        self._viz_bar_key:   object = None
        self._viz_brush_bg:  object = None
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
            self._eq_popup = pop
        return self._eq_popup

    def _toggle_eq(self):
        pop = self._ensure_eq_popup()
        now = QDateTime.currentMSecsSinceEpoch()
        if now - pop._hide_timestamp_ms < 150:
            pop._hidden_by_outside = False
            pop._hide_timestamp_ms = 0
            return
        pop.set_bands(self._player._eq_bands, self._player._eq_enabled)
        if pop.isVisible():
            pop.hide()
        else:
            pop.show_center()

    def _on_eq_changed(self, bands, enabled):
        self._player.set_eq_enabled(enabled)
        self._player.set_eq_bands(bands)

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
            pop.cover_toggled.connect(self._on_cover_toggle)
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
            ]
            for sig in _save_sigs:
                sig.connect(lambda *_: self.settings_changed.emit())
            # Theme switch emits via _on_theme_toggle → connect directly
            pop._theme_sw.toggled.connect(lambda *_: self.settings_changed.emit())
            self._settings_popup = pop
        return self._settings_popup

    @property
    def lyrics_fetch_enabled(self) -> bool:
        pop = self._settings_popup
        return pop.lyrics_fetch_on() if pop else True

    @property
    def cover_fetch_enabled(self) -> bool:
        pop = self._settings_popup
        return pop.cover_fetch_on() if pop else True

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
            self._player._ctrlbar_bref = overlay

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
        dlg = CoverFetchPopup(all_tracks, pages, self, parent=win)
        dlg.show()

    def _on_lyric_fetch_btn(self):
        """Open the LyricsFetchPopup — triggered by the Settings button."""
        win = self.window()
        all_tracks = list(win._lib_page.tracks) if hasattr(win, '_lib_page') and win._lib_page else []
        if not all_tracks:
            QMessageBox.information(win, 'No Tracks', 'Add a folder to the library first.')
            return
        if self._settings_popup: self._settings_popup.hide()
        dlg = LyricsFetchPopup(all_tracks, parent=win)
        dlg.show()

    def _on_tag_fetch_btn(self):
        win = self.window()
        all_tracks = list(win._lib_page.tracks) if hasattr(win, '_lib_page') and win._lib_page else []
        if not all_tracks:
            QMessageBox.information(win, 'No Tracks', 'Add a folder to the library first.')
            return
        if self._settings_popup: self._settings_popup.hide()
        dlg = TagFetchPopup(all_tracks, parent=win)
        # When tags are written, refresh the Track objects in all pages
        dlg.tags_updated.connect(lambda fp, tags: win._on_tags_fetched(fp, tags))
        dlg.show()

    def _on_rename_btn(self):
        """Open the RenamePopup — triggered by the Settings 'Rename…' button.

        After the dialog closes (finished OR cancelled) we:
          1. Update M3U8 files that reference any renamed path
          2. Save config (known_paths, playlists)
          3. Rescan every known folder/m3u so the library reflects new filenames
        """
        win = self.window()
        all_tracks = list(win._lib_page.tracks) if hasattr(win, '_lib_page') and win._lib_page else []
        if not all_tracks:
            QMessageBox.information(win, 'No Tracks', 'Add a folder to the library first.')
            return
        if self._settings_popup:
            self._settings_popup.hide()
        dlg = RenamePopup(all_tracks, parent=win)
        dlg.show()   # non-blocking - allows background operation
        
        def _on_rename_finished(renamed, total):
            """Handle rename completion after dialog finishes."""
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
                        stripped = line.rstrip('\\n\\r')
                        if stripped in rename_map:
                            new_lines.append(rename_map[stripped] + line[len(stripped):])
                            changed = True
                        else:
                            new_lines.append(line)
                    if changed:
                        with open(m3u_path, 'w', encoding='utf-8') as fh:
                            fh.writelines(new_lines)
                except Exception:
                    pass

            # 2. Save config
            if hasattr(win, '_save_config'):
                win._save_config()

            # 3. Rescan all known paths
            if hasattr(win, '_lib_page') and win._lib_page:
                win._lib_page.rescan_all()

        dlg._worker.finished.connect(_on_rename_finished) if dlg._worker else None
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

        # 3. Save config immediately (persists updated known_paths + M3U contents)
        win._save_config()

        # 4. Rescan all folders and M3U playlists so the UI reflects new names
        win._status.showMessage('Rename complete — refreshing library…')
        _cover_cache.clear()
        for path in list(win._known_paths):
            is_m3u = path.endswith(('.m3u', '.m3u8'))
            win._scan_path(path, is_m3u, refresh=True)

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
            pop._hidden_by_outside = False
            pop._hide_timestamp_ms = 0
            return
        if pop.isVisible():
            pop.hide()
        else:
            pop.show_above(self.btn_settings)

    @staticmethod
    def _coerce_bands(bands) -> list:
        """Coerces freq/gain/Q values to float (JSON round-trip may deserialize them as strings)."""
        result = []
        for b in bands:
            try:
                result.append([float(b[0]), float(b[1]), float(b[2])])
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
        _cf = cfg.get('cover_fetch_on', True)
        pop.set_cover_fetch(_cf)
        global _cover_fetch_on; _cover_fetch_on = _cf
        self._player.set_volume(volume / 100)
        # Theme (dark/light) — load before accent so the stylesheet is correct
        _dark = cfg.get('dark_mode', True)
        pop.set_dark_mode(_dark)
        if not _dark:
            apply_theme(dark=False)

        # View mode + scale sliders
        _vm = cfg.get('view_mode', 'classic')
        # Migrate old single 'gallery' value to default gallery_z
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
        eq_profiles  = {k: self._coerce_bands(v) for k, v in raw_profiles.items()}
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
                    'lyrics_fetch_on': pop.lyrics_fetch_on(),
                    'cover_fetch_on': pop.cover_fetch_on(),
                    'view_mode': pop.view_mode(),
                    'list_scale': pop.list_scale(),
                    'gallery_scale': pop.gallery_scale(),
                    'dark_mode': pop.dark_mode_on()})
        eq_pop = self._ensure_eq_popup()
        cfg['eq_profiles'] = eq_pop.get_profiles()
        default_bands, default_enabled = eq_pop.get_default()
        cfg['default_eq_bands'] = default_bands
        cfg['default_eq_enabled'] = default_enabled
        cfg['default_eq_profile'] = eq_pop.get_default_name()
        return cfg

    # Rest of ControlBar methods (unchanged)...

    def _precompute_bars(self):
        iw = self.width()
        if iw < 2: return

        # ── Integer bar geometry: all bars same width, exactly 1px gap ─────────
        # bw * VIZ_BANDS + 1 * (VIZ_BANDS-1) = total_used
        bw = max(1, (iw - (VIZ_BANDS - 1)) // VIZ_BANDS)
        total_used = bw * VIZ_BANDS + (VIZ_BANDS - 1)
        offset = max(0, (iw - total_used) // 2)   # center the bar group

        bar_x0_list = [offset + i * (bw + 1) for i in range(VIZ_BANDS)]
        self._bar_x0 = _np.array(bar_x0_list, dtype=_np.int32)
        self._bar_bw = bw

        # ── Column→bar mapping ────────────────────────────────────────────────
        col_bar = _np.full(iw, -1, dtype=_np.int32)
        for i, x0 in enumerate(bar_x0_list):
            col_bar[x0:x0+bw] = i
        # col_bar: column→bar index mapping, also used for vectorized paint
        self._col_bar = col_bar   # (iw,) int32, -1 = gap
        # Precompute safe-index and mask arrays used every frame in paintEvent
        self._col_has_bar = (col_bar >= 0)               # (iw,) bool
        self._col_bar_safe = _np.maximum(col_bar, 0)     # (iw,) int32, no negatives

        # ── Cap pixel offset arrays (precomputed once per bw, reused every frame) ──
        # For each pixel (row, col) inside the semicircular cap region, store the
        # (row_delta, col_delta) offsets from the bar's top-left corner.
        # paintEvent broadcasts these across all eligible bars with pure numpy indexing
        # — zero Python loops at 60fps.
        #
        # Cap geometry: semicircle of integer radius = bw//2.
        #   circle centre at y = -0.5 (just above row 0), x = (bw-1)/2
        #   row 0 → narrowest (near top); row radius-1 → widest (near equator)
        radius = bw // 2
        if radius > 0 and bw >= 2:
            cx  = (bw - 1) * 0.5
            r2  = float(radius * radius)
            r_offs, c_offs = [], []
            for row in range(radius):
                dy  = radius - row - 0.5
                dx2 = r2 - dy * dy
                if dx2 > 0.0:
                    dx = math.sqrt(dx2)
                    xl = max(0,  int(math.ceil (cx - dx)))
                    xr = min(bw, int(math.floor(cx + dx)) + 1)
                    for col in range(xl, xr):
                        r_offs.append(row)
                        c_offs.append(col)
            if r_offs:
                self._cap_r_offsets = _np.array(r_offs, dtype=_np.int32)
                self._cap_c_offsets = _np.array(c_offs, dtype=_np.int32)
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
            FS_HALF = self._player.current_fs / 2.0  # Nyquist of actual pipeline fs
            FULL_HZ = 20.0; FADE_HZ = 60.0
            log_min = math.log10(F_MIN); log_max = math.log10(F_MAX)
            fracs = []; fc_hz = []
            for d in range(VIZ_BANDS):
                f_lo = 10.0 ** (log_min + d / VIZ_BANDS * (log_max - log_min))
                f_hi = 10.0 ** (log_min + (d+1) / VIZ_BANDS * (log_max - log_min))
                fc = (f_lo * f_hi) ** 0.5
                fracs.append(fc * GST_BANDS / FS_HALF)
                fc_hz.append(fc)
            interp = []
            for frac in fracs:
                b0 = max(0, min(GST_BANDS-1, int(frac)))
                b1 = min(b0+1, GST_BANDS-1)
                interp.append((b0, b1, frac - int(frac)))
            b0s = [int(f) for f in fracs]
            run_len_at = {}
            d = 0
            while d < VIZ_BANDS:
                b0 = b0s[d]; start = d
                while d < VIZ_BANDS and b0s[d] == b0: d += 1
                for k in range(start, d): run_len_at[k] = d - start
            smooth_w = []
            for d in range(VIZ_BANDS):
                fc = fc_hz[d]; rl = run_len_at.get(d, 1)
                if fc >= FADE_HZ or rl <= 1:
                    smooth_w.append(None)
                else:
                    strength = (1.0 if fc < FULL_HZ
                                else 1.0 - (fc - FULL_HZ) / (FADE_HZ - FULL_HZ))
                    hw = max(1, int((rl // 2) * strength))
                    lo = max(0, d - hw); hi = min(VIZ_BANDS-1, d + hw)
                    n  = hi - lo + 1
                    smooth_w.append(tuple((nb, 1.0/n) for nb in range(lo, hi+1)))
        else:
            _fs_half = self._player.current_fs / 2.0  # Nyquist of actual pipeline fs
            _lin_scale = (20000.0 / _fs_half) * GST_BANDS / VIZ_BANDS
            interp = []
            for d in range(VIZ_BANDS):
                frac = d * _lin_scale
                b0 = max(0, min(GST_BANDS-1, int(frac)))
                b1 = min(b0+1, GST_BANDS-1)
                interp.append((b0, b1, frac - int(frac)))
            smooth_w = []

        ba_arr = _np.array([x[0] for x in interp], dtype=_np.int32)
        bb_arr = _np.array([x[1] for x in interp], dtype=_np.int32)
        bt_arr = _np.array([x[2] for x in interp], dtype=_np.float32)

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
            self._player._viz_col_buf[:] = 0.0
        self.update()

    def _on_log_toggle(self, on: bool):
        self._log_scale = on
        self._precompute_bars()
        self.update()

    def _on_delay_change(self, v: int):
        self._delay_ms = v

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
        bg   = QColor(BG)
        ah, as_, al, _ = acc.getHsvF()

        if _DARK_MODE:
            # Dark: dim desaturated accent (t=0) → vivid accent (t=1)
            # Never goes to black — minimum luma is 15% of accent luma
            luma  = max(0.10, al * (0.15 + 0.85 * t))
            sat   = as_ * (0.30 + 0.70 * t)
            tint  = QColor()
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
        self._brush_cache = QBrush(tint)
        self.update()

    def _on_accent_change(self, color: str):
        global ACC, ACCH, SS
        ACC  = color
        ACCH = make_acch(color)
        SS   = make_stylesheet(ACC, ACCH)
        QApplication.instance().setStyleSheet(SS)
        self._on_brightness_change(getattr(self, '_brightness_v', 40))
        _cover_cache.clear()
        # Remove stale default cover disk cache (will regenerate with new color)
        for f in CONFIG_PATH.parent.glob('default_cover_*.jpg'):
            try: f.unlink()
            except Exception: pass
        # Refresh inline-styled widgets (transport buttons use palette globals directly)
        _ts = (f'QPushButton#ctrl {{ background:transparent; border:none; color:{FG2};'
               f' font-size:20px; border-radius:22px; padding:0; text-align:center; }}'
               f'QPushButton#ctrl:hover {{ color:{FG}; background:{BG3}; }}'
               f'QPushButton#ctrl:checked {{ color:{ACC}; background:transparent; }}'
               f'QPushButton#ctrl:pressed {{ background:{BG4}; }}')
        for b in (self.btn_shuf, self.btn_prev, self.btn_next):
            b.setStyleSheet(_ts)
        self.btn_play.setStyleSheet(
            f'QPushButton#play {{ background:{BG3}; color:{ACC};'
            f' border:2px solid {ACC}; border-radius:26px;'
            f' min-width:52px; max-width:52px; min-height:52px; max-height:52px;'
            f' font-size:22px; padding:0 0 2px 5px; text-align:center; }}'
            f'QPushButton#play:hover {{ border-color:{ACCH}; color:{ACCH};'
            f' background:{BG4}; }}'
            f'QPushButton#play:pressed {{ background:{BG4}; }}')
        self.accent_changed.emit(color)
    def _on_cover_toggle(self, on: bool):
        self._cover_lbl.setVisible(on)
        if on and self._cur_track:
            pm = get_cover_pixmap(self._cur_track.filepath, 64, 8)
            self._cover_lbl.setPixmap(pm if pm is not None else draw_default_cover(64, 8))
        # Propagate to main window via signal
        self.cover_on_changed.emit(on)

    def _on_seek_flush(self):
        """Mark viz as awaiting first post-seek frame."""
        self._seek_gen += 1
        self._seek_pending = True
        self._player._viz_spec[:] = MIN_DB
        self._player._viz_col_buf[:] = 0.0
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
            self._player._viz_col_buf[:] = 0.0
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
        self._player._compute_viz_frame()
        if not self._player._viz_has_any:
            if not self._player.playing:
                self._render_timer.stop()
                _gc.enable()
                if self._viz_on:
                    self.update()
            return

        _now = _monotonic()
        if (_now - self._render_last_wt) < _FRAME_S * 0.85:
            return
        self._render_last_wt = _now
        if self._viz_on:
            self.update()


    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Recompute bar/cap geometry — debounced so resize drags don't thrash numpy
        self._resize_timer.start()

    def paintEvent(self, _):
        iw = self.width(); ih = self.height()
        if iw <= 0 or ih <= 0:
            return
        p = QPainter(self)
        if not p.isActive():
            return

        if self._viz_on and not self._viz_paused:
            bh = self._player._viz_bar_buf

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
                    self._viz_brush_bg = QBrush(QColor(BG))
                    # invalidate pixel buffer so it is reallocated with new colors
                    self._px_shape = (0, 0)

                # ── Pixel buffer — reallocate only on resize or color change ───
                if self._px_shape != (ih, iw):
                    self._px_buf   = _np.full((ih, iw), self._px_bg, dtype=_np.uint32)
                    self._px_qimg  = QImage(self._px_buf.data, iw, ih,
                                            iw * 4, QImage.Format.Format_ARGB32_Premultiplied)
                    self._px_shape   = (ih, iw)
                    self._px_col_y0  = _np.full(iw, ih, dtype=_np.int32)
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
                p.setPen(QPen(QColor(BORD), 1))
                p.drawLine(0, 0, iw, 0)
                p.end()
                return

        # Viz off / paused — plain background
        p.fillRect(self.rect(), QColor(BG))
        p.setPen(QPen(QColor(BORD), 1))
        p.drawLine(0, 0, self.width(), 0)
        p.end()

    def _on_playing_changed(self, playing: bool):
        if playing:
            _focus_paused = getattr(self, '_focus_paused', False)
            self._viz_paused = _focus_paused
            self._seek_pending = False
            self._player.set_viz_active(self._viz_on and not _focus_paused)
            if (self._viz_on or self._overlay_viz_enabled) and not _focus_paused:
                self._start_render_timer()
        else:
            self._viz_paused = True
            self._seek_pending = False
            self._seek_gen += 1
            self._render_timer.stop()
            self._player._viz_spec[:] = MIN_DB
            self._player._viz_col_buf[:] = 0.0
            self._player._viz_bar_buf[:] = 0.0
            self.update()
            _bref = getattr(self, '_blackout_ref', None)
            if _bref is not None and getattr(_bref, '_ov_viz', False):
                _bref.push_viz_frame([0.0] * VIZ_BANDS)

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

    def set_track(self, t: Track):
        self._lbl_title.setText(t.title or Path(t.filepath).name)
        self._lbl_artist.setText(t.artist)
        self._seek.setValue(0); self._lbl_cur.setText('0:00')
        self._dur_ms = int(t.duration*1000); self._lbl_tot.setText(t.dur_str())
        self._player._viz_spec[:] = MIN_DB
        # Update cover thumbnail — always show whatever is in cache (or default)
        if self._cover_lbl.isVisible():
            pm = get_cover_pixmap(t.filepath, 64, 8)
            self._cover_lbl.setPixmap(pm if pm is not None else draw_default_cover(64, 8))
        self._cur_track = t

    def set_play_icon(self, playing: bool):
        self.btn_play.setText('⏸' if playing else '▶')
        _pad = '0 0 2px 5px' if not playing else '0'
        # Rebuild from scratch so palette globals (BG3/ACC/ACCH) are always current
        self.btn_play.setStyleSheet(
            f'QPushButton#play {{ background:{BG3}; color:{ACC};'
            f' border:2px solid {ACC}; border-radius:26px;'
            f' min-width:52px; max-width:52px; min-height:52px; max-height:52px;'
            f' font-size:22px; padding:{_pad}; text-align:center; }}'
            f'QPushButton#play:hover {{ border-color:{ACCH}; color:{ACCH};'
            f' background:{BG4}; }}'
            f'QPushButton#play:pressed {{ background:{BG4}; }}')

    def set_play_busy(self, busy: bool):
        """Show/hide spinner on play button during pipeline reload."""
        self.btn_play.set_busy(busy)

    @staticmethod
    def _fmt(ms):
        t = ms//1000; h, r = divmod(t, 3600); m, s = divmod(r, 60)
        return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'

# ══════════════════════════════════════════════════════════════════════════════
#  Main window (with tag editing)
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
#  Custom Title Bar  (frameless, OLED-black bg, dark-grey text & icons)
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
            handle = self._win.windowHandle()
            if handle:
                handle.startSystemMove()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()
        super().mouseDoubleClickEvent(e)

# ══════════════════════════════════════════════════════════════════════════════
#  MainWindow
# ══════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self, splash=None, open_with: str = None):
        super().__init__()
        self._open_with_path = open_with   # file passed via "Open With" / CLI arg
        # Remove native decoration; draw our own black titlebar
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowTitle('VoidPulse'); self.resize(1280, 760)
        self.setMinimumSize(480, 320)

        self._player        = Player()
        self._playlists:    List[PlaylistPage] = []
        self._lib_page:     Optional[PlaylistPage] = None
        self._cur_page:     Optional[PlaylistPage] = None
        self._cur_idx:      int  = -1
        self._shuffle:      bool = False
        self._scan_threads: List[ScanThread] = []
        self._known_paths:  set  = set()
        self._cover_locked_paths: set = set()
        self._cur_track_mw: Track = None
        self._blackout = BlackoutOverlay()
        self._config_loader = None   # ref to ConfigPlaylistLoader while running
        self._splash_ref = splash    # held so _close_splash can always reach it
        self._build_ui()
        self._connect_signals()
        self._load_config()
        # NOTE: do NOT clear _splash_ref here — ConfigPlaylistLoader.all_done
        # fires asynchronously; _close_splash reads _splash_ref at that point.
        # _close_splash calls deleteLater() so the object is GC'd safely.
        self._mpris = MprisServer(self._player, self)
        self._mpris.set_cover_on(self._ctrlbar.cover_on())
        self._player.sig_seek.connect(self._mpris.notify_seeked)
        # Install app-level event filter to detect mouse/key activity for idle timer.
        # We filter at the application level so we catch events on all child widgets
        # without installing per-widget filters or enabling mouse-tracking everywhere.
        QApplication.instance().installEventFilter(self)

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Custom frameless titlebar
        self._titlebar = BlackTitleBar(self)
        root.addWidget(self._titlebar)

        body = QSplitter(Qt.Orientation.Horizontal); body.setHandleWidth(1)
        self._sidebar = Sidebar(); body.addWidget(self._sidebar)

        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)

        cbar = QWidget(); cbar.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        self._cbar_widget = cbar
        cbar.setFixedHeight(28)
        cbl = QHBoxLayout(cbar); cbl.setContentsMargins(12,0,12,0)
        self._count_lbl = QLabel('')
        self._count_lbl.setStyleSheet(f'color:{FG2}; font-size:11px; background:transparent;')
        cbl.addStretch(); cbl.addWidget(self._count_lbl)
        rl.addWidget(cbar)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(False)   # Tabs are never shown for playlists
        self._tabs.tabBar().setVisible(False)   # Hide tab bar entirely; nav via sidebar
        rl.addWidget(self._tabs, 1)
        body.addWidget(right)

        # ctrlbar created just before root.addWidget; use late binding
        self._lyrics_panel = LyricsPanel(self._player, ctrlbar=None)
        self._lyrics_panel.setVisible(False)
        body.addWidget(self._lyrics_panel)

        body.setStretchFactor(0, 0); body.setStretchFactor(1, 1); body.setStretchFactor(2, 0)
        body.setSizes([230, 1050, 0])
        # Debounce splitter moves so config is saved after the user stops dragging
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(400)
        self._splitter_save_timer.timeout.connect(self._save_config)
        body.splitterMoved.connect(lambda *_: self._splitter_save_timer.start())
        root.addWidget(body, 1)

        self._lib_page = PlaylistPage(label='Library')
        self._lib_page.play_track.connect(self._play_from_page)
        self._lib_page.ctx_requested.connect(self._show_ctx_menu)
        self._lib_page.col_widths_changed.connect(self._on_col_widths_changed)
        self._tabs.addTab(self._lib_page, '  Library')
        self._cur_page = self._lib_page

        self._ctrlbar = ControlBar(self._player)
        self._lyrics_panel._ctrlbar = self._ctrlbar
        root.addWidget(self._ctrlbar)
        self._status = self.statusBar()
        # Tab bar hidden; update count when tab changes programmatically
        self._tabs.currentChanged.connect(self._on_tab_change)

    # Keep custom titlebar in sync with window title changes
    def setWindowTitle(self, title: str):
        super().setWindowTitle(title)
        if hasattr(self, '_titlebar'):
            self._titlebar.set_title(title)

    def _connect_signals(self):
        self._sidebar.add_folder_req.connect(self._add_folder_dialog)
        self._sidebar.add_m3u_req.connect(self._import_m3u_dialog)
        self._sidebar.new_playlist_req.connect(self._new_playlist_dialog)
        self._sidebar.remove_req.connect(self._remove_playlist)
        self._sidebar.source_selected.connect(self._select_source)
        self._sidebar.search_changed.connect(self._apply_search)
        self._sidebar.refresh_req.connect(self._refresh_library)
        self._sidebar.export_m3u_req.connect(self._export_m3u_dialog)

        self._player.sig_end.connect(self._on_track_end)
        self._player.sig_err.connect(lambda e: self._status.showMessage(f'Error: {e}', 5000))
        self._player.sig_busy.connect(self._on_player_busy)
        self._ctrlbar.btn_play.clicked.connect(self._play_pause)
        self._ctrlbar.btn_prev.clicked.connect(self._prev_track)
        self._ctrlbar.btn_next.clicked.connect(self._next_track)
        self._ctrlbar.btn_shuf.toggled.connect(lambda v: setattr(self, '_shuffle', v))
        self._ctrlbar.btn_rep.mode_changed.connect(lambda _: None)
        self._ctrlbar.btn_blackout.clicked.connect(self._blackout.show_blackout)
        # Feed track info + position updates to the overlay
        self._player.sig_pos.connect(
            lambda ms: self._blackout.set_pos(ms, self._ctrlbar._dur_ms))
        self._ctrlbar.cover_on_changed.connect(self._on_cover_toggle)
        self._ctrlbar.accent_changed.connect(self._on_accent_refresh)
        self._ctrlbar.btn_lyrics.clicked.connect(self._toggle_lyrics)
        self._player.sig_pos.connect(self._on_pos_for_lyrics)
        self._lyrics_panel.status_msg.connect(
            lambda m: self._status.showMessage(m, 0) if m else self._status.clearMessage())
        self._lyrics_panel.seek_requested.connect(self._player.seek)
        self._lyrics_panel.lyrics_context.connect(self._blackout.set_lyrics_context)
        self._ctrlbar.set_blackout_ref(self._blackout)

        # View mode + scale — connect settings popup signals after popup is ensured
        pop = self._ctrlbar._ensure_settings_popup()
        pop.view_mode_changed.connect(self._on_view_mode_changed)
        pop.list_scale_changed.connect(self._on_list_scale_changed)
        pop.gallery_scale_changed.connect(self._on_gallery_scale_changed)
        # Auto-save config whenever any setting changes (debounced via QTimer)
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(500)
        self._settings_save_timer.timeout.connect(self._save_config)
        self._ctrlbar.settings_changed.connect(self._settings_save_timer.start)
        # Update ctrlbar cover thumbnail when async loader delivers a cover
        _ensure_async_cover_loader().cover_loaded.connect(self._on_cover_loaded_mw)

    def _on_cover_toggle(self, on: bool):
        self._lib_page.set_covers_on(on)
        for pl in self._playlists:
            pl.set_covers_on(on)
        if hasattr(self, '_mpris'):
            self._mpris.set_cover_on(on)

    def _on_cover_loaded_mw(self, fp: str, size: int, radius: int):
        """Update ctrlbar thumbnail when async cover loader finishes for the playing track."""
        if size != 64:
            return
        ctrlbar = self._ctrlbar
        if not ctrlbar._cover_lbl.isVisible():
            return
        cur = ctrlbar._cur_track
        if cur and cur.filepath == fp:
            pm = _cover_cache.get((fp, 64, 8))
            if pm:
                ctrlbar._cover_lbl.setPixmap(pm)

    def _on_view_mode_changed(self, mode: str):
        self._lib_page.set_view_mode(mode)
        for pl in self._playlists:
            pl.set_view_mode(mode)
        self._splitter_save_timer.start()

    def _on_list_scale_changed(self, row_h: int):
        self._lib_page.set_list_scale(row_h)
        for pl in self._playlists:
            pl.set_list_scale(row_h)
        self._splitter_save_timer.start()

    def _on_gallery_scale_changed(self, card_h: int):
        self._lib_page.set_gallery_scale(card_h)
        for pl in self._playlists:
            pl.set_gallery_scale(card_h)
        self._splitter_save_timer.start()

    def _on_tags_fetched(self, fp: str, tags: dict):
        """Called by TagFetchPopup when tags for a track have been written to disk.
        Refreshes the Track object in every page that contains this filepath."""
        if not tags: return
        for page in [self._lib_page] + self._playlists:
            if page is None: continue
            # O(1) lookup via TrackTable reverse index instead of O(n) enumerate scan
            i = page.table._fp_to_row.get(fp, -1)
            if i < 0 or i >= len(page.tracks):
                continue
            t = page.tracks[i]
            if t.filepath != fp:
                continue   # stale index after a re-sort; tolerate silently
            if tags.get('title'):  t.title  = tags['title']
            if tags.get('artist'): t.artist = tags['artist']
            if tags.get('album'):  t.album  = tags['album']
            page.table._fill_row(i, t)
            if (self._cur_page is page and self._cur_idx == i):
                self._ctrlbar.set_track(t)
                self.setWindowTitle(f'{t.title}  —  VoidPulse')

    def _refresh_all_theme_widgets(self, _overlay: '_SpinningOverlay' = None):
        """Re-apply inline stylesheets asynchronously — each chunk yields to the event loop.

        The overlay must already be created and shown before calling this method;
        this method closes it when done.
        """
        # Step 1: critical fast widgets — synchronous, immediately visible
        for lbl in (self._ctrlbar._lbl_title, self._ctrlbar._lbl_artist):
            lbl.setStyleSheet('background:transparent;')
        self._cbar_widget.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        self._count_lbl.setStyleSheet(f'color:{FG2}; font-size:11px; background:transparent;')
        self._ctrlbar._seek.update_accent(ACC, ACCH)
        self._ctrlbar._on_brightness_change(getattr(self._ctrlbar, '_brightness_v', 40))
        _play_ss = (
            f'QPushButton#play {{ background:{BG3}; color:{ACC};'
            f' border:2px solid {ACC}; border-radius:26px;'
            f' min-width:52px; max-width:52px; min-height:52px; max-height:52px;'
            f' font-size:22px; padding:0 0 2px 5px; text-align:center; }}'
            f'QPushButton#play:hover {{ border-color:{ACCH}; color:{ACCH}; background:{BG4}; }}'
            f'QPushButton#play:pressed {{ background:{BG4}; }}')
        self._ctrlbar.btn_play.setStyleSheet(_play_ss)
        _ts = (f'QPushButton#ctrl {{ background:transparent; border:none; color:{FG2};'
               f' font-size:20px; border-radius:22px; padding:0; text-align:center; }}'
               f'QPushButton#ctrl:hover {{ color:{FG}; background:{BG3}; }}'
               f'QPushButton#ctrl:checked {{ color:{ACC}; background:transparent; }}'
               f'QPushButton#ctrl:pressed {{ background:{BG4}; }}')
        for b in (self._ctrlbar.btn_shuf, self._ctrlbar.btn_prev, self._ctrlbar.btn_next):
            b.setStyleSheet(_ts)
        if hasattr(self, '_titlebar'):
            self._titlebar.refresh_theme()
        QApplication.processEvents()

        # Step 2: lyrics + popups — deferred
        def _step2():
            self._lyrics_panel.set_accent(ACC)
            self._lyrics_panel.refresh_theme()
            pop = self._ctrlbar._settings_popup
            if pop is not None:
                _combo_ss = (
                    f'QComboBox {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
                    f' border-radius:6px; padding:4px 8px; font-size:12px; }}'
                    f'QComboBox:hover {{ border-color:{ACC}; }}'
                    f'QComboBox::drop-down {{ border:none; width:20px; }}'
                    f'QComboBox::down-arrow {{ color:{FG2}; }}'
                    f'QComboBox QAbstractItemView {{ background:{BG3}; color:{FG};'
                    f' selection-background-color:{SEL}; border:1px solid {B2}; }}')
                pop._view_combo.setStyleSheet(_combo_ss)
                pop.repaint()
            eq_pop = self._ctrlbar._eq_popup
            if eq_pop is not None:
                eq_pop._profile_combo.setStyleSheet(
                    f'QComboBox {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
                    f' border-radius:6px; padding:4px 8px 4px 8px; min-height:30px; }}'
                    f'QComboBox:focus {{ border-color:{ACC}; }}'
                    f'QComboBox::drop-down {{ width:44px; border-left:1px solid {B2};'
                    f' background:{BG2}; border-radius:0 6px 6px 0; }}'
                    f'QComboBox::down-arrow {{ width:16px; height:16px; }}'
                    f'QComboBox QAbstractItemView {{ background:{BG3}; color:{FG};'
                    f' selection-background-color:{SEL}; border:1px solid {B2}; }}'
                    f'QComboBox QAbstractItemView::item {{ min-height:35px; padding:0 8px; }}')
                eq_pop.repaint()
            self._sidebar.refresh_theme()
            QTimer.singleShot(0, _step3)

        # Step 3: all playlist pages — one per event loop slot
        def _step3():
            pages = [p for p in [self._lib_page] + self._playlists if p]
            def _do_page(i):
                if i >= len(pages):
                    # Done — close overlay
                    if _overlay is not None:
                        _overlay.close_overlay()
                    return
                pg = pages[i]
                pg.refresh_theme()
                if pg.playing_idx >= 0:
                    pg.table.set_playing_row(pg.playing_idx)
                    pg.gallery.set_playing(pg.playing_idx)
                QTimer.singleShot(0, lambda _i=i+1: _do_page(_i))
            _do_page(0)

        QTimer.singleShot(0, _step2)

    def _on_accent_refresh(self, color: str):
        """Accent colour changed — show overlay and start async theme refresh."""
        overlay = _SpinningOverlay(self)
        overlay.show(); overlay.raise_()
        # Defer work until after the overlay's first paint.
        QTimer.singleShot(32, lambda: self._refresh_all_theme_widgets(_overlay=overlay))

    def _refresh_theme_no_overlay(self):
        """Refresh without overlay (for internal calls such as config restore)."""
        self._refresh_all_theme_widgets(_overlay=None)

    def _on_pos_for_lyrics(self, ms: int):
        delay = self._ctrlbar._delay_ms
        self._lyrics_panel.on_position(max(0, ms - delay))

    def _open_lyrics_panel_from_config(self):
        """Restore lyrics panel open state from config."""
        if not self._lyrics_panel.isVisible():
            self._toggle_lyrics()

    def _toggle_lyrics(self, _checked=False):
        panel = self._lyrics_panel
        body  = self.findChild(QSplitter)
        if not body: return
        vis = panel.isVisible()
        panel.setVisible(not vis)
        self._ctrlbar.btn_lyrics.setChecked(not vis)
        sizes = body.sizes()
        if not vis:   # opening
            total = sum(sizes)
            body.setSizes([sizes[0], max(100, total - sizes[0] - 290), 290])
            if self._cur_track_mw:
                deferred = not self.isActiveWindow() or self._blackout.isVisible()
                panel.set_track(self._cur_track_mw, deferred=deferred)
        else:         # closing
            body.setSizes([sizes[0], sizes[1] + sizes[2], 0])

    # --- Context menu with tag editing ---
    def _show_ctx_menu(self, src_page, row, pos):
        if not (0 <= row < len(src_page.tracks)): return
        track = src_page.tracks[row]; m = QMenu(self)
        m.addAction('▶  Play').triggered.connect(lambda: self._play_from_page(src_page, row))
        m.addSeparator()
        add_sub = m.addMenu("Add to Playlist")
        for pl in self._playlists:
            if pl is not src_page:
                def _add(_, _pl=pl, _tr=track):
                    fps = {t.filepath for t in _pl.tracks}
                    if _tr.filepath not in fps:
                        tracks = list(_pl.tracks)
                        # Insert at sorted position instead of full re-sort
                        sk = _tr.sort_key()
                        idx = bisect.bisect_left([t.sort_key() for t in tracks], sk)
                        tracks.insert(idx, _tr)
                        _pl.set_tracks(tracks, _pl.playing_idx); self._save_config()
                add_sub.addAction(pl.label).triggered.connect(_add)
        if src_page is not self._lib_page:
            m.addSeparator()
            def _rem(_, _p=src_page, _r=row):
                tracks = list(_p.tracks); tracks.pop(_r)
                _p.set_tracks(tracks, -1); self._rebuild_library(); self._save_config()
            m.addAction("Remove from Playlist").triggered.connect(_rem)
        m.addSeparator()
        m.addAction("✎  Edit Tags...").triggered.connect(
            lambda: self._edit_tags(src_page, row))
        m.exec(pos)

    def _invalidate_cover_cache(self, fp: str, pre_embed_mtime: float = None):
        """Remove all cached cover data for fp so the next paint reloads from disk.

        pre_embed_mtime: mtime captured BEFORE embed_cover_bytes() is called.
        The disk cache key includes mtime; after af.save() the mtime changes,
        so without the pre-embed value the old disk cache file would be missed.
        """
        # Clear ALL cached sizes for this fp (includes gallery's dynamic cover_sz)
        for key in [k for k in _cover_cache if k[0] == fp]:
            _cover_cache.pop(key, None)
        try:
            try:
                cur_mtime = str(os.path.getmtime(fp))
            except Exception:
                cur_mtime = '0'
            mtimes = {cur_mtime}
            if pre_embed_mtime is not None:
                mtimes.add(str(pre_embed_mtime))
            for mt in mtimes:
                for size, radius in [(28, 4), (64, 8)]:
                    dkey = hashlib.sha1(f'{fp}:{mt}:{size}:{radius}'.encode()).hexdigest()
                    disk_path = _COVER_DISK_DIR / f'{dkey}.jpg'
                    if disk_path.exists():
                        try:
                            disk_path.unlink()
                        except Exception:
                            pass
        except Exception:
            pass
        # Async loader's no-embed blacklist — remove so it retries on next paint
        loader = _async_cover_loader
        if loader is not None:
            with loader._lock:
                loader._no_embed.discard(fp)
                for size, radius in [(28, 4), (64, 8)]:
                    loader._in_flight.discard((fp, size, radius))

    def _edit_tags(self, page, row):
        track = page.tracks[row]
        dlg = TagEditDialog(track, locked_paths=self._cover_locked_paths, parent=None)
        dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_title, new_artist, new_album = dlg.get_tags()
        cover_action, cover_bytes, cover_locked = dlg.get_cover_result()
        # Update cover lock set
        if cover_locked:
            self._cover_locked_paths.add(track.filepath)
            _cover_locked_set.add(track.filepath)
        else:
            self._cover_locked_paths.discard(track.filepath)
            _cover_locked_set.discard(track.filepath)
        # Write tags to file using mutagen
        try:
            ext = Path(track.filepath).suffix.lower()
            # Detect WebM/MKV container (EBML magic) — mutagen cannot write these tags
            with open(track.filepath, 'rb') as _f:
                _magic = _f.read(4)
            if _magic == b'\x1a\x45\xdf\xa3':
                self._status.showMessage(
                    f'Cannot edit tags: {Path(track.filepath).name} is a WebM/MKV container '
                    f'(re-mux to Ogg with ffmpeg to enable tag editing)', 6000)
                return
            af = _open_audio(track.filepath)
            if af is None:
                self._status.showMessage(
                    f'Could not open {Path(track.filepath).name} for tag writing', 3000)
                return
            if af.tags is None:
                af.add_tags()

            if ext == '.mp3':
                from mutagen.id3 import TIT2, TPE1, TALB
                # Only write non-empty values; empty = leave tag unchanged
                if new_title:  af.tags['TIT2'] = TIT2(encoding=3, text=new_title)
                if new_artist: af.tags['TPE1'] = TPE1(encoding=3, text=new_artist)
                if new_album:  af.tags['TALB'] = TALB(encoding=3, text=new_album)

            elif ext in ('.flac', '.ogg', '.opus'):
                # Vorbis comments: normalise to lowercase keys
                # First remove any uppercase duplicates so we don't double-write
                for k_old in ('TITLE', 'ARTIST', 'ALBUM'):
                    try:
                        if k_old in af.tags: del af.tags[k_old]
                    except Exception:
                        pass
                if new_title:  af.tags['title']  = [new_title]
                if new_artist: af.tags['artist'] = [new_artist]
                if new_album:  af.tags['album']  = [new_album]

            elif ext in ('.m4a', '.aac'):
                if new_title:  af.tags['\xa9nam'] = [new_title]
                if new_artist: af.tags['\xa9ART'] = [new_artist]
                if new_album:  af.tags['\xa9alb'] = [new_album]
            else:
                self._status.showMessage(f'Unsupported format: {ext}', 3000)
                return

            af.save()

            # Handle cover changes
            fp = track.filepath
            if cover_action == 'set' and cover_bytes:
                try:
                    _pre_embed_mtime = os.path.getmtime(fp)
                except Exception:
                    _pre_embed_mtime = None
                embed_cover_bytes(fp, cover_bytes)
                self._invalidate_cover_cache(fp, pre_embed_mtime=_pre_embed_mtime)
                # Build pixmaps synchronously NOW — before any _fill_row / populate call
                for size, radius in [(28, 4), (64, 8)]:
                    raw = QPixmap()
                    if raw.loadFromData(cover_bytes):
                        pm = _rounded_pixmap(raw, size, radius)
                        _cover_cache[(fp, size, radius)] = pm
                        try:
                            dkey = _cover_disk_key(fp, size, radius)
                            disk_path = _COVER_DISK_DIR / f'{dkey}.jpg'
                            _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
                            pm.save(str(disk_path), 'JPEG', _COVER_JPEG_QUALITY)
                        except Exception:
                            pass
            elif cover_action == 'remove':
                try:
                    af2 = _open_audio(fp)
                    ext2 = Path(fp).suffix.lower()
                    if af2 and af2.tags:
                        if ext2 == '.mp3':               af2.tags.delall('APIC')
                        elif ext2 == '.flac':            af2.clear_pictures()
                        elif ext2 in ('.m4a', '.aac'):   af2.tags.pop('covr', None)
                        elif ext2 in ('.ogg', '.opus'):
                            af2.tags.pop('metadata_block_picture', None)
                        af2.save()
                except Exception:
                    pass
                # Invalidate and pre-populate with default so _fill_row sees it immediately
                self._invalidate_cover_cache(fp)
                for size, radius in [(28, 4), (64, 8)]:
                    _cover_cache[(fp, size, radius)] = draw_default_cover(size, radius)

            # Re-read metadata to reflect changes in UI
            updated_track = read_metadata(fp)

            def _update_page(pg, idx):
                pg.tracks[idx] = updated_track
                pg.table._tracks_ref = pg.tracks  # keep table ref in sync
                pg.table._fill_row(idx, updated_track)
                pm28 = _cover_cache.get((fp, 28, 4))
                if pm28:
                    item = pg.table.item(idx, C_TIT)
                    if item:
                        item.setIcon(QIcon(pm28))
                # Gallery: repopulate and force repaint so async cover_loaded
                # is re-requested for the gallery's dynamic cover_sz key.
                pg.gallery.populate(pg.tracks, pg.playing_idx)
                # Invalidate the fp→position cache so _on_cover_loaded re-maps
                pg.gallery._fp_to_vis_positions = None
                # Force a full canvas repaint — triggers get_cover_pixmap for
                # the gallery's cover_sz, scheduling a new async load if needed.
                pg.gallery._canvas.update()

            _update_page(page, row)
            # Also update library page and any other playlist containing this track
            for pg in [self._lib_page] + self._playlists:
                if pg is page:
                    continue
                i = pg.table._fp_to_row.get(updated_track.filepath, -1)
                if i >= 0 and i < len(pg.tracks) and pg.tracks[i].filepath == updated_track.filepath:
                    _update_page(pg, i)
            # Update ctrlbar thumbnail only when the edited track is currently playing
            if (cover_action in ('set', 'remove')
                    and self._cur_track_mw is not None
                    and self._cur_track_mw.filepath == fp
                    and self._ctrlbar._cover_lbl.isVisible()):
                pm64 = _cover_cache.get((fp, 64, 8))
                if pm64:
                    self._ctrlbar._cover_lbl.setPixmap(pm64)
            if self._cur_page is page and self._cur_idx == row:
                self._ctrlbar.set_track(updated_track)
                self.setWindowTitle(f'{updated_track.title}  —  VoidPulse')
                self._mpris.notify_track(updated_track)

            self._status.showMessage('Tags updated', 3000)
            self._save_config()
        except Exception as e:
            self._status.showMessage(f'Error saving tags: {e}', 5000)
            print(f'_edit_tags error: {e}')

    # --- Scan methods (unchanged) ---
    def _new_playlist_dialog(self):
        """Ask for name, create an empty M3U8 in the first known folder, load it."""
        name, ok = QInputDialog.getText(self, 'New Playlist', 'Playlist name:')
        if not ok or not name.strip():
            return
        name = name.strip()
        # Find a writable folder — prefer first known non-m3u folder
        save_dir = None
        for p in self._known_paths:
            if not p.endswith(('.m3u', '.m3u8')) and os.path.isdir(p):
                save_dir = p; break
        if save_dir is None:
            # No known folder: ask user
            save_dir = QFileDialog.getExistingDirectory(self, 'Select Playlist Folder')
            if not save_dir:
                return
        # Build safe filename
        safe = ''.join(c for c in name if c.isalnum() or c in ' _-').strip() or 'playlist'
        m3u_path = str(Path(save_dir) / f'{safe}.m3u8')
        # Write empty M3U8
        try:
            with open(m3u_path, 'w', encoding='utf-8') as f:
                f.write('#EXTM3U\n')
        except Exception as e:
            self._status.showMessage(f'Could not create M3U8: {e}', 4000); return
        # Create empty PlaylistPage directly (no scan needed — file is empty)
        page = PlaylistPage([], label=name)
        page.play_track.connect(self._play_from_page)
        page.ctx_requested.connect(self._show_ctx_menu)
        # Apply current view settings to the new playlist page
        pop = self._ctrlbar._ensure_settings_popup()
        page.set_view_mode(pop.view_mode())
        page.set_list_scale(pop.list_scale())
        page.set_gallery_scale(pop.gallery_scale())
        page.set_covers_on(pop.cover_on())

        self._playlists.append(page)
        ti = self._tabs.addTab(page, f' {name} ')
        self._sidebar.add_playlist(name)
        self._tabs.setCurrentIndex(ti)
        # Remember the m3u8 path so "Refresh" can re-scan it
        self._known_paths.add(m3u_path)
        # Store m3u path on page for later save
        page._m3u_path = m3u_path
        self._status.showMessage(f'"{name}" playlist created — {m3u_path}', 5000)
        self._save_config()

    def _add_folder_dialog(self):
        f = QFileDialog.getExistingDirectory(self, 'Select Music Folder', str(Path.home()))
        if f:
            self._known_paths.add(f); self._scan_path(f, False)

    def _import_m3u_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, 'Import Playlist', str(Path.home()),
            'Playlist (*.m3u *.m3u8);;All Files (*)')
        if f:
            self._known_paths.add(f); self._scan_path(f, True)

    def _export_m3u_dialog(self):
        """Export the currently visible playlist to an M3U8 file."""
        page = self._tabs.currentWidget()
        if not isinstance(page, PlaylistPage) or not page.tracks:
            self._status.showMessage('Nothing to export — open a playlist first.', 3000)
            return
        label = page.label or 'playlist'
        safe  = ''.join(c for c in label if c.isalnum() or c in ' _-').strip() or 'playlist'
        default_path = str(Path.home() / f'{safe}.m3u8')
        dest, _ = QFileDialog.getSaveFileName(
            self, 'Export Playlist as M3U8', default_path,
            'M3U Playlist (*.m3u8 *.m3u);;All Files (*)')
        if not dest:
            return
        try:
            lines = ['#EXTM3U\n']
            for t in page.tracks:
                lines.append(f'#EXTINF:{int(t.duration)},{t.artist} - {t.title}\n')
                lines.append(t.filepath + '\n')
            with open(dest, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            self._status.showMessage(
                f'Exported {len(page.tracks)} tracks → {dest}', 5000)
        except Exception as e:
            self._status.showMessage(f'Export failed: {e}', 5000)
            print(f'_export_m3u_dialog error: {e}')

    def _refresh_library(self):
        if not self._known_paths:
            self._status.showMessage('No folders added.', 3000); return
        self._status.showMessage('Refreshing library…')
        # Clear memory cache — disk cache keys include mtime so they go stale automatically
        _cover_cache.clear()
        for path in list(self._known_paths):
            if not path.endswith(('.m3u', '.m3u8')):
                self._scan_path(path, False, refresh=True)

    def _scan_path(self, path, is_m3u, refresh=False):
        self._status.showMessage('Scanning…')
        t = ScanThread(path, is_m3u)
        t.done.connect(lambda tracks, label, r=refresh, p=path:
                       self._on_scan_done(tracks, label, r, p))
        t.progress.connect(lambda m: self._status.showMessage(m))
        self._scan_threads.append(t); t.start()

    def _on_scan_done(self, tracks, label, refresh=False, path=''):
        if not tracks:
            self._status.showMessage('No supported audio files found.', 3000); return

        if refresh:
            for pl in self._playlists:
                if pl.label == label:
                    pl.set_tracks(tracks); self._rebuild_library()
                    self._status.showMessage(f'"{label}" refreshed — {len(tracks)} tracks', 4000)
                    self._save_config(); return

        page = PlaylistPage(tracks, label=label)
        page.play_track.connect(self._play_from_page)
        page.ctx_requested.connect(self._show_ctx_menu)
        page.col_widths_changed.connect(self._on_col_widths_changed)
        page.set_tracks(tracks)
        # Restore saved column ratios to new page
        saved_ratios = getattr(self, '_last_col_widths', None) or TrackTable._DEFAULT_COL_RATIOS
        page.table.restore_col_widths(saved_ratios)
        # Apply current cover preference
        pop = self._ctrlbar._ensure_settings_popup()
        page.set_covers_on(pop.cover_on())
        # Apply current view mode + scale
        page.set_view_mode(pop.view_mode())
        page.set_list_scale(pop.list_scale())
        page.set_gallery_scale(pop.gallery_scale())
        self._playlists.append(page)
        ti = self._tabs.addTab(page, f' {label} ')
        self._sidebar.add_playlist(label)
        self._tabs.setCurrentIndex(ti)
        self._rebuild_library()
        self._status.showMessage(f'"{label}" — {len(tracks)} tracks loaded', 4000)
        self._save_config()

    def _rebuild_library(self):
        all_tracks = []
        for pl in self._playlists: all_tracks.extend(pl.tracks)
        seen = set(); dedup = []
        for t in all_tracks:
            if t.filepath not in seen: seen.add(t.filepath); dedup.append(t)
        dedup.sort(key=lambda t: t.sort_key())
        pidx = -1
        if (self._cur_page is self._lib_page and
                0 <= self._cur_idx < len(self._lib_page.tracks)):
            fp = self._lib_page.tracks[self._cur_idx].filepath
            # O(1) lookup via a temporary reverse index instead of O(n) scan
            fp_to_idx = {t.filepath: i for i, t in enumerate(dedup)}
            pidx = fp_to_idx.get(fp, -1)
        self._lib_page.set_tracks(dedup, pidx)
        # Re-apply saved col widths after populate resets them
        saved = getattr(self, '_last_col_widths', None)
        if saved:
            self._lib_page.table.restore_col_widths(saved)
        self._update_count()

    def _remove_playlist(self, idx):
        if not (0 <= idx < len(self._playlists)): return
        page = self._playlists.pop(idx)
        # Remove tab first (fast)
        for i in range(self._tabs.count()):
            if self._tabs.widget(i) is page:
                self._tabs.removeTab(i)
                break
        self._sidebar.remove_playlist(idx)
        # Defer library rebuild so the UI unblocks immediately
        QTimer.singleShot(0, lambda: (self._rebuild_library(), self._save_config()))

    def _select_source(self, idx):
        if idx == -1: self._tabs.setCurrentIndex(0)
        else:
            ti = idx+1
            if ti < self._tabs.count(): self._tabs.setCurrentIndex(ti)

    # --- Playback ---
    def _play_from_page(self, page, row):
        self._cur_page = page; self._cur_idx = row; self._start_playback()

    def _start_playback(self):
        if not self._cur_page: return
        tracks = self._cur_page.tracks
        if not tracks or not (0 <= self._cur_idx < len(tracks)): return
        t = tracks[self._cur_idx]
        self._player.load(t.filepath)
        self._ctrlbar.set_track(t); self._ctrlbar.set_play_icon(True)
        self._cur_track_mw = t
        # Clear overlay lyrics immediately — new track starts fresh
        self._blackout.set_lyrics_context('', '', '')
        if self._lyrics_panel.isVisible():
            deferred = not self.isActiveWindow() or self._blackout.isVisible()
            self._lyrics_panel.set_track(t, deferred=deferred)
        self._cur_page.set_playing(self._cur_idx)
        self.setWindowTitle(f'{t.title}  —  VoidPulse')
        self._status.showMessage(f'▶  {t.artist}  —  {t.title}', 0)
        self._mpris.notify_track(t); self._mpris.notify_status()
        self._blackout.set_track(t.title or Path(t.filepath).name, t.artist, t.album)

    def _navigate_track(self, play: bool):
        """Change track without altering play/pause state.

        If play=True  → loads and plays (same as _start_playback).
        If play=False → loads, then immediately pauses so the user sees
                        the new track info but audio does not start.
        """
        if not self._cur_page: return
        tracks = self._cur_page.tracks
        if not tracks or not (0 <= self._cur_idx < len(tracks)): return
        t = tracks[self._cur_idx]
        self._player.load(t.filepath)
        if not play:
            self._player.play_pause()   # load() always starts; pause immediately
        self._ctrlbar.set_track(t); self._ctrlbar.set_play_icon(play)
        self._cur_track_mw = t
        self._blackout.set_lyrics_context('', '', '')
        if self._lyrics_panel.isVisible():
            deferred = not self.isActiveWindow() or self._blackout.isVisible()
            self._lyrics_panel.set_track(t, deferred=deferred)
        self._cur_page.set_playing(self._cur_idx)
        self.setWindowTitle(f'{t.title}  —  VoidPulse')
        self._status.showMessage(f'▶  {t.artist}  —  {t.title}', 0)
        self._mpris.notify_track(t); self._mpris.notify_status()
        self._blackout.set_track(t.title or Path(t.filepath).name, t.artist, t.album)

    def _on_player_busy(self, busy: bool):
        """Pipeline is reloading — show spinner on play button, disable MPRIS play/pause."""
        self._ctrlbar.set_play_busy(busy)
        self._mpris.set_pipeline_busy(busy)
        if not busy:
            # Sync play icon to actual state once reload is done
            self._ctrlbar.set_play_icon(self._player.playing)
            self._mpris.notify_status()

    def _play_pause(self):
        if not self._player.has_pipe:
            if self._cur_page and self._cur_page.tracks:
                if self._cur_idx < 0: self._cur_idx = 0
                self._start_playback()
        else:
            self._player.play_pause()
            self._ctrlbar.set_play_icon(self._player.playing)
            self._mpris.notify_status()
        # Play/pause is an intentional user action — reset idle timer
        self._ctrlbar._reset_idle_timer()

    def _prev_track(self):
        self._sync_cur_idx()
        if self._cur_page and self._cur_idx > 0:
            was_playing = self._player.playing
            self._cur_idx -= 1
            self._navigate_track(was_playing)

    def _next_track(self): self._advance(forced=True)

    def _sync_cur_idx(self):
        """After a sort the page reorders _tracks; sync our _cur_idx to match."""
        if not self._cur_page: return
        pi = self._cur_page.playing_idx
        if pi >= 0:
            self._cur_idx = pi

    def _advance(self, forced=False):
        if not self._cur_page: return
        self._sync_cur_idx()          # always use the post-sort index
        n = len(self._cur_page.tracks)
        if n == 0: return
        repeat = self._ctrlbar.btn_rep.current_mode()
        if not forced and repeat == RepeatMode.ONE: self._start_playback(); return
        if self._shuffle:
            if n > 1:
                # Pick random index != current without allocating a list
                skip = random.randrange(n - 1)
                self._cur_idx = skip if skip < self._cur_idx else skip + 1
            # n==1: only one track; replay it (choices would be empty)
            # repeat=NONE in shuffle mode: still play (no hard stop)
        else:
            self._cur_idx += 1
            if self._cur_idx >= n:
                if repeat == RepeatMode.ALL: self._cur_idx = 0
                else:
                    self._player.stop(); self._ctrlbar.set_play_icon(False)
                    self._mpris.notify_status(); return
        if forced:
            # Manual next: preserve playing/paused state
            self._navigate_track(self._player.playing)
        else:
            self._start_playback()

    def _on_track_end(self): self._advance()

    # --- Focus handling ---
    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            if hasattr(self, '_titlebar'):
                # Sync restore/maximize icon with the actual post-change window state
                self._titlebar._btn_max.setText(
                    '❐' if self.isMaximized() else '□'
                )
        if e.type() == QEvent.Type.ActivationChange:
            # Don't pause viz just because EQ/Settings Tool window is focused
            eq_vis  = self._ctrlbar._eq_popup is not None and self._ctrlbar._eq_popup.isVisible()
            set_vis = self._ctrlbar._settings_popup is not None and self._ctrlbar._settings_popup.isVisible()
            blackout_vis = self._blackout.isVisible()
            app_active = self.isActiveWindow() or eq_vis or set_vis or blackout_vis
            was_active = getattr(self, '_was_active', False)
            if not app_active and not blackout_vis:
                self._ctrlbar.set_focus_paused(True)
                self._ctrlbar._idle_timer.stop()   # pause countdown while unfocused
            elif app_active:
                self._ctrlbar.set_focus_paused(False)
                # Restart idle timer only on the rising edge (focus gain)
                if not was_active:
                    self._ctrlbar._idle_last_mouse = None   # reset mouse anchor on focus gain
                    self._ctrlbar._reset_idle_timer()
                # Trigger deferred lyrics fetch if panel is visible
                if self._lyrics_panel.isVisible():
                    self._lyrics_panel.on_focus_gained()
            self._was_active = app_active

    def eventFilter(self, obj, event):  # noqa: N802
        """Application-level filter: reset OLED idle timer on meaningful user activity.

        Design constraints (CPU / tick budget):
        - MouseMove: only reset when displacement from last-reset position > 5 px.
          We compare against _idle_last_mouse which is refreshed lazily; no per-frame
          math when the timer is disabled or the overlay is visible.
        - KeyPress: unconditional reset (cheap; infrequent relative to mouse events).
          Media keys (Play/Pause/Stop/Next/Prev) are also key events so they are
          covered here automatically — no separate hook needed.
        - TouchBegin/Update/End: reset on any finger/stylus touch contact.
        - TabletMove / TabletEnterProximity: reset on stylus hover over screen.
        - All other event types: zero-cost early return.
        - The filter never consumes events (always returns False / super).
        """
        etype = event.type()

        # ── Touch & stylus hover — reset idle unconditionally (cheap) ──────────
        if etype in (
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TabletMove,
            QEvent.Type.TabletEnterProximity,
        ):
            ctrlbar = self._ctrlbar
            if not ctrlbar._overlay_auto_open:
                return False
            bref = getattr(ctrlbar, '_blackout_ref', None)
            if bref is not None and bref.isVisible():
                return False
            ctrlbar._reset_idle_timer()
            return False

        if etype == QEvent.Type.MouseMove:
            ctrlbar = self._ctrlbar
            # Fast-path: bail immediately when feature is off or overlay is showing
            if not ctrlbar._overlay_auto_open:
                return False
            bref = getattr(ctrlbar, '_blackout_ref', None)
            if bref is not None and bref.isVisible():
                return False
            # Only react when our window is active
            if not self.isActiveWindow():
                return False
            pos = QCursor.pos()   # global screen coords — no widget mapping needed
            last = ctrlbar._idle_last_mouse
            if last is None:
                # First move after focus gain: anchor but don't reset yet
                ctrlbar._idle_last_mouse = pos
            else:
                dx = pos.x() - last.x()
                dy = pos.y() - last.y()
                if dx * dx + dy * dy > 25:   # 5² — integer math, no sqrt
                    ctrlbar._idle_last_mouse = pos
                    ctrlbar._reset_idle_timer()
            return False

        if etype == QEvent.Type.KeyPress:
            ctrlbar = self._ctrlbar
            if not ctrlbar._overlay_auto_open:
                return False
            bref = getattr(ctrlbar, '_blackout_ref', None)
            if bref is not None and bref.isVisible():
                return False
            if not self.isActiveWindow():
                return False
            ctrlbar._reset_idle_timer()
            return False

        return False

    # --- Search / tab ---
    def _apply_search(self, q):
        page = self._tabs.currentWidget()
        if isinstance(page, PlaylistPage): page.apply_filter(q)

    def _on_tab_change(self, idx):
        page = self._tabs.widget(idx)
        # _cur_page tracks the SOURCE playlist for playback (set in _play_from_page).
        # Switching tabs only changes the *view* — it must NOT redirect the queue.
        if isinstance(page, PlaylistPage): self._update_count(page)

    def _update_count(self, page=None):
        if page is None: page = self._tabs.currentWidget()
        if isinstance(page, PlaylistPage):
            self._count_lbl.setText(f'{len(page.tracks)} tracks')

    # --- Config ---
    def _on_col_widths_changed(self, widths: list):
        """User resized a column — sync to every page and save."""
        self._last_col_widths = widths
        for page in [self._lib_page] + self._playlists:
            if page is not None:
                page.table.restore_col_widths(widths)
        self._save_config()

    def _save_config(self):
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            cfg = self._ctrlbar.config_state()
            cfg['playlists'] = [{'label': pl.label, 'tracks': [t.filepath for t in pl.tracks]}
                                 for pl in self._playlists
                                 if pl.label != '__open_with__']
            cfg['known_paths'] = list(self._known_paths)
            cfg['lyrics_panel_open'] = self._lyrics_panel.isVisible()
            cfg['cover_locked_paths'] = list(self._cover_locked_paths)
            # Persist table column ratios (proportional, sum ≈ 1.0)
            total_w = sum(self._lib_page.table.columnWidth(c) for c in range(len(COLS)))
            if total_w > 0:
                cfg['table_col_widths'] = [self._lib_page.table.columnWidth(c) / total_w
                                           for c in range(len(COLS))]
            # Persist splitter sizes (sidebar / content / lyrics)
            body = self.findChild(QSplitter)
            if body:
                cfg['splitter_sizes'] = body.sizes()
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            # Write M3U8 for user-created playlists (those with _m3u_path attribute)
            for pl in self._playlists:
                if hasattr(pl, '_m3u_path'):
                    try:
                        lines = ['#EXTM3U\n']
                        for t in pl.tracks:
                            lines.append(f'#EXTINF:{int(t.duration)},{t.artist} - {t.title}\n')
                            lines.append(t.filepath + '\n')
                        with open(pl._m3u_path, 'w', encoding='utf-8') as f:
                            f.writelines(lines)
                    except Exception as e2:
                        print(f'M3U8 save error for {pl.label}: {e2}')
        except Exception as e:
            print(f'Config save error: {e}')

    def _close_splash(self):
        """Close startup splash if one was provided — safe to call multiple times."""
        sp = getattr(self, '_splash_ref', None)
        if sp is not None:
            self._splash_ref = None   # prevent double-close
            sp.close_overlay()
        # Handle "Open With" file after library is ready
        if getattr(self, '_open_with_path', None):
            QTimer.singleShot(0, self._handle_open_with)

    def _handle_open_with(self):
        """Add the file passed via 'Open With' / CLI arg to the library.

        The track is inserted into an internal hidden playlist so _rebuild_library
        picks it up naturally. The library tab is shown, the track is selected and
        highlighted, but playback is left paused so the user decides when to play.
        """
        path = getattr(self, '_open_with_path', None)
        if not path:
            return
        self._open_with_path = None

        fp = str(Path(path).resolve())
        ext = Path(fp).suffix.lower()
        if ext not in SUPPORTED_EXT:
            self._status.showMessage(
                f'Open With: unsupported format "{ext}" — {Path(fp).name}', 5000)
            return

        track = read_metadata(fp)

        # Use a dedicated hidden playlist that accumulates "open with" files.
        # Feeding into _playlists means _rebuild_library picks it up naturally.
        if not hasattr(self, '_open_with_pl'):
            self._open_with_pl = PlaylistPage([], label='__open_with__')
            self._open_with_pl.play_track.connect(self._play_from_page)
            self._open_with_pl.ctx_requested.connect(self._show_ctx_menu)
            self._playlists.append(self._open_with_pl)

        existing_fps = {t.filepath for t in self._open_with_pl.tracks}
        if fp not in existing_fps:
            tracks = list(self._open_with_pl.tracks)
            sk = track.sort_key()
            ins = bisect.bisect_left([t.sort_key() for t in tracks], sk)
            tracks.insert(ins, track)
            self._open_with_pl.set_tracks(tracks, -1)

        self._rebuild_library()

        try:
            row = next(i for i, t in enumerate(self._lib_page.tracks)
                       if t.filepath == fp)
        except StopIteration:
            return

        self._select_source(-1)

        self._cur_page = self._lib_page
        self._cur_idx = row

        # Update all UI elements to reflect the track WITHOUT touching the
        # GStreamer pipeline. Loading+immediately-pausing causes a state-change
        # race: if the user clicks another track before the pipeline settles,
        # the second load() blocks the UI thread. Keeping has_pipe=False means
        # _play_pause() will call _start_playback() cleanly when the user
        # decides to play.
        t = self._lib_page.tracks[row]
        self._cur_track_mw = t
        self._ctrlbar.set_track(t)
        self._ctrlbar.set_play_icon(False)
        self._lib_page.set_playing(row)
        self.setWindowTitle(f'{t.title}  —  VoidPulse')
        self._status.showMessage(f'⏸  {t.artist}  —  {t.title}', 0)
        self._blackout.set_track(t.title or Path(t.filepath).name, t.artist, t.album)
        self._blackout.set_lyrics_context('', '', '')
        self._mpris.notify_track(t)
        self._mpris.notify_status()

        self._lib_page.table.scrollTo(
            self._lib_page.table.model().index(row, 0))

    def _load_config(self):
        if not CONFIG_PATH.exists():
            QTimer.singleShot(0, self._rebuild_library)
            self._close_splash()
            return
        try:
            data = json.loads(CONFIG_PATH.read_text())
            for kp in data.get('known_paths', []):
                self._known_paths.add(kp)

            self._cover_locked_paths = set(data.get('cover_locked_paths', []))
            _cover_locked_set.update(self._cover_locked_paths)
            global _cover_fetch_on
            _cover_fetch_on = data.get('cover_fetch_on', True)
            self._ctrlbar.init_from_config(data)
            # If light mode was restored from config, widget inline stylesheets
            # were baked with dark values during _build_ui. Re-apply now so
            # cbar_widget, play button, seek handle etc. pick up light colours.
            if not data.get('dark_mode', True):
                QTimer.singleShot(0, self._refresh_theme_no_overlay)
            if data.get('lyrics_panel_open', False):
                QTimer.singleShot(200, self._open_lyrics_panel_from_config)
            # Restore table column ratios (deferred so viewport is fully sized)
            col_widths = data.get('table_col_widths', [])
            if col_widths:
                self._last_col_widths = col_widths
                def _apply_saved_ratios(r=col_widths):
                    self._lib_page.table.restore_col_widths(r)
                    for pl in self._playlists:
                        pl.table.restore_col_widths(r)
                QTimer.singleShot(0, _apply_saved_ratios)
            # Restore splitter sizes
            splitter_sizes = data.get('splitter_sizes', [])
            if splitter_sizes and len(splitter_sizes) >= 2:
                body = self.findChild(QSplitter)
                if body:
                    QTimer.singleShot(0, lambda s=splitter_sizes: body.setSizes(s))

            # Load playlist track metadata asynchronously to avoid blocking the UI.
            # ConfigPlaylistLoader emits playlist_ready once per playlist in order.
            playlist_data = data.get('playlists', [])
            if playlist_data:
                self._status.showMessage('Loading playlists…')
                loader = ConfigPlaylistLoader(playlist_data)
                loader.playlist_ready.connect(self._on_config_playlist_ready)
                loader.all_done.connect(self._on_config_playlists_done)
                loader.all_done.connect(loader.deleteLater)
                # Wire splash-done BEFORE start() so the signal is never missed
                loader.all_done.connect(self._close_splash)
                # Keep a reference so the thread isn't garbage-collected mid-run
                self._config_loader = loader
                loader.start()
            else:
                QTimer.singleShot(0, self._rebuild_library)
                self._close_splash()
        except Exception as e:
            print(f'Config load error: {e}')
            QTimer.singleShot(0, self._rebuild_library)
            self._close_splash()

    def _on_config_playlist_ready(self, tracks: list, label: str):
        """Called on main thread for each playlist loaded by ConfigPlaylistLoader."""
        page = PlaylistPage(tracks, label=label)
        page.play_track.connect(self._play_from_page)
        page.ctx_requested.connect(self._show_ctx_menu)
        page.col_widths_changed.connect(self._on_col_widths_changed)
        page.set_tracks(tracks)
        # Apply view settings (settings popup already initialised by init_from_config)
        pop = self._ctrlbar._settings_popup
        if pop is not None:
            page.set_view_mode(pop.view_mode())
            page.set_list_scale(pop.list_scale())
            page.set_gallery_scale(pop.gallery_scale())
            page.set_covers_on(pop.cover_on())
        # Restore saved column ratios
        saved = getattr(self, '_last_col_widths', None)
        if saved:
            page.table.restore_col_widths(saved)
        self._playlists.append(page)
        self._tabs.addTab(page, f' {label} ')
        self._sidebar.add_playlist(label)
        self._status.showMessage(f'Loaded "{label}" — {len(tracks)} tracks')

    def _on_config_playlists_done(self):
        """All playlists loaded — rebuild library index and finalize."""
        self._config_loader = None
        self._rebuild_library()
        self._status.showMessage('Library ready', 3000)

    # --- Keyboard ---
    def keyPressEvent(self, e):
        k, mod = e.key(), e.modifiers()
        if   k == Qt.Key.Key_Space:                                       self._play_pause()
        elif k == Qt.Key.Key_Left:   self._player.seek(max(0, self._player.position_ms()-5000))
        elif k == Qt.Key.Key_Right:  self._player.seek(self._player.position_ms()+5000)
        elif k in (Qt.Key.Key_BracketLeft,  Qt.Key.Key_MediaPrevious):   self._prev_track()
        elif k in (Qt.Key.Key_BracketRight, Qt.Key.Key_MediaNext):       self._next_track()
        elif k == Qt.Key.Key_MediaPlay:                                   self._play_pause()
        elif k == Qt.Key.Key_MediaStop:
            self._player.stop(); self._ctrlbar.set_play_icon(False); self._mpris.notify_status()
        elif k == Qt.Key.Key_F and mod == Qt.KeyboardModifier.ControlModifier:
            self._sidebar._search.setFocus(); self._sidebar._search.selectAll()
        else: super().keyPressEvent(e)

    def closeEvent(self, e):
        # Remove the hidden __open_with__ playlist before saving so it never
        # appears on next launch.  If it was the active source, clear _cur_page
        # to prevent a stale reference in the saved config.
        ow_pl = getattr(self, '_open_with_pl', None)
        if ow_pl is not None and ow_pl in self._playlists:
            if self._cur_page is ow_pl:
                self._cur_page = None
            self._playlists.remove(ow_pl)
        self._save_config()
        self._player.stop()
        super().closeEvent(e)

# ══════════════════════════════════════════════════════════════════════════════
#  Animated Splash Screen
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
#  Spinning overlay — startup splash + accent/theme change blocker
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
            # Install event filter on parent so we track its resize/show events
            # and always fill it completely — even after showMaximized().
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

        # Semi-transparent black backdrop
        p.fillRect(0, 0, w, h, QColor(0, 0, 0, 200))

        cx, cy = w // 2, h // 2

        # "VoidPulse" title — above the spinner
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setWeight(QFont.Weight.Light)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.0)
        p.setFont(title_font)
        p.setPen(QColor('#f0f0f0'))
        p.drawText(QRect(0, cy - 80, w, 36),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                   'VoidPulse')

        # Spinning red arc — below the title
        r = 28
        spinner_cy = cy + 20
        pen = QPen(QColor(ACC), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(cx - r, spinner_cy - r, r * 2, r * 2,
                  int((90.0 - self._angle) * 16), int(260 * 16))
        p.end()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_to_parent()


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════
def main():
    os.environ.setdefault('QT_QPA_PLATFORM', 'wayland;xcb')
    os.environ.setdefault('QT_WAYLAND_DISABLE_WINDOWDECORATION', '1')

    # GC is disabled during the 60fps render loop (see _start_render_timer).
    # Raise gen-0 threshold as a safety net for when the render timer is stopped
    # (e.g. during paused state where gc.enable() is called).
    _gc.set_threshold(5000, 10, 5)

    app = QApplication(sys.argv)
    app.setApplicationName('VoidPulse')
    app.setStyleSheet(SS)
    _apply_app_palette(app)

    # Show splash immediately — before MainWindow (which blocks on config load).
    # 360×200 comfortably fits the "VoidPulse" title + spinner.
    splash = _SpinningOverlay.as_splash()
    screen_geo = QApplication.primaryScreen().geometry()
    splash.move(
        screen_geo.center().x() - splash.width() // 2,
        screen_geo.center().y() - splash.height() // 2,
    )
    splash.show()
    app.processEvents()

    # Pass splash into MainWindow so _load_config can wire all_done BEFORE
    # loader.start() — guaranteeing the signal is never missed on fast loads.
    # Support "Open With" / file manager drag: voidpulse.py <file>
    open_with_path = sys.argv[1] if len(sys.argv) > 1 else None

    win = MainWindow(splash=splash, open_with=open_with_path)

    win.showMaximized()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
