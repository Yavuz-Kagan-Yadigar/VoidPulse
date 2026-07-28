"""
VoidPulse — resampler.py: soxr (libsoxr, the "SoX Resampler" library) streaming
glue for the GStreamer sink pipeline, plus a PipeWire live graph-rate lookup.

build_resampler_stage() returns a Gst.Bin/Element converting in_rate -> out_rate,
for splicing into Player._make_sink_bin() in place of the stock `audioresample`
element. Degrades to stock 'audioconvert ! audioresample' (or None on total
failure) when the `soxr` package isn't installed — callers must not assume
soxr is present.
"""
from constants import *
import re as _re
import time as _time
import numpy as _np

try:
    import soxr as _soxr
    HAVE_SOXR = True
except Exception as _e:
    _soxr = None
    HAVE_SOXR = False
    print(f'[resampler] soxr package unavailable ({_e}) — falling back to audioresample')


class SoxrResamplerBin(Gst.Bin):
    """sink -> audioconvert -> capsfilter(F32LE@in_rate) [pad probe reads +
       drops every buffer here] -> (soxr.ResampleStream, Python) -> appsrc
       (F32LE@out_rate) -> audioconvert -> src.

    Rate conversion changes the frame count, so this cannot be a passthrough
    transform the way _StereoWidthBin is: one pad cannot carry two rates. The
    bin is therefore two independently-capped halves bridged only by Python:

      input half:  ... -> capsfilter, whose src pad is left unlinked. A BUFFER
                   pad probe on that pad reads each buffer and hands it to soxr,
                   returning DROP so GStreamer never pushes to a missing peer.
      output half: appsrc (fed by the probe via push-buffer/push-sample) ->
                   audioconvert -> the bin's src ghost pad.

    A pad probe rather than an appsink on the input half: inside a nested bin,
    appsink delivers the first buffer through both 'new-preroll' and
    'new-sample', which double-counts it and inflates the output length.
    """

    def __init__(self, in_rate: int, out_rate: int, quality: str = 'VHQ'):
        super().__init__()
        self._in_rate  = int(in_rate)
        self._out_rate = int(out_rate)
        self._quality  = quality
        self._channels  = None
        self._stream    = None          # soxr.ResampleStream, built on the first buffer
        self._out_frames_pushed = 0     # frames since _pts_base
        self._eos_forwarded = False
        self._out_caps  = None
        # Seek tracking. FLUSH and SEGMENT events die on the capsfilter's unlinked
        # src pad, so _on_event mirrors them onto the appsrc half by hand; without
        # that the output timeline just counts frames since the bin was built.
        self._segment   = None          # latest upstream Gst.Segment, or None
        self._pts_base  = None          # output pts of the first frame of this segment
        self._duration_synced = False   # track length pushed onto appsrc yet?

        conv_in    = Gst.ElementFactory.make('audioconvert', None)
        capsfilter = Gst.ElementFactory.make('capsfilter', None)
        appsrc     = Gst.ElementFactory.make('appsrc', None)
        conv_out   = Gst.ElementFactory.make('audioconvert', None)
        if not all((conv_in, capsfilter, appsrc, conv_out)):
            raise RuntimeError('SoxrResamplerBin: required elements unavailable')
        self._appsrc = appsrc

        # Forcing F32LE matters because conv_in's src pad has no peer to negotiate
        # with: audioconvert would otherwise pass the input format straight through
        # and the probe would misread the bytes. Channels stay unconstrained.
        in_caps = Gst.Caps.from_string(
            f'audio/x-raw,format=F32LE,layout=interleaved,rate={self._in_rate}')
        capsfilter.set_property('caps', in_caps)

        # appsrc caps must be fully fixed before the first push, and the channel
        # count is unknown until a buffer arrives, so _ensure_stream() sets them.
        appsrc.set_property('format', Gst.Format.TIME)
        appsrc.set_property('is-live', False)
        appsrc.set_property('block', True)   # backpressure rather than dropping
        # Lets a sample carrying a new segment retime the branch, which is how a
        # seek target crosses the Python bridge.
        appsrc.set_property('handle-segment-change', True)

        for el in (conv_in, capsfilter, appsrc, conv_out):
            self.add(el)
        conv_in.link_filtered(capsfilter, in_caps)
        appsrc.link(conv_out)

        cf_src = capsfilter.get_static_pad('src')
        cf_src.add_probe(Gst.PadProbeType.BUFFER, self._on_buffer)
        # EVENT_FLUSH is a separate mask from EVENT_DOWNSTREAM, and FLUSH_STOP —
        # the event saying the soxr history is now stale — only arrives with it.
        cf_src.add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM | Gst.PadProbeType.EVENT_FLUSH,
                         self._on_event)
        # Upstream events, seeks above all, stop dead at appsrc because it is a
        # source with nothing above it. Relayed by hand, or a seek never reaches
        # the decoder and playback just carries on.
        appsrc.get_static_pad('src').add_probe(
            Gst.PadProbeType.EVENT_UPSTREAM, self._on_upstream_event)

        self.add_pad(Gst.GhostPad.new('sink', conv_in.get_static_pad('sink')))
        self.add_pad(Gst.GhostPad.new('src',  conv_out.get_static_pad('src')))

    def _ensure_stream(self, channels: int):
        if self._stream is None or self._channels != channels:
            self._channels = channels
            self._stream = _soxr.ResampleStream(
                self._in_rate, self._out_rate, channels,
                dtype='float32', quality=self._quality)
            fixed_out_caps = Gst.Caps.from_string(
                f'audio/x-raw,format=F32LE,layout=interleaved,'
                f'rate={self._out_rate},channels={channels}')
            self._out_caps = fixed_out_caps
            self._appsrc.set_property('caps', fixed_out_caps)

    def _on_buffer(self, pad, info):
        buf = info.get_buffer()
        if buf is None:
            return Gst.PadProbeReturn.DROP
        caps = pad.get_current_caps()
        channels = caps.get_structure(0).get_int('channels')[1] if caps else 0
        if channels <= 0:
            return Gst.PadProbeReturn.DROP
        ok, rmap = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.PadProbeReturn.DROP
        try:
            data = _np.frombuffer(rmap.data, dtype=_np.float32).copy()
        finally:
            buf.unmap(rmap)
        if data.size == 0:
            return Gst.PadProbeReturn.DROP
        n_frames = data.size // channels
        arr = data[: n_frames * channels].reshape(n_frames, channels)
        self._ensure_stream(channels)
        if not self._duration_synced:
            self._sync_duration()
        if self._pts_base is None:
            # Anchored to the segment's first buffer, so a seek to 60 s produces
            # output stamped from 60 s rather than continuing the old count.
            self._pts_base = (buf.pts if buf.pts != Gst.CLOCK_TIME_NONE
                              else (self._segment.start if self._segment else 0))
        try:
            out = self._stream.resample_chunk(arr, last=False)
        except Exception as e:
            print(f'[resampler] resample_chunk error: {e}')
            return Gst.PadProbeReturn.DROP
        self._push_output(out)
        return Gst.PadProbeReturn.DROP   # this pad has no peer to push to

    def _on_upstream_event(self, pad, info):
        """Relay a seek from appsrc's src pad to the real upstream chain.

        Only SEEK: QOS, LATENCY and RECONFIGURE concern the branch appsrc feeds
        and mean nothing on the far side of a rate change.
        """
        ev = info.get_event()
        if ev.type != Gst.EventType.SEEK:
            return Gst.PadProbeReturn.OK
        sink_pad = self.get_static_pad('sink')
        if sink_pad is None:
            return Gst.PadProbeReturn.OK
        # Dropped either way: appsrc answering a seek it cannot service would tell
        # the caller it succeeded.
        if not sink_pad.push_event(ev.copy()):
            print('[resampler] upstream seek was refused')
        return Gst.PadProbeReturn.DROP

    def _mirror_flush(self, ev):
        """Flush the appsrc half too, so no stale audio survives a seek.

        send_event rather than a pad push: GstBaseSrc's own handler is what pauses
        the streaming task on FLUSH_START and restarts it on FLUSH_STOP. Pushing
        at the pad would pause the task with nothing left to restart it.
        """
        try:
            self._appsrc.send_event(ev)
        except Exception as e:
            print(f'[resampler] flush mirror failed: {e}')

    def _sync_duration(self):
        """Copy the track length from upstream onto appsrc.

        A duration query hits the same dead end a seek does, so appsrc would answer
        "unknown" for the whole track. It cannot be asked across the bridge, so it
        is told instead, once per segment. Resampling changes the frame count but
        not the running time, so the value transfers unchanged.
        """
        sink_pad = self.get_static_pad('sink')
        if sink_pad is None:
            return
        ok, dur = sink_pad.peer_query_duration(Gst.Format.TIME)
        if ok and dur > 0:
            self._appsrc.set_property('duration', dur)
        self._duration_synced = True

    def _on_event(self, pad, info):
        ev = info.get_event()
        if ev.type == Gst.EventType.FLUSH_START:
            self._mirror_flush(Gst.Event.new_flush_start())
            return Gst.PadProbeReturn.OK
        if ev.type == Gst.EventType.FLUSH_STOP:
            self._mirror_flush(Gst.Event.new_flush_stop(True))
            # A flushing seek landed: the soxr history belongs to the old position.
            # The SEGMENT that follows re-anchors the timeline.
            if self._stream is not None:
                try:
                    self._stream.clear()
                except Exception as e:
                    print(f'[resampler] stream clear failed: {e}')
            self._pts_base = None
            self._out_frames_pushed = 0
            self._eos_forwarded = False   # a seek out of EOS must be able to run on
            return Gst.PadProbeReturn.OK
        if ev.type == Gst.EventType.SEGMENT:
            # Carried to appsrc with the next sample, which is what makes
            # query_position report the seek target.
            self._segment = ev.parse_segment()
            self._pts_base = None
            self._out_frames_pushed = 0
            return Gst.PadProbeReturn.OK
        if ev.type == Gst.EventType.EOS:
            if self._stream is not None and self._channels:
                try:
                    tail = self._stream.resample_chunk(
                        _np.zeros((0, self._channels), dtype=_np.float32), last=True)
                    self._push_output(tail)
                except Exception as e:
                    print(f'[resampler] flush error: {e}')
            if not self._eos_forwarded:
                self._eos_forwarded = True
                self._appsrc.emit('end-of-stream')
            return Gst.PadProbeReturn.DROP   # appsrc emits EOS instead
        return Gst.PadProbeReturn.OK

    def _push_output(self, out_arr):
        if out_arr is None or len(out_arr) == 0:
            return
        n_frames = out_arr.shape[0]
        gbuf = Gst.Buffer.new_wrapped(_np.ascontiguousarray(out_arr, dtype=_np.float32).tobytes())
        base = self._pts_base or 0
        gbuf.pts      = int(base + self._out_frames_pushed * Gst.SECOND / self._out_rate)
        gbuf.duration = int(n_frames * Gst.SECOND / self._out_rate)
        self._out_frames_pushed += n_frames
        if self._segment is not None and self._out_caps is not None:
            # push-sample carries the upstream segment with it, so appsrc re-emits
            # it downstream after a seek instead of keeping the original.
            sample = Gst.Sample.new(gbuf, self._out_caps, self._segment, None)
            ret = self._appsrc.emit('push-sample', sample)
        else:
            ret = self._appsrc.emit('push-buffer', gbuf)
        # FLUSHING is normal while a seek's flush is in flight
        if ret not in (Gst.FlowReturn.OK, Gst.FlowReturn.FLUSHING):
            print(f'[resampler] push -> {ret}')


def build_resampler_stage(in_rate: int, out_rate: int):
    """in_rate -> out_rate Gst.Bin/Element, or None if equal (caller inserts
    nothing for true passthrough). Uses soxr VHQ when available; falls back to
    stock 'audioconvert ! audioresample'; returns None only if even that fails
    to build (caller must then abort sink construction, same as any other
    sink-build failure)."""
    if in_rate == out_rate:
        return None
    if HAVE_SOXR:
        try:
            return SoxrResamplerBin(in_rate, out_rate)
        except Exception as e:
            print(f'[resampler] soxr bin failed ({e}) — falling back to audioresample')
    try:
        return Gst.parse_bin_from_description('audioconvert ! audioresample', True)
    except Exception as e:
        print(f'[resampler] audioresample fallback failed: {e}')
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  PipeWire live graph-rate lookup
# ══════════════════════════════════════════════════════════════════════════════
# Lets the soxr stage target the rate the graph is actually running at, so
# PipeWire's own per-client resampler becomes a passthrough instead of stacking a
# second, lower-quality conversion on top.
_PW_RATE_RE = _re.compile(r"key:'clock\.rate'\s+value:'(\d+)'")
_PW_RATE_CACHE_TTL_S = 5.0   # the graph rate can change while running
_pw_rate_cache = (None, 0.0)   # (rate, time of last probe)


def live_pipewire_graph_rate(timeout_s: float = 1.5):
    """Return PipeWire's current running graph/quantum rate (Hz), or None if
    it can't be determined (pw-metadata missing, PipeWire not running, etc.)."""
    global _pw_rate_cache
    rate, last_t = _pw_rate_cache
    now = _time.monotonic()
    if now - last_t < _PW_RATE_CACHE_TTL_S:
        return rate
    rate = None
    try:
        out = subprocess.run(
            ['pw-metadata', '-n', 'settings', '0', 'clock.rate'],
            capture_output=True, text=True, timeout=timeout_s).stdout
        m = _PW_RATE_RE.search(out or '')
        if m:
            rate = int(m.group(1))
    except Exception as e:
        print(f'[resampler] pw-metadata query failed: {e}')
    _pw_rate_cache = (rate, now)
    return rate


def invalidate_pipewire_rate_cache():
    global _pw_rate_cache
    _pw_rate_cache = (None, 0.0)


# ── PipeWire default-sink native-rate lookup ────────────────────────────────
# clock.allowed-rates is graph-wide and says nothing about the connected device:
# a DAC limited to 44.1/48/96 kHz is offered whatever the config lists, and asking
# for anything else makes the hardware resample on top of our conversion. Returns
# the same (kind, rates) shape as alsa.probe_alsa_hw_rate().
_PW_DEFAULT_SINK_ID_RE = _re.compile(r'^[^\n]*\*\s*(\d+)\.\s', _re.MULTILINE)
_PW_RATE_PROP_RE = _re.compile(
    r"Format:Audio:rate.*?\n\s*Choice: type (Spa:Enum:Choice:\w+).*?\n"
    r"((?:\s*Int -?\d+\n)+)", _re.DOTALL)
_PW_SINK_RATE_CACHE_TTL_S = 5.0
_pw_sink_rate_cache = (None, None, 0.0)


def live_pipewire_default_sink_rates(timeout_s: float = 1.5):
    """Return (kind, rates) for PipeWire's current default sink node, in the
    same shape as alsa.probe_alsa_hw_rate():

      ('discrete', (44100, 48000, 96000))  — exactly these rates
      ('range', (lo, hi))                  — any integer rate in [lo, hi]
      (None, None)                         — undetermined (no default sink,
                                              wpctl/pw-cli missing, parse miss)

    Callers must treat (None, None) as unknown, not as "accepts anything"."""
    global _pw_sink_rate_cache
    kind, rates, last_t = _pw_sink_rate_cache
    now = _time.monotonic()
    if now - last_t < _PW_SINK_RATE_CACHE_TTL_S:
        return kind, rates
    kind, rates = None, None
    try:
        wp_out = subprocess.run(
            host_cmd('wpctl', 'status'), capture_output=True, text=True,
            timeout=timeout_s).stdout or ''
        audio_section = wp_out.split('Audio')[1] if 'Audio' in wp_out else ''
        video_section = audio_section.split('Video')[0] if 'Video' in audio_section else audio_section
        sinks_section = video_section.split('Sinks:')[1] if 'Sinks:' in video_section else ''
        sinks_section = sinks_section.split('Sources:')[0] if 'Sources:' in sinks_section else sinks_section
        m = _PW_DEFAULT_SINK_ID_RE.search(sinks_section)
        if m:
            pod_out = subprocess.run(
                ['pw-cli', 'enum-params', m.group(1), 'EnumFormat'],
                capture_output=True, text=True, timeout=timeout_s).stdout or ''
            rm = _PW_RATE_PROP_RE.search(pod_out)
            if rm:
                nums = [int(x) for x in _re.findall(r'-?\d+', rm.group(2))]
                if nums:
                    if rm.group(1) == 'Spa:Enum:Choice:Range':
                        kind, rates = 'range', (min(nums), max(nums))
                    else:
                        kind, rates = 'discrete', tuple(sorted(set(nums)))
    except Exception as e:
        print(f'[resampler] live_pipewire_default_sink_rates failed: {e}')
    _pw_sink_rate_cache = (kind, rates, now)
    return kind, rates


def invalidate_pipewire_sink_rate_cache():
    global _pw_sink_rate_cache
    _pw_sink_rate_cache = (None, None, 0.0)


# ── PipeWire adaptive-rate allowed-set lookup ───────────────────────────────
# Only meaningful once the opt-in drop-in is active and PipeWire has restarted to
# pick it up. A stream requesting a rate from this set can make PipeWire retune
# the whole graph instead of resampling it down to the current rate.
_PW_ALLOWED_RATES_RE = _re.compile(r"key:'clock\.allowed-rates'\s+value:'([^']*)'")
_PW_ALLOWED_RATES_CACHE_TTL_S = 5.0
_pw_allowed_rates_cache = (None, 0.0)


def live_pipewire_allowed_rates(timeout_s: float = 1.5):
    """Return a sorted tuple of PipeWire's currently allowed adaptive graph
    rates (Hz), or None if undetermined/adaptive-rate isn't configured."""
    global _pw_allowed_rates_cache
    rates, last_t = _pw_allowed_rates_cache
    now = _time.monotonic()
    if now - last_t < _PW_ALLOWED_RATES_CACHE_TTL_S:
        return rates
    rates = None
    try:
        out = subprocess.run(
            ['pw-metadata', '-n', 'settings', '0', 'clock.allowed-rates'],
            capture_output=True, text=True, timeout=timeout_s).stdout
        m = _PW_ALLOWED_RATES_RE.search(out or '')
        if m:
            nums = tuple(sorted(int(x) for x in _re.findall(r'\d+', m.group(1))))
            rates = nums if nums else None
    except Exception as e:
        print(f'[resampler] pw-metadata allowed-rates query failed: {e}')
    _pw_allowed_rates_cache = (rates, now)
    return rates


def invalidate_pipewire_allowed_rates_cache():
    global _pw_allowed_rates_cache
    _pw_allowed_rates_cache = (None, 0.0)
