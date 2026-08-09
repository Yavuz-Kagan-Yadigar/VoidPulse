#!/usr/bin/env python3
"""VoidPulse driver — launches the real app in-process and drives it from stdin.

Why in-process instead of xdotool/ydotool: VoidPulse is Qt6, so QTest can post
real QMouseEvent/QKeyEvent into the widgets and QWidget.grab() can screenshot
them without any display server at all. That works identically on Wayland, X11
and in a container, and it is deterministic — no waiting for a compositor to
route a synthetic click. The host here is Wayland (no xdotool), which is exactly
the case this sidesteps.

Commands arrive over stdin through a QSocketNotifier rather than input(), so the
Qt event loop keeps spinning between commands. That matters: the GStreamer bus
poll, the fade ramps and the position interpolator are all QTimers, and a
blocking read would freeze playback mid-command.

  python3 .claude/skills/run-voidpulse/driver.py --help

Run from the project root (the directory holding player.py).
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]

# ── argv/env must be settled before Qt or the app modules are imported ────────
ap = argparse.ArgumentParser(description='Launch and drive VoidPulse.')
ap.add_argument('--platform', default='offscreen',
                help="Qt platform plugin: offscreen (default, no display server "
                     "needed) or xcb (needs DISPLAY, e.g. an Xvfb).")
ap.add_argument('--display', default=None,
                help='DISPLAY to use with --platform xcb, e.g. :99')
ap.add_argument('--profile', default='scratch', choices=('scratch', 'real'),
                help="scratch (default): copy the user's config into a throwaway "
                     "HOME so the run cannot clobber it. real: use the real "
                     "~/.config/voidpulse — it WILL be written on exit.")
ap.add_argument('--volume', type=int, default=0,
                help='Startup volume 0-100. Default 0 = silent. The pipeline is '
                     'real (pipewiresink), so anything above 0 is audible.')
ap.add_argument('--fade-ms', type=int, default=1400,
                help='Fade slider, ms. Nonzero is what makes transport state bugs '
                     'observable; 0 makes play/pause instant.')
ap.add_argument('--crossfade-ms', type=int, default=0,
                help='Crossfade, ms. Keep 0 for transport tests: a crossfade adds '
                     'a second overlapping pipeline.')
ap.add_argument('--track', action='append', default=[],
                help='Seed a playlist with this audio file. Repeatable. Needed on '
                     'a clean machine where no library is configured.')
ap.add_argument('--outdir', default='/tmp/voidpulse-run',
                help='Where screenshots land (default /tmp/voidpulse-run).')
ap.add_argument('--settle-ms', type=int, default=4000,
                help='Grace period after the window opens before commands run.')
args = ap.parse_args()

OUT = Path(args.outdir)
OUT.mkdir(parents=True, exist_ok=True)

real_home = Path(os.path.expanduser('~'))
real_cfg = real_home / '.config/voidpulse/config.json'

if args.profile == 'scratch':
    scratch = Path(tempfile.mkdtemp(prefix='voidpulse-home-'))
    (scratch / '.config/voidpulse').mkdir(parents=True)
    cfg = json.loads(real_cfg.read_text()) if real_cfg.exists() else {}
    cfg['volume'] = args.volume
    cfg['fade_ms'] = args.fade_ms
    cfg['crossfade_ms'] = args.crossfade_ms
    if args.track:
        tracks = [str(Path(t).resolve()) for t in args.track]
        cfg['playlists'] = [{'label': 'Driver', 'tracks': tracks}]
        cfg['known_paths'] = sorted({str(Path(t).resolve().parent) for t in args.track})
    (scratch / '.config/voidpulse/config.json').write_text(json.dumps(cfg))
    os.environ['HOME'] = str(scratch)
    print(f'[driver] scratch HOME={scratch} (real config untouched)')
else:
    scratch = None
    print(f'[driver] using REAL config at {real_cfg} — it will be written on exit')

os.environ['QT_QPA_PLATFORM'] = args.platform
# Without this Qt hunts for qt6ct / xdgdesktopportal; under offscreen that is
# pure noise at best and a stall at worst. voidpulse.py sets it for the human
# path — the driver wants it empty.
os.environ['QT_QPA_PLATFORMTHEME'] = ''
if args.platform == 'offscreen':
    os.environ.pop('DISPLAY', None)
    os.environ.pop('WAYLAND_DISPLAY', None)
elif args.display:
    os.environ['DISPLAY'] = args.display

sys.path.insert(0, str(PROJECT))

from constants import SS, _apply_app_palette, _capture_system_palette   # noqa: E402
from PyQt6.QtCore import QEventLoop, QSocketNotifier, Qt, QTimer        # noqa: E402
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap                # noqa: E402
from PyQt6.QtTest import QTest                                          # noqa: E402
from PyQt6.QtWidgets import QApplication                                # noqa: E402
from widgets_base import _SpinningOverlay                               # noqa: E402
from main_window import MainWindow                                      # noqa: E402

app = QApplication([])
app.setApplicationName('VoidPulse')
_capture_system_palette()
app.setStyleSheet(SS)
_apply_app_palette(app)

# MainWindow takes the splash so _load_config can wire the playlist loader's
# all_done before starting it. Constructing it without one is not supported.
splash = _SpinningOverlay.as_splash()
splash.show()
app.processEvents()

win = MainWindow(splash=splash, open_with=None)
win.resize(1500, 900)
win.show()

cb = win._ctrlbar
pl = win._player

WIDGETS = {
    'play': cb.btn_play, 'next': cb.btn_next, 'prev': cb.btn_prev,
    'shuffle': cb.btn_shuf, 'repeat': cb.btn_rep,
}

_shots: list = []
_fails: list = []


def pump(ms: int):
    """Advance the real event loop for ms — timers, GStreamer bus, ramps."""
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()


def resolve(name: str):
    if name in WIDGETS:
        return WIDGETS[name]
    obj = win
    for part in name.split('.'):
        obj = getattr(obj, part)
    return obj


def state() -> dict:
    """The distinction that matters: .playing is the pipeline, .ui_playing is
    what the button and MPRIS should show. They differ during a fade."""
    return {
        'playing': pl.playing,
        'ui_playing': pl.ui_playing,
        'ramping': pl._fade_timer.isActive(),
        'fade_gain': round(pl._fade_gain, 3),
        'pos_ms': pl.position_ms() if pl.has_pipe else None,
        'has_pipe': pl.has_pipe,
        'track': getattr(getattr(win, '_cur_track_mw', None), 'title', None),
    }


def shot(label: str, target='window'):
    w = win if target == 'window' else resolve(target)
    app.processEvents()
    pm = w.grab()
    path = OUT / f'{len(_shots):02d}-{label.replace(" ", "_")}.png'
    pm.save(str(path))
    _shots.append((label, pm, dict(state())))
    print(f'[shot] {path}  {state()}')


def filmstrip(name='filmstrip', scale=3):
    """One wide PNG of every shot taken — cheaper for an agent to read than N
    separate images."""
    if not _shots:
        print('[filmstrip] nothing captured')
        return
    w0 = _shots[0][1].width()
    h0 = _shots[0][1].height()
    pad, lbl = 26, 42
    strip = QPixmap(len(_shots) * (w0 * scale + pad) + pad, h0 * scale + lbl + pad * 2)
    strip.fill(QColor('#16181d'))
    p = QPainter(strip)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont(); f.setPointSize(11); p.setFont(f)
    x = pad
    for label, pm, st in _shots:
        p.drawPixmap(x, pad, pm.scaled(w0 * scale, h0 * scale,
                                       Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
        p.setPen(QColor('#e6e6e6'))
        p.drawText(x, pad + h0 * scale + 22, label)
        p.setPen(QColor('#9aa0aa'))
        p.drawText(x, pad + h0 * scale + 38,
                   f"playing={st['playing']} ui={st['ui_playing']}")
        x += w0 * scale + pad
    p.end()
    path = OUT / f'{name}.png'
    strip.save(str(path))
    print(f'[filmstrip] {path}')


def expect(key: str, want: str):
    got = state().get(key)
    want_v = {'true': True, 'false': False, 'none': None}.get(want.lower(), want)
    if isinstance(want_v, str) and isinstance(got, (int, float)):
        want_v = type(got)(want_v)
    ok = got == want_v
    if not ok:
        _fails.append(f'{key}: got {got!r}, want {want_v!r}')
    print(f'[{"ok" if ok else "FAIL"}] {key} == {want_v!r} (got {got!r})')


def wait_playing(timeout_ms=10000):
    waited = 0
    while waited < timeout_ms:
        pump(250); waited += 250
        if pl.playing:
            print(f'[wait] playing after {waited}ms'); return
    print(f'[wait] TIMEOUT after {timeout_ms}ms — still not playing')
    _fails.append('wait_playing timed out')


HELP = """commands (one per line, over stdin):
  click <w>          QTest.mouseClick — real press+release. w: play|next|prev|
                     shuffle|repeat, or an attribute path like _ctrlbar.btn_play
  key <name>         QTest.keyClick on the window, e.g. `key Space`
  pump <ms>          advance the event loop (playback keeps running)
  wait_playing [ms]  block until the pipeline reaches PLAYING
  state              print playing / ui_playing / ramping / pos
  shot <label> [w]   screenshot window (default) or a widget
  filmstrip [name]   compose every shot into one labelled PNG
  expect <k> <v>     assert on a state key; failures set exit code 1
  py <expr>          escape hatch, eval in the driver namespace
  quit               stop playback and exit
"""


def dispatch(line: str):
    line = line.strip()
    if not line or line.startswith('#'):
        return
    verb, *rest = line.split(None, 1)
    arg = rest[0] if rest else ''
    if verb == 'quit':
        finish()
    elif verb in ('help', '?'):
        print(HELP)
    elif verb == 'click':
        QTest.mouseClick(resolve(arg), Qt.MouseButton.LeftButton)
        print(f'[click] {arg}')
    elif verb == 'key':
        QTest.keyClick(win, getattr(Qt.Key, f'Key_{arg}'))
        print(f'[key] {arg}')
    elif verb == 'pump':
        pump(int(arg or 100))
    elif verb == 'wait_playing':
        wait_playing(int(arg) if arg else 10000)
    elif verb == 'state':
        print(f'[state] {state()}')
    elif verb == 'shot':
        parts = arg.split()
        shot(parts[0] if parts else 'shot', parts[1] if len(parts) > 1 else 'window')
    elif verb == 'filmstrip':
        filmstrip(arg or 'filmstrip')
    elif verb == 'expect':
        k, v = arg.split(None, 1)
        expect(k, v)
    elif verb == 'py':
        print(f'[py] {eval(arg, globals())!r}')
    else:
        print(f'[err] unknown command {verb!r} — try `help`')


def finish():
    try:
        pl.stop()
    except Exception:
        pass
    if _fails:
        print('FAILURES:\n  ' + '\n  '.join(_fails))
    else:
        print('ALL CHECKS PASSED')
    print(f'[driver] artifacts in {OUT}')
    if scratch is not None:
        shutil.rmtree(scratch, ignore_errors=True)
    # os._exit: GStreamer/soxr teardown on a normal exit prints nanobind leak
    # warnings and can hang on the pipewire thread join.
    sys.stdout.flush()
    os._exit(1 if _fails else 0)


print(f'[driver] settling {args.settle_ms}ms (library scan)…')
pump(args.settle_ms)
print(f'[driver] ready. platform={args.platform} fade_ms={pl._fade_ms} '
      f'volume={args.volume}. `help` for commands.')

notifier = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Type.Read)


def on_stdin():
    # Muted while a command runs: pump() spins a nested event loop, which would
    # otherwise re-enter this handler and interleave commands.
    notifier.setEnabled(False)
    try:
        line = sys.stdin.readline()
        if not line:
            finish()
        dispatch(line)
    except Exception:
        traceback.print_exc()
        _fails.append(f'command raised: {line.strip()!r}')
    finally:
        notifier.setEnabled(True)


notifier.activated.connect(on_stdin)
sys.exit(app.exec())
