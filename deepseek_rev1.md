# VoidPulse — Detailed Code Review (`deepseek_rev1`)

**Reviewer:** DeepSeek (agent runtime)
**Date:** 2026-10-29
**Scope:** all 30 Python modules in the repository root plus `.github/scripts/appimage_smoke_test.py` (≈22,500 LOC), and packaging/repo hygiene.
**Method:** full read of every module, call-graph cross-checks, and targeted greps for risky patterns (signature verification, broad excepts, thread creation, main-thread blocking, app-wide event filters, deferred `QTimer.singleShot` work).

> Granularity note: a literal per-line commentary on 22.5k lines is not useful to a reader, so this document reviews **every file and essentially every function**, citing concrete line ranges, and records every defect or risk found. Severity tags: **CRITICAL / HIGH / MEDIUM / LOW / NIT**.

---

## Contents

1. Executive summary
2. Architecture at a glance
3. Cross-cutting findings
4. File-by-file review
5. Repository & packaging hygiene
6. Prioritised action plan
7. Static metrics

---

## 1. Executive summary

VoidPulse is a substantial, unusually well-commented PyQt6 + GStreamer music player. Quality is **above average for an indie codebase**: the author clearly understands GStreamer pipeline lifecycle, Wayland constraints, high-DPI painting, and hot-path allocation avoidance. Many comments document *measured* trade-offs, which is rare and valuable.

That said, the review found real correctness, threading and — most importantly — **security** problems:

| # | Severity | Finding | Where |
|---|----------|---------|-------|
| 1 | **CRITICAL** | Auto-updater installs downloaded packages with signature verification explicitly disabled on every backend (`--nogpgcheck`, `--allow-untrusted`, `--allow-unauthenticated`, `--nosignature`, `--force`), although `.asc` signatures are shipped with releases. No checksum is checked either. | `auto-update.py` 603–627, 671–701, 730–762 |
| 2 | **HIGH** | SFTP unknown host keys are auto-accepted (choice 0) → MITM possible on every `sftp://` share. | `remote.py` 241–245 |
| 3 | **HIGH** | Deferred seeks in `_load_and_seek` / `_reload_at_pos` are not bound to a pipeline identity; a track change within ~400 ms makes the **new** track seek to the **old** position. | `player.py` 746–803, 872–917 |
| 4 | **HIGH** | `_cover_cache` (`OrderedDict`) is read and mutated from worker threads without an effective lock; `LibraryRenameWorker` mutates it on a `QThread`. | `cover_art.py` 544–587, 617–624; `library.py` 143–218 |
| 5 | **HIGH** | Blocking D-Bus / `aplay` / `pw-metadata` / `wpctl` calls on the GUI thread, one repeating every 3 s while Settings is open. | `alsa.py` 233–249, 320–354; `player.py` 555–557, 1660–1694; `controlbar.py` 448 |
| 6 | **HIGH** | ALSA probe “confirms” a device after a fixed 800 ms whether or not the async error arrived → can confirm a broken device. | `main_window.py` 1727–1769 |
| 7 | **MEDIUM** | `config.json` is written non-atomically; a crash mid-write corrupts all settings and playlists (`update.json` is atomic — inconsistent). | `main_window.py` 2200 |
| 8 | **MEDIUM** | Per-track `threading.Thread(...).start()` in batch fetchers and tag dialogs → unbounded thread creation. | `fetch_popups.py` 508, 606; `dialogs_edit.py` 393–397 |
| 9 | **MEDIUM** | `_scan_threads` grows forever; QThread/QObject lifetimes in `LyricsPanel` and fetch popups can destroy objects on the wrong thread. | `main_window.py` 1191–1197; `lyrics.py` 488–513 |
| 10 | **MEDIUM** | Theme switch leaves stale explicit item foregrounds in tables (rows painted in the old `FG`/`ACC`). | `views.py` 1022–1037; `main_window.py` 478–545 |

**Positives worth keeping:** excellent module docstrings; careful GStreamer teardown on daemon threads (`_destroy`, `_kill_ghost`); pre-allocated NumPy viz buffers with `out=` everywhere; a single `drawImage` per frame; a single-instance async cover loader that constructs `QPixmap` only on the main thread; atomic `update.json`; passwords excluded from config and pushed to the keyring; thoughtful touch/Wayland handling; a real `_ModalOverlay` abstraction; and mostly clean separation between audio engine, UI and persistence.

---

## 2. Architecture at a glance

```
voidpulse.py (entry)
 ├─ constants.py star-import hub, palette/theme, stylesheet, net helpers
 ├─ main_window.py top-level QMainWindow, config, playback orchestration
 │ ├─ player.py GStreamer playbin engine (2.7k LOC)
 │ │ ├─ eq_filters.py pure biquad math
 │ │ ├─ player_dsp.py stereo-width bin, rganalysis
 │ │ ├─ resampler.py soxr bin + PipeWire/ALSA rate probes
 │ │ └─ alsa.py device enum, rate probe, D-Bus reservation
 │ ├─ controlbar.py seek/transport/viz; owns popups
 │ │ ├─ controlbar_widgets.py, eq.py, settings_popup.py, widgets_base.py
 │ ├─ views.py TrackTable, GalleryView, PlaylistPage, SeekSlider, TouchDrag
 │ ├─ sidebar.py, queue_panel.py, titlebar.py, lyrics.py
 │ ├─ cover_art.py, library.py, metadata_online.py, fetch_popups.py
 │ ├─ mpris.py MPRIS2 over GDBus
 │ ├─ remote.py + remote_io.py network shares (GVfs)
 │ └─ blackout_overlay.py
 ├─ auto-update.py GitHub release poll + install (loaded via importlib)
 └─ dialogs_edit.py
```

**Architectural caveat that shapes the whole review:** every module does `from constants import *`, and `constants.py` re-exports `math`, `Path`, `Gst`, all of `PyQt6.QtWidgets/Core/Gui`, etc. Since Python copies names at import time, the codebase then *rewrites module globals at runtime* via `_broadcast_palette()` (constants.py 484–514). That is the single most fragile decision in the project (§3.1).

---

## 3. Cross-cutting findings

### 3.1 Global-mutation theming and star imports — MEDIUM (maintainability, latent bugs)

- `constants.py:10–31` deliberately star-imports stdlib and all of Qt. Every other module therefore receives hundreds of names implicitly:
 - no static analyser can tell what a module actually uses;
 - collisions are silent (`enum`, `random`, `Optional`, `List`, `Path`, `Gst`, `GLib`, `Gio`, `QTimer`, …).
- `from constants import ACC` captures a *copy*; the code compensates by rewriting the `__dict__` of every loaded module (`_broadcast_palette`, constants.py 484–514). This only works for names in `_PALETTE_NAMES` (478–481) and only for modules already imported when the cache was first built — the cache is never invalidated. A module imported later (the lazily loaded `auto-update.py`, or any plugin) keeps stale colours.
- Any function that captured a palette value in a default argument or a closure at import time will not be updated. There is no such instance today, but it is a trap.
- `ControlBar._on_radius_change` (controlbar.py 1258–1294) does `global RAD_PCT` on a star-imported name, then also writes `_cm.RAD_PCT`, then calls `_broadcast_palette()` — three mechanisms for one value.

**Recommendation:** move to `import constants as C` everywhere (`views.py`, `queue_panel.py`, parts of `sidebar.py`, `auto-update.py` already do). Keep `constants` as data only; stop adding new `global` writes meanwhile.

### 3.2 Broad exception handling — LOW each, MEDIUM in aggregate

`grep` finds **161** `except Exception` clauses. Most are justified (network, mutagen, optional GStreamer elements), but a few hide real bugs:

- `cover_art.py:156` `read_metadata` swallows everything with no logging → library-wide corruption is invisible.
- `player.py:972` seek confirm-anchor swallows everything.
- `main_window.py:2213` config-save prints only; a failing disk write is invisible to the user.
- `library.py:597` M3U parse errors only print.

**Recommendation:** add a tiny `log_error()` (stderr + optional logfile) and keep `except Exception` only where a comment explains why.

### 3.3 Threading model — HIGH

There are **17** `daemon=True` threads plus several `QThread` subclasses. The pattern is mostly sound (signals back to the GUI thread), but there are concrete violations:

1. **Unsafe shared state** — `_cover_cache`, `_cover_locked_set`, `_rg_gain_cache`, `_rg_analyzing`, `_shares` are module-level and touched from worker threads. `AsyncCoverLoader._lock` (cover_art.py 610) guards only `_in_flight`, not `_cover_cache`.
2. **Unbounded thread creation** — `fetch_popups.py:508` (`embed_cover_bytes`), 606 (`write_tags_to_file`), `dialogs_edit.py:393` (`embed_lyrics`) spawn one thread per track; a 10k-track batch creates thousands.
3. **QThread/worker lifetime** — `LyricsPanel._abort` (lyrics.py 488–498) does `thread.quit(); thread.wait(300)` while `LyricsFetcher.run` may still be inside 8–14 s network waits. After 300 ms it drops the references; the `QObject` may then be destroyed by Python GC on the wrong thread → classic “QObject destroyed from wrong thread” crash. Same shape in `RenamePopup` / `_BaseFetchPopup`, which null `self._worker` in `_on_finished` without `deleteLater` in its own thread.
4. **`_scan_threads`** (main_window.py 65, 1197) is append-only; every Refresh adds a `ScanThread` that is never removed.

**Recommendation:** put the shared caches behind one `threading.RLock` or mutate them only on the GUI thread (post results via signals); use one `QThreadPool` for embed/write work; connect `thread.finished → thread.deleteLater` and `fetcher.finished → fetcher.deleteLater` and do not null references before the thread has actually finished; prune `_scan_threads` on `done`.

### 3.4 Main-thread blocking — HIGH

Several paths shell out or block on D-Bus from the GUI thread:

| Call | Max block | Trigger |
|---|---|---|
| `alsa.acquire()` → `_wait_pcm_free` | 3.0 s | every `load()` on a hw device (player.py 557, 1640) |
| `alsa.release(wait=True)` | 3.0 s | device switch (player.py 1678) |
| `probe_alsa_hw_rate` (`aplay`) | 2.0 s | first load / device switch (player.py 1767) |
| `live_pipewire_graph_rate` / `allowed_rates` / `default_sink_rates` | 1.5 s each | `_resolve_rate_plan` (player.py 1749) |
| `_resolve_rate_plan` from `ControlBar._refresh_audio_info` | up to ~4.5 s | every 3 s while Settings is open (controlbar.py 448, 1856–1864) |
| `wpctl status` in `_sink_available` | 2.0 s | startup (player.py 307) |

Caches help, but not the first call or TTL expiry (5 s for PipeWire probes). On a busy graph this visibly janks track changes.

**Recommendation:** probe rates on a background thread and cache per load; never call `_resolve_rate_plan()` from a 3 s UI timer — cache the label and refresh on device/rate-change events.

### 3.5 App-wide event filters — MEDIUM (performance)

All of these install `QApplication.instance().installEventFilter(...)`:

- `MainWindow` (main_window.py 101)
- `SettingsPopup` (settings_popup.py 57) — lives forever
- `EqPopup` (eq.py 183) — lives forever
- `_ModalOverlay` instances
- `TouchDrag` instances
- `RenamePopup` / `_BaseFetchPopup` while open

Every Qt event runs through each, in installation order. Mouse-move at 60 Hz through several filters doing `isinstance` and geometry math is measurable. `SettingsPopup.eventFilter` additionally calls `self.findChildren(QComboBox)` on every mouse press (789–792).

**Recommendation:** cache the combo list; prefer per-window filters; check `isVisible()` first in each filter.

### 3.6 Duplicated stylesheet strings and magic numbers — LOW

The same transport-button QSS appears verbatim at controlbar.py 185–190, 1305–1311, 1350–1356 and main_window.py 491–505. Extract a `transport_btn_qss()` helper. Timing constants (`350`, `400`, `500`, `600`, `800`, `1000`, `1500`, `0.15`, `0.5`, `0.6`) are scattered through player.py/main_window.py — name them.

### 3.7 No tests / no CI lint — MEDIUM

`grep` finds no test/pytest/tox/conftest. Given the pure math (`eq_filters.py`, resampler, `_eq_headroom_db`, LRC parser, `_build_new_filename`) and state machines (fades, gates, ALSA probe, updater version compare), unit tests are cheap and high-value. `.ruff_cache` is in the tree, so Ruff was run locally; add it to CI.

---

## 4. File-by-file review

### 4.1 `voidpulse.py` (92 lines)

**Purpose:** entry point, splash, auto-update bootstrap.

- `_load_auto_update()` (16–31): handles the hyphenated filename via `importlib.util.spec_from_file_location`, registers `sys.modules['auto_update']`, returns `None` on any failure. Correct and defensive; the updater can never block startup. NIT: failure only `print`s — consider `_log` to a file since auto-update is user-visible.
- `main()` (37–89):
 - 38–39 `QT_QPA_PLATFORM='wayland;xcb'` — correct preference order; Qt tries Wayland then falls back.
 - 43–47 `QT_QPA_PLATFORMTHEME`: `qt6ct` if installed else `xdgdesktopportal`. On KDE the session usually presets `kde`; acceptable. NIT: no `plasmatheme`/`kde` consideration.
 - 51 `_gc.set_threshold(5000, 10, 5)` — interacts with `ControlBar._start_render_timer()` calling `gc.disable()` and `_stop_render_timer()` calling `gc.enable()`. While the render timer runs GC is fully off regardless of threshold; the raised gen-0 threshold only matters between runs. Documented intent is fine, but note that if a code path calls `_stop_render_timer()` twice or never calls `_start`, GC remains enabled — the pairing is only correct because every start/stop is symmetric (verified in controlbar.py 1162–1176). **LOW:** one exception thrown between `gc.disable()` and `timer.start()` would leave GC off. `_start_render_timer` does `setInterval`, `gc.disable`, `timer.start` — `timer.start` cannot raise meaningfully. OK.
 - 54, 57: two daemon threads started before `QApplication`. `_purge_orphan_disk_covers` walks the cover dir; `remote_io.sweep_buffers` deletes `vpbuf-*`. Both touch the same `~/.config/voidpulse` / cache tree that `MainWindow._load_config` will touch moments later. No shared mutable Python state, so safe. **NIT:** if `CONFIG_PATH.parent` does not exist yet both threads handle it.
 - 59–63: `QApplication`, `_capture_system_palette()` **before** `setStyleSheet`/`_apply_app_palette` — the ordering is essential for SYS theme mode and is correct.
 - 66–73: splash created and centred on `primaryScreen()` only. Multi-monitor: appears on the primary display. **NIT.**
 - 77–79: `MainWindow(splash=..., open_with=...)` is constructed synchronously. This runs `Player()` (which calls `_detect_chain()` → up to 3 × `wpctl status`, 2 s timeout each, plus `Gst.parse_bin_from_description` for sinks) and `_load_config` (playlist loader is async, network mounts deferred). First-frame latency therefore depends on `wpctl`. See §3.4/§4.3.1. **MEDIUM** for perceived startup time on slow systems.
 - 81–87: `showMaximized()`, then `_load_auto_update()` and `check_on_startup(win)` which schedules a 4 s timer. Good: network never delays first frame.
 - 89 `sys.exit(app.exec())`.
- No `sys.excepthook` / `qInstallMessageHandler`: an uncaught exception in a Qt slot prints to stderr and continues (PyQt6 default aborts? — in PyQt6 an unhandled exception in a slot calls `qFatal`/abort by default). **MEDIUM:** install a handler that logs and shows a non-fatal message box, otherwise a bug in any slot kills the app with no user-facing explanation.

### 4.2 `constants.py` (1082 lines)

**Purpose:** palette/theme engine, stylesheet, shared helpers (the star-import hub).

- 5–9, 10–31: the star-import/re-export contract is documented. See §3.1. **MEDIUM.**
- 36–48 `IN_FLATPAK` / `host_cmd`: correct Flatpak detection via `/.flatpak-info`; prefixes commands with `flatpak-spawn --host`. Good.
- 57–90 `_read_app_version`: tries `$APPDIR`, `/app`, `/usr/share/metainfo`, `/usr/local/...`, then the checkout's `appdata.xml`; regex takes the first `<release version="…">`. Good, though it assumes newest-first ordering (AppStream convention holds). Returns `'0.0.0'` on failure, which `auto-update._version_from_metainfo` treats as unknown. Consistent.
- 104–134 palette globals and `_SYSTEM_PALETTE_CACHE` / `_APPLYING_OWN_PALETTE`: see §4.2.1 below for the loop risk.
- 139–143 `_QT6CT_WATCHER`: module global so the watcher is not GC'd — good.
- 145–230 colour maths:
 - `_shade` shifts HSV value clamped to [0,1]. Correct.
 - `_blend` linear RGB blend. Correct.
 - `_relative_luminance` / `_contrast_ratio`: correct WCAG formulas including the 0.04045 linearisation breakpoint.
 - `_muted_fg` (190–217): steps the blend in 5 % increments from the requested amount down to 0, returns the first candidate meeting the contrast floor against the worst surface; otherwise the best-scoring candidate. Solid.
 - `_desaturate_darken`: multiplies s and v by (1-amount). Correct.
- 233–388 qt6ct:
 - `_qt6ct_conf_path` / `_qt6ct_active_color_scheme_path`: reads `~/.config/qt6ct/qt6ct.conf`, resolves `color_scheme_path=`. `expanduser()` used; no `expandvars()`. **NIT.**
 - `_QT6CT_ACTIVE_COLORS_ORDER` (259–264) and `_parse_qt6ct_color_scheme` (266–335): parses the 20 comma-separated hex roles, validates hex, derives BG2/BG3/BG4 with `_shade`, FG2 with `_muted_fg`, SEL via `_desaturate_darken`. Good.
 - `start_qt6ct_live_reload` (349–378): `QFileSystemWatcher` on the conf and active scheme; re-adds missing paths after each change (replace-then-rename editors drop the watch). Good. Never removes stale paths; harmless.
- 391–472 palette capture/derivation: sound. **Latent risk** discussed next.

#### 4.2.1 Potential palette feedback loop — MEDIUM

`_apply_app_palette` (635–658) sets `_APPLYING_OWN_PALETTE = True` around `app.setPalette(pal)`. `MainWindow._on_system_palette_changed` (main_window.py 225) returns early if `is_applying_own_palette()`. This is correct **only if Qt emits `paletteChanged` synchronously** inside `setPalette`. If the platform plugin queues the signal (or emits it from another event), the flag is already `False` when the handler runs; the app then treats its own palette as a system change, calls `resync_system_qt_theme(new_palette)` → `apply_theme()` → `_apply_app_palette()` → another `paletteChanged`… The existing 600 ms coalescing timer damps this but does not eliminate oscillation (colours can drift toward the app's own derived palette). **Fix:** compare the incoming palette against the last one we set (store a tuple of window/text/base/highlight colours) and ignore a match, in addition to the flag.

- 484–514 `_broadcast_palette`: rewrites `_PALETTE_NAMES` in every module found by directory. The module cache is built once and never invalidated; `auto-update.py` is loaded *after* the first `apply_theme`, so if it ever reads `ACC` at import time it would be stale (it reads `_c.ACC` at use time via `constants as _c`, so it is fine). **MEDIUM** maintainability.
- 517–558 `apply_theme` / `apply_system_qt_theme`: correct; SYS mode prefers qt6ct scheme file over the `QPalette` snapshot, which is the right precedence (matugen/wallust rewrite the file). `_USER_ACC` preserved. Good.
- 561–587 `is_system_qt_theme_active` / `is_effective_dark` / `is_applying_own_palette`: fine.
- 590–609 `resync_system_qt_theme`: no-op without a new palette — documented, prevents reading the app's own palette.
- 612–633 `apply_accent`: in SYS mode records `_USER_ACC` and returns without broadcasting — correct.
- 660–664 `make_acch`: raises value by 0.25, drops saturation by 0.15, clamped. Good.
- 666–745: `SUPPORTED_EXT`, `CONFIG_PATH`, viz/EQ constants, `LIMITER_CEILING_DBFS=-1.0`, EQ type constants and labels. Consistent with `eq.py` and `eq_filters.py`.
- 694–700 `_r(full_px)`: scales radius by `RAD_PCT`; `round()`. Good.
- 751–976 `make_stylesheet`: one large f-string. It correctly documents Qt's rejection of four-corner `border-radius` shorthand and uses per-corner properties for the combo drop-down (778–783). `r_eqtype = min(r_inp, 11)` avoids Qt dropping rounding on the 22 px type combo. Comments explain the `#eq_type_combo` override (909–930). Thorough.
 - NIT: `QComboBox::down-arrow { color: … }` has no effect (arrow is a subcontrol image); harmless.
 - NIT: `QWidget { background:…; color:…; font-size:13px; }` is a universal selector that hits every child including QScrollBar internals; overridden where needed. Slight cost, fine.
- 990–1011 `_get_bytes` / `_get` / `_get_json`: **no response size cap** (`r.read()` unbounded). A hostile/broken endpoint can exhaust memory. Add a `max_bytes` with a streaming read. **MEDIUM (robustness).** Also no retry/backoff.
- 1014–1017 `_sanitize_filename_part`: strips `/`, NUL, and leading/trailing `.`/space. Does not handle `\ : * ? " < > |` — fine for Linux, but see `library.py` rename (§4.22): names intended to survive an SMB/Windows sync can become invalid. **LOW.**
- 1019–1068 `_open_audio`: correct `SeekableProxy` substitution for non-seekable shares, `MutagenFile` first then per-format fallback, `seek(0)` before retry (because `MutagenFile` consumes the sniff window), closes the proxy in `finally`. Good.
- 1070–1082 `_apply_scroller_properties`: sensible kinetic-scroll tuning; `touch` flag gates flick tuning. Good.

### 4.3 `player.py` (2686 lines) — the audio engine

The most complex file. Reviewed by section.

#### 4.3.1 Construction & chain detection (101–352)

- `__init__` (101–288): extensive state. A few attributes are only set later and read via `getattr(..., default)` elsewhere:
 - `_sink_bin` set in `load()` (560); `_warning_is_sink_side` uses `getattr(..., None)` (2316). OK but **LOW**: declare in `__init__`.
 - `_stream_restore_reset` set in `load()` (524); `_on_msg` uses `getattr(..., True)` (2351). OK.
 - `_gain_gate_token`, `_fade_arm_in_ms`, etc. declared. Good.
- `_sink_available` (290–337):
 - `pipewiresink`: checks `/run/user/<uid>/pipewire-0*`, then `wpctl status` (2 s timeout, **not** `LC_ALL=C`), string-splits `Audio`→`Video`→`Sinks:`→`Sources:` and regexes for a node line, then constructs and NULLs a `pipewiresink` bin. **LOW:** the split heuristic is brittle across `wpctl` versions/localisation; set `LC_ALL=C` like the `pactl` call does.
 - `pulsesink`/`autoaudiosink`/`alsasink`: `set_state(READY)` probe. Fine.
- `_detect_chain` (339–352): iterates 3 PipeWire entries first; if PipeWire is absent this costs 3 × `wpctl` (6 s worst case) before falling back. **MEDIUM (startup latency).** Cache the result in `update.json`/config or probe once.
- `_is_hw_device` (354–357): simple and used consistently.
- Local-copy machinery (361–479): well-reasoned one-reader-at-a-time design; `_on_copy_done` discards a finished copy if the user moved on; `_begin_seek_fetch` anchors the seekbar at the target and tears the pipeline down before reading. Good. NIT: `_start_local_copy` starts a raw `threading.Thread` (395) — fine, one at a time.

#### 4.3.2 `load()` (481–648)

- 483 sets `_last_filepath` before any failure path; `play_pause` dead-pipe recovery relies on it. Acceptable.
- 487–498 crossfade/ghost handling then `_destroy()` then `_gate_reset()`. Correct ordering: `_detach_to_ghost` moves the old pipe out before `_destroy` would tear it down.
- 500–502 `playbin` unavailable → `sig_err` and return; `_pipe` stays `None`. Good.
- 507–521 local-copy reuse: correct.
- 522 `Path(...).as_uri()`. Good.
- 535–539 optional `track` avoids tag re-reads (important on non-seekable shares). Good.
- 542–553 ReplayGain hold: pauses, takes a gate hold, emits busy, starts analysis. See §4.3.9 for the single-token caveat.
- 557 `_sync_alsa_reservation()` → **blocking `alsa.acquire()` on the GUI thread (up to 3 s)**. **HIGH** (§3.4).
- 559–571 `_make_sink_bin`; on hw failure emits error and returns (leaving `_pipe` non-None and `_playing=False` after `_destroy`). Fine.
- 579–602 spectrum `audio-filter` built dormant (1 h interval) and enabled by `_update_spec_active`. Clever; avoids FFT running before PLAYING. Good.
- 604–606 bus + timer. Good.
- 608–614 always `PLAYING` then deferred pause on ASYNC_DONE — necessary for `pipewiresink`. Good.
- 616–621 anchor preservation. Good.
- 630–639 crossfade fade-in. Good.
- 642–646 600 ms `_post_load_confirm`: harmless if a new track loaded (anchors the *current* pipe to its real position). OK.
- 647–648 `sig_playing(True)` unless silent. Good.

#### 4.3.3 `play_pause` (650–744)

- 664–685 fade branch uses `_fade_intent` to decide direction — correct, because `_playing` stays True during a pause ramp. Reversal handled. Good.
- 686–694 plain pause freezes the interpolated position **before** `_playing=False`, then anchors. Correct.
- 696–709 resume path: `get_state(timeout=0)` + pending fallback; dead pipe → `_resume_with_reload`. Good.
- 711–716 long-pause log only; stall watcher handles reclaim. Good.
- 718–742 resume: reset anchor wall time, burst, viz discard, deferred anchor + one retry. Good.

#### 4.3.4 `_load_and_seek` (746–803) — **HIGH race**

Deferred closures call `self.seek(p)` / `self._anchor_from_gst()` against `self._pipe` as it is *at callback time*. `_gate_release(tok)` is generation-guarded, but the **seek and anchor are not**. A track change within 400 ms (rapid clicks, a concurrent `_resume_with_reload`, an ALSA probe) makes the new pipeline seek to the old position. Same pattern in `_reload_at_pos` (901–915), `main_window._alsa_probe_and_play._after_seek` (1693–1700) and `_on_pipewire_restart_done` (1612).

**Fix:** capture `pipe = self._pipe` (or a `_load_serial`) at scheduling time and guard each callback with `if self._pipe is not pipe: return`. The deferred-pause handler in `_on_msg` already demonstrates the right identity check (`pending is self._pipe`, 2388).

#### 4.3.5 Reload paths (805–917)

- `_resume_with_reload` (805–856): `_reloading` guard reset after 1000 ms. If a real reload exceeds 1 s (network preroll), a second error inside the window is dropped (not a crash, but recovery can be skipped). **MEDIUM.**
- `_reload_at_pos` (872–917): `_reload_guard` reset after 600 ms — released before the 400+350 ms seek/anchor completes. Acceptable but tight.
- Both inherit the unguarded-seek issue above.

#### 4.3.6 `seek` (919–978)

- 924–928 non-seekable → fetch. Correct.
- 931–938 non-blocking state query; bounded retry (6 × 100 ms). Good.
- 943 anchor before seek (UI responsiveness); 946 serial bump; 947–950 viz reset + 150 ms discard. Good.
- 951–957 `seek_simple(FLUSH|ACCURATE)`; re-`set_state(PLAYING)` if playing; burst. Good.
- 961–975 250 ms confirm-anchor, only emit if within 80 ms. Good.
- 978 `sig_seek.emit()` even on failure — MPRIS `Seeked` may fire for a failed seek. **LOW.**

#### 4.3.7 Volume / fade / gate (980–1287)

- `set_volume` (980–993) clamps and emits only on integer-percent change. Good.
- `_effective_volume` (995–1008): ALSA `/7.5` is an unexplained magic divisor (**NIT** — document); multiplies fade and gate. Correct.
- Gate (1049–1083): nested holds + generation tokens; `_gate_release` runs an armed fade-in when the last hold drops. Excellent design and documentation.
- `_start_fade` (1087–1130): `scale` shortens the duration for partial ramps; zero-length path calls `done_cb`; sets `_fade_intent` for `ui_playing`. Good.
- `_tick_fade` (1154–1169) monotonic; calls `done_cb` once. Good.
- Ghosts (1171–1230): `_detach_to_ghost` captures `v0`, starts a per-ghost timer; `_tick_ghost` equal-power fade-out; `_kill_ghost` NULLs on a daemon thread. Good. **MEDIUM:** the detached pipe's spectrum element is never disabled (only `self._spec_el` is dropped), so the FFT keeps posting at 30 fps for up to the crossfade length. Disable it in `_detach_to_ghost`.
- `fade_pause` (1232–1256): zeroes bars and restores `_fade_gain=1.0` after pausing. Good.
- `fade_resume` (1258–1287): arms via gate when muted. Good.

#### 4.3.8 Viz input (1289–1330; 2462–2685)

- `set_viz_tables` / `set_viz_gamma` (clamp 0.05–3.0) / `set_viz_active` / `set_overlay_needs_spectrum` / `_update_spec_active`: correct; interval vs `post-messages` both toggled (post-messages alone does not stop audioconvert work). Good.
- `_store_spectrum` (2462–2554): serial guard, 150 ms discard window, cached field index, `GstValueList` fast path and `to_string()` fallback, 8-slot ring with peak-fold. Well engineered.
- `_compute_viz_frame` (2565–2685): paced release at 30 Hz (double-drain on backlog), time-scaled EMA, `np.take(out=)` frequency mapping, clip/normalise/gamma, gain scaling after EMA, copy into published buffer. Allocation-free. Excellent.

#### 4.3.9 EQ / preamp / loudness (1332–1580)

- `set_eq_enabled` / `set_limiter_enabled` / `set_stereo_enabled` (1332–1365) all call `_resume_with_reload`. **MEDIUM bug:** while `_reloading` is True the reload is dropped but the flag is already updated, so the live chain can disagree with the toggle (e.g. switch EQ on twice quickly → second reload dropped → filters still absent). Track a `_reload_requested` flag and re-run on completion.
- `_headroom_probe_grid` (1378–1396): grid resolution derived from the sharpest UI peak (`EQ_Q_MAX`) — correct and well justified.
- `_eq_headroom_db` (1402–1441): evaluates the cascaded complex response on that grid, skips zero-gain gain-types, returns peak dB (>0 only). Correct.
- `_effective_preamp_linear` (1443–1473): gain staging with loudness folded into the headroom budget; verified against the docstring cases. Good.
- `_effective_track_gain_db` (1475–1482): tag first, cached analysis second. Good.
- `_analyze_loudness_async` (1484–1498): dedupes with `_rg_analyzing`; emits `_sig_gain_analyzed`. Module-global caches mutated from a thread (set ops are atomic enough here). OK.
- `_on_gain_analyzed` (1500–1531): resumes a held load; emits `sig_busy(False)` **last** so the icon sync is correct. Good.
- `_apply_preamp` (1533–1550): read-back compare because `audioamplify` stores float32. Good.
- `set_preamp_db` / `set_loudness_norm` / `set_balance`: live updates. Good.
- `_apply_eq_to_filters` / `_glib` (1582–1625): recomputes coefficients per band, bypass identity for zero-gain types; also re-applies preamp because the headroom changed. Good. NIT: assumes `_eq_filters[i]` matches `_eq_bands[i]`, true because both come from the same ordered build.

#### 4.3.10 Sink chain (1627–2017)

- `_sync_alsa_reservation` (1627–1643): blocking `acquire`/`release` on GUI. **HIGH** (§3.4).
- `shutdown` (1645–1657): ghosts, fetch, copy, destroy, `alsa.release()`. Good.
- `set_output_device` (1659–1694): kills ghosts, updates device, invalidates ALSA cache or `release(wait=True)`, then destroys and schedules a reload in 150 ms. **HIGH** blocking + **MEDIUM** two scheduled loads if called twice quickly.
- `set_pipewire_adaptive_rate` (1696–1722): same 150 ms scheduling pattern. **MEDIUM.**
- `_active_sink_desc` (1724–1747): correct `stream-properties` string; sets `node.rate` for passthrough/resample so PipeWire retunes the graph. Good.
- `_resolve_rate_plan` (1749–1817): ALSA discrete/range/legacy; PipeWire adaptive path cross-checks graph allowed-rates against sink rates before requesting the native rate; graph-rate fallback. Sound logic; cost is the issue (§3.4).
- `_make_sink_bin` (1819–1981):
 - preamp `audioamplify` (clipping-method 3) — correct to avoid playsink hijacking `volume`.
 - balance `audiopanorama method=0` — no mono downmix.
 - EQ bin; limiter `audiodynamic` hard-knee ratio 0.0 at `10^(LIMITER_CEILING_DBFS/20)`; stereo bin; limiter appended **after** stereo (widening adds up to +6 dB). Correct ordering.
 - resample stage; equal-rate collapsed to passthrough; explicit pad checks; `(None, [])` on failure. **LOW:** on failure leaves `_preamp_el`/`_balance_el` set to discarded elements; reset them.
- `_create_eq_bin` (1983–2017): always 10 `audioiirfilter`s. Identity filters are cheap but non-zero; **LOW (perf)**.

#### 4.3.11 Anchors & properties (2019–2090)

- `playing` / `ui_playing` (2020–2034): `ui_playing` honours `_fade_intent` during a ramp. Correct.
- `_anchor_now` / `_anchor_from_gst` (2045–2064): requires steady PLAYING/PAUSED with no pending transition — good.
- `position_ms` (2066–2090): fetch-target short-circuit; interpolate when playing; clamp to cached duration. Good.

#### 4.3.12 Teardown & position timer (2092–2254)

- `_destroy` (2092–2147): cancels fade, stops bus, clears `_pipe` **before** the daemon NULL, resets gates and guards, preserves anchors during silent recovery. Good.
- `_start_pos_burst` / `_tick_pos` (2149–2198): burst to 100 ms then back to 250 ms; drift query deferred with `singleShot(1, ...)` and `_drift_pending`. Good.
- `_check_xfade_point` (2200–2220): once per track, requires `dur > 2*crossfade`. Good.
- `_drift_query_glib` (2222–2254): non-blocking queries on the main thread, resets `_drift_pending` in `finally`. Good.
- `_apply_drift_correction` (2256–2288): corrects >100 ms drift after 1.5 s from resume; stall detection (>0.7 s no forward progress) triggers `_resume_with_reload`. **MEDIUM:** on a buffering network track the queried position can legitimately freeze while PLAYING, causing repeated reloads ~1 s apart; suppress while `sig_buffering` is active or during initial buffering.

#### 4.3.13 Bus & messages (2302–2460)

- `_warning_is_sink_side` (2302–2325): provenance walk to the sink bin, defaults to True. Good fix for giosrc/queue2 “close resource” noise.
- `_poll_bus` (2327–2344): drains with `timed_pop_filtered(0)`; mask excludes QOS/STATE/TAG/STREAM_STATUS/LATENCY. Good.
- `_on_msg` (2346–2460):
 - ASYNC_DONE: one-shot `pactl` stream-restore reset on a daemon thread; deferred pause guarded by `pending is self._pipe`. Good.
 - EOS: signals only, never touches the pipeline (because `sig_end` can load the next track synchronously). Important and correct.
 - ERROR: distinguishes “buffers removed” (reload) from fatal (destroy + `sig_err`). Good.
 - WARNING: sink-side keyword heuristic; ALSA warnings never reload. Good.
 - ELEMENT: spectrum only when needed. Good.

#### 4.3.14 `player.py` summary

| Issue | Sev |
|---|---|
| Unguarded deferred seek/anchor closures (4 sites) | HIGH |
| Blocking `alsa.acquire/release` on GUI thread | HIGH |
| Rapid EQ/limiter/stereo toggles dropped by `_reloading` | MEDIUM |
| Ghost spectrum keeps FFT running during crossfade | MEDIUM |
| Stall detector may loop on buffering/network stalls | MEDIUM |
| Double reload scheduling (device/adaptive-rate, 150 ms) | MEDIUM |
| `_detect_chain` worst-case 6 s of `wpctl` at startup | MEDIUM |
| `_make_sink_bin` failure leaves dangling element refs | LOW |
| 10 identity EQ filters when EQ on | LOW/perf |
| Unexplained ALSA `/7.5` volume divisor | NIT |

### 4.4 `player_dsp.py` (211 lines)

**Purpose:** stereo-width Gst.Bin and ReplayGain analysis.

- `_StereoWidthBin.__init__` (22–60): `audioconvert → identity → audioconvert`, F32LE stereo forced on the link, ghost pads, buffer probe on identity's src. Sound design (rewrites buffers in Python without an appsrc split).
- `_process` (65–97): M/S maths, reuses three scratch arrays, returns a view of `_scratch_out` valid until next call. Correct; `src` is read-only and never copied.
- `_on_buffer` (99–138):
 - Unity fast path when `|w-1| < 2e-6`. Good.
 - Maps READ, builds a read-only numpy view, processes, `tobytes()`, unmaps, wraps a new buffer, copies `pts/dts/duration/offset`.
 - **MEDIUM (correctness):** the new buffer **does not carry buffer flags** (`DISCONT`, `GAP`, `DELTA_UNIT`) nor `Gst.Buffer` metadata; only the four timing fields are copied. Gapless/segment/gap handling can regress when stereo enhance is enabled. Use `buf.copy_region(Gst.BufferCopyFlags.FLAGS | …)` or set `new_buf.set_flags(buf.mini_object.flags)`. Also copy `new_buf.offset_end`.
 - **MEDIUM (perf/robustness):** removing and re-adding the pad probe around every `pad.push()` to avoid re-entry is costly per buffer and racy. Prefer a `self._pushing` boolean guard at the top of `_on_buffer` (return OK/DROP when set) or `identity` signal-handoffs.
- `_run_rganalysis` (151–211): throwaway `filesrc → decodebin → audioconvert → audioresample → rganalysis → fakesink`, TAG/EOS/ERROR bus loop with timeout, NULL in `finally`. Good. NIT: `fakesink sync=False` correct; `num-tracks=1` correct.

### 4.5 `eq_filters.py` (128 lines)

**Purpose:** biquad coefficients (Audio EQ Cookbook).

- `peaking_coefficients` (19–31), `lowshelf_coefficients` (34–47), `highshelf_coefficients` (50–63), `lowpass_coefficients` (66–77), `highpass_coefficients` (80–91), `notch_coefficients` (94–105): all match RBJ’s formulas and normalise by `a0`. Spot-checked signs and the shelf `sq = 2·√A·α` term — correct.
- `_COEFF_DISPATCH` / `eq_band_coefficients` (108–128): unknown types fall back to peak; any exception (e.g. `Q=0`) returns `None`, which callers treat as identity. Good defensive contract.
- **NIT:** no test vectors. This is the ideal place for property tests (`fs=48k`, `f0` sweep → `|H(f0)|≈gain` for peaking). Add to CI.

### 4.6 `resampler.py` (412 lines)

**Purpose:** soxr resampler Gst.Bin and PipeWire/ALSA rate lookups.

- `SoxrResamplerBin.__init__` (45–104): `audioconvert → capsfilter(F32LE, rate=in) → [probe] (dead end)` plus `appsrc → audioconvert → ghost src`. Buffer probe reads input; event probe mirrors FLUSH/SEGMENT/EOS; upstream-event probe relays SEEK. The comments explain why appsink double-counted the preroll buffer and why seeks die on the unlinked pad. Good.
- `_ensure_stream` (106–116): builds the soxr stream per channel count and fixes appsrc caps. Good.
- `_on_buffer` (118–151):
 - `channels = caps.get_structure(0).get_int('channels')[1] if caps else 0` — **verify**: with PyGObject, `GstStructure.get_int()` (the override) returns an int and raises if missing; if so, `[1]` raises `TypeError`. Inside a C probe this is logged/ignored and the buffer is dropped → silence whenever resampling is active. Make it binding-agnostic (`val[1] if isinstance(val, tuple) else val`). **MEDIUM (potential total-silence bug on some bindings).**
 - Copies the mapped data (`frombuffer(...).copy()`), reshapes, `resample_chunk`, pushes. Correct.
- `_on_upstream_event` (153–169): relays only SEEK to the real sink pad, drops it locally. Good.
- `_mirror_flush` (171–181): `appsrc.send_event` so GstBaseSrc pauses/restarts its task properly. Good.
- `_sync_duration` (183–197): copies duration to appsrc once. Good.
- `_on_event` (199–236): FLUSH_START/STOP mirror and clear soxr history; SEGMENT stores and re-anchors; EOS flushes the soxr tail and emits appsrc EOS. Correct.
- `_push_output` (238–256): PTS from `_pts_base + frames·SECOND/rate`; uses `push-sample` with the stored segment so appsrc re-emits it after a seek. Good.
- `build_resampler_stage` (259–276): `None` on equal rates (caller disambiguates), soxr if available, `audioconvert ! audioresample` fallback. Good.
- PipeWire lookups (285–412): TTL-cached `pw-metadata` / `wpctl` / `pw-cli` parsing, wrapped in try/except. Fragile text parsing but contained. **LOW:** `pw-metadata` is not wrapped in `host_cmd`, unlike `wpctl`, so inside a Flatpak sandbox it may fail while `wpctl` works; harmless (falls back) but inconsistent.

### 4.7 `alsa.py` (355 lines)

**Purpose:** device enumeration (`/proc/asound`), rate probing (`aplay`), ReserveDevice1 D-Bus reservation.

- `probe_alsa_devices` (49–87): parses `/proc/asound/cards`, globs `pcm*p`, labels multi-PCM cards with `id:`/`name:`. Correct Flatpak reasoning (no `aplay` needed). Good.
- `_parse_rate_field` (93–110): `[lo hi]`→range, else discrete sorted set. Correct.
- `probe_alsa_hw_rate` (113–144): `aplay --dump-hw-params /dev/zero` via `host_cmd`, timeout handling with kill+communicate, caches only successes. Good. **HIGH** only because callers run it on the GUI thread (§3.4).
- Reservation:
 - `pcm_ids` (189–210): regex for `hw:`/`plughw:`; numeric card ids direct, named ids resolved through `/proc/asound/<id>` symlink. Correct.
 - `_pcm_in_use` / `_wait_pcm_free` (213–249): reads `/proc/asound/.../sub*/status`, treats unreadable as proceed, polls 20 ms up to 3 s. **HIGH** when called from `acquire` on the GUI thread.
 - `_session_bus` / `_request_name` / `acquire` (252–305): `RequestName` with REPLACE_EXISTING|ALLOW_REPLACEMENT|DO_NOT_QUEUE, waits for PCM free. Idempotent; releases previous card first. Correct protocol. NIT: cached `_conn` never reconnects if the bus restarts.
 - `_name_has_owner` / `release(wait)` (308–354): release + optional poll for re-owner. Correct.
- **Recommendation:** run acquire/release on a worker thread and emit a signal; or gate behind a modal “Switching output…” overlay.

### 4.8 `remote_io.py` (311 lines)

**Purpose:** seekable proxy for sequential GVfs shares + local copy buffer.

- Registry: `register_share` / `forget_share` / `_match` / `is_nonseekable` (48–80): normalized prefix match, treats `seekable is not False` as seekable (None → seekable, matching legacy behaviour). Good. `_shares` is mutated from the GUI thread only (mount probe result), read from worker threads during tag reads — **LOW** (dict reads are atomic; a concurrent replace is benign).
- `buffer_dir` (91–106): XDG cache, not `/tmp` (avoids tmpfs RAM), falls back to tempdir. Good.
- `copy_to_local` (109–152): 64 KiB chunks, cancellable, progress callback (deduped by percent), short-read check, deletes partial on any exception. Good.
- `discard_local` (155–164): refuses paths outside `buffer_dir()`. Good safety.
- `sweep_buffers` (167–184): deletes `vpbuf-*` at startup. Good.
- `SeekableProxy` (189–310):
 - Lazy forward pull with spill-to-temp above 8 MiB; `seek` never transfers. Good.
 - `_spill_over` writes accumulated memory then appends; `_slice` reads absolute offsets from spill. Correct.
 - `read(n<0)` (247–257): pulls the **entire** remaining file into memory/spill. If a caller does an unsized read on a multi-GB file the disk cache fills. **MEDIUM:** cap it or raise beyond a limit.
 - Missing `readinto`, `readline`, `fileno`, `__len__`. Mutagen formats in `SUPPORTED_EXT` evidently work, but a future format may call `fileno()`/`readinto()`. **LOW/MEDIUM:** implement `readinto` and `fileno` (raising `io.UnsupportedOperation`) explicitly.
 - Not thread-safe — documented; each read creates its own instance in `_open_audio`. Good.

### 4.9 `main_window.py` (2507 lines)

**Purpose:** top-level window, widget tree, signal wiring, config save/restore, playback orchestration, ALSA probe, network shares, tags, “Open With”.

#### 4.9.1 Construction & UI (39–301)

- `__init__` (40–101): frameless window; `Player()` created eagerly (blocking probes); `_build_ui`, `_connect_signals`, `_load_config`, `MprisServer`, app-wide event filter. Ordering is correct (`_ctrlbar` exists before MPRIS uses `cover_on()`).
 - 77–78 `_queue` pre-declared because `_advance` may read it early — good defensive note.
 - 88 `_blackout = BlackoutOverlay()` constructed eagerly; a failure here kills startup. Fine.
- `_build_ui` (103–189):
 - `body` splitter (sidebar | tabs | right dock); right dock is a **vertical** splitter holding lyrics over queue. Good consolidation (documented).
 - 145–147 `QueuePanel`, `set_track_resolver(self._resolve_track)` — avoids tag re-reads on drop. Good.
 - 157–160 stretch factors + `setSizes([230, 1050, 0])`; magic numbers but reasonable.
 - 162–168 library page created and wired; 170 `ControlBar(self._player)`; 171 back-patches `_lyrics_panel._ctrlbar` — a two-phase init smell (**NIT**; pass ctrlbar in after construction or via setter is already effectively that).
 - 174–183 vertical splitter (body over ctrlbar); sizes `[800, 172]`.
 - 184 `self._status = self.statusBar()`.
 - 188 `DeviceBusyPopup(central)` child, floats above content.
- `setWindowTitle` override (190–193) syncs the custom titlebar. Good.
- `_apply_decoration_mode` (195–223): toggles flags, hides/shows titlebar, restores maximised/visible state. Correct handling of Qt hiding the window on `setWindowFlags`.
- `_on_system_palette_changed` / `_do_system_palette_resync` (225–272): coalesced 600 ms; stores the signal's palette (`_pending_system_palette`) instead of re-querying `app.palette()` — exactly right. See §4.2.1 for the residual loop risk.
- `_on_qt6ct_file_changed` / `_do_qt6ct_file_resync` (274–300): coalesced 600 ms; calls `apply_theme(_DARK_MODE)`. Good.

#### 4.9.2 Signal wiring (302–384)

- Sidebar requests, mounter, sleep timer, player signals, ctrlbar buttons, lyrics/queue panels, settings popup, cover loader. Comprehensive.
 - 353–355 `sig_pos` → lambda gated on `_blackout.isVisible()`; avoids work when overlay hidden. Good.
 - 374 `pop = self._ctrlbar._ensure_settings_popup()` — **forces eager construction** during `_connect_signals`, defeating the “lazy popup” intent and installing `SettingsPopup`'s app-wide event filter at startup. **LOW** (startup + per-event cost, §3.5).
 - 379–383 a second debounce timer for settings saves (500 ms). Fine.

#### 4.9.3 Theme refresh (478–556)

- `_refresh_all_theme_widgets` (478–545): stage 1 synchronous (now-playing labels, current page, ctrlbar, play/ctrl inline QSS, titlebar, device popup); stage 2 deferred (lyrics, queue, settings, eq, sidebar); stage 3 one page per event-loop tick with overlay close at the end. Good.
 - **MEDIUM defect:** stage 3 only calls `pg.table.set_playing_row(pg.playing_idx)` and `gallery.set_playing(...)`. `TrackTable.set_playing_row` writes explicit `ForegroundRole` brushes on the **two** rows it touches (prev playing, new playing). Every row that was ever the playing row but is not now retains its old explicit `FG` brush (and bold=False). After switching dark→light, those rows stay painted in the old (near-white) `FG` on a light background → invisible text. `PlaylistPage.refresh_theme()` (views.py 1934–1939) only repaints the table. **Fix:** add `TrackTable.refresh_theme()` that iterates all rows and re-applies `ACC`/bold to `_playing_row` and `FG`/normal to the rest.
 - 491–505 inline play/ctrl QSS duplicated from `controlbar.py` (§3.6).
- `_on_accent_refresh` / `_refresh_theme_no_overlay` (547–556): good.
- `_on_pos_for_lyrics` (558–569): gates on visibility/focus; subtracts viz delay. Good; reads private `_ctrlbar._delay_ms` (**NIT**).

#### 4.9.4 Panels & queue (571–734)

- `_panel_open` (584–594): `not panel.isHidden()` — correct reasoning for collapsed dock/minimised window.
- `_toggle_side_panel` / `_sync_right_dock` / `_size_right_dock` / `_on_dock_split_moved` (596–663): width moved between content and dock; ratio remembered as a fraction; `mouseButtons()==NoButton` filters programmatic relayouts. Well done.
- `_toggle_lyrics` / `_toggle_queue` (665–672).
- `_resolve_track` (674–687): linear scan over all pages × tracks per queue drop. **LOW** (O(n) with large libraries; build a dict once per rebuild).
- `_on_queue_changed` (689–697): debounced save. Good.
- `_add_to_queue` (699–703).
- `_show_ctx_menu` (705–734): Play / Add to Queue / Add to Playlist (bisect insert, no re-sort) / Remove from Playlist / Edit Tags. `bisect.bisect_left([t.sort_key() for t in tracks], sk)` builds the key list per invocation — fine for a menu action. Good.

#### 4.9.5 Covers & tag editing (736–928)

- `_invalidate_cover_cache` (736–765): drops memory keys, deletes the exact disk key + sidecar (never a stem glob — important, and documented), re-enables the file in the async loader (`_no_embed.discard`, `_in_flight.discard`). Good.
- `_edit_tags` (767–928):
 - Pre-flight: read magic 4 bytes; EBML → explain ffmpeg remux. Good UX.
 - `TagEditDialog` + `_ModalOverlay.show_for`. Good.
 - Per-format write branches; `af.save()` failure gives a DASH hint for MP4. Good.
 - Cover set/remove branches; master pixmap built synchronously **before** repopulating pages so caches are consistent. Careful.
 - `read_metadata(fp)` re-read after save; updates every page + ctrlbar + MPRIS + lyrics. Good.
 - **MEDIUM:** `_open_audio`/`af.save()` runs on the GUI thread. On a network path this can block for seconds. Consider a worker for the write.
 - **LOW:** the cover-remove branch for Ogg/Opus does `af2.tags.pop('metadata_block_picture', None)` — fine, but it does not normalise case like `_vtag` does; some taggers write `METADATA_BLOCK_PICTURE`. Minor.
- `except Exception as e` (926–928) prints and shows a status message. Acceptable.

#### 4.9.6 Playlists (930–1317)

- `_new_playlist_dialog` (930–970): asks name, picks first known folder (or asks), sanitises, writes `#EXTM3U`, creates page, applies view settings from the popup, sets `_m3u_path`. Note `_ensure_settings_popup()` here again forces construction (it is constructed at startup anyway). Good.
- Sleep timer (974–1014): `_on_sleep_timer_changed` restarts timers, formats countdown, `_on_sleep_expired` fades and stops. `reset_sleep_minutes` blocks signals to avoid re-arming. Good.
- Network shares (1018–1141):
 - `_network_share_dialog` blocks in `dlg.exec()`. Good.
 - `_connect_share` stores pending meta, mounts.
 - `_on_share_mounted` **pops the password before saving** (1060) — correct security posture, documented.
 - `_start_seek_probe` / `_on_seek_probe_done`: registers the share before scanning; explains non-seekable behaviour. Good. `self._seek_probes` is pruned to unfinished probes on each start but never cleared on completion — the list holds finished `SeekProbe` objects for the session. **LOW** (small, but unbounded per mount).
 - `_remount_saved_shares` (1125–1141): re-probes mounted shares at startup; mounts the rest. Good.
- `_add_folder_dialog` / `_import_m3u_dialog` / `_export_m3u_dialog` (1143–1179): straightforward. Export writes `#EXTINF` + path; no escaping of newlines in titles. **LOW** (a title with `\n` corrupts the M3U).
- `_refresh_library` (1181–1189): clears the **memory** cover cache and rescans every non-M3U path. Disk covers survive (mtime sidecars). Good.
- `_scan_path` / `_on_scan_done` (1191–1228):
 - `ScanThread` started; `self._scan_threads.append(t)` **never pruned** — **MEDIUM** unbounded growth; each holds a finished QThread.
 - `_on_scan_done` refresh path matches playlists by **label** (1205) — duplicate labels collide (the library has no uniqueness constraint on playlist labels). **LOW/MEDIUM.**
 - A new page gets current popup view settings and column widths. Good.
- `_rebuild_library` (1230–1269): one-time rename-tmp recovery (good), dedupe by filepath, sort, playing row from `player._last_filepath` (falls back to page index). Good.
- `_remove_playlist` / `_rename_playlist` / `_move_playlist` (1271–1311): tab indices assume tab 0 is the library; `_rename_playlist` uses `tab_idx = idx + 1` which is **wrong if a `__open_with__` hidden playlist exists in `_playlists`** (it is appended to `_playlists` but has no tab). `_show_ctx_menu`/`_move_playlist` share the same `idx + 1` assumption. **MEDIUM:** the hidden Open-With playlist desynchronises sidebar index ↔ tab index, so renaming/moving/removing a playlist after an Open-With can hit the wrong tab. Filter `__open_with__` out of the index math or don't store it in `_playlists`.

#### 4.9.7 Playback control (1320–1471)

- `_play_from_page` (1320–1338): queue row → `take_row`; page row → set `_cur_page/_cur_idx`; then `_alsa_play`. Good.
- `_queue_ready` (1340–1347): closed panel ⇒ inert. Documented.
- `_playing_track` / `_mark_playing` (1349–1382): queued track outranks page row; `_mark_playing` uses exact row on the source page and filepath match elsewhere. Careful and correct.
- `_alsa_play` (1384–1406): PipeWire → direct; ALSA → probe if needed. Good.
- `_start_playback` (1408–1429): `arm_crossfade`, `load(track=t)` (no re-read), ctrlbar/title/MPRIS/blackout updates. Good.
- `_navigate_track` (1431–1457): loads and optionally pauses with `play_pause(fade=False)`. Good.

#### 4.9.8 Device / ALSA probe (1459–1792)

- `_on_output_device_changed` (1459–1475): derives `hw:` from `plughw:`, schedules probe. Good.
- `_on_switch_to_pipewire` / adaptive-rate file sync / `_on_adaptive_rate_toggled` / `_restart_pipewire` / `_on_pipewire_restart_done` (1477–1613):
 - `_PW_ADAPTIVE_RATE_CONTENT` writes a global PipeWire config drop-in; the confirmation dialog explains it affects all apps and needs a restart. Responsible.
 - `_sync_pipewire_adaptive_rate_file` only writes/removes on explicit toggle or restoring a saved opt-in. Good.
 - `_restart_pipewire` runs `systemctl --user restart ...` on a daemon thread with a 20 s timeout via `host_cmd`. Good.
 - `_on_pipewire_restart_done` reloads the pipeline after 400 ms **without a pipeline-identity guard** (1612) — same deferred-seek race class as §4.3.4. **MEDIUM.**
- `_alsa_probe_and_play` (1621–1769):
 - Schedule: `hw:`, `plughw:`, `hw:`+2 s, `plughw:`+2 s, `hw:`+4 s. Generation counter cancels superseded probes. Good.
 - **HIGH defect:** `_run()` loads the track and then `QTimer.singleShot(800, lambda: _check(idx, device))`; `_check` calls `_confirm(device)` when `self._alsa_probe_error` is empty. The GStreamer error for a busy/unopenable device arrives asynchronously (bus message polled every 20 ms, but only **after** the sink is built and the pipeline errors). 800 ms is a race, not a confirmation: on a slow/busy machine the error may arrive after `_confirm`, so the UI reports “confirmed” for a device that then errors, and `_on_player_error` re-probes (defeating the point). **Fix:** confirm on the first ASYNC_DONE without error, or on `sig_playing(True)` plus a clean bus, with a timeout fallback; do not use a fixed delay.
 - `_confirm` mutes via the gate, seeks, releases; handles paused resume. Good use of the gate.
 - `_give_up` shows `DeviceBusyPopup`. Good.
- `_on_player_error` (1771–1792): records error, re-probes if not already probing. Good.

#### 4.9.9 Misc (1794–2507)

- `_on_buffering` (1794–1804): status text with percent. Good.
- `_on_player_busy` (1806–1812): spinner + MPRIS busy + icon sync on completion. Good.
- `_on_shuffle_toggled` / `_on_repeat_changed` (1814–1821): `GLib.idle_add(self._mpris._emit, [...])` — reaches a private method from outside; **NIT** (works).
- `_pick_initial_source` / `_play_pause` (1823–1863): cold start prefers current tab, queue first if ready; `ui_playing` for icon. Good.
- `_prev_track` (1865–1879): queued track backs out to the page position. Good semantics.
- `_sync_cur_idx` / `_advance` (1883–1957): queue-first, then repeat-one, then shuffle (skip-over without list allocation), then sequential with repeat-all wrap; `from_xfade` with nothing to fade into rewinds and lets EOS stop. Careful and well documented.
- `_on_track_end` / `_on_crossfade_due` (1959–1970).
- `changeEvent` / `_update_activity_state` (1973–2037): recomputes activity from scratch (idempotent); pauses render/pos timer when unfocused unless opt-out; handles minimised. Good. `_was_active` rising-edge reset. Good.
- `eventFilter` (2039–2108): touch/tablet reset idle, mouse-move >5 px (squared, no sqrt), key press. Cheap early-outs. Good.
- `_apply_search` / `_on_tab_change` / `_update_count` (2110–2124).
- `_on_col_widths_changed` / `_save_config` (2127–2214):
 - `_save_config` **non-atomic** write: `CONFIG_PATH.write_text(json.dumps(cfg, ...))`. A crash/power loss mid-write truncates config.json → all playlists, known paths and settings lost. `auto-update._save_state` already does temp+`os.replace`; use the same here. **MEDIUM.**
 - Skips saving while `_config_loader` is running and re-arms the debounce — good.
 - Writes M3U8 for `_m3u_path` playlists. Good.
 - `cfg['playlists']` excludes `__open_with__`. Good.
 - `network_shares` strips `password`. Good.
 - `table_col_widths` from the library table only; other pages get synced via `_on_col_widths_changed`. Fine.
- `_close_splash` / `_handle_open_with` (2216–2295): Open-With inserts into a hidden playlist, rebuilds, selects the row, updates UI **without creating a pipeline** (deliberate, documented) and sets `_cur_page/_cur_idx`. Good. Note it leaves `_cur_page` as the library, so a later `_advance` follows the library. Fine.
- `_load_config` (2297–2406):
 - Restores known paths, network shares (deferred remount 600 ms), cover locks, Last.fm key, gallery flags, system theme (applied **before** `init_from_config`), background-opt flag, then `_ctrlbar.init_from_config`. Good ordering comments.
 - Restores dock/splitter sizes with legacy padding/trimming; deferred at 100/300 ms. Good.
 - Restores active tab label; playlist loading via `ConfigPlaylistLoader` with `all_done` wired to `_close_splash` **before** `start()`. Good.
 - `except Exception` prints and still rebuilds/close splash. Acceptable, but a corrupt config silently loses everything; consider backing up the bad file.
- `_on_config_playlist_ready` / `_on_config_playlists_done` / `_restore_queue` (2408–2476): incremental page add, view settings, column widths; final rebuild, queue restore (resolver first, else read tags, drop missing), tab restore. Good.
- `keyPressEvent` (2479–2492): space/arrows/brackets/media keys/Ctrl+F. Note Left/Right always seek ±5 s; held key repeats. Fine.
- `closeEvent` (2494–2505): removes hidden playlist, saves config, `player.shutdown()`, then close. Good.

### 4.10 `views.py` (1947 lines)

**Purpose:** SeekSlider, TouchDrag, DoubleTapTracker, LongPressFilter, TrackTable, GalleryView, PlaylistPage.

- `tracks_mime_data` (27–36): custom MIME + `text/uri-list` for external drops. Good.
- `is_touch_pointer` (39–51): checks `pointingDevice().type()`. Correct way to distinguish synthesised mouse from finger.
- `TouchDrag` (54–245): hand-rolled touch drag because `QDrag` follows the mouse pointer. Reads gestures from an app-wide filter; posts hand-built drag/drop events to the widget under the finger; watchdog. Thorough design and documentation.
 - **MEDIUM (performance):** every `TouchDrag` installs an app-wide filter and returns `isinstance(obj, QWidget)` for touch events, swallowing them for widgets. Only one drag at a time, so fine, but the filter stays installed until `finish()`; `_close` + `deleteLater` removes it in `finish`. Good.
 - `_send` constructs `QDragEnterEvent/QDragMoveEvent/QDropEvent` and calls `QApplication.sendEvent`; acceptable, though these constructors are Qt-version sensitive. **LOW.**
- `SeekSlider` (248–353): click-to-jump, drag, touch events; `update_accent`/`update_radius`. Good. `event()` handles touch directly and returns True, bypassing QSlider; correct for the seek use case.
- `DoubleTapTracker` (357–420): pairs taps with a wide window and drift limit; `pending()` lets a long-press timer be suppressed for the second tap. Good.
- `LongPressFilter` (423–599): mouse long-press → context menu; touch: tap-tap→play, flick→scroll (QScroller), hold→lift, hold+move→drag, hold+release→menu. Complex but well documented. `_on_lift` checks QScroller state to avoid fighting a flick. Good.
- `_TouchHeaderView` (603–663): widened column-resize grab zone (±14 px). Correct remap of press/move/release.
- `_CoverTitleDelegate` (666–734): draws cover + title directly, bypassing QIcon (avoids KDE style effects). `paint` calls `initStyleOption`, draws the panel primitive for selection/hover, then the cover via `_draw_cover_rounded`, then elided title. Good.
 - **NIT:** `sizeHint` returns `QSize(200, self._table._row_h)` — fine.
- `TrackTable` (737–1045):
 - Setup: touch header, row selection, no edit, per-pixel scroll, drag-only, custom context menu, interactive sections, scroller + long-press filter, manual sort, `_fp_to_row` index, async cover loader hookup. Good.
 - `activate_row` (822–836): debounces duplicate activation from `doubleClicked`, the viewport filter and tap pairing. Good.
 - `eventFilter` (838–848): catches viewport `MouseButtonDblClick` because QScroller can swallow `doubleClicked`. Good.
 - `startDrag` (850–857) skips when a touch gesture is active. Good.
 - `mimeData` (859–873): filepaths from Title cells, de-duplicated in visual order. Good.
 - `_apply_ratios` (902–920): disconnects `sectionResized` while applying to avoid feedback; last column absorbs rounding. Good.
 - `populate` / `_populate_deferred` (948–973): first 200 rows sync then 200 per event-loop tick. Good for big libraries.
 - `_on_header_clicked` (975–1005): sorts `page.tracks`, preserves the playing filepath, calls `page.set_tracks(...)`. **MEDIUM:** calling `set_tracks` from inside a header click re-populates the table (and gallery) synchronously — on a 20k-row library that is a visible freeze; `populate` already chunks the *filling* but `setRowCount(0)/setRowCount(n)` and the sort itself are O(n). Acceptable but worth a note.
 - `_fill_row` (1007–1015): builds a `QTableWidgetItem` per cell. For 20k rows × 7 columns this is the dominant cost; a model/view would be far faster. **LOW/MEDIUM (scalability).**
 - `set_covers_on(self, on, tracks)` (1017–1020): the `tracks` argument is unused — signature smells (**NIT**).
 - `set_playing_row` (1022–1037): sets explicit `ForegroundRole` and bold on the two affected rows. Correct for the transition, but see §4.9.3 for the theme-refresh leak.
 - `filter` (1038–1044): hides rows by `search_key`. O(n) per keystroke; `search_key` is cached per Track. Good.
- `GalleryView` (1048–1851):
 - Virtual canvas, single `paintEvent`, `_vis_idx` filter, snapped cover size, boustrophedon option, hover/playing borders, text block layout with optional artist/album/format lines, optional spinner overlay. Well implemented.
 - `_recompute_layout` (1248–1282): column count from nominal 2:1 width, cards stretch, cover size snapped to 8 px. Good.
 - `_canvas_paint` (1366–1539): computes visible rows from the clip rect, caches strings per track, elides text, draws covers with rounded clip, redraws the border over the cover. Good. `_scale_spinner_on` schedules `update` every 16 ms while scaling — fine.
 - `eventFilter` (1553–1599) touch gesture set mirrors the table. `_end_touch_gesture` resolves from whichever end signal arrives first. Good.
 - Mouse handlers (1650–1757): press/release/double-click/move/leave, long-press, `_start_card_drag` with QDrag for mouse. Good.
 - `_on_cover_loaded` (1766–1777): lazily builds `filepath → [visual positions]`; a track appearing twice gets both cards repainted. Good.
 - `_on_sort` (1806–1842): sorts `self._tracks`, recomputes playing index, rebuilds layout, then **reaches up** to `page.table.populate(...)`. Works but couples gallery→page→table (**NIT**).
 - `_canvas_*` handlers are assigned as instance attributes (`self._canvas.paintEvent = self._canvas_paint`, 1136–1141) — a monkey-patch idiom; works in PyQt but breaks static analysis and any C++-side call that expects the real virtual. **NIT/LOW.**
- `PlaylistPage` (1855–1944): stack of table+gallery; forwards signals; `set_tracks`, `set_playing`, `set_covers_on`, `apply_filter`, `set_view_mode`, `set_list_scale`, `set_gallery_scale`, `refresh_theme`, `set_label`. `set_list_scale` sets row heights in a Python loop over every row — O(n) per slider tick (**MEDIUM**, the slider is debounced? — `set_list_scale` is called from `SettingsPopup` via `MainWindow._on_list_scale_changed` immediately; no debounce here, so dragging the slider is O(n) per step). Fix: `verticalHeader().setDefaultSectionSize()` alone plus a `viewport().update()`, and only set existing row heights if a mixed-height state exists.

### 4.11 `controlbar.py` (1917 lines)

**Purpose:** seek bar, transport, cover, popups, viz painting.

- Construction (39–264): pre-allocated viz/ring/pixel buffers, responsive breakpoints, popups lazy, seek + transport + right buttons, signals, idle timer, fixed-rate render timer. Very thorough.
 - 43 `WA_OpaquePaintEvent` — right for a fully painted bar.
 - 74–84 delay ring buffer of 200 slots (3.3 s at 60 fps) — sized above the 3 s max delay; good.
- Popup creation (267–389): EQ popup wires player setters directly and also emits `settings_changed`; settings popup wires a large set of signals, many via `getattr(self, '_blackout_ref', None) and ...` lambdas. Good but fragile (**NIT**).
- `_refresh_audio_info` (391–456): builds Format/DSP/Device strings. **HIGH (blocking)** because it calls `_player._resolve_rate_plan()` (448), which shells out. It is called on every track change while Settings is open **and** from `_on_pos` every 3 s while open (1856–1864). See §3.4.
- `lyrics_fetch_enabled` / `cover_on` (458–466).
- Overlay idle/auto-open (468–535): timer start/reset, `set_overlay_open` stops/starts rendering when the overlay covers the bar. Good.
- Fetch-button handlers (537–625): reuse an existing worker popup if one is running (good), otherwise create and `_ModalOverlay.show_for(dlg, watch_hide=True)`. Repeated shape across four handlers → could be one helper (**NIT**).
- `_on_rename_btn` (627–718): on finish rewrites M3U8 lines, known_paths, live player/ctrlbar/track paths, saves config, clears cover cache, rescans. Good — this is the “rename propagates everywhere” logic and it is careful.
 - **LOW:** it rewrites only playlist files with `_m3u_path`; library paths and the queue are rescanned/rebuilt, so fine.
- `_toggle_fullscreen` / `_toggle_settings` (720–742): settings toggle debounced with `_hide_timestamp_ms`. Good.
- `_coerce_bands` (744–763): normalises legacy 3-tuples to 4. Good.
- `init_from_config` (765–952):
 - Coerces numbers from JSON (strings tolerated). Good.
 - `viz_gamma` guarded against bad values. Good.
 - Applies theme after radius (so the first stylesheet is correct). Good.
 - Restores output device: probes ALSA list, falls back to PipeWire if the saved device is gone; sets `_pipeline_dev` to `hw:` from `plughw:`. Good.
 - Restores adaptive-rate toggle silently and re-syncs the drop-in file only if already opted in. Good.
 - Restores loudness norm, crossfade/fade, sleep timer (deliberately **not** restored — good), EQ profiles/default bands, limiter/stereo/balance/preamp by **writing `_player._*` directly** (942–952) instead of calling the setters. This bypasses `_apply_preamp`/`_apply_eq…` (fine at startup, no pipeline yet) but is fragile if init ever runs with a live pipeline. **LOW.**
 - **MEDIUM:** `if acc_color != '#e03030': self._on_accent_change(acc_color)` (794) hard-codes the default accent string; if the built-in default changes, the comparison silently breaks (accent applied or skipped incorrectly). Compare against `ACC`/`_USER_ACC`.
- `config_state` (961–1000): mirrors init. Consistent.
- `_precompute_bars` (1002–1120): vectorised bar x0, column→bar map, cap offsets, freq→bin tables (log/linear), line-mode scratch and interpolation tables. Excellent — the comments explain each vectorisation.
- `_interp_line_y` / `_blend_rows` (1122–1160): `np.take(out=)`, float32 scratch, uint32 blend with wraparound for negative deltas. Correct and fast.
- Render timer start/stop (1162–1176): disables/enables GC. Symmetric; see §4.1 for the caveat.
- `_on_viz_toggle` / `_on_log_toggle` / `_on_delay_change` / `_overlay_cb` / `_on_inertia_change` (1178–1220): reset queues/tables appropriately. Good.
- `_on_brightness_change` (1222–1250): accent-derived bar tint; dark vs effective-light ramps. Good.
- `_on_viz_type_change` / `_on_radius_change` / `_radius_apply` (1252–1330): radius changes broadcast `RAD_PCT`, debounce stylesheet rebuild, overlay during drag, re-style inline widgets, re-precompute caps. Thorough. Note the `global RAD_PCT` issue (§3.1).
- `_on_accent_change` (1332–1358): early-returns in SYS mode; clears cover/LUT caches; deletes placeholder-cover files; re-styles transport; emits `accent_changed`. Good.
- Cover toggles (1359–1377): set/clear accent mode, clear LUT caches. Good.
- `_on_seek_flush` (1379–1394): clears viz + delay ring + display buffer so pre-seek frames never replay. Good.
- `set_focus_paused` (1396–1408): pauses viz/spectrum when unfocused; keeps overlay spectrum if needed. Good.
- `_render_tick` (1410–1487): needs-render gate, drain-after-stop support, 0.85×frame guard, delay ring lookup by timestamp (`argmax` over masked timestamps — efficient), overlay callback, integer-height change detection to skip repaints. Excellent.
 - **NIT:** the delay lookup scans `ts[:count]` (up to 200) per frame; negligible.
- `resizeEvent` (1490–1514): shrinks margins/buttons by height/width breakpoints; invalidates cached frame; debounced `_precompute_bars`. Good.
- `_apply_now_playing_text` (1516–1526): elides against current max widths. Good.
- `paintEvent` (1528–1783): four viz modes (fill/line/line+fill/bars) over a uint32 numpy buffer with a single `drawImage`; caps drawn as a flattened index grid; colour caches; fallback fill when paused. Very well optimised and documented.
 - **LOW:** `paintEvent` reads globals (`BG`, `BORD`, `ACC`, `RAD_PCT`) that `_broadcast_palette` rewrites — fine, but it means painting depends on cross-module mutation (§3.1).
- `_on_playing_changed` / `_finish_viz_stop` (1785–1830): delay-drain then park bars; pushes a zero frame to an open overlay. Good.
- Seek handlers (1832–1866): press/release/move/pos/duration; `_on_pos` updates widgets only on change and refreshes audio info every 3 s while Settings is open (**HIGH** via `_refresh_audio_info`, §3.4).
- `refresh_theme` / `set_track` / `set_play_icon` / `set_play_busy` (1868–1917): good; `set_track` resets seek, viz, delay ring and cover.

### 4.12 `controlbar_widgets.py` (425 lines)

- `_ctrl` (15–18): 44×44 checkable button factory. Good.
- `RepeatButton` (20–56): painted arc + arrow, index cycles NONE→ALL→ONE, `1` badge for ONE. `set_mode` uses `.index` (raises if an unknown mode is passed — callers pass RepeatMode). Good.
- `_FullscreenBtn` (61–103): corner arrows flip direction by state. Good.
- `SpinningPlayButton` (105–258): hand-painted circle/glyph (documented reasons: QSS content-box sizing and per-frame resize). Busy spinner + pulse animation. Good.
 - **NIT:** `_paint_icon` uses `self._is_playing` which flips immediately on `set_playing_icon`, while the circle animates via `_pulse`; glyph and diameter switch at slightly different times. Cosmetic.
- `_RoundedCoverLabel` (260–425): rounded clip; accent-recolour path with its own LUT (`_acc_lut_cache`), stride-correct numpy, cached per (fp, hue, sat, size, dark). Good.
 - **MEDIUM (duplication/bug risk):** `_build_accent_pixmap` re-implements `_recolor_pixmap` (LUT build included) instead of calling it. Two copies of the same maths can drift. Reuse `cover_art._recolor_pixmap` and then scale/cache.
 - **LOW:** `QImage(out.tobytes(), ...)` then `QPixmap.fromImage` — `fromImage` copies, so this is safe (unlike `_recolor_pixmap`, which needs the `.copy()`); consistent.

### 4.13 `eq.py` (1337 lines)

**Purpose:** EQ UI (cells, popup, graph).

- `EQSliderCell` (13–139): log freq / linear gain·Q mapping, label formatting, QSS per enabled state. Good.
- `TouchComboBox` (143–157): suppresses a popup close within 400 ms of opening (touch double-fire). Good.
- `EqPopup` (162–987):
 - Window flags: Tool + frameless + on-top so it survives focus loss. App-wide event filter closes on outside click, suppressed during file dialogs. Good.
 - 300 ms debounce before `_apply`. Good.
 - Profile combo: editable, `＋ New` sentinel, `activated` only on explicit pick. Good.
 - Bands table rebuilt on every refresh (`_refresh_table` creates new `EQSliderCell` + `TouchComboBox` per row) — **LOW** churn but correct.
 - `_apply` also syncs the active profile snapshot, so band edits persist without Save. Good.
 - JSON import/export with PowerAmp/Wavelet/AutoEQ type mapping (`_JSON_TO_VOIDPULSE_TYPE` / inverse), clamping, multi-preset picker, preamp apply, truncation/skip reporting. Thorough.
 - `set_bands` / `set_profiles` / `set_default` / getters: consistent; `set_profiles` normalises legacy bare lists.
 - Limiter/stereo/balance/preamp/loudness setters block signals for restore. Good.
 - `show_center` / `show_above` clamp to the primary screen only (**LOW**: multi-monitor).
- `_smooth_viz_corners` (989–1024): 3-tap neighbour blend into caller-provided buffers; benchmark note. Correct.
- `_np_to_qpolygonf` (1027–1034): interleaves into float64 then builds `QPointF` list — still boxes each point, but fewer Python ops. Fine.
- `_fmt_ms` (1037–1039).
- `EQGraph` (1042–1337):
 - Reference `fs = 44100` for display (independent of track rate) — deliberate, documented by the constant.
 - Cache keyed on `(width, bands)`; vectorised complex response per band; total sum; auto-scale to even dB, capped at `EQ_GAIN_MAX_GRAPH`; grid step 1 or 2 dB; labels backed by filled rects. Good.
 - Per-band dashed curves + total curve + hover crosshair/tooltip. Good.
 - **LOW:** `cache_key = (w, tuple(tuple(b) for b in self._bands))` — rebuilding the tuple each paint is O(bands) (10), fine.
 - **LOW:** band colours use hue by index; export uses the same formula — consistent.

### 4.14 `settings_popup.py` (833 lines)

- Layout: two columns (Overlay/View/Audio info + Adaptive; Visualization/Fetch/Playback/Volume/Output). Documented spacing compromises. Good.
- Signals for every setting; fetch buttons emit actions. Good.
- `_on_theme_toggle` / `_on_system_theme_toggle` (553–584): `apply_theme`/`apply_system_qt_theme` then overlay + `_refresh_all_theme_widgets`; disables DARK/LIGHT and accent in SYS mode with a tooltip. Good.
- `_on_cover_tri_changed` (586–611): 0/1/2 → cover/accent; calls `ctrlbar._on_cover_toggle(..., _emit=False)` then `MainWindow._on_cover_toggle_with_overlay` to avoid double updates. Good.
- `_pick_accent` (613–631): hides the popup, opens `QColorDialog` with `DontUseNativeDialog` (consistent theming), re-styles the swatch, emits. Good.
- Accessors/setters (647–743): comprehensive and consistently use `blockSignals` for restore. Good.
- `refresh_theme` (759–777): re-applies dividers, section labels, combos, accent swatch. Good.
- `eventFilter` (779–802): closes on outside press; skips if a combo dropdown just opened (checks `_popup_opened_ms` within 600 ms). Calls `findChildren(QComboBox)` on every press (**MEDIUM** per §3.5).
- `show_above` (804–831): reparents to the window, clears any height cap, positions above/below with clamping, caps height to available space. Good.

### 4.15 `widgets_base.py` (852 lines)

Reviewed portions: `ToggleSwitch`/`TriSwitch` painting, `JumpSlider`, `SliderRow`, `DeviceBusyPopup`, `_ModalOverlay`, `_SpinningOverlay`.

- `ToggleSwitch`/`TriSwitch`: custom-painted toggles with accent-driven fill, zone dividers, labels, `_r()` radius. Good.
- `JumpSlider` (375–423): click-to-jump, ignores wheel (prevents scroll-over changes), touch handling, `ClickFocus`. Good; the wheel-ignore is a deliberate and correct choice for a settings panel.
- `SliderRow` (425–473): label (wrapping at 70 px), slider, value label; `snap` rounds to `step` and re-enters once to display the snapped value. Correct.
- `DeviceBusyPopup` (477–648): themed popup, auto-dismiss 10 s, Retry/Switch/Dismiss. `refresh_theme` re-applies child QSS. Good.
- `_ModalOverlay` (653–759): dark scrim, follows parent resize, dismisses popup on outside click, watches `finished` for dialogs and `Hide` for non-blocking ones, removes all filters on done. Handles the Wayland “child dialog becomes top-level” case via `QApplication.activeWindow()`. Very good.
 - **NIT:** `show_for` centres using `mapToGlobal` of the window and `popup.move`; on a popup parented to the window this is correct; on one parented deeper it could be off. Callers pass window-parented popups.
- `_SpinningOverlay` (766–852): splash (`as_splash`, standalone top-level) and runtime overlay (child of a window, follows resize/move/show/state). Spinner + title. Good.

### 4.16 `sidebar.py` (458 lines)

- `_PlaylistRowWidget` (9–107): label + delete button; long-press on the label only (not the button) fires the context menu; short tap selects. `update_accent`/`refresh_theme` re-apply colours. Good.
- `Sidebar` (109–458): logo/version/search/divider/library button/playlist scroll/actions. `WA_StyledBackground` for the styled QWidget — correct catch.
 - `_apply_action_btn_height` / `_on_action_btns_resize` (237–273): thins action buttons as the sidebar shrinks (global QPushButton min-height is restated in QSS, as documented). Good.
 - `add_playlist` captures `idx = len(self._pl_rows)` in lambdas (275–282); `_rewire_all_rows` (363–374) rebuilds them after a move/remove. Good.
 - `_show_pl_context_menu` / `_prompt_rename` / `rename_row` / `move_playlist_row` / `remove_playlist` (284–382): consistent index bookkeeping. Good.
 - `_on_select` (384–389): indexes `self._pl_rows[idx]` **without bounds check** — `select_source` is used for restore, but `_on_select` is only connected with valid indices. Still, a defensive `if not (0 <= idx < len(...))` would be cheap. **LOW.**
 - `update_accent` / `refresh_theme` (411–445): re-applies all inline styles; clears the height guard so `_r()` changes rebuild. Good.

### 4.17 `queue_panel.py` (494 lines)

- `_paths_from_mime` (27–37): custom MIME or `text/uri-list` filtered by extension and existence. Good.
- `_QueueList` (40–201): drag-reorder + external drops; touch tap-pair activation; long-press context menu; `startDrag` skipped for touch. `dropEvent` for internal moves defers to Qt then emits `reordered`; external drops compute insert row (below midpoint = after). Good.
- `QueuePanel` (204–494): header (count/clear), list, hint; panel-level drops append.
 - `add_tracks` allows duplicates (documented), clamps insert index. Good.
 - `take_row` / `pop_next` / `remove_row` / `move_row` / `clear_queue`: consistent; `_rebuild` blocks signals. Good.
 - `_on_reordered` (356–379): rebuilds from visual order via filepath buckets (handles duplicates); if counts mismatch it rebuilds from the model rather than dropping entries. Careful.
 - `_on_paths_dropped` (381–390): resolver first, else `read_metadata` if the file exists. **MEDIUM:** `read_metadata` on the GUI thread for each dropped file — dropping a folder’s worth of tracks on a network share blocks. Consider a resolver-only path or a worker.
 - `refresh_theme` / `update_accent`: re-applies the list/header/menu QSS; `update_accent` just calls `refresh_theme`. Good.

### 4.18 `lyrics.py` (621 lines)

- `_lrc_parse` (21–44): handles multiple leading `[mm:ss.xx]` stamps, `mm:ss:cc` variant, sorts. Good.
- `_extract_embedded_lyrics` (47–85): MP3 SYLT/USLT (LRC inside USLT re-parsed), Vorbis `syncedlyrics`/`lyrics` (case variants). Good.
- Sources (89–211): LrcLib exact/search, Lyrics.ovh, ChartLyrics (plain HTTP — **LOW**: unencrypted, but it is a public lyrics API), Genius scrape, AZLyrics, SongLyrics, Letras. All wrapped, all length-guarded. Fragile by nature (HTML scraping) but contained.
- `LyricsFetcher` (227–358): embedded first, then fast phase (LrcLib×2, Lyrics.ovh) with an 8 s window short-circuiting on synced, then slow scrapers with a 14 s window and a 2 s grace for a synced result after a plain one. `was_online` drives tag embedding. Good design; the two-phase behaviour is documented.
 - **MEDIUM (lifetime):** the executors are shut down with `wait=False`; in-flight HTTP requests keep running after the future is cancelled (Python cannot cancel a running thread). Combined with `LyricsPanel._abort`’s 300 ms `wait`, several fetchers can overlap and keep sockets open for up to ~20 s after a track change. Not a correctness bug but a resource/lifetime smell; a single reusable pool plus a cancellation flag checked in each source would be cleaner.
- `LyricsPanel` (361–621): header/status, scroll area, one reused `QPropertyAnimation`, `set_track` bumps `_fetch_id`, `_abort`, deferred fetch while unfocused (`_pending_track` + `on_focus_gained`), `_done` discards stale ids, embeds online results in a daemon thread, builds synced (clickable lines, binary-search highlight, smooth scroll) or plain text.
 - `_abort` (488–498): `quit()` + `wait(300)` then drops references — see §3.3; the worker may still run and its QObject can be destroyed off-thread.
 - `_highlight` uses `bisect_right` over prebuilt timestamps — correct and fast.
 - **NIT:** `_done` uses `self._player._pipe.query_position` directly (private) and swallows exceptions. Works.

### 4.19 `dialogs_edit.py` (507 lines)

- `_CoverPreview` (11–74): full-dialog zoom, dimmed, dismiss on click/key, follows resize. Good.
- `_ClickableCoverLabel` (77–84).
- `TagEditDialog` (87–453):
 - Cover thumbnail + action grid (set from file / search online / remove / auto-fill tags / fetch lyrics / edit lyrics).
 - `changeEvent` closes the dialog on deactivation **except** when a child dialog is open (`_child_dialog_open` + `active.parent() is self`). Necessary on Wayland (modal overlay cannot take input over a top-level dialog) and well explained.
 - `_search_cover_online` / `_fetch_tags_online` / `_fetch_lyrics_online` (243–407): daemon thread + `QTimer` polling every 200 ms, guarded by `isVisible()`. Works, but polling is a smell; a `QThread`+signal or `QMetaObject.invokeMethod` would be cleaner (**NIT**). `_fetch_lyrics_online` queries 8 sources in parallel and waits for all, preferring synced — correct for an explicit user action.
 - `_fetch_lyrics_online` embeds via **another** daemon thread (393–397) — fire-and-forget, no error surfaced to the dialog. **LOW.**
 - `_remove_cover` / `_edit_lyrics` (409–446): direct writes; `_edit_lyrics` reports Saved/Save failed with a 2 s revert. Good.
 - `get_tags` / `get_cover_result` (448–453).
 - **MEDIUM:** file I/O for tag writes happens in `MainWindow._edit_tags` on the GUI thread after the dialog returns (see §4.9.5), not here; this dialog is fine.
- `LyricsEditDialog` (458–501): plain text editor, OK/Cancel, returns text. Good.

### 4.20 `fetch_popups.py` (772 lines)

- `_BaseFetchPopup` (26–414): shared dialog (title, Last.fm key row with live 32-char validation against the API, info, progress, log, result, Start/Cancel/Close + Force), background-worker adoption on reopen, status-bar permanent label per worker. Thorough.
 - `_test_lastfm_key` (169–202): polls a daemon thread; stores the key on success. Good. NIT: the test always queries “Radiohead – Creep”, so a valid key that lacks that track would be marked bad (Last.fm returns an error object for unknown tracks too). Minor false negative risk. **LOW.**
 - `_check_and_restore_background` (224–263): reconnects signals to the new instance, disconnects the old one. Good.
 - `_on_finished` (346–366): removes itself from `_active_workers`, nulls `_thread`/`_worker` **without** `deleteLater` in the worker thread. See §3.3. **MEDIUM.**
 - `_on_close`/`closeEvent` (318–334): running ⇒ hide, else close; removes the app filter. Good.
- `LibraryCoverFetchWorker` (420–460): skips locked/non-missing unless force; per-track network fetch with `stop` callback; emits raw bytes. Good. Runs sequentially in one QThread — correct.
- `CoverFetchPopup` (462–522): `_on_track_done` builds the master pixmap **on the GUI thread** (correct — QPixmap), writes disk+sidecar, caches 28/64, embeds in a **daemon thread per track** (508 → §3.3 unbounded threads), updates table icons + ctrlbar. Good behaviour, thread-per-track is the flaw.
- `LibraryTagFetchWorker` / `TagFetchPopup` (528–607): same shape; `_on_track_done` writes tags in a per-track daemon thread (606). **MEDIUM** for the same reason; also the write is fire-and-forget, so failures are only logged inside `write_tags_to_file`.
- `LibraryLyricsFetchWorker` / `LyricsFetchPopup` (615–696): tries 3 sources per track, embeds, reports ok. Embeds **on the worker thread** (665) — correct (no Qt objects). Good.
- `LibraryGainFetchWorker` / `GainFetchPopup` (706–772): `_run_rganalysis` per track, caches + writes tag on the worker thread. Good; the cache write (`_rg_gain_cache`) is a dict assignment — atomic enough.
- **MEDIUM (overall):** the four batch workers each own one QThread but the side-effect writes spawn unbounded threads; and none of them prune finished `QThread` objects reliably. Move the writes to `QThreadPool.globalInstance()`.

### 4.21 `cover_art.py` (732 lines)

- `Track` (15–67): dataclass with cached lowercase search haystack (`search_key`) invalidated by a signature of the four source fields. Clever and correct; excluded from `__eq__`/`__repr__`. `dur_str` / `sr_str` / `bd_str` / `sort_key`. Good.
- `_tag` / `_vtag` / `_parse_gain_db` (69–98): case-insensitive Vorbis lookup, list-or-scalar handling, numeric parse. Good.
- `read_metadata` (101–158): per-format tag keys (ID3, Vorbis, MP4 freeform), ReplayGain parse, broad `except` returning the filename-based Track. Good fallback, no logging (§3.2).
- Caches (161–181): `_cover_cache` LRU-ordered OrderedDict with a sentinel for cached-None; `_trim_cover_cache` drops oldest. Good.
- `_purge_orphan_disk_covers` (183–204): deletes legacy per-size files at startup. Good.
- `extract_cover_bytes` (206–229): per-format extraction. Good.
- `_square_pixmap` / `_draw_cover_rounded` (231–268): centre-crop with the float-truncation guard; clip-path rounded draw. Good.
- Default cover (271–331): disk-cached PNG master per (accent, background), memory cache for derived sizes. Good.
- `_cover_disk_key` / `_cover_disk_is_stale` / `_cover_disk_write_mtime` (344–389): sha1(path) suffix + sanitized stem, `.mtime` sidecar for staleness. Good.
- Recolour (392–491): `_acc_lut_cache` per (hue, sat, dark); `_recolor_cache` memo keyed on (fp,size,hue,sat,dark) with the source `cacheKey()` re-checked (prevents Qt cache-key recycling bugs) — excellent attention to detail. Stride-correct numpy; `.copy()` before `QPixmap.fromImage` (documented aliasing bug). Good.
- `get_cover_pixmap` (493–533): exact hit → master downscale → best larger downscale → async request. Correct.
- `_CoverTask` (535–587): **worker thread** — checks the in-memory master under `_cover_cache` (unsynchronised read of an OrderedDict being mutated on the GUI thread), reads the disk master, else extracts embedded bytes and encodes JPEG. Posts bytes/QImage to the main thread. The `_cover_cache` membership check here is the concrete data race in §3.3.
- `AsyncCoverLoader` (589–718): signals `cover_loaded`, `_master_ready`, `_raw_ready`, `_derive_ready`; `_lock` guards `_in_flight`/`_no_embed` only; all `QPixmap` construction happens in the queued main-thread slots. Good design apart from the cache race.
- `_ensure_async_cover_loader` (723–727): singleton. Good.

### 4.22 `library.py` (654 lines)

- `_build_new_filename` (20–70): `%F/%A/%T/%C` substitution with separator-collapse for missing tags. Well-reasoned and tested by inspection for the documented cases.
- `_validate_rename_pattern` (73–86): flags unknown `%X` and empty patterns. Good.
- `_recover_rename_temps` (92–120): restores `.__vprename_tmp__` files unless the target exists. Good.
- `LibraryRenameWorker` (123–235):
 - 255-byte filename limit with UTF-8 boundary backoff; `_(n)` de-duplication; two-step temp rename; cover disk+memory key migration.
 - **MEDIUM (thread safety):** iterates and mutates `_cover_cache` (`_fp_to_sizes`, pop/insert) from a `QThread` while the GUI thread reads it. See §3.3. Also `_cover_cache` is an OrderedDict; concurrent mutation during GUI `move_to_end`/`pop` can raise `RuntimeError: OrderedDict mutated during iteration` in the GUI thread’s `_trim_cover_cache` or the `for (cached_fp, cached_sz), … in _cover_cache.items()` loop in `get_cover_pixmap` (521). **This is a real crash risk during a rename.**
 - NIT: `_MAX_FILENAME_BYTES = 255` uses bytes; ext counted; good.
 - NIT: error path emits `(filepath, str(exc), False)` — the second field is documented as `new_path`; overloaded semantics but the popup prints it as the failure reason. OK.
- `RenamePopup` (238–568): pattern validation/preview, log, background-run adoption, status-bar label, `rename_map`. The event filter closes on outside click (`_on_close`), removes the filter when hidden while running. Good. `_on_finished` calls `_post_finish_cb`. Good.
 - **MEDIUM:** `_active_worker` hand-off mirrors `_BaseFetchPopup`; same worker-lifetime caveat.
- `scan_folder` (572–585) / `parse_m3u` (587–604): 4-worker `ThreadPoolExecutor` reading metadata, sorted by `sort_key`. Good. `parse_m3u` accepts absolute/relative paths, filters by extension and existence. `#EXTINF` lines are ignored (fine). Good.
- `ScanThread` (609–624) / `ConfigPlaylistLoader` (627–653): QThread wrappers; `ConfigPlaylistLoader` emits per-playlist and `all_done`. Good.

### 4.23 `metadata_online.py` (386 lines)

- Cover fetchers (12–74): iTunes (100→600 px), Deezer, MusicBrainz+CoverArtArchive, Last.fm (reversed images, skips `noimage`). All >1000-byte sanity check. Good.
- `fetch_cover_online` (76–92): ordered fallbacks with a `stop` callback. Good.
- `lookup_tags_online` (193–220): iTunes → MusicBrainz → Last.fm, merge missing fields, short-circuit when complete. Good.
- `write_tags_to_file` / `write_replaygain_gain_tag` / `embed_cover_bytes` / `embed_lyrics` (222–385): per-format writers, EBML pre-check, `add_tags()` when None, save. Correct. **LOW:** all of these run on caller threads; the batch popups call them from per-track daemon threads (§4.20).
 - `write_tags_to_file` for Vorbis deletes only uppercase `TITLE/ARTIST/ALBUM` then writes lowercase — a mixed-case existing key (`Title`) can survive and mutagen may return the stale one first. **LOW.**
 - `embed_lyrics` writes `LYRICS` for Vorbis; many players read `UNSYNCEDLYRICS`/`LYRICS`. Acceptable.

### 4.24 `mpris.py` (290 lines)

- XML interface definitions (10–52): standard `org.mpris.MediaPlayer2(.Player)`.
- `_setup` (81–104): registers objects (with closures if available), owns `org.mpris.MediaPlayer2.voidpulse`. Good. Errors are printed and swallowed — MPRIS is optional.
- `_handle_method` (107–109): returns immediately and dispatches on the Qt thread via `QTimer.singleShot` — correct, because the GLib thread must not touch widgets.
- `_dispatch` (111–133): transport commands skip while `_pipeline_busy`; `Play`/`Pause` use `ui_playing`; `Stop` fades; `Seek`/`SetPosition` convert µs→ms. Good.
 - **LOW:** `SetPosition` ignores the `TrackId` argument (seeks unconditionally). Standard clients send the current track id; a stale id would still seek. Acceptable.
- `_handle_get` / `_pp` (135–168): properties; `PlaybackStatus` maps Stopped when no pipe. `CanGoNext/CanGoPrevious` always True even at playlist ends — **LOW** (clients may show enabled controls that do nothing).
- `_meta` (170–185): trackid, title, artist list, album, length µs, url, artUrl. Good.
- Art temp files (187–236): md5-named file in tempdir, old file deleted when the path changes, `_build_art_uri` called on the Qt thread. Good. **LOW:** tempdir may be shared; predictable name based on content hash is fine (content-addressed), but a symlink attack on a world-writable `/tmp` is conceivable; use a private subdir with 0700.
- `_handle_set` (238–253): Volume/Shuffle/LoopStatus applied on the Qt thread. Good.
- `notify_track` / `notify_status` / `notify_seeked` / `_emit` / `_emit_seeked` (255–288): emit `PropertiesChanged`/`Seeked` via `GLib.idle_add`. Good.

### 4.25 `remote.py` (530 lines)

- `PROTOCOLS` / `build_uri` / `describe` / `default_label` / `share_local_path` / `is_mounted` (23–107): correct URI assembly (username deliberately excluded), two-route FUSE path resolution. Good.
- `_first_audio_file` / `probe_seekable` (110–155): bounded walk, one open+seek test. Good.
- `SeekProbe` (158–170): QThread wrapper.
- `RemoteMounter` (173–304): GVfs mount with password/question callbacks; password → keyring (`PasswordSave.PERMANENTLY`); retry bound; FUSE path polling; unmount best-effort.
 - **HIGH (security):** `_on_ask_question` (241–245) answers **choice 0** for every question. For SFTP that is the unknown-host-key confirmation, i.e. it accepts any host key silently → MITM. Store/verify host keys (GVfs persists known hosts under `~/.local/share/gvfs-metadata`), or at least surface the question to the user. This is the second-most serious finding after the updater.
 - **LOW:** `_on_ask_password` increments `attempts` on every ask including the first; with `_MAX_PASSWORD_ATTEMPTS=2` the user effectively gets two tries. Fine.
 - **LOW:** `already mounted` fallback by string match. Fine.
- `NetworkShareDialog` (310–528): saved list with connected marker, new-share form, protocol-dependent field enabling, port validator, anonymous handling, note text. Good UX. Password field is `QLineEdit.Password`. Good.

### 4.26 `blackout_overlay.py` (432 lines)

- Frameless top-level, blank cursor, `BypassWindowManagerHint`; child container with `QGraphicsOpacityEffect` + animation; clock/cycle timers; randomised reposition each cycle; fade in/out. Good OLED-burn-in design.
- Setters (70–121): track/pos/viz/lyrics/clock/scale; `push_viz_frame` keeps the ndarray **by reference** (documented; the producer reuses it, so the overlay sees the newest frame — acceptable because it repaints on the next push).
- Dismiss (124–147): mouse/key/touch consume and hide; notifies ctrlbar. Good.
- `show_blackout` / `_reposition` / fade cycle (150–195): fullscreen, stop idle timer, tell ctrlbar the overlay is open, enable overlay spectrum if viz is on. Good.
- `_resize_container` / `resizeEvent` (198–210).
- `_paint_info` (219–411): clock, title, artist, optional lyrics trio, progress bar with times, optional viz in the controlbar’s current style (bars/fill/line/line+fill) with corner smoothing and clipping. Well done; colour cache keyed on `(ACC, BG3)`.
 - **LOW:** bars loop is a Python `for norm in vd` with `float(norm)` per bar (256 iterations) each repaint — fine at 60 fps for 256 bars, but a vectorised rect path would be cheaper. Also `cx_list`/`cy_list` Python lists in fill mode. Acceptable.
 - **NIT:** `_ov_colors` caches `a55/a70/a90/a200/a220` but `a200` is used for bars and `a220` for lines; clear.
- `showEvent` / `eventFilter` (413–430): installs the container filter once; paints the container from the filter and consumes touch. Good (avoids subclassing the inner container).

### 4.27 `titlebar.py` (128 lines)

- `TitleBarButton` / `TitleBarCloseButton` (20–47): minimal window controls, hover/press colours, fixed 46×32.
- `BlackTitleBar` (49–128): logo/title/spacer/min/max/close; `startSystemMove()` on empty-area press (Wayland-correct), double-click toggles maximise; `refresh_theme` re-applies colours.
 - **LOW:** `_btn_max` glyph is set in `_toggle_max` and in `changeEvent` (main_window 1977–1979); two places. Consistent enough.
 - **NIT:** `refresh_theme` sets the title colour to `FG2` while the constructor used `_TB_FG` (`#666666`) — a subtle inconsistency (title colour differs before/after the first theme refresh). Align them.

### 4.28 `auto-update.py` (1426 lines) — **the security hot spot**

- State (`_load_state`/`_save_state`, 87–109): atomic temp+`os.replace`. Good.
- Package detection (115–248): Flatpak/AppImage/deb/rpm/apk/pacman detection via owner queries and distro guess; stored record validated against the live environment (stale AppImage path, dev checkout, flatpak↔non-flatpak) and re-detected. Good.
- Versioning (254–303): `_VER_RE`, `vtuple`, metainfo version, per-format installed version. Good; `vtuple` tolerates `v1.8.1`/`v.1.6.0`.
- Release query / newest / asset classification / matching / choices (309–396): correct, including excluding `appimagetool`.
- Download (`_Downloader`, 421–464): streams to `.part`, `os.replace`, cancel, unlink on failure. Good. **HIGH (security):** no checksum and no signature verification is performed after download.
- Desktop entry (470–568): rewrites/creates `.desktop`, refreshes the database, installs the SVG icon. Good.
- Install plan (574–663):
 - `native_tool`: **`dnf … --nogpgcheck`**, `zypper … --allow-unsigned-rpm`, `apt-get … --allow-unauthenticated`, `rpm -Uvh --force --nosignature`, `pacman -U` (no `--noconfirm`? it does add it), `apk add --allow-untrusted`. The docstring rationalises this as “the file was just downloaded from the project’s own release page and no repository signed it”. That is precisely the trust model a signature exists to fix: HTTPS protects transit, not a compromised release account/CDN, and the code itself ships `.asc` files (there are `VoidPulse-2.0.0-*.AppImage.asc` in this very tree). **CRITICAL.** Verify the detached signature (gpgv/minisign) or a published SHA-256 before installing; refuse on mismatch.
 - `install_plan` returns `sudo` based on `os.geteuid()!=0`. Good.
- `_sudo_wrap` / `swap_appimage` / `_Installer` (671–795): `sudo -S -p ''` with the password on stdin; AppImage swap chmods and unlinks the old file (safe because it is mounted). `_stream` merges stdout/stderr and keeps the last 14 lines. Good engineering.
 - **MEDIUM (security):** the GUI collects the sudo password and pipes it to `sudo -S`; it is never written to disk, but it lives in a Python string and in `_Installer._pw`. Acceptable for a desktop app; note that any process able to read the app’s memory gets it. Mention only.
 - **LOW:** `install_plan` prints `sudo` in the log line but strips `-S -p ''`; fine.
- `relaunch` (798–811): starts the new binary detached and quits. Good.
- `UpdatePopup` (824–1304): changelog vs format-choice body, live log, sudo password row with retry-on-rejection, progress, skip-for-now/skip-version, restart. Thoughtful UX and good failure reporting.
- `_Checker` / `_show` / `check_on_startup` / `check_now` (1310–1395): background thread, version compare, skip list, env opt-outs (`VOIDPULSE_NO_UPDATE_CHECK`, `VOIDPULSE_UPDATE_FORCE`), 4 s start delay. Good.
- CLI harness (1401–1426): `--reset`, `--check`. Nice for debugging.

### 4.29 `.github/scripts/appimage_smoke_test.py` (56 lines)

- Runs the built AppImage headless and asserts it starts; used by the AppImage workflow. Reasonable smoke test. **LOW:** a smoke test that only checks startup does not catch packaging regressions in codecs/GStreamer plugins; consider asserting a GStreamer element set and a `--version` print.

---

## 5. Repository & packaging hygiene

Observations from the tree (not code defects, but they matter for a release):

1. **Build artefacts committed to the repo.** The root contains `VoidPulse-1.9.0-*.AppImage`, `VoidPulse-2.0.0-*.AppImage` (plus `.asc`), `voidpulse_1.9.0_*.deb`, `voidpulse_2.0.0_*.deb`, `voidpulse-*.rpm`, `appimagetool-x86_64.AppImage`, and a full `org.voidpulse.VoidPulse-repo/` OSTree repository (thousands of files). These bloat the repository and, per the `.asc` files present, prove signed artefacts exist — which makes §4.28’s `--nogpgcheck` inexcusable. Move artefacts to GitHub Releases (they are already published there) and `.gitignore` them.
2. **Caches committed:** `.ruff_cache/`, `.crush/` (SQLite db + WAL + logs), `.claude/settings.local.json`, `__pycache__/*.pyc`. Add to `.gitignore` and remove from the index.
3. **Two version schemes live side by side** (1.9.0 and 2.0.0 artefacts). Clean up.
4. **No `requirements.txt` / `pyproject.toml` / `setup.py`.** Dependencies (`PyQt6`, `mutagen`, `numpy`, `soxr`, `PyGObject`, GStreamer plugins) are implicit in the Flatpak manifest and CI workflows. A `pyproject.toml` with a `[project]` table and a `dependencies` list, plus a Ruff config, would let contributors install and lint reproducibly.
5. **No CI lint/test job.** The five release workflows build packages only. Add a job that runs `ruff check`, `python -m compileall`, and (once written) `pytest`.
6. **`voidpulse-launcher`** is a 2-line file; verify it is still referenced by the packaging; otherwise drop it.
7. **Licence present** (`LICENSE`) — good.
8. **`appdata.xml` + `.desktop` + `.svg` + `.yml` manifest** present and consistent with `APP_ID` — good.

---

## 6. Prioritised action plan

**P0 — security, ship-blocking**
1. `auto-update.py`: verify a detached signature (`.asc`, already published) or a published SHA-256 of the asset before handing it to any package manager; abort on mismatch. Remove `--nogpgcheck` / `--allow-untrusted` / `--allow-unauthenticated` / `--nosignature` / `--force` from `native_tool`.
2. `remote.py`: stop auto-answering `ask-question` with choice 0; at minimum refuse to auto-accept SFTP host keys and let GVfs prompt/persist them.

**P1 — correctness / crashes**
3. Guard every deferred pipeline action (`_load_and_seek`, `_reload_at_pos`, ALSA probe `_after_seek`, pipewire-restart reload) with a captured pipeline/serial identity.
4. Make `_cover_cache` thread-safe (one `RLock` around all access, or move mutation to the GUI thread); the rename worker must not mutate it from a QThread.
5. Fix the ALSA probe confirmation to be event-driven (ASYNC_DONE without error / clean bus), not a fixed 800 ms.
6. Make `config.json` writes atomic (temp + `os.replace`).
7. Add a `sys.excepthook` / `qInstallMessageHandler` so a slot exception logs and surfaces instead of aborting silently.

**P2 — responsiveness**
8. Move `alsa.acquire/release`, `probe_alsa_hw_rate`, and the PipeWire rate probes off the GUI thread; stop calling `_resolve_rate_plan()` from the 3 s audio-info refresh (cache the label).
9. Cache or persist `_detect_chain()`’s result to remove the worst-case 6 s of `wpctl` at startup.
10. Re-run a requested reload when `_reloading` clears (EQ/limiter/stereo toggles).
11. Debounce/cheapen `PlaylistPage.set_list_scale` (avoid the per-row loop).

**P3 — resource hygiene**
12. Replace per-track `threading.Thread` writes with a shared `QThreadPool`.
13. Give `LyricsPanel`/`RenamePopup`/`_BaseFetchPopup` proper worker lifetimes (`finished → deleteLater`, no premature nulling).
14. Prune `_scan_threads` and `_seek_probes`.
15. Disable the ghost pipeline’s spectrum element on crossfade detach.

**P4 — maintainability**
16. Extract the duplicated transport QSS; name the deferred-timing constants.
17. Migrate to `import constants as C`; retire `_broadcast_palette`.
18. Deduplicate the accent-recolour maths (`controlbar_widgets` vs `cover_art`).
19. Fix the `__open_with__` playlist desynchronising sidebar/tab indices.
20. Add `pyproject.toml`, Ruff config and a lint+compile CI job; add unit tests for `eq_filters`, `_build_new_filename`, `_lrc_parse`, `vtuple`, and the gate/fade state machine.
21. Remove build artefacts, caches and the OSTree repo from the Git index; extend `.gitignore`.

---

## 7. Static metrics

| Metric | Value |
|---|---|
| Python modules reviewed | 30 (plus 1 CI script) |
| Total Python LOC | ≈22,583 |
| Largest modules | player.py 2,686 · main_window.py 2,507 · views.py 1,947 · controlbar.py 1,917 · auto-update.py 1,426 |
| `except Exception` clauses | 161 |
| `daemon=True` thread creations | 17 (+ several QThread subclasses) |
| `QTimer.singleShot` call sites | 82 |
| App-wide event filters installed at steady state | ≥3 (`MainWindow`, `SettingsPopup`, `EqPopup`) |
| Automated tests | 0 |
| Signature verification in updater | 0 (despite `.asc` assets shipping) |

---

*End of review. The single most important change is P0 item 1: the updater currently defeats the signatures the project already publishes.*


