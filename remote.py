"""
VoidPulse — network shares: Samba/SMB, FTP, FTPS and SFTP.

The share is mounted through GVfs (the same machinery a file manager uses) and
then reached at its FUSE path under /run/user/<uid>/gvfs/…, so everything
downstream — the folder scan, mutagen tag reads, cover extraction and the
file:// URI handed to playbin — works on remote files with no changes at all.

Mounting is asynchronous. GIO's callbacks run on the default GLib main context,
which Qt's Unix event dispatcher already iterates, so they land on the Qt main
thread and may touch widgets directly.

Passwords are never written to VoidPulse's config. When the backend offers to
remember one it is handed to the session keyring (Gio.PasswordSave), which is
where the desktop keeps such things; only the URI, username and domain are
persisted here so a saved share can reconnect on the next launch.
"""
from constants import *
from constants import ACC, B2, BG, BG2, BG3, BG4, BORD, FG, FG2, SUPPORTED_EXT, _r
import io

# (combo label, URI scheme, default port, needs a share/path)
PROTOCOLS = [
    ('Samba / SMB', 'smb',  445),
    ('FTP',         'ftp',  21),
    ('FTPS',        'ftps', 990),
    ('SFTP / SSH',  'sftp', 22),
]
_SCHEME_TO_LABEL = {s: l for l, s, _p in PROTOCOLS}
_SCHEME_DEFAULT_PORT = {s: p for _l, s, p in PROTOCOLS}

# gvfs re-asks for credentials when the server rejects them. Answering the same
# way forever would spin, so give up after this many tries and report the error.
_MAX_PASSWORD_ATTEMPTS = 2
# The FUSE path can appear a moment after the mount itself completes
_FUSE_POLL_MS    = 200
_FUSE_POLL_TRIES = 15


def build_uri(scheme: str, host: str, port: int = 0, path: str = '') -> str:
    """Assemble a share URI. The username is deliberately left out: it goes to
    the mount operation instead, so it never ends up in a saved URI or a log."""
    host = (host or '').strip().strip('/')
    if not host:
        return ''
    netloc = host
    default_port = _SCHEME_DEFAULT_PORT.get(scheme, 0)
    if port and port != default_port:
        netloc = f'{host}:{int(port)}'
    path = (path or '').strip().strip('/')
    return f'{scheme}://{netloc}/{path}' if path else f'{scheme}://{netloc}/'


def describe(share: dict) -> str:
    """One-line description of a saved share, for list rows and status text."""
    uri = share.get('uri', '')
    who = share.get('user') or ('anonymous' if share.get('anonymous') else '')
    return f'{uri}  ({who})' if who else uri


def default_label(uri: str) -> str:
    """Playlist label for a share: its last path component, else the host."""
    try:
        parts = [p for p in uri.split('://', 1)[1].split('/') if p]
    except IndexError:
        return 'Network Share'
    if len(parts) > 1:
        return parts[-1]
    return parts[0].split(':')[0] if parts else 'Network Share'


def share_local_path(uri: str) -> Optional[str]:
    """Local FUSE path for an already-mounted share, or None.

    Two routes, because either can be the one that works: a mounted GDaemonFile
    answers get_path() with its FUSE path directly, and where it does not, the
    enclosing mount's root does — with the URI's own sub-path appended.
    """
    if not uri:
        return None
    try:
        gfile = Gio.File.new_for_uri(uri)
    except Exception:
        return None
    try:
        p = gfile.get_path()
        if p and os.path.isdir(p):
            return p
    except Exception:
        pass
    try:
        mount = gfile.find_enclosing_mount(None)
    except Exception:
        return None
    if mount is None:
        return None
    root = mount.get_root()
    root_path = root.get_path() if root is not None else None
    if not root_path:
        return None
    rel = root.get_relative_path(gfile)
    full = os.path.join(root_path, rel) if rel else root_path
    return full if os.path.isdir(full) else None


def is_mounted(uri: str) -> bool:
    return share_local_path(uri) is not None


def _first_audio_file(root: str, max_dirs: int = 12, max_entries: int = 400):
    """First supported audio file at or just below `root`, or None.

    Bounded on purpose: this walks a network filesystem, and it only needs one
    example file, not an inventory.
    """
    seen_dirs = seen_entries = 0
    for cur, dirs, files in os.walk(root):
        dirs.sort()
        seen_dirs += 1
        for f in sorted(files):
            seen_entries += 1
            if Path(f).suffix.lower() in SUPPORTED_EXT:
                return os.path.join(cur, f)
            if seen_entries >= max_entries:
                return None
        if seen_dirs >= max_dirs:
            return None
    return None


def probe_seekable(root: str) -> Optional[bool]:
    """Is random access possible on this mount? None when there is nothing to test.

    GVfs exposes some backends — FTP and FTPS in particular — as sequential-only
    streams through FUSE: reads work, seek() raises. The answer decides how the
    share's files are read from then on (see remote_io): tags go through a
    seekable proxy, and seeking fetches the track to disk first. Measured here
    against local servers: smb:// and sftp:// seek fine, ftp:// and ftps:// do
    not, at the FUSE layer and at the GIO layer alike.

    Finding out costs one open and one seek — cheap, and it has to be known
    before the share is scanned.
    """
    sample = _first_audio_file(root)
    if sample is None:
        return None
    try:
        with open(sample, 'rb') as fh:
            fh.read(4)
            fh.seek(0)
        return True
    except (OSError, ValueError, io.UnsupportedOperation):
        return False
    except Exception:
        return None


class SeekProbe(QThread):
    """Runs probe_seekable() off the UI thread — it touches the network."""
    done = pyqtSignal(str, object)   # (uri, True | False | None)

    def __init__(self, uri: str, root: str, parent=None):
        super().__init__(parent)
        self._uri, self._root = uri, root

    def run(self):
        try:
            self.done.emit(self._uri, probe_seekable(self._root))
        except Exception:
            self.done.emit(self._uri, None)


class RemoteMounter(QObject):
    """Mounts share URIs through GVfs, one request at a time per URI."""
    mounted = pyqtSignal(str, str)   # (uri, local FUSE path)
    failed  = pyqtSignal(str, str)   # (uri, human-readable reason)
    started = pyqtSignal(str)        # (uri)

    def __init__(self, parent=None):
        super().__init__(parent)
        # uri → context dict; also keeps the GMountOperation alive for the whole
        # exchange, which PyGObject would otherwise collect mid-handshake.
        self._pending: dict = {}

    def mount(self, share: dict):
        """Mount `share` ({'uri','user','domain','anonymous'}). Idempotent."""
        uri = (share or {}).get('uri', '')
        if not uri:
            self.failed.emit('', 'No share address given.')
            return
        existing = share_local_path(uri)
        if existing:
            self.mounted.emit(uri, existing)
            return
        if uri in self._pending:
            return   # already in flight

        op = Gio.MountOperation()
        ctx = {'share': dict(share), 'op': op, 'attempts': 0}
        self._pending[uri] = ctx
        op.connect('ask-password', self._on_ask_password, uri)
        op.connect('ask-question', self._on_ask_question, uri)
        self.started.emit(uri)
        try:
            Gio.File.new_for_uri(uri).mount_enclosing_volume(
                Gio.MountMountFlags.NONE, op, None, self._on_mount_done, uri)
        except Exception as e:
            self._pending.pop(uri, None)
            self.failed.emit(uri, str(e))

    # ── GIO callbacks (Qt main thread, via the GLib default context) ────────

    def _on_ask_password(self, op, message, default_user, default_domain,
                         flags, uri):
        ctx = self._pending.get(uri)
        if ctx is None:
            op.reply(Gio.MountOperationResult.ABORTED)
            return
        ctx['attempts'] += 1
        if ctx['attempts'] > _MAX_PASSWORD_ATTEMPTS:
            # The server keeps rejecting what we have; stop rather than loop.
            ctx['auth_rejected'] = True
            op.reply(Gio.MountOperationResult.ABORTED)
            return
        share = ctx['share']
        if share.get('anonymous') and (flags & Gio.AskPasswordFlags.ANONYMOUS_SUPPORTED):
            op.set_anonymous(True)
        else:
            if flags & Gio.AskPasswordFlags.NEED_USERNAME:
                op.set_username(share.get('user') or default_user or '')
            if flags & Gio.AskPasswordFlags.NEED_DOMAIN:
                op.set_domain(share.get('domain') or default_domain or '')
            if flags & Gio.AskPasswordFlags.NEED_PASSWORD:
                op.set_password(share.get('password') or '')
            if flags & Gio.AskPasswordFlags.SAVING_SUPPORTED:
                # Into the desktop keyring, so the next launch reconnects
                # without a prompt and VoidPulse never stores the secret itself.
                op.set_password_save(Gio.PasswordSave.PERMANENTLY)
        op.reply(Gio.MountOperationResult.HANDLED)

    def _on_ask_question(self, op, message, choices, uri):
        """Answer the backend's yes/no prompts with their first (affirmative)
        choice — in practice SFTP's unknown-host-key confirmation."""
        op.set_choice(0)
        op.reply(Gio.MountOperationResult.HANDLED)

    def _on_mount_done(self, gfile, result, uri):
        ctx = self._pending.pop(uri, None)
        try:
            gfile.mount_enclosing_volume_finish(result)
        except GLib.Error as e:
            already = False
            try:
                already = e.matches(Gio.io_error_quark(),
                                    Gio.IOErrorEnum.ALREADY_MOUNTED)
            except Exception:
                already = 'already mounted' in (e.message or '').lower()
            if not already:
                if ctx is not None and ctx.get('auth_rejected'):
                    self.failed.emit(
                        uri, 'Authentication was rejected — check the username, '
                             'domain and password.')
                else:
                    self.failed.emit(uri, e.message or str(e))
                return
        except Exception as e:
            self.failed.emit(uri, str(e))
            return
        self._await_fuse_path(uri, _FUSE_POLL_TRIES)

    def _await_fuse_path(self, uri: str, tries_left: int):
        """The mount exists; wait for its FUSE path to show up under /run/user."""
        path = share_local_path(uri)
        if path:
            self.mounted.emit(uri, path)
            return
        if tries_left <= 0:
            self.failed.emit(
                uri,
                'The share was mounted, but it has no local path.\n\n'
                'VoidPulse reads remote files through the GVfs FUSE mount, so '
                'the gvfs-fuse package has to be installed and gvfsd-fuse '
                'running.')
            return
        QTimer.singleShot(_FUSE_POLL_MS,
                          lambda: self._await_fuse_path(uri, tries_left - 1))

    # ── unmount ─────────────────────────────────────────────────────────────

    @staticmethod
    def unmount(uri: str):
        """Disconnect a share. Best-effort and fire-and-forget: the library keeps
        working from cached metadata either way, and the next connect remounts."""
        try:
            mount = Gio.File.new_for_uri(uri).find_enclosing_mount(None)
        except Exception:
            return
        if mount is None:
            return
        try:
            mount.unmount_with_operation(
                Gio.MountUnmountFlags.NONE, Gio.MountOperation(), None, None, None)
        except Exception as e:
            print(f'[Remote] unmount failed for {uri}: {e}')


# ══════════════════════════════════════════════════════════════════════════════
#  Dialog
# ══════════════════════════════════════════════════════════════════════════════
class NetworkShareDialog(QDialog):
    """Connect a new share, or reconnect / forget a saved one.

    `connect_requested` carries the share dict; MainWindow owns the mounter and
    the saved list, so this dialog only collects input and reports the result.
    """
    connect_requested = pyqtSignal(dict)
    forget_requested  = pyqtSignal(str)   # uri

    def __init__(self, saved: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Network Share')
        self.setModal(True)
        self.setMinimumWidth(470)
        self.setStyleSheet(self._ss())

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # ── saved shares ────────────────────────────────────────────────────
        self._saved_lbl = QLabel('SAVED SHARES')
        self._saved_lbl.setObjectName('sect')
        root.addWidget(self._saved_lbl)

        self._saved_list = QListWidget()
        self._saved_list.setMaximumHeight(110)
        self._saved_list.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self._saved_list)

        saved_btns = QHBoxLayout(); saved_btns.setSpacing(6)
        self._btn_reconnect = QPushButton('Reconnect')
        self._btn_forget    = QPushButton('Forget')
        self._btn_reconnect.clicked.connect(self._on_reconnect)
        self._btn_forget.clicked.connect(self._on_forget)
        saved_btns.addStretch(1)
        saved_btns.addWidget(self._btn_reconnect)
        saved_btns.addWidget(self._btn_forget)
        root.addLayout(saved_btns)

        div = QFrame(); div.setFixedHeight(1)
        div.setStyleSheet(f'background:{BORD}; margin:2px 0;')
        root.addWidget(div)

        # ── new share ───────────────────────────────────────────────────────
        new_lbl = QLabel('NEW SHARE'); new_lbl.setObjectName('sect')
        root.addWidget(new_lbl)

        form = QGridLayout(); form.setHorizontalSpacing(8); form.setVerticalSpacing(6)
        root.addLayout(form)

        self._proto = QComboBox()
        for label, scheme, _port in PROTOCOLS:
            self._proto.addItem(label, userData=scheme)
        self._proto.currentIndexChanged.connect(self._on_proto_changed)

        self._host   = QLineEdit(); self._host.setPlaceholderText('nas.local  or  192.168.1.20')
        self._port   = QLineEdit(); self._port.setPlaceholderText('default')
        self._port.setValidator(QIntValidator(0, 65535, self))
        self._port.setMaximumWidth(90)
        self._path   = QLineEdit(); self._path.setPlaceholderText('Music        (share name / remote folder)')
        self._user   = QLineEdit(); self._user.setPlaceholderText('username')
        self._domain = QLineEdit(); self._domain.setPlaceholderText('WORKGROUP   (SMB only, optional)')
        self._pw     = QLineEdit(); self._pw.setPlaceholderText('password')
        self._pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._anon   = QCheckBox('Connect anonymously (guest)')
        self._anon.toggled.connect(self._on_anon_toggled)

        rows = [('Protocol', self._proto), ('Server', self._host), ('Port', self._port),
                ('Share / Path', self._path), ('Username', self._user),
                ('Domain', self._domain), ('Password', self._pw)]
        for r, (text, widget) in enumerate(rows):
            lab = QLabel(text); lab.setObjectName('field')
            form.addWidget(lab, r, 0)
            form.addWidget(widget, r, 1)
        form.addWidget(self._anon, len(rows), 1)

        note = QLabel(
            'The password is handed to the system keyring, not saved by VoidPulse. '
            'Remote files are read through the GVfs FUSE mount, so gvfs-fuse must '
            'be installed. SMB and SFTP seek directly. FTP and FTPS cannot seek '
            'at all, so the first seek on a track fetches it to disk first; '
            'everything else works normally.')
        note.setObjectName('note')
        note.setWordWrap(True)
        root.addWidget(note)

        self._status = QLabel('')
        self._status.setObjectName('note')
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        btns = QHBoxLayout(); btns.setSpacing(6)
        self._btn_connect = QPushButton('Connect')
        self._btn_connect.setDefault(True)
        self._btn_close   = QPushButton('Close')
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_close.clicked.connect(self.reject)
        btns.addStretch(1); btns.addWidget(self._btn_connect); btns.addWidget(self._btn_close)
        root.addLayout(btns)

        self.set_saved(saved)
        self._on_proto_changed()

    # ── saved list ──────────────────────────────────────────────────────────

    def set_saved(self, saved: list):
        self._saved = list(saved or [])
        self._saved_list.clear()
        for sh in self._saved:
            item = QListWidgetItem(describe(sh))
            item.setData(Qt.ItemDataRole.UserRole, sh.get('uri', ''))
            if is_mounted(sh.get('uri', '')):
                item.setText(item.text() + '   ● connected')
                item.setForeground(QColor(ACC))
            self._saved_list.addItem(item)
        has_any = bool(self._saved)
        self._saved_lbl.setVisible(has_any)
        self._saved_list.setVisible(has_any)
        self._btn_reconnect.setVisible(has_any)
        self._btn_forget.setVisible(has_any)

    def _selected_share(self) -> Optional[dict]:
        item = self._saved_list.currentItem()
        if item is None:
            return None
        uri = item.data(Qt.ItemDataRole.UserRole)
        return next((s for s in self._saved if s.get('uri') == uri), None)

    def _on_reconnect(self):
        share = self._selected_share()
        if share is None:
            self.set_status('Select a saved share first.')
            return
        # The keyring holds the password; an empty one here means "use it"
        self.connect_requested.emit(dict(share))

    def _on_forget(self):
        share = self._selected_share()
        if share is None:
            self.set_status('Select a saved share first.')
            return
        self.forget_requested.emit(share.get('uri', ''))

    # ── new share ───────────────────────────────────────────────────────────

    def _on_proto_changed(self, *_):
        scheme = self._proto.currentData()
        self._domain.setEnabled(scheme == 'smb')
        self._port.setPlaceholderText(str(_SCHEME_DEFAULT_PORT.get(scheme, '')))
        # Only SMB and FTP servers routinely allow guests
        self._anon.setEnabled(scheme in ('smb', 'ftp', 'ftps'))
        if not self._anon.isEnabled():
            self._anon.setChecked(False)

    def _on_anon_toggled(self, on: bool):
        for w in (self._user, self._domain, self._pw):
            w.setEnabled(not on and (w is not self._domain
                                     or self._proto.currentData() == 'smb'))

    def _on_connect(self):
        scheme = self._proto.currentData()
        host   = self._host.text().strip()
        if not host:
            self.set_status('Enter a server address.')
            return
        port = int(self._port.text()) if self._port.text().strip() else 0
        uri  = build_uri(scheme, host, port, self._path.text())
        if not uri:
            self.set_status('That server address is not usable.')
            return
        share = {
            'uri':       uri,
            'user':      '' if self._anon.isChecked() else self._user.text().strip(),
            'domain':    '' if self._anon.isChecked() else self._domain.text().strip(),
            'anonymous': self._anon.isChecked(),
            'password':  '' if self._anon.isChecked() else self._pw.text(),
            'label':     default_label(uri),
        }
        self.connect_requested.emit(share)

    # ── feedback ────────────────────────────────────────────────────────────

    def set_status(self, msg: str):
        self._status.setText(msg)

    def set_busy(self, busy: bool):
        self._btn_connect.setEnabled(not busy)
        self._btn_reconnect.setEnabled(not busy)
        self._btn_connect.setText('Connecting…' if busy else 'Connect')

    @staticmethod
    def _ss() -> str:
        return (
            f'QDialog {{ background:{BG2}; }}'
            f'QLabel {{ color:{FG}; font-size:12px; background:transparent; }}'
            f'QLabel#sect {{ color:{FG2}; font-size:9px; letter-spacing:2px; }}'
            f'QLabel#field {{ color:{FG2}; font-size:11px; }}'
            f'QLabel#note {{ color:{FG2}; font-size:10px; }}'
            f'QCheckBox {{ color:{FG}; font-size:11px; background:transparent; }}'
            f'QLineEdit {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:{_r(8)}px; padding:5px 8px; font-size:12px; }}'
            f'QLineEdit:focus {{ border-color:{ACC}; }}'
            f'QLineEdit:disabled {{ color:{FG2}; background:{BG}; }}'
            f'QComboBox {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:{_r(8)}px; padding:5px 8px; font-size:12px; }}'
            f'QComboBox QAbstractItemView {{ background:{BG3}; color:{FG};'
            f' border:1px solid {B2}; }}'
            f'QListWidget {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:{_r(8)}px; font-size:11px; }}'
            f'QListWidget::item {{ padding:5px 8px; }}'
            f'QListWidget::item:selected {{ background:{BG4}; color:{ACC}; }}'
            f'QPushButton {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:{_r(9)}px; padding:6px 16px; font-size:12px;'
            f' min-height:26px; }}'
            f'QPushButton:hover {{ border-color:{ACC}; }}'
            f'QPushButton:default {{ border-color:{ACC}; color:{ACC}; }}'
            f'QPushButton:disabled {{ color:{FG2}; border-color:{BORD}; }}'
        )

# ══════════════════════════════════════════════════════════════════════════════
