#!/usr/bin/env python3
"""
VoidPulse — entry point: _SpinningOverlay splash/runtime overlay and main().
"""
from constants import *
from constants import SS, _apply_app_palette
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

    # GC is disabled during the 60fps render loop (see _start_render_timer).
    # Raise gen-0 threshold as a safety net for when the render timer is stopped
    # (e.g. during paused state where gc.enable() is called).
    _gc.set_threshold(5000, 10, 5)

    # One-time background sweep: delete cover disk files whose size is no longer
    # canonical (pre-snapping orphans).  Daemon thread — never blocks startup.
    threading.Thread(target=_purge_orphan_disk_covers, daemon=True).start()

    app = QApplication(sys.argv)
    app.setApplicationName('VoidPulse')
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
