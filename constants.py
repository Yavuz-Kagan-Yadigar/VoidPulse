#!/usr/bin/env python3
"""
VoidPulse — constants, palette, theme helpers, and global stylesheet.
"""
# Every other VoidPulse module does `from constants import *`, so the stdlib
# names below are deliberate re-exports: they are what `math`, `Path`, `Gst`
# etc. resolve to in those modules. A linter will report most of them as
# unused here — do not "fix" that, it breaks all 26 importers. Only
# underscore-prefixed aliases are private (star-import skips them).
import sys, os, re, json, threading, enum, random, math, hashlib, bisect, base64, tempfile, subprocess
from collections import OrderedDict
import urllib.request as _urlreq

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

# Imports nothing from VoidPulse, so it is safe to pull into the base module
import remote_io

# ══════════════════════════════════════════════════════════════════════════════
#  Flatpak sandbox detection
# ══════════════════════════════════════════════════════════════════════════════
IN_FLATPAK = Path('/.flatpak-info').exists()


def host_cmd(*args) -> list:
    """Prefix a command with `flatpak-spawn --host` when sandboxed.

    aplay and systemctl aren't part of the flatpak runtime, only the host —
    flatpak-spawn --host runs them there. Works with the finish-args VoidPulse
    already requests (--socket=session-bus grants unrestricted bus access, so
    no extra permission or manifest change is needed); outside flatpak this is
    a no-op passthrough.
    """
    return (['flatpak-spawn', '--host'] if IN_FLATPAK else []) + list(args)


# ══════════════════════════════════════════════════════════════════════════════
#  Application version
# ══════════════════════════════════════════════════════════════════════════════
APP_ID = 'org.voidpulse.VoidPulse'


def _read_app_version() -> str:
    """The running build's version, read from its AppStream metainfo.

    voidpulse_build.sh stamps the version it was given into <release version="…"/>
    for every package format it produces, so the metainfo file is the one place
    that stays correct in a flatpak, an AppImage, a deb/rpm/apk and a source
    checkout alike. A literal here would go stale the moment a package was built
    from an unchanged tree — the build script never rewrites the .py files.

    The paths are tried most-specific first: an AppImage exports APPDIR, a
    flatpak mounts /app, system packages install under /usr, and the checkout
    keeps its own appdata.xml next to this module.
    """
    cands = []
    appdir = os.environ.get('APPDIR')
    if appdir:
        cands.append(Path(appdir) / 'usr/share/metainfo' / f'{APP_ID}.appdata.xml')
    cands += [
        Path('/app/share/metainfo') / f'{APP_ID}.appdata.xml',
        Path('/usr/share/metainfo') / f'{APP_ID}.appdata.xml',
        Path('/usr/local/share/metainfo') / f'{APP_ID}.appdata.xml',
        Path(__file__).resolve().parent / 'appdata.xml',
    ]
    for c in cands:
        try:
            m = re.search(r'<release\s+version="([^"]+)"', c.read_text(errors='ignore'))
        except Exception:
            continue
        if m:
            return m.group(1).strip()
    return '0.0.0'


APP_VERSION = _read_app_version()


# ══════════════════════════════════════════════════════════════════════════════
#  Performance constants
# ══════════════════════════════════════════════════════════════════════════════
FPS_CAP       = 60           # render timer target
_FRAME_MS     = 1000 // FPS_CAP          # 16 ms
_FRAME_S      = 1.0 / FPS_CAP


# ══════════════════════════════════════════════════════════════════════════════
#  Palette
# ══════════════════════════════════════════════════════════════════════════════
_DARK_MODE = True
_USE_SYSTEM_QT_THEME = False  # derive the palette from the system Qt theme

_DARK = dict(
    BG='#000000', BG2='#080808', BG3='#141414', BG4='#1e1e1e',
    BORD='#222222', B2='#333333', FG='#f0f0f0', FG2='#909090', SEL='#181818',
)
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
_USER_ACC = ACC  # the user's own pick, kept so SYS mode can override ACC and
                 # still restore it afterwards
ACCH = '#ff4444'
FG   = _DARK['FG']
FG2  = _DARK['FG2']
SEL  = _DARK['SEL']

_SYSTEM_PALETTE_CACHE = None  # QPalette snapshot taken before app.setPalette() is ever called
# True only while _apply_app_palette() is inside app.setPalette(). Qt fires
# paletteChanged for every setPalette() call, so without this guard VoidPulse's
# own repaint reads as "the system theme changed" and loops forever.
_APPLYING_OWN_PALETTE = False

# ══════════════════════════════════════════════════════════════════════════════
#  qt6ct color-scheme file watching
# ══════════════════════════════════════════════════════════════════════════════
# qt6ct's platform plugin reads its color-scheme file once at startup and never
# watches it, so tools that rewrite that file live (matugen, wallust) emit no
# paletteChanged signal. QFileSystemWatcher (inotify-backed, no polling) on the
# files themselves is the only event-driven way to notice those edits.
_QT6CT_WATCHER = None          # module global so the watcher is not GC'd

def _shade(hex_col: str, amount: float) -> str:
    """Shift a hex color's HSV value (brightness) by `amount` (can be negative)."""
    c = QColor(hex_col)
    h, s, v, a = c.getHsvF()
    v = max(0.0, min(1.0, v + amount))
    c2 = QColor(); c2.setHsvF(h, s, v, a)
    return c2.name()


def _blend(hex_a: str, hex_b: str, t: float) -> str:
    """Blend hex_a toward hex_b by fraction t (0=a, 1=b)."""
    a, b = QColor(hex_a), QColor(hex_b)
    r  = round(a.red()   + (b.red()   - a.red())   * t)
    g  = round(a.green() + (b.green() - a.green()) * t)
    bl = round(a.blue()  + (b.blue()  - a.blue())  * t)
    return QColor(r, g, bl).name()


def _relative_luminance(hex_col: str) -> float:
    """WCAG relative luminance of a colour, 0.0 (black) to 1.0 (white)."""
    c = QColor(hex_col)

    def _lin(v: int) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(c.red()) + 0.7152 * _lin(c.green()) + 0.0722 * _lin(c.blue())


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG contrast ratio between two colours, from 1.0 (identical) to 21.0."""
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# Secondary text (artist line, format info, section labels) is FG blended toward
# the background to read as muted. A fixed blend is unsafe on system themes: where
# the theme's own text/background contrast is already low, blending again drops
# below readable. MIN_FG2_CONTRAST is the floor (WCAG AA for body text); the
# built-in palettes sit near 6.6:1, so only themes that need it get pulled back.
FG2_BLEND = 0.45
MIN_FG2_CONTRAST = 4.5


def _muted_fg(text_hex: str, window_hex: str, *surfaces: str,
              blend: float = FG2_BLEND,
              min_ratio: float = MIN_FG2_CONTRAST) -> str:
    """Blend text toward window for a muted tone, backing off until the result
    clears min_ratio.

    Extra `surfaces` are the other backgrounds secondary text is painted on (BG2
    for list rows, BG3 for cards, combos and popups). Contrast is measured
    against the worst of them.

    Returns the most muted colour that still clears the floor, or the best-scoring
    candidate if the theme is too low-contrast for any of them to.
    """
    checks = (window_hex,) + tuple(s for s in surfaces if s)

    def _worst(col: str) -> float:
        return min(_contrast_ratio(col, s) for s in checks)

    best, best_ratio = text_hex, _worst(text_hex)
    steps = max(1, int(round(blend / 0.05)))
    for i in range(steps, 0, -1):
        cand = _blend(text_hex, window_hex, i * 0.05)
        ratio = _worst(cand)
        if ratio >= min_ratio:
            return cand
        if ratio > best_ratio:
            best, best_ratio = cand, ratio
    return best


def _desaturate_darken(hex_col: str, sat_amount: float, val_amount: float) -> str:
    """Reduce saturation by sat_amount and value/brightness by val_amount
    (both 0..1 fractions of the current value, subtracted). Used to turn a
    vivid accent/highlight color into a muted selection background that's
    clearly distinct from vivid accent text drawn on top of it."""
    c = QColor(hex_col)
    h, s, v, a = c.getHsvF()
    s = max(0.0, s * (1.0 - sat_amount))
    v = max(0.0, v * (1.0 - val_amount))
    c2 = QColor(); c2.setHsvF(h, s, v, a)
    return c2.name()


def _qt6ct_conf_path() -> 'Path':
    return Path.home() / '.config' / 'qt6ct' / 'qt6ct.conf'

def _qt6ct_active_color_scheme_path() -> 'Optional[Path]':
    """Read ~/.config/qt6ct/qt6ct.conf and resolve the color_scheme_path it
    points to (the file matugen/wallust etc. actually rewrite). Returns None
    if qt6ct.conf doesn't exist or doesn't set a custom color scheme."""
    conf = _qt6ct_conf_path()
    if not conf.exists():
        return None
    try:
        text = conf.read_text()
    except Exception:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('color_scheme_path='):
            raw = line.split('=', 1)[1].strip()
            if not raw:
                return None
            p = Path(raw).expanduser()
            return p if p.exists() else None
    return None

# The QPalette::ColorRole order qt6ct writes in its active_colors= line, 20
# comma-separated hex values. Unused roles are parsed and ignored.
_QT6CT_ACTIVE_COLORS_ORDER = (
    'window_text', 'button', 'light', 'midlight', 'dark', 'mid',
    'text', 'bright_text', 'button_text', 'base', 'window', 'shadow',
    'highlight', 'highlighted_text', 'link', 'link_visited',
    'alternate_base', 'no_role', 'tooltip_base', 'tooltip_text',
)

def _parse_qt6ct_color_scheme(path: 'Path') -> Optional[dict]:
    """Parse a qt6ct/qt5ct .conf color-scheme file's [ColorScheme] section
    into the same BG/FG/etc. dict shape _system_palette_colors() produces,
    so apply_theme() can use either source interchangeably."""
    try:
        text = path.read_text()
    except Exception:
        return None
    active_line = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('active_colors='):
            active_line = line.split('=', 1)[1]
            break
    if active_line is None:
        return None
    parts = [p.strip() for p in active_line.split(',')]
    if len(parts) < 13:
        return None
    roles = dict(zip(_QT6CT_ACTIVE_COLORS_ORDER, parts))

    def _valid_hex(s):
        c = QColor(s)
        return c if c.isValid() else None

    window = _valid_hex(roles.get('window', ''))
    base = _valid_hex(roles.get('base', ''))
    alt_base = _valid_hex(roles.get('alternate_base', ''))
    button = _valid_hex(roles.get('button', ''))
    text_c = _valid_hex(roles.get('window_text', ''))
    highlight = _valid_hex(roles.get('highlight', ''))
    mid = _valid_hex(roles.get('mid', ''))
    if window is None or text_c is None:
        return None   # unusable; the caller keeps what it had

    window_hex, text_hex = window.name(), text_c.name()
    is_dark = window.value() < 128
    step = 0.06 if is_dark else -0.05

    bg2 = base.name() if base is not None and base.name() != window_hex else _shade(window_hex, step)
    bg3 = alt_base.name() if alt_base is not None and alt_base.name() != window_hex else _shade(window_hex, step * 2)
    bg4 = button.name() if button is not None and button.name() != window_hex else _shade(window_hex, step * 3)

    fg2 = _muted_fg(text_hex, window_hex, bg2, bg3)
    # `mid` is present in every valid active_colors= line (fixed 20 fields), so
    # this fallback only matters for a truncated one. It shades toward window
    # brightness, the same direction Qt's own Mid role sits in.
    bord = mid.name() if mid is not None else _shade(window_hex, step)

    # Same guards as _system_palette_colors(): fall back when Highlight is unset
    # or black, and keep SEL distinct from ACC (muted, darkened, desaturated) so
    # playing-row text stays legible on a selected row.
    sel_src = (highlight.name()
               if (highlight is not None and highlight.value() >= 20 and highlight.name() != window_hex)
               else None)
    acc_hex = sel_src if sel_src is not None else _USER_ACC
    sel_hex = _desaturate_darken(acc_hex, 0.5, 0.5) if sel_src is not None else acc_hex

    return dict(
        BG=window_hex,
        BG2=bg2,
        BG3=bg3,
        BG4=bg4,
        BORD=bord,
        B2=_shade(bord, step),
        ACC=acc_hex,
        FG=text_hex,
        FG2=fg2,
        SEL=sel_hex,
    )

def _qt6ct_files_to_watch() -> list:
    """qt6ct.conf itself, so a switch to a different scheme file is noticed,
    plus whichever scheme file it currently points at."""
    paths = []
    conf = _qt6ct_conf_path()
    if conf.exists():
        paths.append(str(conf))
    scheme = _qt6ct_active_color_scheme_path()
    if scheme is not None:
        paths.append(str(scheme))
    return paths

def start_qt6ct_live_reload(on_change) -> None:
    """Watch qt6ct's config and active color-scheme file for external edits.

    Uses QFileSystemWatcher (inotify-backed, no polling) so tools that rewrite
    the scheme file on disk — matugen, wallust-driven Hyprland scripts — are
    picked up live; qt6ct's plugin never re-reads it itself.

    `on_change` is called with no arguments on every watched-file change; the
    caller re-derives colors (see MainWindow._on_qt6ct_file_changed). No-op when
    qt6ct is not configured at all.
    """
    global _QT6CT_WATCHER
    paths = _qt6ct_files_to_watch()
    if not paths:
        return
    watcher = QFileSystemWatcher(paths, QApplication.instance())

    def _on_path_changed(_path):
        # Tools that replace-then-rename a file drop it from the watch list, so
        # re-add whatever is missing after each event — including a different
        # scheme file if qt6ct.conf now points at one.
        current = set(watcher.files())
        wanted = set(_qt6ct_files_to_watch())
        missing = wanted - current
        if missing:
            watcher.addPaths(list(missing))
        on_change()

    watcher.fileChanged.connect(_on_path_changed)
    _QT6CT_WATCHER = watcher   # keep alive — QFileSystemWatcher is GC'd otherwise

def qt6ct_color_scheme_colors() -> Optional[dict]:
    """Parse the active qt6ct colour scheme from disk into a palette dict.

    Read fresh each call, which only happens at startup and on a file change.
    """
    scheme = _qt6ct_active_color_scheme_path()
    if scheme is None:
        return None
    return _parse_qt6ct_color_scheme(scheme)


def _capture_system_palette(explicit_palette: 'QPalette' = None) -> None:
    """Snapshot the OS/Qt-theme-provided QPalette.

    app.palette() is read only on the first call — right after QApplication is
    constructed in voidpulse.py, before VoidPulse overrides the palette itself.
    Later calls are a no-op, since app.palette() would by then return VoidPulse's
    own colors rather than the theme's.

    explicit_palette overwrites the cache directly. That is the paletteChanged
    path: Qt hands the new system palette to the signal, so app.palette() must
    not be consulted at all.
    """
    global _SYSTEM_PALETTE_CACHE
    if explicit_palette is not None:
        _SYSTEM_PALETTE_CACHE = QPalette(explicit_palette)
        return
    if _SYSTEM_PALETTE_CACHE is not None:
        return
    app = QApplication.instance()
    if app:
        _SYSTEM_PALETTE_CACHE = QPalette(app.palette())


def _system_palette_colors() -> dict:
    """Derive VoidPulse's BG/FG palette from the system Qt theme.

    Falls back to the current style's standard palette if none was captured.
    """
    pal = _SYSTEM_PALETTE_CACHE
    if pal is None:
        app = QApplication.instance()
        pal = app.style().standardPalette() if app else QPalette()

    def col(role, group=QPalette.ColorGroup.Active):
        return pal.color(group, role).name()

    window   = col(QPalette.ColorRole.Window)
    base     = col(QPalette.ColorRole.Base)
    alt_base = col(QPalette.ColorRole.AlternateBase)
    button   = col(QPalette.ColorRole.Button)
    text     = col(QPalette.ColorRole.WindowText)
    sel      = col(QPalette.ColorRole.Highlight)
    bord     = col(QPalette.ColorRole.Mid)

    # Some themes never set Highlight and Qt fills the role with black, which
    # QColor.isValid() cannot detect. Using that as ACC would paint the play
    # button, playing-track text and viz bars black, so fall back to the user's
    # accent when Highlight is black or invisible against the window.
    _sel_c = QColor(sel)
    if _sel_c.value() < 20 or _sel_c.name() == QColor(window).name():
        sel = _USER_ACC

    is_dark = QColor(window).value() < 128
    step = 0.06 if is_dark else -0.05

    bg2 = base if base != window else _shade(window, step)
    bg3 = alt_base if alt_base != window else _shade(window, step * 2)
    bg4 = button if button != window else _shade(window, step * 3)

    # FG2 is derived rather than read from PlaceholderText: themes that leave
    # that role unset report pure black, which hides secondary text. _muted_fg()
    # blends toward the background but holds a contrast floor against every
    # surface the text is drawn on.
    fg2 = _muted_fg(text, window, bg2, bg3)

    # SEL must differ from ACC: playing-track text is drawn in ACC, so if that
    # row is also selected both would come from Highlight and cancel out.
    # Desaturating and darkening keeps the hue and restores contrast.
    sel_bg = _desaturate_darken(sel, 0.5, 0.5)

    return dict(
        BG=window,
        BG2=bg2,
        BG3=bg3,
        BG4=bg4,
        BORD=bord,
        B2=_shade(bord, step),
        ACC=sel,
        FG=text,
        FG2=fg2,
        SEL=sel_bg,
    )


_VP_MODULE_CACHE = None  # filled in on the first _broadcast_palette()


_PALETTE_NAMES = (
    'BG', 'BG2', 'BG3', 'BG4', 'BORD', 'B2',
    'FG', 'FG2', 'SEL', 'ACC', 'ACCH', 'SS', '_DARK_MODE', 'RAD_PCT',
)


def _broadcast_palette() -> None:
    """Push the current palette and accent globals into every VoidPulse module.

    Modules do `from constants import BG, ACC, ...`, so they hold copies taken at
    import time, which go stale when apply_theme() or apply_accent() changes the
    values here. Writing the new values into each module's __dict__ keeps bare
    names (e.g. ``FG`` inside a refresh_theme method) correct without every file
    having to import constants as a module.

    Modules are found by location — any loaded module whose file sits in this
    directory — so new files participate automatically. The list is cached
    because this runs on every step of a colour-picker drag.
    """
    global _VP_MODULE_CACHE
    _current = {n: globals()[n] for n in _PALETTE_NAMES}
    if _VP_MODULE_CACHE is None:
        import sys as _sys
        _here = os.path.dirname(os.path.abspath(__file__))
        _cache = []
        for _mod in list(_sys.modules.values()):
            _f = getattr(_mod, '__file__', None)
            if _f and os.path.dirname(os.path.abspath(_f)) == _here:
                _cache.append(_mod)
        _VP_MODULE_CACHE = _cache
    for _mod in _VP_MODULE_CACHE:
        _d = getattr(_mod, '__dict__', None)
        if _d is None:
            continue
        for _k, _v in _current.items():
            if _k in _d:
                _d[_k] = _v


def apply_theme(dark: bool) -> None:
    """Switch all palette globals between dark and light, then rebuild stylesheet.

    Under the system-theme override the dark/light palettes are ignored in favour
    of the desktop's colours, but `dark` is still stored so the toggle keeps its
    state for when that override is turned off again.
    """
    global _DARK_MODE, BG, BG2, BG3, BG4, BORD, B2, FG, FG2, SEL, ACC, ACCH, SS
    _DARK_MODE = dark
    if _USE_SYSTEM_QT_THEME:
        # The scheme file beats the QPalette snapshot: tools like matugen rewrite
        # it directly, without qt6ct ever updating QApplication's live palette.
        pal = qt6ct_color_scheme_colors() or _system_palette_colors()
        ACC = pal['ACC']   # follow the desktop's own accent
    else:
        pal = _DARK if dark else _LIGHT
        ACC = _USER_ACC
    BG = pal['BG']; BG2 = pal['BG2']; BG3 = pal['BG3']; BG4 = pal['BG4']
    BORD = pal['BORD']; B2 = pal['B2']; FG = pal['FG']; FG2 = pal['FG2']
    SEL = pal['SEL']
    ACCH = make_acch(ACC)
    SS = make_stylesheet(ACC, ACCH)
    _broadcast_palette()
    app = QApplication.instance()
    if app:
        app.setStyleSheet(SS)
        _apply_app_palette(app)


def apply_system_qt_theme(enabled: bool) -> None:
    """Toggle 'use system Qt theme' mode.

    When enabled the whole palette comes from the system Qt theme instead of the
    built-in dark and light ones; disabling reverts to whichever of those matches
    the current _DARK_MODE flag.
    """
    global _USE_SYSTEM_QT_THEME
    _USE_SYSTEM_QT_THEME = enabled
    if enabled:
        # A no-op when the startup snapshot exists, which is the normal case
        _capture_system_palette()
    apply_theme(_DARK_MODE)


def is_system_qt_theme_active() -> bool:
    """True while the palette is being derived from the live system Qt theme."""
    return _USE_SYSTEM_QT_THEME


def is_applying_own_palette() -> bool:
    """True only while _apply_app_palette() is inside its app.setPalette() call.

    Distinguishes a real system-theme change from the paletteChanged Qt emits as
    a side effect of VoidPulse's own setPalette(). Without the check, each repaint
    would come back as a fake theme change and loop.
    """
    return _APPLYING_OWN_PALETTE


def resync_system_qt_theme(new_palette: 'QPalette' = None) -> None:
    """Re-sample the live system Qt palette and reapply it.

    Called when Qt reports a platform-theme change (paletteChanged), e.g. the
    color scheme changed in qt6ct, KDE System Settings, or any desktop speaking
    xdg-desktop-portal. QPalette is Qt's DE-agnostic surface for this, so no
    per-desktop code is needed.

    new_palette must be the QPalette from the paletteChanged signal. Reading
    QApplication.palette() instead returns VoidPulse's own derived colors (it has
    already called setPalette by this point), which feeds the output back into
    itself. Without the argument this is a no-op, as it is when system-theme mode
    is off.
    """
    if not _USE_SYSTEM_QT_THEME:
        return
    if new_palette is None:
        return
    _capture_system_palette(explicit_palette=new_palette)
    apply_theme(_DARK_MODE)


def apply_accent(color: str) -> None:
    """Update accent colour globally and broadcast to all modules.

    Called by ControlBar._on_accent_change(), so every other module sees the
    new ACC.
    """
    global ACC, ACCH, SS, _USER_ACC
    # Record the user's pick even while SYS mode is on, so config restore and
    # turning SYS back off both recover it instead of the built-in default.
    # Only the visible ACC is left alone in that case.
    _USER_ACC = color
    if _USE_SYSTEM_QT_THEME:
        # SYS mode drives ACC from the desktop via apply_theme(); a manual pick
        # must not override it, so there is nothing to broadcast.
        return
    ACC  = color
    ACCH = make_acch(color)
    SS   = make_stylesheet(ACC, ACCH)
    _broadcast_palette()
    app = QApplication.instance()
    if app:
        app.setStyleSheet(SS)

def _apply_app_palette(app):
    """Sync QPalette with current BG/FG globals."""
    global _APPLYING_OWN_PALETTE
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
    _APPLYING_OWN_PALETTE = True
    try:
        app.setPalette(pal)
    finally:
        _APPLYING_OWN_PALETTE = False

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
GST_BANDS     = 2048  # FFT bands, well above VIZ_BANDS for a cleaner mapping
OV_VIZ_H      = 60    # overlay viz height, px
MIN_DB        = -70.0
# Default for config.json's "viz_gamma" — the power-law exponent applied to the
# normalised [0,1] bar height. Below 1.0 lifts quiet bands, and the lower it goes
# the more it lifts them, until a busy mix flattens into a solid block; 1.0 is a
# straight dB scale. 0.38 was the original and left almost nothing at the floor.
# There is no slider for it: config.json is where it gets changed, and this value
# only applies to a config that has no key yet. See Player.set_viz_gamma.
VIZ_GAMMA     = 0.7
RAD_PCT       = 60   # corner radius: 0 is square, 100 a pill or circle

def _r(full_px: int) -> int:
    """Scale a corner radius by RAD_PCT.

    full_px is the radius at 100%, usually half the element's height, which gives
    a pill or a circle. At 0% the corners are square.
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
EQ_GAIN_MAX_GRAPH = EQ_GAIN_MAX   # graph range, matching the slider maximum

# Output ceiling the limiter brick-walls at; Player._make_sink_bin converts it to
# audiodynamic's linear threshold. The automatic EQ headroom stage deliberately
# aims for 0 dBFS instead: staging to this ceiling would cost every track another
# dB even with a flat EQ, and letting the brick wall trim a peak that was already
# at full scale is inaudible.
LIMITER_CEILING_DBFS = -1.0

# ── EQ filter types ───────────────────────────────────────────────────────────
# The last three ignore the gain value.
EQ_TYPE_PEAK       = 0
EQ_TYPE_LOWSHELF   = 1
EQ_TYPE_HIGHSHELF  = 2
EQ_TYPE_LOWPASS    = 3
EQ_TYPE_HIGHPASS   = 4
EQ_TYPE_NOTCH      = 5

EQ_TYPE_LABELS = {
    EQ_TYPE_PEAK:      'Peak',
    EQ_TYPE_LOWSHELF:  'Low Shelf',
    EQ_TYPE_HIGHSHELF: 'High Shelf',
    EQ_TYPE_LOWPASS:   'Low Pass',
    EQ_TYPE_HIGHPASS:  'High Pass',
    EQ_TYPE_NOTCH:     'Notch',
}

# Combo box order; the index equals the constant
EQ_TYPE_LIST = [
    EQ_TYPE_PEAK,
    EQ_TYPE_LOWSHELF,
    EQ_TYPE_HIGHSHELF,
    EQ_TYPE_LOWPASS,
    EQ_TYPE_HIGHPASS,
    EQ_TYPE_NOTCH,
]
# ══════════════════════════════════════════════════════════════════════════════
#  Stylesheet
# ══════════════════════════════════════════════════════════════════════════════


def make_stylesheet(acc: str = None, acch: str = None) -> str:
    if acc  is None: acc  = ACC
    if acch is None: acch = ACCH
    # Radii per element, from each one's own full-size height
    r_gen  = _r(12)   # menus, tooltips, dialogs, popups
    r_btn  = _r(18)   # standard buttons (36 px height → max 18 px pill)
    r_play = _r(26)   # play button (52 px → max 26 px circle)
    r_ctrl = _r(22)   # ctrl icon buttons (44 px → max 22 px circle)
    r_icon = _r(18)   # icon_btn buttons (36 px → max 18 px circle)
    r_grv  = _r(2)    # slider groove (4 px height → max 2 px)
    r_slh  = _r(7)    # EQ/settings slider handle (14 px → max 7 px circle)
    r_inp  = _r(15)   # text inputs & combo boxes (~30 px → max 15 px)
    # eq_type_combo renders 22px tall (min-height 16 + padding 4 + border 2).
    # r_inp is calibrated for a ~30px input and would ask for up to 15px here;
    # past about half a box's height Qt drops the rounding entirely instead of
    # clamping to a pill, so this radius is capped to what the box supports.
    r_eqtype = min(r_inp, 22 // 2)
    r_tbl  = _r(8)    # table & list container
    r_tab  = _r(5)    # tab bar top corners
    r_item = _r(6)    # list/tab item highlight
    r_scr  = _r(2)    # scrollbar handle (5 px wide)
    # Drop-down strip: rounded on the right, square against the box.
    # Qt's stylesheet parser accepts only one or two lengths for `border-radius`
    # — CSS's four-corner shorthand is dropped silently, which left the strip
    # square and painting its own corners over the combo's rounded outline.
    # Per-corner properties are the form Qt honours. The strip is laid out
    # inside the 1px border, so its radius is a pixel tighter than the box's.
    def _dd_right(radius: int) -> str:
        rr = max(radius - 1, 0)
        return ('border-top-left-radius:0; border-bottom-left-radius:0;'
                f'border-top-right-radius:{rr}px; border-bottom-right-radius:{rr}px;')
    r_dd_r = _dd_right(r_inp)
    r_dd_r_eqtype = _dd_right(r_eqtype)
    return f"""
* {{ outline: none; }}
QWidget     {{ background:{BG};  color:{FG};  font-size:13px; }}
QMainWindow {{ background:{BG}; }}
QDialog     {{ background:{BG}; border-radius:{r_gen}px; border:3px solid {ACC}; }}
QWidget#sidebar {{ background:{BG}; border-right:1px solid {BORD}; }}

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
/* Rounded at the start of the groove, square where the handle covers it. Written
   per corner because Qt ignores CSS's four-corner border-radius shorthand. */
QSlider::sub-page:horizontal {{
    background:{acc};
    border-top-left-radius:{r_grv}px; border-bottom-left-radius:{r_grv}px;
    border-top-right-radius:0; border-bottom-right-radius:0;
}}
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
    subcontrol-origin: padding; subcontrol-position: top right;
    border-left:1px solid {B2}; background:{BG2};
    width:30px; {r_dd_r}
}}
QComboBox::down-arrow {{ color:{FG2}; }}
QComboBox QAbstractItemView {{
    background:{BG3}; color:{FG}; border:1px solid {B2};
    selection-background-color:{SEL};
}}
QComboBox QAbstractItemView::item {{ min-height:30px; padding:0 8px; }}

/* EQ band-table "Type" combo. eq.py gives this cell control a 26px fixed
   height, but the generic QComboBox rule above (min-height:30px + padding +
   border) pushes the real box past that — stylesheet sizing wins over
   setFixedHeight() — and the pill then clips against the next table row.
   This ID rule (higher specificity) shrinks the box and the drop-down strip
   to fit 26px and leaves more width for the label.

   Background, colour, border and radius are restated rather than inherited:
   once this rule declares its own box model, the plain QComboBox rule's
   border-radius no longer applies and the corners come out square whatever
   RAD_PCT is set to. */
#eq_type_combo {{
    background:{BG3}; color:{FG}; border:1px solid {B2};
    border-radius:{r_eqtype}px; min-height:16px; padding:2px 6px; font-size:11px;
}}
#eq_type_combo:hover  {{ border-color:{acc}; }}
#eq_type_combo:focus  {{ border-color:{acc}; }}
#eq_type_combo::drop-down {{
    subcontrol-origin: padding; subcontrol-position: top right;
    border-left:1px solid {B2}; background:{BG2};
    width:16px; {r_dd_r_eqtype}
}}

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

QSplitter::handle {{ background:{BG2}; }}
QSplitter::handle:horizontal {{ width:16px; border-left:1px solid {BORD}; border-right:1px solid {BORD}; }}
QSplitter::handle:vertical   {{ height:16px; border-top:1px solid {BORD}; border-bottom:1px solid {BORD}; }}

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
QFrame#eq_popup,
QFrame#device_busy_popup {{
    background: transparent;
    border: none;
}}
"""

SS = make_stylesheet()


# ══════════════════════════════════════════════════════════════════════════════
#  Shared utilities — here rather than in a module, to avoid import cycles
# ══════════════════════════════════════════════════════════════════════════════

_lastfm_api_key  = ''    # from the config file or a fetch popup

_HTTP_UA = 'Mozilla/5.0 (X11; Linux x86_64) VoidPulse/2.0'


def _get_bytes(url, timeout=8, headers=None):
    """Fetch a URL and return the raw body bytes.

    Used for images. Decoding those as text would corrupt them, so text and
    binary fetches are kept apart.
    """
    h = {'User-Agent': _HTTP_UA}
    if headers:
        h.update(headers)
    req = _urlreq.Request(url, headers=h)
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get(url, timeout=8, headers=None):
    """Fetch a URL and return the body decoded as text."""
    return _get_bytes(url, timeout, headers).decode('utf-8', errors='replace')


def _get_json(url, timeout=8, headers=None):
    """Fetch a URL and parse the body as JSON."""
    return json.loads(_get(url, timeout, headers))


def _sanitize_filename_part(text: str) -> str:
    """Remove characters that are illegal in filenames on Linux/POSIX."""
    text = text.replace('/', '_').replace('\x00', '')
    return text.strip('. ')

def _open_audio(fp: str):
    """Open an audio file with mutagen, falling back to per-format classes.

    On a share that cannot seek (FTP/FTPS through GVfs) mutagen is handed a
    SeekableProxy instead of the path — it needs random access, and the raw
    FUSE file only reads forward. Every mutagen call in VoidPulse comes through
    here, so this one substitution is what gives those shares tags, durations
    and embedded covers.
    """
    src = fp
    if remote_io.is_nonseekable(fp):
        try:
            src = remote_io.SeekableProxy(fp)
        except OSError:
            return None
    try:
        af = MutagenFile(src, easy=False)
        if af is not None:
            return af
        ext = Path(fp).suffix.lower()
        # MutagenFile() sniffs content and consumes the stream doing it, so a
        # per-format retry has to start from the beginning again.
        if src is not fp:
            src.seek(0)
        try:
            if ext == '.opus':
                from mutagen.oggopus import OggOpus;    return OggOpus(src)
            if ext == '.ogg':
                from mutagen.oggvorbis import OggVorbis; return OggVorbis(src)
            if ext == '.flac':
                from mutagen.flac import FLAC;           return FLAC(src)
            if ext == '.mp3':
                from mutagen.mp3 import MP3;             return MP3(src)
            if ext in ('.m4a', '.aac'):
                from mutagen.mp4 import MP4;             return MP4(src)
            if ext in ('.wav', '.wave'):
                from mutagen.wave import WAVE;           return WAVE(src)
            if ext in ('.aiff', '.aif'):
                from mutagen.aiff import AIFF;           return AIFF(src)
        except Exception:
            pass
        return None
    finally:
        # The proxy's spill buffer can hold megabytes; the tags mutagen parsed
        # out of it are plain Python objects by now and do not need the stream.
        if src is not fp:
            try:
                src.close()
            except Exception:
                pass

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
