"""
VoidPulse — track metadata + cover art: Track dataclass, read_metadata(),
disk-cache helpers, _CoverTask, AsyncCoverLoader, _BaseFetchPopup,
LibraryCoverFetchWorker, CoverFetchPopup.
"""
from constants import *
from constants import ACC, B2, BG, BG3, CONFIG_PATH, FG, FG2, _DARK_MODE, _apply_scroller_properties, _sanitize_filename_part
import re as _re
import urllib.request as _urlreq
import urllib.parse as _urlparse
import numpy as _np

@dataclass
class Track:
    filepath:    str
    title:       str   = ''
    artist:      str   = ''
    album:       str   = ''
    duration:    float = 0.0
    sample_rate: int   = 0
    bit_depth:   int   = 0
    file_type:   str   = ''

    def dur_str(self):
        t = int(self.duration); h, r = divmod(t, 3600); m, s = divmod(r, 60)
        return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'

    def sr_str(self):
        if not self.sample_rate: return ''
        k = self.sample_rate/1000
        return f'{k:.1f} kHz' if k % 1 else f'{int(k)} kHz'

    def bd_str(self): return f'{self.bit_depth}-bit' if self.bit_depth else ''

    def sort_key(self):
        return (self.artist.lower() or '\xff', self.album.lower() or '\xff',
                self.title.lower() or '\xff')

def _tag(tags, *keys):
    for k in keys:
        v = tags.get(k)
        if v:
            s = str(v[0]) if isinstance(v, list) else str(v)
            s = s.strip()
            if s:
                return s
    return ''

def _vtag(tags, *keys):
    """Case-insensitive tag lookup for Vorbis comment tags (FLAC/OGG/OPUS).
    Avoids rebuilding a lowercase dict by iterating tags directly.
    For the small tag sets typical of audio files this is faster.
    Pre-lowercases each search key once instead of re-lowercasing it per tag.
    """
    # Pre-lower each tag key once so the inner loop only lowers per-tag items.
    lc_tags = [(tk.lower(), tv) for tk, tv in tags.items()]
    for k in keys:
        kl = k.lower()
        for tkl, tv in lc_tags:
            if tkl == kl:
                s = str(tv[0]) if isinstance(tv, list) else str(tv)
                s = s.strip()
                if s:
                    return s
    return ''

def _open_audio(fp: str):
    """Open an audio file with mutagen, trying format-specific classes as fallback.
    Returns a mutagen File object or None."""
    af = MutagenFile(fp, easy=False)
    if af is not None:
        return af
    ext = Path(fp).suffix.lower()
    try:
        if ext == '.opus':
            from mutagen.oggopus import OggOpus;    return OggOpus(fp)
        if ext == '.ogg':
            from mutagen.oggvorbis import OggVorbis; return OggVorbis(fp)
        if ext == '.flac':
            from mutagen.flac import FLAC;           return FLAC(fp)
        if ext == '.mp3':
            from mutagen.mp3 import MP3;             return MP3(fp)
        if ext in ('.m4a', '.aac'):
            from mutagen.mp4 import MP4;             return MP4(fp)
        if ext in ('.wav', '.wave'):
            from mutagen.wave import WAVE;           return WAVE(fp)
        if ext in ('.aiff', '.aif'):
            from mutagen.aiff import AIFF;           return AIFF(fp)
    except Exception:
        pass
    return None

def read_metadata(fp: str) -> Track:
    p = Path(fp); ext = p.suffix.lower()
    tr = Track(filepath=fp, title=p.stem, file_type=ext.lstrip('.').upper())
    try:
        af = _open_audio(fp)
        if af is None: return tr
        i = af.info
        tr.duration    = getattr(i, 'length', 0.0)
        tr.sample_rate = getattr(i, 'sample_rate', 0)
        for a in ('bits_per_sample', 'bits_per_raw_sample'):
            v = getattr(i, a, 0)
            if v: tr.bit_depth = v; break
        tg = af.tags
        if tg is None: return tr
        if ext == '.mp3':
            tr.title  = _tag(tg, 'TIT2') or tr.title
            tr.artist = _tag(tg, 'TPE1', 'TPE2'); tr.album = _tag(tg, 'TALB')
        elif ext in ('.flac', '.opus', '.ogg'):
            tr.title  = _vtag(tg, 'title') or tr.title
            tr.artist = _vtag(tg, 'artist', 'albumartist')
            tr.album  = _vtag(tg, 'album')
        elif ext in ('.m4a', '.aac'):
            tr.title  = _tag(tg, '\xa9nam') or tr.title
            tr.artist = _tag(tg, '\xa9ART', 'aART'); tr.album = _tag(tg, '\xa9alb')
        else:
            tr.title  = _tag(tg, 'title',  'TITLE') or tr.title
            tr.artist = _tag(tg, 'artist', 'ARTIST'); tr.album = _tag(tg, 'album', 'ALBUM')
    except Exception:
        pass
    return tr

# ── Cover art ─────────────────────────────────────────────────────────────────
_cover_cache: OrderedDict = OrderedDict()  # (fp, size) → QPixmap (LRU-ordered via move_to_end)
                                           # Radius is NOT stored here — applied at draw time via _draw_cover_rounded()
_COVER_SENTINEL = object()  # distinguishes cache miss from cached None

# Master resolution stored on disk — one file per track regardless of how many
# display sizes are requested.  All smaller sizes are derived in-memory by
# downscaling from this master; no per-size disk files are written.
# 220px is the maximum gallery card cover size so it is the natural upper bound.
_COVER_MASTER_SIZE = 220

# Memory cache limit.  With one master per track in memory plus a handful of
# derived sizes (28, 64, gallery size), 2000 entries covers ~400 tracks at
# ~5 sizes each with comfortable headroom.
_COVER_CACHE_MAX = 2000

def _trim_cover_cache() -> None:
    """Evict oldest quarter of entries when cache exceeds _COVER_CACHE_MAX.

    Python dicts are insertion-ordered (3.7+).  Trimming from the front evicts
    the least-recently-inserted entries.  Good enough for a cover cache where
    recency roughly correlates with 'currently visible in gallery/table'.
    """
    overflow = len(_cover_cache) - _COVER_CACHE_MAX
    if overflow > 0:
        trim = overflow + _COVER_CACHE_MAX // 4   # remove 25% extra to avoid thrash
        for key in list(_cover_cache.keys())[:trim]:
            _cover_cache.pop(key, None)

def _purge_orphan_disk_covers() -> None:
    """Delete disk cover files that are not the 220px master (_220.jpg).

    Old versions wrote a separate <stem>_<size>.jpg for every display size.
    This one-time startup sweep removes those stale files so the covers
    directory converges to exactly one file per track.
    Runs in a daemon thread — never blocks the UI.
    """
    if not _COVER_DISK_DIR.exists():
        return
    try:
        _size_re = _re.compile(r'_(\d+)\.jpg$', _re.IGNORECASE)
        for f in _COVER_DISK_DIR.iterdir():
            if not f.is_file():
                continue
            m = _size_re.search(f.name)
            if m and int(m.group(1)) != _COVER_MASTER_SIZE:
                try:
                    f.unlink(missing_ok=True)
                    Path(str(f) + '.mtime').unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass

def extract_cover_bytes(fp: str) -> Optional[bytes]:
    """Return raw cover bytes from embedded tags, or None."""
    try:
        ext = Path(fp).suffix.lower()
        af = _open_audio(fp)
        if af is None: return None
        if ext == '.mp3':
            from mutagen.id3 import APIC
            for tag in af.tags.values():
                if isinstance(tag, APIC): return tag.data
        elif ext == '.flac':
            if hasattr(af, 'pictures') and af.pictures:
                return af.pictures[0].data
        elif ext in ('.m4a', '.aac'):
            covr = af.tags.get('covr')
            if covr: return bytes(covr[0])
        elif ext in ('.ogg', '.opus'):
            from mutagen.flac import Picture
            pics = af.tags.get('metadata_block_picture', [])
            if pics:
                return Picture(base64.b64decode(pics[0])).data
    except Exception:
        pass
    return None

def _square_pixmap(pm: QPixmap, size: int) -> QPixmap:
    """Scale pm to size×size and centre-crop to an exact square.

    No rounded corners are applied here — the result is a plain opaque JPEG-
    compatible square.  Corner rounding is done at draw time by
    _draw_cover_rounded() so we never need transparency in the disk cache and
    one cached pixmap serves every radius value.

    Note: KeepAspectRatioByExpanding can produce a result 1px smaller than
    requested due to float→int truncation (e.g. 220*(28/220) = 27.999…→27).
    The IgnoreAspectRatio fallback guarantees exact size×size output.
    """
    pm = pm.scaled(size, size,
                   Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                   Qt.TransformationMode.SmoothTransformation)
    # Guard: float→int truncation in Qt scaling can produce a result 1px
    # smaller than requested (e.g. 220px master → 28px target).
    # If either dimension fell short, force an exact square via IgnoreAspectRatio.
    if pm.width() < size or pm.height() < size:
        pm = pm.scaled(size, size,
                       Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    x = max(0, (pm.width()  - size) // 2)
    y = max(0, (pm.height() - size) // 2)
    return pm.copy(x, y, size, size)

# Pre-cached corner-frame pixmaps: (size, radius, bg_color) → QPixmap
# Each is a size×size ARGB pixmap that is fully transparent in the rounded-rect
# interior and bg_color in the four corner areas.  Painting it on top of a
# square cover produces the rounded-corner illusion with zero transparency in
# the cover cache files.  Frames are tiny (a few KB each) and keyed by
# (size, radius, bg_color) — only a handful ever exist at runtime.
_corner_frame_cache: dict = {}

def _get_corner_frame(size: int, radius: int, bg_color: str) -> QPixmap:
    """Return (or build + cache) the corner-masking overlay frame.

    The frame is size×size with transparent interior (shows cover below) and
    bg_color corners.  Composited on top of the square cover to fake rounded
    corners without any ARGB data in the cover cache.
    """
    key = (size, radius, bg_color)
    pm = _corner_frame_cache.get(key)
    if pm is not None:
        return pm
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 1. Fill everything with bg_color
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(bg_color)))
    p.drawRect(0, 0, size, size)
    # 2. Clear (transparent) the rounded-rect interior so the cover shows through
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.setBrush(Qt.BrushStyle.SolidPattern)
    p.drawRoundedRect(0, 0, size, size, radius, radius)
    p.end()
    _corner_frame_cache[key] = pm
    return pm

def _draw_cover_rounded(painter: QPainter, pm: QPixmap,
                        x: int, y: int, size: int, radius: int,
                        bg_color: str) -> None:
    """Draw *pm* at (x,y) with rounded corners, no transparency in cover cache.

    Strategy: draw the square cover pixmap, then draw a pre-built corner-frame
    overlay on top.  The frame is ARGB with transparent interior and bg_color
    corners — it costs one extra drawPixmap() call but avoids storing ARGB
    data in the disk/memory cover cache and keeps the cache key radius-free.
    """
    painter.drawPixmap(x, y, size, size, pm)
    if radius > 0:
        frame = _get_corner_frame(size, radius, bg_color)
        painter.drawPixmap(x, y, frame)


def _default_cover_disk_path(acc: str, bg: str, size: int) -> Path:
    safe_acc = acc.lstrip('#')
    safe_bg  = bg.lstrip('#')
    # PNG for the 220px master (lossless); kept as .jpg key for back-compat
    # but the new master always uses .png extension.
    if size == 220:
        return CONFIG_PATH.parent / f'default_cover_{safe_acc}_{safe_bg}_{size}.png'
    return CONFIG_PATH.parent / f'default_cover_{safe_acc}_{safe_bg}_{size}.jpg'

_default_cover_mem_cache: dict = {}   # various keys -> QPixmap  (square, no radius)

_DEFAULT_COVER_MASTER_SIZE = _COVER_MASTER_SIZE  # kept in sync with audio cover master size

def _render_default_cover_master(size: int = _DEFAULT_COVER_MASTER_SIZE) -> QPixmap:
    """Render the clef placeholder at the given size (plain opaque square)."""
    pm = QPixmap(size, size)
    pm.fill(QColor(BG))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(ACC), 1))
    font = p.font()
    font.setPixelSize(int(size * 0.67))
    font.setFamily('Segoe UI Symbol, FreeSerif, Symbola, Arial Unicode MS')
    p.setFont(font)
    p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, '𝄞')
    p.end()
    return pm

def draw_default_cover(size: int) -> QPixmap:
    """Return (or build) the clef-placeholder cover as a plain square pixmap.

    Uses the same master-size (220px) + downscale architecture as real covers:
      • 220px master is rendered once and cached in memory (keyed by ACC + BG).
      • Requested sizes are derived by downscaling the master — no per-size
        disk files, no JPEG round-trips at small dimensions.
    The default cover is stored without rounded corners — like all covers —
    so the same pixmap serves every radius setting.  Callers that need rounded
    display use _draw_cover_rounded() or _get_corner_frame().
    """
    master_key = ('__default__', _DEFAULT_COVER_MASTER_SIZE, ACC, BG)
    master_pm = _default_cover_mem_cache.get(master_key)
    if master_pm is None:
        # Build 220px master; also try disk cache for it
        disk = _default_cover_disk_path(ACC, BG, _DEFAULT_COVER_MASTER_SIZE)
        if disk.exists():
            pm = QPixmap()
            if pm.load(str(disk)):
                master_pm = pm
        if master_pm is None:
            master_pm = _render_default_cover_master(_DEFAULT_COVER_MASTER_SIZE)
            # Persist master to disk (PNG — lossless, one file per theme combo)
            try:
                disk.parent.mkdir(parents=True, exist_ok=True)
                master_pm.save(str(disk), 'PNG')
            except Exception:
                pass
        _default_cover_mem_cache[master_key] = master_pm

    if size == _DEFAULT_COVER_MASTER_SIZE:
        return master_pm

    # Derive requested size by downscaling the in-memory master (no disk I/O)
    mem_key = ('__default__', size, ACC, BG)
    pm = _default_cover_mem_cache.get(mem_key)
    if pm is None:
        pm = _square_pixmap(master_pm, size)
        _default_cover_mem_cache[mem_key] = pm
    return pm

_COVER_DISK_DIR  = CONFIG_PATH.parent / 'covers'
_cover_fetch_on  = True   # module-level flag — updated by ControlBar
_lastfm_api_key  = ''    # set from config or fetch popups — never hardcoded
_cover_locked_set: set = set()   # filepaths that must not auto-fetch
_COVER_JPEG_QUALITY = 80

# Pre-create cover cache dir; non-fatal if it fails (e.g. read-only Flatpak sandbox)
try:
    _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

def _cover_disk_key(fp: str) -> str:
    """Persistent filename-based disk cache key: <sanitized_stem>_220.

    One master file per track at _COVER_MASTER_SIZE (220px).  All smaller
    display sizes are derived in-memory by downscaling; no per-size files.

    Using the audio filename stem (not a SHA1 hash) means:
    - The disk key is human-readable and survives process restarts.
    - Batch rename can update cover filenames by a simple rename on disk.
    - Stale covers (file replaced with different content) are detected by
      comparing the embedded-cover mtime via a sidecar .mtime file written
      alongside the JPEG.  If the audio mtime changed we re-extract.

    The key is sanitized with the same rules as _sanitize_filename_part so
    characters illegal on Linux/Windows are stripped.
    """
    stem = _sanitize_filename_part(Path(fp).stem)
    # Truncate very long stems to keep filenames under 200 chars
    if len(stem) > 120:
        stem = stem[:120]
    return f'{stem}_{_COVER_MASTER_SIZE}'

def _cover_disk_is_stale(fp: str, disk_path: Path) -> bool:
    """Return True if the cover on disk is older than the audio file's mtime.

    A sidecar file ``<disk_path>.mtime`` holds the mtime string at the time
    the cover was extracted.  If the audio file has been re-tagged since then
    the sidecar will differ and we re-extract.  Missing sidecar → stale.
    """
    sidecar = Path(str(disk_path) + '.mtime')
    try:
        audio_mtime = str(os.path.getmtime(fp))
    except Exception:
        return False  # can't stat audio — keep existing cover
    try:
        cached_mtime = sidecar.read_text().strip()
        return cached_mtime != audio_mtime
    except Exception:
        return True  # no sidecar → treat as stale

def _cover_disk_write_mtime(fp: str, disk_path: Path) -> None:
    """Write a sidecar .mtime file next to *disk_path*."""
    try:
        audio_mtime = str(os.path.getmtime(fp))
        Path(str(disk_path) + '.mtime').write_text(audio_mtime)
    except Exception:
        pass

# Global flag — toggled by ControlBar._on_cover_acc_toggle
_COVER_ACC_ON: bool = False

# LUT cache: acc_h → (lut_r, lut_g, lut_b) uint8 arrays of length 256
# Built once per accent hue, reused across all cover sizes.
_acc_lut_cache: dict = {}   # acc_h → (lut_r, lut_g, lut_b)

def _recolor_pixmap(pm: QPixmap) -> QPixmap:
    """Return pm recoloured using a luminance LUT.

    Dark mode:  black (v=0)  → accent (v=255)
    Light mode: accent (v=0) → white  (v=255)

    LUT is cached per (acc_h, dark_mode) pair and rebuilt when either changes.
    """
    acc_h, acc_s, _, _ = QColor(ACC).getHsv()
    cache_key = (acc_h, _DARK_MODE)
    lut = _acc_lut_cache.get(cache_key)
    if lut is None:
        lut_r = _np.empty(256, dtype=_np.uint8)
        lut_g = _np.empty(256, dtype=_np.uint8)
        lut_b = _np.empty(256, dtype=_np.uint8)
        _c = QColor()
        if _DARK_MODE:
            # v=0 → black, v=255 → accent (full saturation, value ramp)
            for v in range(256):
                _c.setHsv(acc_h, acc_s, v)
                lut_r[v] = _c.red()
                lut_g[v] = _c.green()
                lut_b[v] = _c.blue()
        else:
            # v=0 → accent, v=255 → white (value fixed at 255, saturation ramp down)
            for v in range(256):
                sat = 255 - v   # high lum → low saturation → white
                _c.setHsv(acc_h, sat, 255)
                lut_r[v] = _c.red()
                lut_g[v] = _c.green()
                lut_b[v] = _c.blue()
        lut = (lut_r, lut_g, lut_b)
        _acc_lut_cache[cache_key] = lut
    lut_r, lut_g, lut_b = lut
    img = pm.toImage().convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    stride = img.bytesPerLine()   # may be > w*4 due to Qt row alignment
    ptr = img.bits(); ptr.setsize(h * stride)
    # Read as (h, stride) byte array so row padding is preserved in the copy,
    # then slice out only the w*4 pixel bytes per row — avoids stride mismatch
    # that causes cross-row garbage when bytesPerLine != w*4.
    raw = _np.frombuffer(ptr, dtype=_np.uint8).reshape(h, stride).copy()
    # img no longer needed after copy() — release before heavy numpy work
    del img
    arr = raw[:, : w * 4].reshape(h * w, 4)   # exact pixel columns only
    # Qt RGB32 LE layout: B G R 0xFF
    y8 = ((arr[:, 2].astype(_np.uint16) * 2 +
           arr[:, 1].astype(_np.uint16) * 5 +
           arr[:, 0].astype(_np.uint16)) >> 3).clip(0, 255).astype(_np.uint8)
    out = arr.copy()
    out[:, 0] = lut_b[y8]
    out[:, 1] = lut_g[y8]
    out[:, 2] = lut_r[y8]
    return QPixmap.fromImage(QImage(out.tobytes(), w, h, w * 4, QImage.Format.Format_RGB32))

def get_cover_pixmap(fp: str, size: int = 48) -> Optional[QPixmap]:
    """Return cached square QPixmap (memory-only, non-blocking).

    The returned pixmap is a plain square — no rounded corners baked in.
    Callers paint the rounded-corner overlay frame themselves via
    _draw_cover_rounded(), so one pixmap serves all radius values.

    Architecture (master-size cache):
      L1  Exact-size memory hit → return immediately.
      L2  Master (220px) already in memory → downscale on main thread,
          cache the result, return immediately.  No disk I/O.
      L3  Any other larger cached size for this fp → downscale, cache, return.
      L4  Cache miss → schedule async load.  The worker always fetches/stores
          the 220px master on disk and posts it back; the main thread derives
          the requested size and caches both master + requested size.
    """
    key = (fp, size)
    cached = _cover_cache.get(key, _COVER_SENTINEL)
    if cached is not _COVER_SENTINEL:
        _cover_cache.move_to_end(key)   # LRU: mark as recently used
        return _recolor_pixmap(cached) if (_COVER_ACC_ON and cached is not None) else cached

    # L2: master already in memory — cheapest derive path
    master = _cover_cache.get((fp, _COVER_MASTER_SIZE), _COVER_SENTINEL)
    if master is not _COVER_SENTINEL and master is not None:
        if size == _COVER_MASTER_SIZE:
            return _recolor_pixmap(master) if _COVER_ACC_ON else master
        pm = _square_pixmap(master, size)
        _cover_cache[key] = pm
        _trim_cover_cache()
        return _recolor_pixmap(pm) if _COVER_ACC_ON else pm

    # L3: any other larger cached size for this fp (covers sizes > master too)
    best_pm: Optional[QPixmap] = None
    best_sz = 0
    for (cached_fp, cached_sz), cached_pm in _cover_cache.items():
        if cached_fp == fp and cached_pm is not None and cached_sz >= size:
            if best_sz == 0 or cached_sz < best_sz:
                best_pm = cached_pm
                best_sz = cached_sz
    if best_pm is not None:
        pm = _square_pixmap(best_pm, size)
        _cover_cache[key] = pm
        _trim_cover_cache()
        return _recolor_pixmap(pm) if _COVER_ACC_ON else pm

    # L4: schedule async load — worker will fetch/cache master, then derive size
    _ensure_async_cover_loader().request(fp, size)
    return None

class _CoverTask(QRunnable):
    """One cover-load task. Reads disk/mutagen on a pool thread, posts result
    back to the main thread via a queued signal on the loader QObject."""
    def __init__(self, loader, fp, size):
        super().__init__()
        self.setAutoDelete(True)
        self._loader = loader
        self._fp = fp; self._size = size

    def run(self):
        fp, size = self._fp, self._size
        try:
            # Master disk path — always 220px regardless of requested size.
            # All display sizes are derived from this one file.
            master_dkey = _cover_disk_key(fp)
            master_disk_path = _COVER_DISK_DIR / f'{master_dkey}.jpg'

            # L1.5: master already in memory (race with another task that just
            # finished) — re-emit the 220px master via _master_ready so the
            # main thread derives the requested size cleanly with _square_pixmap.
            # Never encode a downscaled derived size as JPEG here: JPEG 8x8 DCT
            # block artefacts at 28-44px are visible and get amplified by
            # _recolor_pixmap when cover-accent mode is on.
            master_pm = _cover_cache.get((fp, _COVER_MASTER_SIZE))
            if master_pm is not None:
                buf    = QByteArray()
                buf_io = QBuffer(buf)
                buf_io.open(QIODeviceBase.OpenModeFlag.WriteOnly)
                master_pm.save(buf_io, 'JPEG', _COVER_JPEG_QUALITY)
                buf_io.close()
                raw = bytes(buf)
                if raw:
                    # Emit as master (empty disk_path = already on disk).
                    # _on_master_ready will derive the target size losslessly.
                    self._loader._master_ready.emit(fp, size, raw, '')
                    return

            # L2: master disk cache — one file per track, already square 220px.
            if master_disk_path.exists() and not _cover_disk_is_stale(fp, master_disk_path):
                try:
                    with open(str(master_disk_path), 'rb') as f:
                        master_raw = f.read()
                    if master_raw:
                        sidecar = Path(str(master_disk_path) + '.mtime')
                        if not sidecar.exists():
                            _cover_disk_write_mtime(fp, master_disk_path)
                        if size == _COVER_MASTER_SIZE:
                            # Requested size IS the master — emit directly.
                            self._loader._raw_ready.emit(fp, size, master_raw, '')
                        else:
                            # Decode master, downscale to requested size, emit.
                            # master_disk_path is passed so main thread also
                            # stores the master in _cover_cache.
                            self._loader._post_raw_master(fp, size, master_raw,
                                                          str(master_disk_path))
                        return
                except Exception:
                    pass  # fall through to full load

            # L3: embedded cover — decode, write 220px master to disk, derive size.
            data = extract_cover_bytes(fp)
            if data:
                img = QImage()
                img.loadFromData(data)
                if not img.isNull():
                    self._loader._post_image(fp, size, img, str(master_disk_path))
                    return

            # Nothing found
            self._loader._post_miss(fp, size)
        except Exception:
            self._loader._post_miss(fp, size)

class AsyncCoverLoader(QObject):
    """
    Non-blocking cover loader for the gallery paint path.
    Uses QThreadPool so tasks run on pool threads managed by Qt.
    Results are delivered back to the main thread via a queued signal
    (Qt auto-selects queued connection when emitter and receiver are in
    different threads).
    """
    # emitted on main thread after QPixmap is built
    cover_loaded = pyqtSignal(str, int)   # fp, size
    # master signal — worker posts 220px bytes + disk path; main thread stores + derives
    _master_ready = pyqtSignal(str, int, bytes, str)  # fp, requested_size, master_raw, disk_path
    # derived signal — worker posts already-scaled bytes for a specific size (no disk write)
    _raw_ready    = pyqtSignal(str, int, bytes, str)  # fp, size, data, disk_path (unused)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._in_flight: set = set()
        self._no_embed:  set = set()
        self._lock = threading.Lock()
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max(2, self._pool.maxThreadCount()))
        self._master_ready.connect(self._on_master_ready, Qt.ConnectionType.QueuedConnection)
        self._raw_ready.connect(self._on_raw_ready, Qt.ConnectionType.QueuedConnection)

    def request(self, fp: str, size: int):
        key = (fp, size)
        with self._lock:
            if key in _cover_cache or key in self._in_flight or fp in self._no_embed:
                return
            self._in_flight.add(key)
        task = _CoverTask(self, fp, size)
        self._pool.start(task)

    # ── worker-thread helpers ─────────────────────────────────────────────────

    def _post_image(self, fp: str, size: int, img: QImage, master_disk_path: str):
        """Scale raw QImage to 220px master, encode JPEG, emit.  Worker thread."""
        img = img.scaled(_COVER_MASTER_SIZE, _COVER_MASTER_SIZE,
                         Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.SmoothTransformation)
        cx = (img.width()  - _COVER_MASTER_SIZE) // 2
        cy = (img.height() - _COVER_MASTER_SIZE) // 2
        img = img.copy(cx, cy, _COVER_MASTER_SIZE, _COVER_MASTER_SIZE)
        buf    = QByteArray()
        buf_io = QBuffer(buf)
        buf_io.open(QIODeviceBase.OpenModeFlag.WriteOnly)
        img.save(buf_io, 'JPEG', _COVER_JPEG_QUALITY)
        buf_io.close()
        master_raw = bytes(buf)
        if master_raw:
            self._master_ready.emit(fp, size, master_raw, master_disk_path or '')

    def _post_raw_master(self, fp: str, size: int,
                         master_raw: bytes, master_disk_path: str):
        """Cache master in memory and derive requested size.  Worker thread.

        Called when the 220px disk file exists and size != _COVER_MASTER_SIZE.
        Emits _master_ready with the master bytes; _on_master_ready caches the
        master, derives the requested size, and emits cover_loaded exactly once.
        No disk write — the master file is already fresh.
        """
        # Just forward to the master path — _on_master_ready handles the derive.
        # Empty disk_path means: master is already on disk, skip the write.
        self._master_ready.emit(fp, size, master_raw, '')

    def _post_miss(self, fp, size):
        with self._lock:
            self._no_embed.add(fp)
            self._in_flight.discard((fp, size))

    # ── main thread (called via queued connection) ────────────────────────────

    def _on_master_ready(self, fp: str, size: int,
                         master_raw: bytes, master_disk_path: str):
        """Store 220px master in memory + disk, derive requested size."""
        with self._lock:
            self._in_flight.discard((fp, size))
        if not master_raw:
            with self._lock:
                self._no_embed.add(fp)
            return
        master_pm = QPixmap()
        if not master_pm.loadFromData(master_raw, 'JPEG') or master_pm.isNull():
            with self._lock:
                self._no_embed.add(fp)
            return
        # Cache master
        _cover_cache[(fp, _COVER_MASTER_SIZE)] = master_pm
        # Derive requested size from master (in-memory — very cheap)
        if size != _COVER_MASTER_SIZE:
            pm = _square_pixmap(master_pm, size)
            _cover_cache[(fp, size)] = pm
        _trim_cover_cache()
        # Persist master to disk (one file per track)
        if master_disk_path:
            try:
                _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
                with open(master_disk_path, 'wb') as f:
                    f.write(master_raw)
                _cover_disk_write_mtime(fp, Path(master_disk_path))
            except Exception:
                pass
        self.cover_loaded.emit(fp, size)

    def _on_raw_ready(self, fp: str, size: int, data: bytes, _disk_path: str):
        """Store a pre-scaled derived-size pixmap (no disk write — master already saved)."""
        key = (fp, size)
        with self._lock:
            self._in_flight.discard(key)
        if not data:
            with self._lock:
                self._no_embed.add(fp)
            return
        pm = QPixmap()
        if not pm.loadFromData(data, 'JPEG') or pm.isNull():
            with self._lock:
                self._no_embed.add(fp)
            return
        _cover_cache[key] = pm
        _trim_cover_cache()
        self.cover_loaded.emit(fp, size)

# Module-level singleton — created once, shared by all gallery views
_async_cover_loader: Optional['AsyncCoverLoader'] = None

def _ensure_async_cover_loader() -> 'AsyncCoverLoader':
    global _async_cover_loader
    if _async_cover_loader is None:
        _async_cover_loader = AsyncCoverLoader()
    return _async_cover_loader

class _BaseFetchPopup(QDialog):
    """Shared base for CoverFetchPopup, TagFetchPopup, LyricsFetchPopup.

    Subclasses must implement:
        _make_worker()  -> QObject worker with .run(), .progress(int,int,str),
                           .track_done(...), .finished(int,int), .cancel()
        _on_track_done(fp, *args)
    And may override _on_finished(found, total) to customise the result label.
    """

    # Class-level tracking of active workers per popup type (supports multiple concurrent workers)
    _active_workers = {}  # key: popup_type_name, value: list of (instance, worker, thread)

    def __init__(self, tracks: list, title: str, info_text: str, needs_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        self.setMinimumHeight(600)
        self._tracks   = list(tracks)
        self._thread   = None
        self._worker   = None
        self._running  = False
        self._popup_type = self.__class__.__name__
        # Store background state for restoration
        self._bg_progress = 0
        self._bg_total = needs_count
        self._bg_track_name = ''
        self._bg_log_items = []  # list of (text, ok_flag)
        self._bg_result = ''
        self._worker_id = None  # Will be set when worker is created or restored
        self._status_widget_key = None  # Key for status bar widget

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 18, 20, 18)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f'font-size:14px;font-weight:bold;color:{FG};')
        root.addWidget(title_lbl)

        # ── Last.fm API Key row ───────────────────────────────────────────────
        lfm_row = QHBoxLayout(); lfm_row.setSpacing(6)
        lfm_lbl = QLabel('Last.fm key:')
        lfm_lbl.setStyleSheet(f'color:{FG2};font-size:11px;')
        lfm_lbl.setFixedWidth(72)
        lfm_row.addWidget(lfm_lbl)
        self._lfm_edit = QLineEdit()
        self._lfm_edit.setPlaceholderText('API key (optional)')
        self._lfm_edit.setFixedHeight(22)
        self._lfm_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._lfm_edit.setText(_lastfm_api_key)
        self._lfm_edit.setStyleSheet(
            f'QLineEdit{{background:{BG3};color:{FG};border:1px solid {B2};'
            f'border-radius:4px;padding:0 6px;font-size:11px;}}'
            f'QLineEdit:focus{{border-color:{ACC};}}'
        )
        lfm_row.addWidget(self._lfm_edit, 1)
        root.addLayout(lfm_row)

        self._lfm_edit.textChanged.connect(self._on_lfm_text_changed)
        if len(_lastfm_api_key) == 32:
            self._set_lfm_border(True)
        # ─────────────────────────────────────────────────────────────────────

        info_lbl = QLabel(info_text)
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(f'color:{FG2};font-size:12px;')
        root.addWidget(info_lbl)

        self._track_lbl = QLabel('')
        self._track_lbl.setStyleSheet(f'color:{FG};font-size:12px;')
        self._track_lbl.setWordWrap(True)
        root.addWidget(self._track_lbl)

        self._progress = QProgressBar()
        self._progress.setRange(0, max(1, needs_count))
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFixedHeight(22)
        self._progress.setStyleSheet(
            f'QProgressBar{{background:{BG3};border:1px solid {B2};border-radius:4px;'
            f'color:{FG};font-size:11px;text-align:center;}}'
            f'QProgressBar::chunk{{background:{ACC};border-radius:3px;}}')
        root.addWidget(self._progress)

        self._log = QListWidget()
        self._log.setFixedHeight(140)
        self._log.setStyleSheet(
            'QListWidget{background:' + BG + ';border:1px solid ' + B2 + ';border-radius:4px;'
            'color:' + FG2 + ';font-size:10px;outline:none;}'
            'QListWidget::item{padding:1px 6px;border:none;}'
            'QListWidget::item:selected{background:transparent;color:' + FG2 + ';}'
        )
        self._log.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        QScroller.grabGesture(self._log.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        _apply_scroller_properties(self._log.viewport(), touch=False)
        root.addWidget(self._log)

        self._result_lbl = QLabel('')
        self._result_lbl.setStyleSheet(f'color:{FG2};font-size:11px;')
        root.addWidget(self._result_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._btn_start  = QPushButton('Start')
        self._btn_cancel = QPushButton('Cancel')
        self._btn_cancel.setEnabled(False)
        self._btn_close  = QPushButton('Close')
        self._force_cb   = QCheckBox('Force (re-fetch all)')
        self._force_cb.setStyleSheet(f'color:{FG2};font-size:11px;')
        
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addSpacing(8)
        btn_row.addWidget(self._force_cb)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

        self._btn_start.clicked.connect(self._start)
        self._btn_cancel.clicked.connect(self._cancel)
        self._btn_close.clicked.connect(self._on_close)
        self._force = False   # set just before _make_worker() is called
        # Initialise close button to correct label (not running yet)
        self._update_close_btn()

        # Check if there's an existing worker running in background and auto-start
        self._check_and_restore_background()
        QApplication.instance().installEventFilter(self)

    def _on_lfm_text_changed(self, text: str):
        """Automatically test when 32 characters are reached, reset border if incomplete."""
        if len(text) == 32:
            self._test_lastfm_key()
        else:
            self._lfm_edit.setStyleSheet(
                f'QLineEdit{{background:{BG3};color:{FG};border:1px solid {B2};'
                f'border-radius:4px;padding:0 6px;font-size:11px;}}'
                f'QLineEdit:focus{{border-color:{ACC};}}'
            )

    def _test_lastfm_key(self):
        """Test the API key, set textbox border to green/red based on result and save."""
        key = self._lfm_edit.text().strip()
        if not key:
            self._set_lfm_border(False)
            return
        result = [None]

        def _check():
            try:
                q = _urlparse.quote('Radiohead'); tk = _urlparse.quote('Creep')
                url = (f'https://ws.audioscrobbler.com/2.0/?method=track.getinfo'
                       f'&artist={q}&track={tk}&api_key={key}&format=json')
                req = _urlreq.Request(url, headers={'User-Agent': 'VoidPulse/2.0'})
                with _urlreq.urlopen(req, timeout=6) as r:
                    d = json.loads(r.read())
                result[0] = 'error' not in d and 'track' in d
            except Exception:
                result[0] = False

        thr = threading.Thread(target=_check, daemon=True)
        thr.start()

        def _poll():
            if thr.is_alive():
                QTimer.singleShot(150, _poll)
                return
            if not self.isVisible(): return
            ok = result[0]
            self._set_lfm_border(ok)
            if ok:
                global _lastfm_api_key
                _lastfm_api_key = key

        QTimer.singleShot(150, _poll)

    def _set_lfm_border(self, ok: bool):
        color = '#44bb44' if ok else '#bb3333'
        self._lfm_edit.setStyleSheet(
            f'QLineEdit{{background:{BG3};color:{FG};border:2px solid {color};'
            f'border-radius:4px;padding:0 6px;font-size:11px;}}'
        )

    def _make_worker(self):
        raise NotImplementedError

    def _on_track_done(self, *_args):
        raise NotImplementedError

    def _update_close_btn(self):
        """Show 'Run in\nbackground' while running, 'Close' otherwise."""
        if self._running:
            self._btn_close.setText('Run in\nbackground')
        else:
            self._btn_close.setText('Close')

    def _check_and_restore_background(self):
        """Check if there's an existing worker running in background and auto-restore UI."""
        workers_list = _BaseFetchPopup._active_workers.get(self._popup_type, [])
        if workers_list:
            # Find the most recent worker for this popup type
            old_instance, old_worker, old_thread = workers_list[-1]
            # Restore UI to show the existing running operation with full state
            self._thread = old_thread
            self._worker = old_worker
            self._running = True
            self._worker_id = old_instance._worker_id  # Reuse same worker ID
            self._status_widget_key = old_instance._status_widget_key
            self._btn_start.setEnabled(False)
            self._btn_cancel.setEnabled(True)
            # Restore progress, log, and track info from background state
            self._progress.setValue(old_instance._bg_progress)
            self._track_lbl.setText(f'[{old_instance._bg_progress}/{old_instance._bg_total}]  {old_instance._bg_track_name}')
            # Restore log items
            self._log.clear()
            for text, ok_flag in old_instance._bg_log_items:
                item = QListWidgetItem(text)
                item.setForeground(QColor('#55bb55') if ok_flag else QColor('#bb3333'))
                self._log.addItem(item)
            self._log.scrollToBottom()
            # Restore result label if present
            if old_instance._bg_result:
                self._result_lbl.setText(old_instance._bg_result)
            # Emit progress to main window status bar (reuses existing widget)
            self._emit_status_update()
            # Auto-show the dialog (it may have been hidden) - but don't auto-start since it's already running
            self.show()
            # Disconnect the old instance's UI slots before connecting this instance's slots.
            # Without this, both the old popup and the new popup would receive every signal,
            # causing progress updates, log entries and _on_finished to fire twice.
            try: old_worker.progress.disconnect(old_instance._on_progress)
            except Exception: pass
            try: old_worker.track_done.disconnect(old_instance._on_track_done)
            except Exception: pass
            try: old_worker.finished.disconnect(old_instance._on_finished)
            except Exception: pass
            # Connect this instance's slots
            self._worker.progress.connect(self._on_progress)
            self._worker.track_done.connect(self._on_track_done)
            self._worker.finished.connect(self._on_finished)
            self._update_close_btn()

    # ── common implementation ────────────────────────────────────────────────

    def _log_add(self, text: str, ok: bool):
        item = QListWidgetItem(text)
        item.setForeground(QColor('#55bb55') if ok else QColor('#bb3333'))
        self._log.addItem(item)
        self._log.scrollToBottom()
        # Store log item for background restoration
        self._bg_log_items.append((text, ok))

    def _start(self):
        if self._running:
            return
        
        self._running = True
        self._force   = self._force_cb.isChecked()   # subclasses read self._force in _make_worker
        self._log.clear()
        self._progress.setValue(0)
        self._result_lbl.setText('')
        self._btn_start.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._update_close_btn()

        worker = self._make_worker()
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.track_done.connect(self._on_track_done)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(thread.quit)
        self._thread = thread
        self._worker = worker
        # Generate unique ID for this worker instance if not already set
        if self._worker_id is None:
            self._worker_id = id(worker)
        if self._status_widget_key is None:
            self._status_widget_key = f"_fetch_widget_{self._worker_id}"
        # Register this worker as active for this popup type (support multiple concurrent workers)
        if self._popup_type not in _BaseFetchPopup._active_workers:
            _BaseFetchPopup._active_workers[self._popup_type] = []
        _BaseFetchPopup._active_workers[self._popup_type].append((self, worker, thread))
        thread.start()
        # Emit initial status update
        self._emit_status_update()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
        self._btn_cancel.setEnabled(False)
        self._track_lbl.setText('Cancelling…')

    def _really_close(self):
        """Actually close the dialog (bypassing the hide-guard in closeEvent)."""
        self._force_close = True
        self.reject()

    def _on_close(self):
        if self._running:
            # Hide the dialog but keep the thread running in background.
            # Remove the application-wide event filter so the hidden dialog
            # does not continue swallowing all mouse events.
            QApplication.instance().removeEventFilter(self)
            self.hide()
        else:
            # Nothing is running — just close the dialog
            self._really_close()

    def closeEvent(self, e):
        if getattr(self, '_force_close', False) or not self._running:
            # Allow genuine close when not running.
            # Always remove the event filter on a real close.
            QApplication.instance().removeEventFilter(self)
            self._force_close = False
            e.accept()
        else:
            # Hide instead of closing — keeps thread alive.
            # Remove the event filter so the hidden dialog does not swallow mouse events.
            QApplication.instance().removeEventFilter(self)
            self.hide()
            e.ignore()

    def _on_progress(self, current: int, total: int, name: str):
        self._progress.setValue(current)
        self._track_lbl.setText(f'[{current}/{total}]  {name}')
        # Store state for background restoration
        self._bg_progress = current
        self._bg_total = total
        self._bg_track_name = name
        # Emit progress to main window status bar
        self._emit_status_update()

    def _on_finished(self, found: int, total: int):
        self._running = False
        # Remove this specific worker from active workers list
        workers_list = _BaseFetchPopup._active_workers.get(self._popup_type, [])
        # Find and remove this worker by identity
        for i, (inst, wk, th) in enumerate(workers_list):
            if inst is self or wk is self._worker:
                workers_list.pop(i)
                break
        # Clean up empty lists
        if not workers_list:
            _BaseFetchPopup._active_workers.pop(self._popup_type, None)
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._track_lbl.setText('Done.')
        self._progress.setValue(total)
        result_msg = self._finished_msg(found, total)
        self._result_lbl.setText(result_msg)
        # Store result for background restoration
        self._bg_result = result_msg
        # Clean up thread references but don't quit (already quit via signal)
        self._thread = None
        self._worker = None
        # Clear status bar message
        self._emit_status_clear()
        self._update_close_btn()

    def _emit_status_update(self):
        """Emit progress status to main window status bar - shows all concurrent fetches."""
        if not self._running or not self._worker_id:
            return
        if not (hasattr(self, '_bg_progress') and hasattr(self, '_bg_total')):
            return
        
        # Determine fetch type label from the already-stored popup type name
        _TYPE_LABELS = {
            'CoverFetchPopup':  'Covers',
            'TagFetchPopup':    'Tags',
            'LyricsFetchPopup': 'Lyrics',
        }
        type_label = _TYPE_LABELS.get(self._popup_type, 'Fetch')
        
        msg = f"{type_label}: [{self._bg_progress}/{self._bg_total}] {self._bg_track_name}"
        # Find main window and update status bar
        win = self.parent()
        while win and not isinstance(win, MainWindow):
            win = win.parent()
        if win and hasattr(win, '_status'):
            # Use unique widget key for this specific worker instance
            widget_key = self._status_widget_key or f"_fetch_widget_{self._worker_id}"
            # Check if widget already exists
            old_lbl = getattr(win, widget_key, None)
            if old_lbl:
                # Update existing widget text instead of creating new one
                old_lbl.setText(msg)
            else:
                # Create new permanent widget
                lbl = QLabel(msg)
                lbl.setStyleSheet(f'color:{FG}; font-size:11px; padding: 0 8px;')
                win._status.addPermanentWidget(lbl, 0)
                setattr(win, widget_key, lbl)

    def _emit_status_clear(self):
        """Clear status bar message for this specific fetch instance when finished."""
        # Use unique widget key for this instance
        widget_key = self._status_widget_key or f"_fetch_widget_{self._worker_id}"
        
        win = self.parent()
        while win and not isinstance(win, MainWindow):
            win = win.parent()
        if win:
            old_lbl = getattr(win, widget_key, None)
            if old_lbl:
                old_lbl.deleteLater()
                setattr(win, widget_key, None)

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Processed {found} out of {total}.' 


# ══════════════════════════════════════════════════════════════════════════════
#  Library Cover Fetch Popup
# ══════════════════════════════════════════════════════════════════════════════
class LibraryCoverFetchWorker(QObject):
    """Fetches covers for an entire track list sequentially in a worker thread.
    Emits raw bytes per track so the UI thread builds QPixmap objects."""
    progress    = pyqtSignal(int, int, str)   # current_index, total, track_name
    track_done  = pyqtSignal(str, bytes, bool) # filepath, raw_bytes, found_flag
    finished    = pyqtSignal(int, int)        # found_count, total_count

    def __init__(self, tracks: list, force: bool = False):
        super().__init__()
        self._tracks    = list(tracks)
        self._force     = force
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # In force mode, process all tracks; otherwise skip tracks that already have a cover.
        if self._force:
            needs_fetch = [t for t in self._tracks if t.filepath not in _cover_locked_set]
        else:
            needs_fetch = [t for t in self._tracks
                           if extract_cover_bytes(t.filepath) is None
                           and t.filepath not in _cover_locked_set]
        total = len(needs_fetch)
        found = 0
        done  = 0
        for t in needs_fetch:
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            done += 1
            self.progress.emit(done, total, name)
            data = fetch_cover_online(t.artist or '', t.title or '', t.album or '',
                                      stop=lambda: self._cancelled)
            if data:
                found += 1
                self.track_done.emit(t.filepath, data, True)
            else:
                self.track_done.emit(t.filepath, b'', False)
        self.finished.emit(found, total)

class CoverFetchPopup(_BaseFetchPopup):
    """Modal dialog that fetches covers for tracks missing a cover."""

    def __init__(self, tracks: list, table_pages: list, ctrlbar, parent=None):
        self._pages   = table_pages
        self._ctrlbar = ctrlbar
        needs = [t for t in tracks
                 if extract_cover_bytes(t.filepath) is None
                 and t.filepath not in _cover_locked_set]
        info = (f'<b>{len(needs)}</b> tracks need a cover '
                f'(out of {len(tracks)} total — tracks with embedded covers skipped).')
        super().__init__(tracks, 'Fetch Covers', info, len(needs), parent)
        self._needs = needs

    def _make_worker(self):
        return LibraryCoverFetchWorker(self._tracks, force=self._force)

    def set_tracks(self, tracks: list):
        self._tracks = list(tracks)
        self._needs  = [t for t in tracks
                        if extract_cover_bytes(t.filepath) is None
                        and t.filepath not in _cover_locked_set]
        self._progress.setRange(0, max(1, len(self._needs)))

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Found covers for {found} out of {total} tracks.'

    def _on_track_done(self, fp: str, data: bytes, found: bool):
        name = Path(fp).stem
        if not found:
            self._log_add(f'FAIL  {name}', False)
            return
        self._log_add(f'OK    {name}', True)
        # Decode raw bytes to QPixmap — scale to master, then derive display sizes
        src_pm = QPixmap()
        if not src_pm.loadFromData(data):
            return
        # Store 220px master in memory and on disk
        master_pm = _square_pixmap(src_pm, _COVER_MASTER_SIZE)
        _cover_cache[(fp, _COVER_MASTER_SIZE)] = master_pm
        try:
            master_dkey = _cover_disk_key(fp)
            master_disk_path = _COVER_DISK_DIR / f'{master_dkey}.jpg'
            if not (master_disk_path.exists() and not _cover_disk_is_stale(fp, master_disk_path)):
                _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
                master_pm.save(str(master_disk_path), 'JPEG', _COVER_JPEG_QUALITY)
                _cover_disk_write_mtime(fp, master_disk_path)
        except Exception:
            pass
        # Derive display sizes from master (in-memory — no extra disk I/O)
        for size in (28, 64):
            _cover_cache[(fp, size)] = _square_pixmap(master_pm, size)
        _trim_cover_cache()
        threading.Thread(target=embed_cover_bytes, args=(fp, data), daemon=True).start()
        for page in self._pages:
            tracks = page.tracks if hasattr(page, 'tracks') else []
            for r, t in enumerate(tracks):
                if t.filepath == fp and r < page.table.rowCount():
                    item = page.table.item(r, 1)  # 1 = C_TIT
                    pm28 = _cover_cache.get((fp, 28))
                    if item and pm28:
                        item.setIcon(QIcon(pm28))
                    break
        if self._ctrlbar and self._ctrlbar._cur_track:
            if self._ctrlbar._cur_track.filepath == fp:
                pm64 = _cover_cache.get((fp, 64))
                if pm64 and self._ctrlbar._cover_lbl.isVisible():
                    self._ctrlbar._cover_lbl.setPixmap(pm64)



# ══════════════════════════════════════════════════════════════════════════════
