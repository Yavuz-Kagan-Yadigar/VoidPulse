"""
VoidPulse — audio engine.

Player owns the GStreamer pipeline: source selection (ALSA direct or
PipeWire), the EQ/limiter/stereo-width chain, spectrum tapping for the
visualiser, position interpolation, seeking, and shuffle/repeat.

Biquad coefficients come from eq_filters.py (shared with the EQ UI) and the
stereo-width bin and loudness analysis from player_dsp.py.
"""
from constants import *
from cover_art import read_metadata
from constants import EQ_TYPE_HIGHSHELF, EQ_TYPE_LOWSHELF, GST_BANDS, MAX_EQ_BANDS, MIN_DB, VIZ_BANDS
import re as _re
import urllib.parse as _urlparse
from time import monotonic as _monotonic
import numpy as _np

from constants import EQ_TYPE_PEAK
from eq_filters import eq_band_coefficients

_DIAG = False  # set True to print timing diagnostics for the render/spectrum timers
from resampler import (build_resampler_stage, live_pipewire_graph_rate,
                        live_pipewire_allowed_rates, live_pipewire_default_sink_rates)
from alsa import probe_alsa_hw_rate, invalidate_alsa_rate_cache
import alsa
from player_dsp import (_StereoWidthBin, _run_rganalysis,
                        _rg_gain_cache, _rg_analyzing)

class RepeatMode(enum.Enum):
    NONE = 0; ALL = 1; ONE = 2


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
    _sig_gain_analyzed = pyqtSignal(str, float)   # background thread → main thread: (filepath, gain_db)

    _SPEC_INTERVAL_NS = int(1_000_000_000 / 30)  # 30fps spectrum — reduces GIL contention vs 60fps
    _SPEC_INTERVAL_S  = 1.0 / 30.0
    # Spectrum frames buffered between arrival and display. Sized for the worst
    # real burst: libFLAC's ~3 messages per decode block, doubled for a block
    # that lands while the render timer is starved.
    _VIZ_PEND_N = 8

    # Candidate (pre-spectrum chain, sink) pairs in priority order: PipeWire
    # first (bit-perfect), then PulseAudio, then autoaudiosink. Within each sink:
    # direct, format-only conversion, then conversion plus resampling.
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
        # Position is pos = _pos_anchor_ms + elapsed since the anchor, rather than
        # a GStreamer query per tick (which lags after seek/pause). The anchor
        # moves on load/seek/play/pause for zero-latency response, and periodic
        # drift correction nudges it back in line with GStreamer.
        self._pos_anchor_ms: float = 0.0   # reference position in ms
        self._pos_anchor_wt: float = 0.0   # wall-clock time of that reference
        self._pos_playing:   bool  = False  # local copy of playing state for anchor math

        # Viz state, all preallocated numpy arrays
        self._viz_spec = _np.full(GST_BANDS, MIN_DB, dtype=_np.float32)  # inertia state
        # Viz mapping tables — set by ControlBar.set_viz_tables()
        self._viz_ba: object = None          # int32 (VIZ_BANDS,)
        self._viz_bb: object = None
        self._viz_bt: object = None
        self._viz_inertia: float = 0.5
        self._viz_overlay_cb: object = None  # callable(list) for overlay frames
        self._viz_discard_until: float = 0.0  # wall-clock: discard frames before this
        self._viz_has_any: bool = False       # True once first spectrum arrives after load
        # Spectrum queue: _store_spectrum fills it, _compute_viz_frame drains it
        self._viz_pend    = _np.full((self._VIZ_PEND_N, GST_BANDS), MIN_DB, dtype=_np.float32)
        self._viz_pend_r: int  = 0            # next slot to release
        self._viz_pend_w: int  = 0            # next slot to fill
        self._viz_pend_ct: int = 0            # frames currently queued
        self._viz_target  = _np.full(GST_BANDS, MIN_DB, dtype=_np.float32)  # EMA target: last released frame
        self._viz_next_release: float = 0.0   # monotonic: when the next queued frame may be released
        self._viz_ema_wt: float = 0.0         # monotonic time of the last EMA step
        self._viz_bh_pre  = _np.empty(VIZ_BANDS, dtype=_np.float32)         # work buffer
        self._viz_tmp_pre = _np.empty(VIZ_BANDS, dtype=_np.float32)         # work buffer
        self._viz_ema_tmp = _np.empty(GST_BANDS, dtype=_np.float32)         # EMA work buffer
        self._viz_bar_buf = _np.zeros(VIZ_BANDS, dtype=_np.float32)  # published bar heights (pre-alloc)
        self._overlay_needs_spec: bool = False
        self._last_parsed_serial: object = None
        self._viz_mag_field_idx: int = -1   # cached 'magnitude' field index in spectrum structure
        self._reloading: bool = False
        self._reload_guard: bool = False
        self._silent_recovery: bool = False  # True during invisible stall recovery
        self._seek_retries: int = 0
        self._pos_timer_burst: int = 0
        # Stall detection on real queried positions, not interpolated ones.
        # _apply_drift_correction updates these and spots a freeze in ~700 ms.
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
        self._last_preamp_applied = None   # gain last written to it, for change logging
        # Loudness normalization: the track's REPLAYGAIN_TRACK_GAIN tag, folded
        # into the same preamp element as the EQ headroom. 0.0 is a no-op.
        self._loudness_norm_enabled = False
        self._current_track_gain_db = 0.0
        # Set while load() holds playback silent for an in-flight gain analysis
        self._awaiting_initial_gain_for: str = None
        # Stereo balance: -100 (full left) .. 0 (centre) .. +100 (full right)
        self._balance           = 0
        self._balance_el        = None     # GStreamer volume element ref pair (updated per load)

        self._chain, self._out = self._detect_chain()
        print(f'[Player] chain: "{self._chain or "(none)"}" → {self._out}  (pre-config default)')
        # Output device; 'pipewire' means the detected software sink
        self._alsa_device: str = 'pipewire'
        # PipeWire adaptive sample-rate opt-in — see set_pipewire_adaptive_rate().
        self._pipewire_adaptive_enabled: bool = False
        # Saved by set_output_device(), consumed by the ALSA probe. Set here so
        # _on_player_error can read them even before any device switch happened.
        self._last_switch_pos_ms:      Optional[int]  = None
        self._last_switch_was_playing: Optional[bool] = None
        # load(paused=True) parks the pipe here; ASYNC_DONE pauses it and clears it
        self._pending_pause_pipe = None

        self._has_spec = Gst.ElementFactory.find('spectrum') is not None
        print(f'[Player] spectrum: {"OK" if self._has_spec else "not found"}')

        self._pos_timer  = QTimer(self)
        self._pos_timer.setInterval(250)
        self._pos_timer.timeout.connect(self._tick_pos)
        # After seek/resume, fire more frequently for the first few ticks
        self._pos_timer_burst = 0   # countdown: ticks remaining at fast (100ms) rate

        # Bus polling instead of add_signal_watch() + a GLib main loop.
        # timed_pop_filtered(0) returns at once when the bus is empty, and the mask
        # keeps QOS/STATE_CHANGED/TAG/STREAM_STATUS/LATENCY out of Python entirely.
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

        # _drift_pending keeps one position/duration query in flight at a time
        self._drift_pending: bool = False
        self._tick_last_wt:   float = -1.0
        self._resume_wt:      float = 0.0
        self._play_start_wt:  float = 0.0   # wall-clock of last play — for relative timestamps
        self._sig_drift_gst_ms.connect(self._apply_drift_correction)
        self._sig_dur_gst_ms.connect(self._on_dur_from_glib)
        self._sig_gain_analyzed.connect(self._on_gain_analyzed)

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
                audio_section = out_wp.split('Audio')[1] if 'Audio' in out_wp else ''
                video_section = audio_section.split('Video')[0] if 'Video' in audio_section else audio_section
                sinks_section = video_section.split('Sinks:')[1] if 'Sinks:' in video_section else ''
                sources_section = sinks_section.split('Sources:')[0] if 'Sources:' in sinks_section else sinks_section
                # A node line is a number+period after wpctl's tree art, which
                # is not whitespace, so the prefix pattern cannot use \s*.
                has_node = bool(_re.search(r'^[^\d\n]*\d+\.', sources_section, _re.MULTILINE))
                if not has_node:
                    return False
            except Exception:
                return False
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

        # sig_fs_changed makes ControlBar rebuild its freq→bin tables for the
        # new Nyquist frequency.
        track = read_metadata(filepath)
        self._current_fs = track.sample_rate if track.sample_rate > 0 else 48000
        self.sig_fs_changed.emit(self._current_fs)
        self._current_track_gain_db = track.rg_track_gain_db
        self._awaiting_initial_gain_for = None
        if (self._loudness_norm_enabled and self._current_track_gain_db == 0.0
                and filepath not in _rg_gain_cache and not self._silent_recovery):
            # Gain unknown, and this is a user-visible load (a stall-recovery
            # reload must stay unnoticed, spinner included). Hold it paused and
            # muted until analysis finishes, reusing the preroll-then-pause path
            # and the sig_busy spinner, rather than playing a moment at the wrong
            # level and correcting audibly. _on_gain_analyzed resumes it.
            self._awaiting_initial_gain_for = filepath
            paused = True
            self._pipe.set_property('volume', 0.0)
            self.sig_busy.emit(True)
            self._analyze_loudness_async(filepath)

        # Reserve the card before anything opens it: the native-rate probe inside
        # _make_sink_bin() opens the PCM too, not just alsasink.
        self._sync_alsa_reservation()

        sink_bin, eq_filters = self._make_sink_bin()
        if sink_bin:
            self._pipe.set_property('audio-sink', sink_bin)
            self._eq_filters = eq_filters
            self._apply_eq_to_filters()
        elif self._is_hw_device(self._alsa_device):
            # Device not openable at build time — sig_err drives the
            # hw→plughw retry in MainWindow._on_player_error.
            print(f'[Player] ALSA sink build failed for {self._alsa_device!r} — emitting error')
            self._destroy()
            self.sig_err.emit(f'ALSA: cannot open device {self._alsa_device!r}')
            return

        # The spectrum goes in as audio-filter, i.e. before playbin's volume
        # element, so bar heights follow real amplitude instead of the volume
        # slider. It only analyses; audio passes through unchanged. Bursty
        # spectrum messages from large decode blocks are smoothed in software
        # (_store_spectrum queues, _compute_viz_frame releases) rather than with
        # audiobuffersplit, which breaks caps negotiation on some codecs.
        self._spec_el = None
        if self._has_spec:
            # Built dormant (an interval so long it never fires) and only enabled
            # by _update_spec_active() below. Starting at 30 fps and disabling
            # afterwards races: from track 2 on the pipeline reaches PLAYING
            # before the element is linked, and changing interval mid-stream does
            # not abandon an accumulation window already in progress, so the FFT
            # can keep running.
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
                    self._update_spec_active()
            except Exception as e:
                print(f'[Player] spectrum audio-filter creation failed: {e}')

        bus = self._pipe.get_bus()
        self._bus = bus   # held so _poll_bus can call timed_pop_filtered each tick
        self._bus_timer.start()

        # Always start PLAYING, whatever the caller asked for: set_state(PAUSED)
        # on a fresh pipewiresink pipeline blocks for seconds while the session
        # manager acquires the node, freezing the UI. PLAYING returns at once, and
        # a requested pause happens on ASYNC_DONE instead.
        self._pipe.set_state(Gst.State.PLAYING)
        self._playing = True; self._pos_timer.start()
        self._start_pos_burst(8)  # fast updates while prerolling

        if not self._silent_recovery:
            self._pos_playing = True
            # Keep an anchor the caller already set (_load_and_seek and the ALSA
            # probe do), so the seekbar does not snap to 0 during preroll.
            if self._pos_anchor_ms == 0.0:
                self._anchor_now(0.0)

        if paused:
            # Pausing only becomes non-blocking after preroll, so _on_msg does it
            # on ASYNC_DONE. The pipe reference identifies stale callbacks.
            self._pending_pause_pipe = self._pipe
        else:
            self._pending_pause_pipe = None

        # Re-anchor once prerolled (~300-600 ms) to absorb startup latency
        def _post_load_confirm():
            if not self._pipe or not self._playing:
                return
            self._anchor_from_gst()
        QTimer.singleShot(600, _post_load_confirm)
        if not self._silent_recovery:
            self.sig_playing.emit(True)   # always playing until deferred pause fires

    def play_pause(self):
        if not self._pipe:
            # Pipeline was destroyed (e.g. by a GStreamer error) — reload the last
            # file so the Play press is not silently swallowed.
            if self._last_filepath:
                pos_ms = int(self._pos_anchor_ms)
                self._load_and_seek(self._last_filepath, pos_ms)
            return
        if self._playing:
            self._pipe.set_state(Gst.State.PAUSED)
            # Freeze the anchor at the interpolated position before the clock stops
            frozen = self.position_ms()
            self._playing = False; self._pos_timer.stop()
            self._pos_playing = False
            self._anchor_now(frozen)   # anchor is now the paused position
            self._pause_ts = _monotonic()   # record pause time
            self.sig_playing.emit(False)
        else:
            self._play_start_wt = _monotonic()
            # timeout=0 so the UI thread never blocks. VOID_PENDING means a
            # transition is in progress; treat it as PAUSED.
            _, st, pending = self._pipe.get_state(timeout=0)
            eff_st = pending if (st == Gst.State.VOID_PENDING
                                 and pending != Gst.State.VOID_PENDING) else st

            # Pipeline dead — reload immediately, no further probing needed.
            if eff_st in (Gst.State.NULL, Gst.State.READY):
                # The user pressed Play, so end up PLAYING regardless of
                # self._playing (False in this branch).
                self._resume_with_reload(fallback_ms=int(self._pos_anchor_ms),
                                         want_playing=True)
                return

            pause_dur = (_monotonic() - self._pause_ts) if self._pause_ts > 0.0 else 0.0
            if pause_dur > 2.0:
                # PipeWire may have reclaimed the sink over a long pause. Resume
                # anyway; the stall detector reloads if position does not advance.
                print(f'[Player] resuming after {pause_dur:.1f}s pause — stall watcher armed')
            self._pipe.set_state(Gst.State.PLAYING)

            self._playing = True; self._pos_timer.start()
            self._resume_wt = _monotonic()   # gate drift correction for 1.5 s after resume
            # _pos_anchor_wt still holds the pause timestamp, so elapsed would come
            # out as the whole pause duration and jump the position forward. Reset
            # it to now so interpolation resumes where it froze.
            self._pos_anchor_wt = _monotonic()
            self._pos_playing = True
            # Fresh stall-detection window after resume
            self._gst_pos_adv_ms   = -1.0   # re-initialise on first post-resume drift query
            self._gst_pos_adv_wt   = -1.0
            # Fast position updates so the seekbar snaps back immediately
            self._start_pos_burst(8)
            # Drop frames buffered during the pause so the viz does not jump
            self._viz_discard_until = _monotonic() + 0.15
            self.sig_playing.emit(True)
            # query_position right after set_state(PLAYING) is unreliable — the
            # clock has not restarted yet, which shows up as 1-2 s of drift.
            # 150 ms is enough for it to settle.
            def _deferred_anchor():
                if self._pipe and self._playing:
                    if not self._anchor_from_gst():
                        # Not ready yet — one more try
                        QTimer.singleShot(150, lambda: self._pipe and self._playing
                                          and self._anchor_from_gst())
            QTimer.singleShot(150, _deferred_anchor)
            # Short pauses need nothing extra: drift correction and the
            # real-position stall detector in _apply_drift_correction cover them.

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
            self._viz_reset_queue()
            self._viz_discard_until = _monotonic() + 0.5   # 500 ms discard post-load

        self._pause_ts = 0.0
        self._gst_pos_adv_ms   = -1.0
        self._gst_pos_adv_wt   = -1.0

        if pos_ms > 200:
            self.load(filepath, paused=paused)
            # Mute through the ~400 ms preroll so the track's start is never heard
            if self._pipe:
                self._pipe.set_property('volume', 0.0)
            def _do_seek(p=pos_ms, _sil=silent, _paused=paused):
                self.seek(p)
                def _after_seek(_sil=_sil):
                    self._anchor_from_gst()
                    # Only if this pipeline is still the current one
                    if self._pipe:
                        self._pipe.set_property('volume', self._effective_volume())
                    if not _sil:
                        self.sig_busy.emit(False)
                    self._silent_recovery = False
                QTimer.singleShot(350, _after_seek)
            QTimer.singleShot(400, _do_seek)
        else:
            self.load(filepath, paused=paused)
            # Mute briefly even at start-of-track so a codec pre-buffer flush
            # stays inaudible.
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

    def _resume_with_reload(self, fallback_ms: int = 0, want_playing: bool = None):
        """Reload pipeline at current position, reacquiring the PipeWire sink.

        Args:
            fallback_ms: Seek target if GStreamer query_position returns 0 (pipeline
                         may already be NULL/READY).  Pass int(self._pos_anchor_ms).
            want_playing: End state after the reload.  Defaults to self._playing,
                         which is only correct for callers that reload a *healthy*
                         pipeline (EQ/limiter/stereo toggles).  Recovery callers
                         must pass it explicitly: both the sink-lost error handler
                         and play_pause's dead-pipeline branch have already set
                         self._playing = False by the time they get here, so the
                         default would silently reload PAUSED.  Because
                         _load_and_seek(silent=True) keeps _pos_playing = True the
                         seekbar carries on advancing over that paused pipeline —
                         the "it looks like it is playing but there is no sound
                         until I hit the button again" bug.
        """
        if want_playing is None:
            want_playing = self._playing
        # Re-entrancy guard: a WARNING and ERROR arriving together would reload
        # twice, and the resulting double seek makes the slider bounce.
        if self._reloading:
            return
        self._reloading = True

        # _last_filepath is always current; the URI property is the fallback
        fp = self._last_filepath
        if not fp:
            uri = ''
            try: uri = (self._pipe and self._pipe.get_property('uri')) or ''
            except Exception: pass
            if not uri:
                self._reloading = False
                return
            fp = _urlparse.unquote(uri.replace('file://', ''))

        # query_position is unreliable outside PAUSED/PLAYING, so trust GStreamer
        # only above 200 ms and fall back to the caller's anchor.
        gst_ms = 0
        if self._pipe:
            ok, pos = self._pipe.query_position(Gst.Format.TIME)
            gst_ms = pos // Gst.MSECOND if ok and pos > 0 else 0
        pos_ms = gst_ms if gst_ms > 200 else fallback_ms

        self._load_and_seek(fp, pos_ms, silent=True, paused=not want_playing)
        # silent=True suppresses load()'s own sig_playing, and the sink-lost
        # handler already emitted False, so re-assert it or the button stays paused.
        if want_playing:
            self.sig_playing.emit(True)
        # Release the guard once the pipeline has had time to preroll and seek
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
        # Separate guard from _resume_with_reload so the WARNING and ERROR
        # recovery paths do not block each other.
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
            # Mute through preroll so the track's start is never heard
            if self._pipe:
                self._pipe.set_property('volume', 0.0)
            if pos_ms > 200:
                # Wait for preroll before seeking, as _resume_with_reload does
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
        # Seeking outside PAUSED/PLAYING can hang, and _seek_retries already covers
        # a pipeline that has not got there yet, so the state query stays non-blocking.
        _, state, _pending = self._pipe.get_state(timeout=0)
        if state not in (Gst.State.PAUSED, Gst.State.PLAYING):
            # Retry, but bounded
            _retry = self._seek_retries
            if _retry < 6:
                self._seek_retries = _retry + 1
                QTimer.singleShot(100, lambda: self.seek(ms))
            return
        self._seek_retries = 0
        try:
            target_ns = max(0, ms) * Gst.MSECOND
            # Anchor to the target now so the UI updates before the seek completes
            self._anchor_now(float(max(0, ms)))
            # Bump the serial before seeking so pre-seek spectrum messages are
            # recognisable as stale.
            self._spec_serial += 1
            self._viz_spec[:] = MIN_DB
            self._viz_bar_buf[:] = 0.0
            self._viz_reset_queue()
            self._viz_discard_until = _monotonic() + 0.15   # skip buffered pre-seek frames
            self._pipe.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                target_ns)
            if self._playing:
                self._pipe.set_state(Gst.State.PLAYING)
                self._start_pos_burst(8)
            # Re-confirm the anchor once GStreamer has settled. An ACCURATE seek
            # can land a few ms off target; correcting it here keeps the seekbar
            # honest without a visible jump.
            _seek_ms = float(max(0, ms))
            def _schedule_confirm_anchor():
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
        """Set playback volume. v is 0.0–1.0 (slider 0–100 mapped linearly).

        sig_volume_changed carries the 0–100 slider value so the settings popup
        follows volume set from outside the UI (MPRIS SetVolume, media keys).
        It only fires on a real change, which also stops the popup's own
        valueChanged → set_volume round trip from ping-ponging.
        """
        old = self._volume
        self._volume = max(0.0, min(1.0, v))
        if self._pipe:
            self._pipe.set_property('volume', self._effective_volume())
        if int(round(self._volume * 100)) != int(round(old * 100)):
            self.sig_volume_changed.emit(int(round(self._volume * 100)))

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

    def set_viz_tables(self, ba, bb, bt, inertia, overlay_cb=None):
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
        self._viz_reset_queue()      # queued frames belong to the old mapping

    def set_viz_active(self, on: bool):
        self._viz_on = on
        self._update_spec_active()

    def set_overlay_needs_spectrum(self, on: bool):
        self._overlay_needs_spec = on
        self._update_spec_active()

    def _update_spec_active(self):
        # post-messages=false only stops delivery; audioconvert still converts
        # every buffer. A very long interval stops the element accumulating
        # samples at all, which is what actually removes the CPU cost.
        need = self._viz_on or self._overlay_needs_spec
        if self._spec_el:
            self._spec_el.set_property('post-messages', bool(need))
            # 30 fps when active, an hour (i.e. never) when not
            interval = self._SPEC_INTERVAL_NS if need else 3_600_000_000_000
            self._spec_el.set_property('interval', interval)

    def set_eq_enabled(self, enabled: bool):
        if self._eq_enabled == enabled:
            return
        self._eq_enabled = enabled
        # Rebuild the pipeline so the filters are added or removed (the chain stays
        # bit-perfect when EQ is off). _resume_with_reload rather than a bare
        # destroy+load, which races PipeWire's buffer reclaim.
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

    def _headroom_probe_grid(self, fs: float):
        """Log-spaced frequencies (Hz) to measure the EQ chain's response on.

        Spans exactly the range the EQ UI can place a band in (EQ_FREQ_MIN..
        EQ_FREQ_MAX), clamped to just under Nyquist so 44.1 kHz material doesn't
        probe past the sample rate.  Resolution is derived from the sharpest
        curve the UI can produce rather than picked: a band at EQ_Q_MAX has a
        -3 dB bandwidth of f0/Q, so its narrowest possible peak spans
        log10(1 + 1/EQ_Q_MAX) decades.  Sampling that at _PROBE_PER_PEAK points
        guarantees the peak is never missed between grid points, at any fs.
        """
        lo = EQ_FREQ_MIN
        hi = min(EQ_FREQ_MAX, fs * self._NYQUIST_MARGIN)
        if hi <= lo:
            return _np.array([lo])
        decades = _np.log10(hi / lo)
        per_decade = self._PROBE_PER_PEAK / _np.log10(1.0 + 1.0 / EQ_Q_MAX)
        n = int(max(self._PROBE_MIN_POINTS, _np.ceil(decades * per_decade)))
        return _np.logspace(_np.log10(lo), _np.log10(hi), n)

    _NYQUIST_MARGIN   = 0.4995   # fraction of fs — just inside Nyquist (0.5)
    _PROBE_PER_PEAK   = 8        # grid points across the narrowest possible peak
    _PROBE_MIN_POINTS = 64       # floor for degenerate ranges

    def _eq_headroom_db(self) -> float:
        """Attenuation (dB, >= 0) needed so the EQ chain cannot exceed 0 dBFS.

        Evaluates the actual cascaded biquad response — the same coefficients
        that go into the audioiirfilter elements — on a log frequency grid and
        returns its peak.  Summing the per-band gain sliders would be wrong in
        both directions: overlapping bands (e.g. a +8 dB peak at 10 kHz sitting
        under a +7.8 dB high shelf at 15 kHz) reinforce each other beyond either
        slider, while well-separated bands never add up at all.

        Returns 0.0 when the EQ is disabled or the chain is net-attenuating —
        cuts must not be turned into a volume boost.
        """
        if not self._eq_enabled or not self._eq_bands:
            return 0.0
        fs = float(self._current_fs or 48000)
        w = 2.0 * _np.pi * self._headroom_probe_grid(fs) / fs
        z1 = _np.exp(-1j * w)
        z2 = z1 * z1
        mag = _np.ones_like(w)
        for band in self._eq_bands:
            f0    = float(band[0])
            gain  = float(band[1])
            q     = float(band[2])
            ftype = int(band[3]) if len(band) > 3 else EQ_TYPE_PEAK
            if ftype in (EQ_TYPE_PEAK, EQ_TYPE_LOWSHELF, EQ_TYPE_HIGHSHELF) and gain == 0.0:
                continue   # bypassed in _apply_eq_to_filters_glib too
            coeffs = eq_band_coefficients(fs, f0, gain, q, ftype)
            if coeffs is None:
                continue
            b0, b1, b2, a1, a2 = coeffs
            num = b0 + b1 * z1 + b2 * z2
            den = 1.0 + a1 * z1 + a2 * z2
            with _np.errstate(divide='ignore', invalid='ignore'):
                h = _np.abs(num / den)
            mag *= _np.nan_to_num(h, nan=1.0, posinf=1.0)
        peak = float(mag.max())
        if not _np.isfinite(peak) or peak <= 1.0:
            return 0.0
        return 20.0 * _np.log10(peak)

    def _effective_preamp_linear(self) -> float:
        """Linear gain for the preamp volume element.

        This is the user's preamp minus the EQ's own peak gain, and it is the
        thing that actually stops boosted profiles from clipping: the preamp
        element sits *before* the filters, so pulling it down by the chain's
        peak means the loudest point of the EQ curve lands at 0 dBFS instead of
        well above it.  Without it a profile like ew200-flat (+8.2 dB at 10 kHz
        under a +7.8 dB shelf at 15 kHz) drives a 0 dBFS master more than 10 dB
        into the ceiling.

        Only applied when the Limiter switch is on — that switch's job is
        precisely "prevent clipping on boosted EQ bands", and gain-staging is
        how you do that without hard-clipping.  With it off the signal path is
        left exactly as the user asked for, overs and all, and the (now
        functional) brick wall is not in the chain either.

        The loudness-norm gain shares this headroom budget instead of being an
        independent offset. A loud track's negative gain already pulls the signal
        away from 0 dBFS before the EQ sees it, so subtracting the full headroom
        on top would cut twice for the same protection; a quiet track's positive
        gain needs more pulldown than the base headroom, or a boosted then
        normalised-up track still clips. Net pulldown is
        max(0, headroom + loudness_gain) either way.
        """
        db = self._preamp_db
        loud_gain = self._effective_track_gain_db() if self._loudness_norm_enabled else 0.0
        if self._limiter_enabled:
            db -= max(0.0, self._eq_headroom_db() + loud_gain)
        db += loud_gain
        return 10.0 ** (db / 20.0)

    def _effective_track_gain_db(self) -> float:
        """Loudness-norm gain for the current track: prefer the embedded
        REPLAYGAIN_TRACK_GAIN tag (self._current_track_gain_db, set in
        load()); fall back to a background on-the-fly analysis result
        (_rg_gain_cache) for untagged files — see _analyze_loudness_async."""
        if self._current_track_gain_db != 0.0:
            return self._current_track_gain_db
        return _rg_gain_cache.get(self._last_filepath, 0.0)

    def _analyze_loudness_async(self, filepath: str):
        """Kick off a background rganalysis pass for filepath if it has no
        tag-based gain and isn't already cached/in flight. Safe to call on
        every load() — the cache/in-flight checks make repeat calls free."""
        if not filepath or filepath in _rg_gain_cache or filepath in _rg_analyzing:
            return
        _rg_analyzing.add(filepath)

        def _run(fp=filepath):
            gain = _run_rganalysis(fp)
            _rg_analyzing.discard(fp)
            if gain is not None:
                _rg_gain_cache[fp] = gain
                self._sig_gain_analyzed.emit(fp, gain)
        threading.Thread(target=_run, daemon=True).start()

    def _on_gain_analyzed(self, filepath: str, gain_db: float):
        """Main thread: background analysis finished.

        Two cases:
          - load() paused-and-muted this exact load waiting for the result
            (self._awaiting_initial_gain_for) — apply the gain and resume.
          - Otherwise (e.g. loudness norm was switched on mid-playback, or
            this result arrived for a track the user has since skipped past)
            just re-apply gain if it's still the current track; the result
            always lands in _rg_gain_cache for next time regardless.
        """
        print(f'[Player] loudness analysis: {filepath!r} -> {gain_db:+.2f} dB')
        if filepath == self._awaiting_initial_gain_for:
            self._awaiting_initial_gain_for = None
            self._apply_preamp()   # bake in the now-known gain before anyone hears it
            if self._pipe and filepath == self._last_filepath:
                self._pipe.set_property('volume', self._effective_volume())
                if self._playing:
                    # Analysis beat preroll: cancel the pending pause so playback
                    # runs straight through instead of pausing and resuming.
                    self._pending_pause_pipe = None
                else:
                    self.play_pause()   # resumes from the preroll-triggered pause
            # sig_busy(False) goes last: MainWindow._on_player_busy reads
            # self._player.playing synchronously to sync the play/pause icon, and
            # that is the only thing driving the icon here. Emitting it before
            # play_pause() above leaves the icon stuck on ▶.
            self.sig_busy.emit(False)
            return
        if filepath == self._last_filepath and self._loudness_norm_enabled:
            self._apply_preamp()

    def _apply_preamp(self) -> None:
        """Push the current effective preamp gain to the live volume element.

        Logs only on an actual change, so the terminal shows exactly when — and
        by how much — the level moved, rather than one line per EQ touch.
        """
        if self._preamp_el is None:
            return
        linear = self._effective_preamp_linear()
        # audioamplify stores gain at single precision, so the value read back
        # never matches the double written. Compare after the round trip.
        self._preamp_el.set_property('amplification', linear)
        applied = self._preamp_el.get_property('amplification')
        if applied != self._last_preamp_applied:
            self._last_preamp_applied = applied
            print(f'[Player] preamp -> {20.0 * _np.log10(linear):+.2f} dB '
                  f'(user {self._preamp_db:+.1f} dB, EQ headroom '
                  f'-{self._eq_headroom_db():.2f} dB, limiter {self._limiter_enabled})')

    def set_preamp_db(self, db: float):
        """Preamp gain in dB, applied before the EQ filters (-24..+24 dB).
        Applied live via the GStreamer volume element — no pipeline reload needed."""
        db = max(-24.0, min(24.0, float(db)))
        self._preamp_db = db
        self._apply_preamp()

    def set_loudness_norm(self, enabled: bool):
        """Toggle loudness normalization: embedded REPLAYGAIN_TRACK_GAIN tag
        when present, else a background on-the-fly analysis (see
        _effective_track_gain_db / _analyze_loudness_async). Applied live via
        the same preamp element as set_preamp_db — no pipeline reload needed.
        """
        if enabled == self._loudness_norm_enabled:
            return
        self._loudness_norm_enabled = enabled
        if enabled and self._current_track_gain_db == 0.0:
            # Switched on mid-playback of an untagged track: analyse what is
            # loaded now instead of waiting for the next load().
            self._analyze_loudness_async(self._last_filepath)
        self._apply_preamp()

    def set_balance(self, balance: int):
        """Stereo balance: -100 (full left) .. 0 (centre) .. +100 (full right).
        Applied live via the GStreamer audiopanorama element — no pipeline reload needed."""
        balance = max(-100, min(100, int(balance)))
        self._balance = balance
        if self._balance_el is not None:
            self._balance_el.set_property('panorama', balance / 100.0)

    def _apply_eq_to_filters(self):
        """Update the properties of existing EQ filter elements."""
        if not self._eq_filters:
            return
        self._apply_eq_to_filters_glib()
        # The auto headroom comes from these same bands, and set_eq_bands() edits
        # them live, so a stale preamp would let the new peak clip.
        self._apply_preamp()

    def _apply_eq_to_filters_glib(self):
        if not self._eq_filters:
            return
        fs = self._current_fs
        for i, filt in enumerate(self._eq_filters):
            if i < len(self._eq_bands) and self._eq_enabled:
                band = self._eq_bands[i]
                # Bands are (freq, gain, Q) or (freq, gain, Q, type)
                f0   = float(band[0])
                gain = float(band[1])
                q    = float(band[2])
                ftype = int(band[3]) if len(band) >= 4 else EQ_TYPE_PEAK

                # Gain-using types at 0 dB do nothing, so bypass them; pass and
                # notch filters always need real coefficients.
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

    def _sync_alsa_reservation(self) -> None:
        """Keep the ALSA card reservation in step with the selected output.

        ALSA-direct: claim org.freedesktop.ReserveDevice1.Audio<N> so WirePlumber
        closes its own PCM instead of colliding with us — a collision is what
        leaves the card wedged until it is physically replugged.  Anything else
        (PipeWire/Pulse): drop the reservation so WirePlumber takes the card back
        immediately.  See alsa.py for the protocol details.

        Called from load(), so a reservation is never left held after the user
        switches back to PipeWire, and startup restore (which writes
        _alsa_device directly, bypassing set_output_device) is covered too.
        """
        if self._is_hw_device(self._alsa_device):
            alsa.acquire(self._alsa_device)
        else:
            alsa.release()

    def shutdown(self) -> None:
        """Tear down the pipeline and hand any reserved ALSA card back.

        Called from MainWindow.closeEvent.  Releasing explicitly (rather than
        relying on the D-Bus connection dying with the process) means WirePlumber
        sees NameOwnerChanged while our sink is already gone, so it re-opens the
        card on the first try.
        """
        self._destroy()
        alsa.release()

    def set_output_device(self, device_id: str):
        """Switch audio output sink.  device_id is 'pipewire' or a plughw id like
        'plughw:0,0'.  Change takes effect immediately by reloading the current
        track at the current position.  If called before any track is loaded
        (startup restore) the device is stored silently and takes effect on first play."""
        if device_id == self._alsa_device:
            return
        self._alsa_device = device_id
        print(f'[Player] output device -> {device_id}')
        if self._is_hw_device(device_id):
            # Re-probe: the device may have been replugged with other capabilities
            invalidate_alsa_rate_cache(device_id)
        else:
            # Release now, not at the next load(): with no track loaded there is
            # no next load, and the node would stay missing system-wide. wait=True
            # because the reload below needs WirePlumber's sink node to exist again.
            alsa.release(wait=True)

        if self._pipe:
            self._pipe.set_property('volume', self._effective_volume())

        if self._last_filepath:
            pos_ms = int(self.position_ms())
            self._last_switch_pos_ms      = pos_ms         # consumed by ALSA probe
            self._last_switch_was_playing = self._playing  # consumed by ALSA probe
            was_playing = self._playing
            self._destroy()
            if not self._is_hw_device(device_id):
                # Reload here for PipeWire. Any card handover already completed
                # synchronously above via release(wait=True).
                fp = self._last_filepath
                QTimer.singleShot(150, lambda: self._load_and_seek(
                    fp, pos_ms, paused=not was_playing))

    def set_pipewire_adaptive_rate(self, enabled: bool, reload: bool = True):
        """Toggle PipeWire adaptive-rate mode (see _resolve_rate_plan()).

        When enabled, the PipeWire branch requests the track's own native
        rate directly (true passthrough) whenever that rate is currently in
        PipeWire's advertised allowed-rates set — that request is what lets
        PipeWire's own adaptive mechanism retune the whole graph to match,
        instead of us always pre-matching whatever the graph already runs at.
        Only takes effect for the pipewiresink path; ALSA-direct is unaffected.

        reload=False is used for silent startup restore (mirrors
        set_output_device()'s pattern) — no pipeline rebuild, just remembers
        the flag for the first real load()/play().
        """
        if enabled == self._pipewire_adaptive_enabled:
            return
        self._pipewire_adaptive_enabled = enabled
        print(f'[Player] PipeWire adaptive rate -> {enabled}')
        if not reload or self._out != 'pipewiresink' or self._is_hw_device(self._alsa_device):
            return
        if self._last_filepath:
            pos_ms = int(self.position_ms())
            was_playing = self._playing
            self._destroy()
            fp = self._last_filepath
            QTimer.singleShot(150, lambda: self._load_and_seek(
                fp, pos_ms, paused=not was_playing))

    def _active_sink_desc(self) -> str:
        """Return the GStreamer description for the terminal sink element only.

        audioconvert/resample are handled separately in _make_sink_bin() (see
        _resolve_rate_plan()) so the soxr resampler Gst.Bin can be spliced in
        between when needed — parse_bin_from_description can't embed a Python
        Gst.Bin object inside a pipeline description string.
        """
        if self._is_hw_device(self._alsa_device):
            return f'alsasink device={self._alsa_device}'
        if self._out == 'pipewiresink':
            # resample.quality raises PipeWire's own residual resampler (the small
            # graph-rate → device-rate step left to it) from 4 to near-max.
            props = 'resample.quality=(int)10'
            mode, target_rate = self._resolve_rate_plan()
            # node.rate is what asks PipeWire to retune the graph; just sending
            # audio at a rate does not, the per-client resampler converts it.
            # Set for 'resample' too so an upsample target pulls the graph up.
            if mode == 'passthrough':
                props += f',node.rate=(string)1/{self._current_fs}'
            elif mode == 'resample' and target_rate:
                props += f',node.rate=(string)1/{target_rate}'
            return f'pipewiresink stream-properties="props,{props}"'
        return self._out  # PulseAudio / autoaudiosink fallback — unchanged

    def _resolve_rate_plan(self):
        """Decide how the sink chain should handle sample-rate conversion.

        Returns (mode, target_rate):
          ('legacy', None)      — ALSA-hw path where native-rate detection
                                   failed entirely; reproduce today's exact
                                   behavior (audioconvert ! audioresample)
                                   rather than guessing.
          ('passthrough', None) — rates already match (or this isn't an
                                   ALSA-hw/PipeWire path); audioconvert only,
                                   true bit-perfect.
          ('resample', rate)    — insert the soxr stage targeting `rate`.

        Called once per load()/device-switch from _make_sink_bin(), never per
        buffer — the ALSA/PipeWire rate probes are cached but still shell out,
        so this must never run on a hot path.
        """
        if self._is_hw_device(self._alsa_device):
            kind, rates = probe_alsa_hw_rate(self._alsa_device)
            if kind == 'discrete':
                if self._current_fs in rates:
                    return ('passthrough', None)  # exact match — e.g. a 96kHz file on a device that lists 96000
                nearest = min(rates, key=lambda r: abs(r - self._current_fs))
                return ('resample', nearest)
            if kind == 'range':
                lo, hi = rates
                if lo <= self._current_fs <= hi:
                    return ('passthrough', None)  # continuous range: file's own rate is accepted as-is
                # Outside the device's range — clamp instead of letting hw: refuse
                target = lo if self._current_fs < lo else hi
                return ('resample', target)
            return ('legacy', None)  # detection failed entirely (often a transient device-busy race)
        if self._out == 'pipewiresink':
            if self._pipewire_adaptive_enabled:
                allowed = live_pipewire_allowed_rates()
                # A missing or single-entry allowed-rates set means PipeWire has
                # not picked the opt-in drop-in up yet (it needs a restart — see
                # MainWindow._on_adaptive_rate_toggled). Requesting a rate the
                # graph cannot switch to just gets silently resampled back down,
                # so fall through to plain graph-rate matching below.
                if allowed and len(allowed) > 1:
                    # clock.allowed-rates is graph-wide and says nothing about the
                    # connected device, so cross-check the sink's own rates — else
                    # the hardware resamples again on top of our conversion.
                    sink_kind, sink_rates = live_pipewire_default_sink_rates()
                    def _device_ok(fs):
                        if sink_kind == 'discrete':
                            return fs in sink_rates
                        if sink_kind == 'range':
                            return sink_rates[0] <= fs <= sink_rates[1]
                        return True  # undetermined — don't block on missing data
                    usable = [r for r in allowed if _device_ok(r)]
                    if self._current_fs in usable:
                        # Ask for the track's own rate: PipeWire's adaptive
                        # mechanism only reacts to a stream requesting a rate
                        # other than the current graph rate, which pre-matching
                        # the graph rate below can never do.
                        return ('passthrough', None)
                    if usable:
                        # Not usable end to end — resample to the highest rate
                        # both device and graph accept (upsampling beats down).
                        return ('resample', max(usable))
            rate = live_pipewire_graph_rate()
            if rate is None:
                return ('passthrough', None)  # unknown — today's PipeWire behavior, no forced resample
            if rate == self._current_fs:
                return ('passthrough', None)
            return ('resample', rate)
        return ('passthrough', None)  # pulsesink / autoaudiosink — unchanged

    def _make_sink_bin(self):
        """Create a bin containing EQ (if any), limiter (optional),
           stereo enhancer (optional), and sink.
           The spectrum element is wired separately as audio-filter (pre-volume) in load().
           Returns (bin, list_of_eq_filter_elements)."""
        elements = []

        # Preamp: gain before the EQ chain, carrying the automatic EQ headroom.
        # audioamplify rather than `volume` because playsink hijacks any element in
        # the sink bin exposing a "volume" property and drives it from playbin's
        # own volume, overwriting the headroom on every slider move.
        self._preamp_el = None
        preamp_el = Gst.ElementFactory.make('audioamplify', 'preamp')
        if preamp_el:
            preamp_el.set_property('clipping-method', 3)  # 3 = none (plain gain)
            self._preamp_el = preamp_el
            # Fresh element — clear the remembered value so _apply_preamp reports
            self._last_preamp_applied = None
            self._apply_preamp()
            elements.append(preamp_el)
        else:
            print('[Player] audioamplify element unavailable — preamp disabled')

        # Balance: audiopanorama in simple mode pans by scaling channels without
        # downmixing to mono, so it is safe to insert unconditionally.
        self._balance_el = None
        pan_el = Gst.ElementFactory.make('audiopanorama', 'balance')
        if pan_el:
            try:
                pan_el.set_property('method', 0)  # 0 = simple (no mono downmix)
            except Exception:
                pass
            pan_el.set_property('panorama', self._balance / 100.0)
            self._balance_el = pan_el
            elements.append(pan_el)
        else:
            print('[Player] audiopanorama element unavailable — balance disabled')

        eq_bin, eq_filters = self._create_eq_bin()
        if eq_bin:
            elements.append(eq_bin)

        # Limiter: audiodynamic as a hard-knee compressor. Built here but appended
        # after the stereo-width stage, because M/S widening adds up to +6 dB and a
        # limiter ahead of it could not catch those overs.
        lim_bin = None
        if self._limiter_enabled:
            lim = Gst.ElementFactory.find('audiodynamic')
            if lim:
                lim_el = Gst.ElementFactory.make('audiodynamic', 'limiter')
                if lim_el:
                    # These enums are plain integers in the GStreamer API
                    lim_el.set_property('mode', 0)             # compressor
                    lim_el.set_property('characteristics', 0)  # hard-knee
                    # Past the threshold it computes
                    #   out = threshold + (in - threshold) * ratio
                    # so ratio is the slope above the knee, not an N:1 figure.
                    # The default 1.0 is a no-op; a brick wall is 0.0.
                    lim_el.set_property('ratio', 0.0)
                    # The threshold property is linear, the shared ceiling is dBFS
                    lim_el.set_property(
                        'threshold', 10.0 ** (LIMITER_CEILING_DBFS / 20.0))
                    # Wrapped in a bin with converters so caps survive
                    lim_bin = Gst.Bin.new('limiter_bin')
                    conv_in  = Gst.ElementFactory.make('audioconvert', 'lim_conv_in')
                    conv_out = Gst.ElementFactory.make('audioconvert', 'lim_conv_out')
                    lim_bin.add(conv_in); lim_bin.add(lim_el); lim_bin.add(conv_out)
                    conv_in.link(lim_el); lim_el.link(conv_out)
                    lim_bin.add_pad(Gst.GhostPad.new('sink', conv_in.get_static_pad('sink')))
                    lim_bin.add_pad(Gst.GhostPad.new('src',  conv_out.get_static_pad('src')))
            else:
                print('[Player] audiodynamic not found — limiter unavailable')

        # Stereo width is a mid/side matrix in numpy (_StereoWidthBin):
        #   L' = a*L + b*R  with  a = 0.5*(1+w),  b = 0.5*(1-w)
        # w < 1 narrows the image, 1 is unity, > 1 widens it. No stock element
        # fits: PyGObject cannot set audiomixer's mix-matrix at runtime,
        # parse_bin_from_description rejects mix-matrix strings, and
        # audiopanorama has no independent L/R matrix mode.
        self._stereo_el = None
        if self._stereo_enabled:
            try:
                st_bin = _StereoWidthBin(self._stereo_width)
                self._stereo_el = st_bin
                elements.append(st_bin)
                print(f'[Player] stereo width bin OK (w={self._stereo_width})')
            except Exception as e:
                print(f'[Player] stereo width bin failed: {e}')

        # Last in the chain, so it sees preamp + EQ + stereo width summed
        if lim_bin is not None:
            elements.append(lim_bin)

        # ── Sample-rate conversion stage (ALSA-direct native rate, or PipeWire
        # pre-resample to the live graph rate) — see _resolve_rate_plan().
        mode, target_rate = self._resolve_rate_plan()
        # build_resampler_stage() answers "rates are equal, insert nothing" with
        # the same None it uses for "the stage failed to build", and the branch
        # below has to treat None as fatal. Collapsing the equal-rate case to
        # passthrough here keeps those two meanings from ever colliding.
        if mode == 'resample' and target_rate == self._current_fs:
            mode, target_rate = 'passthrough', None
        print(f'[Player] rate plan: mode={mode!r} track_fs={self._current_fs} '
              f'target={target_rate} device={self._alsa_device!r}')
        if mode == 'legacy':
            ac = Gst.ElementFactory.make('audioconvert', None)
            ar = Gst.ElementFactory.make('audioresample', None)
            if ac: elements.append(ac)
            if ar: elements.append(ar)
        elif mode == 'resample':
            resamp = build_resampler_stage(self._current_fs, target_rate)
            if resamp is not None:
                elements.append(resamp)
            else:
                print('[Player] resample stage build failed')
                return None, []
        else:
            conv_el = Gst.ElementFactory.make('audioconvert', None)
            if conv_el:
                elements.append(conv_el)

        try:
            sink = Gst.parse_bin_from_description(self._active_sink_desc(), True)
            elements.append(sink)
        except Exception as e:
            print(f'[Player] sink creation failed: {e}')
            return None, []

        if len(elements) == 1:
            outer = Gst.Bin.new()
            outer.add(elements[0])
            sink_pad = elements[0].get_static_pad('sink')
            if not sink_pad:
                print('[Player] sink has no sink pad')
                return None, []
            ghost = Gst.GhostPad.new('sink', sink_pad)
            outer.add_pad(ghost)
            return outer, eq_filters

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
            # Identity coefficients — every band starts bypassed
            filt.set_property('b', [1.0, 0.0, 0.0])
            filt.set_property('a', [1.0, 0.0, 0.0])
            bin.add(filt)
            filters.append(filt)
            if prev:
                prev_src = prev.get_static_pad('src')
                this_sink = filt.get_static_pad('sink')
                prev_src.link(this_sink)
            prev = filt

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
            if self._dur_ms_cached > 0:
                pos = max(0.0, min(pos, float(self._dur_ms_cached)))
            return int(pos)
        else:
            # Paused — the anchor already holds the frozen position
            return int(self._pos_anchor_ms)

    def _destroy(self):
        was_playing = self._playing
        if self._pipe:
            # Stop polling and drop the bus reference before the teardown below,
            # so no further messages from this pipeline are dispatched.
            self._bus_timer.stop()
            self._bus = None
            # set_state(NULL) on a pipewiresink pipeline can block for seconds
            # while PipeWire's session manager tears the link down, so it runs on
            # a daemon thread. self._pipe is cleared first: nothing else may touch
            # the dying pipeline.
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
        self._viz_reset_queue()
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

        # Drop back to the slow rate once the burst is used up
        burst = self._pos_timer_burst
        if burst > 0:
            self._pos_timer_burst = burst - 1
            if self._pos_timer_burst == 0:
                self._pos_timer.setInterval(250)
        pos = self.position_ms()
        self.sig_pos.emit(pos)

        _t1 = _monotonic()
        _tick_ms = (_t1 - _t0) * 1000.0

        # Report a tick that fired well after its interval (-1.0 = first tick)
        _last = self._tick_last_wt
        _interval = self._pos_timer.interval()
        if _last >= 0.0:
            _actual_gap_ms = (_t1 - _last) * 1000.0
            if _DIAG and _actual_gap_ms > _interval + 60:
                _pt = (_t1 - self._play_start_wt)
                print(f'[DIAG][tick] play+{_pt:.3f}s  LATE FIRE: expected={_interval}ms actual={_actual_gap_ms:.1f}ms'
                      f'  tick_work={_tick_ms:.2f}ms  pos={pos}ms', flush=True)
        self._tick_last_wt = _t1

        # Schedule the combined position+duration query roughly every second
        # (every 4th tick at the 250 ms base rate). It is deferred to its own
        # event-loop slot rather than run inline so a slow query — both can block
        # under PipeWire or aggressive power management — does not stretch this
        # tick. Results arrive back through _sig_dur_gst_ms / _sig_drift_gst_ms.
        # _drift_pending keeps at most one query outstanding.
        if self._playing and self._pipe \
                and self._pos_timer_burst == 0 and not self._drift_pending:
            self._drift_pending = True
            QTimer.singleShot(1, self._drift_query_glib)


    def _drift_query_glib(self):
        """Query pipeline position (for drift) and duration if not cached yet.

        Runs in its own event-loop slot, scheduled by _tick_pos.
        """

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
                        if _DIAG and _qms > 30:
                            _pt = _query_wt - self._play_start_wt
                            print(f'[DIAG][drift_glib] play+{_pt:.3f}s  SLOW query={_qms:.1f}ms', flush=True)
                        self._sig_drift_gst_ms.emit(p / Gst.MSECOND, _query_wt)
        except Exception as _e:
            if _DIAG:
                print(f'[DIAG][drift_glib] exception: {_e}')
        finally:
            _total = (_monotonic() - _t0) * 1000.0
            if _DIAG and _total > 50:
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
        # Only queried positions can reveal a freeze: position_ms() is
        # interpolated and keeps advancing regardless. Queries arrive every
        # ~250 ms, so a 700 ms no-advance window detects a stall within ~1 s.
        if not self._reloading and not self._reload_guard:
            if self._gst_pos_adv_ms < 0:
                # First query after load/resume — initialise only
                self._gst_pos_adv_ms = gst_ms
                self._gst_pos_adv_wt = query_wt
            elif gst_ms - self._gst_pos_adv_ms > 150:   # >150 ms forward = genuine progress
                self._gst_pos_adv_ms = gst_ms
                self._gst_pos_adv_wt = query_wt
            elif (query_wt - self._gst_pos_adv_wt) > 0.7:   # frozen for >700 ms
                print(f'[Player] GST position stalled at {gst_ms:.0f} ms — reloading pipeline')
                # Reset before reloading so the next query does not race the guard
                self._gst_pos_adv_ms = gst_ms
                self._gst_pos_adv_wt = query_wt
                _fb = int(self._pos_anchor_ms)
                # A stalled pipeline is by definition one that should be playing
                self._resume_with_reload(fallback_ms=_fb, want_playing=True)

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
            # PipeWire's stream-restore can apply a stale saved volume when the
            # stream opens, silently overriding playbin's. Reset the sink input to
            # 100% once per pipeline so the slider stays in control.
            if (not getattr(self, '_stream_restore_reset', True)
                    and not self._is_hw_device(self._alsa_device)):
                self._stream_restore_reset = True
                def _reset_stream_vol():
                    # The verbose listing, not `short`: the short form has no PID
                    # column at all, so scanning it for our PID matched nothing —
                    # and when it did match it was a coincidence (a sample rate
                    # or index happening to contain the digits). The
                    # application.process.id property is the only reliable link
                    # from a sink input back to this process. LC_ALL=C keeps the
                    # 'Sink Input #' headers untranslated.
                    try:
                        out = subprocess.check_output(
                            ['pactl', 'list', 'sink-inputs'],
                            stderr=subprocess.DEVNULL, text=True,
                            env={**os.environ, 'LC_ALL': 'C'})
                    except Exception:
                        return
                    want = f'"{os.getpid()}"'
                    idx = None
                    for line in out.splitlines():
                        s = line.strip()
                        if s.startswith('Sink Input #'):
                            idx = s[len('Sink Input #'):].strip()
                        elif idx and s.startswith('application.process.id') \
                                and s.endswith(want):
                            try:
                                subprocess.run(
                                    ['pactl', 'set-sink-input-volume', idx, '100%'],
                                    stderr=subprocess.DEVNULL)
                            except Exception:
                                pass
                            return
                threading.Thread(target=_reset_stream_vol, daemon=True).start()
            # Preroll done. A load(paused=True) started PLAYING to keep the main
            # thread free; now that the sink is acquired, PAUSED is non-blocking.
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
            if self._dur_ms_cached > 0:
                self._anchor_now(float(self._dur_ms_cached))
            # Signals only — the pipeline must not be touched here. sig_end can
            # run _advance() → load() → _destroy() straight away, and anything
            # still reaching for the old pipeline then crashes.
            self.sig_playing.emit(False)
            self.sig_end.emit()
        elif msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            err_str = str(err)
            dbg_str = (dbg or '').lower()
            was_playing = self._playing   # captured before the reset below
            self._playing = False
            self._pos_playing = False
            self.sig_playing.emit(False)

            # "all buffers have been removed" (resource error 3) means PipeWire
            # reclaimed its buffers while paused — another app took the sink, a
            # Bluetooth reconnect. The pipeline is intact, so reload rather than
            # tear it down.
            _is_buffers_removed = (
                'buffers have been removed' in err_str.lower() or
                'buffers have been removed' in dbg_str or
                ('resource' in err_str.lower() and '(3)' in err_str)
            )
            if _is_buffers_removed:
                print(f'[Player] sink buffers removed — reloading pipeline: {err_str}')
                _fb = int(self._pos_anchor_ms)
                QTimer.singleShot(0, lambda: self._resume_with_reload(
                    fallback_ms=_fb, want_playing=was_playing))
                return

            # Everything else: tear down and surface the error
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
                    # ALSA xruns and underruns are transient and reloading on them
                    # loops forever. On PipeWire/Pulse a warning means real sink loss.
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
        """Queue one spectrum message's magnitudes for the renderer.

        Called from _on_msg, i.e. on the Qt main thread via _poll_bus's timer —
        the same thread as _compute_viz_frame, so the queue below needs no lock.

        Design notes:
        - serial guard: reset inertia when a new track loads mid-stream.
        - discard window: suppress the first 150 ms after load/seek to avoid
          decoding artefacts.
        - magnitude extraction: try fast GstValueList path first; fall back to
          s.to_string() parsing only when the binding doesn't expose __len__/n_values.
        """
        # ── Serial guard — new track resets inertia ───────────────────────────
        serial = self._spec_serial
        if serial != self._last_parsed_serial:
            self._last_parsed_serial = serial
            self._viz_spec[:] = MIN_DB
            self._viz_reset_queue()
            self._viz_discard_until = _monotonic() + 0.15
            return

        # ── Discard window ────────────────────────────────────────────────────
        now = _monotonic()
        if now < self._viz_discard_until:
            return

        # ── Magnitude extraction ──────────────────────────────────────────────
        # Fast path via GstValueList, avoiding a full s.to_string(). The field
        # index is cached — the layout is identical for every message.
        raw = None
        try:
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

        # Fallback: parse s.to_string() — slow but works on any binding version
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
                        raw = _np.array(txt[i1 + 1:i2].split(','),
                                        dtype=_np.float32)
            except Exception:
                pass

        if raw is None:
            return

        n = min(GST_BANDS, len(raw))
        if n <= 0:
            return

        # Each frame is queued whole instead of folded into the previous one.
        # Bursts are normal — libFLAC's ~104 ms blocks deliver three messages back
        # to back, then nothing — and merging them drops two frames in three,
        # stepping the bars at ~8 Hz. _compute_viz_frame paces the queue out again.
        w = self._viz_pend_w
        if self._viz_pend_ct >= self._VIZ_PEND_N:
            # Queue full: the renderer has been starved longer than the queue is
            # deep. Fold peak-wise into the newest frame so transients survive.
            newest = (w - 1) % self._VIZ_PEND_N
            _np.maximum(self._viz_pend[newest, :n], raw[:n], out=self._viz_pend[newest, :n])
        else:
            slot = self._viz_pend[w]
            slot[:n] = raw[:n]
            if n < GST_BANDS:
                slot[n:] = MIN_DB
            self._viz_pend_w  = (w + 1) % self._VIZ_PEND_N
            self._viz_pend_ct += 1
        self._viz_has_any = True

    def _viz_reset_queue(self):
        """Drop every queued spectrum frame (track change, seek, teardown)."""
        self._viz_pend_r  = 0
        self._viz_pend_w  = 0
        self._viz_pend_ct = 0
        self._viz_next_release = 0.0
        self._viz_ema_wt  = 0.0
        self._viz_target[:] = MIN_DB

    def _compute_viz_frame(self):
        """Main thread: called by _render_tick on every frame (60 fps).

        Drains the spectrum queue filled by _store_spectrum and produces
        smoothed, normalised bar heights published into _viz_bar_buf.

        Works in place on pre-allocated numpy buffers to keep per-frame
        allocation (and so GC pressure) down.

        Pipeline:
          1. Release at most one queued spectrum frame, paced at the spectrum
             element's own 30 Hz, then one EMA step towards it sized by the
             real elapsed time.
          2. Linear interpolation from GST_BANDS FFT bins → VIZ_BANDS display bars
          3. Clip + normalise dB to [0, 1]
          4. Power-law perceptual gamma (0.38)
          5. Publish to _viz_bar_buf

        The overlay callback is invoked by ControlBar._render_tick, not here —
        it needs the delay-ring-buffer-adjusted frame, which only exists after
        this method returns.

        Runs on every frame rather than only when a message arrived: gating it on
        arrivals ties the visible frame rate to the codec's decode block size
        (~8 fps on FLAC versus 30 on Opus).
        """
        ba = self._viz_ba
        bb = self._viz_bb
        bt = self._viz_bt
        if ba is None or bb is None or bt is None:
            return

        try:
            sp    = self._viz_spec
            bh    = self._viz_bh_pre     # (VIZ_BANDS,) work buffer
            tmp   = self._viz_tmp_pre    # (VIZ_BANDS,) work buffer
            alpha = max(0.0, min(1.0, float(self._viz_inertia)))
            now   = _monotonic()

            # ── 1a. Release one queued frame, at the spectrum's own cadence ───
            # A backlog means frames arrived faster than they were shown, so
            # drain at double rate rather than letting the lag accumulate.
            if self._viz_pend_ct > 0 and now >= self._viz_next_release:
                r = self._viz_pend_r
                _np.copyto(self._viz_target, self._viz_pend[r])
                self._viz_pend_r   = (r + 1) % self._VIZ_PEND_N
                self._viz_pend_ct -= 1
                step = self._SPEC_INTERVAL_S
                if self._viz_pend_ct >= 3:
                    step *= 0.5
                self._viz_next_release = max(now, self._viz_next_release) + step

            # ── 1b. Inertia: one EMA step, exponent scaled by elapsed time ────
            # alpha is defined per spectrum interval (1/30 s), so raising it to
            # (dt / interval) keeps the settling speed the same whatever the render
            # cadence or block size is. After a reset there is no previous
            # timestamp, so the first step counts as exactly one interval.
            dt = now - self._viz_ema_wt if self._viz_ema_wt > 0.0 else self._SPEC_INTERVAL_S
            self._viz_ema_wt = now
            exp = min(8.0, max(0.0, dt / self._SPEC_INTERVAL_S))
            if alpha <= 0.0:
                ea = 0.0
            elif alpha >= 1.0:
                ea = 1.0
            else:
                ea = alpha ** exp
            # Through a reused buffer: (1 - ea) * target allocated a fresh
            # GST_BANDS array on every one of the 60 frames per second.
            ema_t = self._viz_ema_tmp
            _np.multiply(self._viz_target, (1.0 - ea), out=ema_t)
            sp *= ea
            sp += ema_t

            # ── 2. Freq mapping: linear interpolation (GST_BANDS → VIZ_BANDS) ─
            # bh[d] = sp[ba[d]] + (sp[bb[d]] - sp[ba[d]]) * bt[d]
            # np.take with out= rather than sp[bb] / sp[ba]: fancy indexing
            # would allocate a VIZ_BANDS array per gather, twice per frame.
            _np.take(sp, bb, out=tmp)
            _np.take(sp, ba, out=bh)
            _np.subtract(tmp, bh, out=tmp)
            _np.multiply(tmp, bt, out=tmp)
            _np.add(bh, tmp, out=bh)

            # ── 3. Clip + normalise dB → [0, 1] ──────────────────────────────
            _np.clip(bh, MIN_DB, 0.0, out=bh)
            bh -= MIN_DB          # shift: [MIN_DB, 0] → [0, -MIN_DB]
            bh *= (-1.0 / MIN_DB) # scale: → [0, 1]
            _np.clip(bh, 0.0, 1.0, out=bh)

            # ── 4. Perceptual gamma ───────────────────────────────────────────
            _np.power(bh, 0.38, out=bh)

            # ── 5. Publish ─────────────────────────────────────────────────────
            _np.copyto(self._viz_bar_buf, bh)
        except Exception as _ve:
            print(f'[VizFrame] {type(_ve).__name__}: {_ve}')

# MprisServer is defined in mpris.py