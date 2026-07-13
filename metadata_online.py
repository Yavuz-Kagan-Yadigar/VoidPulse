"""
VoidPulse — online metadata: cover art fetching (iTunes/Deezer/MusicBrainz/LastFM),
tag lookup (MusicBrainz/iTunes/LastFM), and mutagen tag/cover/lyrics writers.
"""
from constants import *
from constants import _open_audio
import constants as _const_mod
from lyrics import _get, _get_json
import urllib.request as _urlreq
import urllib.parse as _urlparse

def _fetch_cover_itunes(artist: str, title: str) -> Optional[bytes]:
    try:
        q = _urlparse.quote(f'{artist} {title}')
        d = _get_json(f'https://itunes.apple.com/search?term={q}'
                      f'&media=music&entity=song&limit=5')
        for item in d.get('results', []):
            url = item.get('artworkUrl100', '')
            if url:
                url = url.replace('100x100bb', '600x600bb')
                data = _get(url)
                if isinstance(data, str): data = data.encode('latin1')
                if data and len(data) > 1000: return data
    except Exception: pass
    return None

def _fetch_cover_deezer(artist: str, title: str) -> Optional[bytes]:
    try:
        q = _urlparse.quote(f'artist:"{artist}" track:"{title}"')
        d = _get_json(f'https://api.deezer.com/search?q={q}&limit=3')
        for item in d.get('data', []):
            url = item.get('album', {}).get('cover_xl', '') or \
                  item.get('album', {}).get('cover_big', '')
            if url:
                data = _get(url)
                if isinstance(data, str): data = data.encode('latin1')
                if data and len(data) > 1000: return data
    except Exception: pass
    return None

def _fetch_cover_musicbrainz(artist: str, album: str) -> Optional[bytes]:
    try:
        q = _urlparse.quote(f'artist:"{artist}" AND release:"{album}"')
        d = _get_json(
            f'https://musicbrainz.org/ws/2/release/?query={q}&limit=5&fmt=json',
            headers={'Accept': 'application/json'})
        for rel in d.get('releases', [])[:3]:
            mbid = rel.get('id', '')
            if not mbid: continue
            url = f'https://coverartarchive.org/release/{mbid}/front-500'
            try:
                req = _urlreq.Request(url, headers={'User-Agent': 'VoidPulse/2.0'})
                with _urlreq.urlopen(req, timeout=8) as r:
                    data = r.read()
                if data and len(data) > 1000: return data
            except Exception: pass
    except Exception: pass
    return None

def _fetch_cover_lastfm(artist: str, album: str) -> Optional[bytes]:
    try:
        key = _const_mod._lastfm_api_key.strip()
        if not key:
            return None
        a = _urlparse.quote(artist); al = _urlparse.quote(album)
        url = (f'https://ws.audioscrobbler.com/2.0/?method=album.getinfo'
               f'&artist={a}&album={al}&api_key={key}&format=json')
        d = _get_json(url)
        images = d.get('album', {}).get('image', [])
        for img in reversed(images):
            img_url = img.get('#text', '')
            if img_url and 'noimage' not in img_url:
                data = _get(img_url)
                if isinstance(data, str): data = data.encode('latin1')
                if data and len(data) > 1000: return data
    except Exception: pass
    return None

def fetch_cover_online(artist: str, title: str, album: str, *,
                       stop=None) -> Optional[bytes]:
    """Try multiple sources, return raw image bytes or None.
    ``stop`` is an optional callable; if it returns True the fetch is aborted."""
    for fn in [
        lambda: _fetch_cover_itunes(artist, title),
        lambda: _fetch_cover_deezer(artist, title),
        lambda: _fetch_cover_musicbrainz(artist, album),
        lambda: _fetch_cover_lastfm(artist, album),
    ]:
        if stop and stop():
            return None
        try:
            data = fn()
            if data: return data
        except Exception: pass
    return None

# ══════════════════════════════════════════════════════════════════════════════
#  Online tag / metadata lookup
# ══════════════════════════════════════════════════════════════════════════════

# MusicBrainz release-type filter constants (shared by _mb_rel_score + _lookup_tags_musicbrainz)
_MB_BAD_SEC  = frozenset({'Live', 'Compilation', 'DJ-mix', 'Mixtape/Street', 'Demo'})
_MB_GOOD_PRI = frozenset({'Album', 'Single', 'EP'})

def _mb_rel_score(rel):
    """Score a MusicBrainz release for preference (lower = better)."""
    rg  = rel.get('release-group') or {}
    pri = rg.get('primary-type', '')
    sec = set(rg.get('secondary-types', []))
    bad  = bool(sec & _MB_BAD_SEC)
    good = pri in _MB_GOOD_PRI
    if good and not bad: return 0
    if good and bad:     return 1
    if not bad:          return 2
    return 3

def _mb_rec_score(rec):
    """Score a MusicBrainz recording by its best release."""
    scores = [_mb_rel_score(r) for r in rec.get('releases', [])]
    return min(scores) if scores else 99

def _lookup_tags_musicbrainz(artist: str, title: str) -> dict:
    """Query MusicBrainz for recording metadata. Returns dict with keys:
    title, artist, album, date. All values may be empty strings.
    Prefers studio albums/singles over live/compilation releases."""

    try:
        q = _urlparse.quote(f'recording:"{title}" AND artist:"{artist}"')
        d = _get_json(
            f'https://musicbrainz.org/ws/2/recording/?query={q}&limit=5&fmt=json',
            headers={'Accept': 'application/json'})
        recs = d.get('recordings', [])[:5]
        if not recs:
            return {}
        best = sorted(recs, key=_mb_rec_score)[0]
        t    = best.get('title', '').strip()
        art_list = best.get('artist-credit', [])
        art  = art_list[0].get('artist', {}).get('name', '').strip() if art_list else ''
        rels = sorted(best.get('releases', []), key=_mb_rel_score)
        alb, date = '', ''
        for rel in rels:
            rg  = rel.get('release-group') or {}
            sec = set(rg.get('secondary-types', []))
            if not (sec & _MB_BAD_SEC):
                alb  = rel.get('title', '').strip()
                date = (rel.get('date') or '')[:4]
                break
        if not alb and rels:
            alb  = rels[0].get('title', '').strip()
            date = (rels[0].get('date') or '')[:4]
        if t or art:
            return {'title': t, 'artist': art, 'album': alb, 'date': date}
    except Exception:
        pass
    return {}

def _lookup_tags_itunes(artist: str, title: str) -> dict:
    """Query iTunes Search API for track metadata."""
    try:
        q = _urlparse.quote(f'{artist} {title}')
        d = _get_json(
            f'https://itunes.apple.com/search?term={q}&media=music&entity=song&limit=5')
        for item in d.get('results', []):
            return {
                'title':  item.get('trackName', '').strip(),
                'artist': item.get('artistName', '').strip(),
                'album':  item.get('collectionName', '').strip(),
                'date':   str(item.get('releaseDate', ''))[:4],
            }
    except Exception:
        pass
    return {}

def _lookup_tags_lastfm(artist: str, title: str) -> dict:
    """Query Last.fm track.getInfo for metadata."""
    try:
        key = _const_mod._lastfm_api_key.strip()
        if not key:
            return {}
        a = _urlparse.quote(artist); t = _urlparse.quote(title)
        url = (f'https://ws.audioscrobbler.com/2.0/?method=track.getinfo'
               f'&artist={a}&track={t}&api_key={key}&format=json')
        d = _get_json(url)
        tr = d.get('track', {})
        alb = tr.get('album', {}).get('title', '').strip()
        return {
            'title':  tr.get('name', '').strip(),
            'artist': tr.get('artist', {}).get('name', '').strip() if isinstance(tr.get('artist'), dict) else tr.get('artist', '').strip(),
            'album':  alb,
            'date':   '',
        }
    except Exception:
        pass
    return {}

def lookup_tags_online(artist: str, title: str, *, stop=None) -> dict:
    """Try multiple sources; return best result dict with title/artist/album keys.
    Sources are tried in priority order: iTunes first (most reliable album data),
    then MusicBrainz, then Last.fm. Each fills only fields still missing.
    ``stop`` is an optional callable; if it returns True the lookup is aborted."""
    merged = {}

    sources = [
        lambda: _lookup_tags_itunes(artist, title),       # best album accuracy
        lambda: _lookup_tags_musicbrainz(artist, title),  # fallback
        lambda: _lookup_tags_lastfm(artist, title),       # fallback
    ]
    for fn in sources:
        if stop and stop():
            break
        # Short-circuit: all fields filled
        if merged.get('title') and merged.get('artist') and merged.get('album'):
            break
        try:
            r = fn()
            if r.get('album') or r.get('artist') or r.get('title'):
                for k, v in r.items():
                    if v and not merged.get(k):
                        merged[k] = v
        except Exception:
            pass

    return merged

def write_tags_to_file(fp: str, tags: dict) -> bool:
    """Write title/artist/album from tags dict into the audio file. Returns True on success."""
    try:
        ext = Path(fp).suffix.lower()
        # Reject WebM/MKV containers — mutagen cannot write tags to them
        try:
            with open(fp, 'rb') as _wf:
                if _wf.read(4) == b'\x1a\x45\xdf\xa3':
                    print(f'write_tags_to_file: {fp} is a WebM/MKV container, skipping')
                    return False
        except OSError:
            return False
        af  = _open_audio(fp)
        if af is None: return False
        if af.tags is None: af.add_tags()

        if ext == '.mp3':
            from mutagen.id3 import TIT2, TPE1, TALB
            if tags.get('title'):  af.tags['TIT2'] = TIT2(encoding=3, text=tags['title'])
            if tags.get('artist'): af.tags['TPE1'] = TPE1(encoding=3, text=tags['artist'])
            if tags.get('album'):  af.tags['TALB'] = TALB(encoding=3, text=tags['album'])
        elif ext in ('.flac', '.ogg', '.opus'):
            if tags.get('title'):  af.tags['title']  = [tags['title']]
            if tags.get('artist'): af.tags['artist'] = [tags['artist']]
            if tags.get('album'):  af.tags['album']  = [tags['album']]
        elif ext in ('.m4a', '.aac'):
            if tags.get('title'):  af.tags['\xa9nam'] = [tags['title']]
            if tags.get('artist'): af.tags['\xa9ART'] = [tags['artist']]
            if tags.get('album'):  af.tags['\xa9alb'] = [tags['album']]
        else:
            return False
        af.save()
        return True
    except Exception as e:
        print(f'write_tags_to_file error: {e}')
        return False

def embed_cover_bytes(fp: str, data: bytes) -> bool:
    """Write cover bytes into the audio file tags. Returns True on success."""
    try:
        ext = Path(fp).suffix.lower()
        try:
            with open(fp, 'rb') as _wf:
                if _wf.read(4) == b'\x1a\x45\xdf\xa3':
                    return False
        except OSError:
            return False
        af  = _open_audio(fp)
        if af is None: return False

        if ext == '.mp3':
            from mutagen.id3 import APIC
            if af.tags is None: af.add_tags()
            mime = 'image/jpeg' if data[:3] == b'\xff\xd8\xff' else 'image/png'
            af.tags.delall('APIC')
            af.tags.add(APIC(encoding=3, mime=mime, type=3,
                             desc='Cover', data=data))

        elif ext == '.flac':
            from mutagen.flac import Picture
            pic = Picture()
            pic.type = 3; pic.mime = 'image/jpeg' if data[:3] == b'\xff\xd8\xff' else 'image/png'
            pic.desc = 'Cover'; pic.data = data
            af.clear_pictures(); af.add_picture(pic)

        elif ext in ('.m4a', '.aac'):
            from mutagen.mp4 import MP4Cover
            fmt = MP4Cover.FORMAT_JPEG if data[:3] == b'\xff\xd8\xff' else MP4Cover.FORMAT_PNG
            af.tags['covr'] = [MP4Cover(data, imageformat=fmt)]

        elif ext in ('.ogg', '.opus'):
            from mutagen.flac import Picture
            pic = Picture()
            pic.type = 3; pic.mime = 'image/jpeg' if data[:3] == b'\xff\xd8\xff' else 'image/png'
            pic.desc = 'Cover'; pic.data = data
            encoded = base64.b64encode(pic.write()).decode('ascii')
            af.tags['metadata_block_picture'] = [encoded]
        else:
            return False

        af.save(); return True
    except Exception as e:
        print(f'embed_cover_bytes error: {e}'); return False

def embed_lyrics(fp: str, synced, plain: str) -> bool:
    """Write lyrics into audio file tags. Returns True on success."""
    try:
        ext = Path(fp).suffix.lower()
        try:
            with open(fp, 'rb') as _wf:
                if _wf.read(4) == b'\x1a\x45\xdf\xa3':
                    return False
        except OSError:
            return False
        af  = _open_audio(fp)
        if af is None: return False

        if synced:
            lrc_lines = [f'[{ms//60000:02d}:{(ms%60000)/1000:05.2f}]{txt}'
                         for ms, txt in synced]
            lrc_text = '\n'.join(lrc_lines)
        else:
            lrc_text = None

        text_to_write = lrc_text if lrc_text else plain

        if ext == '.mp3':
            from mutagen.id3 import USLT
            if af.tags is None: af.add_tags()
            af.tags.delall('USLT'); af.tags.delall('SYLT')
            af.tags.add(USLT(encoding=3, lang='eng', desc='', text=text_to_write))

        elif ext in ('.flac', '.ogg', '.opus'):
            if af.tags is None: af.add_tags()
            af.tags['LYRICS'] = [text_to_write]

        elif ext in ('.m4a', '.aac'):
            if af.tags is None: af.add_tags()
            af.tags['\xa9lyr'] = [text_to_write]

        else:
            return False

        af.save(); return True
    except Exception as e:
        print(f'embed_lyrics error: {e}'); return False

