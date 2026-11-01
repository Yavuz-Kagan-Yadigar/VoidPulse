"""
VoidPulse — audio helpers used by the player pipeline.

_StereoWidthBin is a Gst.Bin applying mid/side stereo-width processing to
interleaved F32LE stereo. _run_rganalysis() computes a ReplayGain track gain
for files that carry no REPLAYGAIN_TRACK_GAIN tag.

measure_probe_headroom_db() measures the transient (time-domain) peak gain of
an EQ band chain by pushing a deterministic full-scale probe through the same
audioiirfilter elements the playback chain uses.

Kept out of player.py so the pipeline code there stays readable; all are
independent of any Player instance.
"""
from constants import *
from time import monotonic as _monotonic
import numpy as _np
import eq_filters as _eqfilt
from gi.repository import Gst as _Gst


class _StereoWidthBin(Gst.Bin):
    """Mid/side stereo width processing on interleaved F32LE stereo.

    Ghost pads let it stand in for a regular element anywhere in a chain.
    """

    def __init__(self, width: int = 50):
        super().__init__()
        self._width = max(-100, min(100, width))
        # Guards against the push below re-entering this same callback. A
        # plain flag is far cheaper than detaching and reattaching the pad
        # probe for every single buffer.
        self._pushing = False

        # Reusable work buffers, grown on demand. PyGObject never hands back a
        # writable mapping (neither a pad probe's buffer nor a freshly
        # allocated one), so the samples cannot be rewritten where they lie —
        # but processing straight from the source into a reused output array
        # keeps the per-buffer cost to the single unavoidable tobytes() copy.
        self._scratch_m   = _np.empty(0, dtype=_np.float32)
        self._scratch_s   = _np.empty(0, dtype=_np.float32)
        self._scratch_out = _np.empty(0, dtype=_np.float32)

        # audioconvert (force F32LE) → identity → audioconvert (back to the
        # original format). A pad probe on identity intercepts each buffer and
        # rewrites it in Python; width processing keeps the frame count and rate,
        # so no appsrc/appsink split is needed.
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

        # Ghost pads let the bin stand in for a plain element
        self.add_pad(Gst.GhostPad.new('sink', self._conv_in.get_static_pad('sink')))
        self.add_pad(Gst.GhostPad.new('src',  self._conv_out.get_static_pad('src')))

        # Buffer probe on identity's src pad does the actual processing
        self._src_pad  = self._identity.get_static_pad('src')
        self._probe_id = self._src_pad.add_probe(Gst.PadProbeType.BUFFER, self._on_buffer)

    def set_width(self, width: int):
        self._width = max(-100, min(100, width))

    def _process(self, src, w: float):
        """Apply the width matrix to interleaved F32 stereo, returning the output.

        The a*L+b*R matrix is equivalent to its mid/side form — with
        M = (L+R)/2 and S = w*(L-R)/2, the outputs are L' = M+S and R' = M-S.
        Both outputs come from two scratch rows, so the read-only source is
        never copied and neither channel needs a defensive copy before being
        written. Returns a view of a reused buffer, valid until the next call.
        """
        if src.size < 2 or src.size % 2 != 0:
            return None
        n = src.size // 2
        if self._scratch_m.size < n:
            self._scratch_m = _np.empty(n, dtype=_np.float32)
            self._scratch_s = _np.empty(n, dtype=_np.float32)
        if self._scratch_out.size < src.size:
            self._scratch_out = _np.empty(src.size, dtype=_np.float32)

        m = self._scratch_m[:n]
        s = self._scratch_s[:n]
        src_st = src.reshape(-1, 2)
        L = src_st[:, 0]
        R = src_st[:, 1]
        _np.add(L, R, out=m)
        m *= 0.5
        _np.subtract(L, R, out=s)
        s *= 0.5 * w

        out = self._scratch_out[:src.size]
        out_st = out.reshape(-1, 2)
        _np.add(m, s, out=out_st[:, 0])
        _np.subtract(m, s, out=out_st[:, 1])
        return out

    def _on_buffer(self, pad, info):
        if self._pushing:
            return Gst.PadProbeReturn.OK
        buf = info.get_buffer()
        if buf is None:
            return Gst.PadProbeReturn.OK
        w = (self._width + 100) / 100.0   # -100 → mono, 0 → unity, +100 → widest

        # Unity (width 0) means a == 1 and b == 0, so the matrix is a no-op
        if abs(w - 1.0) < 2e-6:
            return Gst.PadProbeReturn.OK

        result, rmap = buf.map(Gst.MapFlags.READ)
        if not result:
            return Gst.PadProbeReturn.OK
        try:
            # frombuffer over the mapping directly — the samples are read but
            # never written, so the read-only view costs nothing to make.
            src = _np.frombuffer(rmap.data, dtype=_np.float32)
            out = self._process(src, w)
            if out is None:
                return Gst.PadProbeReturn.OK
            out_bytes = out.tobytes()
        finally:
            buf.unmap(rmap)

        # Wrap the processed samples in a new buffer, carrying the original
        # timing metadata. The probe is detached across pad.push() so the push
        # does not re-enter this callback, then reattached.
        new_buf = Gst.Buffer.new_wrapped(out_bytes)
        if new_buf is None:
            return Gst.PadProbeReturn.OK
        new_buf.pts      = buf.pts
        new_buf.dts      = buf.dts
        new_buf.pts = buf.pts
        new_buf.dts = buf.dts
        new_buf.duration = buf.duration
        new_buf.offset = buf.offset
        new_buf.offset_end = buf.offset_end
        # Carry the buffer flags too (DISCONT/GAP/DELTA_UNIT/...), or gapless
        # and segment handling regress whenever stereo width is on.
        new_buf.set_flags(buf.mini_object.flags)

        self._pushing = True
        try:
            pad.push(new_buf)
        finally:
            self._pushing = False
        return Gst.PadProbeReturn.DROP


# Loudness-analysis results, shared by the Player thread and the batch
# fetch workers. Deliberately unlocked: every use is a single-key
# membership test, get, add, discard or assignment, all of which are
# atomic under the GIL. Nothing ever iterates these containers, so the
# dict-changed-during-iteration crash that forced a lock on
# _cover_cache cannot happen here.
_rg_gain_cache: dict = {} # filepath → gain in dB
_rg_analyzing: set = set() # analyses currently in flight


def _run_rganalysis(filepath: str, timeout_s: float = 30.0):
    """Return the track's gain in dB, or None. Blocks; background threads only.

    None also covers a missing element, a file that fails to decode, and a
    pipeline that produces nothing within timeout_s.
    """
    pipeline = Gst.Pipeline.new('rg-analysis')
    src  = Gst.ElementFactory.make('filesrc', None)
    dec  = Gst.ElementFactory.make('decodebin', None)
    conv = Gst.ElementFactory.make('audioconvert', None)
    rs   = Gst.ElementFactory.make('audioresample', None)
    rg   = Gst.ElementFactory.make('rganalysis', None)
    sink = Gst.ElementFactory.make('fakesink', None)
    if not all((pipeline, src, dec, conv, rs, rg, sink)):
        print('[Player] loudness analysis: required elements unavailable (gst-plugins-good?)')
        return None
    src.set_property('location', filepath)   # a property, so no escaping worries
    rg.set_property('num-tracks', 1)
    rg.set_property('message', True)
    sink.set_property('sync', False)
    for el in (src, dec, conv, rs, rg, sink):
        pipeline.add(el)
    src.link(dec)
    conv.link(rs); rs.link(rg); rg.link(sink)

    def _on_pad_added(_element, pad):
        # decodebin's src pad appears only once it knows the stream type
        sinkpad = conv.get_static_pad('sink')
        if not sinkpad.is_linked():
            pad.link(sinkpad)
    dec.connect('pad-added', _on_pad_added)

    bus = pipeline.get_bus()
    pipeline.set_state(Gst.State.PLAYING)
    gain = None
    try:
        deadline = _monotonic() + timeout_s
        while True:
            remaining = deadline - _monotonic()
            if remaining <= 0:
                print(f'[Player] loudness analysis timed out: {filepath!r}')
                break
            msg = bus.timed_pop_filtered(
                int(remaining * Gst.SECOND),
                Gst.MessageType.TAG | Gst.MessageType.EOS | Gst.MessageType.ERROR)
            if msg is None:
                print(f'[Player] loudness analysis timed out: {filepath!r}')
                break
            if msg.type == Gst.MessageType.TAG:
                ok, g = msg.parse_tag().get_double('replaygain-track-gain')
                if ok:
                    gain = g
            elif msg.type == Gst.MessageType.ERROR:
                err, _dbg = msg.parse_error()
                print(f'[Player] loudness analysis failed for {filepath!r}: {err}')
                break
            elif msg.type == Gst.MessageType.EOS:
                break
    finally:
        pipeline.set_state(Gst.State.NULL)
    return gain


# ── EQ transient-overshoot probe ──────────────────────────────────────────────
#
# The steady-state peak of the EQ's magnitude response (what _eq_headroom_db
# computes in player.py) does not bound its *sample* gain. For an LTI filter,
# sup|y| ≤ sup|x| · ||h||₁, and ||h||₁ can exceed |H(ω)|max when broadband
# energy and ringing accumulate: a decaying kick under a bass shelf, or a snare
# under a wide treble boost, produce peaks several tenths of a dB up to a
# couple of dB past the steady-state bound. Those samples are precisely what a
# hard ceiling (the audiodynamic brickwall, or the integer conversion's clamp)
# flat-lines — so with a steady-state-only headroom they ride just past the
# ceiling on every hit, which reads to the ear as diminished punch.
#
# This probe pushes a deterministic full-scale signal (impulse train, broadband
# pink noise, and a decaying sine burst on each boosted band's centre) through
# the very same audioiirfilter elements the playback chain uses, so the
# measurement inherits the real chain's per-sample F32 precision, and adds the
# measured sample-domain peak on top of the frequency-domain one.

_PROBE_BAND_CACHE = {}   # (fs, rounded band tuple) → measured overshoot dB


def _probe_segments(fs: float, bands):
    """Deterministic probe segments, each normalised to ≤ 0.999 amplitide.

    Returns a single mono float64 array. Three classes, because the peak gain
    of the cascade depends on the input direction in which the filter is
    excited: broadband (pink noise), periodic impulses (transient piling) and
    the sustained-to-dying sine on every boosted band's centre (the strongest
    realistic single-band excitation)."""
    segs = []

    # Impulse train: 40 full-scale impulses per second (kick-peak cadence).
    n = int(0.30 * fs)
    x = _np.zeros(n)
    x[::max(1, int(fs // 40))] = 1.0
    x[fs // 8: fs // 8 + 400] += _np.sin(2 * _np.pi * 1000 * _np.arange(400) / fs)
    segs.append(x)

    # Pink-ish noise: full-scale broadband with most energy below ~1 kHz, the
    # direction shelving boosts live in.
    rng = _np.random.default_rng(0x5EED)
    n = int(1.0 * fs)
    pink = _np.convolve(rng.standard_normal(n), _np.exp(-_np.arange(50) / 12.0), 'same')
    pink -= pink.mean()
    if _np.abs(pink).max() > 0:
        pink *= 0.999 / _np.abs(pink).max()
    segs.append(pink)

    # One decaying burst per boost band: fast transient attack, short punch
    # tail plus a slower body — the two timescales a kick/snare really has.
    t = _np.arange(int(0.35 * fs))
    env = ((1.0 - _np.exp(-t / (0.0025 * fs))) * _np.exp(-t / (0.05 * fs))
           + 0.3 * _np.exp(-t / (0.25 * fs)))
    for band in bands:
        f0, gain = float(band[0]), float(band[1])
        ftype = int(band[3]) if len(band) > 3 else EQ_TYPE_PEAK
        if gain <= 0.0 or ftype not in (EQ_TYPE_PEAK, EQ_TYPE_LOWSHELF, EQ_TYPE_HIGHSHELF):
            continue
        if f0 >= fs * 0.4995:
            continue
        burst = _np.sin(2 * _np.pi * f0 * t / fs) * env
        burst *= 0.999 / _np.abs(burst).max()
        segs.append(burst)

    gap = _np.zeros(int(0.02 * fs))
    out = []
    for seg in segs:
        out.append(gap)
        out.append(seg)
    return _np.concatenate(out)


def measure_probe_headroom_db(bands, fs, timeout_s: float = 2.0):
    """Sample-domain peak gain (dB, >= 0) of the EQ chain on transient-like
    input, measured through the real audioiirfilter elements.

    Returns None when the measurement is unavailable (a filter element is
    missing, or the run timed out inside timeout_s) or plainly bogus (zero),
    so callers fall back to the frequency-domain headroom instead of applying
    none at all.
    """
    bands = tuple(bands)
    if not bands:
        return 0.0
    fs = int(fs)
    key = (fs, tuple((round(float(b[0]), 2), round(float(b[1]), 2),
                      round(float(b[2]), 2),
                      int(b[3]) if len(b) > 3 else EQ_TYPE_PEAK)
                     for b in bands))
    cached = _PROBE_BAND_CACHE.get(key)
    if cached is not None:
        return cached

    mono = _probe_segments(fs, bands)
    data = _np.ascontiguousarray(_np.stack([mono, mono], axis=1), dtype=_np.float32).tobytes()

    pipeline = _Gst.Pipeline.new('eq-probe')
    src = _Gst.ElementFactory.make('appsrc', 'probe_src')
    appsrc_caps = _Gst.Caps.from_string(
        f'audio/x-raw,format=F32LE,layout=interleaved,rate={fs},channels=2')
    if src is not None:
        src.set_property('caps', appsrc_caps)
        src.set_property('format', 2)   # GST_FORMAT_TIME: PTS in buffers below
        pipeline.add(src)
    idn = _Gst.ElementFactory.make('identity', 'probe_tap')
    snk = _Gst.ElementFactory.make('fakesink', 'probe_sink')
    if src is None or idn is None or snk is None:
        pipeline.set_state(_Gst.State.NULL)
        return None

    filters = []
    for i, band in enumerate(bands):
        f0    = float(band[0])
        gain  = float(band[1])
        q     = float(band[2])
        ftype = int(band[3]) if len(band) > 3 else EQ_TYPE_PEAK
        if ftype in (EQ_TYPE_PEAK, EQ_TYPE_LOWSHELF, EQ_TYPE_HIGHSHELF) and gain == 0.0:
            continue
        filt = _Gst.ElementFactory.make('audioiirfilter', f'probe_filter_{i}')
        if filt is None:
            pipeline.set_state(_Gst.State.NULL)
            return None
        coeffs = _eqfilt.eq_band_coefficients(fs, f0, gain, q, ftype)
        if coeffs is None:
            continue
        b0, b1, b2, a1, a2 = coeffs
        filt.set_property('b', [b0, b1, b2])
        filt.set_property('a', [1.0, a1, a2])
        filters.append(filt)

    snk.set_property('sync', False)
    pipeline.add(idn)
    pipeline.add(snk)
    if not filters:
        # No active band — the chain is identity; transient headroom is nil.
        pipeline.set_state(_Gst.State.NULL)
        _PROBE_BAND_CACHE[key] = 0.0
        return 0.0
    tail = src
    for filt in filters:
        pipeline.add(filt)
        tail.link(filt)
        tail = filt
    tail.link(idn)
    idn.link(snk)

    peak = 0.0
    def _on_buffer(pad, info):
        nonlocal peak
        buf = info.get_buffer()
        if buf is None:
            return _Gst.PadProbeReturn.OK
        result, rmap = buf.map(_Gst.MapFlags.READ)
        if result and rmap.data:
            samples = _np.frombuffer(bytes(rmap.data), dtype=_np.float32)
            peak = max(peak, float(_np.abs(samples).max()))
        buf.unmap(rmap)
        return _Gst.PadProbeReturn.OK
    idn.get_static_pad('src').add_probe(_Gst.PadProbeType.BUFFER, _on_buffer)

    result = None
    try:
        pipeline.set_state(_Gst.State.PLAYING)
        stride = max(1, len(data) // 8)   # ~1/8 s chunks: few big buffers, fast push
        # stride must stay stereo-frame aligned: 2 ch × 4 B = 8 bytes per frame
        stride -= stride % 8
        pts = 0
        for i in range(0, len(data), stride):
            chunk = data[i:i + stride]
            if len(chunk) < 8:
                continue
            frames = len(chunk) / 8
            buf = _Gst.Buffer.new_wrapped(chunk)
            buf.pts = pts
            buf.duration = int(frames / fs * _Gst.SECOND)
            pts += buf.duration
            src.emit('push-buffer', buf)
        src.emit('end-of-stream')

        deadline = _monotonic() + timeout_s
        bus = pipeline.get_bus()
        while _monotonic() < deadline:
            msg = bus.timed_pop_filtered(
                int(0.05 * _Gst.SECOND),
                _Gst.MessageType.EOS | _Gst.MessageType.ERROR)
            if msg is None:
                continue
            if msg.type == _Gst.MessageType.ERROR:
                err, _dbg = msg.parse_error()
                print(f'[Player] EQ probe: {err}')
                break
            result = peak   # EOS reached with no error
            break
    finally:
        pipeline.set_state(_Gst.State.NULL)

    if result is None or result <= 0.0 or not _np.isfinite(result):
        return None
    db = max(0.0, 20.0 * _np.log10(result))
    _PROBE_BAND_CACHE[key] = db
    # Keep the cache bounded: one entry per persistent band configuration is
    # the norm, but dragging sliders generates thousands. Cheap generational
    # reset keeps memory flat at the cost of one re-measure after the reset.
    if len(_PROBE_BAND_CACHE) > 64:
        _PROBE_BAND_CACHE.clear()
        _PROBE_BAND_CACHE[key] = db
    return db
