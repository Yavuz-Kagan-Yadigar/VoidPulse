"""
VoidPulse — library batch-fetch popups: LibraryTagFetchWorker, TagFetchPopup,
LibraryLyricsFetchWorker, LyricsFetchPopup.
"""
from constants import *
from metadata_online import lookup_tags_online, embed_lyrics, write_tags_to_file
from lyrics import _extract_embedded_lyrics, _src_lrclib_exact, _src_lrclib_search, _src_lyrics_ovh
from cover_art import _BaseFetchPopup

# ══════════════════════════════════════════════════════════════════════════════
#  Library Tag Fetch Worker + Popup
# ══════════════════════════════════════════════════════════════════════════════

class LibraryTagFetchWorker(QObject):
    """Fetches missing tags (title/artist/album) for library tracks sequentially.
    Progress is based only on tracks that are missing at least one tag."""
    progress   = pyqtSignal(int, int, str)        # current, total, track_name
    track_done = pyqtSignal(str, dict, bool)       # filepath, tags_dict, found_flag
    finished   = pyqtSignal(int, int)              # updated_count, total_needs

    def __init__(self, tracks: list, force: bool = False):
        super().__init__()
        self._tracks    = list(tracks)
        self._force     = force
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # In force mode, attempt a tag lookup for every track.
        if self._force:
            needs = list(self._tracks)
        else:
            needs = [t for t in self._tracks
                     if not (t.title.strip() and t.artist.strip() and t.album.strip())]
        total   = len(needs)
        updated = 0
        for i, t in enumerate(needs):
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            self.progress.emit(i + 1, total, name)
            tags = lookup_tags_online(t.artist or '', t.title or Path(t.filepath).stem,
                                      stop=lambda: self._cancelled)
            if tags:
                result = {}
                if not t.title.strip()  and tags.get('title'):  result['title']  = tags['title']
                if not t.artist.strip() and tags.get('artist'): result['artist'] = tags['artist']
                if not t.album.strip()  and tags.get('album'):  result['album']  = tags['album']
                if result:
                    updated += 1
                    self.track_done.emit(t.filepath, result, True)
                else:
                    self.track_done.emit(t.filepath, {}, False)
            else:
                self.track_done.emit(t.filepath, {}, False)
        self.finished.emit(updated, total)

class TagFetchPopup(_BaseFetchPopup):
    """Modal dialog that looks up missing tags for library tracks."""

    tags_updated = pyqtSignal(str, dict)

    def __init__(self, tracks: list, parent=None):
        needs = [t for t in tracks
                 if not (t.title.strip() and t.artist.strip() and t.album.strip())]
        info = (f'<b>{len(needs)}</b> tracks have at least one missing tag '
                f'(out of {len(tracks)} total — tracks with all tags are skipped).')
        super().__init__(tracks, 'Fetch Missing Tags', info, len(needs), parent)
        self._needs = needs

    def _make_worker(self):
        return LibraryTagFetchWorker(self._tracks, force=self._force)

    def set_tracks(self, tracks: list):
        self._tracks = list(tracks)
        self._needs  = [t for t in tracks
                        if not (t.title.strip() and t.artist.strip() and t.album.strip())]
        self._progress.setRange(0, max(1, len(self._needs)))

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Updated tags for {found} out of {total} tracks.'

    def _on_track_done(self, fp: str, tags: dict, found: bool):
        name = Path(fp).stem
        if not found or not tags:
            self._log_add(f'FAIL  {name}', False)
            return
        filled = ', '.join(f'{k}={v}' for k, v in tags.items())
        self._log_add(f'OK    {name}  [{filled}]', True)
        threading.Thread(target=write_tags_to_file, args=(fp, tags), daemon=True).start()
        self.tags_updated.emit(fp, tags)



# ══════════════════════════════════════════════════════════════════════════════
#  Library Lyrics Fetch Worker + Popup
# ══════════════════════════════════════════════════════════════════════════════

class LibraryLyricsFetchWorker(QObject):
    """Fetches and embeds lyrics for library tracks that have no embedded lyrics.
    Runs sequentially in a worker thread; emits per-track results back to the UI."""
    progress   = pyqtSignal(int, int, str)        # current, total, track_name
    track_done = pyqtSignal(str, bool)             # filepath, found_flag
    finished   = pyqtSignal(int, int)              # found_count, total_needs

    def __init__(self, tracks: list, force: bool = False):
        super().__init__()
        self._tracks    = list(tracks)
        self._force     = force
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # In force mode, process every track (overwrite existing embedded lyrics too).
        if self._force:
            needs = list(self._tracks)
        else:
            needs = [t for t in self._tracks if not any(_extract_embedded_lyrics(t.filepath))]
        total = len(needs)
        found = 0
        for i, t in enumerate(needs):
            if self._cancelled:
                break
            name = t.title or Path(t.filepath).stem
            self.progress.emit(i + 1, total, name)
            artist = (t.artist or '').strip()
            title  = (t.title  or '').strip()
            album  = (t.album  or '').strip()
            # Run the same multi-source fetch used by LyricsFetcher
            synced, plain = None, None
            for src_fn in [
                lambda: _src_lrclib_exact(artist, title, album, t.duration),
                lambda: _src_lrclib_search(artist, title),
                lambda: _src_lyrics_ovh(artist, title),
            ]:
                if self._cancelled:
                    break
                try:
                    s, p = src_fn()
                    if s:
                        synced = s; break
                    if p and not plain:
                        plain = p
                except Exception:
                    pass
            if synced or plain:
                ok = embed_lyrics(t.filepath, synced, plain)
                self.track_done.emit(t.filepath, ok)
                if ok:
                    found += 1
            else:
                self.track_done.emit(t.filepath, False)
        self.finished.emit(found, total)

class LyricsFetchPopup(_BaseFetchPopup):
    """Modal dialog that fetches and embeds lyrics for library tracks."""

    def __init__(self, tracks: list, parent=None):
        # ponytail: don't scan every track's embedded lyrics on the UI thread here —
        # on large libraries (thousands of tracks) that's a multi-second freeze, and
        # the worker thread (run(), below) recomputes the exact same "needs" list
        # anyway once it starts. Show the total count as a placeholder; the real
        # needs-count arrives via the progress signal and corrects the bar range
        # (see _BaseFetchPopup._on_progress).
        info = (f'Checking <b>{len(tracks)}</b> tracks for missing lyrics…')
        super().__init__(tracks, 'Fetch Lyrics', info, len(tracks), parent)
        self._needs = list(tracks)  # placeholder only; not used for worker logic

    def _make_worker(self):
        return LibraryLyricsFetchWorker(self._tracks, force=self._force)

    def set_tracks(self, tracks: list):
        self._tracks = list(tracks)
        self._needs  = list(tracks)  # placeholder; corrected once the worker reports real total
        self._progress.setRange(0, max(1, len(self._needs)))

    def _finished_msg(self, found: int, total: int) -> str:
        return f'Embedded lyrics for {found} out of {total} tracks.'

    def _on_track_done(self, fp: str, found: bool):
        name = Path(fp).stem
        self._log_add(f'{"OK  " if found else "FAIL"} {name}', found)


# ══════════════════════════════════════════════════════════════════════════════
