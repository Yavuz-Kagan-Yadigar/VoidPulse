"""
VoidPulse — audio helpers used by the player pipeline.

_StereoWidthBin is a Gst.Bin applying mid/side stereo-width processing to
interleaved F32LE stereo. _run_rganalysis() computes a ReplayGain track gain
for files that carry no REPLAYGAIN_TRACK_GAIN tag.

Kept out of player.py so the pipeline code there stays readable; both are
independent of any Player instance.
"""
from constants import *
from time import monotonic as _monotonic
import numpy as _np


class _StereoWidthBin(Gst.Bin):
    """Mid/side stereo width processing on interleaved F32LE stereo.

    Ghost pads let it stand in for a regular element anywhere in a chain.
    """

    def __init__(self, width: int = 50):
        super().__init__()
        self._width = max(-100, min(100, width))

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
        new_buf.duration = buf.duration
        new_buf.offset   = buf.offset

        self._src_pad.remove_probe(self._probe_id)
        pad.push(new_buf)
        self._probe_id = self._src_pad.add_probe(Gst.PadProbeType.BUFFER, self._on_buffer)
        return Gst.PadProbeReturn.DROP


# ══════════════════════════════════════════════════════════════════════════════
#  On-the-fly loudness analysis (ReplayGain via GStreamer's rganalysis)
# ══════════════════════════════════════════════════════════════════════════════
# For tracks with no REPLAYGAIN_TRACK_GAIN tag. A throwaway pipeline decodes the
# file as fast as it can (fakesink sync=false), usually in well under a second.
# The caches are module-level: a gain belongs to the file, not to a Player.
_rg_gain_cache: dict = {}     # filepath → gain in dB
_rg_analyzing:  set  = set()  # analyses currently in flight


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
