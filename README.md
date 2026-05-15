# VoidPulse
<img width="1395" height="610" alt="org voidpulse VoidPulse" src="https://github.com/user-attachments/assets/17badd45-a0e1-42e8-9ef9-2b92baa11b80" />

Advanced Music Player for OLED and Touchscreens on Linux
- Parametric EQ
- OLED burn-in protection overlay with optional auto timer
- Cover, lyrics and tag fetching and embedding to music files
- Batch file rename 
- Local and fetched synced and plain lyrics support
- Universal accent color and corner radius
- Dark/light theme
- List & gallery view modes with adjustable sizes and sorting.
- Optimized for touch scrolling and hold context menu
- Toggleable spectrum visualization with custom inertia, multpiple styles and standart logarithmic/linear scale
- Visualization delay to match timing with bluetooth headphones / DACs
- Toggleable cover art
- MPRIS2 desktop environment integration
- Basic tag and lyrics editing
- M3u8 and folder playlist support
- Visualization stops when overlay is active or focus lost to reduce CPU usage

Dependencies (You can use Flatpak from releases for ease of installation->):

Python 3, PyQt6 (PyQt6.QtWidgets, PyQt6.QtCore, PyQt6.QtGui), gobject-introspection (gi.repository), GStreamer (Gst, Gio, GLib), gst-plugins-base (GStreamer base plugins), gst-plugins-good (GStreamer good plugins), gst-plugins-bad (GStreamer bad plugins, spectrum, audioiirfilter), Mutagen (mutagen), PipeWire (pipewire, pipewire-alsa, pipewire-pulse, pipewire-gstreamer), google-noto-music-fonts, python313-numpy 

Disclaimer: Entire code is written by AI, I do not suggest to use as referance code. It might have inefficiencies, bugs, vulnabilities. Just sharing in case somebody wantto use it since most of music players does not go well with touchscreen.

