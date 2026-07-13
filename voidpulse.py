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
    # Without QT_QPA_PLATFORMTHEME, a bare PyQt6 QApplication does NOT pick up
    # the desktop's live Qt theme — it falls back to Qt's built-in default
    # palette, regardless of what the DE's theming tool has configured. This
    # matters for apply_system_qt_theme(): if the platform theme plugin never
    # loads, the "system" palette we capture is just Qt's generic default.
    #
    # No DE-specific special-casing here (no "if KDE" / "if GNOME"). Two
    # DE-agnostic mechanisms cover every Qt-based or portal-capable desktop:
    #   1. qt6ct — standalone Qt config tool, works under ANY DE (reads its
    #      own theme file independent of which DE is running).
    #   2. xdgdesktopportal — talks to the desktop-neutral
    #      org.freedesktop.portal.Settings interface, implemented by
    #      xdg-desktop-portal-{kde,gnome,gtk,...}. Works on whatever DE is
    #      running as long as a matching portal backend is installed,
    #      without VoidPulse needing to know or guess which DE that is.
    # Respect anything already set by the session/user; only autodetect if
    # QT_QPA_PLATFORMTHEME is unset.
    if not os.environ.get('QT_QPA_PLATFORMTHEME'):
        if shutil.which('qt6ct'):
            os.environ['QT_QPA_PLATFORMTHEME'] = 'qt6ct'
        else:
            os.environ['QT_QPA_PLATFORMTHEME'] = 'xdgdesktopportal'

    # GC is disabled during the 60fps render loop (see _start_render_timer).
    # Raise gen-0 threshold as a safety net for when the render timer is stopped
    # (e.g. during paused state where gc.enable() is called).
    _gc.set_threshold(5000, 10, 5)

    # One-time background sweep: delete cover disk files whose size is no longer
    # canonical (pre-snapping orphans).  Daemon thread — never blocks startup.
    threading.Thread(target=_purge_orphan_disk_covers, daemon=True).start()

    app = QApplication(sys.argv)
    app.setApplicationName('VoidPulse')
    _capture_system_palette()   # snapshot real OS/Qt-theme palette before we override it below
    app.setStyleSheet(SS)
    _apply_app_palette(app)

    # Show splash immediately — before MainWindow (which blocks on config load).
    # 360×200 comfortably fits the "VoidPulse" title + spinner.
    splash = _SpinningOverlay.as_splash()
    screen_geo = QApplication.primaryScreen().geometry()
    splash.move(
        screen_geo.center().x() - splash.width() // 2,
        screen_geo.center().y() - splash.height() // 2,
    )
    splash.show()
    app.processEvents()

    # Pass splash into MainWindow so _load_config can wire all_done BEFORE
    # loader.start() — guaranteeing the signal is never missed on fast loads.
    # Support "Open With" / file manager drag: voidpulse.py <file>
    open_with_path = sys.argv[1] if len(sys.argv) > 1 else None

    win = MainWindow(splash=splash, open_with=open_with_path)

    win.showMaximized()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
