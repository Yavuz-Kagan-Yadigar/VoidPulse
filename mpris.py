"""
VoidPulse — MPRIS2 D-Bus server (GLib thread). Exposes Player controls and
metadata to desktop environments via the org.mpris.MediaPlayer2 interface.
"""
from constants import *
from player import Player, RepeatMode
from cover_art import Track, extract_cover_bytes

class MprisServer(QObject):
    _MPRIS_XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/> <method name="Quit"/>
    <property name="CanQuit"             type="b"  access="read"/>
    <property name="CanRaise"            type="b"  access="read"/>
    <property name="HasTrackList"        type="b"  access="read"/>
    <property name="Identity"            type="s"  access="read"/>
    <property name="DesktopEntry"        type="s"  access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes"  type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>  <method name="Previous"/>
    <method name="Pause"/> <method name="PlayPause"/>
    <method name="Stop"/>  <method name="Play"/>
    <method name="Seek">
      <arg name="Offset"   type="x" direction="in"/>
    </method>
    <method name="SetPosition">
      <arg name="TrackId"  type="o" direction="in"/>
      <arg name="Position" type="x" direction="in"/>
    </method>
    <method name="OpenUri"><arg name="Uri" type="s" direction="in"/></method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s"     access="read"/>
    <property name="LoopStatus"     type="s"     access="readwrite"/>
    <property name="Rate"           type="d"     access="readwrite"/>
    <property name="Shuffle"        type="b"     access="readwrite"/>
    <property name="Metadata"       type="a{sv}" access="read"/>
    <property name="Volume"         type="d"     access="readwrite"/>
    <property name="Position"       type="x"     access="read"/>
    <property name="MinimumRate"    type="d"     access="read"/>
    <property name="MaximumRate"    type="d"     access="read"/>
    <property name="CanGoNext"      type="b"     access="read"/>
    <property name="CanGoPrevious"  type="b"     access="read"/>
    <property name="CanPlay"        type="b"     access="read"/>
    <property name="CanPause"       type="b"     access="read"/>
    <property name="CanSeek"        type="b"     access="read"/>
    <property name="CanControl"     type="b"     access="read"/>
  </interface>
</node>
"""
    def __init__(self, player: Player, win: 'MainWindow', parent=None):
        super().__init__(parent)
        self._player = player; self._win = win
        self._conn: Optional[Gio.DBusConnection] = None
        self._reg_ids: list = []
        self._cur_track: Optional[Track] = None
        self._track_serial = 0
        self._cover_on: bool = True          # mirrors the Settings cover toggle
        self._art_tmp_path: Optional[str] = None   # last written temp cover file
        self._cached_art_uri: Optional[str] = None  # built in Qt thread
        self._pipeline_busy: bool = False    # True while pipeline is reloading
        GLib.idle_add(self._setup)

    def set_pipeline_busy(self, busy: bool):
        """Called when a pipeline reload starts/finishes. Disables MPRIS play/pause."""
        self._pipeline_busy = busy
        if busy:
            # Only hide play/pause capability — don't touch PlaybackStatus so
            # MPRIS clients (GNOME Shell, KDE) don't remove the player widget.
            GLib.idle_add(self._emit, ['CanPlay', 'CanPause'])
        else:
            # Reload done: restore capabilities and sync playback status together.
            GLib.idle_add(self._emit, ['CanPlay', 'CanPause', 'PlaybackStatus'])

    # Called by MainWindow whenever the cover switch is toggled
    def set_cover_on(self, enabled: bool):
        self._cover_on = enabled
        # Rebuild art URI with new setting (in Qt thread — safe for disk I/O)
        self._cached_art_uri = self._build_art_uri(self._cur_track)
        GLib.idle_add(self._emit, ['Metadata'])

    def _setup(self):
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(MprisServer._MPRIS_XML)
            for iface in node.interfaces:
                # Try new API first (PyGObject >= 3.51), fallback to old API
                if hasattr(self._conn, 'register_object_with_closures'):
                    rid = self._conn.register_object_with_closures(
                        '/org/mpris/MediaPlayer2', iface,
                        self._handle_method, self._handle_get, self._handle_set)
                    self._reg_ids.append(rid)
                elif hasattr(self._conn, 'register_object'):
                    # Fallback to deprecated API for older PyGObject versions
                    rid = self._conn.register_object('/org/mpris/MediaPlayer2', iface,
                        self._handle_method, self._handle_get, self._handle_set)
                    self._reg_ids.append(rid)
                else:
                    print('[MPRIS] No registration method available, skipping MPRIS')
                    return False
            Gio.bus_own_name_on_connection(self._conn,
                'org.mpris.MediaPlayer2.voidpulse',
                Gio.BusNameOwnerFlags.NONE, None, None)
        except Exception as e:
            print(f'[MPRIS] {e}')
        return False

    def _handle_method(self, conn, sender, obj, iface, method, params, inv):  # noqa: conn/sender required by GIO D-Bus protocol
        inv.return_value(None)
        QTimer.singleShot(0, lambda m=method, p=params: self._dispatch(m, p))

    def _dispatch(self, method, params):
        w = self._win; p = self._player
        # While pipeline is reloading, ignore transport commands to avoid
        # re-entrant reloads. CanPlay/CanPause already signal False to the client.
        if self._pipeline_busy and method in ('PlayPause', 'Play', 'Pause'):
            return
        if   method == 'PlayPause': w._play_pause()
        elif method == 'Play':
            if not p.playing: w._play_pause()
        elif method == 'Pause':
            if p.playing: w._play_pause()
        elif method == 'Stop':
            p.stop(); w._ctrlbar.set_play_icon(False); self.notify_status()
            w._ctrlbar._reset_idle_timer()
        elif method == 'Next':   w._next_track(); w._ctrlbar._reset_idle_timer()
        elif method == 'Previous': w._prev_track(); w._ctrlbar._reset_idle_timer()
        elif method == 'Raise':  w.raise_(); w.activateWindow()
        elif method == 'Quit':   w.close()
        elif method == 'Seek':   p.seek(max(0, p.position_ms()+params[0]//1000))
        elif method == 'SetPosition': p.seek(params[1]//1000)

    def _handle_get(self, conn, sender, obj, iface, prop):  # noqa: conn/sender required by GIO D-Bus protocol
        if iface == 'org.mpris.MediaPlayer2':
            d = {'CanQuit': GLib.Variant('b', True), 'CanRaise': GLib.Variant('b', True),
                 'HasTrackList': GLib.Variant('b', False),
                 'Identity': GLib.Variant('s', 'VoidPulse'),
                 'DesktopEntry': GLib.Variant('s', 'voidpulse'),
                 'SupportedUriSchemes': GLib.Variant('as', ['file']),
                 'SupportedMimeTypes': GLib.Variant('as',
                    ['audio/mpeg','audio/flac','audio/ogg','audio/opus','audio/mp4'])}
            return d.get(prop)
        if iface == 'org.mpris.MediaPlayer2.Player':
            return self._pp(prop)
        return None

    def _pp(self, prop):
        p = self._player; w = self._win
        if prop == 'PlaybackStatus':
            return GLib.Variant('s',
                'Playing' if p.playing else 'Paused' if p.has_pipe else 'Stopped')
        if prop == 'LoopStatus':
            m = w._ctrlbar.btn_rep.current_mode()
            return GLib.Variant('s', 'Track' if m==RepeatMode.ONE
                                else 'Playlist' if m==RepeatMode.ALL else 'None')
        if prop == 'Rate':        return GLib.Variant('d', 1.0)
        if prop == 'Shuffle':     return GLib.Variant('b', w._shuffle)
        if prop == 'Metadata':    return self._meta()
        if prop == 'Volume':      return GLib.Variant('d', p._volume)
        if prop == 'Position':    return GLib.Variant('x', p.position_ms()*1000)
        if prop in ('MinimumRate','MaximumRate'): return GLib.Variant('d', 1.0)
        if prop in ('CanGoNext','CanGoPrevious','CanSeek','CanControl'):
            return GLib.Variant('b', True)
        if prop in ('CanPlay', 'CanPause'):
            return GLib.Variant('b', not self._pipeline_busy)
        return None

    def _meta(self):
        tid = f'/org/voidpulse/track/{self._track_serial}'; t = self._cur_track
        if t is None:
            return GLib.Variant('a{sv}', {'mpris:trackid': GLib.Variant('o', tid)})
        d = {
            'mpris:trackid': GLib.Variant('o', tid),
            'xesam:title':   GLib.Variant('s', t.title or ''),
            'xesam:artist':  GLib.Variant('as', [t.artist] if t.artist else []),
            'xesam:album':   GLib.Variant('s', t.album or ''),
            'mpris:length':  GLib.Variant('x', int(t.duration*1_000_000)),
            'xesam:url':     GLib.Variant('s', Path(t.filepath).as_uri()),
        }
        art_uri = self._art_url_for(t)
        if art_uri:
            d['mpris:artUrl'] = GLib.Variant('s', art_uri)
        return GLib.Variant('a{sv}', d)

    def _art_ext(self, raw: bytes) -> str:
        """Detect image format from magic bytes."""
        if raw[:4] == b'\x89PNG':
            return 'png'
        return 'jpg'

    def _build_art_uri(self, t: Optional['Track']) -> Optional[str]:
        """
        Build a file:// URI for cover art. Called from Qt main thread so
        blocking disk I/O (mutagen) is safe and doesn't block the GLib loop.
        """
        if not self._cover_on or t is None:
            self._delete_art_tmp()
            return None
        raw = extract_cover_bytes(t.filepath)
        if not raw:
            self._delete_art_tmp()
            return None
        ext    = self._art_ext(raw)
        digest = hashlib.md5(raw).hexdigest()[:12]
        tmp_path = os.path.join(tempfile.gettempdir(),
                                f'voidpulse_cover_{digest}.{ext}')
        if not os.path.exists(tmp_path):
            self._delete_art_tmp()
            try:
                with open(tmp_path, 'wb') as fh:
                    fh.write(raw)
            except OSError as e:
                print(f'[MPRIS] cover temp write failed: {e}')
                return None
        self._art_tmp_path = tmp_path
        return Path(tmp_path).as_uri()

    def _art_url_for(self, t: 'Track') -> Optional[str]:
        """Return cached art URI (built in Qt thread). Kept for backward compat."""
        return getattr(self, '_cached_art_uri', None)

    def _delete_art_tmp(self):
        if self._art_tmp_path and os.path.exists(self._art_tmp_path):
            try:
                os.unlink(self._art_tmp_path)
            except OSError:
                pass
        self._art_tmp_path = None

    def _handle_set(self, conn, sender, obj, iface, prop, value):  # noqa: conn/sender required by GIO D-Bus protocol
        if iface != 'org.mpris.MediaPlayer2.Player': return
        if prop == 'Volume':
            QTimer.singleShot(0, lambda v=value.unpack(): self._player.set_volume(v))
        elif prop == 'Shuffle':
            def _apply_shuffle(v):
                self._win._shuffle = v
                self._win._ctrlbar.btn_shuf.setChecked(v)
                GLib.idle_add(self._emit, ['Shuffle'])
            QTimer.singleShot(0, lambda v=value.unpack(): _apply_shuffle(v))
        elif prop == 'LoopStatus':
            def _apply_loop(s):
                m = {'Track': RepeatMode.ONE, 'Playlist': RepeatMode.ALL}.get(s, RepeatMode.NONE)
                self._win._ctrlbar.btn_rep.set_mode(m)
                GLib.idle_add(self._emit, ['LoopStatus'])
            QTimer.singleShot(0, lambda s=value.unpack(): _apply_loop(s))

    def notify_track(self, track: Optional[Track]):
        self._cur_track = track; self._track_serial += 1
        # Build art URI in Qt main thread — extract_cover_bytes does disk I/O
        # via mutagen; doing it here avoids blocking the GLib main loop.
        self._cached_art_uri = self._build_art_uri(track)
        GLib.idle_add(self._emit, ['Metadata', 'PlaybackStatus'])

    def notify_status(self):
        GLib.idle_add(self._emit, ['PlaybackStatus', 'CanPlay', 'CanPause',
                                   'Shuffle', 'LoopStatus'])

    def notify_seeked(self):
        """Emit the MPRIS Seeked signal so clients update their seekbars."""
        GLib.idle_add(self._emit_seeked)

    def _emit_seeked(self):
        if not self._conn: return False
        try:
            pos_us = self._player.position_ms() * 1000
            self._conn.emit_signal(None, '/org/mpris/MediaPlayer2',
                'org.mpris.MediaPlayer2.Player', 'Seeked',
                GLib.Variant('(x)', (pos_us,)))
        except Exception: pass
        return False

    def _emit(self, props):
        if not self._conn: return False
        try:
            changed = {p: v for p in props if (v := self._pp(p)) is not None}
            if changed:
                self._conn.emit_signal(None, '/org/mpris/MediaPlayer2',
                    'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                    GLib.Variant('(sa{sv}as)', ('org.mpris.MediaPlayer2.Player', changed, [])))
        except Exception: pass
        return False

# ══════════════════════════════════════════════════════════════════════════════
