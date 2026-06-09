# VoidPulse — Module Structure

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
