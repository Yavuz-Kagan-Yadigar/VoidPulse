"""
VoidPulse — ALSA support: device enumeration, sample-rate probing, and D-Bus
device reservation.

Depends only on constants.py, so player.py and settings_popup.py can both
import it without creating a cycle.
"""
from constants import *
import glob as _glob
import re as _re
import time as _time

# ══════════════════════════════════════════════════════════════════════════════
#  Device enumeration (/proc/asound) and rate probing (aplay)
# ══════════════════════════════════════════════════════════════════════════════

_CARDS_RE = _re.compile(
    r'^\s*(\d+)\s+\[([^\]]*)\]:\s*\S.*\n\s+(.*)$', _re.MULTILINE)
_PCM_DEV_RE = _re.compile(r'pcm(\d+)p$')
_RATE_LINE_RE = _re.compile(r'^RATE:\s*(.+)$', _re.MULTILINE)
_PCM_ID_RE = _re.compile(r'^id:\s*(.+)$', _re.MULTILINE)
_PCM_NAME_RE = _re.compile(r'^name:\s*(.+)$', _re.MULTILINE)


def _pcm_label(card_num: str, dev_num: int) -> str:
    """Human name for one playback PCM, from /proc/asound/cardN/pcmDp/info.

    Cards routinely expose several playback devices — analog, a deep-buffer
    alias and one PCM per HDMI connector are typical — and the card name alone
    is identical for all of them. `id:` is populated on every driver seen
    ('HDA Analog (*)', 'HDMI1 (*)'); `name:` is often blank outside HDMI, so it
    is only the fallback. Returns '' when neither is readable.
    """
    try:
        with open(f'/proc/asound/card{card_num}/pcm{dev_num}p/info') as fh:
            info = fh.read()
    except Exception:
        return ''
    for rx in (_PCM_ID_RE, _PCM_NAME_RE):
        m = rx.search(info)
        if m:
            # The trailing '(*)' only marks the driver's default subdevice
            label = m.group(1).strip().removesuffix('(*)').strip()
            if label:
                return label
    return ''


def probe_alsa_devices() -> list:
    """Return [(display_name, device_id)] for available ALSA playback devices.

    Reads /proc/asound directly instead of shelling out to `aplay -l`: aplay
    (alsa-utils) is not part of the flatpak runtime, so under flatpak the old
    aplay-based probe always hit its except-Exception branch and silently
    returned an empty list, even though /proc/asound and /dev/snd are visible
    in the sandbox. /proc/asound's card/pcm layout is a stable kernel ABI, not
    driver-specific formatting the way aplay's text output is.
    """
    devices = []
    try:
        with open('/proc/asound/cards') as fh:
            cards_text = fh.read()
    except Exception:
        return devices
    for m in _CARDS_RE.finditer(cards_text):
        card_num = m.group(1)
        card_id = m.group(2).strip()        # named id, e.g. 'SIMGOT'
        card_name = m.group(3).strip()
        try:
            pcm_dirs = _glob.glob(f'/proc/asound/card{card_num}/pcm*p')
        except Exception:
            continue
        numbered = []
        for pcm_dir in pcm_dirs:
            dm = _PCM_DEV_RE.search(pcm_dir)
            if dm:
                numbered.append(int(dm.group(1)))
        # Only disambiguate when there is something to disambiguate: a card with a
        # single playback PCM reads better as just the card name.
        multi = len(numbered) > 1
        for dev_num in sorted(numbered):        # numeric, not lexicographic ('31' < '3')
            label = f'{card_name}'[:32]
            if multi:
                pcm = _pcm_label(card_num, dev_num)
                label = f'{label} · {pcm[:24]}' if pcm else f'{label} · dev {dev_num}'
            devices.append((f'ALSA: {label}', f'plughw:{card_id},{dev_num}'))
    return devices


_hw_rate_cache: dict = {}   # device_id → ('discrete'|'range', rates)


def _parse_rate_field(dump_text: str):
    """Parse the RATE: line of `aplay --dump-hw-params`.

    Brackets mean a continuous range: 'RATE: [8000 192000]'. Without them the
    line is an exact list, often non-contiguous: 'RATE: 44100 48000 96000'.

    Returns ('discrete', rates), ('range', (lo, hi)), or (None, None).
    """
    m = _RATE_LINE_RE.search(dump_text)
    if not m:
        return None, None
    field = m.group(1).strip()
    nums = [int(x) for x in _re.findall(r'\d+', field)]
    if not nums:
        return None, None
    if field.startswith(('[', '(')):
        return 'range', (min(nums), max(nums))
    return 'discrete', tuple(sorted(set(nums)))


def probe_alsa_hw_rate(device_id: str, timeout_s: float = 2.0):
    """Return (kind, rates) describing the rates device_id accepts:

      ('discrete', (44100, 48000, 96000))  — exactly these rates
      ('range', (lo, hi))                  — any integer rate in [lo, hi]
      (None, None)                         — detection failed

    (None, None) means unknown, never "accepts anything".

    Only successful probes are cached: a failure is often just a transient device
    busy, since the previous pipeline tears down on a background thread.
    """
    if device_id in _hw_rate_cache:
        return _hw_rate_cache[device_id]
    kind, rates = None, None
    try:
        proc = subprocess.Popen(
            host_cmd('aplay', '-D', device_id, '--dump-hw-params', '/dev/zero'),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            out, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        kind, rates = _parse_rate_field(out or '')
    except FileNotFoundError:
        print('[alsa] aplay not found — native-rate detection disabled')
    except Exception as e:
        print(f'[alsa] probe_alsa_hw_rate({device_id!r}) failed: {e}')
    if kind is not None:
        _hw_rate_cache[device_id] = (kind, rates)
    return kind, rates


def invalidate_alsa_rate_cache(device_id: Optional[str] = None):
    """Drop cached rate info for one device, or all devices when None."""
    if device_id is None:
        _hw_rate_cache.clear()
    else:
        _hw_rate_cache.pop(device_id, None)


# ══════════════════════════════════════════════════════════════════════════════
#  Device reservation (org.freedesktop.ReserveDevice1)
# ══════════════════════════════════════════════════════════════════════════════
# WirePlumber owns the session bus name org.freedesktop.ReserveDevice1.Audio<N>
# for each ALSA card, and that name is the handover protocol: take it with
# REPLACE_EXISTING and WirePlumber closes its PCM; release it and WirePlumber
# takes the name back and re-opens the card. Opening hw:/plughw: while
# WirePlumber still holds the PCM leaves the card half-owned — its own open
# fails with EBUSY, the node goes away, and only a replug brings it back.
#
# Only name ownership is implemented, not the full ReserveDevice1 object:
# exporting that needs a GLib main loop to dispatch incoming calls, which
# VoidPulse does not run (the GStreamer bus is polled from a Qt timer). Name
# ownership is what WirePlumber reacts to anyway. Calls use Gio call_sync for
# the same reason and complete in well under a millisecond.

_DEV_ID_RE = _re.compile(r'^(?:plug)?hw:([^,]+?)(?:,(\d+))?$')

_conn = None          # Gio.DBusConnection, held while we own a name
_owned_name = None    # currently held ReserveDevice1 name, or None

# RequestName flags (org.freedesktop.DBus)
_ALLOW_REPLACEMENT = 0x1   # another app may take the card the same way
_REPLACE_EXISTING = 0x2    # take the name from WirePlumber
_DO_NOT_QUEUE = 0x4        # fail fast instead of queueing
_REQUEST_NAME_FLAGS = _ALLOW_REPLACEMENT | _REPLACE_EXISTING | _DO_NOT_QUEUE
_PRIMARY_OWNER = 1         # RequestName reply: the name is ours

# Both handover directions are asynchronous: acquire() polls the kernel's PCM
# state, release() polls name ownership. These values only bound the wait.
HANDOVER_TIMEOUT_S = 3.0
HANDOVER_POLL_S = 0.02


def pcm_ids(device_id: str):
    """Map an ALSA device id to (card_index, device_index), or (None, None).

    'plughw:SIMGOT,0' and 'hw:1,0' both give (1, 0); a named card resolves through
    /proc/asound/<id>, a symlink to card<N>. 'pipewire', 'pulse' and anything
    unparseable give (None, None).
    """
    if not device_id:
        return None, None
    m = _DEV_ID_RE.match(device_id.strip())
    if not m:
        return None, None
    card_id = m.group(1).strip()
    dev = int(m.group(2)) if m.group(2) is not None else 0
    if card_id.isdigit():
        return int(card_id), dev
    try:
        target = os.path.realpath(f'/proc/asound/{card_id}')
        m2 = _re.search(r'card(\d+)$', target)
        return (int(m2.group(1)), dev) if m2 else (None, None)
    except Exception:
        return None, None


def _pcm_in_use(card: int, dev: int):
    """Is any process holding this playback PCM open?

    The kernel writes 'closed' in .../sub*/status for a free substream. None means
    the files could not be read, which is not the same as free.
    """
    paths = _glob.glob(f'/proc/asound/card{card}/pcm{dev}p/sub*/status')
    if not paths:
        return None
    busy = False
    for path in paths:
        try:
            with open(path) as fh:
                if 'closed' not in fh.read():
                    busy = True
        except Exception:
            return None
    return busy


def _wait_pcm_free(card: int, dev: int) -> bool:
    """Block until the card's playback PCM is closed, or the timeout expires.

    This is the handover's completion signal: WirePlumber drops the device some
    time after losing the name. True when the PCM is known free, False on timeout;
    an unreadable /proc counts as proceed.
    """
    deadline = _time.monotonic() + HANDOVER_TIMEOUT_S
    while True:
        busy = _pcm_in_use(card, dev)
        if busy is None or not busy:
            return True
        if _time.monotonic() >= deadline:
            print(f'[alsa] card{card} pcm{dev}p still busy after '
                  f'{HANDOVER_TIMEOUT_S:g}s — opening anyway')
            return False
        _time.sleep(HANDOVER_POLL_S)


def _session_bus():
    global _conn
    if _conn is None:
        _conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    return _conn


def _request_name(conn, name: str) -> bool:
    reply = conn.call_sync(
        'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
        'RequestName', GLib.Variant('(su)', (name, _REQUEST_NAME_FLAGS)),
        GLib.VariantType('(u)'), Gio.DBusCallFlags.NONE, 3000, None)
    return reply.unpack()[0] == _PRIMARY_OWNER


def acquire(device_id: str) -> bool:
    """Reserve the ALSA card behind device_id so WirePlumber releases its PCM.

    Idempotent — re-acquiring the card we already hold returns immediately.
    Switching cards releases the previous reservation first.

    True when the card is ours, and also when there is no session bus at all: on a
    bare ALSA system there is nobody to hand the card over, so opening it directly
    must not be blocked.

    A real acquisition blocks until the kernel reports the PCM closed, so callers
    can open the device as soon as this returns.
    """
    global _owned_name
    card, dev = pcm_ids(device_id)
    if card is None:
        return False
    name = f'org.freedesktop.ReserveDevice1.Audio{card}'
    if _owned_name == name:
        return True
    release()
    try:
        conn = _session_bus()
    except Exception as e:
        print(f'[alsa] no session bus ({e}) — opening {device_id!r} unreserved')
        return True
    try:
        if _request_name(conn, name):
            _owned_name = name
            t0 = _time.monotonic()
            _wait_pcm_free(card, dev)
            print(f'[alsa] reserved {name} for {device_id!r} — card free '
                  f'after {(_time.monotonic() - t0) * 1000:.0f} ms')
            return True
        print(f'[alsa] {name} refused — another app holds card {card}')
        return False
    except Exception as e:
        print(f'[alsa] RequestName({name}) failed: {e}')
        return False


def _name_has_owner(conn, name: str) -> bool:
    """Has anyone — WirePlumber, once we are gone — claimed the name?"""
    try:
        reply = conn.call_sync(
            'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'NameHasOwner', GLib.Variant('(s)', (name,)),
            GLib.VariantType('(b)'), Gio.DBusCallFlags.NONE, 3000, None)
        return bool(reply.unpack()[0])
    except Exception:
        return False


def release(wait: bool = False) -> None:
    """Give the card back so WirePlumber re-acquires the name and re-opens it.

    Safe to call when nothing is held, and never raises: it runs on the
    switch-to-PipeWire and quit paths.

    wait=True blocks until the name has an owner again, i.e. WirePlumber has
    re-created its node. Callers about to connect to PipeWire need that, or the
    stream lands on whatever sink is default meanwhile.
    """
    global _owned_name
    if not _owned_name:
        return
    name, _owned_name = _owned_name, None
    try:
        conn = _session_bus()
        conn.call_sync(
            'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'ReleaseName', GLib.Variant('(s)', (name,)),
            GLib.VariantType('(u)'), Gio.DBusCallFlags.NONE, 3000, None)
    except Exception as e:
        print(f'[alsa] ReleaseName({name}) failed: {e}')
        return
    if not wait:
        print(f'[alsa] released {name}')
        return
    t0 = _time.monotonic()
    deadline = t0 + HANDOVER_TIMEOUT_S
    while not _name_has_owner(_conn, name):
        if _time.monotonic() >= deadline:
            print(f'[alsa] released {name} — nobody reclaimed it within '
                  f'{HANDOVER_TIMEOUT_S:g}s')
            return
        _time.sleep(HANDOVER_POLL_S)
    print(f'[alsa] released {name} — reclaimed after '
          f'{(_time.monotonic() - t0) * 1000:.0f} ms')
