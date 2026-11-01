#!/usr/bin/env python3
"""
VoidPulse — entry point: _SpinningOverlay splash/runtime overlay and main().
"""
from constants import *
from constants import SS, _apply_app_palette, _capture_system_palette
import shutil
import gc as _gc
import importlib.util as _ilu
import traceback
from widgets_base import _SpinningOverlay
from main_window import MainWindow
from cover_art import _purge_orphan_disk_covers
import remote_io


def _load_auto_update():
    """Import auto-update.py, whose hyphen makes it unreachable by `import`.

    Returns None if the module is missing or fails to load: the updater is
    optional and must never keep the player from starting.
    """
    path = Path(__file__).resolve().parent / 'auto-update.py'
    try:
        spec = _ilu.spec_from_file_location('auto_update', path)
        mod = _ilu.module_from_spec(spec)
        sys.modules['auto_update'] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:
        print('[AutoUpdate] module not loaded:', exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════
def _install_excepthook() -> None:
    """Log uncaught exceptions instead of letting Qt abort silently.

    PyQt6 calls abort() on an exception that escapes a slot, which kills
    the player with no message at all. Replacing sys.excepthook lets the
    error reach a log file and one dialog while the app keeps running.
    Repeated identical failures are only logged once per session so a
    broken timer cannot spawn a dialog storm.
    """
    log_path = CONFIG_PATH.parent / 'voidpulse.log'
    seen = set()

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = ''.join(traceback.format_exception(exc_type, exc, tb))
        print(text, file=sys.stderr)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, 'a', encoding='utf-8') as fh:
                fh.write(text)
                fh.write('\n')
        except Exception:
            pass
        sig = (exc_type, str(exc))
        if sig in seen:
            return
        seen.add(sig)
        try:
            # Non-modal on purpose: QMessageBox.critical() spins a nested
            # event loop, and doing that from inside the exception handler can
            # deadlock or re-enter the slot that just failed.
            box = QMessageBox(QMessageBox.Icon.Critical,
                'VoidPulse — unexpected error',
                f'{exc_type.__name__}: {exc}\n\n'
                'The error was written to voidpulse.log. The player will keep '
                'running, but something may not work until it is restarted.',
                QMessageBox.StandardButton.Ok)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            box.setWindowModality(Qt.WindowModality.NonModal)
            box.show()
            # Qt owns the widget; hold a reference so it is not collected.
            _hook._boxes = getattr(_hook, '_boxes', [])[-2:] + [box]
        except Exception:
            pass # no GUI yet, or it is already being torn down

    sys.excepthook = _hook


def main():
    os.environ.setdefault('QT_QPA_PLATFORM', 'wayland;xcb')
    os.environ.setdefault('QT_WAYLAND_DISABLE_WINDOWDECORATION', '1')
    # Without a platform theme plugin QApplication never loads the desktop's Qt
    # theme, and the system-theme mode would capture Qt's generic default instead.
    # Both options are desktop-agnostic; anything the session already set wins.
    if not os.environ.get('QT_QPA_PLATFORMTHEME'):
        if shutil.which('qt6ct'):
            os.environ['QT_QPA_PLATFORMTHEME'] = 'qt6ct'
        else:
            os.environ['QT_QPA_PLATFORMTHEME'] = 'xdgdesktopportal'

    # GC is off during the 60 fps render loop, so raise the gen-0 threshold for
    # the periods where it runs again.
    _gc.set_threshold(5000, 10, 5)

    # Clears cover files left by older versions; never blocks startup
    threading.Thread(target=_purge_orphan_disk_covers, daemon=True).start()
    # queue2 removes its own download buffers on shutdown, so anything still on
    # disk is the residue of a crash or a kill.
    threading.Thread(target=remote_io.sweep_buffers, daemon=True).start()

    app = QApplication(sys.argv)
    app.setApplicationName('VoidPulse')
    _capture_system_palette()   # the real theme palette, before it is overridden
    _install_excepthook()
    app.setStyleSheet(SS)
    _apply_app_palette(app)

    # Shown before MainWindow, whose config load blocks
    splash = _SpinningOverlay.as_splash()
    screen_geo = QApplication.primaryScreen().geometry()
    splash.move(
        screen_geo.center().x() - splash.width() // 2,
        screen_geo.center().y() - splash.height() // 2,
    )
    splash.show()
    app.processEvents()

    # MainWindow takes the splash so _load_config can connect the playlist
    # loader's all_done before starting it, never missing the signal.
    open_with_path = sys.argv[1] if len(sys.argv) > 1 else None

    win = MainWindow(splash=splash, open_with=open_with_path)

    win.showMaximized()

    # Polls GitHub on a timer a few seconds after the window is up, so a slow
    # or missing network never delays the first frame.
    _au = _load_auto_update()
    if _au is not None:
        _au.check_on_startup(win)

    sys.exit(app.exec())

if __name__ == '__main__':
    main()
