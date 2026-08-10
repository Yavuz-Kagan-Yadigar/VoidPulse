"""Smoke test run inside a freshly built VoidPulse AppImage.

Proves the bundle is genuinely self-contained: the interpreter, Qt, GStreamer
and the typelibs all have to come from inside the AppDir. A packaging mistake
surfaces here instead of on a user's machine.

Executed by .github/workflows/appimage-release.yml via the extracted AppRun.
"""
import sys

print("python:", sys.version.split()[0], "->", sys.executable)
assert "squashfs-root" in sys.executable, (
    f"not running the bundled interpreter: {sys.executable}"
)

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
print("Qt:", QtCore.QT_VERSION_STR)
assert "squashfs-root" in QtCore.__file__, (
    f"PyQt6 came from outside the bundle: {QtCore.__file__}"
)

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst
Gst.init(None)
print("GStreamer:", Gst.version_string())

# Every element the player actually instantiates — see the ElementFactory.make
# calls in player.py, eq.py and resampler.py, plus the sinks in _active_sink_desc.
REQUIRED = (
    "playbin", "decodebin", "audioconvert", "audioresample", "capsfilter",
    "identity", "fakesink", "filesrc", "appsrc", "audioamplify",
    "audiodynamic", "audioiirfilter", "audiopanorama", "spectrum", "rganalysis",
)
missing = [name for name in REQUIRED if Gst.ElementFactory.find(name) is None]
assert not missing, f"GStreamer elements missing from the bundle: {missing}"
print(f"all {len(REQUIRED)} required elements present")

# At least one audio sink must exist or playback has nowhere to go. Which one
# is available depends on the host, so any of the three counts.
sinks = [n for n in ("pipewiresink", "pulsesink", "alsasink", "autoaudiosink")
         if Gst.ElementFactory.find(n) is not None]
assert sinks, "no audio sink bundled (pipewiresink/pulsesink/alsasink/autoaudiosink)"
print("audio sinks available:", ", ".join(sinks))

import numpy
import mutagen
print("numpy:", numpy.__version__, "| mutagen:", mutagen.version_string)

try:
    import soxr
    print("soxr:", soxr.__version__)
except Exception as exc:  # resampler.py degrades to audioresample
    print("soxr unavailable, falling back to audioresample:", exc)

print("SMOKE TEST PASSED")
