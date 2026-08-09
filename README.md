# VoidPulse
<img width="1395" height="610" alt="org voidpulse VoidPulse" src="https://github.com/user-attachments/assets/17badd45-a0e1-42e8-9ef9-2b92baa11b80" />

Advanced Music Player for OLED and Touchscreens on Linux
- Parametric EQ, compatiable with Poweramp, JSON import and export.
- ALSA output
- Sox Resampler
- Adaptive Sample Rate: It checks output devices supported sample rates.
If it does support same sample rate as file sets it and pipewire to it: File (44.1khz) -> Pipewire (44.1khz) -> Output Device (44.1khz). No resampling.
If it doesn't support same sampel rate as file, it sets device to its max sample rate, then upsamples to it with builtin Soxr resampler (since upsampling results better than downsample) while settigns Pipewire to same sample rate as output device: File (44.1khz) --(Voidpulse Soxr resample)-> Pipewire (96khz) -> Output Device (96khz).
- Limitter and Stereo Expander
- OLED burn-in protection overlay with optional auto timer
- Cover, lyrics and tag fetching and embedding to music files
- Batch file rename 
- Local and fetched synced and plain lyrics support
- Universal accent color and corner radius
- Dark/light theme and system QT6 color scheme support
- List & gallery view modes with adjustable sizes and sorting.
- Optimized for touch scrolling and hold context menu
- Toggleable spectrum visualization with custom inertia, multpiple styles and standart logarithmic/linear scale
- Visualization delay to match timing with bluetooth headphones / DACs
- Toggleable cover art with optional accent colored cover
- MPRIS2 desktop environment integration
- Basic tag and lyrics editing
- M3u8 and folder playlist support
- Network shares: Samba/SMB, FTP, FTPS and SFTP, mounted through GVfs and reconnected on startup. Passwords go to the system keyring, never to VoidPulse's config. Shares appear as ordinary folders, so scanning, tag reading and playback work unchanged.
  Seeking works on all four, but not the same way. `smb://` and `sftp://` seek directly. `ftp://` and `ftps://` **cannot seek at all** — GVfs exposes them as sequential streams, at the FUSE layer and the GIO layer alike — so VoidPulse reads their tags through a seekable proxy (durations and the seek bar work), and the first time you seek within a track it fetches that track to disk, pauses for the transfer with progress in the status bar, and resumes at the point you asked for. Seeking is instant for the rest of that track, and nothing is fetched for a track you only listen to. VoidPulse probes each share on connect and picks the right path automatically.
- Crossfade between tracks (0–12 s, 0 = off, equal-power). The outgoing track keeps playing while the next fades in, so it needs a mixing sink — it is skipped on exclusive ALSA hw devices, where only one stream can hold the card
- Fade in / out (0–5 s, 0 = off) applied to every play and pause, including media keys, MPRIS and the sleep timer
- Play queue panel next to the lyrics panel: drag tracks in from either the list or the gallery (or drop files from a file manager), or use "Add to Queue"; reorder by dragging or with the per-item ▲/▼ actions, remove with ✕. A non-empty queue takes over playback at the next track change, and the first play after launch starts from it
- Sleep timer, 0 (off) to 6 hours in 5-minute steps, with a live countdown; fades out when it elapses
- Visualization stops when overlay is active or focus lost to reduce CPU usage
- Ability to use system window decorations or custom OLED friendly one with config
  
Dependencies (You can use packages from releases for ease of installation->):

Python 3, PyQt6 (PyQt6.QtWidgets, PyQt6.QtCore, PyQt6.QtGui), gobject-introspection (gi.repository), GStreamer (Gst, Gio, GLib), gst-plugins-base (GStreamer base plugins), gst-plugins-good (GStreamer good plugins), gst-plugins-bad (GStreamer bad plugins, spectrum, audioiirfilter), Mutagen (mutagen), PipeWire (pipewire, pipewire-alsa, pipewire-pulse, pipewire-gstreamer), google-noto-music-fonts, python313-numpy 

Optional, for network shares: gvfs plus its backends (gvfs-backends / gvfs-smb) and **gvfs-fuse** — remote files are read through the FUSE mount under `/run/user/<uid>/gvfs`, so without gvfsd-fuse running a share will connect but stay unreadable.

Disclaimer: Entire code is written by AI, I do not suggest to use as referance code. It might have inefficiencies, bugs, vulnabilities. Just sharing in case somebody wantto use it since most of music players does not go well with touchscreen.

## Gallery

<table>
  <tr>
    <td colspan="2"><img src="https://github.com/user-attachments/assets/617d5b95-4911-4c8a-9c49-c2aa089e3f83" width="100%" alt="Screenshot-2026-07-28_14-13-19"/></td>
  </tr>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/c3200906-dd61-4cb3-8732-296ac24ae8f6" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/6b527098-a242-465b-aec9-4bbc7509bccb" width="100%"/></td>
  </tr>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/379be352-aa17-4130-8c79-367e412c5712" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/2fd92cda-1acc-4310-a221-d70e9c9b139a" width="100%"/></td>
  </tr>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/61b6e913-2fc9-4277-aede-f38c8c9be24d" width="100%" alt="Screenshot-2026-07-28_14-13-42"/></td>
    <td><img src="https://github.com/user-attachments/assets/a52907f4-c7a6-4ab9-a262-f51c592ca142" width="100%"/></td>
  </tr>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/cf6c26e4-e2c1-4308-b337-3148c39fb1d8" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/38624580-c39c-41c8-9526-94b1da623e28" width="100%"/></td>
  </tr>
</table>

### Accent Cover — Light Mode (Violet)
<img src="https://github.com/user-attachments/assets/512ed43d-e029-4866-885c-2fc831ec862a" width="200"/>

### Accent Cover — Dark Mode (Red)
<img src="https://github.com/user-attachments/assets/7f2c4fa2-4c6f-451e-a509-30f5c9cd3fbf" width="200"/>



-------------------------------------------
Run with: `python3 voidpulse.py`

## Files (dependency order, low → high)

| File | Contents | Lines |
|------|----------|-------|
| `remote_io.py` | `register_share()`/`is_nonseekable()` share registry, `SeekableProxy` (seekable view of a sequential stream, for mutagen), `copy_to_local()` on-demand track fetch and its buffer directory — imports nothing from VoidPulse so `constants.py` can use it | 311 |
| `constants.py` | Shared imports re-exported to every module, palette globals (`BG`/`ACC`/…), `apply_theme()`, `apply_accent()`, `_broadcast_palette()`, system Qt theme sync (qt6ct color-scheme parsing + live reload, system palette capture), `_r()`, EQ constants, `make_stylesheet()`, and the shared helpers (`_get`/`_get_json`, `_open_audio`, …) that would otherwise cause import cycles | 977 |
| `alsa.py` | ALSA device enumeration (`aplay -l`), native-rate probing (`aplay --dump-hw-params`), and D-Bus device reservation (`org.freedesktop.ReserveDevice1`) | 355 |
| `eq_filters.py` | Biquad coefficient maths (Peak/Shelf/Pass/Notch) — pure functions, no Qt; shared by the EQ UI and the audio engine | 128 |
| `widgets_base.py` | `ToggleSwitch`, `TriSwitch`, `JumpSlider`, `SliderRow`, `DeviceBusyPopup`, `_ModalOverlay`, `_SpinningOverlay` | 831 |
| `resampler.py` | `SoxrResamplerBin`, `build_resampler_stage()` — soxr streaming resample glue; PipeWire graph/sink rate lookups | 412 |
| `metadata_online.py` | Online cover fetching (iTunes/Deezer/MusicBrainz/LastFM), tag lookup, `write_tags_to_file()`, `write_replaygain_gain_tag()`, `embed_cover_bytes()`, `embed_lyrics()` | 386 |
| `lyrics.py` | LRC parser, embedded-tag extractor, lyric-source functions, `LyricsFetcher`, `LyricsPanel`, `ClickableLyricLine` | 621 |
| `cover_art.py` | `Track` dataclass, `read_metadata()`, cover extraction/rendering, memory+disk cover caches, `_CoverTask`, `AsyncCoverLoader` | 706 |
| `player_dsp.py` | `_StereoWidthBin` (M/S width in numpy), `_run_rganalysis()` ReplayGain analysis and its caches | 211 |
| `player.py` | `RepeatMode`, fade curves, `Player` — GStreamer pipeline, ALSA/PipeWire output, EQ/limiter chain, spectrum tap, seek (incl. fetch-then-seek on shares that cannot seek), shuffle/repeat, play/pause fades and ghost-pipeline crossfade | 2479 |
| `eq.py` | `EQSliderCell`, `TouchComboBox`, `EqPopup` (parametric EQ + preset manager), `EQGraph` | 1299 |
| `settings_popup.py` | `SettingsPopup` — audio device, viz type, EQ, theme, cover/accent toggles | 732 |
| `dialogs_edit.py` | `TagEditDialog` (tag+cover+lyrics editor), `LyricsEditDialog` (plain/LRC editor), `_CoverPreview`, `_ClickableCoverLabel` | 507 |
| `fetch_popups.py` | `_BaseFetchPopup` plus the batch cover / tag / lyrics / ReplayGain workers and their popups | 772 |
| `library.py` | Rename pattern building, `LibraryRenameWorker`, `RenamePopup`, `scan_folder()`, `parse_m3u()`, `ScanThread`, `ConfigPlaylistLoader` | 654 |
| `blackout_overlay.py` | `BlackoutOverlay` — full-screen OLED burn-in protection | 421 |
| `views.py` | `QUEUE_MIME`/`tracks_mime_data()`, `SeekSlider`, `DoubleTapTracker`, `LongPressFilter`, `_TouchHeaderView`, `_CoverTitleDelegate`, `TrackTable`, `GalleryView`, `PlaylistPage` | 1385 |
| `queue_panel.py` | `_QueueList` (drag-reorder + external drops), `QueuePanel` — the play queue, shaped like a `PlaylistPage` so MainWindow drives it unchanged | 400 |
| `remote.py` | `PROTOCOLS`, `build_uri()`, `share_local_path()`, `probe_seekable()`/`SeekProbe`, `RemoteMounter` (GVfs/GIO async mount), `NetworkShareDialog` | 530 |
| `sidebar.py` | `Sidebar` (playlist list, add/rename/remove, drag-reorder, network share button), `_PlaylistRowWidget` | 445 |
| `controlbar_widgets.py` | `_ctrl()`, `RepeatButton`, `_FullscreenBtn`, `SpinningPlayButton`, `_RoundedCoverLabel` | 425 |
| `titlebar.py` | `TitleBarButton`, `TitleBarCloseButton`, `BlackTitleBar` — custom frameless decorations | 128 |
| `controlbar.py` | `ControlBar` — seek + transport, cover thumbnail, EQ/settings popups, spectrum visualiser `paintEvent` | 1837 |
| `mpris.py` | `MprisServer` — MPRIS2 D-Bus interface (GLib thread) | 287 |
| `main_window.py` | `MainWindow` — widget tree, signal wiring, config I/O, playback control, ALSA probing, tag editing, Open With | 1902 |
| `voidpulse.py` | **Entry point** — `main()` | 62 |

## Dependency graph

```
constants ── re-exports the shared imports; every module starts `from constants import *`
    ├── alsa           device list, rate probe, D-Bus reservation
    ├── eq_filters     biquad maths (no Qt)
    ├── resampler      soxr stage + PipeWire rate lookups
    ├── widgets_base   generic touch widgets
    ├── metadata_online
    ├── lyrics             ── uses metadata_online (embed_lyrics)
    ├── cover_art
    ├── player_dsp     stereo-width bin, ReplayGain analysis
    │       └── player ── uses alsa, eq_filters, resampler, player_dsp, cover_art
    ├── eq             ── uses eq_filters, widgets_base
    ├── settings_popup ── uses alsa, eq, player, widgets_base
    ├── dialogs_edit   ── uses cover_art, lyrics, metadata_online
    ├── fetch_popups   ── uses cover_art, lyrics, metadata_online, player_dsp
    ├── library        ── uses cover_art
    ├── blackout_overlay ── uses eq (_fmt_ms, _np_to_qpolygonf)
    ├── views          ── uses cover_art
    │       └── queue_panel ── uses cover_art, views (DoubleTapTracker, QUEUE_MIME)
    ├── remote         gvfs/GIO share mounting + NetworkShareDialog
    ├── sidebar
    ├── controlbar_widgets ── uses cover_art, player
    ├── titlebar
    ├── controlbar     ── uses controlbar_widgets, eq, settings_popup, views,
    │                     fetch_popups, library, widgets_base, player, resampler, cover_art
    ├── mpris          ── uses player, cover_art
    ├── main_window    ── uses everything above
    └── voidpulse.py   ── entry point, also uses cover_art, widgets_base directly
```
