"""
VoidPulse — biquad filter coefficients for the parametric EQ.

Pure math, no Qt. Kept separate from eq.py (the EQ UI) so the audio engine in
player.py can compute filter responses without importing any widget code.

Every function returns (b0, b1, b2, a1, a2) normalised to a0 = 1, matching the
layout GStreamer's audioiirfilter expects. Formulas follow the Audio EQ
Cookbook (Robert Bristow-Johnson).
"""
import math

from constants import (
    EQ_TYPE_PEAK, EQ_TYPE_LOWSHELF, EQ_TYPE_HIGHSHELF,
    EQ_TYPE_LOWPASS, EQ_TYPE_HIGHPASS, EQ_TYPE_NOTCH,
)


def peaking_coefficients(fs, f0, gain_db, Q):
    """Peaking (bell) filter: boosts or cuts a band centred on f0."""
    A     = 10.0 ** (gain_db / 40.0)
    w0    = 2.0 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2.0 * Q)
    cos_w = math.cos(w0)
    b0 =  1.0 + alpha * A
    b1 = -2.0 * cos_w
    b2 =  1.0 - alpha * A
    a0 =  1.0 + alpha / A
    a1 =  b1
    a2 =  1.0 - alpha / A
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def lowshelf_coefficients(fs, f0, gain_db, Q):
    """Low-shelf filter: shifts everything below f0 by gain_db."""
    A     = 10.0 ** (gain_db / 40.0)
    w0    = 2.0 * math.pi * f0 / fs
    cos_w = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * Q)
    sq    = 2.0 * math.sqrt(A) * alpha
    b0 =  A * ((A + 1.0) - (A - 1.0) * cos_w + sq)
    b1 =  2.0 * A * ((A - 1.0) - (A + 1.0) * cos_w)
    b2 =  A * ((A + 1.0) - (A - 1.0) * cos_w - sq)
    a0 =       (A + 1.0) + (A - 1.0) * cos_w + sq
    a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cos_w)
    a2 =        (A + 1.0) + (A - 1.0) * cos_w - sq
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def highshelf_coefficients(fs, f0, gain_db, Q):
    """High-shelf filter: shifts everything above f0 by gain_db."""
    A     = 10.0 ** (gain_db / 40.0)
    w0    = 2.0 * math.pi * f0 / fs
    cos_w = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * Q)
    sq    = 2.0 * math.sqrt(A) * alpha
    b0 =  A * ((A + 1.0) + (A - 1.0) * cos_w + sq)
    b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cos_w)
    b2 =  A * ((A + 1.0) + (A - 1.0) * cos_w - sq)
    a0 =       (A + 1.0) - (A - 1.0) * cos_w + sq
    a1 =  2.0 * ((A - 1.0) - (A + 1.0) * cos_w)
    a2 =        (A + 1.0) - (A - 1.0) * cos_w - sq
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def lowpass_coefficients(fs, f0, Q):
    """2nd-order low-pass. Gain does not apply."""
    w0    = 2.0 * math.pi * f0 / fs
    cos_w = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * Q)
    b0 = (1.0 - cos_w) / 2.0
    b1 =  1.0 - cos_w
    b2 = (1.0 - cos_w) / 2.0
    a0 =  1.0 + alpha
    a1 = -2.0 * cos_w
    a2 =  1.0 - alpha
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def highpass_coefficients(fs, f0, Q):
    """2nd-order high-pass. Gain does not apply."""
    w0    = 2.0 * math.pi * f0 / fs
    cos_w = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * Q)
    b0 =  (1.0 + cos_w) / 2.0
    b1 = -(1.0 + cos_w)
    b2 =  (1.0 + cos_w) / 2.0
    a0 =   1.0 + alpha
    a1 =  -2.0 * cos_w
    a2 =   1.0 - alpha
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


def notch_coefficients(fs, f0, Q):
    """Notch (band-stop): rejects a narrow band at f0. Gain does not apply."""
    w0    = 2.0 * math.pi * f0 / fs
    cos_w = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * Q)
    b0 =  1.0
    b1 = -2.0 * cos_w
    b2 =  1.0
    a0 =  1.0 + alpha
    a1 =  b1
    a2 =  1.0 - alpha
    return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


_COEFF_DISPATCH = {
    EQ_TYPE_PEAK:      lambda fs, f0, g, q: peaking_coefficients(fs, f0, g, q),
    EQ_TYPE_LOWSHELF:  lambda fs, f0, g, q: lowshelf_coefficients(fs, f0, g, q),
    EQ_TYPE_HIGHSHELF: lambda fs, f0, g, q: highshelf_coefficients(fs, f0, g, q),
    EQ_TYPE_LOWPASS:   lambda fs, f0, g, q: lowpass_coefficients(fs, f0, q),
    EQ_TYPE_HIGHPASS:  lambda fs, f0, g, q: highpass_coefficients(fs, f0, q),
    EQ_TYPE_NOTCH:     lambda fs, f0, g, q: notch_coefficients(fs, f0, q),
}


def eq_band_coefficients(fs, f0, gain_db, Q, filter_type: int):
    """Coefficients for one EQ band, dispatched on filter_type.

    Returns (b0, b1, b2, a1, a2), or None if the parameters produce a maths
    error (e.g. f0 at or above Nyquist). Unknown types fall back to peaking.
    """
    fn = _COEFF_DISPATCH.get(filter_type, _COEFF_DISPATCH[EQ_TYPE_PEAK])
    try:
        return fn(fs, f0, gain_db, Q)
    except Exception:
        return None
