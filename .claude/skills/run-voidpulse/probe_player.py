#!/usr/bin/env python3
"""Player without a window — a real Player against a stub GStreamer pipeline.

For changes to player.py state machines (transport, fades, drift, stall
recovery) this boots in ~2s instead of the driver's ~15s, needs no audio device,
and lets you step time precisely. It is the real Player class; only the playbin
handle is faked.

  import as a module:
      from probe_player import make_player
      app, pl, pump = make_player(fade_ms=400)
      pl.play_pause(); pump(500); print(pl.playing, pl.ui_playing)

  or run it directly for the play/pause fade regression check:
      python3 .claude/skills/run-voidpulse/probe_player.py
"""
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['QT_QPA_PLATFORMTHEME'] = ''
sys.path.insert(0, str(PROJECT))

from PyQt6.QtCore import QEventLoop, QTimer      # noqa: E402
from PyQt6.QtWidgets import QApplication         # noqa: E402
import gi                                        # noqa: E402
gi.require_version('Gst', '1.0')
from gi.repository import Gst                    # noqa: E402


class FakePipe:
    """Just enough playbin surface for the transport paths."""

    def __init__(self):
        self.state = Gst.State.PLAYING
        self.props = {'volume': 1.0}

    def set_state(self, st):
        self.state = st

    def get_state(self, timeout=0):
        return (1, self.state, Gst.State.VOID_PENDING)

    def query_position(self, fmt):
        return (True, 5 * Gst.SECOND)

    def get_property(self, k):
        return self.props.get(k, 0.0)

    def set_property(self, k, v):
        self.props[k] = v


def make_player(fade_ms=400, playing=True):
    """-> (app, player, pump). Player starts with a stub pipe already attached."""
    app = QApplication.instance() or QApplication([])
    Gst.init(None)
    from player import Player
    pl = Player()
    pl._pipe = FakePipe()
    pl._playing = playing
    pl._pos_playing = playing
    pl._fade_ms = fade_ms

    def pump(ms):
        loop = QEventLoop()
        QTimer.singleShot(int(ms), loop.quit)
        loop.exec()

    return app, pl, pump


def _regression():
    """play/pause must stay correct across a fade, including a reversing press."""
    app, pl, pump = make_player(fade_ms=400)
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f'{label}: got {got!r}, want {want!r}')
        print(f'  [{"ok" if got == want else "FAIL"}] {label}: {got!r}')

    print('press pause — icon state must flip immediately, mid-fade')
    pl.play_pause()
    check('ui_playing right after pause press', pl.ui_playing, False)
    check('pipeline still PLAYING mid-ramp', pl.playing, True)
    pump(600)
    check('pipeline paused once ramp ends', pl.playing, False)
    check('ui_playing after ramp', pl.ui_playing, False)

    print('press play, then press again mid-fade — must reverse, not re-pause')
    pl.play_pause(); pump(600)
    pl.play_pause()                     # start fading out
    pump(120)
    check('ui_playing mid pause-fade', pl.ui_playing, False)
    pl.play_pause()                     # reverse it
    check('ui_playing after reversing press', pl.ui_playing, True)
    check('never left PLAYING', pl.playing, True)
    pump(700)
    check('still playing after ramp', pl.playing, True)
    check('gain restored', round(pl._fade_gain, 2), 1.0)

    print('fade disabled — toggle must be instant')
    pl._fade_ms = 0
    pl.play_pause()
    check('instant pause', pl.playing, False)
    pl.play_pause()
    check('instant resume', pl.playing, True)

    _check_ramp_rate(check)
    _check_mute_gate(check)
    _check_reload_fade(check)
    _check_viz_follows_fade(check)

    print('\n' + ('ALL CHECKS PASSED' if not fails else 'FAILURES:\n  ' + '\n  '.join(fails)))
    # os._exit skips GStreamer/soxr teardown (nanobind leak spam, occasional hang
    # joining the pipewire thread) — but it also skips flushing, and stdout is
    # block-buffered when piped. Flush first or the whole run prints nothing.
    sys.stdout.flush()
    os._exit(1 if fails else 0)


def _check_ramp_rate(check):
    """A reversed ramp must run at the Fade slider's *rate*, not take its whole
    length to cover whatever sliver is left."""
    print('reversing a fade runs at the same rate, not the full duration')
    _, pl, pump = make_player(fade_ms=1000)
    pl.set_volume(1.0)
    pl.play_pause(); pump(1100)          # fully paused
    pl.play_pause(); pump(200)           # fade in, reaching ~10%
    level = pl._fade_gain
    pl.play_pause()                      # reverse
    pump(250)
    check('reversal from ~10% is done inside 250 ms', pl.playing, False)
    check('it really was a partial ramp', level < 0.35, True)


def _check_mute_gate(check):
    """The preroll mute and a running ramp must not overwrite each other."""
    print('preroll mute gate holds against ramp ticks')
    _, pl, pump = make_player(fade_ms=1000)
    pl.set_volume(1.0)
    pl.play_pause()                      # start a fade-out
    pump(150)
    tok = pl._gate_mute()
    pump(200)
    check('gate survives the ramp ticks', pl._pipe.props['volume'], 0.0)
    pl._gate_release(tok)
    check('release restores the ramp level, not full volume',
          0.0 < pl._pipe.props['volume'] < 0.95, True)
    print('a stale release cannot unmute the pipeline that replaced it')
    tok = pl._gate_mute()
    pl._gate_reset()                     # stands in for load()
    pl._gate_mute()
    pl._gate_release(tok)                # token from the superseded load
    check('stale token ignored', pl._pipe.props['volume'], 0.0)


def _check_reload_fade(check):
    """A resume that has to rebuild the pipeline still fades in — the ramp waits
    for the preroll mute instead of running to completion behind it."""
    print('fade-in survives a pipeline reload')
    from gi.repository import Gst
    _, pl, pump = make_player(fade_ms=800)
    pl.set_volume(1.0)
    pl.play_pause(); pump(900)           # paused
    pl._pipe.state = Gst.State.PAUSED
    tok = pl._gate_mute()                # stands in for the reload's preroll mute
    pl.fade_resume()
    check('armed rather than started', pl._fade_arm_in_ms, 800)
    pump(900)
    check('ramp did not run behind the mute', pl._pipe.props['volume'], 0.0)
    pl._gate_release(tok)
    pump(120)
    check('ramp starts when sound can be heard',
          0.0 < pl._pipe.props['volume'] < 0.4, True)
    pump(900)
    check('reaches full level', round(pl._pipe.props['volume'], 2), 1.0)


def _check_viz_follows_fade(check):
    """Bar heights must track the fade, sampled at the instant the frame being
    drawn belongs to rather than the live one."""
    print('viz bars follow the fade')
    import numpy as np
    from constants import GST_BANDS, VIZ_BANDS
    _, pl, pump = make_player(fade_ms=1000)
    pl.set_volume(1.0)
    # One FFT bin per display bar, no interpolation, no inertia.
    ba = np.arange(VIZ_BANDS, dtype=np.int32) * (GST_BANDS // VIZ_BANDS)
    pl.set_viz_tables(ba, ba.copy(), np.zeros(VIZ_BANDS, dtype=np.float32), 0.0)

    def frame():
        pl._viz_target[:] = -20.0
        pl._viz_spec[:]   = -20.0
        pl._compute_viz_frame()
        return float(pl._viz_bar_buf.mean())

    full = frame()
    pl._fade_gain = 0.5
    half = frame()
    pl._fade_gain = 0.0
    silent = frame()
    check('half level halves the bars', round(half / full, 2), 0.5)
    check('silence empties them', silent, 0.0)

    # The gain rides ControlBar's delay ring buffer inside the frame it scaled,
    # so it must be sampled live here — offsetting it again would delay it twice.
    pl._fade_gain = 1.0
    pl.play_pause()                      # 1000 ms fade-out
    pump(500)
    check('viz gain tracks the live ramp, no second delay applied',
          abs(pl._viz_gain() - pl._fade_gain) < 1e-9, True)
    check('the ramp really had moved', 0.05 < pl._fade_gain < 0.95, True)
    tok = pl._gate_mute()
    check('a muted pipeline draws no bars', pl._viz_gain(), 0.0)
    pl._gate_release(tok)


if __name__ == '__main__':
    _regression()
