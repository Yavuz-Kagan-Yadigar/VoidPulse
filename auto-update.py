#!/usr/bin/env python3
"""
VoidPulse — auto-update: package detection, GitHub release polling, in-place update.

The format VoidPulse was installed as is resolved once, on the first launch that
runs this module, and written to ~/.config/voidpulse/update.json. Every later
launch reuses that record and polls

    https://github.com/Yavuz-Kagan-Yadigar/VoidPulse/releases

in a background thread. When a newer tag carries an asset of the same format and
architecture the user is offered the update; when the tag exists but ships no
matching asset the release is still announced, with the formats it does ship
listed as download buttons.

Nothing here is allowed to affect startup: the check is fired on a timer after
the window is up, every network path is wrapped, and a failure only prints.

The module is named with a hyphen so it cannot be imported as `auto_update`;
voidpulse.py loads it through importlib. See `check_on_startup` for the entry
point and the `__main__` block for the offline test harness.
"""
from constants import *
import constants as _c
from constants import (ACC, ACCH, BG, BG2, BG3, BORD, FG, FG2, _r,
                       CONFIG_PATH, IN_FLATPAK, host_cmd)

import re
import shutil
import platform
import urllib.request
import urllib.error


# ══════════════════════════════════════════════════════════════════════════════
#  Constants
# ══════════════════════════════════════════════════════════════════════════════
REPO         = 'Yavuz-Kagan-Yadigar/VoidPulse'
RELEASES_URL = f'https://github.com/{REPO}/releases'
API_URL      = f'https://api.github.com/repos/{REPO}/releases?per_page=8'
APP_ID       = 'org.voidpulse.VoidPulse'

STATE_PATH   = CONFIG_PATH.parent / 'update.json'

_HTTP_TIMEOUT   = 12       # s, per request
_START_DELAY_MS = 4000     # let the library finish loading before we ask
_UA             = 'VoidPulse-Updater'

# Package formats voidpulse_build.sh produces, plus 'source' for a git checkout.
PKG_LABELS = {
    'flatpak':  'Flatpak',
    'appimage': 'AppImage',
    'deb':      'Deb',
    'rpm':      'RPM',
    'apk':      'Apk',
    'pacman':   'Pacman',
    'source':   'Source checkout',
}

# platform.machine() → the arch tag each format uses in its file names. The two
# tables differ: Debian renames x86_64 to amd64 and aarch64 to arm64, appimage
# keeps the kernel names but folds every 32-bit ARM into armhf.
_APPIMAGE_ARCH = {
    'x86_64': 'x86_64', 'amd64': 'x86_64',
    'aarch64': 'aarch64', 'arm64': 'aarch64',
    'armv7l': 'armhf', 'armv6l': 'armhf', 'armhf': 'armhf',
    'i686': 'i686', 'i386': 'i686', 'i586': 'i686',
}
_DEB_ARCH = {
    'x86_64': 'amd64', 'amd64': 'amd64',
    'aarch64': 'arm64', 'arm64': 'arm64',
    'armv7l': 'armhf', 'armhf': 'armhf',
    'armv6l': 'armel', 'armel': 'armel',
    'riscv64': 'riscv64',
    'loongarch64': 'loong64', 'loong64': 'loong64',
    'i686': 'i386', 'i386': 'i386',
}


def _log(*a):
    print('[AutoUpdate]', *a)


# ══════════════════════════════════════════════════════════════════════════════
#  Persistent state
# ══════════════════════════════════════════════════════════════════════════════
def _load_state() -> dict:
    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as fh:
            st = json.load(fh)
        return st if isinstance(st, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        _log('state unreadable, starting fresh:', exc)
        return {}


def _save_state(st: dict) -> None:
    """Write update.json atomically; ~/.config stays writable inside the flatpak
    thanks to --filesystem=xdg-config, so this works in every package format."""
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(st, fh, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception as exc:
        _log('state not saved:', exc)


# ══════════════════════════════════════════════════════════════════════════════
#  Package-type detection
# ══════════════════════════════════════════════════════════════════════════════
def _module_dir() -> Path:
    return Path(__file__).resolve().parent


def _run(cmd, timeout=8):
    """Run a command and return (rc, combined output). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except Exception as exc:
        return 127, str(exc)


def _owner_package(path: Path) -> Optional[str]:
    """Ask the system package managers which of them owns `path`.

    Only one of dpkg/rpm/apk is normally present, and a hit is conclusive: an
    installed VoidPulse lives in /usr/lib/voidpulse, which nothing else writes.
    """
    p = str(path)
    if shutil.which('dpkg-query'):
        rc, out = _run(['dpkg-query', '-S', p])
        if rc == 0 and 'voidpulse' in out.lower():
            return 'deb'
    if shutil.which('rpm'):
        rc, out = _run(['rpm', '-qf', p])
        if rc == 0 and 'voidpulse' in out.lower():
            return 'rpm'
    if shutil.which('apk'):
        rc, out = _run(['apk', 'info', '--who-owns', p])
        if rc == 0 and 'voidpulse' in out.lower():
            return 'apk'
    if shutil.which('pacman'):
        rc, out = _run(['pacman', '-Qo', p])
        if rc == 0 and 'voidpulse' in out.lower():
            return 'pacman'
    return None


def _distro_guess() -> Optional[str]:
    """Fallback when the file is under /usr but no package tool claimed it —
    a package manager that was removed, or a --nodeps install."""
    try:
        rel = Path('/etc/os-release').read_text(errors='ignore').lower()
    except Exception:
        return None
    if 'alpine' in rel:
        return 'apk'
    if any(k in rel for k in ('arch', 'manjaro', 'endeavour')):
        return 'pacman'
    if any(k in rel for k in ('debian', 'ubuntu', 'mint', 'pop')):
        return 'deb'
    if any(k in rel for k in ('fedora', 'rhel', 'centos', 'suse', 'mageia')):
        return 'rpm'
    return None


def detect_package() -> dict:
    """Work out how this copy of VoidPulse was installed.

    Returns {'type', 'arch', 'path'} where `path` is the AppImage file for an
    AppImage and '' for every format the system owns.
    """
    machine = platform.machine()

    if IN_FLATPAK:
        # The bundle is arch-specific but only ever published under one name.
        return {'type': 'flatpak', 'arch': 'noarch', 'path': ''}

    ai = os.environ.get('APPIMAGE', '')
    if ai and Path(ai).exists():
        return {'type': 'appimage',
                'arch': _APPIMAGE_ARCH.get(machine, machine),
                'path': str(Path(ai).resolve())}

    here = _module_dir()
    owner = _owner_package(here / 'voidpulse.py')
    if owner is None and str(here).startswith(('/usr/', '/opt/')):
        owner = _distro_guess()
    if owner == 'deb':
        return {'type': 'deb', 'arch': _DEB_ARCH.get(machine, machine), 'path': ''}
    if owner == 'rpm':
        return {'type': 'rpm', 'arch': 'noarch', 'path': ''}
    if owner == 'apk':
        return {'type': 'apk', 'arch': 'noarch', 'path': ''}

    return {'type': 'source', 'arch': machine, 'path': str(here)}


def resolve_package() -> dict:
    """The stored package record, detecting and persisting it on first run.

    The stored value wins on later launches — that is the whole point of pinning
    it — but a record that the environment now contradicts (an AppImage that was
    replaced by a deb, a recorded AppImage path that is gone) is re-detected so
    a user who switches formats is not stuck updating the wrong one.
    """
    st = _load_state()
    stored = st.get('package')
    live = None

    if isinstance(stored, dict) and stored.get('type') in PKG_LABELS:
        stale = False
        if stored['type'] == 'appimage':
            # $APPIMAGE moves with every update, so refresh it rather than
            # trusting the recorded path.
            ai = os.environ.get('APPIMAGE', '')
            if ai and Path(ai).exists():
                stored['path'] = str(Path(ai).resolve())
            elif not Path(stored.get('path', '')).exists():
                stale = True
        if stored['type'] == 'flatpak' and not IN_FLATPAK:
            stale = True
        if stored['type'] != 'flatpak' and IN_FLATPAK:
            stale = True
        if stored['type'] == 'source':
            # A record written by a dev run of the checkout must never pin a
            # later packaged install, which shares ~/.config with it.
            stale = True
        if stored['type'] in ('deb', 'rpm', 'apk', 'pacman') and \
                not str(_module_dir()).startswith(('/usr/', '/opt/')):
            stale = True
        if not stale:
            st['package'] = stored
            _save_state(st)
            return stored
        _log('stored package record no longer matches this install — re-detecting')

    live = detect_package()
    st['package'] = live
    st.setdefault('first_detected', QDateTime.currentDateTimeUtc().toString(Qt.DateFormat.ISODate))
    _save_state(st)
    _log(f"package type: {live['type']} ({live['arch']})")
    return live


# ══════════════════════════════════════════════════════════════════════════════
#  Version discovery
# ══════════════════════════════════════════════════════════════════════════════
_VER_RE = re.compile(r'(\d+(?:\.\d+)+)')


def vtuple(text: str) -> tuple:
    """'v1.10.0' → (1, 10, 0). Unparseable input sorts lowest.

    Tags in this repo are not consistent — v1.8.1 next to v.1.6.0 — so the
    number is pulled out of the string rather than assuming a prefix.
    """
    m = _VER_RE.search(text or '')
    if not m:
        return (0,)
    return tuple(int(x) for x in m.group(1).split('.'))


def _version_from_metainfo() -> Optional[str]:
    """The version constants resolved from the AppStream metainfo at import.

    A thin wrapper on purpose: the sidebar badge and the updater must never
    disagree about which version is running, so there is one implementation and
    it lives in constants.
    """
    v = _c.APP_VERSION
    return v if v and v != '0.0.0' else None


def installed_version(pkg: dict) -> str:
    """Best-effort version of the running copy; '0' if nothing could be read."""
    v = _version_from_metainfo()
    if v:
        return v
    if pkg['type'] == 'appimage' and pkg.get('path'):
        m = re.search(r'VoidPulse-([\d.]+)-', Path(pkg['path']).name)
        if m:
            return m.group(1)
    if pkg['type'] == 'flatpak':
        rc, out = _run(host_cmd('flatpak', 'info', APP_ID))
        if rc == 0:
            m = re.search(r'Version:\s*([\d.]+)', out)
            if m:
                return m.group(1)
    if pkg['type'] == 'deb':
        rc, out = _run(['dpkg-query', '-W', '-f=${Version}', 'voidpulse'])
        if rc == 0 and out.strip():
            return out.strip()
    if pkg['type'] == 'rpm':
        rc, out = _run(['rpm', '-q', '--qf', '%{VERSION}', 'voidpulse'])
        if rc == 0 and out.strip():
            return out.strip()
    return '0'


# ══════════════════════════════════════════════════════════════════════════════
#  GitHub release query
# ══════════════════════════════════════════════════════════════════════════════
def fetch_releases() -> list:
    """GET the release list. Raises on network/HTTP failure; callers catch."""
    req = urllib.request.Request(
        API_URL,
        headers={'User-Agent': _UA,
                 'Accept': 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        data = json.loads(resp.read().decode('utf-8', 'replace'))
    return data if isinstance(data, list) else []


def newest_release(releases: list) -> Optional[dict]:
    """Highest published, non-draft, non-prerelease entry.

    Sorted by parsed version rather than publish date because a backported patch
    release can be published after a newer minor.
    """
    live = [r for r in releases
            if not r.get('draft') and not r.get('prerelease') and r.get('tag_name')]
    if not live:
        return None
    return max(live, key=lambda r: vtuple(r['tag_name']))


# ══════════════════════════════════════════════════════════════════════════════
#  Asset matching
# ══════════════════════════════════════════════════════════════════════════════
def _is_appimage(name: str) -> bool:
    # appimagetool rides along in some releases and is not a VoidPulse build.
    return name.endswith('.AppImage') and not name.lower().startswith('appimagetool')


def classify_asset(name: str) -> Optional[tuple]:
    """('type', 'arch') for a release asset, or None if it is not a package."""
    if name.endswith('.flatpak'):
        return ('flatpak', 'noarch')
    if _is_appimage(name):
        m = re.search(r'-([A-Za-z0-9_]+)\.AppImage$', name)
        return ('appimage', m.group(1) if m else 'unknown')
    if name.endswith('.deb'):
        m = re.search(r'_([A-Za-z0-9]+)\.deb$', name)
        return ('deb', m.group(1) if m else 'unknown')
    if name.endswith('.rpm'):
        m = re.search(r'\.([A-Za-z0-9_]+)\.rpm$', name)
        return ('rpm', m.group(1) if m else 'noarch')
    if name.endswith('.apk'):
        return ('apk', 'noarch')
    if '.pkg.tar' in name:
        # voidpulse-2.0.0-1-x86_64.pkg.tar.zst
        m = re.search(r'-([A-Za-z0-9_]+)\.pkg\.tar', name)
        return ('pacman', m.group(1) if m else 'any')
    return None


def matching_asset(release: dict, pkg: dict) -> Optional[dict]:
    """The asset that can replace this install: same format *and* same arch.

    A format match with the wrong arch is not usable — an aarch64 AppImage will
    not run on x86_64 — so it deliberately falls through to the "no identical
    package type" path instead.
    """
    want_arch = pkg['arch']
    if pkg['type'] == 'rpm':
        want_arch = 'noarch'
    for a in release.get('assets', []):
        c = classify_asset(a.get('name', ''))
        if c and c[0] == pkg['type'] and c[1] == want_arch:
            return a
    return None


def available_choices(release: dict) -> list:
    """[(label, asset)] for every package asset in the release, grouped by
    format in a stable order so the no-match list does not shuffle."""
    order = ['flatpak', 'appimage', 'deb', 'rpm', 'pacman', 'apk']
    found = []
    for a in release.get('assets', []):
        c = classify_asset(a.get('name', ''))
        if not c:
            continue
        kind, arch = c
        label = PKG_LABELS.get(kind, kind)
        if arch not in ('noarch', 'unknown'):
            label = f'{label} — {arch}'
        found.append((order.index(kind) if kind in order else 99, label, a))
    found.sort(key=lambda t: (t[0], t[1]))
    return [(label, a) for _, label, a in found]


# ══════════════════════════════════════════════════════════════════════════════
#  Download
# ══════════════════════════════════════════════════════════════════════════════
def _download_dir(pkg: dict) -> Path:
    """Where a downloaded asset lands.

    An AppImage goes next to the one it replaces, so the update is a rename on
    the same filesystem and the user's chosen location is preserved. Everything
    else goes to the cache dir — inside the flatpak XDG_CACHE_HOME already
    points at ~/.var/app/org.voidpulse.VoidPulse/cache, which is writable in the
    sandbox and readable from the host, so `flatpak-spawn --host` can reach it.
    """
    if pkg['type'] == 'appimage' and pkg.get('path'):
        d = Path(pkg['path']).parent
        if os.access(d, os.W_OK):
            return d
    cache = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache')))
    d = cache / 'voidpulse' / 'updates'
    d.mkdir(parents=True, exist_ok=True)
    return d


class _Downloader(QThread):
    """Streams one asset to disk, reporting progress to the GUI thread."""

    progress    = pyqtSignal(int, int)   # bytes received, total (0 = unknown)
    finished_ok = pyqtSignal(str)        # final path
    failed      = pyqtSignal(str)

    _CHUNK = 256 * 1024

    def __init__(self, url: str, dest: Path, parent=None):
        super().__init__(parent)
        self._url  = url
        self._dest = Path(dest)
        self._stop = threading.Event()

    def cancel(self):
        self._stop.set()

    def run(self):
        part = self._dest.with_name(self._dest.name + '.part')
        try:
            req = urllib.request.Request(
                self._url, headers={'User-Agent': _UA, 'Accept': 'application/octet-stream'})
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                total = int(resp.headers.get('Content-Length') or 0)
                got = 0
                with open(part, 'wb') as fh:
                    while True:
                        if self._stop.is_set():
                            raise InterruptedError('cancelled')
                        buf = resp.read(self._CHUNK)
                        if not buf:
                            break
                        fh.write(buf)
                        got += len(buf)
                        self.progress.emit(got, total)
            os.replace(part, self._dest)
            self.finished_ok.emit(str(self._dest))
        except InterruptedError:
            part.unlink(missing_ok=True)
            self.failed.emit('Cancelled.')
        except Exception as exc:
            part.unlink(missing_ok=True)
            self.failed.emit(f'Download failed: {exc}')


# ══════════════════════════════════════════════════════════════════════════════
#  Desktop entry
# ══════════════════════════════════════════════════════════════════════════════
def _applications_dir() -> Path:
    return Path(os.environ.get(
        'XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'applications'


def _refresh_desktop_db(app_dir: Path) -> None:
    if shutil.which('update-desktop-database'):
        _run(['update-desktop-database', str(app_dir)], timeout=30)


def _install_appimage_icon() -> str:
    """Copy the icon out of the mounted AppImage so a generated entry has one.

    Returns the icon name to use — the themed name once the SVG is in place,
    otherwise the same name in the hope the system already provides it.
    """
    appdir = os.environ.get('APPDIR')
    if appdir:
        src = Path(appdir) / f'{APP_ID}.svg'
        dst = (Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
               / 'icons/hicolor/scalable/apps' / f'{APP_ID}.svg')
        try:
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        except Exception as exc:
            _log('icon not installed:', exc)
    return APP_ID


def update_desktop_entry(pkg: dict, old_path: str, new_path: str) -> str:
    """Point the menu entry at the file that now exists.

    Only AppImages need rewriting: their file name carries the version, so every
    update invalidates the Exec line. deb/rpm/apk/flatpak ship their own entry
    and the package manager replaces it — there the desktop database is just
    refreshed so the change is picked up without a re-login.
    """
    app_dir = _applications_dir()

    if pkg['type'] != 'appimage':
        _refresh_desktop_db(Path('/usr/share/applications'))
        _refresh_desktop_db(app_dir)
        return 'Desktop database refreshed.'

    old, new = str(old_path), str(new_path)
    touched = []
    try:
        entries = sorted(app_dir.glob('*.desktop')) if app_dir.is_dir() else []
    except Exception:
        entries = []

    # Both the exact old path and any sibling VoidPulse-<ver>-<arch>.AppImage
    # are rewritten: AppImageLauncher writes its own entry with a path we never
    # handed out, and a user may have skipped a version.
    sibling = re.compile(
        re.escape(str(Path(old).parent)) + r'/VoidPulse-[\d.]+-[A-Za-z0-9_]+\.AppImage')
    for f in entries:
        try:
            text = f.read_text(errors='ignore')
        except Exception:
            continue
        if old not in text and not sibling.search(text):
            continue
        fixed = sibling.sub(new, text.replace(old, new))
        if fixed != text:
            try:
                f.write_text(fixed)
                touched.append(f.name)
            except Exception as exc:
                _log(f'could not rewrite {f}:', exc)

    if not touched:
        # No entry existed — write one so the new AppImage is reachable from the
        # menu instead of only from wherever the old file was launched.
        icon = _install_appimage_icon()
        entry = app_dir / f'{APP_ID}.desktop'
        try:
            app_dir.mkdir(parents=True, exist_ok=True)
            entry.write_text(
                '[Desktop Entry]\n'
                'Name=VoidPulse\n'
                'Comment=Advanced music player\n'
                f'Exec="{new}" %f\n'
                f'TryExec={new}\n'
                f'Icon={icon}\n'
                'Terminal=false\n'
                'Type=Application\n'
                'Categories=AudioVideo;Audio;Music;Player;\n'
                'MimeType=audio/flac;audio/mpeg;audio/ogg;audio/opus;audio/mp4;'
                'audio/aac;audio/x-wav;audio/wav;audio/aiff;audio/x-aiff;\n')
            os.chmod(entry, 0o644)
            touched.append(entry.name)
        except Exception as exc:
            _log('could not create desktop entry:', exc)

    _refresh_desktop_db(app_dir)
    return ('Desktop entry updated: ' + ', '.join(touched)) if touched \
        else 'No desktop entry found to update.'


# ══════════════════════════════════════════════════════════════════════════════
#  Install
# ══════════════════════════════════════════════════════════════════════════════
def distro_ids() -> set:
    """Everything /etc/os-release calls this system: ID plus ID_LIKE.

    ID_LIKE is what makes derivatives work without a table of every distro —
    Linux Mint says `ubuntu debian`, Manjaro says `arch`, Nobara says `fedora`.
    """
    ids = set()
    try:
        for line in Path('/etc/os-release').read_text(errors='ignore').splitlines():
            k, _, v = line.partition('=')
            if k in ('ID', 'ID_LIKE'):
                ids.update(v.strip().strip('"\'').lower().split())
    except Exception:
        pass
    return ids


def native_tool(pkg_type: str) -> tuple:
    """(argv-prefix, tool name) for installing a `pkg_type` file on this system.

    Picked from the distro rather than from the file extension alone: an .rpm
    goes through dnf on Fedora and zypper on openSUSE, and those take different
    flags for the same thing. Every command is non-interactive and accepts an
    unsigned package, because the file was just downloaded from the project's
    own release page and no repository signed it.
    """
    ids = distro_ids()
    have = shutil.which

    if pkg_type == 'rpm':
        if have('dnf') and ('fedora' in ids or 'rhel' in ids or not have('zypper')):
            return (['dnf', 'install', '-y', '--nogpgcheck'], 'dnf')
        if have('zypper'):
            return (['zypper', '--non-interactive', 'install',
                     '--allow-unsigned-rpm'], 'zypper')
        if have('dnf'):
            return (['dnf', 'install', '-y', '--nogpgcheck'], 'dnf')
        return (['rpm', '-Uvh', '--force', '--nosignature'], 'rpm')

    if pkg_type == 'deb':
        if have('apt-get'):
            # A path argument is what tells apt-get to install a local file
            # rather than look the name up in the repositories.
            return (['apt-get', 'install', '-y', '--allow-downgrades',
                     '--allow-unauthenticated'], 'apt-get')
        return (['dpkg', '-i', '--force-confnew'], 'dpkg')

    if pkg_type == 'pacman':
        return (['pacman', '-U', '--noconfirm'], 'pacman')

    if pkg_type == 'apk':
        return (['apk', 'add', '--allow-untrusted'], 'apk')

    return ([], '')


def install_plan(pkg: dict, file_path: str) -> dict:
    """How this file gets installed, resolved before anything is run.

    Returned up front so the popup can tell the user which tool is about to run
    and whether it will need a password, instead of surprising them with an
    authentication prompt halfway through.
    """
    fp = str(file_path)
    t = pkg['type']

    if t == 'appimage':
        return {'kind': 'appimage', 'cmd': [], 'sudo': False, 'tool': 'file swap',
                'why': 'Replacing the AppImage in place'}

    if t == 'flatpak':
        # A --user install needs no privileges at all, and --reinstall is what
        # upgrades an already-installed ref from a bundle; a plain install
        # would abort with "already installed".
        return {'kind': 'cmd',
                'cmd': list(host_cmd('flatpak', 'install', '--user', '-y',
                                     '--reinstall', fp)),
                'sudo': False, 'tool': 'flatpak',
                'why': 'Installing the bundle into your user flatpak install'}

    prefix, tool = native_tool(t)
    if not prefix:
        return {'kind': 'unsupported', 'cmd': [], 'sudo': False, 'tool': '',
                'why': f'{PKG_LABELS.get(t, t)} installs cannot be updated automatically.'}
    if not shutil.which(prefix[0]):
        return {'kind': 'unsupported', 'cmd': [], 'sudo': False, 'tool': tool,
                'why': f'{tool} is not installed on this system.'}

    return {'kind': 'cmd', 'cmd': prefix + [fp], 'sudo': os.geteuid() != 0,
            'tool': tool, 'why': f'Installing with {tool}'}


# Marker the popup matches on to decide whether the password field is worth
# reopening; kept in one place so the two ends cannot drift apart.
_PW_REJECTED = 'The password was not accepted'


def _sudo_wrap(cmd: list) -> list:
    """sudo reading the password from stdin, with its own prompt suppressed.

    -S sends the prompt to stderr and reads the password from stdin; -p ''
    silences it, because the popup already asked. Without -S sudo would try to
    open the terminal it does not have and fail outright.
    """
    return ['sudo', '-S', '-p', ''] + cmd


def swap_appimage(pkg: dict, fp: str, log) -> tuple:
    """Replace the running AppImage with the downloaded one."""
    old = pkg.get('path', '')
    try:
        os.chmod(fp, 0o755)
        log(f'Marked executable: {Path(fp).name}')
    except Exception as exc:
        return False, f'Could not make the AppImage executable: {exc}'
    # The old file is still mounted by the running process; unlinking it is
    # safe on Linux because the FUSE mount holds the inode open.
    if old and os.path.realpath(old) != os.path.realpath(fp):
        try:
            Path(old).unlink(missing_ok=True)
            log(f'Removed the old AppImage: {Path(old).name}')
        except Exception as exc:
            log(f'Could not remove the old AppImage: {exc}')
    pkg['path'] = fp
    st = _load_state()
    st['package'] = pkg
    _save_state(st)
    return True, 'AppImage replaced.'


class _Installer(QThread):
    """Runs the install plan, streaming every line it produces to the popup.

    The command is not captured and reported at the end: dnf/zypper/apt take
    tens of seconds and a frozen dialog with no output looks like a hang, so
    stdout and stderr are merged and emitted line by line as they arrive.
    """

    log  = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, pkg: dict, path: str, plan: dict,
                 password: str = '', parent=None):
        super().__init__(parent)
        self._pkg  = pkg
        self._path = str(path)
        self._plan = plan
        self._pw   = password

    def run(self):
        try:
            ok, msg = self._work()
        except Exception as exc:
            ok, msg = False, f'Install failed: {exc}'
        self.done.emit(ok, msg)

    def _work(self) -> tuple:
        plan = self._plan
        if plan['kind'] == 'unsupported':
            return False, plan['why']

        if plan['kind'] == 'appimage':
            self.log.emit(plan['why'] + '…')
            # Captured before the swap: rewriting the desktop entry needs the
            # path that is about to stop existing.
            old = self._pkg.get('path', '')
            ok, msg = swap_appimage(self._pkg, self._path, self.log.emit)
            if not ok:
                return False, msg
            self.log.emit(msg)
            return self._finish_desktop(old)

        cmd = _sudo_wrap(plan['cmd']) if plan['sudo'] else list(plan['cmd'])
        self.log.emit(plan['why'] + '…')
        self.log.emit('$ ' + ' '.join(
            ('sudo' if c == 'sudo' else c) for c in cmd if c not in ('-S', '-p', '')))

        rc, tail = self._stream(cmd)
        if rc != 0:
            # The password case leads, because it is the one failure the user
            # can fix from this dialog — _on_installed reopens the field for it.
            if plan['sudo'] and any(
                    k in tail.lower() for k in ('incorrect password', 'sorry, try again',
                                                'authentication failure',
                                                'no password was provided')):
                return False, (f'{_PW_REJECTED} — {plan["tool"]} did not run.'
                               f'\n\n{tail}')
            return False, f'{plan["tool"]} exited with code {rc}.\n\n{tail}'
        return self._finish_desktop()

    def _stream(self, cmd: list) -> tuple:
        """Run `cmd`, emitting each output line. Returns (rc, last lines)."""
        env = dict(os.environ, DEBIAN_FRONTEND='noninteractive', LC_ALL='C')
        p = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
        try:
            if self._pw:
                p.stdin.write(self._pw + '\n')
                p.stdin.flush()
        except Exception:
            pass                      # command may not read stdin at all
        try:
            p.stdin.close()
        except Exception:
            pass

        tail = []
        for line in p.stdout:
            line = line.rstrip()
            if not line:
                continue
            tail.append(line)
            del tail[:-14]            # only the end is worth reporting on failure
            self.log.emit(line)
        return p.wait(), '\n'.join(tail)

    def _finish_desktop(self, old_path: str = '') -> tuple:
        self.log.emit('Updating the desktop entry…')
        msg = update_desktop_entry(self._pkg, old_path, self._path)
        self.log.emit(msg)
        return True, msg


def relaunch(pkg: dict) -> None:
    """Start the updated build and leave; called from the Restart button."""
    try:
        if pkg['type'] == 'appimage' and pkg.get('path'):
            cmd = [pkg['path']]
        elif pkg['type'] == 'flatpak':
            cmd = host_cmd('flatpak', 'run', APP_ID)
        else:
            cmd = [shutil.which('voidpulse') or 'voidpulse']
        subprocess.Popen(cmd, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        _log('relaunch failed:', exc)
    QApplication.instance().quit()


# ══════════════════════════════════════════════════════════════════════════════
#  Popup
# ══════════════════════════════════════════════════════════════════════════════
def _fmt_size(n: int) -> str:
    if n <= 0:
        return '—'
    mb = n / (1024 * 1024)
    return f'{mb:.1f} MB' if mb >= 1 else f'{n / 1024:.0f} KB'


class UpdatePopup(QFrame):
    """Release announcement, parented to the main window like every other popup.

    Two shapes, decided by whether the release ships this install's format:
      • match    — title, changelog, [Update] [Skip for now] [Skip this version]
      • no match — title, the formats it does ship as download buttons, and the
                   same two skip buttons.
    Both collapse into a progress row while a download or install runs.
    """

    def __init__(self, parent: QWidget, pkg: dict, release: dict,
                 asset: Optional[dict], cur_ver: str):
        super().__init__(parent)
        self.setObjectName('update_popup')
        self._pkg     = pkg
        self._release = release
        self._asset   = asset
        self._new_ver = (_VER_RE.search(release.get('tag_name', '')) or
                         _VER_RE.search(release.get('name', '') or '') )
        self._new_ver = self._new_ver.group(1) if self._new_ver else release.get('tag_name', '?')
        self._cur_ver = cur_ver
        self._worker  = None
        self._overlay = None
        self._save_to = None     # set when downloading a non-matching format
        self._plan    = None     # resolved install plan, once the file is down
        self._dl_path = ''

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 18)
        root.setSpacing(10)
        self.setFixedWidth(460)

        # ── Title ─────────────────────────────────────────────────────────────
        self._title = QLabel()
        self._title.setObjectName('popup_title')
        self._title.setWordWrap(True)
        self._title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        if asset:
            self._title.setText(f'v{self._new_ver} IS OUT!')
        else:
            self._title.setText(
                f'v{self._new_ver} IS OUT BUT NO IDENTICAL PACKAGE TYPE FOUND')
        root.addWidget(self._title)

        self._divider = QFrame()
        self._divider.setFixedHeight(1)
        root.addWidget(self._divider)

        # ── Subtitle: what is installed, and what is on offer ─────────────────
        label = PKG_LABELS.get(pkg['type'], pkg['type'])
        if pkg['arch'] not in ('noarch', ''):
            label = f"{label} · {pkg['arch']}"
        if asset:
            sub = (f'Installed v{cur_ver} · {label}   →   '
                   f'{asset["name"]}  ({_fmt_size(asset.get("size", 0))})')
        else:
            sub = (f'Installed v{cur_ver} · {label} — this release does not ship '
                   f'that package. Available downloads:')
        self._sub = QLabel(sub)
        self._sub.setWordWrap(True)
        self._sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self._sub)

        # ── Body: changelog, or the list of other formats ─────────────────────
        if asset:
            self._body = QTextBrowser()
            self._body.setOpenExternalLinks(True)
            self._body.setFrameShape(QFrame.Shape.NoFrame)
            self._body.setFixedHeight(190)
            body_md = (release.get('body') or '').strip()
            head = release.get('name') or release.get('tag_name') or ''
            self._body.setMarkdown(f'### {head}\n\n{body_md}' if body_md
                                   else f'### {head}\n\n_No changelog provided._')
            root.addWidget(self._body)
        else:
            self._body = QScrollArea()
            self._body.setWidgetResizable(True)
            self._body.setFrameShape(QFrame.Shape.NoFrame)
            self._body.setFixedHeight(190)
            inner = QWidget()
            col = QVBoxLayout(inner)
            col.setContentsMargins(0, 0, 8, 0)
            col.setSpacing(6)
            self._choice_btns = []
            for text, a in available_choices(release):
                b = QPushButton(f'{text}   ·   {_fmt_size(a.get("size", 0))}')
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _=False, aa=a: self._download_only(aa))
                col.addWidget(b)
                self._choice_btns.append(b)
            if not self._choice_btns:
                col.addWidget(QLabel('This release has no downloadable packages.'))
            col.addStretch(1)
            self._body.setWidget(inner)
            root.addWidget(self._body)

        # ── Live log, shown in place of the body once work starts ─────────────
        # Every step the updater takes is written here, including the exact
        # command and the package manager's own output, so a failure is visible
        # rather than collapsed into "install failed".
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFrameShape(QFrame.Shape.NoFrame)
        self._log_view.setFixedHeight(190)
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._log_view.hide()
        root.addWidget(self._log_view)

        # ── Password row, shown only when the plan needs sudo ─────────────────
        self._pw_row = QWidget()
        pwl = QVBoxLayout(self._pw_row)
        pwl.setContentsMargins(0, 0, 0, 0)
        pwl.setSpacing(6)
        self._pw_lbl = QLabel()
        self._pw_lbl.setWordWrap(True)
        pwl.addWidget(self._pw_lbl)
        pw_in = QHBoxLayout()
        pw_in.setSpacing(8)
        self._pw_edit = QLineEdit()
        self._pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw_edit.setPlaceholderText('Password')
        self._pw_edit.returnPressed.connect(self._submit_password)
        self._btn_pw_ok = QPushButton('Install')
        self._btn_pw_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_pw_ok.clicked.connect(self._submit_password)
        self._btn_pw_cancel = QPushButton('Cancel')
        self._btn_pw_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_pw_cancel.clicked.connect(self._dismiss)
        pw_in.addWidget(self._pw_edit, 1)
        pw_in.addWidget(self._btn_pw_ok, 0)
        pw_in.addWidget(self._btn_pw_cancel, 0)
        pwl.addLayout(pw_in)
        self._pw_row.hide()
        root.addWidget(self._pw_row)

        # ── Progress row, hidden until something is running ───────────────────
        self._prog_row = QWidget()
        pr = QHBoxLayout(self._prog_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(8)
        self._bar = QProgressBar()
        self._bar.setTextVisible(True)
        self._bar.setFixedHeight(18)
        self._btn_cancel = QPushButton('Cancel')
        self._btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cancel.clicked.connect(self._cancel)
        pr.addWidget(self._bar, 1)
        pr.addWidget(self._btn_cancel, 0)
        self._prog_row.hide()
        root.addWidget(self._prog_row)

        # ── Buttons ───────────────────────────────────────────────────────────
        self._btn_row = QWidget()
        br = QHBoxLayout(self._btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        br.setSpacing(8)
        br.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._btn_primary = None
        if asset:
            self._btn_primary = QPushButton('Update')
            self._btn_primary.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btn_primary.clicked.connect(self._start_update)
            br.addWidget(self._btn_primary)

        self._btn_skip = QPushButton('Skip for now')
        self._btn_skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_skip.clicked.connect(self._dismiss)
        br.addWidget(self._btn_skip)

        self._btn_skip_ver = QPushButton('Skip this version entirely')
        self._btn_skip_ver.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_skip_ver.clicked.connect(self._skip_version)
        br.addWidget(self._btn_skip_ver)

        root.addWidget(self._btn_row)

        self.refresh_theme()
        self.hide()

    # ── Painting / theme ─────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        cr = _r(11)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(_c.BG)))
        p.drawRoundedRect(r, cr, cr)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(_c.ACC), 3.0))
        p.drawRoundedRect(r, cr, cr)
        p.end()

    def refresh_theme(self) -> None:
        """Re-apply the child stylesheets, which bake in palette values."""
        self._divider.setStyleSheet(f'background:{_c.BORD}; margin:0;')
        self._sub.setStyleSheet(
            f'color:{_c.FG2}; font-size:11px; background:transparent;')
        self._body.setStyleSheet(
            f'QTextBrowser, QScrollArea {{ background:{_c.BG2}; color:{_c.FG};'
            f'  border:1px solid {_c.BORD}; border-radius:{_r(8)}px;'
            f'  font-size:11px; padding:8px; }}'
            f'QWidget {{ background:transparent; }}')
        self._log_view.setStyleSheet(
            f'QPlainTextEdit {{ background:{_c.BG2}; color:{_c.FG2};'
            f'  border:1px solid {_c.BORD}; border-radius:{_r(8)}px;'
            f'  font-family:monospace; font-size:10px; padding:8px; }}')
        self._pw_lbl.setStyleSheet(
            f'color:{_c.FG2}; font-size:11px; background:transparent;')
        self._pw_edit.setStyleSheet(
            f'QLineEdit {{ background:{_c.BG3}; color:{_c.FG};'
            f'  border:1px solid {_c.B2}; border-radius:{_r(6)}px;'
            f'  padding:5px 10px; font-size:11px; }}'
            f'QLineEdit:focus {{ border-color:{_c.ACC}; }}')
        self._bar.setStyleSheet(
            f'QProgressBar {{ background:{_c.BG2}; color:{_c.FG};'
            f'  border:1px solid {_c.BORD}; border-radius:{_r(6)}px;'
            f'  font-size:10px; text-align:center; }}'
            f'QProgressBar::chunk {{ background:{_c.ACC};'
            f'  border-radius:{_r(5)}px; }}')

        primary = (f'QPushButton {{ background:{_c.ACC}; color:#fff; border:none;'
                   f'  border-radius:{_r(6)}px; font-size:11px; font-weight:600;'
                   f'  padding:6px 14px; }}'
                   f'QPushButton:hover {{ background:{_c.ACCH}; }}'
                   f'QPushButton:disabled {{ background:{_c.BG3}; color:{_c.FG2}; }}')
        secondary = (f'QPushButton {{ background:transparent; color:{_c.FG2};'
                     f'  border:1px solid {_c.BORD}; border-radius:{_r(6)}px;'
                     f'  font-size:11px; padding:6px 14px; }}'
                     f'QPushButton:hover {{ color:{_c.FG}; border-color:{_c.FG2}; }}')
        if self._btn_primary is not None:
            self._btn_primary.setStyleSheet(primary)
        self._btn_pw_ok.setStyleSheet(primary)
        for b in (self._btn_skip, self._btn_skip_ver, self._btn_cancel,
                  self._btn_pw_cancel):
            b.setStyleSheet(secondary)
        for b in getattr(self, '_choice_btns', []):
            b.setStyleSheet(secondary)
        self.update()

    # ── Placement ────────────────────────────────────────────────────────────
    def _reposition(self) -> None:
        p = self.parent()
        if p is None:
            return
        self.adjustSize()
        self.move(max(4, (p.width()  - self.width())  // 2),
                  max(4, (p.height() - self.height()) // 2))

    def show_centered(self) -> None:
        """Show above the scrim.

        The scrim is a child of the main window, so the popup has to be one too:
        parented any deeper — to the central widget, say — it sits *inside* a
        sibling the scrim paints over, which both dims it and hands every click
        to the scrim, whose job is to dismiss on an outside press. Same parent
        plus raise_() puts it on top, where its buttons are reachable.
        """
        win = self.parent()
        while win is not None and not isinstance(win, QMainWindow):
            win = win.parent()
        try:
            from widgets_base import _ModalOverlay
            if win is not None and self.parent() is win:
                self._overlay = _ModalOverlay(win, self, watch_hide=True)
                self._overlay.show()
        except Exception as exc:
            _log('no modal scrim:', exc)
        self._reposition()
        self.show()
        self.raise_()
        self.activateWindow()
        if self._btn_primary is not None:
            self._btn_primary.setFocus()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.isVisible():
            self._reposition()

    # ── Actions ──────────────────────────────────────────────────────────────
    def _busy(self, on: bool, label: str = '') -> None:
        self._btn_row.setVisible(not on)
        self._prog_row.setVisible(on)
        if on:
            self._bar.setRange(0, 0)
            self._bar.setFormat(label)
        for b in getattr(self, '_choice_btns', []):
            b.setEnabled(not on)
        self._reposition()

    def _say(self, line: str) -> None:
        """Append a line to the visible log, revealing it on the first call."""
        if not self._log_view.isVisible():
            self._body.hide()
            self._log_view.show()
        for part in str(line).splitlines() or ['']:
            self._log_view.appendPlainText(part)
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _start_update(self) -> None:
        """[Update] — fetch the matching asset, then hand it to the installer."""
        self._save_to = None
        self._say(f'Package type: {PKG_LABELS.get(self._pkg["type"], self._pkg["type"])}'
                  f' ({self._pkg["arch"]})')
        self._say(f'Downloading {self._asset["name"]} '
                  f'({_fmt_size(self._asset.get("size", 0))})…')
        self._begin_download(self._asset)

    def _download_only(self, asset: dict) -> None:
        """A button in the no-match list: fetch it, but never install it.

        Installing a different format than the one in use is a migration, not an
        update — it would leave two copies of VoidPulse on the system — so the
        file is saved and the path is shown instead.
        """
        self._save_to = asset
        self._begin_download(asset)

    def _begin_download(self, asset: dict) -> None:
        if self._worker is not None:
            return
        url = asset.get('browser_download_url')
        if not url:
            self._fail('That asset has no download URL.')
            return
        dest = _download_dir(self._pkg) / asset['name']
        self._busy(True, 'Connecting…')
        self._worker = _Downloader(url, dest, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_downloaded)
        self._worker.failed.connect(self._fail)
        self._worker.start()

    def _on_progress(self, got: int, total: int) -> None:
        if total > 0:
            self._bar.setRange(0, total)
            self._bar.setValue(got)
            self._bar.setFormat(f'{_fmt_size(got)} / {_fmt_size(total)}  (%p%)')
        else:
            self._bar.setFormat(f'{_fmt_size(got)} downloaded')

    def _on_downloaded(self, path: str) -> None:
        self._worker = None
        if self._save_to is not None:
            self._finish(f'Saved to:\n{path}\n\nInstall it with your package '
                         f'manager to switch package type.')
            return

        self._dl_path = path
        self._say(f'Downloaded to {path}')

        plan = install_plan(self._pkg, path)
        self._plan = plan
        if plan['kind'] == 'unsupported':
            self._fail(plan['why'])
            return

        distro = ', '.join(sorted(distro_ids())) or 'unknown'
        self._say(f'System: {distro}')
        self._say(f'Installer: {plan["tool"]}')

        if not plan['sudo']:
            # flatpak --user and the AppImage swap both run as the user.
            self._run_install('')
            return

        # Everything system-wide goes through sudo, and sudo needs the password
        # on stdin because there is no terminal to prompt on. The offer buttons
        # go away while it is up: pressing Update again here would start a
        # second download on top of the one already waiting to install.
        self._busy(False)
        self._btn_row.hide()
        self._pw_lbl.setText(
            f'Installing with {plan["tool"]} needs administrator rights.\n'
            f'Enter your password to continue.')
        self._pw_row.show()
        self._pw_edit.setFocus()
        self._reposition()

    def _submit_password(self) -> None:
        pw = self._pw_edit.text()
        if not pw:
            self._pw_lbl.setText('Enter your password to continue.')
            return
        self._pw_edit.clear()
        self._pw_row.hide()
        self._run_install(pw)

    def _run_install(self, password: str) -> None:
        self._busy(True, f'Installing with {self._plan["tool"]}…')
        self._btn_cancel.setEnabled(False)   # nothing safe to cancel mid-install
        self._worker = _Installer(self._pkg, self._dl_path, self._plan,
                                  password, self)
        self._worker.log.connect(self._say)
        self._worker.done.connect(self._on_installed)
        self._worker.start()

    def _on_installed(self, ok: bool, msg: str) -> None:
        self._worker = None
        self._btn_cancel.setEnabled(True)
        if not ok:
            self._say('')
            self._say('FAILED — ' + msg.splitlines()[0])
            self._fail(msg)
            if msg.startswith(_PW_REJECTED):
                # Recoverable in place: put the field back rather than making
                # the user run the whole download again over a typo.
                self._busy(False)
                self._btn_row.hide()
                self._pw_lbl.setText(f'{_PW_REJECTED}. Try again.')
                self._pw_row.show()
                self._pw_edit.setFocus()
                self._reposition()
            return
        self._say('')
        self._say(f'VoidPulse v{self._new_ver} installed.')
        # The new version is live on disk; forget any skip for it.
        st = _load_state()
        st['skipped'] = [v for v in st.get('skipped', []) if v != self._new_ver]
        st['last_installed'] = self._new_ver
        _save_state(st)
        self._finish(f'VoidPulse v{self._new_ver} installed. '
                     f'Restart to run the new version.', restart=True)

    def _cancel(self) -> None:
        w = self._worker
        if isinstance(w, _Downloader):
            w.cancel()
        else:
            # An install is already underway; cancelling it would be worse than
            # letting it finish, so only the popup goes away.
            self._dismiss()

    def _fail(self, msg: str) -> None:
        """Report a failure but keep the log on screen — it holds the cause."""
        self._worker = None
        self._pw_row.hide()
        self._busy(False)
        self._sub.setText(msg.splitlines()[0] if msg else 'Failed.')
        self._reposition()

    def _finish(self, msg: str, restart: bool = False) -> None:
        """Collapse to a result message with a Close (and maybe Restart) button."""
        self._busy(False)
        self._pw_row.hide()
        self._sub.setText(msg)
        # The log outlives the run when there is one; only the changelog and the
        # download list are done with.
        if not self._log_view.isVisible():
            self._body.hide()
        if self._btn_primary is not None:
            self._btn_primary.setVisible(restart)
            if restart:
                self._btn_primary.setText('Restart now')
                try:
                    self._btn_primary.clicked.disconnect()
                except Exception:
                    pass
                self._btn_primary.clicked.connect(lambda: relaunch(self._pkg))
        self._btn_skip.setText('Close')
        self._btn_skip_ver.hide()
        self._reposition()

    def _skip_version(self) -> None:
        st = _load_state()
        skipped = set(st.get('skipped', []))
        skipped.add(self._new_ver)
        st['skipped'] = sorted(skipped)
        _save_state(st)
        _log(f'v{self._new_ver} skipped permanently')
        self._dismiss()

    def _dismiss(self) -> None:
        w = self._worker
        if isinstance(w, _Downloader):
            w.cancel()
        self.hide()
        self.deleteLater()


# ══════════════════════════════════════════════════════════════════════════════
#  Startup check
# ══════════════════════════════════════════════════════════════════════════════
class _Checker(QObject):
    """Runs the network query off the GUI thread and reports back on it."""

    ready = pyqtSignal(object, object, str)   # release, asset|None, current version
    quiet = pyqtSignal(str)                   # nothing to show / failure reason

    def __init__(self, pkg: dict, force: bool, parent=None):
        super().__init__(parent)
        self._pkg   = pkg
        self._force = force

    def start(self) -> None:
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        try:
            rel = newest_release(fetch_releases())
            if rel is None:
                self.quiet.emit('no published releases')
                return
            cur = installed_version(self._pkg)
            new_tag = rel.get('tag_name', '')
            new_ver_m = _VER_RE.search(new_tag)
            new_ver = new_ver_m.group(1) if new_ver_m else new_tag

            if not self._force and vtuple(new_tag) <= vtuple(cur):
                self.quiet.emit(f'up to date (v{cur})')
                return
            if not self._force and new_ver in _load_state().get('skipped', []):
                self.quiet.emit(f'v{new_ver} skipped by the user')
                return

            self.ready.emit(rel, matching_asset(rel, self._pkg), cur)
        except urllib.error.HTTPError as exc:
            self.quiet.emit(f'GitHub returned {exc.code}')
        except Exception as exc:
            self.quiet.emit(f'check failed: {exc}')


# Kept alive for the process: a local reference would be collected mid-flight.
_active_checker = None
_active_popup   = None


def _show(main_window, release, asset, cur_ver) -> None:
    global _active_popup
    try:
        # Parented to the window itself, not the central widget: see
        # UpdatePopup.show_centered for why the scrim demands it.
        _active_popup = UpdatePopup(main_window, resolve_package(),
                                    release, asset, cur_ver)
        _active_popup.show_centered()
    except Exception as exc:
        _log('popup failed:', exc)


def check_on_startup(main_window, delay_ms: int = _START_DELAY_MS) -> None:
    """Poll for a new release once, shortly after the window is up.

    Safe to call unconditionally — a source checkout is skipped (there is
    nothing to replace), and any failure is logged and dropped. Set
    VOIDPULSE_UPDATE_FORCE=1 to run it anyway and ignore both the version
    comparison and the skip list.
    """
    global _active_checker
    try:
        force = os.environ.get('VOIDPULSE_UPDATE_FORCE') == '1'
        if os.environ.get('VOIDPULSE_NO_UPDATE_CHECK') == '1':
            return
        pkg = resolve_package()
        if pkg['type'] == 'source' and not force:
            _log('running from a source checkout — update check skipped')
            return

        chk = _Checker(pkg, force, main_window)
        chk.ready.connect(lambda rel, asset, cur: _show(main_window, rel, asset, cur))
        chk.quiet.connect(lambda why: _log(why))
        _active_checker = chk
        QTimer.singleShot(max(0, delay_ms), chk.start)
    except Exception as exc:
        _log('not started:', exc)


def check_now(main_window) -> None:
    """Immediate check for a menu item; still respects the skip list."""
    check_on_startup(main_window, delay_ms=0)


# ══════════════════════════════════════════════════════════════════════════════
#  CLI — inspection without launching the player
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    args = sys.argv[1:]
    if '--reset' in args:
        st = _load_state()
        st.pop('skipped', None)
        st.pop('package', None)
        _save_state(st)
        print('update.json cleared')
        sys.exit(0)

    pkg = resolve_package()
    print(f'package    : {pkg["type"]} ({pkg["arch"]}) {pkg.get("path", "")}')
    print(f'installed  : v{installed_version(pkg)}')
    print(f'state file : {STATE_PATH}')
    print(f'skipped    : {_load_state().get("skipped", [])}')
    if '--check' in args:
        rel = newest_release(fetch_releases())
        if rel is None:
            print('latest     : none')
            sys.exit(0)
        print(f'latest     : {rel["tag_name"]}  ({rel.get("name", "")})')
        a = matching_asset(rel, pkg)
        print(f'match      : {a["name"] if a else "NONE — no identical package type"}')
        if not a:
            for label, asset in available_choices(rel):
                print(f'  offer    : {label:22s} {asset["name"]}')
