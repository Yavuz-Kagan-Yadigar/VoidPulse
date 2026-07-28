"""
VoidPulse — TagEditDialog and LyricsEditDialog: modal tag/lyrics editors.
"""
from constants import *
from cover_art import extract_cover_bytes
from lyrics import _extract_embedded_lyrics, _lrc_parse, _src_azlyrics, _src_chartlyrics, _src_genius_search, _src_letras, _src_lrclib_exact, _src_lrclib_search, _src_lyrics_ovh, _src_songlyrics
from constants import ACC, B2, BG2, BG3, BG4, BORD, FG, FG2, _r
import concurrent.futures as _cf
from metadata_online import embed_lyrics, fetch_cover_online, lookup_tags_online

class _CoverPreview(QWidget):
    """Full-dialog cover zoom shown when the cover thumbnail is clicked.

    Sits over the whole dialog as a dimmed backdrop with the artwork centred at
    its native aspect ratio. Any mouse press or key press dismisses it, and it
    follows the dialog if that is resized while open.
    """

    _MARGIN_PCT = 0.06   # empty border kept around the artwork

    def __init__(self, pixmap: QPixmap, parent: QWidget):
        super().__init__(parent)
        self._pm = pixmap
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())

    def eventFilter(self, obj, ev):
        if obj is self.parent() and ev.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return False

    def _dismiss(self):
        p = self.parent()
        if p is not None:
            p.removeEventFilter(self)
        self.hide()
        self.deleteLater()

    def mousePressEvent(self, e):
        self._dismiss()

    def keyPressEvent(self, e):
        self._dismiss()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        scrim = QColor(0, 0, 0, 200)
        p.fillRect(self.rect(), scrim)

        if self._pm.isNull():
            return
        m = int(min(self.width(), self.height()) * self._MARGIN_PCT)
        avail = self.rect().adjusted(m, m, -m, -m)
        shown = self._pm.scaled(avail.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        x = avail.x() + (avail.width()  - shown.width())  // 2
        y = avail.y() + (avail.height() - shown.height()) // 2

        # Same corner treatment as the thumbnail
        r = _r(10)
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, shown.width(), shown.height()), r, r)
        p.save()
        p.setClipPath(path)
        p.drawPixmap(x, y, shown)
        p.restore()
        p.setPen(QPen(QColor(ACC), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


class _ClickableCoverLabel(QLabel):
    """Cover thumbnail that emits `clicked` when pressed."""
    clicked = pyqtSignal()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class TagEditDialog(QDialog):
    """Tag editor with cover art management."""
    def __init__(self, track: 'Track', parent=None):
        super().__init__(parent)
        self.setWindowTitle('Edit Tags')
        self.setMinimumWidth(420)
        self._track    = track
        self._cover_action = 'keep'   # 'keep' | 'remove' | 'set'
        self._new_cover_bytes: Optional[bytes] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Cover row ──────────────────────────────────────────────────────
        cover_row = QHBoxLayout(); cover_row.setSpacing(12)
        self._cover_full: Optional[QPixmap] = None   # full-res source for the zoom view
        self._cover_lbl = _ClickableCoverLabel()
        self._cover_lbl.setFixedSize(96, 96)
        self._cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_lbl.setStyleSheet(
            f'background:{BG3}; border:1px solid {B2}; border-radius:{_r(8)}px;')
        self._cover_lbl.clicked.connect(self._show_cover_preview)
        raw = extract_cover_bytes(track.filepath)
        if raw:
            pm = QPixmap(); pm.loadFromData(raw)
            self._set_cover_pixmap(pm)
        else:
            self._show_no_cover('No Cover')
        cover_row.addWidget(self._cover_lbl)

        # ── 2-column × 4-row action button grid ───────────────────────────
        _tag_btn_ss = (
            f'QPushButton {{ background:{BG3}; color:{FG}; border:1px solid {B2};'
            f' border-radius:{_r(9)}px; padding:4px 6px; font-size:11px; }}'
            f'QPushButton:hover {{ border-color:{ACC}; }}'
            f'QPushButton:pressed {{ background:{BG4}; }}'
            f'QPushButton:checked {{ color:{ACC}; border-color:{ACC}; }}'
        )
        self._btn_cover_file   = QPushButton('Set Cover\nfrom File…')
        self._btn_cover_search = QPushButton('Search\nCover…')
        self._btn_cover_remove = QPushButton('Remove\nCover')
        self._btn_tag_fetch    = QPushButton('Auto-fill\nTags…')
        self._btn_lyrics_fetch = QPushButton('Fetch\nLyrics…')
        self._btn_lyrics_edit  = QPushButton('Edit\nLyrics…')

        cover_grid = QGridLayout()
        cover_grid.setSpacing(5)
        cover_grid.addWidget(self._btn_cover_file,   0, 0)
        cover_grid.addWidget(self._btn_cover_search, 0, 1)
        cover_grid.addWidget(self._btn_cover_remove, 1, 0)
        cover_grid.addWidget(self._btn_lyrics_edit,   1, 1)
        cover_grid.addWidget(self._btn_tag_fetch,    2, 0)
        cover_grid.addWidget(self._btn_lyrics_fetch, 2, 1)

        for btn in (self._btn_cover_file, self._btn_cover_search,
                    self._btn_cover_remove,
                    self._btn_tag_fetch, self._btn_lyrics_fetch,
                    self._btn_lyrics_edit):
            btn.setMinimumHeight(38)
            btn.setStyleSheet(_tag_btn_ss)

        cover_row.addLayout(cover_grid)
        layout.addLayout(cover_row)

        self._btn_cover_file.clicked.connect(self._pick_cover_file)
        self._btn_cover_search.clicked.connect(self._search_cover_online)
        self._btn_cover_remove.clicked.connect(self._remove_cover)
        self._btn_tag_fetch.clicked.connect(self._fetch_tags_online)
        self._btn_lyrics_fetch.clicked.connect(self._fetch_lyrics_online)
        self._btn_lyrics_edit.clicked.connect(self._edit_lyrics)

        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f'color:{BORD};'); layout.addWidget(div)

        # ── Text tags ──────────────────────────────────────────────────────
        for label, attr in [('Title', 'title'), ('Artist', 'artist'), ('Album', 'album')]:
            row = QHBoxLayout()
            lbl = QLabel(f'{label}:'); lbl.setFixedWidth(50)
            row.addWidget(lbl)
            edit = QLineEdit(getattr(track, attr))
            setattr(self, f'_{attr}_edit', edit)
            row.addWidget(edit)
            layout.addLayout(row)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def changeEvent(self, e):
        # On Wayland the modal overlay cannot receive input while a top-level
        # QDialog holds focus, so the dialog closes on deactivation instead. A
        # child dialog (file picker, message box) also deactivates this one, so
        # those cases are filtered out below and by _child_dialog_open.
        if e.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            if getattr(self, '_child_dialog_open', False):
                super().changeEvent(e)
                return
            active = QApplication.activeWindow()
            # Keep open if a child dialog (file picker, online search feedback, etc.)
            # stole focus — active window will be None only momentarily during
            # transitions, or will be a transient child of this dialog.
            if active is None or active is self:
                pass   # transient; don't close
            elif active.parent() is self:
                pass   # child dialog opened from here — keep open
            else:
                self.reject()
        super().changeEvent(e)

    def _set_cover_pixmap(self, pm: QPixmap):
        """Show pm as the 96px thumbnail and keep the original for the zoom view."""
        self._cover_full = pm
        self._cover_lbl.setText('')
        self._cover_lbl.setToolTip('Click to enlarge')
        self._cover_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cover_lbl.setStyleSheet(
            f'background:{BG3}; border:1px solid {B2}; border-radius:{_r(8)}px;')
        self._cover_lbl.setPixmap(
            pm.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                      Qt.TransformationMode.SmoothTransformation).copy(0, 0, 96, 96))

    def _show_no_cover(self, text: str):
        """Put the label into its empty state — nothing to enlarge."""
        self._cover_full = None
        self._cover_lbl.clear()
        self._cover_lbl.setText(text)
        self._cover_lbl.setToolTip('')
        self._cover_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        self._cover_lbl.setStyleSheet(
            f'background:{BG3}; border:1px solid {B2}; border-radius:{_r(8)}px;'
            f' color:{FG2}; font-size:11px;')

    def _show_cover_preview(self):
        """Open the full-size cover view; ignored when there is no artwork."""
        if self._cover_full is None or self._cover_full.isNull():
            return
        view = _CoverPreview(self._cover_full, self)
        view.show()
        view.raise_()
        view.setFocus()

    def _pick_cover_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select Cover Image', '',
            'Images (*.jpg *.jpeg *.png *.webp *.bmp)')
        if not path: return
        with open(path, 'rb') as f:
            data = f.read()
        pm = QPixmap()
        if pm.loadFromData(data):
            self._new_cover_bytes = data
            self._cover_action = 'set'
            self._set_cover_pixmap(pm)

    def _search_cover_online(self):
        """Fetch cover from online sources for this specific track in a background thread."""
        self._btn_cover_search.setEnabled(False)
        self._btn_cover_search.setText('Searching…')
        artist = self._artist_edit.text().strip() or self._track.artist
        title  = self._title_edit.text().strip()  or self._track.title
        album  = self._album_edit.text().strip()  or self._track.album

        # Run network fetch in a daemon thread; update UI via QTimer
        result = [None]

        def _fetch():
            result[0] = fetch_cover_online(artist, title, album)

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()

        def _poll():
            if not self.isVisible(): return   # dialog closed while thread was running
            if t.is_alive():
                QTimer.singleShot(200, _poll)
                return
            data = result[0]
            self._btn_cover_search.setEnabled(True)
            self._btn_cover_search.setText('Search Cover…')
            if data:
                pm = QPixmap()
                if pm.loadFromData(data):
                    self._new_cover_bytes = data
                    self._cover_action    = 'set'
                    self._set_cover_pixmap(pm)
                else:
                    self._show_no_cover('Load error')
            else:
                self._btn_cover_search.setText('Not found')
                QTimer.singleShot(2000,
                    lambda: self._btn_cover_search.setText('Search Cover…'))

        QTimer.singleShot(200, _poll)

    def _fetch_tags_online(self):
        """Look up missing title/artist/album for this track and fill the edit fields."""
        self._btn_tag_fetch.setEnabled(False)
        self._btn_tag_fetch.setText('Searching…')
        artist = self._artist_edit.text().strip() or self._track.artist
        title  = self._title_edit.text().strip()  or self._track.title or Path(self._track.filepath).stem

        result = [{}]
        def _fetch():
            result[0] = lookup_tags_online(artist, title)

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()

        def _poll():
            if not self.isVisible(): return   # dialog closed while thread was running
            if t.is_alive():
                QTimer.singleShot(200, _poll)
                return
            self._btn_tag_fetch.setEnabled(True)
            tags = result[0]
            if tags:
                # Fill only empty fields
                if not self._title_edit.text().strip()  and tags.get('title'):
                    self._title_edit.setText(tags['title'])
                if not self._artist_edit.text().strip() and tags.get('artist'):
                    self._artist_edit.setText(tags['artist'])
                if not self._album_edit.text().strip()  and tags.get('album'):
                    self._album_edit.setText(tags['album'])
                self._btn_tag_fetch.setText('Auto-fill Tags…')
            else:
                self._btn_tag_fetch.setText('Not found')
                QTimer.singleShot(2000,
                    lambda: self._btn_tag_fetch.setText('Auto-fill Tags…'))

        QTimer.singleShot(200, _poll)

    def _fetch_lyrics_online(self):
        """Force-fetch lyrics from all online sources, ignoring any embedded tags.

        All APIs are queried in parallel; the worker waits for every future to
        settle so a synced result that arrives late still beats an early plain
        one.  On success the best result (synced preferred) is written back into
        the audio file's tags via embed_lyrics.  The button label tracks
        progress so the user has live feedback.
        """
        self._btn_lyrics_fetch.setEnabled(False)
        self._btn_lyrics_fetch.setText('Searching…')

        track  = self._track
        artist = self._artist_edit.text().strip()  or track.artist
        title  = self._title_edit.text().strip()   or track.title
        album  = self._album_edit.text().strip()   or track.album
        dur    = getattr(track, 'duration', 0) or 0

        result = [None, None]   # [synced, plain]

        def _fetch():
            sources = [
                ('LrcLib (exact)',  lambda: _src_lrclib_exact(artist, title, album, dur)),
                ('LrcLib (search)', lambda: _src_lrclib_search(artist, title)),
                ('Lyrics.ovh',      lambda: _src_lyrics_ovh(artist, title)),
                ('Genius',          lambda: _src_genius_search(artist, title)),
                ('AZLyrics',        lambda: _src_azlyrics(artist, title)),
                ('SongLyrics',      lambda: _src_songlyrics(artist, title)),
                ('ChartLyrics',     lambda: _src_chartlyrics(artist, title)),
                ('Letras.mus.br',   lambda: _src_letras(artist, title)),
            ]
            lock        = threading.Lock()
            best_synced = [None]
            best_plain  = [None]

            def _run(fn):
                try:
                    s, p = fn()
                except Exception:
                    return
                with lock:
                    if s and best_synced[0] is None:
                        best_synced[0] = s
                    if p and best_plain[0] is None:
                        best_plain[0] = p

            # Fire all sources in parallel and wait for EVERY future to finish.
            # Unlike LyricsFetcher (which short-circuits on the first synced hit
            # for low latency), this path waits for all results so a synced lyric
            # found late always wins over a plain one found early.
            with _cf.ThreadPoolExecutor(max_workers=len(sources)) as pool:
                futs = [pool.submit(_run, fn) for _, fn in sources]
                _cf.wait(futs)

            result[0] = best_synced[0]
            result[1] = best_plain[0]

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()

        def _poll():
            if not self.isVisible(): return   # dialog closed while thread was running
            if t.is_alive():
                QTimer.singleShot(200, _poll)
                return

            synced = result[0]
            plain  = result[1]
            self._btn_lyrics_fetch.setEnabled(True)

            if synced or plain:
                # Embed result into the audio file so the player panel picks it
                # up on the next track load without another network round-trip.
                threading.Thread(
                    target=embed_lyrics,
                    args=(track.filepath, synced, plain or ''),
                    daemon=True,
                ).start()
                kind = 'synced' if synced else 'plain'
                self._btn_lyrics_fetch.setText(f'Saved ({kind})')
                QTimer.singleShot(2500,
                    lambda: self._btn_lyrics_fetch.setText('Fetch Lyrics…'))
            else:
                self._btn_lyrics_fetch.setText('Not found')
                QTimer.singleShot(2000,
                    lambda: self._btn_lyrics_fetch.setText('Fetch Lyrics…'))

        QTimer.singleShot(200, _poll)

    def _remove_cover(self):
        self._cover_action = 'remove'
        self._new_cover_bytes = None
        self._show_no_cover('Removed')

    def _edit_lyrics(self):
        """Open lyrics editor popup with current embedded lyrics."""
        synced, plain = _extract_embedded_lyrics(self._track.filepath)
        # Build editable text: prefer LRC-formatted synced, then plain
        if synced:
            current_text = '\n'.join(
                f'[{ms//60000:02d}:{(ms%60000)/1000:05.2f}]{txt}'
                for ms, txt in synced)
        elif plain:
            current_text = plain
        else:
            current_text = ''

        dlg = LyricsEditDialog(current_text, parent=self)
        self._child_dialog_open = True
        result = dlg.exec()
        self._child_dialog_open = False
        if result == QDialog.DialogCode.Accepted:
            new_text = dlg.get_lyrics()
            # Write directly to file: try to parse as LRC first
            parsed = _lrc_parse(new_text) if new_text.strip() else None
            if parsed:
                ok = embed_lyrics(self._track.filepath, parsed, '')
            else:
                ok = embed_lyrics(self._track.filepath, None, new_text)
            if ok:
                self._btn_lyrics_edit.setText('Saved!')
                QTimer.singleShot(2000,
                    lambda: self._btn_lyrics_edit.setText('Edit\nLyrics…'))
            else:
                self._btn_lyrics_edit.setText('Save failed')
                QTimer.singleShot(2000,
                    lambda: self._btn_lyrics_edit.setText('Edit\nLyrics…'))

    def get_tags(self):
        return self._title_edit.text(), self._artist_edit.text(), self._album_edit.text()

    def get_cover_result(self):
        """Returns (action, bytes|None)."""
        return self._cover_action, self._new_cover_bytes

# ══════════════════════════════════════════════════════════════════════════════
#  Lyrics editor dialog
# ══════════════════════════════════════════════════════════════════════════════
class LyricsEditDialog(QDialog):
    """Popup editor for embedded lyrics (plain or LRC-timestamped)."""

    def __init__(self, current_text: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle('Edit Lyrics')
        self.setModal(True)
        self.setMinimumSize(480, 520)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Info label
        info = QLabel(
            'Edit lyrics below. Timestamped LRC format ([mm:ss.xx]…) is preserved\n'
            'on save. Leave empty to clear embedded lyrics.')
        info.setWordWrap(True)
        info.setStyleSheet(f'color:{FG2}; font-size:11px;')
        layout.addWidget(info)

        # Text editor
        self._editor = QPlainTextEdit()
        self._editor.setPlainText(current_text)
        self._editor.setStyleSheet(
            f'QPlainTextEdit {{'
            f'  background:{BG2}; color:{FG}; border:1px solid {B2};'
            f'  border-radius:{_r(6)}px;'
            f'  font-family: monospace; font-size:12px;'
            f'  padding:6px;'
            f'}}'
            f'QPlainTextEdit:focus {{ border-color:{ACC}; }}'
        )
        layout.addWidget(self._editor, 1)

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_lyrics(self) -> str:
        return self._editor.toPlainText()


# ══════════════════════════════════════════════════════════════════════════════
#  Custom slider cell for EQ table
# ══════════════════════════════════════════════════════════════════════════════
# EQSliderCell is defined in eq.py
