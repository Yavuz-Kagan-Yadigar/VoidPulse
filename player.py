"""
VoidPulse — audio engine: RepeatMode enum, _StereoWidthBin GStreamer bin,
Player (GStreamer pipeline, ALSA/PipeWire, EQ/DSP, spectrum visualisation,
position interpolation, seek, shuffle/repeat).

Biquad coefficient functions are in eq.py (imported by both Player and EqPopup).
"""
from constants import *
from cover_art import read_metadata
from constants import EQ_TYPE_HIGHSHELF, EQ_TYPE_LOWSHELF, GST_BANDS, MAX_EQ_BANDS, MIN_DB, VIZ_BANDS
import re as _re
import urllib.parse as _urlparse
from time import monotonic as _monotonic
import numpy as _np
from eq import (
    EQ_TYPE_PEAK, eq_band_coefficients,
)

class RepeatMode(enum.Enum):
    NONE = 0; ALL = 1; ONE = 2

class _StereoWidthBin(Gst.Bin):
    """A Gst.Bin that applies M/S stereo width processing to interleaved F32LE
    stereo audio using a GStreamer appsrc→appsink pipeline internally.

    Built as a Bin with ghost sink/src pads so it can be dropped into any
    pipeline chain in place of a regular element.
    """

    def __init__(self, width: int = 50):
        super().__init__()
        self._width = max(-100, min(100, width))

        # We need: audioconvert (to F32LE) → appsink (grab buffers) and
        # appsrc (push processed buffers) → audioconvert (back to original fmt)
        # But building a split pipeline inside a Bin is complex.
        #
        # Simpler: use a single identity element + GStreamer pad probe to
        # intercept every buffer, process it in Python, and write it back.
        self._identity = Gst.ElementFactory.make('identity', 'sw_identity')
        self._conv_in  = Gst.ElementFactory.make('audioconvert', 'sw_conv_in')
        self._conv_out = Gst.ElementFactory.make('audioconvert', 'sw_conv_out')

        if not self._identity or not self._conv_in or not self._conv_out:
            raise RuntimeError('_StereoWidthBin: required elements unavailable')

        for el in (self._conv_in, self._identity, self._conv_out):
            self.add(el)

        self._conv_in.link_filtered(
            self._identity,
            Gst.Caps.from_string('audio/x-raw,format=F32LE,channels=2,layout=interleaved'))
        self._identity.link(self._conv_out)

        # Ghost pads
        self.add_pad(Gst.GhostPad.new('sink', self._conv_in.get_static_pad('sink')))
        self.add_pad(Gst.GhostPad.new('src',  self._conv_out.get_static_pad('src')))

        # Attach buffer probe on identity src pad
        self._src_pad  = self._identity.get_static_pad('src')
        self._probe_id = self._src_pad.add_probe(Gst.PadProbeType.BUFFER, self._on_buffer)

    def set_width(self, width: int):
        self._width = max(-100, min(100, width))

    def _on_buffer(self, pad, info):
        buf = info.get_buffer()
        if buf is None:
            return Gst.PadProbeReturn.OK

        w = (self._width + 100) / 100.0   # -100→0(mono), 0→1(unity), +100→2(wide)
        a = float(0.5 * (1.0 + w))
        b = float(0.5 * (1.0 - w))

        # unity — skip processing entirely
        if abs(a - 1.0) < 1e-6 and abs(b) < 1e-6:
            return Gst.PadProbeReturn.OK

        # Read original samples
        result, rmap = buf.map(Gst.MapFlags.READ)
        if not result:
            return Gst.PadProbeReturn.OK
        try:
            arr = _np.frombuffer(bytes(rmap.data), dtype=_np.float32)
            if arr.size < 2 or arr.size % 2 != 0:
                return Gst.PadProbeReturn.OK
            stereo = arr.reshape(-1, 2)
            L = stereo[:, 0].copy()
            R = stereo[:, 1].copy()
            out = _np.empty_like(stereo)
            out[:, 0] = a * L + b * R
            out[:, 1] = b * L + a * R
            out_bytes = out.astype(_np.float32).tobytes()
        finally:
            buf.unmap(rmap)

        # Build a new writable buffer with processed audio.
        # Timing metadata is copied from the original buffer.
        # We remove the probe before pushing so pad.push() doesn't re-trigger
        # this callback (recursion), then re-add it immediately after.
        new_buf = Gst.Buffer.new_wrapped(out_bytes)
        if new_buf is None:
            return Gst.PadProbeReturn.OK
        new_buf.pts      = buf.pts
        new_buf.dts      = buf.dts
        new_buf.duration = buf.duration
        new_buf.offset   = buf.offset

        self._src_pad.remove_probe(self._probe_id)
        pad.push(new_buf)
        self._probe_id = self._src_pad.add_probe(Gst.PadProbeType.BUFFER, self._on_buffer)
        return Gst.PadProbeReturn.DROP


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
    sig_volume_changed = pyqtSignal(int)  # emitted when volume changes programmatically (0–100)
    _sig_drift_gst_ms = pyqtSignal(float, float)  # GLib thread → main thread: (gst_pos_ms, query_wall_t)
    _sig_dur_gst_ms   = pyqtSignal(int)           # GLib thread → main thread: confirmed duration (ms)

    _SPEC_INTERVAL_NS = int(1_000_000_000 / 30)  # 30fps spectrum — reduces GIL contention vs 60fps

    # (pre-spectrum chain, output sink)
    # 0=direct(bit-perfect) 1=audioconvert(format only, no rate) 2=+audioresample
    # Priority: PipeWire (native, bit-perfect) → PulseAudio → autoaudiosink
    # _sink_available() checks whether PipeWire actually has an audio node
    # via wpctl; falls back to pulsesink if not.
    # Bit-perfect: PipeWire (native) or ALSA direct (selected from combo).
    _CHAINS   = ['', 'audioconvert', 'audioconvert ! audioresample',
                 '', 'audioconvert', 'audioconvert ! audioresample']
    _OUTS     = ['pipewiresink', 'pipewiresink', 'pipewiresink',
                 'pulsesink',   'pulsesink',   'pulsesink']
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
        # ── Interpolated position tracking ────────────────────────────────────
        # Instead of asking GStreamer on every tick (which lags after seek/pause),
        # a wall-clock anchor is maintained: pos = _pos_anchor_ms + elapsed_since_anchor.
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
        self._viz_mag_buf = _np.full(GST_BANDS, MIN_DB, dtype=_np.float32)  # latest raw magnitude
        self._viz_bh_pre  = _np.empty(VIZ_BANDS, dtype=_np.float32)         # work buffer
        self._viz_tmp_pre = _np.empty(VIZ_BANDS, dtype=_np.float32)         # work buffer
        self._viz_bar_buf = _np.zeros(VIZ_BANDS, dtype=_np.float32)  # published bar heights (pre-alloc)
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
        # Real GStreamer position stall tracking — uses actual queried values, not interpolated.
        # _apply_drift_correction updates these; detects pipeline freeze in ~700 ms.
        self._gst_pos_adv_ms: float = -1.0   # last GST query that showed genuine forward movement
        self._gst_pos_adv_wt: float = -1.0   # wall-clock time of that query

        # EQ related
        self._eq_enabled = True
        self._eq_bands = []               # list of (freq, gain, Q)
        self._eq_filters = []              # list of Gst.Element for each band (size MAX_EQ_BANDS)
        self._current_fs = 48000           # default sample rate, will update from track
        # Limiter & stereo enhance
        self._limiter_enabled  = False
        self._stereo_enabled   = False
        self._stereo_width     = 0         # -100 to +100; 0=unity, mapped to M/S mix-matrix width factor
        self._stereo_el        = None      # audioconvert mix-matrix element ref (updated per load)
        # Preamp: dB gain applied before EQ filters (-24..+24 dB)
        self._preamp_db        = 0.0
        self._preamp_el        = None      # GStreamer volume element ref (updated per load)

        self._chain, self._out = self._detect_chain()
        print(f'[Player] chain: "{self._chain or "(none)"}" → {self._out}  (pre-config default)')
        # ALSA hw device override — 'pipewire' means use detected PipeWire sink (default).
        # Config restore in ControlBar._restore_config() will override this via _alsa_device directly.
        self._alsa_device: str = 'pipewire'
        # Saved position/state from set_output_device(); consumed by ALSA probe.
        # Initialized here so _on_player_error can always access them safely,
        # even when the error fires before any device switch (e.g. EQ toggle).
        self._last_switch_pos_ms:      Optional[int]  = None
        self._last_switch_was_playing: Optional[bool] = None
        # Set to self._pipe inside load() when paused=True; cleared on ASYNC_DONE.
        # Allows deferred pause after preroll without blocking the main thread.
        self._pending_pause_pipe = None

        self._has_spec = Gst.ElementFactory.find('spectrum') is not None
        print(f'[Player] spectrum: {"OK" if self._has_spec else "not found"}')

        self._pos_timer  = QTimer(self)
        self._pos_timer.setInterval(250)
        self._pos_timer.timeout.connect(self._tick_pos)
        # After seek/resume, fire more frequently for the first few ticks
        self._pos_timer_burst = 0   # countdown: ticks remaining at fast (100ms) rate

        # Bus poll timer: replaces add_signal_watch() + GLib main loop.
        # timed_pop_filtered(0) is non-blocking — returns immediately if no message
        # is waiting.  We only ask for the 5 message types _on_msg actually handles,
        # so QOS / STATE_CHANGED / TAG / STREAM_STATUS / LATENCY are never dequeued
        # and never cross the Python boundary at all.
        self._bus_timer = QTimer(self)
        self._bus_timer.setInterval(20)   # 50 Hz — fast enough for EOS/ERROR/ASYNC_DONE
        self._bus_timer.timeout.connect(self._poll_bus)
        self._bus_msg_mask = (
            Gst.MessageType.ASYNC_DONE |
            Gst.MessageType.EOS        |
            Gst.MessageType.ERROR      |
            Gst.MessageType.WARNING    |
            Gst.MessageType.ELEMENT
        )

        # GLib-thread drift correction: one idle query in flight at a time
        # _drift_pending guards both position and duration queries (single GLib slot).
        self._drift_pending: bool = False
        self._tick_last_wt:   float = -1.0
        self._resume_wt:      float = 0.0
        self._play_start_wt:  float = 0.0   # wall-clock of last play — for relative timestamps
        self._sig_drift_gst_ms.connect(self._apply_drift_correction)
        self._sig_dur_gst_ms.connect(self._on_dur_from_glib)

    @staticmethod
    def _sink_available(out: str) -> bool:
        """Check whether a GStreamer sink can reach its daemon.

        pipewiresink: checks wpctl status output for a real Audio Sink.
                      Returns False if PipeWire is installed but has no audio
                      node (e.g. pulseaudio-wireplumber architecture).
        pulsesink:    set_state(READY) is sufficient.
        """
        if out == 'pipewiresink':
            import glob
            uid = os.getuid()
            # No socket means daemon is not running
            if not glob.glob(f'/run/user/{uid}/pipewire-0*'):
                return False
            # Check for a real audio sink node via wpctl
            try:
                out_wp = subprocess.check_output(
                    ['wpctl', 'status'], stderr=subprocess.DEVNULL, text=True,
                    timeout=2)
                # The 'Audio' section under 'Sinks:' must have at least one real device
                audio_section = out_wp.split('Audio')[1] if 'Audio' in out_wp else ''
                video_section = audio_section.split('Video')[0] if 'Video' in audio_section else audio_section
                sinks_section = video_section.split('Sinks:')[1] if 'Sinks:' in video_section else ''
                sources_section = sinks_section.split('Sources:')[0] if 'Sources:' in sinks_section else sinks_section
                # Real node line: starts with a number (e.g. '42. Sink Name')
                has_node = bool(_re.search(r'^\s*\d+\.', sources_section, _re.MULTILINE))
                if not has_node:
                    return False
            except Exception:
                return False
            # Check whether we can actually connect
            try:
                b = Gst.parse_bin_from_description('pipewiresink', True)
                ret = b.set_state(Gst.State.READY)
                b.set_state(Gst.State.NULL)
                return ret in (Gst.StateChangeReturn.SUCCESS,
                               Gst.StateChangeReturn.ASYNC)
            except Exception:
                return False
        # pulsesink / autoaudiosink / alsasink
        try:
            b = Gst.parse_bin_from_description(out, True)
            ret = b.set_state(Gst.State.READY)
            b.set_state(Gst.State.NULL)
            return ret in (Gst.StateChangeReturn.SUCCESS,
                           Gst.StateChangeReturn.ASYNC)
        except Exception:
            return False

    @staticmethod
    def _detect_chain():
        for chain, out in zip(Player._CHAINS, Player._OUTS):
            if not Player._sink_available(out):
                continue
            desc = f'{chain} ! {out}' if chain else out
            try:
                b = Gst.parse_bin_from_description(desc, True)
                b.set_state(Gst.State.NULL)
                print(f'[Player] _detect_chain: selected sink={out!r} chain={chain!r}')
                return chain, out
            except Exception:
                continue
        return Player._FALLBACK

    @staticmethod
    def _is_hw_device(dev: str) -> bool:
        """True iff dev is a real ALSA hw device (not pipewire/pulse/auto)."""
        return bool(dev) and dev not in ("pipewire", "pulseaudio", "pulse", "auto")

    def load(self, filepath: str, paused: bool = False):
        self._last_filepath = filepath   # remember for dead-pipe recovery in play_pause
        self._destroy()
        self._spec_serial += 1
        self._pipe = Gst.ElementFactory.make('playbin', None)
        if not self._pipe:
            self.sig_err.emit('playbin unavailable'); return
        self._pipe.set_property('uri', Path(filepath).as_uri())
        self._pipe.set_property('volume', self._effective_volume())
        self._stream_restore_reset = False  # reset once on first ASYNC_DONE

        # Get sample rate from track metadata; emit sig_fs_changed so ControlBar
        # recomputes freq→bin mapping tables with the correct Nyquist frequency.
        track = read_metadata(filepath)
        self._current_fs = track.sample_rate if track.sample_rate > 0 else 48000
        self.sig_fs_changed.emit(self._current_fs)

        # Build sink bin with EQ (spectrum is tapped pre-volume via audio-filter below)
        sink_bin, eq_filters = self._make_sink_bin()
        if sink_bin:
            self._pipe.set_property('audio-sink', sink_bin)
            self._eq_filters = eq_filters
            # Apply current EQ settings
            self._apply_eq_to_filters()
        elif self._is_hw_device(self._alsa_device):
            # ALSA sink failed to build (device not openable at pipeline-build time).
            # Emit sig_err so MainWindow._on_player_error triggers the hw→plughw retry.
            print(f'[Player] ALSA sink build failed for {self._alsa_device!r} — emitting error')
            self._destroy()
            self.sig_err.emit(f'ALSA: cannot open device {self._alsa_device!r}')
            return

        # Attach spectrum as audio-filter so it reads the signal BEFORE playbin's
        # volume element.  This means bar heights reflect real acoustic amplitude and
        # are never clipped by the threshold due to volume attenuation — eliminating
        # the need for post-hoc dB compensation which loses data below MIN_DB.
        # The spectrum element is a pure analyser: its src pad passes audio unchanged.
        # Burst messages from large FLAC decode blocks (libFLAC 1.5.0 at 44.1 kHz/16-bit
        # emits ~3 spectrum messages per 104 ms block) are handled in software:
        # _store_spectrum accumulates elapsed frames; _compute_viz_frame applies
        # alpha^N in one EMA step.  audiobuffersplit is intentionally omitted — it
        # causes caps-negotiation failures on some format/codec combinations that
        # result in silence, and its state-change locking can trigger pipeline crashes
        # when tracks are switched or focus is lost.
        self._spec_el = None
        if self._has_spec:
            # Start with interval=3600s (effectively never fires) so the spectrum
            # element is completely dormant from the moment the pipeline is built.
            # _update_spec_active() below enables it only if viz is actually on.
            #
            # Previously this used interval=_SPEC_INTERVAL_NS (30 fps) and relied
            # on _update_spec_active() to immediately override it.  That worked on
            # the first track (pipeline is still in NULL state when properties are
            # written, so the override is atomic).  On tracks 2+ the pipeline
            # transitions to PLAYING before the element is fully linked, so there
            # is a real window where the 30-fps FFT runs; worse, the GStreamer
            # spectrum element does not interrupt an in-progress sample-accumulation
            # window when interval is changed mid-stream — so the element can stay
            # hot for one full 30-fps cycle (~33 ms) causing the audioconvert +
            # FFT overhead to persist indefinitely.  Starting dormant eliminates
            # the race entirely: _update_spec_active only needs to *enable*, never
            # to race-disable.
            _DORMANT_INTERVAL = 3_600_000_000_000  # 1 hour in ns — never fires
            spec_desc = (
                f'audioconvert ! audio/x-raw,format=F32LE '
                f'! spectrum name=bp_spec bands={GST_BANDS} '
                f'threshold={int(MIN_DB)} interval={_DORMANT_INTERVAL} '
                f'post-messages=false message-magnitude=true message-phase=false'
                f' ! audioconvert'   # passthrough: restore caps flexibility for playsink
            )
            try:
                spec_bin = Gst.parse_bin_from_description(spec_desc, True)
                self._pipe.set_property('audio-filter', spec_bin)
                self._spec_el = spec_bin.get_by_name('bp_spec')
                if self._spec_el:
                    # Enable to 30 fps only if viz (main or overlay) actually needs it.
                    self._update_spec_active()
            except Exception as e:
                print(f'[Player] spectrum audio-filter creation failed: {e}')

        bus = self._pipe.get_bus()
        self._bus = bus   # held so _poll_bus can call timed_pop_filtered each tick
        self._bus_timer.start()

        # Always start PLAYING regardless of the requested end-state.
        # set_state(PAUSED) on a fresh pipewiresink pipeline blocks the calling
        # thread while PipeWire's session manager acquires the audio node and
        # completes preroll — this can take several seconds and hangs the UI.
        # set_state(PLAYING) returns immediately; GStreamer completes the transition
        # asynchronously.  If the caller wanted PAUSED we transition back once
        # ASYNC_DONE (preroll complete) arrives on the bus.
        self._pipe.set_state(Gst.State.PLAYING)
        self._playing = True; self._pos_timer.start()
        self._start_pos_burst(8)  # fast updates while prerolling

        if not self._silent_recovery:
            self._pos_playing = True
            # Only reset anchor to 0 if the caller hasn't already positioned it.
            # _load_and_seek and the ALSA probe's _run() both call _anchor_now(pos)
            # before load() so the seekbar stays at the correct position during
            # preroll rather than snapping to 0.
            if self._pos_anchor_ms == 0.0:
                self._anchor_now(0.0)

        if paused:
            # Pipeline must reach PAUSED/PLAYING (preroll) before we can pause it
            # without blocking.  _on_msg handles ASYNC_DONE and calls _deferred_pause
            # if this flag is set.  Capture the pipe reference so stale callbacks
            # from a superseded pipeline are silently ignored.
            self._pending_pause_pipe = self._pipe
        else:
            self._pending_pause_pipe = None

        # Once the pipeline has prerolled (~300-600 ms), re-anchor from GStreamer
        # so any startup latency is absorbed and the display stays accurate.
        def _post_load_confirm():
            if not self._pipe or not self._playing:
                return
            self._anchor_from_gst()
        QTimer.singleShot(600, _post_load_confirm)
        if not self._silent_recovery:
            self.sig_playing.emit(True)   # always playing until deferred pause fires

    def play_pause(self):
        if not self._pipe:
            # Pipeline was destroyed (e.g. after a GST ERROR).  If we know the last
            # file, reload it so the user's Play press is not silently swallowed.
            if self._last_filepath:
                pos_ms = int(self._pos_anchor_ms)
                self._load_and_seek(self._last_filepath, pos_ms)
            return
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
            self._play_start_wt = _monotonic()
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
            # Reset stall tracking so detection window starts fresh after resume.
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

    def _load_and_seek(self, filepath: str, pos_ms: int, silent: bool = False, paused: bool = False):
        """Load filepath and seek to pos_ms after preroll. Used for dead-pipe recovery.

        Args:
            silent: When True (stall auto-recovery), the UI is not notified — no busy
                    spinner, no play/pause icon flip, no viz clear.  The seekbar keeps
                    interpolating from the saved anchor and the user sees nothing.
            paused: When True the pipeline ends up paused at pos_ms.
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
            self._viz_spec[:] = MIN_DB
            self._viz_discard_until = _monotonic() + 0.5   # 500 ms discard post-load

        self._pause_ts = 0.0
        self._gst_pos_adv_ms   = -1.0
        self._gst_pos_adv_wt   = -1.0

        if pos_ms > 200:
            self.load(filepath, paused=paused)
            # Mute immediately so the ~400 ms preroll window before the seek
            # fires is completely silent — user never hears the start of the track.
            if self._pipe:
                self._pipe.set_property('volume', 0.0)
            def _do_seek(p=pos_ms, _sil=silent, _paused=paused):
                self.seek(p)
                def _after_seek(_sil=_sil):
                    self._anchor_from_gst()
                    # Restore volume only if pipeline is still alive and belongs
                    # to this reload (not superseded by another load()).
                    if self._pipe:
                        self._pipe.set_property('volume', self._effective_volume())
                    if not _sil:
                        self.sig_busy.emit(False)
                    self._silent_recovery = False
                QTimer.singleShot(350, _after_seek)
            QTimer.singleShot(400, _do_seek)
        else:
            self.load(filepath, paused=paused)
            # Even for pos_ms <= 200 (effectively start-of-track), mute briefly so
            # any seek-window audio glitch or codec pre-buffer flush is inaudible.
            if self._pipe:
                self._pipe.set_property('volume', 0.0)
            def _after_preroll(_sil=silent):
                self._anchor_from_gst()
                if self._pipe:
                    self._pipe.set_property('volume', self._effective_volume())
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

        self._load_and_seek(fp, pos_ms, silent=True, paused=not self._playing)
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
            # Mute immediately so the preroll window before the seek fires is
            # completely silent — user never hears the beginning of the track.
            if self._pipe:
                self._pipe.set_property('volume', 0.0)
            if pos_ms > 200:
                # Same as _resume_with_reload: wait for preroll before seeking.
                def _do_seek_silent(p=pos_ms):
                    self.seek(p)
                    def _finish():
                        self._anchor_from_gst()
                        if self._pipe:
                            self._pipe.set_property('volume', self._effective_volume())
                        self._silent_recovery = False
                    QTimer.singleShot(350, _finish)
                QTimer.singleShot(400, _do_seek_silent)
            else:
                def _restore_vol_short():
                    if self._pipe:
                        self._pipe.set_property('volume', self._effective_volume())
                    self._silent_recovery = False
                QTimer.singleShot(500, _restore_vol_short)
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
            # Set position anchor immediately to seek target — UI updates at zero latency
            # even before GStreamer has finished the seek.
            self._anchor_now(float(max(0, ms)))
            # Increment serial BEFORE seek so old GLib bus messages arriving after
            # the serial bump are tagged with the new serial and can be filtered.
            self._spec_serial += 1
            self._viz_spec[:] = MIN_DB
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
            def _schedule_confirm_anchor():
                # query_position is thread-safe; run directly on Qt thread
                try:
                    pipe = self._pipe
                    if not pipe or not self._playing:
                        return
                    ok2, p2 = pipe.query_position(Gst.Format.TIME)
                    if ok2 and p2 >= 0:
                        confirmed_ms = p2 / Gst.MSECOND
                        if abs(confirmed_ms - _seek_ms) < 80:
                            self._sig_drift_gst_ms.emit(confirmed_ms, _monotonic())
                except Exception:
                    pass
            QTimer.singleShot(250, _schedule_confirm_anchor)
            self.sig_seek_flush.emit()
        except Exception as ex:
            print(f'[Player] seek error: {ex}')
        self.sig_seek.emit()

    def set_volume(self, v: float):
        """Set playback volume. v is 0.0–1.0 (slider 0–100 mapped linearly)."""
        self._volume = max(0.0, min(1.0, v))
        if self._pipe:
            self._pipe.set_property('volume', self._effective_volume())

    def _effective_volume(self) -> float:
        """Return the volume value to set on the GStreamer playbin volume property.

        playbin volume range is 0.0–10.0 on both backends (1.0 = unity gain).
        self._volume is 0.0–1.0 (slider 0–100 / 100).

          - PipeWire: pass through as-is (0.0–1.0 = unity, no distortion)
          - ALSA:     divide by 7.5 (tuned)
        """
        if self._is_hw_device(self._alsa_device):
            return self._volume / 7.5
        return self._volume

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
            # interval: active = _SPEC_INTERVAL_NS (30 fps);
            # inactive = 3600 s (effectively never fires — eliminates FFT accumulation
            # overhead entirely; previous value of 1 s was still running audioconvert
            # and waking the GLib loop once per second for no reason).
            interval = self._SPEC_INTERVAL_NS if need else 3_600_000_000_000
            self._spec_el.set_property('interval', interval)

    def set_eq_enabled(self, enabled: bool):
        if self._eq_enabled == enabled:
            return
        self._eq_enabled = enabled
        # Rebuild the pipeline so EQ filters are added/removed (bit-perfect when off).
        # Use _resume_with_reload (same recovery path as sink-stolen errors) instead of
        # the bare _reload_current destroy+load sequence, which can race with PipeWire
        # buffer reclaim and trigger gst-resource-error-quark code 3.
        if self._pipe:
            _fb = int(self._pos_anchor_ms)
            self._resume_with_reload(fallback_ms=_fb)
        else:
            self._apply_eq_to_filters()

    def set_eq_bands(self, bands: List[tuple]):
        """bands: list of (freq, gain, Q) or (freq, gain, Q, type).
        type is one of EQ_TYPE_* constants (default EQ_TYPE_PEAK = 0)."""
        self._eq_bands = bands[:MAX_EQ_BANDS]  # truncate if too many
        self._apply_eq_to_filters()

    def set_limiter_enabled(self, enabled: bool):
        if self._limiter_enabled == enabled:
            return
        self._limiter_enabled = enabled
        if self._pipe:
            _fb = int(self._pos_anchor_ms)
            self._resume_with_reload(fallback_ms=_fb)

    def set_stereo_enabled(self, enabled: bool):
        if self._stereo_enabled == enabled:
            return
        self._stereo_enabled = enabled
        if self._pipe:
            _fb = int(self._pos_anchor_ms)
            self._resume_with_reload(fallback_ms=_fb)

    def set_stereo_width(self, width: int):
        """width: -100 to +100.  0 = unity, -100 = mono, +100 = max wide.
        Applied live via _StereoWidthBin.set_width() — no pipeline reload needed.
        """
        new_width = max(-100, min(100, width))
        if new_width == self._stereo_width:
            return
        self._stereo_width = new_width
        if self._stereo_el is not None:
            self._stereo_el.set_width(new_width)

    def set_preamp_db(self, db: float):
        """Preamp gain in dB, applied before the EQ filters (-24..+24 dB).
        Applied live via the GStreamer volume element — no pipeline reload needed."""
        db = max(-24.0, min(24.0, float(db)))
        self._preamp_db = db
        if self._preamp_el is not None:
            linear = 10.0 ** (db / 20.0)
            if self._preamp_el is not None:
                self._preamp_el.set_property('volume', linear)

    def _apply_eq_to_filters(self):
        """Update the properties of existing EQ filter elements."""
        if not self._eq_filters:
            return
        self._apply_eq_to_filters_glib()

    def _apply_eq_to_filters_glib(self):
        if not self._eq_filters:
            return
        fs = self._current_fs
        for i, filt in enumerate(self._eq_filters):
            if i < len(self._eq_bands) and self._eq_enabled:
                band = self._eq_bands[i]
                # Support both legacy (freq, gain, Q) and new (freq, gain, Q, type) tuples
                f0   = float(band[0])
                gain = float(band[1])
                q    = float(band[2])
                ftype = int(band[3]) if len(band) >= 4 else EQ_TYPE_PEAK

                # Filters that don't use gain: bypass if not providing real attenuation
                # For pass/notch filters we always compute coefficients regardless of gain
                is_gain_type = ftype in (EQ_TYPE_PEAK, EQ_TYPE_LOWSHELF, EQ_TYPE_HIGHSHELF)
                if is_gain_type and gain == 0.0:
                    # Bypass: unity gain identity filter
                    b = [1.0, 0.0, 0.0]
                    a = [1.0, 0.0, 0.0]
                else:
                    coeffs = eq_band_coefficients(fs, f0, gain, q, ftype)
                    if coeffs is None:
                        b = [1.0, 0.0, 0.0]
                        a = [1.0, 0.0, 0.0]
                    else:
                        b0, b1, b2, a1, a2 = coeffs
                        b = [b0, b1, b2]
                        a = [1.0, a1, a2]
            else:
                # Bypass slot
                b = [1.0, 0.0, 0.0]
                a = [1.0, 0.0, 0.0]
            filt.set_property('b', b)
            filt.set_property('a', a)

    def set_output_device(self, device_id: str):
        """Switch audio output sink.  device_id is 'pipewire' or a plughw id like
        'plughw:0,0'.  Change takes effect immediately by reloading the current
        track at the current position.  If called before any track is loaded
        (startup restore) the device is stored silently and takes effect on first play."""
        if device_id == self._alsa_device:
            return
        self._alsa_device = device_id
        print(f'[Player] output device -> {device_id}')

        # Re-apply volume with new sink active.
        if self._pipe:
            self._pipe.set_property('volume', self._effective_volume())

        if self._last_filepath:
            pos_ms = int(self.position_ms())
            self._last_switch_pos_ms      = pos_ms         # consumed by ALSA probe
            self._last_switch_was_playing = self._playing  # consumed by ALSA probe
            was_playing = self._playing
            self._destroy()
            if not self._is_hw_device(device_id):
                # PipeWire: reload here.  Always start PLAYING — load() now routes
                # paused=True through a deferred ASYNC_DONE pause to avoid blocking
                # the main thread on PipeWire node acquisition.
                fp = self._last_filepath
                QTimer.singleShot(150, lambda: self._load_and_seek(
                    fp, pos_ms, paused=not was_playing))

    def _active_sink_desc(self) -> str:
        """Return the GStreamer sink description for the current output device.

        When an ALSA device is selected, hw:X,Y (derived from the selected
        plughw:X,Y) is tried first for bit-perfect output; plughw:X,Y is used
        as fallback (set via _alsa_device after a failed hw: attempt).  audioconvert + audioresample are always prepended
        so GStreamer caps negotiation succeeds regardless of source format.
        """
        if self._is_hw_device(self._alsa_device):
            return f'audioconvert ! audioresample ! alsasink device={self._alsa_device}'
        return self._out  # PipeWire (or autoaudiosink fallback)

    def _make_sink_bin(self):
        """Create a bin containing EQ (if any), limiter (optional),
           stereo enhancer (optional), and sink.
           The spectrum element is wired separately as audio-filter (pre-volume) in load().
           Returns (bin, list_of_eq_filter_elements)."""
        elements = []

        # Preamp: a volume element before the EQ chain, updated live via set_preamp_db()
        self._preamp_el = None
        preamp_el = Gst.ElementFactory.make('volume', 'preamp')
        if preamp_el:
            linear = 10.0 ** (self._preamp_db / 20.0)
            preamp_el.set_property('volume', linear)
            self._preamp_el = preamp_el
            elements.append(preamp_el)
        else:
            print('[Player] volume element unavailable — preamp disabled')

        eq_bin, eq_filters = self._create_eq_bin()
        if eq_bin:
            elements.append(eq_bin)

        # Limiter via audiodynamic (hard-limit mode, ratio=∞ approximated by 100)
        self._limiter_el = None
        if self._limiter_enabled:
            lim = Gst.ElementFactory.find('audiodynamic')
            if lim:
                lim_el = Gst.ElementFactory.make('audiodynamic', 'limiter')
                if lim_el:
                    # audiodynamic enums are integers: mode 0=compressor 1=expander;
                    # characteristics 0=hard-knee 1=soft-knee
                    lim_el.set_property('mode', 0)             # compressor
                    lim_el.set_property('characteristics', 0)  # hard-knee
                    lim_el.set_property('ratio', 1.0)          # ratio=1.0 → ∞:1 brick-wall limiter
                    lim_el.set_property('threshold', 0.891)    # 0.891 ≈ −1.0 dBFS ceiling
                    self._limiter_el = lim_el
                    # wrap in a passthrough bin so caps are preserved
                    lim_bin = Gst.Bin.new('limiter_bin')
                    conv_in  = Gst.ElementFactory.make('audioconvert', 'lim_conv_in')
                    conv_out = Gst.ElementFactory.make('audioconvert', 'lim_conv_out')
                    lim_bin.add(conv_in); lim_bin.add(lim_el); lim_bin.add(conv_out)
                    conv_in.link(lim_el); lim_el.link(conv_out)
                    lim_bin.add_pad(Gst.GhostPad.new('sink', conv_in.get_static_pad('sink')))
                    lim_bin.add_pad(Gst.GhostPad.new('src',  conv_out.get_static_pad('src')))
                    elements.append(lim_bin)
            else:
                print('[Player] audiodynamic not found — limiter unavailable')

        # Stereo width via M/S (mid-side) processing using volume elements.
        # PyGObject cannot set GstValueArray properties at runtime, and
        # parse_bin_from_description also rejects mix-matrix strings.
        # Instead we implement M/S width purely with volume gain elements:
        #
        #   mid  = (L+R) — the mono/centre content
        #   side = (L-R) — the stereo/difference content
        #
        # width < 50 (w<1): reduce side → narrower image
        # width = 50 (w=1): unity, no change
        # width > 50 (w>1): boost side → wider image (Poweramp-style)
        #
        # Implementation: audiopanorama in "matrix" method with panorama=0
        # cannot do this directly.  We use a volume element whose gain is
        # (w-1) on a difference signal — but that needs a tee/adder graph
        # which parse_bin_from_description cannot do either.
        #
        # Simplest working approach with available elements:
        # rgvolume has pre-amp + fallback-gain but not L/R independent.
        #
        # Final working approach: use a custom GStreamer pipeline with
        # audiomixer + tee to implement the M/S matrix entirely via
        # volume gains and channel-wise operations:
        #
        #   L' = mid_gain*L + mid_gain*R + side_gain*L - side_gain*R
        #      = (mid_gain + side_gain)*L + (mid_gain - side_gain)*R
        #   where mid_gain = 0.5, side_gain = 0.5*w
        #   → a = mid_gain + side_gain = 0.5*(1+w)   [same as before]
        #     b = mid_gain - side_gain = 0.5*(1-w)
        #
        # The only way to apply this without mix-matrix is a stereopan
        # element that doesn't exist, or a custom element.
        # Since all GStreamer property-based approaches fail for this,
        # we implement it using a Python GStreamer BaseTransform element
        # that processes audio buffers directly with numpy.
        self._stereo_el = None
        if self._stereo_enabled:
            try:
                st_bin = _StereoWidthBin(self._stereo_width)
                self._stereo_el = st_bin
                elements.append(st_bin)
                print(f'[Player] stereo width bin OK (w={self._stereo_width})')
            except Exception as e:
                print(f'[Player] stereo width bin failed: {e}')

        try:
            sink = Gst.parse_bin_from_description(self._active_sink_desc(), True)
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

    def _destroy(self):
        was_playing = self._playing
        if self._pipe:
            # Remove the bus watch BEFORE set_state(NULL) so no further GLib bus
            # Stop the poll timer and drop the bus reference before handing the
            # pipeline off to a daemon thread for NULL teardown.
            self._bus_timer.stop()
            self._bus = None
            # set_state(NULL) on a pipewiresink pipeline can block the calling
            # thread for several seconds while PipeWire's session manager negotiates
            # link teardown.  Run it on a daemon thread so the Qt event loop stays
            # responsive.  We null self._pipe immediately so no further code in this
            # session touches the old pipeline.
            _dying_pipe = self._pipe
            self._pipe = None
            threading.Thread(
                target=_dying_pipe.set_state,
                args=(Gst.State.NULL,),
                daemon=True,
                name='gst-null'
            ).start()
        self._pending_pause_pipe = None   # cancel any in-flight deferred pause
        self._spec_el = None; self._playing = False
        self._pos_timer_burst = 0
        self._pos_timer.setInterval(250)
        self._pos_timer.stop()
        if not self._silent_recovery:
            self._pos_playing   = False
            self._pos_anchor_ms = 0.0
            self._pos_anchor_wt = 0.0
        self._eq_filters = []
        self._dur_ms_cached = 0
        self._pause_ts       = 0.0   # reset — prevent reload loop after ERROR/EOS
        self._reloading      = False  # reset — prevent guard staying locked after stop/error
        self._reload_guard   = False  # reset — WARNING-path guard
        if not self._silent_recovery:
            self._viz_bar_buf[:] = 0.0
            self._viz_spec[:] = MIN_DB
            self._viz_discard_until = 0.0
        self._viz_last_stream_time = -1
        self._viz_accumulated_el = 0
        self._viz_has_new = False
        self._viz_has_any = False
        self._viz_mag_field_idx = -1   # reset field cache — new pipeline may differ
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

        # Detect late tick — Qt timer fired significantly after its scheduled interval.
        # Skip when _tick_last_wt is the -1.0 sentinel (first tick ever).
        _last = self._tick_last_wt
        _interval = self._pos_timer.interval()
        if _last >= 0.0:
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
        if self._playing and self._pipe \
                and self._pos_timer_burst == 0 and not self._drift_pending:
            self._drift_pending = True
            QTimer.singleShot(1, self._drift_query_glib)

        # Stall detection runs in _apply_drift_correction which operates on real
        # GStreamer-queried positions.  Checking interpolated position_ms() here was
        # broken: that value always advances while _pos_playing=True, so frozen
        # pipelines were never detected.

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

    def _poll_bus(self):
        """Qt main thread: drain pending GStreamer bus messages (non-blocking).

        Called every 20 ms by _bus_timer instead of using add_signal_watch() +
        a GLib main loop.  timed_pop_filtered(0, mask) returns immediately when
        the bus is empty, so this call is essentially free when nothing is
        happening.  Only the 5 message types _on_msg handles are dequeued —
        QOS, STATE_CHANGED, TAG, STREAM_STATUS and LATENCY are never popped and
        never touch Python at all.
        """
        bus = getattr(self, '_bus', None)
        if bus is None:
            return
        while True:
            msg = bus.timed_pop_filtered(0, self._bus_msg_mask)
            if msg is None:
                break
            self._on_msg(bus, msg)

    def _on_msg(self, _bus, msg):
        if msg.type == Gst.MessageType.ASYNC_DONE:
            # On PipeWire, stream-restore may have saved a stale volume for this
            # application and will silently override playbin's volume on stream open.
            # Reset the sink-input volume to 100% once per pipeline so the slider
            # is always in control.
            if (not getattr(self, '_stream_restore_reset', True)
                    and not self._is_hw_device(self._alsa_device)):
                self._stream_restore_reset = True
                def _reset_stream_vol():
                    try:
                        out = subprocess.check_output(
                            ['pactl', 'list', 'sink-inputs', 'short'],
                            stderr=subprocess.DEVNULL)
                        pid = str(os.getpid()).encode()
                        for line in out.splitlines():
                            if pid in line:
                                idx = line.split()[0].decode()
                                subprocess.run(
                                    ['pactl', 'set-sink-input-volume', idx, '100%'],
                                    stderr=subprocess.DEVNULL)
                                break
                    except Exception:
                        pass
                threading.Thread(target=_reset_stream_vol, daemon=True).start()
            # Preroll complete.  If load() was called with paused=True we started
            # PLAYING to avoid blocking the main thread on PipeWire node acquisition.
            # Now that the pipeline is prerolled, drop to PAUSED safely — this
            # set_state() call is non-blocking because the sink is already acquired.
            pending = self._pending_pause_pipe
            if pending is not None and pending is self._pipe:
                self._pending_pause_pipe = None
                self._pipe.set_state(Gst.State.PAUSED)
                frozen = self._pos_anchor_ms   # anchor was set to seek target in _load_and_seek
                self._playing = False; self._pos_timer.stop()
                self._pos_playing = False
                self._anchor_now(frozen)
                if not self._silent_recovery:
                    self.sig_playing.emit(False)
        elif msg.type == Gst.MessageType.EOS:
            self._playing = False; self._pos_timer.stop()
            self._pos_playing = False
            # Freeze anchor at end of track
            if self._dur_ms_cached > 0:
                self._anchor_now(float(self._dur_ms_cached))
            # Notify UI that playback stopped (viz must freeze immediately).
            # sig_playing and sig_end are both thread-safe pyqtSignals — they
            # are delivered queued to the main thread.
            # Do NOT touch the pipeline here; _advance() →
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
                    # ALSA hw/plughw warnings (xrun, buffer underrun) are transient —
                    # reloading would create an infinite loop.  Only reload for
                    # PipeWire/pulse/auto sinks where a WARNING signals real sink loss.
                    if self._is_hw_device(self._alsa_device):
                        print(f'[Player] ALSA sink warning (no reload): {warn}')
                    else:
                        print(f'[Player] audio sink warning - reloading: {warn}')
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
            fi = self._viz_mag_field_idx
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
        if ba is None or bb is None or bt is None or not self._viz_has_new:
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

            # ── 2b. Volume compensation removed ──────────────────────────────
            # Spectrum is now wired as audio-filter (pre-volume) so bar heights
            # already reflect real acoustic amplitude.  No dB offset needed.

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

# MprisServer is defined in mpris.py