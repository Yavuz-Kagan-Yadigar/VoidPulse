"""
VoidPulse — reading files off network shares that cannot seek.

GVfs exposes some backends as sequential-only streams: FTP and FTPS in
particular. Measured against local servers, `can_seek()` is False at the GIO
level and `seek()` raises through the FUSE mount, so nothing downstream can do
random access. That breaks two separate things, which this module fixes
separately:

  * **Tag reading.** mutagen seeks constantly, so tags, durations, sample rate
    and embedded covers all came back empty. `SeekableProxy` gives it a
    file-like object that satisfies seeks from a spill buffer of what has
    already been read. It is lazy — seeking alone fetches nothing — so reading
    a FLAC header still only pulls the head of the file.

  * **Playback seeking.** Playback streams straight off the share, as before.
    The first time a seek is asked for, `copy_to_local()` fetches the track to
    real disk and the pipeline reopens from there; every seek after that is
    instant. Nothing is fetched for a track that is only listened to.

    Two earlier designs were measured and dropped. GStreamer's own download
    buffering needs the share's `ftp://` URI to engage at all, and in that
    configuration Ogg/Opus fails to demux on plain FTP every time. Fetching in
    the background while the track played looked better but was worse: one GVfs
    FTP mount serves one reader at a time, so on a 120 KiB/s link the copy
    pushed the start of playback from 4.5 s to 33 s with the link mostly idle.
    Hence one reader at a time, and only when seeking needs it.

Nothing here imports from the rest of VoidPulse: constants.py uses it, and
constants.py is the module everything else is built on.
"""
import os
import tempfile

# uri → (fuse_root, seekable). Populated by MainWindow once the mount's seek
# probe answers; consulted on every tag read, so the lookups stay O(#shares)
# string comparisons with no I/O.
_shares: dict = {}

# Bytes held in memory before a proxy spills to a temp file. Tag reads normally
# stay far below this; the ceiling only matters for formats that make mutagen
# walk deep into the file.
_SPILL_MAX_MEM = 8 * 1024 * 1024


# ── share registry ──────────────────────────────────────────────────────────

def register_share(uri: str, fuse_root: str, seekable) -> None:
    """Record a mounted share and whether its FUSE mount supports seeking.

    `seekable` is True/False/None exactly as remote.probe_seekable() reports it;
    None (nothing on the share to test) is treated as seekable, which is the
    behaviour every share had before this module existed.
    """
    if not uri or not fuse_root:
        return
    _shares[uri] = (os.path.normpath(fuse_root), seekable is not False)


def forget_share(uri: str) -> None:
    _shares.pop(uri, None)


def _match(path: str):
    """(uri, fuse_root) of the share holding `path`, or None."""
    if not path or not _shares:
        return None
    p = os.path.normpath(path)
    for uri, (root, _seekable) in _shares.items():
        if p == root or p.startswith(root + os.sep):
            return uri, root
    return None


def is_nonseekable(path: str) -> bool:
    """True iff `path` lives on a mounted share known to reject seeks."""
    hit = _match(path)
    if hit is None:
        return False
    return not _shares[hit[0]][1]


# ── local copies, so that seeking has something to seek in ──────────────────

_COPY_PREFIX = 'vpbuf-'
# Small enough that progress moves visibly on a slow link: at 120 KiB/s a
# 512 KiB chunk only reports every ~4 s, which reads as a frozen UI.
_COPY_CHUNK  = 64 * 1024


def buffer_dir() -> str:
    """Where local copies of remote tracks live while they are playing.

    Deliberately not /tmp: that is tmpfs on most systems, so a copy of a 100 MB
    FLAC would be spent out of RAM. The cache directory is real disk. Nothing
    here is meant to survive the track that needed it — see discard_local() and
    sweep_buffers().
    """
    d = os.path.join(
        os.environ.get('XDG_CACHE_HOME', os.path.join(os.path.expanduser('~'), '.cache')),
        'voidpulse', 'buffer')
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = tempfile.gettempdir()
    return d


def copy_to_local(src: str, cancel=None, progress=None):
    """Copy a file off a non-seekable share to local disk. Returns the path.

    Sequential reads are all these mounts support, and all this needs. Raises
    if it is cancelled or cannot finish, having first deleted what it wrote —
    a partial file must never be returned, or the caller would cheerfully play
    half a track and call it the end.
    """
    ext = os.path.splitext(src)[1]
    fd, dest = tempfile.mkstemp(prefix=_COPY_PREFIX, suffix=ext, dir=buffer_dir())
    total = 0
    try:
        size = os.path.getsize(src)
    except OSError:
        size = 0
    done = 0
    last_pct = -1
    try:
        with os.fdopen(fd, 'wb') as out, open(src, 'rb', buffering=0) as fh:
            while True:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError
                chunk = fh.read(_COPY_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                total += len(chunk)
                if progress is not None and size:
                    pct = min(99, int(done * 100 / size))
                    if pct != last_pct:
                        last_pct = pct
                        progress(pct)
        if size and total < size:
            raise OSError(f'short read: {total} of {size} bytes')
        if progress is not None:
            progress(100)
        return dest
    except Exception:
        try:
            os.unlink(dest)
        except OSError:
            pass
        raise


def discard_local(path) -> None:
    """Delete a local copy. Ignores anything that is not one of ours."""
    if not path:
        return
    try:
        if os.path.dirname(os.path.normpath(path)) != buffer_dir():
            return
        os.unlink(path)
    except OSError:
        pass


def sweep_buffers() -> None:
    """Delete copies left behind by a previous run.

    A clean shutdown removes its own, so anything still here is the residue of
    a crash or a kill.
    """
    d = buffer_dir()
    try:
        names = os.listdir(d)
    except OSError:
        return
    for name in names:
        if not name.startswith(_COPY_PREFIX):
            continue
        try:
            os.unlink(os.path.join(d, name))
        except OSError:
            pass


# ── seekable view of a sequential stream ────────────────────────────────────

class SeekableProxy:
    """A seekable file-like view of a stream that only reads forward.

    Bytes are pulled from the underlying file only when `read()` asks for ones
    that have not been seen yet; everything read so far is retained so that
    backward seeks — which is most of what mutagen does — are free. `seek()`
    itself never transfers anything, so `seek(0, SEEK_END)` to measure the file
    costs nothing (the size comes from stat, which these mounts do answer).

    Not thread-safe: one instance belongs to one read.
    """

    def __init__(self, path: str):
        self.name = path
        self._fh = open(path, 'rb', buffering=0)
        try:
            self._size = os.fstat(self._fh.fileno()).st_size
        except OSError:
            self._size = 0
        self._pos = 0          # logical position, what tell() reports
        self._got = 0          # bytes pulled from the source so far
        self._mem = bytearray()
        self._spill = None     # temp file, once _mem would exceed _SPILL_MAX_MEM

    # -- internals --

    def _spill_over(self):
        """Move the in-memory buffer to a temp file and keep growing there."""
        self._spill = tempfile.TemporaryFile()
        self._spill.write(self._mem)
        self._mem = bytearray()

    def _store(self, chunk: bytes):
        if self._spill is not None:
            self._spill.seek(0, os.SEEK_END)
            self._spill.write(chunk)
        else:
            self._mem += chunk
            if len(self._mem) > _SPILL_MAX_MEM:
                self._spill_over()
        self._got += len(chunk)

    def _pull_to(self, target: int):
        """Read forward from the source until `target` bytes have been seen."""
        while self._got < target:
            chunk = self._fh.read(min(1 << 20, target - self._got))
            if not chunk:
                break            # short file, or the server ended the transfer
            self._store(chunk)

    def _slice(self, start: int, end: int) -> bytes:
        if self._spill is not None:
            self._spill.seek(start)
            return self._spill.read(end - start)
        return bytes(self._mem[start:end])

    # -- file API --

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            end = self._size if self._size else self._got
            self._pull_to(max(end, self._got))
            # A stat-less stream keeps going until the source runs dry
            while True:
                before = self._got
                self._pull_to(self._got + (1 << 20))
                if self._got == before:
                    break
            end = self._got
        else:
            end = min(self._pos + n, self._size) if self._size else self._pos + n
            self._pull_to(end)
            end = min(end, self._got)
        start = min(self._pos, self._got)
        if end <= start:
            self._pos = max(self._pos, start)
            return b''
        data = self._slice(start, end)
        self._pos = end
        return data

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence == os.SEEK_SET:
            new = offset
        elif whence == os.SEEK_CUR:
            new = self._pos + offset
        elif whence == os.SEEK_END:
            new = (self._size or self._got) + offset
        else:
            raise ValueError(f'invalid whence: {whence}')
        self._pos = max(0, new)
        return self._pos

    def tell(self) -> int:
        return self._pos

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def close(self):
        try:
            self._fh.close()
        finally:
            if self._spill is not None:
                try:
                    self._spill.close()
                except OSError:
                    pass
                self._spill = None
            self._mem = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False
