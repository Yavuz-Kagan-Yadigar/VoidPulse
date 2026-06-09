#!/usr/bin/env python3
"""
VoidPulse — constants, palette, theme helpers, and global stylesheet.
"""
import sys, os, json, threading, enum, random, math, hashlib, bisect, base64, tempfile, subprocess
from collections import OrderedDict
import concurrent.futures as _cf

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
    BG='#000000', BG2='#080808', BG3='#141414', BG4='#1e1e1e',
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

def _broadcast_palette() -> None:
    """Push current palette + accent globals into every voidpulse module namespace.

    Because all modules do `from constants import BG, ACC, ...` they get *copies*
    of the strings at import time.  When apply_theme() or apply_accent() mutates
    the module-level globals here, those copies go stale.  This function fixes
    that by writing the new values back into every loaded module's __dict__ so
    that bare-name references (e.g. ``FG`` in a refresh_theme method) always see
    the current value without requiring every file to use ``import constants as _c``.
    """
    import sys as _sys
    _PALETTE_NAMES = (
        'BG', 'BG2', 'BG3', 'BG4', 'BORD', 'B2',
        'FG', 'FG2', 'SEL', 'ACC', 'ACCH', 'SS', '_DARK_MODE', 'RAD_PCT',
    )
    _current = {n: globals()[n] for n in _PALETTE_NAMES}
    _vp_prefixes = (
        'constants', 'controlbar', 'cover_art', 'dialogs_edit', 'eq',
        'fetch_popups', 'library', 'lyrics', 'main_window', 'metadata_online',
        'mpris', 'player', 'settings_popup', 'views', 'voidpulse',
        'widgets_base', 'blackout_overlay',
    )
    for _mod in list(_sys.modules.values()):
        _name = getattr(_mod, '__name__', '') or ''
        if not any(_name == p or _name.endswith('.' + p) for p in _vp_prefixes):
            continue
        _d = getattr(_mod, '__dict__', None)
        if _d is None:
            continue
        for _k, _v in _current.items():
            if _k in _d:
                _d[_k] = _v


def apply_theme(dark: bool) -> None:
    """Switch all palette globals between dark and light, then rebuild stylesheet."""
    global _DARK_MODE, BG, BG2, BG3, BG4, BORD, B2, FG, FG2, SEL, ACCH, SS
    _DARK_MODE = dark
    pal = _DARK if dark else _LIGHT
    BG = pal['BG']; BG2 = pal['BG2']; BG3 = pal['BG3']; BG4 = pal['BG4']
    BORD = pal['BORD']; B2 = pal['B2']; FG = pal['FG']; FG2 = pal['FG2']
    SEL = pal['SEL']
    ACCH = make_acch(ACC)   # recompute from current ACC (HSV shift is palette-independent)
    SS = make_stylesheet(ACC, ACCH)
    _broadcast_palette()    # push new values into every module's namespace
    app = QApplication.instance()
    if app:
        app.setStyleSheet(SS)
        _apply_app_palette(app)


def apply_accent(color: str) -> None:
    """Update accent colour globally and broadcast to all modules.

    Called by ControlBar._on_accent_change() after it updates its own locals.
    Ensures every other module (settings_popup, views, etc.) sees the new ACC.
    """
    global ACC, ACCH, SS
    ACC  = color
    ACCH = make_acch(color)
    SS   = make_stylesheet(ACC, ACCH)
    _broadcast_palette()
    app = QApplication.instance()
    if app:
        app.setStyleSheet(SS)

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
RAD_PCT       = 60   # global corner-radius percentage (0 = boxy/sharp, 100 = pill/circle)

def _r(full_px: int) -> int:
    """Return a corner radius scaled by RAD_PCT.

    ``full_px`` is the maximum radius (at 100 %) for the element being styled —
    typically half the element's height (gives a pill/circle shape).
    At 0 % returns 0 (perfectly sharp corners).
    """
    return round(full_px * RAD_PCT / 100)

# EQ constants
MAX_EQ_BANDS  = 10
EQ_FREQ_MIN   = 20.0
EQ_FREQ_MAX   = 22000.0
EQ_GAIN_MIN   = -10.0
EQ_GAIN_MAX   = 10.0
EQ_Q_MIN      = 0.1
EQ_Q_MAX      = 10.0
EQ_GAIN_MAX_GRAPH = EQ_GAIN_MAX   # graph vertical range — kept in sync with slider max

# ── EQ filter type constants ──────────────────────────────────────────────────
EQ_TYPE_PEAK       = 0   # Bell / peaking EQ
EQ_TYPE_LOWSHELF   = 1   # Low-shelf
EQ_TYPE_HIGHSHELF  = 2   # High-shelf
EQ_TYPE_LOWPASS    = 3   # Low-pass  (gain ignored)
EQ_TYPE_HIGHPASS   = 4   # High-pass (gain ignored)
EQ_TYPE_NOTCH      = 5   # Band-stop / notch  (gain ignored)

EQ_TYPE_LABELS = {
    EQ_TYPE_PEAK:      'Peak',
    EQ_TYPE_LOWSHELF:  'Low Shelf',
    EQ_TYPE_HIGHSHELF: 'High Shelf',
    EQ_TYPE_LOWPASS:   'Low Pass',
    EQ_TYPE_HIGHPASS:  'High Pass',
    EQ_TYPE_NOTCH:     'Notch',
}

# Ordered list for the ComboBox (index == EQ_TYPE_* constant value)
EQ_TYPE_LIST = [
    EQ_TYPE_PEAK,
    EQ_TYPE_LOWSHELF,
    EQ_TYPE_HIGHSHELF,
    EQ_TYPE_LOWPASS,
    EQ_TYPE_HIGHPASS,
    EQ_TYPE_NOTCH,
]
# ══════════════════════════════════════════════════════════════════════════════
#  Stylesheet — uses current BG/FG globals (dark or light)
# ══════════════════════════════════════════════════════════════════════════════


def make_stylesheet(acc: str = None, acch: str = None) -> str:
    if acc  is None: acc  = ACC
    if acch is None: acch = ACCH
    # ── Semantic radius values (computed once per stylesheet rebuild) ──────────
    r_gen  = _r(12)   # menus, tooltips, dialogs, popups
    r_btn  = _r(18)   # standard buttons (36 px height → max 18 px pill)
    r_play = _r(26)   # play button (52 px → max 26 px circle)
    r_ctrl = _r(22)   # ctrl icon buttons (44 px → max 22 px circle)
    r_icon = _r(18)   # icon_btn buttons (36 px → max 18 px circle)
    r_grv  = _r(2)    # slider groove (4 px height → max 2 px)
    r_slh  = _r(7)    # EQ/settings slider handle (14 px → max 7 px circle)
    r_inp  = _r(15)   # text inputs & combo boxes (~30 px → max 15 px)
    r_tbl  = _r(8)    # table & list container
    r_tab  = _r(5)    # tab bar top corners
    r_item = _r(6)    # list/tab item highlight
    r_scr  = _r(2)    # scrollbar handle (5 px wide)
    # Drop-down arrow sub-control: right side rounded, left side square
    r_dd_r = f'0 {r_inp}px {r_inp}px 0'
    return f"""
* {{ outline: none; }}
QWidget     {{ background:{BG};  color:{FG};  font-size:13px; }}
QMainWindow {{ background:{BG}; }}
QDialog     {{ background:{BG}; border-radius:{r_gen}px; border:3px solid {ACC}; }}
QWidget#sidebar {{ background:{BG2}; border-right:1px solid {BORD}; }}

QPushButton {{
    background:{BG3}; color:{FG}; border:1px solid {B2};
    border-radius:{r_btn}px; padding:8px 14px; min-height:36px; text-align:center;
}}
QPushButton:hover   {{ border-color:{acc}; }}
QPushButton:pressed {{ background:{BG4}; }}
QPushButton:checked {{ color:{acc}; border-color:{acc}; background:{BG3}; }}
QPushButton:disabled {{ color:{B2}; border-color:{BORD}; }}

QPushButton#play {{
    background:{BG3}; color:{acc}; border:2px solid {acc}; border-radius:{r_play}px;
    min-width:52px; max-width:52px; min-height:52px; max-height:52px;
    font-size:22px; padding:0; text-align:center;
}}
QPushButton#play:hover   {{ border-color:{acch}; color:{acch}; background:{BG4}; }}
QPushButton#play:pressed {{ background:{BG4}; }}

QPushButton#ctrl {{
    background:transparent; border:none; color:{FG2}; font-size:20px;
    min-width:44px; max-width:44px; min-height:44px; max-height:44px;
    border-radius:{r_ctrl}px; padding:0; text-align:center;
}}
QPushButton#ctrl:hover   {{ color:{FG};  background:{BG3}; }}
QPushButton#ctrl:checked {{ color:{acc}; background:transparent; }}
QPushButton#ctrl:pressed {{ background:{BG4}; }}

QPushButton#icon_btn {{
    background:transparent; border:none; color:{FG2}; font-size:18px;
    min-width:36px; max-width:36px; min-height:36px; max-height:36px;
    border-radius:{r_icon}px; padding:0; text-align:center;
}}
QPushButton#icon_btn:hover   {{ color:{FG}; background:{BG3}; }}
QPushButton#icon_btn:pressed {{ background:{BG4}; }}

QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{ background:{B2}; height:4px; border-radius:{r_grv}px; }}
QSlider::sub-page:horizontal {{ background:{acc}; border-radius:{r_grv}px 0 0 {r_grv}px; }}
QSlider::handle:horizontal {{
    background:{BG4}; border:2px solid {acc};
    width:14px; height:14px; border-radius:{r_slh}px; margin:-5px 0;
}}
QSlider::handle:horizontal:hover {{
    background:{BG4}; border:3px solid {acch};
    width:14px; height:14px; border-radius:{r_slh}px; margin:-5px 0;
}}
QSlider::handle:horizontal:pressed {{
    background:{BG4}; border:3px solid {acch};
    width:14px; height:14px; border-radius:{r_slh}px; margin:-5px 0;
}}
QSlider:disabled {{ background: transparent; }}
QSlider::groove:horizontal:disabled {{ background:{BORD}; }}
QSlider::sub-page:horizontal:disabled {{ background:{BORD}; }}
QSlider::handle:horizontal:disabled {{
    background:{BG3}; border:2px solid {BORD};
    width:14px; height:14px; border-radius:{r_slh}px; margin:-5px 0;
}}

QTableWidget {{
    background:{BG}; color:{FG}; border:none; gridline-color:transparent;
    selection-background-color:{SEL}; selection-color:{FG};
    border-radius:{r_tbl}px;
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
    border-top-left-radius:{r_tab}px; border-top-right-radius:{r_tab}px;
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
    border-radius:{r_inp}px; padding:8px 16px; min-height:36px; max-height:36px;
}}
QLineEdit:focus {{ border-color:{acc}; }}

QComboBox {{
    background:{BG3}; color:{FG}; border:1px solid {B2};
    border-radius:{r_inp}px; padding:4px 8px; min-height:30px; font-size:12px;
}}
QComboBox:hover  {{ border-color:{acc}; }}
QComboBox:focus  {{ border-color:{acc}; }}
QComboBox::drop-down {{
    border-left:1px solid {B2}; background:{BG2};
    width:30px; border-radius:{r_dd_r};
}}
QComboBox::down-arrow {{ color:{FG2}; }}
QComboBox QAbstractItemView {{
    background:{BG3}; color:{FG}; border:1px solid {B2};
    selection-background-color:{SEL};
}}
QComboBox QAbstractItemView::item {{ min-height:30px; padding:0 8px; }}

QListWidget {{ background:{BG2}; border:none; color:{FG}; border-radius:{r_tbl}px; }}
QListWidget::item {{ padding:12px 14px; border-bottom:1px solid {BORD}; font-size:12px; }}
QListWidget::item:selected {{ background:{SEL}; color:{acc}; border-radius:{r_item}px; }}
QListWidget::item:hover:!selected {{ background:{BG3}; border-radius:{r_item}px; }}

QScrollBar {{ background:{BG}; border:none; }}
QScrollBar:vertical   {{ width:5px; margin:0; }}
QScrollBar:horizontal {{ height:5px; margin:0; }}
QScrollBar::handle {{ background:{B2}; border-radius:{r_scr}px; min-height:20px; }}
QScrollBar::handle:hover {{ background:{acc}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
QScrollBar::add-page,  QScrollBar::sub-page {{ background:none; }}

QSplitter::handle {{ background:transparent; }}
QSplitter::handle:horizontal {{ width:16px; border-left:1px solid {BORD}; border-right:1px solid {BORD}; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 transparent, stop:0.4999 transparent, stop:0.5 {BORD}, stop:0.5001 {BORD}, stop:0.5002 transparent, stop:1 transparent); }}
QSplitter::handle:vertical   {{ height:16px; border-top:1px solid {BORD}; border-bottom:1px solid {BORD}; background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 transparent, stop:0.4999 transparent, stop:0.5 {BORD}, stop:0.5001 {BORD}, stop:0.5002 transparent, stop:1 transparent); }}

QMenu {{ background:{BG3}; border:2px solid {ACC}; border-radius:{r_gen}px; padding:4px 0; }}
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
              border-radius:{r_gen}px; }}
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
#  Shared utilities (moved here to break circular imports)
# ══════════════════════════════════════════════════════════════════════════════

_lastfm_api_key  = ''    # set from config or fetch popups — never hardcoded

def _sanitize_filename_part(text: str) -> str:
    """Remove characters that are illegal in filenames on Linux/POSIX."""
    text = text.replace('/', '_').replace('\x00', '')
    return text.strip('. ')

def _open_audio(fp: str):
    """Open an audio file with mutagen, trying format-specific classes as fallback."""
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

def _apply_scroller_properties(widget, *, touch: bool = True):
    """Apply standard kinetic-scroll properties to a viewport widget."""
    SM = QScrollerProperties.ScrollMetric
    OP = QScrollerProperties.OvershootPolicy
    sp = QScrollerProperties()
    sp.setScrollMetric(SM.DecelerationFactor,           0.35)
    sp.setScrollMetric(SM.MaximumVelocity,              0.8)
    sp.setScrollMetric(SM.VerticalOvershootPolicy,      OP.OvershootAlwaysOff)
    sp.setScrollMetric(SM.HorizontalOvershootPolicy,    OP.OvershootAlwaysOff)
    if touch:
        sp.setScrollMetric(SM.AcceleratingFlickMaximumTime, 0.15)
        sp.setScrollMetric(SM.DragStartDistance,            0.005)
    QScroller.scroller(widget).setScrollerProperties(sp)
