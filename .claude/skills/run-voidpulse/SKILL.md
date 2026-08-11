---
name: run-voidpulse
description: Build, run, and drive VoidPulse, the PyQt6/GStreamer music player. Use when asked to start VoidPulse, launch or screenshot its UI, click its transport controls, reproduce a playback or fade bug, or test player.py behaviour.
---

VoidPulse is a PyQt6 + GStreamer music player. There is no build step and no
test suite; you verify changes by **driving the real app**. Two harnesses live
next to this file:

| harness | what it boots | cost | use it for |
|---|---|---|---|
| `.claude/skills/run-voidpulse/driver.py` | the whole app — `MainWindow`, real pipeline, real audio graph | ~15 s | UI, transport, MPRIS, anything a user clicks |
| `.claude/skills/run-voidpulse/probe_player.py` | `Player` alone against a stub playbin | ~2 s | `player.py` state machines: fades, drift, stall recovery |

Both run with **no display server** (`QT_QPA_PLATFORM=offscreen`) and drive the
app with `QTest` + `QWidget.grab()`. Do not reach for `xdotool`/`ydotool` — this
host is Wayland and has neither, and they buy nothing here: `QTest.mouseClick`
posts a real press+release into the widget, deterministically, on any platform.

All paths below are relative to the project root (the directory holding `player.py`).

## Prerequisites

Nothing needed installing on this machine — the deps were already present, so
there is no verified `apt-get` line to give. Check before assuming:

```bash
python3 - <<'EOF'
import importlib
for m in ['PyQt6.QtWidgets','PyQt6.QtTest','gi','numpy','mutagen','soxr']:
    try: importlib.import_module(m); print(f'  ok      {m}')
    except Exception as e: print(f'  MISSING {m}: {e}')
import gi; gi.require_version('Gst','1.0')
from gi.repository import Gst; Gst.init(None)
for el in ('playbin','pipewiresink','spectrum','audioresample','equalizer-nbands'):
    print(f'  {"ok     " if Gst.ElementFactory.find(el) else "MISSING"} gst:{el}')
EOF
```

All eleven print `ok` on this box. (`pyalsaaudio` appears in
`.claude/settings.local.json` but is imported nowhere — not a dependency.)

## Run (agent path)

Commands go in on stdin, one per line. Heredoc it:

```bash
python3 .claude/skills/run-voidpulse/driver.py <<'EOF'
click play
wait_playing
pump 1500
shot now-playing play
state
quit
EOF
```

Screenshots → `/tmp/voidpulse-run/` (override with `--outdir`), numbered in
capture order. `filmstrip` stitches every shot into one labelled PNG — read that
instead of N separate images.

| command | what it does |
|---|---|
| `click <w>` | `QTest.mouseClick`, real press+release. `w`: `play`/`next`/`prev`/`shuffle`/`repeat`, or an attribute path like `_ctrlbar.btn_play` |
| `key <name>` | `QTest.keyClick` on the window — `key Space` is play/pause |
| `pump <ms>` | advance the event loop; playback, fades and bus polling keep running |
| `wait_playing [ms]` | block until the pipeline reaches PLAYING (default 10 s) |
| `state` | `playing` / `ui_playing` / `ramping` / `fade_gain` / `pos_ms` / `track` |
| `shot <label> [widget]` | screenshot the window, or a widget: `shot mid-fade play` |
| `filmstrip [name]` | stitch all shots into one labelled PNG |
| `expect <key> <value>` | assert on a `state` key; any failure ⇒ exit code 1 |
| `py <expr>` | escape hatch, eval'd in the driver namespace |
| `quit` | stop playback, print pass/fail, exit |

Useful flags: `--track /path/to.flac` (seed a playlist — required on a machine
with no configured library), `--fade-ms`/`--crossfade-ms`, `--volume` (default
`0`), `--settle-ms`, `--profile real`, `--platform xcb --display :99`.

A worked example — the play/pause fade regression, all six states asserted and
screenshotted:

```bash
python3 .claude/skills/run-voidpulse/driver.py --outdir /tmp/voidpulse-run/transport <<'EOF'
click play
wait_playing
pump 1800
shot 1-playing play
click play
shot 2-press+0ms play
expect ui_playing false
expect playing true
pump 500
shot 3-midfade play
click play
shot 4-reversed play
expect ui_playing true
pump 2000
expect playing true
click play
pump 2200
shot 6-paused play
expect playing false
filmstrip transport
quit
EOF
```

## Direct invocation (no window)

For `player.py` changes, skip the app entirely:

```bash
python3 .claude/skills/run-voidpulse/probe_player.py     # play/pause fade regression, ~2s
```

Or build your own scenario against a real `Player`:

```python
import sys; sys.path.insert(0, '.claude/skills/run-voidpulse')
from probe_player import make_player
app, pl, pump = make_player(fade_ms=400)
pl.play_pause()                      # press pause
print(pl.playing, pl.ui_playing)     # True False  — pipeline still up, UI already paused
pump(600)
print(pl.playing, pl.ui_playing)     # False False
```

## Run (human path)

```bash
python3 voidpulse.py      # opens a maximized window on the real desktop. Ctrl-C to stop.
```

Verified only to the extent of launching and staying up for 20 s under Xvfb with
a scratch `HOME` — pointing it at a real session was not something to do
unprompted, because it uses the **real** `~/.config/voidpulse/config.json`, at
the user's real volume, and rewrites that file on exit. Prefer the driver.

## Gotchas

- **The app rewrites `~/.config/voidpulse/config.json` on exit.** Every driver
  run would stomp the user's volume, EQ, playlists and window geometry. That is
  why `--profile scratch` is the default: it copies the real config into a
  throwaway `HOME` and deletes it afterwards. Only pass `--profile real` if you
  actually mean to persist changes.
- **The pipeline is real even offscreen** — it builds a `pipewiresink` and plays
  actual audio. `--volume` defaults to `0` for that reason. Raising it will make
  noise come out of the user's speakers.
- **`fade_ms` is what makes transport bugs visible.** With Fade at 0 play/pause
  is instant and whole classes of bug vanish. The driver defaults to `1400`.
  Keep `--crossfade-ms 0` for transport work — a crossfade adds a second
  overlapping pipeline and a ghost.
- **`Player.playing` is not what the button shows.** During a fade the pipeline
  stays PLAYING for the whole ramp and only pauses in the completion callback.
  `Player.ui_playing` is the user-visible state (it reports the ramp's intent
  mid-fade). Assert on `ui_playing` for anything UI, `playing` for anything
  audio. Getting these backwards is the source of the stuck-icon bug class.
- **The first `click play` is not a toggle.** With no pipeline yet,
  `_play_pause()` routes to `_start_playback()`. Always `wait_playing` after the
  first click before treating further clicks as toggles.
- **`MainWindow` requires a splash object.** It takes ownership so `_load_config`
  can connect the playlist loader's `all_done` before starting it. Constructing
  `MainWindow(splash=None)` is not a supported path — the driver builds a real
  `_SpinningOverlay.as_splash()`.
- **Give it ~4 s to settle before clicking** (`--settle-ms`). Click too early and
  the library scan hasn't populated any tracks, so `click play` silently does
  nothing.
- **Read commands with `QSocketNotifier`, never `input()`.** The GStreamer bus
  poll, fade ramps and position interpolator are all QTimers; a blocking stdin
  read freezes playback mid-command. The driver already does this — the same
  trap applies to any ad-hoc script you write.
- **`os._exit()` skips flushing.** Both harnesses use it to dodge GStreamer/soxr
  teardown, and it discards block-buffered stdout when piped. `sys.stdout.flush()`
  first, or your entire run prints nothing and looks like a hang.
- **`QT_QPA_PLATFORMTHEME` must be cleared.** `voidpulse.py` sets it to
  `qt6ct`/`xdgdesktopportal` for the human path; leave it set under `offscreen`
  and Qt hunts for a platform theme plugin it will not find.

## Troubleshooting

- **Run prints nothing, exit code 0 or 1** — `os._exit` without a flush. See above.
- **`click play` does nothing, `state` shows `has_pipe: False`** — no tracks
  loaded. Either the settle period was too short, or the profile has no library:
  pass `--track /path/to/file.flac`.
- **`nanobind: leaked 1 instances! ... leaked type "soxr.soxr_ext.CSoxr"`** on
  exit — harmless teardown noise from the resampler binding, not a failure. Both
  harnesses avoid it with `os._exit`; you'll still see it if you exit normally.
- **`[Player] ALSA sink build failed for ...`** — the configured output device
  isn't openable here. The scratch profile inherits `output_device` from the real
  config; `pipewire` works on this box.
- **Want real rendering rather than offscreen** — start an X server first, then
  point the driver at it. Verified working:
  ```bash
  Xvfb :99 -screen 0 1600x1000x24 &
  python3 .claude/skills/run-voidpulse/driver.py --platform xcb --display :99 <<'EOF'
  click play
  wait_playing
  shot window-xcb
  quit
  EOF
  pkill -f "Xvfb :99"
  ```
  Xvfb spews `xkbcomp` keymap warnings (`Could not resolve keysym
  XF86ElectronicPrivacyScreenOn`, …) on startup — noise from the host's keymap,
  not a failure. Offscreen and xcb produce identical button pixels; xcb is only
  worth it if you suspect a compositing or native-window issue.
- **`pkill -f "Xvfb :99"` makes the shell report exit 144** — that's `128+SIGTERM`
  for the backgrounded job, not an error from your command.
