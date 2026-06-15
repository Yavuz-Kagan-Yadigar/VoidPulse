# VoidPulse
<img width="1395" height="610" alt="org voidpulse VoidPulse" src="https://github.com/user-attachments/assets/17badd45-a0e1-42e8-9ef9-2b92baa11b80" />

Advanced Music Player for OLED and Touchscreens on Linux
- Parametric EQ, compatiable with Poweramp, JSON import and export.
- ALSA output
- Limitter and Stereo Expander
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
- Toggleable cover art with optional accent colored cover
- MPRIS2 desktop environment integration
- Basic tag and lyrics editing
- M3u8 and folder playlist support
- Visualization stops when overlay is active or focus lost to reduce CPU usage
- Ability to use system window decorations or custom OLED friendly one with config

Dependencies (You can use Flatpak from releases for ease of installation->):

Python 3, PyQt6 (PyQt6.QtWidgets, PyQt6.QtCore, PyQt6.QtGui), gobject-introspection (gi.repository), GStreamer (Gst, Gio, GLib), gst-plugins-base (GStreamer base plugins), gst-plugins-good (GStreamer good plugins), gst-plugins-bad (GStreamer bad plugins, spectrum, audioiirfilter), Mutagen (mutagen), PipeWire (pipewire, pipewire-alsa, pipewire-pulse, pipewire-gstreamer), google-noto-music-fonts, python313-numpy 

Disclaimer: Entire code is written by AI, I do not suggest to use as referance code. It might have inefficiencies, bugs, vulnabilities. Just sharing in case somebody wantto use it since most of music players does not go well with touchscreen.

## Gallery

<table>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/c3200906-dd61-4cb3-8732-296ac24ae8f6" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/6b527098-a242-465b-aec9-4bbc7509bccb" width="100%"/></td>
  </tr>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/38624580-c39c-41c8-9526-94b1da623e28" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/379be352-aa17-4130-8c79-367e412c5712" width="100%"/></td>
  </tr>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/a9a98bb9-ee92-4df1-8a45-4aee4dc3ebc6" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/2fd92cda-1acc-4310-a221-d70e9c9b139a" width="100%"/></td>
  </tr>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/a52907f4-c7a6-4ab9-a262-f51c592ca142" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/cf6c26e4-e2c1-4308-b337-3148c39fb1d8" width="100%"/></td>
  </tr>
</table>

### Accent Cover — Light Mode (Violet)
<img src="https://github.com/user-attachments/assets/512ed43d-e029-4866-885c-2fc831ec862a" width="200"/>

### Accent Cover — Dark Mode (Red)
<img src="https://github.com/user-attachments/assets/7f2c4fa2-4c6f-451e-a509-30f5c9cd3fbf" width="200"/>


-------------------------------------------
Run with: `python3 voidpulse.py`

## Files (dependency order, low → high)

| File | Contents | ~Lines |
|------|----------|--------|
| `constants.py` | All imports, palette globals (`BG`/`ACC`/…), `apply_theme()`, `_apply_app_palette()`, `make_acch()`, `_r()`, `SUPPORTED_EXT`, EQ constants, `make_stylesheet()`, `SS` | 321 |
| `widgets_base.py` | `ToggleSwitch`, `TriSwitch`, `JumpSlider`, `SliderRow`, `DeviceBusyPopup`, `_ModalOverlay` | 696 |
| `settings_popup.py` | `SettingsPopup` — audio device, viz-type, EQ, theme, cover/accent toggles | 636 |
| `dialogs_edit.py` | `TagEditDialog` (tag+cover+lyrics editor), `LyricsEditDialog` (plain/LRC editor) | 417 |
| `metadata_online.py` | Online cover fetching (iTunes/Deezer/MusicBrainz/LastFM), tag lookup, `write_tags_to_file()`, `embed_cover_bytes()`, `embed_lyrics()` | 346 |
| `lyrics.py` | LRC parser, embedded-tag extractor, HTTP helpers, all lyric-source functions, `LyricsFetcher`, `LyricsPanel`, `ClickableLyricLine` | 649 |
| `eq.py` | Biquad coefficient functions (Peak/Shelf/Pass/Notch), `EQSliderCell`, `TouchComboBox`, `EqPopup`, `_np_to_qpolygonf`, `_fmt_ms`, `EQGraph` | 1387 |
| `blackout_overlay.py` | `BlackoutOverlay` — full-screen OLED burn-in protection | 429 |
| `cover_art.py` | `Track` dataclass, `read_metadata()`, disk-cache helpers, `_CoverTask`, `AsyncCoverLoader`, `_BaseFetchPopup`, `LibraryCoverFetchWorker`, `CoverFetchPopup` | 1238 |
| `fetch_popups.py` | `LibraryTagFetchWorker`, `TagFetchPopup`, `LibraryLyricsFetchWorker`, `LyricsFetchPopup` | 183 |
| `library.py` | Filename sanitising, `LibraryRenameWorker`, `RenamePopup`, `scan_folder()`, `parse_m3u()`, `ScanThread`, `ConfigPlaylistLoader` | 662 |
| `player.py` | `RepeatMode`, `_StereoWidthBin`, `Player` (GStreamer pipeline, ALSA/PipeWire, EQ DSP, spectrum, seek, shuffle/repeat) | 1713 |
| `mpris.py` | `MprisServer` — MPRIS2 D-Bus interface (GLib thread) | 283 |
| `views.py` | `SeekSlider`, `LongPressFilter`, `_TouchHeaderView`, `_CoverTitleDelegate`, `TrackTable`, `GalleryView`, `PlaylistPage`, `_PlaylistRowWidget`, `Sidebar` | 1613 |
| `controlbar.py` | `_ctrl()`, `RepeatButton`, `_FullscreenBtn`, `SpinningPlayButton`, `_RoundedCoverLabel`, `ControlBar`, `TitleBarButton`, `TitleBarCloseButton`, `BlackTitleBar` | 2166 |
| `main_window.py` | `MainWindow` — widget tree, signal wiring, config I/O, playback control, ALSA probing, tag editing, Open With | 1691 |
| `voidpulse.py` | **Entry point** — `_SpinningOverlay`, `main()` | 156 |

## Dependency graph

```
constants
    ├── widgets_base
    │       └── settings_popup
    ├── metadata_online
    ├── lyrics
    ├── eq  ◄─────────────────────────┐
    ├── blackout_overlay              │
    ├── cover_art                     │
    │       └── fetch_popups          │
    ├── library                       │
    ├── player  ──────── uses eq ─────┘
    ├── mpris
    ├── views  ──────── uses cover_art
    ├── controlbar  ─── uses eq, settings_popup, blackout_overlay, cover_art
    ├── main_window ─── uses everything above
    └── voidpulse.py ── entry point
```
