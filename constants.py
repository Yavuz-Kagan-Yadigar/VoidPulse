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
_USE_SYSTEM_QT_THEME = False  # when True, palette is derived from the system Qt theme instead of _DARK/_LIGHT

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
_USER_ACC = ACC  # user's own accent choice, remembered so SYS mode can override ACC
                 # without losing it, and restore it when SYS mode is turned off.
ACCH = '#ff4444'
FG   = _DARK['FG']
FG2  = _DARK['FG2']
SEL  = _DARK['SEL']

_SYSTEM_PALETTE_CACHE = None  # QPalette snapshot taken before we ever override app.setPalette()
_APPLYING_OWN_PALETTE = False  # guard: True while VoidPulse's own _apply_app_palette() is
                                # inside app.setPalette() — Qt fires paletteChanged for ANY
                                # setPalette() call, including our own, with no way to tell
                                # the difference from the signal alone. Without this guard,
                                # our own repaint would be misread as "the system theme
                                # changed", triggering apply_theme() again, which calls
                                # setPalette() again, which fires the signal again —
                                # an infinite feedback loop that looked like colors
                                # constantly flipping / chasing the picker.

# ══════════════════════════════════════════════════════════════════════════════
#  qt6ct color-scheme file watching
# ══════════════════════════════════════════════════════════════════════════════
# qt6ct's own platform plugin only reads its color-scheme .conf file once, at
# process startup — it does not watch the file itself, so it never emits a
# live QApplication.paletteChanged when that file changes underneath a
# running app. Tools like matugen (and wallust-driven Hyprland setups) work
# by rewriting that .conf file directly on disk, so under qt6ct there is no
# Qt-level signal to hook for a live update at all — every Qt app in this
# situation (KeePassXC, Dolphin, etc., not just VoidPulse) has the same gap.
#
# The only reliable, still-fully-event-driven fix is to watch the relevant
# files ourselves via QFileSystemWatcher (inotify-backed on Linux — zero
# polling, zero extra disk I/O beyond the one read triggered by an actual
# change) and re-parse+apply the color scheme directly when they change.
_QT6CT_WATCHER = None          # QFileSystemWatcher instance (kept alive via module global)

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

# Standard Qt QPalette::ColorRole order as written by qt6ct/qt5ct's
# active_colors= line (20 comma-separated hex values). Only the roles
# VoidPulse actually uses are named; the rest are parsed but ignored.
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
        return None   # unusable — caller falls back to whatever it had before

    window_hex, text_hex = window.name(), text_c.name()
    is_dark = window.value() < 128
    step = 0.06 if is_dark else -0.05

    fg2 = _blend(text_hex, window_hex, 0.45)
    # `mid` is present in every valid active_colors= line (it's a fixed-width
    # 20-field format), so this fallback only matters if the line was
    # malformed/truncated. Shade *toward* window brightness (lighter in dark
    # mode, darker in light mode) — same direction _system_palette_colors()
    # implicitly gets by using Mid directly, since Qt's own Mid role sits
    # between Window and WindowText in brightness.
    bord = mid.name() if mid is not None else _shade(window_hex, step)

    # Same black/unset-Highlight safety net as _system_palette_colors(), and
    # the same SEL != ACC contrast fix (see that function's comments) —
    # accent stays the vivid Highlight color, SEL is a muted, darkened,
    # desaturated version of it so playing-row text stays legible.
    sel_src = (highlight.name()
               if (highlight is not None and highlight.value() >= 20 and highlight.name() != window_hex)
               else None)
    acc_hex = sel_src if sel_src is not None else _USER_ACC
    sel_hex = _desaturate_darken(acc_hex, 0.5, 0.5) if sel_src is not None else acc_hex

    return dict(
        BG=window_hex,
        BG2=base.name() if base is not None and base.name() != window_hex else _shade(window_hex, step),
        BG3=alt_base.name() if alt_base is not None and alt_base.name() != window_hex else _shade(window_hex, step * 2),
        BG4=button.name() if button is not None and button.name() != window_hex else _shade(window_hex, step * 3),
        BORD=bord,
        B2=_shade(bord, step),
        ACC=acc_hex,
        FG=text_hex,
        FG2=fg2,
        SEL=sel_hex,
    )

def _qt6ct_files_to_watch() -> list:
    """Every path we currently need to watch: qt6ct.conf itself (so we
    notice if the user/matugen points it at a *different* scheme file) plus
    whichever scheme file it currently resolves to."""
    paths = []
    conf = _qt6ct_conf_path()
    if conf.exists():
        paths.append(str(conf))
    scheme = _qt6ct_active_color_scheme_path()
    if scheme is not None:
        paths.append(str(scheme))
    return paths

def start_qt6ct_live_reload(on_change) -> None:
    """Set up a QFileSystemWatcher (inotify-backed — no polling) on qt6ct's
    config + active color-scheme file, so external tools that rewrite that
    file on disk (matugen, wallust-based Hyprland scripts, etc.) are picked
    up live. qt6ct's own platform plugin does not re-read the file itself
    once the process has started, so this is the only way to react without
    restarting VoidPulse.

    `on_change` is called (with no arguments) whenever a watched file
    changes; the caller is expected to re-derive colors afterwards (see
    MainWindow._on_qt6ct_file_changed). No-op if qt6ct isn't configured at
    all (no qt6ct.conf found) — nothing to watch, nothing to do.
    """
    global _QT6CT_WATCHER
    paths = _qt6ct_files_to_watch()
    if not paths:
        return
    watcher = QFileSystemWatcher(paths, QApplication.instance())

    def _on_path_changed(_path):
        # Editors/tools often replace-then-rename a file rather than writing
        # in place, which drops it from the watch list — re-add whatever is
        # currently missing (including a newly-resolved scheme file if
        # qt6ct.conf itself changed which one is active) after each event.
        current = set(watcher.files())
        wanted = set(_qt6ct_files_to_watch())
        missing = wanted - current
        if missing:
            watcher.addPaths(list(missing))
        on_change()

    watcher.fileChanged.connect(_on_path_changed)
    _QT6CT_WATCHER = watcher   # keep alive — QFileSystemWatcher is GC'd otherwise

def qt6ct_color_scheme_colors() -> Optional[dict]:
    """Return the current qt6ct color-scheme-derived palette dict (parsed
    fresh from disk each call — only ever called from start_qt6ct_live_reload's
    on_change callback or once at startup, so this is not a hot path)."""
    scheme = _qt6ct_active_color_scheme_path()
    if scheme is None:
        return None
    return _parse_qt6ct_color_scheme(scheme)


def _capture_system_palette(explicit_palette: 'QPalette' = None) -> None:
    """Snapshot the OS/Qt-theme-provided QPalette.

    Only snapshots once via app.palette() (the very first call, right after
    QApplication() is constructed in voidpulse.py, before VoidPulse has ever
    called app.setPalette()/setStyleSheet() itself). Re-reading app.palette()
    at any later point would just read back VoidPulse's *own* colors (since
    _apply_app_palette() already overwrote it), not qt6ct's — so later calls
    are a no-op by default.

    Pass explicit_palette to force-set the cache to a specific QPalette
    instead — used when QGuiApplication.paletteChanged fires, since Qt hands
    us the new system palette directly as part of that signal and we don't
    need (and must not) go back through app.palette().
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
    """Derive the BG/FG/etc. hex palette VoidPulse uses internally from the
    real system Qt theme (falls back to the current style's standard palette
    if we never captured one)."""
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

    # Safety net: some qt6ct/system themes never actually set Highlight (Qt's
    # QColor.isValid() can't tell us this — it returns True even for a role
    # the theme left at Qt's own black default). If Highlight comes back
    # black, or effectively invisible against the window background, using
    # it verbatim as ACC would silently paint the play button, playing-track
    # text, active tab/playlist label, and viz bars all black. Fall back to
    # the user's own chosen accent (or the built-in default) in that case —
    # still "system-derived" everywhere else, just not for a role the theme
    # never actually populated.
    _sel_c = QColor(sel)
    if _sel_c.value() < 20 or _sel_c.name() == QColor(window).name():
        sel = _USER_ACC

    # NOTE: we deliberately do NOT use QPalette.ColorRole.PlaceholderText here.
    # QColor.isValid() only checks that the color can be parsed — it's true
    # even for a role the theme never actually set (Qt fills it with a
    # default, often pure black). That produced FG2 == "#000000" under
    # qt6ct/Hyprland themes that don't customize PlaceholderText, making
    # secondary/muted text render as solid black instead of a dim grey.
    # Blending WindowText 45% toward the window background reliably yields a
    # muted-but-legible secondary text color under both light and dark
    # system themes, matching how _DARK/_LIGHT define FG2 relative to FG/BG.
    fg2 = _blend(text, window, 0.45)

    is_dark = QColor(window).value() < 128
    step = 0.06 if is_dark else -0.05

    # SEL (row/list selection background) must NOT equal ACC (accent — also
    # used to paint the currently-playing track's text). Under system themes
    # both were being sampled from the same QPalette.Highlight role, so a
    # playing row that was also the selected row rendered accent-colored
    # text directly on an identical accent-colored background — invisible.
    # Desaturating + darkening Highlight by 50% for SEL keeps it recognizably
    # "the same hue" (still looks like a selection tint) while guaranteeing
    # legible contrast against the vivid ACC text painted on top.
    sel_bg = _desaturate_darken(sel, 0.5, 0.5)

    return dict(
        BG=window,
        BG2=base if base != window else _shade(window, step),
        BG3=alt_base if alt_base != window else _shade(window, step * 2),
        BG4=button if button != window else _shade(window, step * 3),
        BORD=bord,
        B2=_shade(bord, step),
        ACC=sel,
        FG=text,
        FG2=fg2,
        SEL=sel_bg,
    )


_VP_MODULE_CACHE = None  # populated lazily by _broadcast_palette()


def _broadcast_palette() -> None:
    """Push current palette + accent globals into every voidpulse module namespace.

    Because all modules do `from constants import BG, ACC, ...` they get *copies*
    of the strings at import time.  When apply_theme() or apply_accent() mutates
    the module-level globals here, those copies go stale.  This function fixes
    that by writing the new values back into every loaded module's __dict__ so
    that bare-name references (e.g. ``FG`` in a refresh_theme method) always see
    the current value without requiring every file to use ``import constants as _c``.
    """
    global _VP_MODULE_CACHE
    _PALETTE_NAMES = (
        'BG', 'BG2', 'BG3', 'BG4', 'BORD', 'B2',
        'FG', 'FG2', 'SEL', 'ACC', 'ACCH', 'SS', '_DARK_MODE', 'RAD_PCT',
    )
    _current = {n: globals()[n] for n in _PALETTE_NAMES}
    # ponytail: cache the actual module objects on first call instead of
    # rescanning all of sys.modules (1000+ entries) on every theme/accent
    # change — this fires repeatedly while the user drags the color picker.
    if _VP_MODULE_CACHE is None:
        import sys as _sys
        _vp_names = frozenset((
            'constants', 'controlbar', 'cover_art', 'dialogs_edit', 'eq',
            'fetch_popups', 'library', 'lyrics', 'main_window', 'metadata_online',
            'mpris', 'player', 'settings_popup', 'views', 'voidpulse',
            'widgets_base', 'blackout_overlay',
        ))
        _VP_MODULE_CACHE = [
            _mod for _name, _mod in _sys.modules.items() if _name in _vp_names
        ]
    for _mod in _VP_MODULE_CACHE:
        _d = getattr(_mod, '__dict__', None)
        if _d is None:
            continue
        for _k, _v in _current.items():
            if _k in _d:
                _d[_k] = _v


def apply_theme(dark: bool) -> None:
    """Switch all palette globals between dark and light, then rebuild stylesheet.

    If the system Qt theme override is active, the dark/light palettes are
    ignored in favour of colors sampled from the system Qt theme (see
    apply_system_qt_theme); `dark` is still stored so the DARK/LIGHT toggle
    keeps its state for when the system-theme override is turned back off.
    """
    global _DARK_MODE, BG, BG2, BG3, BG4, BORD, B2, FG, FG2, SEL, ACC, ACCH, SS
    _DARK_MODE = dark
    if _USE_SYSTEM_QT_THEME:
        # Prefer a freshly-parsed qt6ct color-scheme file (see
        # start_qt6ct_live_reload) over the QPalette snapshot — external
        # tools like matugen rewrite that file directly without qt6ct's
        # platform plugin ever updating QApplication's live palette, so the
        # file is the more current source of truth whenever qt6ct is in use.
        pal = qt6ct_color_scheme_colors() or _system_palette_colors()
        ACC = pal['ACC']   # follow the desktop's Highlight/accent color while SYS mode is on
    else:
        pal = _DARK if dark else _LIGHT
        ACC = _USER_ACC    # SYS mode off — restore the user's own accent choice
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


def apply_system_qt_theme(enabled: bool) -> None:
    """Toggle 'use system Qt theme' mode.

    When enabled, VoidPulse's entire color palette (backgrounds, foregrounds,
    borders, selection color) is derived from the system Qt theme rather than
    the app's built-in DARK/LIGHT palettes. When disabled, reverts to
    DARK/LIGHT based on the current _DARK_MODE flag.
    """
    global _USE_SYSTEM_QT_THEME
    _USE_SYSTEM_QT_THEME = enabled
    if enabled:
        # No-op if we already have a clean snapshot from startup (the normal
        # case) — see _capture_system_palette()'s docstring for why we must
        # NOT re-read app.palette() here (it would read back VoidPulse's own
        # colors, not qt6ct's).
        _capture_system_palette()
    apply_theme(_DARK_MODE)


def is_system_qt_theme_active() -> bool:
    """Return whether VoidPulse is currently deriving its palette from the
    live system Qt theme (qt6ct / KDE Plasma / any xdg-desktop-portal
    backend), rather than its own built-in DARK/LIGHT palettes."""
    return _USE_SYSTEM_QT_THEME


def is_applying_own_palette() -> bool:
    """True only while VoidPulse's own _apply_app_palette() is inside its
    app.setPalette() call. Used to distinguish a genuine live system-theme
    change (fires paletteChanged from outside VoidPulse) from the
    paletteChanged Qt fires right back at us as a side effect of our own
    setPalette() call — without this check, our own repaint would loop back
    around as a fake "system theme changed", triggering another repaint,
    forever."""
    return _APPLYING_OWN_PALETTE


def resync_system_qt_theme(new_palette: 'QPalette' = None) -> None:
    """Re-sample the live system Qt palette and reapply it.

    Called whenever Qt reports that the platform theme has changed
    underneath us (QGuiApplication.paletteChanged), e.g. the user switches
    the color scheme in qt6ct, KDE System Settings, or any desktop that
    talks to xdg-desktop-portal's org.freedesktop.portal.Settings. This is
    the mechanism that makes "follow the system theme" actually live rather
    than a one-time snapshot taken at startup — no per-DE code is needed
    here since QPalette is already the DE-agnostic surface Qt exposes for
    this.

    IMPORTANT: new_palette must be the QPalette Qt handed us as the
    paletteChanged signal argument. We must NOT fall back to reading
    QApplication.instance().palette() here — by the time this runs,
    VoidPulse has already called app.setPalette() with its own derived
    colors, so re-reading app.palette() would just feed VoidPulse's own
    output back into itself (colors would drift/freeze instead of tracking
    the desktop). If new_palette isn't supplied, this is a no-op.

    No-op if system-theme mode isn't currently enabled.
    """
    if not _USE_SYSTEM_QT_THEME:
        return
    if new_palette is None:
        return
    _capture_system_palette(explicit_palette=new_palette)
    apply_theme(_DARK_MODE)


def apply_accent(color: str) -> None:
    """Update accent colour globally and broadcast to all modules.

    Called by ControlBar._on_accent_change() after it updates its own locals.
    Ensures every other module (settings_popup, views, etc.) sees the new ACC.
    """
    global ACC, ACCH, SS, _USER_ACC
    # Always remember the user's own pick — including while SYS mode is on,
    # so that config restore (which loads the saved accent_color regardless
    # of SYS state) and toggling SYS back off later both recover the correct
    # color instead of falling back to the '#e03030' default. Only the
    # *visible* ACC is left alone while SYS is active (it stays following
    # the system Highlight color); _USER_ACC just tracks what to restore.
    _USER_ACC = color
    if _USE_SYSTEM_QT_THEME:
        # Don't let a manual accent pick visually override SYS mode's
        # system-derived accent — SYS mode is already driving ACC via
        # apply_theme(). Broadcast is skipped; there's nothing new to show.
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
