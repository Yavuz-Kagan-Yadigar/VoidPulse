"""
VoidPulse — track metadata and cover art: the Track dataclass, read_metadata(),
cover extraction and rendering, the memory/disk cover caches, and the
background cover loader (_CoverTask, AsyncCoverLoader).

The batch cover-fetch UI lives in fetch_popups.py.
"""
from constants import *
from constants import (ACC, BG, CONFIG_PATH, _DARK_MODE,
                       _sanitize_filename_part, _open_audio)
import re as _re
import numpy as _np
from dataclasses import field as _dc_field

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
    # ReplayGain track gain in dB. 0.0 means absent, which is also a no-op gain,
    # so callers need not tell untagged from an explicit 0 dB.
    rg_track_gain_db: float = 0.0
    # Cached lowercase search haystack, plus the field values it was built from.
    # Excluded from __eq__/__repr__ so Track compares exactly as before.
    _search_sig: tuple = _dc_field(default=(), repr=False, compare=False)
    _search_key: str   = _dc_field(default='', repr=False, compare=False)

    def search_key(self) -> str:
        """Lowercased title/artist/album/filename haystack for substring search.

        The search box filters the whole library on every keystroke, across both
        the table and the gallery, so this is cached instead of rebuilt per
        track per key. Comparing the signature is much cheaper than three
        .lower() calls plus a basename split, and it self-invalidates when a tag
        edit or a rename changes one of the source fields — no explicit
        cache-busting call sites to keep in sync.

        Fields are joined with '\n', which the single-line search QLineEdit
        cannot produce, so a query can never match across a field boundary.
        """
        sig = (self.title, self.artist, self.album, self.filepath)
        if sig != self._search_sig:
            self._search_sig = sig
            self._search_key = '\n'.join((
                self.title.lower(), self.artist.lower(), self.album.lower(),
                os.path.basename(self.filepath).lower()))
        return self._search_key

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
    """Case-insensitive tag lookup for Vorbis comments (FLAC/OGG/OPUS)."""
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

def _parse_gain_db(s: str):
    """Parse a ReplayGain tag value like '-3.20 dB' or '-3.20' into a float,
    or None if s doesn't contain a number (missing/malformed tag)."""
    if not s:
        return None
    m = _re.search(r'[-+]?\d+(?:\.\d+)?', s)
    return float(m.group(0)) if m else None


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
            # A TXXX frame keyed 'TXXX:<description>', whose casing is not
            # standardised — hence the case-insensitive scan.
            for k in tg.keys():
                if isinstance(k, str) and k.upper() == 'TXXX:REPLAYGAIN_TRACK_GAIN':
                    frame = tg[k]
                    txt = str(frame.text[0]) if getattr(frame, 'text', None) else ''
                    g = _parse_gain_db(txt)
                    if g is not None:
                        tr.rg_track_gain_db = g
                    break
        elif ext in ('.flac', '.opus', '.ogg'):
            tr.title  = _vtag(tg, 'title') or tr.title
            tr.artist = _vtag(tg, 'artist', 'albumartist')
            tr.album  = _vtag(tg, 'album')
            g = _parse_gain_db(_vtag(tg, 'REPLAYGAIN_TRACK_GAIN'))
            if g is not None:
                tr.rg_track_gain_db = g
        elif ext in ('.m4a', '.aac'):
            tr.title  = _tag(tg, '\xa9nam') or tr.title
            tr.artist = _tag(tg, '\xa9ART', 'aART'); tr.album = _tag(tg, '\xa9alb')
            # MP4 has no standard atom: it is a freeform '----:...' one
            for k, v in tg.items():
                if isinstance(k, str) and k.lower().endswith('replaygain_track_gain') and v:
                    try:
                        raw = v[0]
                        txt = raw.decode('utf-8', 'ignore') if isinstance(raw, (bytes, bytearray)) else str(raw)
                    except Exception:
                        txt = ''
                    g = _parse_gain_db(txt)
                    if g is not None:
                        tr.rg_track_gain_db = g
                    break
        else:
            tr.title  = _tag(tg, 'title',  'TITLE') or tr.title
            tr.artist = _tag(tg, 'artist', 'ARTIST'); tr.album = _tag(tg, 'album', 'ALBUM')
            g = _parse_gain_db(_tag(tg, 'replaygain_track_gain', 'REPLAYGAIN_TRACK_GAIN'))
            if g is not None:
                tr.rg_track_gain_db = g
    except Exception:
        pass
    return tr

# ── Cover art ─────────────────────────────────────────────────────────────────
_cover_cache: OrderedDict = OrderedDict()  # (fp, size) → QPixmap, LRU-ordered
_COVER_SENTINEL = object()  # distinguishes cache miss from cached None

# One master per track on disk; every smaller size is downscaled from it in
# memory. 220px is the largest gallery card cover, so it is the upper bound.
_COVER_MASTER_SIZE = 220

# 2000 entries is roughly 400 tracks at a master plus four derived sizes each
_COVER_CACHE_MAX = 2000

def _trim_cover_cache() -> None:
    """Evict from the front once the cache exceeds _COVER_CACHE_MAX.

    The dict is LRU-ordered, so the oldest entries go first — close enough to
    "no longer on screen" for a cover cache.
    """
    overflow = len(_cover_cache) - _COVER_CACHE_MAX
    if overflow > 0:
        trim = overflow + _COVER_CACHE_MAX // 4   # extra headroom, to avoid thrashing
        for key in list(_cover_cache.keys())[:trim]:
            _cover_cache.pop(key, None)

def _purge_orphan_disk_covers() -> None:
    """Delete disk covers that are not the 220px master.

    Older versions wrote one file per display size; this startup sweep removes
    them so the directory converges on a single file per track.
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

    Corners stay square here and are rounded at draw time by
    _draw_cover_rounded(), so the disk cache needs no transparency and one
    cached pixmap serves every radius setting.
    """
    pm = pm.scaled(size, size,
                   Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                   Qt.TransformationMode.SmoothTransformation)
    # KeepAspectRatioByExpanding can land 1px short through float→int truncation
    # (220 * 28/220 = 27.999…). Force the exact square when it does.
    if pm.width() < size or pm.height() < size:
        pm = pm.scaled(size, size,
                       Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    x = max(0, (pm.width()  - size) // 2)
    y = max(0, (pm.height() - size) // 2)
    return pm.copy(x, y, size, size)

def _draw_cover_rounded(painter: QPainter, pm: QPixmap,
                        x: int, y: int, size: int, radius: int) -> None:
    """Draw *pm* at (x,y) clipped to a rounded rect.

    Clipping rather than masking the corners with a matching-coloured overlay:
    the clip is correct whatever is painted behind the cover (fill, hover,
    selection, playing highlight, accent tint), with nothing to keep in sync.
    """
    if radius <= 0:
        painter.drawPixmap(x, y, size, size, pm)
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, size, size), radius, radius)
    painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
    painter.drawPixmap(x, y, size, size, pm)
    painter.restore()


def _default_cover_disk_path(acc: str, bg: str, size: int) -> Path:
    safe_acc = acc.lstrip('#')
    safe_bg  = bg.lstrip('#')
    # The master is PNG (lossless); derived sizes were JPEG in older versions
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
    """Return the clef-placeholder cover as a plain square pixmap.

    Same master-and-downscale scheme as real covers: one 220px master per
    (accent, background) pair, cached in memory and on disk, with every other
    size derived from it.
    """
    master_key = ('__default__', _DEFAULT_COVER_MASTER_SIZE, ACC, BG)
    master_pm = _default_cover_mem_cache.get(master_key)
    if master_pm is None:
        disk = _default_cover_disk_path(ACC, BG, _DEFAULT_COVER_MASTER_SIZE)
        if disk.exists():
            pm = QPixmap()
            if pm.load(str(disk)):
                master_pm = pm
        if master_pm is None:
            master_pm = _render_default_cover_master(_DEFAULT_COVER_MASTER_SIZE)
            # PNG so the master stays lossless
            try:
                disk.parent.mkdir(parents=True, exist_ok=True)
                master_pm.save(str(disk), 'PNG')
            except Exception:
                pass
        _default_cover_mem_cache[master_key] = master_pm

    if size == _DEFAULT_COVER_MASTER_SIZE:
        return master_pm

    mem_key = ('__default__', size, ACC, BG)
    pm = _default_cover_mem_cache.get(mem_key)
    if pm is None:
        pm = _square_pixmap(master_pm, size)
        _default_cover_mem_cache[mem_key] = pm
    return pm

_COVER_DISK_DIR  = CONFIG_PATH.parent / 'covers'
_cover_fetch_on  = True   # module-level flag — updated by ControlBar
_cover_locked_set: set = set()   # filepaths that must not auto-fetch
_COVER_JPEG_QUALITY = 80

# Non-fatal if it fails, e.g. in a read-only sandbox
try:
    _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

def _cover_disk_key(fp: str) -> str:
    """Persistent disk cache key: <sanitized_stem>_<path_hash>_220.

    One master file per track at _COVER_MASTER_SIZE (220px); smaller display
    sizes are derived in memory, so no per-size files exist.

    The hash of the full path is what makes the key unique: two tracks with the
    same filename in different folders (a studio and a live version, the same
    track on two albums) would otherwise share one cache file and end up showing
    each other's artwork. The stem prefix is only there to keep the directory
    readable.

    A sidecar <name>.mtime file records the audio file's mtime at extraction
    time, so a re-tagged file is detected as stale and re-read.
    """
    stem = _sanitize_filename_part(Path(fp).stem)
    # Cap the readable part; the hash suffix is what guarantees uniqueness.
    if len(stem) > 100:
        stem = stem[:100]
    path_hash = hashlib.sha1(str(Path(fp).resolve()).encode('utf-8', 'surrogateescape')).hexdigest()[:10]
    return f'{stem}_{path_hash}_{_COVER_MASTER_SIZE}'

def _cover_disk_is_stale(fp: str, disk_path: Path) -> bool:
    """True when the cached cover predates the audio file's current mtime.

    The mtime at extraction time lives in a ``<disk_path>.mtime`` sidecar; a
    mismatch or a missing sidecar counts as stale.
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

# Toggled by ControlBar._on_cover_acc_toggle
_COVER_ACC_ON: bool = False

# Brightness → colour lookup tables, built once per accent and theme and shared
# across every cover size. Key: (hue, saturation, dark mode).
_acc_lut_cache: dict = {}   # (acc_h, acc_s, dark) → (lut_r, lut_g, lut_b)

# Recoloured results. Without this every get_cover_pixmap() hit re-ran the whole
# LUT pass — six image copies per call — so each visible row paid for it again
# on every repaint and every scroll frame.
#
# Keyed on (file, size, palette), i.e. the cover's own identity, NOT on
# QPixmap.cacheKey(): Qt recycles a cache key once its pixmap is freed, so a
# key-based memo eventually hands a newly created cover the recoloured image
# belonging to a long-gone one. The source's cacheKey is still stored alongside
# the result and re-checked on every hit, so a cover re-read at the same size
# (new artwork for the same file) misses instead of serving the old picture.
_recolor_cache: OrderedDict = OrderedDict()  # (fp, size, hue, sat, dark) → (src key, QPixmap)
_RECOLOR_CACHE_MAX = 512


def _trim_recolor_cache() -> None:
    overflow = len(_recolor_cache) - _RECOLOR_CACHE_MAX
    if overflow > 0:
        for _ in range(overflow + _RECOLOR_CACHE_MAX // 4):
            if not _recolor_cache:
                break
            _recolor_cache.popitem(last=False)


def _recolor_cached(fp: str, size: int, pm: QPixmap) -> QPixmap:
    """Memoized _recolor_pixmap for the cover *fp* at *size*."""
    acc_h, acc_s, _, _ = QColor(ACC).getHsv()
    key = (fp, size, acc_h, acc_s, _DARK_MODE)
    src_key = pm.cacheKey()
    hit = _recolor_cache.get(key)
    if hit is not None and hit[0] == src_key:
        _recolor_cache.move_to_end(key)   # most recently used
        return hit[1]
    out = _recolor_pixmap(pm)
    _recolor_cache[key] = (src_key, out)
    _trim_recolor_cache()
    return out


def _recolor_pixmap(pm: QPixmap) -> QPixmap:
    """Return pm recoloured using a luminance LUT.

    Dark mode:  black (v=0)  → accent (v=255)
    Light mode: accent (v=0) → white  (v=255)
    """
    acc_h, acc_s, _, _ = QColor(ACC).getHsv()
    cache_key = (acc_h, acc_s, _DARK_MODE)
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
    # Read whole rows including any padding, then slice the pixel bytes out:
    # bytesPerLine can exceed w*4 and a plain reshape would smear rows.
    raw = _np.frombuffer(ptr, dtype=_np.uint8).reshape(h, stride).copy()
    del img
    arr = raw[:, : w * 4].reshape(h * w, 4)   # pixel columns only
    # Qt RGB32 LE layout: B G R 0xFF
    y8 = ((arr[:, 2].astype(_np.uint16) * 2 +
           arr[:, 1].astype(_np.uint16) * 5 +
           arr[:, 0].astype(_np.uint16)) >> 3).clip(0, 255).astype(_np.uint8)
    out = arr.copy()
    out[:, 0] = lut_b[y8]
    out[:, 1] = lut_g[y8]
    out[:, 2] = lut_r[y8]
    # .copy() forces the pixels into Qt-owned memory before the pixmap is built.
    # QImage does not take ownership of the bytes it is handed, so without this
    # the pixmap aliases a temporary that is freed the moment this returns —
    # harmless when the result is drawn immediately, but the caller caches it,
    # and a cached pixmap over freed memory paints as garbage.
    img_out = QImage(out.tobytes(), w, h, w * 4, QImage.Format.Format_RGB32).copy()
    return QPixmap.fromImage(img_out)

def get_cover_pixmap(fp: str, size: int = 48) -> Optional[QPixmap]:
    """Return a cached square pixmap, or None. Memory only, never blocks.

    Corners stay square; callers round them at draw time with
    _draw_cover_rounded(), so one pixmap serves every radius.

    In order: an exact-size hit, a downscale of the cached 220px master, a
    downscale of any larger cached size, or None plus a queued async load that
    reads the master from disk or the file's tags.
    """
    key = (fp, size)
    cached = _cover_cache.get(key, _COVER_SENTINEL)
    if cached is not _COVER_SENTINEL:
        _cover_cache.move_to_end(key)   # most recently used
        return (_recolor_cached(fp, size, cached)
                if (_COVER_ACC_ON and cached is not None) else cached)

    master = _cover_cache.get((fp, _COVER_MASTER_SIZE), _COVER_SENTINEL)
    if master is not _COVER_SENTINEL and master is not None:
        if size == _COVER_MASTER_SIZE:
            return _recolor_cached(fp, size, master) if _COVER_ACC_ON else master
        pm = _square_pixmap(master, size)
        _cover_cache[key] = pm
        _trim_cover_cache()
        return _recolor_cached(fp, size, pm) if _COVER_ACC_ON else pm

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
        return _recolor_cached(fp, size, pm) if _COVER_ACC_ON else pm

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
            master_dkey = _cover_disk_key(fp)
            master_disk_path = _COVER_DISK_DIR / f'{master_dkey}.jpg'

            # Another task may already have loaded the master while this one was
            # queued. QPixmap must not be touched outside the GUI thread, so let
            # the main thread scale the cached master instead of re-encoding it
            # here; that also skips a pointless lossy JPEG round trip.
            if (fp, _COVER_MASTER_SIZE) in _cover_cache:
                self._loader._derive_ready.emit(fp, size)
                return

            # The master on disk is already a square 220px JPEG
            if master_disk_path.exists() and not _cover_disk_is_stale(fp, master_disk_path):
                try:
                    with open(str(master_disk_path), 'rb') as f:
                        master_raw = f.read()
                    if master_raw:
                        sidecar = Path(str(master_disk_path) + '.mtime')
                        if not sidecar.exists():
                            _cover_disk_write_mtime(fp, master_disk_path)
                        if size == _COVER_MASTER_SIZE:
                            self._loader._raw_ready.emit(fp, size, master_raw, '')
                        else:
                            self._loader._post_raw_master(fp, size, master_raw,
                                                          str(master_disk_path))
                        return
                except Exception:
                    pass  # fall through to full load

            # Nothing cached — read the cover out of the file's tags
            data = extract_cover_bytes(fp)
            if data:
                img = QImage()
                img.loadFromData(data)
                if not img.isNull():
                    self._loader._post_image(fp, size, img, str(master_disk_path))
                    return

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
    # the master is already cached in memory; the main thread just rescales it
    _derive_ready = pyqtSignal(str, int)  # fp, requested_size

    def __init__(self, parent=None):
        super().__init__(parent)
        self._in_flight: set = set()
        self._no_embed:  set = set()
        self._lock = threading.Lock()
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max(2, self._pool.maxThreadCount()))
        self._master_ready.connect(self._on_master_ready, Qt.ConnectionType.QueuedConnection)
        self._raw_ready.connect(self._on_raw_ready, Qt.ConnectionType.QueuedConnection)
        self._derive_ready.connect(self._on_derive_ready, Qt.ConnectionType.QueuedConnection)

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
        """Hand a master read from disk to the main thread. Worker thread.

        The empty disk path tells _on_master_ready the file is already there, so
        it caches, derives the requested size and skips the write.
        """
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
        _cover_cache[(fp, _COVER_MASTER_SIZE)] = master_pm
        if size != _COVER_MASTER_SIZE:
            pm = _square_pixmap(master_pm, size)
            _cover_cache[(fp, size)] = pm
        _trim_cover_cache()
        if master_disk_path:
            try:
                _COVER_DISK_DIR.mkdir(parents=True, exist_ok=True)
                with open(master_disk_path, 'wb') as f:
                    f.write(master_raw)
                _cover_disk_write_mtime(fp, Path(master_disk_path))
            except Exception:
                pass
        self.cover_loaded.emit(fp, size)

    def _on_derive_ready(self, fp: str, size: int):
        """Scale the already-cached 220px master down to size. Main thread."""
        with self._lock:
            self._in_flight.discard((fp, size))
        master_pm = _cover_cache.get((fp, _COVER_MASTER_SIZE))
        if master_pm is None:
            return   # evicted between the worker's check and this call
        if size != _COVER_MASTER_SIZE:
            _cover_cache[(fp, size)] = _square_pixmap(master_pm, size)
            _trim_cover_cache()
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

# Shared by every view; use _ensure_async_cover_loader() to reach it
_async_cover_loader: Optional['AsyncCoverLoader'] = None

def _ensure_async_cover_loader() -> 'AsyncCoverLoader':
    global _async_cover_loader
    if _async_cover_loader is None:
        _async_cover_loader = AsyncCoverLoader()
    return _async_cover_loader




# ══════════════════════════════════════════════════════════════════════════════
