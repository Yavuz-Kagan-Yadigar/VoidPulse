"""
VoidPulse — lyrics engine: LRC parser, embedded tag extractor, online sources
(LrcLib, Lyrics.ovh, ChartLyrics, Genius, AZLyrics, SongLyrics, Letras),
LyricsFetcher worker, LyricsPanel display widget.
"""
from constants import *
from constants import ACC, B2, BG, BG2, BORD, FG2, _open_audio
# embed_lyrics is imported lazily inside the function that uses it (below) to
# avoid a circular import: metadata_online imports _get/_get_json from this
# module at load time, so importing metadata_online back here at module level
# fails depending on which module happens to be imported first.
import re as _re
import html as _html
import urllib.request as _urlreq
import urllib.parse as _urlparse

# ══════════════════════════════════════════════════════════════════════════════
#  Lyrics — fetch, parse, display
# ══════════════════════════════════════════════════════════════════════════════
# ── LRC parser ────────────────────────────────────────────────────────────────
_LRC_LINE_RE = _re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)')

def _lrc_parse(text: str):
    lines = []
    for raw in text.splitlines():
        m = _LRC_LINE_RE.match(raw.strip())
        if m:
            mm, ss_str, txt = m.groups()
            ms = int(mm) * 60000 + round(float(ss_str) * 1000)
            lines.append((ms, txt.strip()))
    return sorted(lines, key=lambda x: x[0]) if lines else None

# ── Embedded tags ─────────────────────────────────────────────────────────────
def _extract_embedded_lyrics(fp: str):
    try:
        af = _open_audio(fp)
        if af is None or af.tags is None:
            return None, None
        ext = Path(fp).suffix.lower()
        if ext == '.mp3':
            from mutagen.id3 import USLT, SYLT
            for tag in af.tags.values():
                if isinstance(tag, SYLT):
                    lines = sorted([(ms, t) for t, ms in tag.text if t.strip()],
                                   key=lambda x: x[0])
                    if lines: return lines, None
            for tag in af.tags.values():
                if isinstance(tag, USLT) and tag.text.strip():
                    p = _lrc_parse(tag.text)
                    return (p, None) if p else (None, tag.text.strip())
        else:
            tg = af.tags
            # Check synced-lyrics tags first (stored by LRC-aware taggers)
            for key in ('syncedlyrics', 'SYNCEDLYRICS'):
                v = tg.get(key)
                if v:
                    text = str(v[0]) if isinstance(v, list) else str(v)
                    if text.strip():
                        p = _lrc_parse(text)
                        if p:
                            return p, None
            # Fall back to plain/unsynced tags; try LRC parse in case they contain timestamps
            for key in ('lyrics', 'LYRICS', 'unsyncedlyrics', 'UNSYNCEDLYRICS'):
                v = tg.get(key)
                if v:
                    text = str(v[0]) if isinstance(v, list) else str(v)
                    if text.strip():
                        p = _lrc_parse(text)
                        return (p, None) if p else (None, text.strip())
    except Exception:
        pass
    return None, None

# ── Network helpers ───────────────────────────────────────────────────────────
def _get(url, timeout=8, headers=None):
    h = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) VoidPulse/2.0'}
    if headers: h.update(headers)
    req = _urlreq.Request(url, headers=h)
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')

def _get_json(url, timeout=8, headers=None):
    return json.loads(_get(url, timeout, headers))

def _apply_scroller_properties(widget, *, touch: bool = True):
    """Apply standard kinetic-scroll properties to a viewport widget.

    ``touch=True`` (default) adds the tight DragStartDistance / AcceleratingFlickMaximumTime
    values that make touch flicks feel immediate.  Pass ``touch=False`` for mouse-only
    scroll targets (e.g. the EQ band table) where a looser start distance is acceptable.
    """
    SM = QScrollerProperties.ScrollMetric
    OP = QScrollerProperties.OvershootPolicy
    sp = QScrollerProperties()
    sp.setScrollMetric(SM.DecelerationFactor,           0.35)
    sp.setScrollMetric(SM.MaximumVelocity,              0.8)
    sp.setScrollMetric(SM.VerticalOvershootPolicy,      OP.OvershootAlwaysOff)
    sp.setScrollMetric(SM.HorizontalOvershootPolicy,    OP.OvershootAlwaysOff)
    if touch:
        sp.setScrollMetric(SM.AcceleratingFlickMaximumTime, 0.15)
        sp.setScrollMetric(SM.DragStartDistance,            0.005)
    QScroller.scroller(widget).setScrollerProperties(sp)


# ── Source functions — each returns (synced|None, plain|None) or (None, text) ─

def _src_lrclib_exact(artist, title, album, dur):
    try:
        p = _urlparse.urlencode({'artist_name': artist, 'track_name': title,
                                  'album_name': album, 'duration': int(dur)})
        d = _get_json(f'https://lrclib.net/api/get?{p}')
        sl = d.get('syncedLyrics') or ''
        pl = d.get('plainLyrics')  or ''
        if sl.strip():
            lrc = _lrc_parse(sl)
            if lrc: return lrc, None
        if pl.strip(): return None, pl.strip()
    except Exception: pass
    return None, None

def _src_lrclib_search(artist, title):
    try:
        q = _urlparse.quote(f'{artist} {title}')
        results = _get_json(f'https://lrclib.net/api/search?q={q}')
        best_plain = None
        for item in results[:6]:
            sl = item.get('syncedLyrics') or ''
            pl = item.get('plainLyrics')  or ''
            if sl.strip():
                lrc = _lrc_parse(sl)
                if lrc:
                    return lrc, None          # synced found — return immediately
            if pl.strip() and best_plain is None:
                best_plain = pl.strip()       # cache plain; keep searching for synced
        if best_plain:
            return None, best_plain
    except Exception:
        pass
    return None, None

def _src_lyrics_ovh(artist, title):
    try:
        a = _urlparse.quote(artist); t = _urlparse.quote(title)
        d = _get_json(f'https://api.lyrics.ovh/v1/{a}/{t}')
        txt = (d.get('lyrics') or '').strip()
        if txt: return None, txt
    except Exception: pass
    return None, None

def _src_chartlyrics(artist, title):
    try:
        a = _urlparse.quote(artist); t = _urlparse.quote(title)
        xml = _get(f'http://api.chartlyrics.com/apiv1.asmx/SearchLyricDirect?artist={a}&song={t}')
        m = _re.search(r'<Lyric>(.*?)</Lyric>', xml, _re.DOTALL)
        if m:
            txt = _html.unescape(m.group(1)).strip()
            if txt and len(txt) > 30: return None, txt
    except Exception: pass
    return None, None


def _src_genius_search(artist, title):
    # Genius web scraping — no API key
    try:
        q = _urlparse.quote(f'{artist} {title}')
        html_txt = _get(f'https://genius.com/search?q={q}',
                        headers={'Accept': 'text/html'})
        # Find first hit URL
        m = _re.search(r'"url":"(https://genius\.com/[^"]+lyrics[^"]*)"', html_txt)
        if not m: return None, None
        url = m.group(1)
        page = _get(url, headers={'Accept': 'text/html'})
        # Extract lyrics containers
        parts = _re.findall(
            r'<div[^>]*data-lyrics-container[^>]*>(.*?)</div>',
            page, _re.DOTALL)
        if not parts: return None, None
        lines = []
        for part in parts:
            clean = _re.sub(r'<br\s*/?>', '\n', part)
            clean = _re.sub(r'<[^>]+>', '', clean)
            lines.append(_html.unescape(clean).strip())
        txt = '\n'.join(lines).strip()
        if txt and len(txt) > 30: return None, txt
    except Exception: pass
    return None, None

def _src_azlyrics(artist, title):
    try:
        a = _re.sub(r'[^a-z0-9]', '', artist.lower())
        t = _re.sub(r'[^a-z0-9]', '', title.lower())
        url = f'https://www.azlyrics.com/lyrics/{a}/{t}.html'
        page = _get(url, headers={'Accept': 'text/html'}, timeout=9)
        m = _re.search(
            r'<!-- Usage of azlyrics.*?-->\s*(.*?)\s*</div>',
            page, _re.DOTALL)
        if m:
            raw = _re.sub(r'<[^>]+>', '', m.group(1))
            txt = _html.unescape(raw).strip()
            if txt and len(txt) > 30: return None, txt
    except Exception: pass
    return None, None

def _src_songlyrics(artist, title):
    try:
        a = _re.sub(r'[^a-z0-9-]', '-', artist.lower()).strip('-')
        t = _re.sub(r'[^a-z0-9-]', '-', title.lower()).strip('-')
        url = f'https://www.songlyrics.com/{a}/{t}-lyrics/'
        page = _get(url, headers={'Accept': 'text/html'})
        m = _re.search(r'<p id="songLyricsDiv"[^>]*>(.*?)</p>', page, _re.DOTALL)
        if m:
            raw = _re.sub(r'<[^>]+>', '', m.group(1))
            txt = _html.unescape(raw).strip()
            if txt and 'not found' not in txt.lower() and len(txt) > 30:
                return None, txt
    except Exception: pass
    return None, None

def _src_letras(artist, title):
    try:
        a = _re.sub(r'[^a-z0-9-]', '-', artist.lower()).strip('-')
        t = _re.sub(r'[^a-z0-9-]', '-', title.lower()).strip('-')
        url = f'https://www.letras.mus.br/{a}/{t}/'
        page = _get(url, headers={'Accept': 'text/html'})
        m = _re.search(r'<div class="lyric-original">(.*?)</div>', page, _re.DOTALL)
        if m:
            raw = _re.sub(r'<br\s*/?>', '\n', m.group(1))
            raw = _re.sub(r'<[^>]+>', '', raw)
            txt = _html.unescape(raw).strip()
            if txt and len(txt) > 30: return None, txt
    except Exception: pass
    return None, None

# ── Fetcher — sequential sources with status callbacks ────────────────────────
class ClickableLyricLine(QLabel):
    clicked = pyqtSignal(int)  # emits timestamp ms

    def __init__(self, text: str, ms: int, parent=None):
        super().__init__(text, parent)
        self._ms = ms
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._ms)
        super().mousePressEvent(e)

class LyricsFetcher(QObject):
    finished = pyqtSignal(object, object)   # synced|None, plain|None
    status   = pyqtSignal(str)              # progress message

    def __init__(self, track, fetch_online: bool = True):
        super().__init__()
        self._t = track
        self._fetch_online = fetch_online
        self.was_online = False   # set True if result came from network

    def run(self):
        t = self._t
        artist = (t.artist or '').strip()
        title  = (t.title  or '').strip()
        album  = (t.album  or '').strip()

        # 1. Embedded tags — instant, no network required
        self.status.emit('Checking embedded tags…')
        synced, plain = _extract_embedded_lyrics(t.filepath)
        if synced or plain:
            self.finished.emit(synced, plain)
            return

        if not self._fetch_online:
            self.status.emit('')
            self.finished.emit(None, None)
            return

        # 2. Two-phase online search:
        #    Phase A — fast, reliable sources (LrcLib has synced, Lyrics.ovh is quick).
        #              Return immediately on first synced result.  If Phase A finishes
        #              with a plain result, skip slow sources — plain is sufficient.
        #    Phase B — only when Phase A returns empty; web scrapers; wait up to 2 s
        #              for synced after first plain result, then deliver whatever we have.
        fast_sources = [
            ('LrcLib (exact)',  lambda: _src_lrclib_exact(artist, title, album, t.duration)),
            ('LrcLib (search)', lambda: _src_lrclib_search(artist, title)),
            ('Lyrics.ovh',      lambda: _src_lyrics_ovh(artist, title)),
        ]
        slow_sources = [
            ('Genius',          lambda: _src_genius_search(artist, title)),
            ('AZLyrics',        lambda: _src_azlyrics(artist, title)),
            ('SongLyrics',      lambda: _src_songlyrics(artist, title)),
            ('ChartLyrics',     lambda: _src_chartlyrics(artist, title)),
            ('Letras.mus.br',   lambda: _src_letras(artist, title)),
        ]

        result_lock  = threading.Lock()
        best_synced  = [None]
        best_plain   = [None]

        def _run_source(fn):
            # Lock-free early exit — read-only check without lock is safe under CPython GIL
            if best_synced[0] is not None:
                return
            try:
                s, p = fn()
            except Exception:
                return
            with result_lock:
                if s and best_synced[0] is None:
                    best_synced[0] = s
                # plain is only saved when synced has not been found;
                # otherwise the receiver may choose the wrong format
                elif p and best_plain[0] is None and best_synced[0] is None:
                    best_plain[0] = p

        def _emit_best():
            """Determine and emit the result — if synced is present, plain is never emitted alongside it."""
            if best_synced[0] is not None:
                self.was_online = True
                self.finished.emit(best_synced[0], None)
                return True
            if best_plain[0] is not None:
                self.was_online = True
                self.finished.emit(None, best_plain[0])
                return True
            return False

        # ── Phase A: fast sources ────────────────────────────────────────────
        self.status.emit('Searching lyrics…')
        pool_a = _cf.ThreadPoolExecutor(max_workers=len(fast_sources))
        try:
            futs_a = [pool_a.submit(_run_source, fn) for _, fn in fast_sources]
            try:
                for fut in _cf.as_completed(futs_a, timeout=8):
                    fut.result()
                    if best_synced[0] is not None:
                        for f in futs_a:
                            f.cancel()
                        break
            except _cf.TimeoutError:
                pass
        finally:
            pool_a.shutdown(wait=False, cancel_futures=True)

        # Any result from Phase A → don't start slow sources at all
        if best_synced[0] is not None or best_plain[0] is not None:
            _emit_best()
            return

        # ── Phase B: slow scrapers ──────────────────────────────────────────
        self.status.emit('Searching lyrics (extended)…')
        pool_b = _cf.ThreadPoolExecutor(max_workers=len(slow_sources))
        try:
            futs_b = [pool_b.submit(_run_source, fn) for _, fn in slow_sources]
            try:
                for fut in _cf.as_completed(futs_b, timeout=14):
                    fut.result()
                    if best_synced[0] is not None:
                        for f in futs_b:
                            f.cancel()
                        break
                    if best_plain[0] is not None:
                        # Plain found; give remaining futures 2 more seconds to find a synced result
                        remaining = [f for f in futs_b if not f.done()]
                        if remaining:
                            try:
                                for fut2 in _cf.as_completed(remaining, timeout=2):
                                    fut2.result()
                                    if best_synced[0] is not None:
                                        for f in futs_b:
                                            f.cancel()
                                        break
                            except _cf.TimeoutError:
                                pass
                        break
            except _cf.TimeoutError:
                pass
        finally:
            pool_b.shutdown(wait=False, cancel_futures=True)

        if not _emit_best():
            self.status.emit('')
            self.finished.emit(None, None)

# ── Panel ─────────────────────────────────────────────────────────────────────
class LyricsPanel(QWidget):
    status_msg = pyqtSignal(str)   # forwarded to status bar
    seek_requested = pyqtSignal(int)          # seek to ms
    lyrics_context = pyqtSignal(str, str, str)  # prev, cur, next

    _LINE_H  = 38
    _LINE_SP = 4

    def __init__(self, player, ctrlbar=None, parent=None):
        super().__init__(parent)
        self._player   = player
        self._ctrlbar  = ctrlbar  # for lyrics_fetch_enabled flag
        self._synced   = []
        self._synced_ts: list | None = None   # sorted timestamp list for bisect; None = not built
        self._plain    = ''
        self._cur_idx  = -1
        self._track    = None
        self._thread: QThread  = None
        self._fetcher: LyricsFetcher = None   # keep ref to prevent GC
        self._pending_track = None
        self._fetch_id: int = 0   # incremented on each new fetch; guards stale callbacks

        self.setObjectName('lyrics_panel')
        self.setMinimumWidth(180)
        self.setMaximumWidth(600)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QWidget(); hdr.setFixedHeight(28)
        self._hdr_widget = hdr
        hdr.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 0, 8, 0)
        self._hdr_lbl = QLabel('Lyrics')
        self._hdr_lbl.setStyleSheet(f'color:{FG2};font-size:11px;background:transparent;')
        self._src_lbl = QLabel('')
        self._src_lbl.setStyleSheet(f'color:{FG2};font-size:10px;background:transparent;')
        hl.addWidget(self._hdr_lbl, 1); hl.addWidget(self._src_lbl)
        root.addWidget(hdr)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f'QScrollArea{{border:none;background:transparent;}}'
            f'QScrollBar:vertical{{background:{BG};width:3px;border-radius:1px;}}'
            f'QScrollBar::handle:vertical{{background:{B2};border-radius:1px;min-height:20px;}}'
            f'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}')
        
        # Enable touch scrolling
        QScroller.grabGesture(self._scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        _apply_scroller_properties(self._scroll.viewport())

        self._cont = QWidget()
        self._cont.setStyleSheet('background:transparent;')
        self._cl = QVBoxLayout(self._cont)
        self._cl.setContentsMargins(14, 18, 14, 18)
        self._cl.setSpacing(self._LINE_SP)
        self._scroll.setWidget(self._cont)
        root.addWidget(self._scroll, 1)

        self._lbls: list = []
        # Lyrics position is driven by on_position() called from sig_pos (100 ms).
        # No separate timer needed — avoids a redundant query_position() call per 80 ms.

        # Pre-allocate a single scroll animation; reuse it in _highlight to avoid
        # constructing a new QPropertyAnimation (+ parent-lookup + signal-wire) on
        # every lyric line change while music is playing.
        # Target widget (_scroll.verticalScrollBar()) is wired lazily after the
        # scroll area is fully initialised.
        self._scroll_anim: QPropertyAnimation = QPropertyAnimation(
            self._scroll.verticalScrollBar(), b'value', self)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scroll_anim.setDuration(300)

    # ── public ──────────────────────────────────────────────────────────────

    def set_track(self, track, deferred=False):
        # Increment fetch_id before aborting so any in-flight _done callback is discarded
        self._fetch_id += 1
        self._track = track
        self._synced = []; self._plain = ''; self._cur_idx = -1
        self._abort()
        if track:
            self._hdr_lbl.setText(track.title or '')
            fetch_ok = (self._ctrlbar is None or self._ctrlbar.lyrics_fetch_enabled)
            if deferred:
                self._pending_track = track
                self._show_status('Waiting for focus…')
            else:
                self._pending_track = None
                self._show_status('Searching…')
                self._start(track, fetch_ok)
        else:
            self._pending_track = None
            self._hdr_lbl.setText('Lyrics')
            self._show_status('')

    def on_focus_gained(self):
        """Call when app regains focus — starts deferred fetch if pending."""
        if self._pending_track and self._fetcher is None:
            track = self._pending_track
            self._pending_track = None
            self._show_status('Searching…')
            fetch_ok = (self._ctrlbar is None or self._ctrlbar.lyrics_fetch_enabled)
            self._start(track, fetch_ok)

    def on_position(self, ms: int):
        if self._synced:
            self._highlight(ms)

    def set_accent(self, _acc: str):
        if 0 <= self._cur_idx < len(self._lbls):
            self._style_lbl(self._lbls[self._cur_idx], True)

    def refresh_theme(self):
        """Re-apply palette globals after dark/light switch."""
        self._hdr_widget.setStyleSheet(f'background:{BG2}; border-bottom:1px solid {BORD};')
        self._hdr_lbl.setStyleSheet(f'color:{FG2};font-size:11px;background:transparent;')
        self._src_lbl.setStyleSheet(f'color:{FG2};font-size:10px;background:transparent;')
        self._scroll.setStyleSheet(
            f'QScrollArea{{border:none;background:transparent;}}'
            f'QScrollBar:vertical{{background:{BG};width:3px;border-radius:1px;}}'
            f'QScrollBar::handle:vertical{{background:{B2};border-radius:1px;min-height:20px;}}'
            f'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}')
        # Re-style all lyric line labels
        for i, lbl in enumerate(self._lbls):
            self._style_lbl(lbl, i == self._cur_idx)

    # ── internal ────────────────────────────────────────────────────────────

    def _abort(self):
        thread   = self._thread
        self._thread  = None
        self._fetcher = None   # drop ref before quit so GC doesn't race
        if thread is not None:
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(300)
            except RuntimeError:
                pass  # C++ object already deleted

    def _start(self, track, fetch_online: bool = True):
        # Capture the generation id set by set_track() — any in-flight callback
        # with an older id will be discarded by the stale-guard in _done().
        my_id = self._fetch_id
        thread  = QThread(self)
        fetcher = LyricsFetcher(track, fetch_online=fetch_online)
        fetcher.moveToThread(thread)
        thread.started.connect(fetcher.run)
        # Wrap _done with the current fetch_id so stale callbacks are ignored
        fetcher.finished.connect(lambda s, p, fid=my_id: self._done(s, p, fid))
        fetcher.finished.connect(thread.quit)
        fetcher.status.connect(self.status_msg)   # forward to status bar
        thread.finished.connect(thread.deleteLater)
        self._thread  = thread
        self._fetcher = fetcher   # prevent GC!
        thread.start()

    def _done(self, synced, plain, fetch_id: int = -1):
        # Ignore callbacks from previous fetch cycles (stale results)
        if fetch_id != self._fetch_id:
            return
        fetcher = self._fetcher; self._fetcher = None
        if self._track is None: return
        if synced:
            self._synced = synced
            self._src_lbl.setText('synced')
            self._build_synced()
            # Jump to current playback position immediately
            try:
                ok, p = self._player._pipe.query_position(Gst.Format.TIME)
                if ok: self._highlight(p // Gst.MSECOND)
            except Exception:
                pass
        elif plain:
            self._plain = plain
            self._src_lbl.setText('')
            self._build_plain()
        else:
            fetch_off = self._ctrlbar and not self._ctrlbar.lyrics_fetch_enabled
            msg = 'File does not contain lyrics.' if fetch_off else 'Lyrics not found.'
            self._show_status(msg)
            self._src_lbl.setText('')
            return
        # Embed into file if fetched from network (fetcher flag) and not already embedded
        if fetcher and fetcher.was_online and self._track:
            fp = self._track.filepath
            from metadata_online import embed_lyrics
            threading.Thread(
                target=embed_lyrics, args=(fp, synced, plain or ''),
                daemon=True).start()

    def _clear(self):
        while self._cl.count():
            it = self._cl.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        self._lbls = []
        self._synced_ts = None   # invalidate bisect index

    def _show_status(self, msg):
        self._clear()
        if not msg: return
        lbl = QLabel(msg)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f'color:{FG2};font-size:13px;background:transparent;')
        self._cl.addStretch(); self._cl.addWidget(lbl); self._cl.addStretch()

    def _style_lbl(self, lbl, active: bool):
        if active:
            lbl.setStyleSheet(
                f'color:{ACC};font-size:16px;font-weight:600;'
                f'padding:0 2px;background:transparent;')
        else:
            lbl.setStyleSheet(
                f'color:{FG2};font-size:14px;padding:0 2px;background:transparent;')

    def _build_synced(self):
        self._clear()
        for ms, txt in self._synced:
            lbl = ClickableLyricLine(txt if txt else '·', ms)
            lbl.setWordWrap(True)
            lbl.setFixedHeight(self._LINE_H)
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            self._style_lbl(lbl, False)
            lbl.clicked.connect(self.seek_requested)
            self._lbls.append(lbl)
            self._cl.addWidget(lbl)
        self._cl.addStretch()
        # Pre-build sorted timestamp list for O(log N) binary search in _highlight
        self._synced_ts = [t for t, _ in self._synced]

    def _build_plain(self):
        self._clear()
        lbl = QLabel(self._plain)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        lbl.setStyleSheet(
            f'color:{FG2};font-size:14px;line-height:1.7;background:transparent;')
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._cl.addWidget(lbl); self._cl.addStretch()

    def _highlight(self, ms: int):
        if not self._synced or not self._lbls: return
        # O(log N) binary search — replaces O(N) linear scan called every 250 ms
        if self._synced_ts is None:
            return
        pos = bisect.bisect_right(self._synced_ts, ms) - 1
        idx = max(0, pos)
        if idx == self._cur_idx: return
        if 0 <= self._cur_idx < len(self._lbls):
            self._style_lbl(self._lbls[self._cur_idx], False)
        self._cur_idx = idx
        self._style_lbl(self._lbls[idx], True)
        prev_t = self._synced[idx-1][1] if idx > 0 else ''
        cur_t  = self._synced[idx][1]
        nxt_t  = self._synced[idx+1][1] if idx < len(self._synced)-1 else ''
        self.lyrics_context.emit(prev_t, cur_t, nxt_t)
        # Reuse the pre-allocated animation — stop if running, then retarget.
        # This avoids allocating a new QPropertyAnimation + signal connection on
        # every lyric-line change (called up to 10× per second while playing).
        step   = self._LINE_H + self._LINE_SP
        target = max(0, idx * step - self._scroll.height() // 2 + self._LINE_H // 2)
        bar    = self._scroll.verticalScrollBar()
        anim   = self._scroll_anim
        if anim.state() == QAbstractAnimation.State.Running:
            anim.stop()
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        anim.start()

# TouchComboBox is defined in eq.py
