"""
VoidPulse — playlist sidebar: Sidebar (the playlist list with add/rename/remove
and drag-reorder) and _PlaylistRowWidget (one row inside it).
"""
from constants import *
from constants import _apply_scroller_properties, _r


class _PlaylistRowWidget(QWidget):
    """A sidebar playlist row: [label] [X btn] — delete button on the far right."""
    delete_clicked = pyqtSignal()
    select_clicked = pyqtSignal()
    long_pressed   = pyqtSignal(QPoint)   # emitted with global pos after hold

    _LONG_PRESS_MS = 550
    _DRIFT_PX      = 10

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(28)
        self.setMaximumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 4, 8, 4)
        lay.setSpacing(4)

        self._lbl = QLabel(label)
        self._lbl.setStyleSheet(f'color:{FG}; font-size:13px; background:transparent;')

        self._del_btn = QPushButton('✕')
        self._del_btn.setMinimumSize(24, 24)
        self._del_btn.setMaximumSize(28, 28)
        self._del_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._del_btn.setStyleSheet(
            f'QPushButton {{ background:transparent; border:none; color:{ACC};'
            f' font-size:12px; font-weight:bold; border-radius:{_r(13)}px; padding:0; }}'
            f'QPushButton:hover {{ background:{BG4}; color:{ACCH}; }}'
            f'QPushButton:pressed {{ background:{BG3}; }}')
        self._del_btn.setToolTip('Remove playlist')
        self._del_btn.clicked.connect(self.delete_clicked)

        lay.addWidget(self._lbl, 1)
        lay.addWidget(self._del_btn)

        self._lp_timer = QTimer(self)
        self._lp_timer.setSingleShot(True)
        self._lp_timer.setInterval(self._LONG_PRESS_MS)
        self._lp_timer.timeout.connect(self._on_long_press_fire)
        self._lp_start  = QPoint()
        self._lp_gpos   = QPoint()
        self._lp_active = False

    def _on_long_press_fire(self):
        self._lp_active = True
        self.long_pressed.emit(self._lp_gpos)

    def set_selected(self, on: bool):
        c = ACC if on else FG
        self._selected = on
        self._lbl.setStyleSheet(f'color:{c}; font-size:13px; font-weight:{"bold" if on else "normal"}; background:transparent;')

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # Long-press only on the label, not the delete button
            if self.childAt(e.position().toPoint()) is not self._del_btn:
                self._lp_start  = e.position().toPoint()
                self._lp_gpos   = self.mapToGlobal(e.position().toPoint())
                self._lp_active = False
                self._lp_timer.start()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._lp_timer.isActive():
            d = e.position().toPoint() - self._lp_start
            if abs(d.x()) + abs(d.y()) > self._DRIFT_PX:
                self._lp_timer.stop()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._lp_timer.stop()
            if not self._lp_active:
                # A short tap on the label selects the playlist
                if self.childAt(e.position().toPoint()) is not self._del_btn:
                    self.select_clicked.emit()
            self._lp_active = False
        super().mouseReleaseEvent(e)

    def update_accent(self):
        self._del_btn.setStyleSheet(
            f'QPushButton {{ background:transparent; border:none; color:{ACC};'
            f' font-size:12px; font-weight:bold; border-radius:{_r(11)}px; padding:0; }}'
            f'QPushButton:hover {{ background:{BG4}; color:{ACCH}; }}'
            f'QPushButton:pressed {{ background:{BG3}; }}')
        if getattr(self, '_selected', False):
            self._lbl.setStyleSheet(
                f'color:{ACC}; font-size:13px; font-weight:bold; background:transparent;')

    def refresh_theme(self):
        """Re-apply FG/BG colours after a dark/light theme switch."""
        self.update_accent()
        # An unselected label uses FG, which differs per theme
        if not getattr(self, '_selected', False):
            self._lbl.setStyleSheet(
                f'color:{FG}; font-size:13px; font-weight:normal; background:transparent;')

class Sidebar(QWidget):
    add_folder_req    = pyqtSignal()
    add_m3u_req       = pyqtSignal()
    new_playlist_req  = pyqtSignal()
    refresh_req       = pyqtSignal()
    remove_req        = pyqtSignal(int)
    rename_req        = pyqtSignal(int, str)   # (index, new_label)
    move_up_req       = pyqtSignal(int)        # index to move up
    move_down_req     = pyqtSignal(int)        # index to move down
    source_selected   = pyqtSignal(int)
    search_changed    = pyqtSignal(str)
    export_m3u_req    = pyqtSignal()
    network_share_req = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('sidebar')
        # A plain QWidget subclass does not paint a stylesheet background unless
        # this attribute is set, so without it any area no child covers — the space
        # below a short playlist list — shows whatever sits behind the sidebar.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(140)
        self.setMaximumWidth(400)
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        logo = QLabel('VoidPulse')
        self._logo_lbl = logo
        logo.setObjectName('logo_lbl')
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f'color:{ACC}; font-size:15px; font-weight:900;'
                           f' letter-spacing:5px; padding:16px 0 1px 0; background:{BG};')
        root.addWidget(logo)

        # The logo gives up its bottom padding to this line, so the pair keeps
        # the vertical space the logo used to occupy on its own.
        ver = QLabel(APP_VERSION)
        self._ver_lbl = ver
        ver.setObjectName('ver_lbl')
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(f'color:{FG2}; font-size:9px; letter-spacing:1px;'
                          f' padding:0 0 9px 0; background:{BG};')
        root.addWidget(ver)

        sf = QWidget(); sf.setStyleSheet(f'background:{BG};')
        self._sf = sf
        sfl = QHBoxLayout(sf); sfl.setContentsMargins(10,3,10,6)
        self._search = QLineEdit()
        self._search.setPlaceholderText('Search…'); self._search.setClearButtonEnabled(True)
        self._search.setMaximumHeight(40)
        self._search.setStyleSheet(
            f'QLineEdit {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            # Radius off max-height (40px) for a full pill at RAD_PCT=100.
            f' border-radius:{_r(20)}px; padding:3px 10px; font-size:12px; }}'
            f'QLineEdit:focus {{ border-color:{ACC}; }}')
        self._search.textChanged.connect(self.search_changed)
        sfl.addWidget(self._search); root.addWidget(sf)

        div = QFrame(); div.setFixedHeight(1); div.setStyleSheet(f'background:{BORD};')
        self._sidebar_div = div
        root.addWidget(div)

        lbl1 = QLabel('LIBRARY'); lbl1.setObjectName('sect_lbl'); root.addWidget(lbl1)

        self._lib_btn = QPushButton('  All Tracks')
        self._lib_btn.setStyleSheet(
            f'QPushButton {{ background:{BG3}; color:{ACC}; border:none;'
            f' border-left:3px solid {ACC}; border-radius:{_r(6)}px; text-align:left;'
            f' padding:6px 16px; font-weight:bold; font-size:12px; }}'
            f'QPushButton:hover {{ background:{BG4}; }}')
        self._lib_btn.setMaximumHeight(56)
        self._lib_btn.clicked.connect(lambda: self.source_selected.emit(-1))
        root.addWidget(self._lib_btn)

        lbl2 = QLabel("PLAYLISTS"); lbl2.setObjectName('sect_lbl'); root.addWidget(lbl2)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet('background:transparent; border:none;')
        QScroller.grabGesture(scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        _apply_scroller_properties(scroll.viewport())
        self._pl_container = QWidget(); self._pl_container.setStyleSheet('background:transparent;')
        self._pl_layout = QVBoxLayout(self._pl_container)
        self._pl_layout.setContentsMargins(0,0,0,0); self._pl_layout.setSpacing(0)
        self._pl_layout.addStretch()
        scroll.setWidget(self._pl_container)
        root.addWidget(scroll, 1)

        self._pl_rows: list = []   # list of _PlaylistRowWidget
        self._selected_pl_idx = -1

        bdiv = QFrame(); bdiv.setFixedHeight(1); bdiv.setStyleSheet(f'background:{BORD};')
        self._sidebar_bdiv = bdiv
        root.addWidget(bdiv)

        bf = QWidget(); bf.setStyleSheet(f'background:{BG};')
        self._bf = bf
        bfl = QVBoxLayout(bf); bfl.setContentsMargins(10,6,10,8); bfl.setSpacing(3)
        self._bf_layout = bfl
        # Plain '+', not the fullwidth U+FF0B: too many fonts lack it and render
        # a placeholder box instead.
        add_f    = QPushButton('+  Add Folder')
        add_m    = QPushButton('+  Import M3U / M3U8')
        add_net  = QPushButton('⇄  Network Share…')
        add_net.setToolTip('Connect a Samba/SMB, FTP, FTPS or SFTP share and add it '
                           'to the library')
        new_pl   = QPushButton('+ Create New Playlist')
        new_pl.setToolTip('Create an empty playlist and save as M3U8')
        refresh  = QPushButton('↺  Refresh Library')
        refresh.setToolTip('Rescan all saved folders')
        export_m = QPushButton('↑  Export as M3U8')
        export_m.setToolTip('Export current playlist to an M3U8 file')
        add_f.clicked.connect(self.add_folder_req); add_m.clicked.connect(self.add_m3u_req)
        add_net.clicked.connect(self.network_share_req)
        new_pl.clicked.connect(self.new_playlist_req)
        refresh.clicked.connect(self.refresh_req)
        export_m.clicked.connect(self.export_m3u_req)
        self._action_btns = [add_f, add_m, add_net, new_pl, refresh, export_m]
        # Fixed rather than Preferred: _apply_action_btn_height() drives the height
        # from bf's resizeEvent, so the buttons thin out instead of clipping.
        for b in self._action_btns:
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            bfl.addWidget(b)
        self._action_btn_h = None
        self._apply_action_btn_height(36)
        bf.resizeEvent = self._on_action_btns_resize
        root.addWidget(bf)

    def _action_btn_ss(self, height: int) -> str:
        # Capped at half the real height: above that Qt drops the rounding
        # entirely instead of clamping to a pill (as with #eq_type_combo).
        r = min(_r(18), height // 2)
        return (
            f'QPushButton {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            # The heights are restated because the global QPushButton rule's
            # min-height:36px beats setMinimumHeight() from Python, and the
            # buttons would never shrink below it.
            f' border-radius:{r}px; padding:2px 8px; font-size:11px;'
            f' min-height:{height}px; max-height:{height}px; }}'
            f'QPushButton:hover {{ border-color:{ACC}; }}'
            f'QPushButton:pressed {{ background:{BG4}; }}')

    def _apply_action_btn_height(self, height: int):
        height = max(18, min(36, height))
        if self._action_btn_h == height:
            return
        self._action_btn_h = height
        ss = self._action_btn_ss(height)
        for b in self._action_btns:
            b.setMinimumHeight(height)
            b.setMaximumHeight(height)
            b.setStyleSheet(ss)

    def _on_action_btns_resize(self, e):
        """bf's resizeEvent — bf.height() reflects whatever the sidebar's
        outer QVBoxLayout actually allocated it, so when the window is too
        short for all 5 buttons at 36px this is the real, smaller number to
        divide up, not their sizeHint. Cover art and title/artist in
        ControlBar shrink the same reactive way — see ControlBar.resizeEvent."""
        n = len(self._action_btns)
        if n == 0:
            return
        m = self._bf_layout.contentsMargins()
        avail = self._bf.height() - m.top() - m.bottom() - self._bf_layout.spacing() * (n - 1)
        self._apply_action_btn_height(avail // n)

    def add_playlist(self, label: str):
        row = _PlaylistRowWidget(label)
        idx = len(self._pl_rows)
        self._pl_rows.append(row)
        self._pl_layout.insertWidget(self._pl_layout.count() - 1, row)
        row.select_clicked.connect(lambda i=idx: self._on_select(i))
        row.delete_clicked.connect(lambda i=idx: self._on_delete_clicked(i))
        row.long_pressed.connect(lambda gpos, i=idx: self._show_pl_context_menu(i, gpos))

    def _show_pl_context_menu(self, idx: int, gpos: QPoint):
        if not (0 <= idx < len(self._pl_rows)):
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            f'QMenu {{ background:{BG3}; color:{FG}; border:2px solid {ACC};'
            f' border-radius:{_r(12)}px; padding:4px 0; font-size:12px; }}'
            f'QMenu::item {{ padding:6px 20px; }}'
            f'QMenu::item:selected {{ background:{SEL}; color:{ACC}; }}'
            f'QMenu::separator {{ height:1px; background:{B2}; margin:3px 8px; }}')
        act_rename = menu.addAction('✎  Rename')
        menu.addSeparator()
        act_up   = menu.addAction('▲  Move Up')
        act_down = menu.addAction('▼  Move Down')
        act_up.setEnabled(idx > 0)
        act_down.setEnabled(idx < len(self._pl_rows) - 1)
        chosen = menu.exec(gpos)
        if chosen is act_rename:
            self._prompt_rename(idx)
        elif chosen is act_up:
            self.move_up_req.emit(idx)
        elif chosen is act_down:
            self.move_down_req.emit(idx)

    def _prompt_rename(self, idx: int):
        if not (0 <= idx < len(self._pl_rows)):
            return
        current = self._pl_rows[idx]._lbl.text()
        dlg = QInputDialog(self)
        dlg.setWindowTitle('Rename Playlist')
        dlg.setLabelText('New name:')
        dlg.setTextValue(current)
        dlg.setStyleSheet(
            f'QDialog {{ background:{BG2}; }}'
            f'QLabel {{ color:{FG}; font-size:13px; }}'
            f'QLineEdit {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:{_r(6)}px; padding:4px 8px; font-size:13px; }}'
            f'QPushButton {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:{_r(5)}px; padding:4px 16px; font-size:12px; }}'
            f'QPushButton:hover {{ border-color:{ACC}; }}'
            f'QPushButton:default {{ border-color:{ACC}; color:{ACC}; }}')
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_name = dlg.textValue().strip()
            if new_name and new_name != current:
                self.rename_row(idx, new_name)
                self.rename_req.emit(idx, new_name)

    def rename_row(self, idx: int, new_label: str):
        """Update the sidebar label for playlist at idx."""
        if not (0 <= idx < len(self._pl_rows)):
            return
        row = self._pl_rows[idx]
        row._lbl.setText(new_label)
        row.set_selected(getattr(row, '_selected', False))

    def move_playlist_row(self, from_idx: int, to_idx: int):
        """Swap two adjacent playlist rows in the sidebar UI and rewire signals."""
        n = len(self._pl_rows)
        if not (0 <= from_idx < n and 0 <= to_idx < n):
            return
        lo_i = min(from_idx, to_idx)
        hi_i = max(from_idx, to_idx)
        lo_w = self._pl_rows[lo_i]
        hi_w = self._pl_rows[hi_i]
        self._pl_rows[from_idx], self._pl_rows[to_idx] = (
            self._pl_rows[to_idx], self._pl_rows[from_idx])
        # Higher index first, so removing does not shift the other one
        lo = self._pl_layout
        lo.removeWidget(hi_w)
        lo.removeWidget(lo_w)
        lo.insertWidget(lo_i, hi_w)
        lo.insertWidget(hi_i, lo_w)
        if self._selected_pl_idx == from_idx:
            self._selected_pl_idx = to_idx
        elif self._selected_pl_idx == to_idx:
            self._selected_pl_idx = from_idx
        # The captured indices in the row signals are now wrong
        self._rewire_all_rows()

    def _rewire_all_rows(self):
        """Disconnect and reconnect all row signals with correct current indices."""
        for i, r in enumerate(self._pl_rows):
            try: r.select_clicked.disconnect()
            except Exception: pass
            try: r.delete_clicked.disconnect()
            except Exception: pass
            try: r.long_pressed.disconnect()
            except Exception: pass
            r.select_clicked.connect(lambda _i=i: self._on_select(_i))
            r.delete_clicked.connect(lambda _i=i: self._on_delete_clicked(_i))
            r.long_pressed.connect(lambda gpos, _i=i: self._show_pl_context_menu(_i, gpos))

    def remove_playlist(self, idx: int):
        if not (0 <= idx < len(self._pl_rows)): return
        row = self._pl_rows.pop(idx)
        self._pl_layout.removeWidget(row); row.deleteLater()
        self._rewire_all_rows()
        if self._selected_pl_idx >= len(self._pl_rows):
            self._selected_pl_idx = -1

    def _on_select(self, idx: int):
        if self._selected_pl_idx >= 0 and self._selected_pl_idx < len(self._pl_rows):
            self._pl_rows[self._selected_pl_idx].set_selected(False)
        self._selected_pl_idx = idx
        self._pl_rows[idx].set_selected(True)
        self.source_selected.emit(idx)

    def select_source(self, idx: int):
        """Highlight sidebar row for tab index without emitting source_selected.

        idx == -1  → Library (All Tracks)
        idx >= 0   → playlist row at that index
        Used by MainWindow to sync sidebar highlight on startup restore.
        """
        if self._selected_pl_idx >= 0 and self._selected_pl_idx < len(self._pl_rows):
            self._pl_rows[self._selected_pl_idx].set_selected(False)
        if idx == -1:
            self._selected_pl_idx = -1
            self._lib_btn.setStyleSheet(
                f'QPushButton {{ background:{BG3}; color:{ACC}; border:none;'
                f' border-left:3px solid {ACC}; border-radius:{_r(6)}px; text-align:left;'
                f' padding:6px 16px; font-weight:bold; font-size:12px; }}'
                f'QPushButton:hover {{ background:{BG4}; }}')
        elif 0 <= idx < len(self._pl_rows):
            self._selected_pl_idx = idx
            self._pl_rows[idx].set_selected(True)

    def update_accent(self):
        """Re-apply accent color to all inline-styled sidebar widgets."""
        self._lib_btn.setStyleSheet(
            f'QPushButton {{ background:{BG3}; color:{ACC}; border:none;'
            f' border-left:3px solid {ACC}; border-radius:{_r(6)}px; text-align:left;'
            f' padding:6px 16px; font-weight:bold; font-size:12px; }}'
            f'QPushButton:hover {{ background:{BG4}; }}')
        self._search.setStyleSheet(
            f'QLineEdit {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            # Radius off max-height (40px) for a full pill at RAD_PCT=100.
            f' border-radius:{_r(20)}px; padding:3px 10px; font-size:12px; }}'
            f'QLineEdit:focus {{ border-color:{ACC}; }}')
        logo = self.findChild(QLabel, 'logo_lbl')
        if logo:
            logo.setStyleSheet(
                f'color:{ACC}; font-size:15px; font-weight:900;'
                f' letter-spacing:5px; padding:16px 0 1px 0; background:{BG};')
        for row in self._pl_rows:
            row.update_accent()

    def refresh_theme(self):
        """Re-apply all palette globals after a dark/light switch."""
        self._sf.setStyleSheet(f'background:{BG};')
        self._bf.setStyleSheet(f'background:{BG};')
        # Carries no accent colour, so it sits here rather than in update_accent.
        self._ver_lbl.setStyleSheet(f'color:{FG2}; font-size:9px; letter-spacing:1px;'
                                    f' padding:0 0 9px 0; background:{BG};')
        self._sidebar_div.setStyleSheet(f'background:{BORD};')
        self._sidebar_bdiv.setStyleSheet(f'background:{BORD};')
        # RAD_PCT may have changed, so clear the height guard to force a rebuild
        self._action_btn_h = None
        self._apply_action_btn_height(self._action_btns[0].height() or 36)
        self.update_accent()   # logo, lib_btn, search
        for row in self._pl_rows:
            row.refresh_theme()   # also updates FG for unselected labels

    def _on_delete_clicked(self, idx: int):
        if not (0 <= idx < len(self._pl_rows)): return
        name = self._pl_rows[idx]._lbl.text()
        reply = QMessageBox.question(
            self, 'Remove Playlist',
            f'Remove "{name}" from the player?\n(Files will not be deleted)',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.remove_req.emit(idx)

# ══════════════════════════════════════════════════════════════════════════════
