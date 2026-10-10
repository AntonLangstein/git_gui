"""Dialoge: Datei-Historie mit Blame, interaktiver Rebase, Konflikte lösen."""
import html
import os
import shlex
import tempfile
import time

from PySide6.QtCore import QUrl, Qt

from PySide6.QtGui import QDesktopServices

from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea,
    QSizePolicy, QSplitter, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .theme import COLORS
from .core import (
    REBASE_ACTIONS, parse_blame, parse_conflicts, parse_file_log, rebase_todo, resolve_conflicts,
    view_option, ws_args,
)
from .diff import FANCY_LIMIT, code_html, lexer_for, patch_html


class FileHistoryDialog(QDialog):
    """Datei-Historie (auch über Umbenennungen) mit Diff und Blame je Commit."""

    def __init__(self, tab, path):
        super().__init__(tab)
        self.tab, self.path = tab, path
        self.setWindowTitle(f"Historie – {path}")
        self.resize(1200, 760)
        self.commits = QTreeWidget(rootIsDecorated=False, uniformRowHeights=True)
        self.commits.setHeaderLabels(["Beschreibung", "Autor", "Datum", "Commit"])
        for col, width in ((0, 260), (1, 110), (2, 120)):
            self.commits.setColumnWidth(col, width)
        self.commits.currentItemChanged.connect(lambda cur, _prev: self.show_commit(cur))
        self.diff = QTextBrowser(openLinks=False, font=tab.mono)
        self.blame = QTextBrowser(openLinks=False, font=tab.mono)
        self.blame.anchorClicked.connect(self.jump_to)
        self.views = QTabWidget(objectName="detail", documentMode=True)
        self.views.addTab(self.diff, "Änderungen")
        self.views.addTab(self.blame, "Blame")
        self.views.currentChanged.connect(lambda _i: self.show_commit(self.commits.currentItem()))
        split = QSplitter()
        split.addWidget(self.commits)
        split.addWidget(self.views)
        split.setSizes([560, 640])
        lay = QVBoxLayout(self)
        lay.addWidget(split)

        out = tab.git("log", "--follow", "--name-only", "--date=format:%d.%m.%Y %H:%M",
                      "--format=%x1e%H%x1f%h%x1f%s%x1f%an%x1f%ad", "--", path)
        for (full, short, subject, author, date), old_path in parse_file_log(out):
            it = QTreeWidgetItem(self.commits, [subject, author, date, short])
            it.setData(0, Qt.UserRole, (full, old_path or path))
            if old_path and old_path != path:
                it.setToolTip(0, f"Hieß damals: {old_path}")
        if self.commits.topLevelItemCount():
            self.commits.setCurrentItem(self.commits.topLevelItem(0))
        else:
            self.diff.setPlainText("Diese Datei hat noch keine Commits.")

    def show_commit(self, item):
        data = item and item.data(0, Qt.UserRole)
        if not data:
            return
        sha, path = data
        if self.views.currentIndex() == 0:
            patch = self.tab.git("show", "--format=", "-M", *ws_args(), sha, "--", path)
            self.diff.setHtml(patch_html(patch, split=view_option("split_diff")))
        else:
            self.blame.setHtml(self.blame_html(sha, path))

    def blame_html(self, sha, path):
        """Wer hat welche Zeile zuletzt geändert – gruppiert nach Commit, abwechselnd hinterlegt."""
        rows = parse_blame(self.tab.git("blame", "--line-porcelain", sha, "--", path))
        if not rows:
            return f"<p style='color:{COLORS['dim']}'>Kein Blame möglich (z.B. Binärdatei).</p>"
        lexer = lexer_for(path) if len(rows) < FANCY_LIMIT else None
        e, out, band, last = html.escape, [], 0, None
        for n, (row_sha, author, when, code) in enumerate(rows, 1):
            first = row_sha != last
            if first:
                band, last = band ^ 1, row_sha
            meta = (f"<a href='blame:{row_sha}' style='color:{COLORS['accent']}; text-decoration:none'>{row_sha[:7]}</a>"
                    f"&nbsp; {e(author[:18])}&nbsp; <span style='color:{COLORS['dim']}'>"
                    f"{time.strftime('%d.%m.%Y', time.localtime(when))}</span>") if first else ""
            out.append(f"<tr{' bgcolor=' + COLORS['alt'] if band else ''}><td style='white-space:pre'>{meta}</td>"
                       f"<td width='44' align='right' style='color:{COLORS['lineno']}'>{n}&nbsp;</td>"
                       f"<td width='100%' style='white-space:pre'>{code_html(code, lexer)}</td></tr>")
        return f"<table width='100%' cellspacing='0' cellpadding='1'>{''.join(out)}</table>"

    def jump_to(self, url):
        """Klick auf einen Commit im Blame: diesen Commit in der Liste auswählen."""
        sha = url.path()
        for i in range(self.commits.topLevelItemCount()):
            it = self.commits.topLevelItem(i)
            if it.data(0, Qt.UserRole)[0] == sha:
                self.commits.setCurrentItem(it)
                return


class RebaseDialog(QDialog):
    """Interaktiver Rebase wie in Fork: Commits ab einem Punkt umsortieren, umbenennen, zusammenfassen, entfernen."""

    def __init__(self, tab, start):
        super().__init__(tab)
        self.tab = tab
        self.setWindowTitle("Interaktiver Rebase")
        self.resize(900, 520)
        parent = tab.git("rev-parse", "-q", "--verify", f"{start}^").strip()
        self.base = parent or "--root"  # der Start-Commit selbst ist bearbeitbar
        out = tab.git("log", "--reverse", "--format=%H%x1f%h%x1f%s", f"{parent}..HEAD" if parent else "HEAD")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Commits auf „{tab.branch}“, ältester oben. Reihenfolge mit den Pfeilen ändern; "
                             "eine neue Nachricht direkt in der Spalte „Nachricht“ eintippen.", wordWrap=True))
        self.list = QTreeWidget(rootIsDecorated=False)
        self.list.setHeaderLabels(["Aktion", "Commit", "Nachricht"])
        self.list.setColumnWidth(0, 300)
        self.list.setColumnWidth(1, 80)
        self.list.itemChanged.connect(self.on_edit)
        for sha, short, subject in (line.split("\x1f") for line in out.splitlines()):
            it = QTreeWidgetItem(self.list, ["", short, subject])
            it.setData(0, Qt.UserRole, (sha, subject))
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            self.add_combo(it)
        self.list.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for text, step in (("▲ Nach oben", -1), ("▼ Nach unten", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c, step=step: self.move(step))
            row.addWidget(b)
        row.addStretch()
        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        start_btn = QPushButton("Rebase starten", objectName="commitBtn")
        start_btn.clicked.connect(self.start)
        row.addWidget(cancel)
        row.addWidget(start_btn)
        lay.addLayout(row)

    def add_combo(self, item, action="pick"):
        combo = QComboBox()
        for key, label in REBASE_ACTIONS:
            combo.addItem(f"{key} – {label}", key)
        combo.setCurrentIndex([k for k, _ in REBASE_ACTIONS].index(action))
        self.list.setItemWidget(item, 0, combo)

    def action(self, item):
        return self.list.itemWidget(item, 0).currentData()

    def on_edit(self, item, column):
        """Nachricht geändert -> Aktion automatisch auf „reword“."""
        if column == 2 and item.text(2) != item.data(0, Qt.UserRole)[1] and self.action(item) == "pick":
            combo = self.list.itemWidget(item, 0)
            combo.setCurrentIndex(combo.findData("reword"))

    def move(self, step):
        item = self.list.currentItem()
        if not item:
            return
        i, action = self.list.indexOfTopLevelItem(item), self.action(item)
        j = i + step
        if 0 <= j < self.list.topLevelItemCount():
            self.list.takeTopLevelItem(i)  # dabei geht das Auswahlfeld verloren -> neu anlegen
            self.list.insertTopLevelItem(j, item)
            self.add_combo(item, action)
            self.list.setCurrentItem(item)

    def rows(self):
        items = [self.list.topLevelItem(i) for i in range(self.list.topLevelItemCount())]
        return [(self.action(it), it.data(0, Qt.UserRole)[0], it.text(2)) for it in items]

    def start(self):
        rows = self.rows()
        kept = [r for r in rows if r[0] != "drop"]
        if kept and kept[0][0] in ("squash", "fixup"):
            return QMessageBox.information(self, "Rebase", "Der erste Commit kann nicht mit einem vorherigen "
                                                           "zusammengefasst werden.")
        if any(a == "reword" and not m.strip() for a, _, m in rows):
            return QMessageBox.information(self, "Rebase", "Eine Commit-Nachricht darf nicht leer sein.")
        with tempfile.NamedTemporaryFile("w", suffix=".todo", delete=False) as f:
            f.write(rebase_todo(rows))
        try:
            # Git ruft den „Editor“ mit dem Pfad seiner Todo-Datei auf – wir kopieren unsere darüber
            self.tab.git("rebase", "-i", "--autostash", self.base, check=True,
                         env={"GIT_SEQUENCE_EDITOR": f"cp {shlex.quote(f.name)}"})
        finally:
            os.unlink(f.name)
        self.accept()
        self.tab.refresh()


class ConflictDialog(QDialog):
    """Konflikte einer Datei Block für Block lösen, wie der Merge-Dialog in Fork."""

    def __init__(self, gui, path):
        super().__init__(gui)
        self.gui, self.path = gui, path
        self.full = os.path.join(gui.repo, path)
        self.setWindowTitle(f"Konflikt lösen – {path}")
        self.resize(1100, 750)
        try:
            with open(self.full, encoding="utf-8", newline="") as f:
                self.segs = parse_conflicts(f.read())
        except (OSError, UnicodeDecodeError):  # gelöscht oder binär
            self.segs = []
        blocks = [seg for seg in self.segs if not isinstance(seg, str)]
        ours_l, theirs_l = (blocks[0][2], blocks[0][3]) if blocks else ("unsere Seite", "ihre Seite")

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        for text, slot in ((f"Ganze Datei: {ours_l}", lambda: self.whole("--ours")),
                           (f"Ganze Datei: {theirs_l}", lambda: self.whole("--theirs")),
                           ("Im Editor öffnen", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.full))),
                           ("Datei löschen…", self.delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            top.addWidget(b)
        top.addStretch()
        lay.addLayout(top)

        self.blocks = []  # (Radio-Gruppe, Ergebnis-Feld) pro Konflikt
        if blocks:
            mono = gui.mono
            inner = QWidget()
            il = QVBoxLayout(inner)
            before = ""
            for seg in self.segs:
                if isinstance(seg, str):
                    before = seg
                    continue
                ours, theirs, lo, lt = seg
                box = QGroupBox(f"Konflikt {len(self.blocks) + 1} von {len(blocks)}")
                bl = QVBoxLayout(box)
                context = "".join(before.splitlines(keepends=True)[-3:]).rstrip("\n")
                if context:  # ein paar Zeilen davor zur Orientierung
                    c = QLabel(context, font=mono, enabled=False)
                    c.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                    bl.addWidget(c)
                group = QButtonGroup(box)
                row = QHBoxLayout()
                for choice, label, text in (("ours", lo, ours), ("theirs", lt, theirs)):
                    col = QVBoxLayout()
                    rb = QRadioButton(label or choice)
                    rb.setProperty("choice", choice)
                    group.addButton(rb)
                    ed = QPlainTextEdit(text, readOnly=True, font=mono)
                    lines = max(1, text.count("\n"))
                    ed.setFixedHeight(min(300, 30 + ed.fontMetrics().lineSpacing() * lines))
                    col.addWidget(rb)
                    col.addWidget(ed)
                    row.addLayout(col)
                bl.addLayout(row)
                both = QHBoxLayout()
                for choice, label in (("both", f"Beide ({lo} zuerst)"), ("both_rev", f"Beide ({lt} zuerst)")):
                    rb = QRadioButton(label)
                    rb.setProperty("choice", choice)
                    group.addButton(rb)
                    both.addWidget(rb)
                both.addStretch()
                bl.addLayout(both)

                bl.addWidget(QLabel("<b>Ergebnis</b> (Seite wählen und/oder hier bearbeiten)"))
                result = QPlainTextEdit(font=mono, placeholderText="Noch nichts gewählt")
                lines = max(3, ours.count("\n"), theirs.count("\n"))
                result.setFixedHeight(min(400, 30 + result.fontMetrics().lineSpacing() * lines))
                bl.addWidget(result)
                texts = {"ours": ours, "theirs": theirs, "both": ours + theirs, "both_rev": theirs + ours}
                group.buttonClicked.connect(
                    lambda b, r=result, t=texts: r.setPlainText(t[b.property("choice")].removesuffix("\n")))
                self.blocks.append((group, result))
                il.addWidget(box)
                before = ""
            il.addStretch()
            scroll = QScrollArea(widgetResizable=True)
            scroll.setWidget(inner)
            lay.addWidget(scroll)
            save = QPushButton("Speichern und als gelöst markieren")
            save.clicked.connect(self.save)
        else:
            lay.addWidget(QLabel("Keine Konfliktmarker gefunden (z.B. auf einer Seite gelöscht oder Binärdatei).\n"
                                 "Wähle oben eine Version, lösche die Datei oder übernimm den aktuellen Stand."))
            lay.addStretch()
            save = QPushButton("Aktuellen Stand als gelöst markieren")
            save.clicked.connect(lambda: self.run(("add", "--", path)))
        bottom = QHBoxLayout()
        bottom.addStretch()
        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        bottom.addWidget(save)
        save.setDefault(True)
        lay.addLayout(bottom)

    def run(self, *cmds):
        for cmd in cmds:
            self.gui.git(*cmd, check=True)
            if self.gui.last_rc:
                return
        self.accept()

    def whole(self, side):
        self.run(("checkout", side, "--", self.path), ("add", "--", self.path))

    def delete(self):
        if self.gui.confirm("Datei löschen", f"„{self.path}“ löschen und das als Lösung übernehmen?"):
            self.run(("rm", "-f", "--", self.path))

    def save(self):
        results = []
        for n, (group, result) in enumerate(self.blocks, 1):
            if not group.checkedButton() and not result.document().isModified():
                return QMessageBox.information(
                    self, "Konflikt lösen", f"Bitte für Konflikt {n} eine Seite wählen oder das Ergebnis bearbeiten.")
            text = result.toPlainText()
            results.append(text + "\n" if text else "")  # leer = Block ganz entfernen
        with open(self.full, "w", encoding="utf-8", newline="") as f:
            f.write(resolve_conflicts(self.segs, results))
        self.run(("add", "--", self.path))
