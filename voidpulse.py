#!/usr/bin/env python3
"""
VoidPulse — entry point: _SpinningOverlay splash/runtime overlay and main().
"""
from constants import *
from constants import SS, _apply_app_palette, _capture_system_palette
import shutil
import gc as _gc
from widgets_base import _SpinningOverlay
from main_window import MainWindow
from cover_art import _purge_orphan_disk_covers


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════
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

    app = QApplication(sys.argv)
    app.setApplicationName('VoidPulse')
    _capture_system_palette()   # the real theme palette, before it is overridden
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
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
