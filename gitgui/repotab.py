"""Ein geöffnetes Repository als Tab: Seitenleiste, Änderungen, Verlauf, Commit-Details."""
import html
import os
import re
import shlex
import subprocess
import time

from PySide6.QtCore import QFileSystemWatcher, QProcess, QProcessEnvironment, QSettings, QTimer, QUrl, Qt, Signal

from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QShortcut

from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QStackedWidget,
    QTabWidget, QTextBrowser, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .theme import COLORS, STATUS_COLORS
from .core import (
    GIT_ENV, OPERATIONS, build_graph, file_diffs, friendly_error, git_out,
    graph_args, line_patch, load_stars, parse_refs, parse_ssh_remote, parse_status, repo_value,
    save_stars, set_repo_value, split_hunks, ssh_command_for, ssh_key_from_command, ssh_test_result,
    view_option, ws_args,
)
from .diff import diff_html, patch_html, status_icon
from .widgets import (
    AuthorDelegate, Background, CommitDelegate, DiffView, EXTRA_ROLE, GRAPH_ROLE,
    HASH_ROLE, HEAD_ROLE, NODE_ROLE, REFS_ROLE, initials, person_color,
)
from .dialogs import ConflictDialog, FileHistoryDialog, RebaseDialog


LOG_PAGE = 1000  # so viele Commits werden auf einmal geladen; beim Scrollen ans Ende kommen weitere dazu


LOG_FORMAT = ["--date=format:%d.%m.%Y %H:%M", "--format=%H%x1f%P%x1f%h%x1f%s%x1f%an%x1f%ad%x1f%D"]


class RepoTab(QWidget):
    """Ein geöffnetes Repository (ein Tab im Hauptfenster)."""
    changed = Signal()  # Branch o.ä. hat sich geändert -> Tab-/Fenstertitel aktualisieren

    def __init__(self, repo):
        super().__init__()
        self.repo = repo
        self.name = os.path.basename(repo)
        self.branch = ""
        self.view = ("changes",)
        self.collapsed = {"Tags"}  # eingeklappte Abschnitte/Ordner der Seitenleiste
        self.op = None  # laufender merge/rebase/... oder None
        self.proc = None  # laufender Hintergrund-Befehl (fetch/pull/push)
        self.proc_label = ""
        self.n_conflicts = 0
        mono = QFont("monospace")
        mono.setStyleHint(QFont.Monospace)

        # Seitenleiste: Repo-Name, Filter, Baum
        self.sidebar = QTreeWidget(objectName="sidebar", headerHidden=True, indentation=14)
        self.sidebar.currentItemChanged.connect(self.on_select)
        self.sidebar.itemDoubleClicked.connect(self.on_double)
        self.sidebar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sidebar.customContextMenuRequested.connect(self.sidebar_menu)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar.itemCollapsed.connect(lambda it: self.collapsed.add(it.data(0, NODE_ROLE)))
        self.sidebar.itemExpanded.connect(lambda it: self.collapsed.discard(it.data(0, NODE_ROLE)))
        self.filter = QLineEdit(objectName="filter", placeholderText="Filter", clearButtonEnabled=True)
        self.filter.textChanged.connect(self.apply_filter)
        pane = QWidget(objectName="sidebarPane")
        pv = QVBoxLayout(pane)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)
        pv.addWidget(QLabel(self.name, objectName="repoTitle"))
        pv.addWidget(self.filter)
        pv.addWidget(self.sidebar)

        # Seite 0: lokale Änderungen wie bei Fork
        self.mono = mono

        def file_list():
            w = QListWidget(objectName="files", selectionMode=QAbstractItemView.ExtendedSelection)
            w.setContextMenuPolicy(Qt.CustomContextMenu)
            w.customContextMenuRequested.connect(lambda pos, w=w: self.file_menu(w, pos))
            return w

        def list_panel(title, widget, button, slot):
            panel = QWidget()
            pv = QVBoxLayout(panel)
            pv.setContentsMargins(0, 0, 0, 0)
            pv.setSpacing(0)
            head = QFrame(objectName="listHeader")
            hl = QHBoxLayout(head)
            hl.setContentsMargins(8, 4, 6, 4)
            label = QLabel(title)
            btn = QPushButton(button, toolTip="Auswahl, oder alle wenn nichts ausgewählt ist")
            btn.clicked.connect(slot)
            hl.addWidget(label)
            hl.addStretch()
            hl.addWidget(btn)
            pv.addWidget(head)
            pv.addWidget(widget)
            return panel, label

        self.unstaged = file_list()
        self.staged = file_list()
        unstaged_panel, self.unstaged_label = list_panel(
            "Nicht gestaged", self.unstaged, "Stagen", lambda: self.stage(self.selected(self.unstaged)))
        staged_panel, self.staged_label = list_panel(
            "Gestaged", self.staged, "Unstagen", lambda: self.unstage(self.selected(self.staged)))

        # Commit-Box: Betreff, Beschreibung, Amend
        box = QWidget(objectName="commitBox")
        cv = QVBoxLayout(box)
        cv.setContentsMargins(8, 8, 8, 8)
        self.subject = QLineEdit(objectName="subject", placeholderText="Commit-Betreff")
        self.subject.returnPressed.connect(self.commit)
        self.body = QPlainTextEdit(objectName="body", placeholderText="Beschreibung (optional)")
        self.amend = QCheckBox("Amend (letzten Commit ändern)")
        self.amend.toggled.connect(self.on_amend)
        self.commit_btn = QPushButton("Commit", objectName="commitBtn")
        self.commit_btn.clicked.connect(self.commit)
        crow = QHBoxLayout()
        crow.addWidget(self.amend)
        crow.addStretch()
        crow.addWidget(self.commit_btn)
        cv.addWidget(self.subject)
        cv.addWidget(self.body)
        cv.addLayout(crow)

        # Diff rechts mit Kopfzeile (Dateiname + Datei-Aktionen)
        self.diff = DiffView(self.on_hunk)
        self.diff.setFont(mono)
        self.diff.anchorClicked.connect(self.on_hunk)
        self.diff_ctx = None  # (pfad, gestaged, diff-text)
        self.sel_lines, self.last_line = set(), None  # ausgewählte Diff-Zeilen {(hunk, zeile)}
        diff_head = QFrame(objectName="diffHeader")
        dh = QHBoxLayout(diff_head)
        dh.setContentsMargins(8, 4, 6, 4)
        self.diff_title = QLabel()
        self.file_btn = QPushButton()
        self.file_btn.clicked.connect(self.toggle_file)
        self.lines_btn = QPushButton()
        self.lines_btn.clicked.connect(self.apply_lines)
        self.discard_btn = QPushButton("Verwerfen…")
        self.discard_btn.clicked.connect(lambda: self.diff_ctx and self.discard([self.diff_ctx[0]]))
        dh.addWidget(self.diff_title)
        dh.addStretch()
        self.diff_head_layout = dh  # Ansichts-Knöpfe hängt das Hauptfenster ein (add_view_buttons)
        dh.addWidget(self.lines_btn)
        dh.addWidget(self.discard_btn)
        dh.addWidget(self.file_btn)
        diff_pane = QWidget()
        dv = QVBoxLayout(diff_pane)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(0)
        dv.addWidget(diff_head)
        dv.addWidget(self.diff)

        # Banner während Merge/Rebase mit Abbrechen/Fortsetzen
        self.banner = QFrame(objectName="banner")
        bv = QVBoxLayout(self.banner)
        self.banner_label = QLabel(wordWrap=True)
        bv.addWidget(self.banner_label)
        brow = QHBoxLayout()
        abort_btn = QPushButton("Abbrechen")
        abort_btn.clicked.connect(self.abort_op)
        cont_btn = QPushButton("Fortsetzen")
        cont_btn.clicked.connect(lambda: self.act(self.op, "--continue"))
        brow.addStretch()
        brow.addWidget(abort_btn)
        brow.addWidget(cont_btn)
        bv.addLayout(brow)
        self.conflicts = QListWidget()
        self.conflicts_label = QLabel("Konflikte (Doppelklick = lösen)")

        lists = QSplitter(Qt.Vertical)
        lists.addWidget(unstaged_panel)
        lists.addWidget(staged_panel)
        lists.addWidget(box)
        lists.setSizes([300, 220, 170])
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.banner)
        lv.addWidget(self.conflicts_label)
        lv.addWidget(self.conflicts)
        lv.addWidget(lists)
        changes = QSplitter()
        changes.addWidget(left)
        changes.addWidget(diff_pane)
        changes.setSizes([360, 700])

        # Seite 1: Verlauf oben, Commit-Details unten
        self.log = QTreeWidget(objectName="log", rootIsDecorated=False, uniformRowHeights=True)
        self.log.setHeaderLabels(["Beschreibung", "Autor", "Commit", "Datum"])
        self.commit_delegate = CommitDelegate(self.log)
        self.log.setItemDelegateForColumn(0, self.commit_delegate)
        self.log_filter = QLineEdit(objectName="filter", clearButtonEnabled=True,
                                    placeholderText="Verlauf filtern: Tag, Branch, Nachricht, Autor oder Hash (Strg+F)")
        self.log_filter.textChanged.connect(self.apply_log_filter)
        self.log_limit, self.log_truncated, self.log_args = LOG_PAGE, False, []
        self.log.verticalScrollBar().valueChanged.connect(self.on_log_scroll)
        self.search_timer = QTimer(self, singleShot=True, interval=350)  # erst suchen, wenn das Tippen pausiert
        self.search_timer.timeout.connect(self.search_older)
        self.log.setItemDelegateForColumn(1, AuthorDelegate(self.log))
        header = self.log.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 180), (2, 80), (3, 130)):
            self.log.setColumnWidth(col, width)
        self.log.currentItemChanged.connect(lambda cur, _prev: self.show_commit(cur))
        self.log.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log.customContextMenuRequested.connect(self.log_menu)

        self.commit_info = QTextBrowser(openLinks=False)
        self.commit_info.anchorClicked.connect(self.on_link)
        self.commit_view = QTextBrowser(openLinks=False, font=mono)
        self.commit_view.anchorClicked.connect(self.on_link)
        self.commit_files = []  # Pfade in Reihenfolge des Patches, für Sprünge aus dem Commit-Tab
        self.detail = QTabWidget(objectName="detail", documentMode=True)
        self.detail.addTab(self.commit_info, "Commit")
        self.detail.addTab(self.commit_view, "Änderungen")
        self.detail_files = []

        # Dateibaum: alle Dateien des Repos zum Stand des Commits, rechts der Inhalt
        self.tree_files = QTreeWidget(objectName="sidebar", headerHidden=True)
        self.tree_files.currentItemChanged.connect(lambda cur, _prev: self.show_tree_file(cur))
        self.tree_files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_files.customContextMenuRequested.connect(self.tree_menu)
        self.tree_title = QLabel()
        self.tree_content = QPlainTextEdit(readOnly=True, font=mono, lineWrapMode=QPlainTextEdit.NoWrap)
        tree_head = QFrame(objectName="diffHeader")
        th = QHBoxLayout(tree_head)
        th.setContentsMargins(8, 4, 6, 4)
        th.addWidget(self.tree_title)
        tree_right = QWidget()
        tv = QVBoxLayout(tree_right)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        tv.addWidget(tree_head)
        tv.addWidget(self.tree_content)
        tree_split = QSplitter()
        tree_split.addWidget(self.tree_files)
        tree_split.addWidget(tree_right)
        tree_split.setSizes([320, 700])
        self.detail.addTab(tree_split, "Dateibaum")
        self.detail.currentChanged.connect(lambda _i: self.fill_tree())
        self.detail_hash, self.detail_status, self.tree_hash = None, {}, None
        log_pane = QWidget()
        lp = QVBoxLayout(log_pane)
        lp.setContentsMargins(0, 0, 0, 0)
        lp.setSpacing(0)
        self.graph_bar = QFrame(objectName="listHeader")
        gb = QHBoxLayout(self.graph_bar)
        gb.setContentsMargins(8, 4, 6, 4)
        self.graph_label = QLabel(wordWrap=True)
        reset = QPushButton("Filter zurücksetzen")
        reset.clicked.connect(lambda: self.set_graph_filter([], []))
        gb.addWidget(QLabel(pixmap=QIcon.fromTheme("view-filter").pixmap(16)))
        gb.addWidget(self.graph_label, 1)
        gb.addWidget(reset)
        self.graph_bar.hide()
        lp.addWidget(self.graph_bar)
        lp.addWidget(self.log_filter)
        lp.addWidget(self.log)
        history = QSplitter(Qt.Vertical)
        history.addWidget(log_pane)
        history.addWidget(self.detail)
        history.setSizes([420, 380])


        # Seite 2: Stash-Inhalt
        self.stash_view = QTextBrowser(openLinks=False, font=mono)

        self.stack = QStackedWidget()
        self.stack.addWidget(changes)
        self.stack.addWidget(history)
        self.stack.addWidget(self.stash_view)
        main = QSplitter()
        main.addWidget(pane)
        main.addWidget(self.stack)
        main.setSizes([230, 1000])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(main)

        self.unstaged.currentTextChanged.connect(lambda p: self.show_diff(p, cached=False))
        self.staged.currentTextChanged.connect(lambda p: self.show_diff(p, cached=True))
        # Auswahl gibt es immer nur in einer der beiden Listen
        self.unstaged.itemPressed.connect(lambda _: self.staged.clearSelection())
        self.staged.itemPressed.connect(lambda _: self.unstaged.clearSelection())
        self.conflicts.currentTextChanged.connect(lambda p: self.show_diff(p, cached=False))
        self.conflicts.itemDoubleClicked.connect(lambda it: self.resolve(it.text()))
        self.unstaged.itemDoubleClicked.connect(lambda it: self.act("add", "--", it.text()))
        self.staged.itemDoubleClicked.connect(lambda it: self.act("restore", "--staged", "--", it.text()))
        # nur im sichtbaren Tab aktiv, sonst wäre das Kürzel mehrdeutig
        QShortcut(QKeySequence("Ctrl+Return"), self, self.commit, context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+F"), self, context=Qt.WidgetWithChildrenShortcut,
                  activated=lambda: (self.log_filter if self.stack.currentIndex() == 1 else self.filter).setFocus())

        # Automatisch neu laden, wenn sich im .git-Ordner etwas tut (Commit/Branchwechsel im Terminal usw.)
        self.git_dir = None
        self.ahead_behind = None  # (ahead, behind) gegenüber dem Upstream, None = kein Upstream
        self.last_refresh = 0.0
        self.git_state = None
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.on_repo_changed)
        self.watcher.fileChanged.connect(self.on_repo_changed)
        self.reload_timer = QTimer(self, singleShot=True, interval=400)  # mehrere Änderungen zusammenfassen
        self.reload_timer.timeout.connect(self.auto_refresh)

        self.refresh()

    # --- git ---------------------------------------------------------------

    def git(self, *args, check=False, input=None, env=None):
        """Schnelle, lokale git-Befehle synchron; Netzwerk-Befehle laufen über act_async."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            stdin = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
            r = subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env={**GIT_ENV, **(env or {})}, **stdin)
        finally:
            QApplication.restoreOverrideCursor()
        self.last_rc = r.returncode
        if check:
            if r.returncode:
                self.show_error(args[0], r.stderr + r.stdout)
            else:
                self.show_status(args[0], r.stderr or r.stdout)
        return r.stdout

    def show_error(self, cmd, output):
        """Fehler verständlich anzeigen; Gits Originaltext steht unter „Details“."""
        message, translated = friendly_error(output)
        if message is None:  # Konflikt: Banner und Konfliktliste erklären es schon
            if isinstance(self.window(), QMainWindow):
                self.window().statusBar().showMessage(f"git {cmd}: Konflikte – bitte lösen", 10000)
            return
        box = QMessageBox(QMessageBox.Warning, f"git {cmd} fehlgeschlagen", message, QMessageBox.Ok, self)
        if translated:
            box.setDetailedText(output.strip())
        box.exec()

    def show_status(self, cmd, output):
        last = output.strip().splitlines()
        if isinstance(self.window(), QMainWindow):
            self.window().statusBar().showMessage(f"git {cmd}: " + (last[-1] if last else "ok"), 8000)

    def act_async(self, *args, quiet=False):
        """Fetch/Pull/Push im Hintergrund: das Fenster bleibt bedienbar, danach wird aktualisiert.

        quiet=True (automatischer Fetch): Fehler nur in der Statusleiste, kein Dialog.
        """
        if self.proc:
            if quiet:
                return
            return QMessageBox.information(self, "Git", f"Es läuft noch „git {self.proc_label}“. Bitte kurz warten.")
        proc = QProcess(self)
        env = QProcessEnvironment()
        for key, value in GIT_ENV.items():
            env.insert(key, value)
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(self.repo)
        proc.finished.connect(lambda code, status: self.async_done(proc, args, code, status, quiet))
        proc.errorOccurred.connect(lambda err: err == QProcess.FailedToStart
                                   and self.async_done(proc, args, -1, None, quiet))
        self.proc, self.proc_label = proc, args[0]
        self.changed.emit()
        proc.start("git", list(args))
        proc.closeWriteChannel()  # keine Eingaben: Git soll nie auf stdin warten

    def async_done(self, proc, args, code, status, quiet=False):
        if self.proc is not proc:  # schon behandelt (z.B. Startfehler + finished)
            return
        out = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        err = bytes(proc.readAllStandardError()).decode(errors="replace")
        self.proc = None
        proc.deleteLater()
        if (code != 0 or status == QProcess.CrashExit) and quiet:
            message = friendly_error(err + out)[0] or "Konflikte"
            if isinstance(self.window(), QMainWindow):
                self.window().statusBar().showMessage(f"Automatischer Fetch ({self.name}) fehlgeschlagen: "
                                                      + message.splitlines()[0], 10000)
        elif code != 0 or status == QProcess.CrashExit:
            self.show_error(args[0], (err + out) or "Der Befehl wurde abgebrochen.")
        elif not quiet:
            self.show_status(args[0], err or out)
        self.refresh()

    def act(self, *args):
        self.git(*args, check=True)
        self.refresh()

    def push(self, branch=None, force=False):
        """Pusht `branch` (Standard: aktueller Branch); force = sicheres Erzwingen mit --force-with-lease."""
        name = branch or self.branch
        if force and not self.confirm(
                "Push erzwingen", f"„{name}“ auf dem Remote überschreiben?\n\nNötig z.B. nach Amend oder Rebase. "
                "Abgesichert mit --force-with-lease: Hat jemand anderes inzwischen gepusht, bricht Git ab."):
            return
        extra = ["--force-with-lease"] if force else []
        upstream = self.git("rev-parse", "--abbrev-ref", f"{branch or ''}@{{u}}").strip()
        if upstream and not branch:
            self.act_async("push", *extra)
        elif upstream:  # ponytail: nimmt an, dass Remote-Namen keinen "/" enthalten
            self.act_async("push", *extra, upstream.split("/", 1)[0], branch)
        else:  # erster Push eines Branches: Upstream setzen
            self.act_async("push", *extra, "-u", "origin", branch or "HEAD")

    def pull(self, rebase=None):
        """Pull mit Merge oder Rebase; ohne Angabe gilt die Einstellung „Standardmäßig mit Rebase pullen“."""
        if rebase is None:
            rebase = QSettings("git_gui", "git_gui").value("pull_rebase", False, type=bool)
        # immer explizit, sonst bricht neueres Git bei auseinandergelaufenen Branches mit einer Rückfrage ab
        self.act_async("pull", "--rebase" if rebase else "--no-rebase")

    def new_branch(self, start=None):
        name, ok = QInputDialog.getText(self, "Neuer Branch", f"Name (wird von {start or 'HEAD'} erstellt):")
        if ok and name.strip():
            self.act("switch", "-c", name.strip(), *([start] if start else []))

    def rename_branch(self, old):
        new, ok = QInputDialog.getText(self, "Branch umbenennen", f"Neuer Name für „{old}“:", text=old)
        new = new.strip()
        if ok and new and new != old:
            self.git("branch", "-m", old, new, check=True)
            if self.last_rc == 0:  # Favorit und Graph-Filter wandern mit
                save_stars(self.repo, [f"branch:{new}" if x == f"branch:{old}" else x for x in load_stars(self.repo)])
                ren = lambda refs: [f"refs/heads/{new}" if r == f"refs/heads/{old}" else r for r in refs]
                only, hidden = self.graph_filter()
                set_repo_value("graph_filter", self.repo, {"only": ren(only), "hidden": ren(hidden)})
            self.refresh()

    def graph_filter(self):
        """(nur_zeigen, ausgeblendet) als volle Ref-Namen für die Ansicht „Alle Commits“."""
        gf = repo_value("graph_filter", self.repo, {})
        return gf.get("only", []), gf.get("hidden", [])

    def set_graph_filter(self, only, hidden):
        set_repo_value("graph_filter", self.repo, {"only": only, "hidden": hidden} if only or hidden else None)
        self.view = ("log", "--all", "all")  # Ergebnis gleich zeigen
        self.refresh()

    def toggle_graph(self, ref, which):
        """Ref in „nur zeigen“ (which="only") oder „ausblenden“ (which="hidden") an-/abschalten."""
        only, hidden = self.graph_filter()
        target, other = (only, hidden) if which == "only" else (hidden, only)
        if ref in target:
            target.remove(ref)
        else:
            target.append(ref)
            if ref in other:  # beides gleichzeitig ergibt keinen Sinn
                other.remove(ref)
        self.set_graph_filter(only, hidden)

    def toggle_star(self, kind, name):
        sid, stars = f"{kind}:{name}", load_stars(self.repo)
        save_stars(self.repo, [x for x in stars if x != sid] if sid in stars else stars + [sid])
        self.refresh()

    def confirm(self, title, text):
        return QMessageBox.question(self, title, text) == QMessageBox.Yes

    def delete_branch(self, name):
        if not self.confirm("Branch löschen", f"Branch „{name}“ löschen?"):
            return
        self.git("branch", "-d", name)
        if self.refs(f"refs/heads/{name}") and self.confirm(
                "Nicht gemergt", f"„{name}“ enthält Commits, die nirgends gemergt sind.\n"
                                 "Trotzdem löschen? Diese Commits gehen dann verloren."):
            self.git("branch", "-D", name, check=True)
        if not self.refs(f"refs/heads/{name}"):  # gelöscht: auch aus Favoriten und Graph-Filter
            save_stars(self.repo, [x for x in load_stars(self.repo) if x != f"branch:{name}"])
            only, hidden = self.graph_filter()
            drop = lambda refs: [r for r in refs if r != f"refs/heads/{name}"]
            set_repo_value("graph_filter", self.repo, {"only": drop(only), "hidden": drop(hidden)}
                           if drop(only) or drop(hidden) else None)
        self.refresh()

    def delete_remote_branch(self, name):
        remote, branch = name.split("/", 1)
        if self.confirm("Remote-Branch löschen", f"„{branch}“ auf „{remote}“ löschen?\n"
                                                 "Das betrifft alle, die dieses Remote nutzen."):
            self.act_async("push", remote, "--delete", branch)

    def delete_tag(self, name):
        if self.confirm("Tag löschen", f"Tag „{name}“ lokal löschen?"):
            self.act("tag", "-d", name)

    def operation(self):
        """Läuft gerade ein Merge/Rebase/Cherry-Pick/Revert? -> git-Befehlsname oder None."""
        markers = (("merge", "MERGE_HEAD"), ("rebase", "rebase-merge"), ("rebase", "rebase-apply"),
                   ("cherry-pick", "CHERRY_PICK_HEAD"), ("revert", "REVERT_HEAD"))
        args = [a for _, m in markers for a in ("--git-path", m)]
        paths = self.git("rev-parse", *args).splitlines()
        for (op, _), path in zip(markers, paths):
            if os.path.exists(os.path.join(self.repo, path)):
                return op
        return None

    def abort_op(self):
        if self.confirm(f"{OPERATIONS[self.op]} abbrechen",
                        f"{OPERATIONS[self.op]} abbrechen? Bereits gelöste Konflikte gehen dabei verloren."):
            self.act(self.op, "--abort")

    def resolve(self, path):
        ConflictDialog(self, path).exec()
        self.refresh()

    def stash(self):
        if not (self.unstaged.count() or self.staged.count()):
            return QMessageBox.information(self, "Stash", "Keine lokalen Änderungen.")
        msg, ok = QInputDialog.getText(self, "Stash", "Nachricht (optional):")
        if ok:
            self.act("stash", "push", "--include-untracked", *(["-m", msg.strip()] if msg.strip() else []))

    def drop_stash(self, ref, label):
        if QMessageBox.question(self, "Stash löschen", f"„{label}“ endgültig löschen?") == QMessageBox.Yes:
            self.act("stash", "drop", ref)

    # --- Repo / Refresh ----------------------------------------------------

    def refs(self, pattern, fmt="%(refname:short)"):
        out = self.git("for-each-ref", f"--format={fmt}", pattern)
        return [line.split("\t") for line in out.splitlines()]

    def refs_stash(self):
        out = self.git("stash", "list", "--format=%gd%x1f%s")
        return [line.split("\x1f", 1) for line in out.splitlines()]

    def refresh(self):
        unstaged, staged, conflicts = parse_status(self.git("status", "--porcelain=v1", "-z"))
        keep = self.diff_ctx and self.diff_ctx[:2]  # angezeigte Datei nach dem Refresh wieder auswählen
        for widget, items in ((self.unstaged, unstaged), (self.staged, staged)):
            widget.blockSignals(True)
            widget.clear()
            for path, code in items:
                it = QListWidgetItem(status_icon(code), path)
                it.setData(Qt.UserRole, code)
                widget.addItem(it)
            widget.blockSignals(False)
        self.unstaged_label.setText(f"Nicht gestaged ({len(unstaged)})")
        self.staged_label.setText(f"Gestaged ({len(staged)})")
        self.commit_btn.setText(f"{len(staged)} Datei{'en' if len(staged) != 1 else ''} committen"
                                if staged else "Commit")
        self.conflicts.clear()
        self.conflicts.addItems(conflicts)
        for i in range(self.conflicts.count()):
            self.conflicts.item(i).setForeground(QColor(COLORS["conflict"]))
        self.conflicts.setVisible(bool(conflicts))
        self.conflicts_label.setVisible(bool(conflicts))
        if conflicts and not self.n_conflicts:  # neue Konflikte: direkt hinspringen
            self.view = ("changes",)
        self.n_conflicts = len(conflicts)

        self.op = self.operation()
        self.banner.setVisible(bool(self.op))
        if self.op:
            name = OPERATIONS[self.op]
            self.banner_label.setText(
                f"<b>{name} läuft.</b> {len(conflicts)} Konflikt(e) offen." if conflicts else
                f"<b>{name} läuft.</b> Alle Konflikte gelöst – „Fortsetzen“ schließt ab.")
        self.diff_ctx = None
        self.diff.clear()
        self.diff_title.clear()
        self.file_btn.hide()
        self.discard_btn.hide()
        self.lines_btn.hide()
        if keep:
            path, cached = keep
            widget = self.staged if cached else self.unstaged
            found = widget.findItems(path, Qt.MatchExactly)
            if found:
                widget.setCurrentItem(found[0])
        self.branch = self.git("branch", "--show-current").strip() or "(detached)"
        counts = self.git("rev-list", "--left-right", "--count", "HEAD...@{u}").split()
        self.ahead_behind = tuple(map(int, counts)) if self.last_rc == 0 and len(counts) == 2 else None
        self.changed.emit()
        self.build_sidebar(len({p for p, _ in unstaged} | {p for p, _ in staged} | set(conflicts)))
        self.render_view()
        self.watch_git_dir()
        self.last_refresh = time.time()
        self.git_state = self.state_fingerprint()

    def watch_git_dir(self):
        """.git, HEAD-Datei und alle Ordner unter refs/ beobachten (QFileSystemWatcher ist nicht rekursiv)."""
        if not self.git_dir:
            self.git_dir = self.git("rev-parse", "--absolute-git-dir").strip()
        if not self.git_dir:
            return
        paths = [self.git_dir]
        for sub in ("refs/heads", "refs/remotes", "refs/tags"):
            for dirpath, _dirs, _files in os.walk(os.path.join(self.git_dir, sub)):
                paths.append(dirpath)
        new = [p for p in paths if p not in self.watcher.directories()]
        if new:
            self.watcher.addPaths(new)

    def state_fingerprint(self):
        """Änderungszeiten von HEAD, Index, Refs & Co. – gleich geblieben heißt: nichts Neues von außen."""
        if not self.git_dir:
            return None
        paths = [os.path.join(self.git_dir, name) for name in
                 ("HEAD", "index", "packed-refs", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge")]
        for sub in ("refs/heads", "refs/remotes", "refs/tags"):
            for dirpath, _dirs, files in os.walk(os.path.join(self.git_dir, sub)):
                paths += [os.path.join(dirpath, f) for f in files]
        state = []
        for path in paths:
            try:
                state.append((path, os.stat(path).st_mtime_ns))
            except OSError:  # gibt es (gerade) nicht
                pass
        return state

    def on_repo_changed(self, _path):
        self.reload_timer.start()  # mehrere Ereignisse kurz hintereinander zusammenfassen

    def auto_refresh(self):
        """Neu laden nach Änderungen von außen – nur sichtbare Tabs, beim Tab-Wechsel wird ohnehin geladen.

        Eigene Aktionen laden selbst neu; deren Ereignisse erkennt man daran, dass sich seither nichts geändert hat.
        """
        if self.isVisible() and not self.proc and self.state_fingerprint() != self.git_state:
            self.refresh()

    def build_sidebar(self, n_changes):
        t = self.sidebar
        t.blockSignals(True)
        t.clear()
        selected, nodes = None, []

        def add(parent, text, key, icon, bold=False):
            nonlocal selected
            it = QTreeWidgetItem(parent, [text])
            it.setData(0, Qt.UserRole, key)
            it.setIcon(0, QIcon.fromTheme(icon))
            if bold:
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
            if key == self.view:
                selected = it
            return it

        def node(parent, text, path, icon=None):
            """Nicht auswählbarer Abschnitt/Ordner; merkt sich, ob er eingeklappt war."""
            it = QTreeWidgetItem(parent, [text])
            it.setFlags(Qt.ItemIsEnabled)
            it.setData(0, NODE_ROLE, path)
            if icon:
                it.setIcon(0, QIcon.fromTheme(icon))
            else:  # Abschnitts-Überschrift
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
            nodes.append(it)
            return it

        def add_path(sec, name, key, icon, bold=False, suffix="", first_icon="folder"):
            """`feature/x` -> Ordner „feature“ mit Eintrag „x“, wie bei Fork."""
            *dirs, leaf = name.split("/")
            parent = sec
            for i, d in enumerate(dirs):
                path = f"{parent.data(0, NODE_ROLE)}/{d}"
                found = [parent.child(c) for c in range(parent.childCount())
                         if parent.child(c).data(0, NODE_ROLE) == path]
                parent = found[0] if found else node(parent, d, path, first_icon if i == 0 else "folder")
            return add(parent, leaf + suffix, key, icon, bold)

        add(t, f"Änderungen ({n_changes})", ("changes",), "document-edit")
        all_item = add(t, "Alle Commits", ("log", "--all", "all"), "view-history")

        heads = self.refs("refs/heads", "%(HEAD)\t%(refname:short)\t%(upstream:track,nobracket)")
        remotes = [n for (n,) in self.refs("refs/remotes") if "/" in n and not n.endswith("/HEAD")]  # "origin" = origin/HEAD
        current = next((n for h, n, _ in heads if h == "*"), None)
        only, hidden = self.graph_filter()
        existing_refs = {f"refs/heads/{n}" for _, n, _ in heads} | {f"refs/remotes/{n}" for n in remotes}
        if existing_refs & set(only + hidden):
            all_item.setText(0, "Alle Commits (gefiltert)")
            all_item.setIcon(0, QIcon.fromTheme("view-filter"))

        def mark(item, kind, name):
            """Filter-/Ausblenden-Symbol für Branches im Graph-Filter."""
            ref = f"refs/heads/{name}" if kind == "branch" else f"refs/remotes/{name}"
            if ref in only:
                item.setIcon(0, QIcon.fromTheme("view-filter"))
                item.setToolTip(0, "Im Graph-Filter: „Alle Commits“ zeigt nur gefilterte Branches")
            elif ref in hidden:
                item.setIcon(0, QIcon.fromTheme("view-hidden"))
                item.setForeground(0, QColor(COLORS["dim"]))
                item.setToolTip(0, "In „Alle Commits“ ausgeblendet")

        # Favoriten (Starred) oben, wie bei Fork; gelöschte Branches werden einfach nicht gezeigt
        existing = {f"branch:{n}" for _, n, _ in heads} | {f"remote:{n}" for n in remotes}
        stars = sorted((x for x in load_stars(self.repo) if x in existing), key=lambda x: x.split(":", 1)[1].lower())
        if stars:
            sec = node(t, "Favoriten", "Favoriten")
            for sid in stars:
                kind, name = sid.split(":", 1)
                mark(add(sec, name, ("log", name, kind), "starred", bold=kind == "branch" and name == current), kind, name)

        sec = node(t, "Branches", "Branches")
        for head, name, track in heads:
            track = track.replace("ahead ", "↑").replace("behind ", "↓").replace(",", "")
            current = head == "*"
            mark(add_path(sec, name, ("log", name, "branch"), "checkmark" if current else "vcs-branch",
                          bold=current, suffix=f"  {track}" if track else ""), "branch", name)

        sec = node(t, "Remotes", "Remotes")
        for name in self.git("remote").split():  # auch Remotes ohne (bisher gefetchte) Branches zeigen
            node(sec, name, f"Remotes/{name}", "folder-cloud")
        for name in remotes:
            mark(add_path(sec, name, ("log", name, "remote"), "vcs-branch", first_icon="folder-cloud"), "remote", name)

        sec = node(t, "Tags", "Tags")
        for (name,) in self.refs("refs/tags"):
            add_path(sec, name, ("log", name, "tag"), "tag")

        sec = node(t, "Stashes", "Stashes")
        for ref, subject in self.refs_stash():
            add(sec, subject, ("stash", ref), "vcs-stash")

        for n in nodes:
            n.setExpanded(n.data(0, NODE_ROLE) not in self.collapsed)
        if selected is None:  # z.B. Branch wurde gelöscht
            self.view = ("changes",)
            selected = t.topLevelItem(0)
        t.setCurrentItem(selected)
        t.blockSignals(False)
        self.apply_filter()

    def apply_filter(self, *_):
        """Blendet Branches/Remotes/Tags/Stashes aus, die nicht zum Filtertext passen."""
        text = self.filter.text().strip().lower()
        t = self.sidebar
        t.blockSignals(True)  # Aufklappen fürs Filtern soll nicht als „vom Nutzer aufgeklappt“ zählen

        def visit(item):
            if item.data(0, NODE_ROLE) and item.childCount():
                visible = any([visit(item.child(i)) for i in range(item.childCount())])
                if text:
                    item.setExpanded(True)
            else:
                key = item.data(0, Qt.UserRole) or ()
                name = f"{key[1] if len(key) > 1 else ''} {item.text(0)}".lower()
                visible = not text or text in name
            item.setHidden(not visible)
            return visible

        for i in range(t.topLevelItemCount()):
            sec = t.topLevelItem(i)
            if sec.data(0, NODE_ROLE):
                visit(sec)
                sec.setHidden(False)
        if not text:  # Ausklapp-Zustand wie vor dem Filtern
            for it in t.findItems("", Qt.MatchContains | Qt.MatchRecursive):
                if it.data(0, NODE_ROLE):
                    it.setExpanded(it.data(0, NODE_ROLE) not in self.collapsed)
        t.blockSignals(False)

    # --- Ansichten ---------------------------------------------------------

    def on_select(self, item):
        key = item and item.data(0, Qt.UserRole)
        if key:
            if tuple(key) != self.view:
                self.log_limit = LOG_PAGE  # neue Ansicht: wieder mit der ersten Seite anfangen
            self.view = tuple(key)
            self.render_view()

    def on_double(self, item):
        key = item.data(0, Qt.UserRole)
        if key and key[0] == "stash":
            return self.act("stash", "apply", key[1])
        if not key or key[0] != "log":
            return
        self.checkout(key[1], key[2])

    def node_menu(self, node, pos):
        """Rechtsklick auf Abschnitt „Remotes“/„Tags“ oder einen Remote-Ordner; True, wenn ein Menü kam."""
        menu = QMenu(self)
        if node == "Remotes":
            menu.addAction("Remote hinzufügen…", self.add_remote)
        elif node.startswith("Remotes/") and node.count("/") == 1:
            name = node.split("/", 1)[1]
            menu.addAction(f"„{name}“ fetchen", lambda: self.act_async("fetch", "--prune", name))
            menu.addSeparator()
            menu.addAction("Umbenennen…", lambda: self.rename_remote(name))
            menu.addAction("Adresse ändern…", lambda: self.set_remote_url(name))
            menu.addAction("Adresse kopieren",
                           lambda: QApplication.clipboard().setText(self.git("remote", "get-url", name).strip()))
            menu.addSeparator()
            key = self.ssh_key()
            menu.addAction("SSH-Verbindung testen", lambda: self.test_ssh(name))
            menu.addAction(f"SSH-Schlüssel für dieses Repo… ({os.path.basename(key)})" if key
                           else "SSH-Schlüssel für dieses Repo…", self.choose_ssh_key)
            if key:
                menu.addAction("Eigenen SSH-Schlüssel entfernen (Standard nutzen)", self.remove_ssh_key)
            menu.addSeparator()
            menu.addAction("Entfernen…", lambda: self.remove_remote(name))
        elif node == "Tags":
            menu.addAction("Neuer Tag auf aktuellem Commit…",
                           lambda: self.create_tag(self.git("rev-parse", "HEAD").strip()))
            menu.addAction("Alle Tags zu origin pushen", lambda: self.act_async("push", "origin", "--tags"))
        else:
            return False
        menu.exec(self.sidebar.viewport().mapToGlobal(pos))
        return True

    def ssh_key(self):
        """Für dieses Repo gesetzter SSH-Schlüssel (core.sshCommand) oder None."""
        return ssh_key_from_command(self.git("config", "--get", "core.sshCommand").strip())

    def choose_ssh_key(self):
        """Eigenen SSH-Schlüssel für dieses Repo setzen – gilt für alle Remotes dieses Repos."""
        path, _ = QFileDialog.getOpenFileName(self, "Privaten SSH-Schlüssel wählen (nicht die .pub-Datei)",
                                              self.ssh_key() or os.path.expanduser("~/.ssh"))
        if not path:
            return
        path = path.removesuffix(".pub")  # aus Versehen den öffentlichen Schlüssel gewählt
        if not os.path.isfile(path):
            return QMessageBox.information(self, "SSH-Schlüssel", f"Zu „{path}.pub“ fehlt der private Schlüssel.")
        self.git("config", "core.sshCommand", ssh_command_for(path), check=True)
        self.show_status("config", f"SSH-Schlüssel für dieses Repo: {path}")

    def remove_ssh_key(self):
        self.git("config", "--unset", "core.sshCommand", check=True)
        self.show_status("config", "Eigener SSH-Schlüssel entfernt – es gelten wieder ~/.ssh/config und der SSH-Agent")

    def test_ssh(self, remote):
        """Anmeldung mit genau dem SSH-Befehl prüfen, den Git für dieses Repo nimmt (läuft im Hintergrund)."""
        url = self.git("remote", "get-url", remote).strip()
        target = parse_ssh_remote(url)
        if not target:
            return QMessageBox.information(self, "SSH-Verbindung testen", f"„{remote}“ nutzt keine SSH-Adresse:\n{url}"
                                           "\n\nBei HTTPS fragt Git nach Benutzer und Token. Für die Anmeldung per "
                                           "Schlüssel die Adresse auf SSH umstellen (z.B. git@github.com:name/repo.git).")
        host, port = target
        command = [*shlex.split(self.git("config", "--get", "core.sshCommand").strip() or "ssh"), "-T",
                   "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10", *(["-p", port] if port else []), host]
        self.show_status("ssh", f"Teste die Anmeldung bei {host}…")

        def run():
            r = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=GIT_ENV, timeout=60)
            return r.returncode, (r.stderr + r.stdout).strip()

        Background(self, run, lambda result: self.show_ssh_result(host, result))

    def show_ssh_result(self, host, result):
        code, output = result or (-1, "Keine Antwort (Zeitüberschreitung).")
        ok, message = ssh_test_result(code, output)
        box = QMessageBox(QMessageBox.Information if ok else QMessageBox.Warning, "SSH-Verbindung testen",
                          f"{host}\n\n{message}", QMessageBox.Ok, self)
        box.setDetailedText(output)
        box.exec()

    def add_remote(self):
        name, ok = QInputDialog.getText(self, "Remote hinzufügen", "Name (z.B. origin oder upstream):")
        if not ok or not name.strip():
            return
        url, ok = QInputDialog.getText(self, "Remote hinzufügen", "Adresse (z.B. git@github.com:name/repo.git):")
        if ok and url.strip():
            self.git("remote", "add", name.strip(), url.strip(), check=True)
            if self.last_rc == 0:  # gleich die Branches holen, damit sie in der Seitenleiste erscheinen
                self.act_async("fetch", name.strip())
            self.refresh()

    def rename_remote(self, old):
        new, ok = QInputDialog.getText(self, "Remote umbenennen", f"Neuer Name für „{old}“:", text=old)
        if ok and new.strip() and new.strip() != old:
            self.act("remote", "rename", old, new.strip())

    def set_remote_url(self, name):
        url, ok = QInputDialog.getText(self, "Adresse ändern", f"Neue Adresse für „{name}“:",
                                       text=self.git("remote", "get-url", name).strip())
        if ok and url.strip():
            self.act("remote", "set-url", name, url.strip())

    def remove_remote(self, name):
        if self.confirm("Remote entfernen", f"Remote „{name}“ entfernen?\n\nNur die Verbindung und die lokalen "
                        "Remote-Branches verschwinden – auf dem Server selbst wird nichts gelöscht."):
            self.act("remote", "remove", name)

    def checkout(self, name, kind):
        if kind == "branch":
            self.act("switch", name)
        elif kind == "remote":  # legt lokalen Tracking-Branch an bzw. wechselt dorthin
            self.act("switch", name.split("/", 1)[1])
        elif kind == "tag":
            self.act("switch", "--detach", name)

    def sidebar_menu(self, pos):
        item = self.sidebar.itemAt(pos)
        key = item and item.data(0, Qt.UserRole)
        node = item and item.data(0, NODE_ROLE)
        if node and self.node_menu(node, pos):
            return
        if not key or key[:2] in (("changes",), ("log", "--all")):
            return
        menu = QMenu(self)
        add = menu.addAction
        if key[0] == "stash":
            ref, label = key[1], item.text(0)
            add("Anwenden", lambda: self.act("stash", "apply", ref))
            add("Anwenden und löschen (Pop)", lambda: self.act("stash", "pop", ref))
            menu.addSeparator()
            add("Löschen…", lambda: self.drop_stash(ref, label))
        else:
            _, name, kind = key
            current = self.git("branch", "--show-current").strip()
            if name != current:
                add(f"„{name}“ auschecken", lambda: self.checkout(name, kind))
                if current:  # nicht im detached HEAD
                    add(f"„{name}“ in „{current}“ mergen", lambda: self.act("merge", name))
                    add(f"„{current}“ auf „{name}“ rebasen", lambda: self.act("rebase", name))
                menu.addSeparator()
            add("Neuer Branch von hier…", lambda: self.new_branch(name))
            if kind in ("branch", "remote"):
                starred = f"{kind}:{name}" in load_stars(self.repo)
                add("Aus Favoriten entfernen" if starred else "Zu Favoriten hinzufügen",
                    lambda: self.toggle_star(kind, name))
                ref = f"refs/heads/{name}" if kind == "branch" else f"refs/remotes/{name}"
                only, hidden = self.graph_filter()
                add("Aus dem Graph-Filter nehmen" if ref in only else "Im Graph filtern (nur gefilterte zeigen)",
                    lambda: self.toggle_graph(ref, "only"))
                add("Im Graph wieder einblenden" if ref in hidden else "Im Graph ausblenden",
                    lambda: self.toggle_graph(ref, "hidden"))
            if kind == "branch":
                add("Umbenennen…", lambda: self.rename_branch(name))
                add("Pushen", lambda: self.push(name))
                if name != current:
                    menu.addSeparator()
                    add("Löschen…", lambda: self.delete_branch(name))
            elif kind == "remote":
                menu.addSeparator()
                add("Auf Remote löschen…", lambda: self.delete_remote_branch(name))
            elif kind == "tag":
                add("Pushen", lambda: self.act_async("push", "origin", f"refs/tags/{name}"))
                menu.addSeparator()
                add("Löschen…", lambda: self.delete_tag(name))
        menu.exec(self.sidebar.viewport().mapToGlobal(pos))

    def render_view(self):
        if self.view[0] == "changes":
            self.stack.setCurrentIndex(0)
            return
        if self.view[0] == "stash":
            self.stack.setCurrentIndex(2)
            ref = self.view[1]
            # -u: auch neue (untracked) Dateien des Stashs zeigen
            self.stash_view.setHtml(patch_html(self.git("stash", "show", "-p", "-u", *ws_args(), ref),
                                               split=view_option("split_diff")))
            return
        self.stack.setCurrentIndex(1)
        self.graph_bar.hide()  # nur in „Alle Commits“ mit aktivem Graph-Filter sichtbar
        keep = self.log.currentItem() and self.log.currentItem().data(0, HASH_ROLE)
        bar = self.log.verticalScrollBar()
        scroll = bar.value()
        self.log.blockSignals(True)  # kein show_commit für jede Zwischenauswahl
        self.log.clear()
        self.log.blockSignals(False)
        self.commit_info.clear()
        self.commit_view.clear()
        head = self.git("rev-parse", "HEAD").strip()
        self.log_args = self.all_commits_args() if self.view[1] == "--all" else [self.view[1]]
        out = self.git("log", "--date-order", "--decorate=full", "-n", str(self.log_limit), *LOG_FORMAT,
                       *self.log_args, "--")
        commits = [line.split("\x1f") for line in out.splitlines()]
        self.log_truncated = len(commits) >= self.log_limit
        graph = build_graph([(c[0], c[1].split()) for c in commits])
        items = [self.log_item(c, row, head) for c, row in zip(commits, graph)]
        self.log.addTopLevelItems(items)
        # zuvor gewählten Commit wieder auswählen, sonst den ersten – damit die Details nicht leer sind
        again = next((it for it in items if it.data(0, HASH_ROLE) == keep), items[0] if items else None)
        bar.blockSignals(True)  # Auswahl und Scroll-Wiederherstellung sollen nicht selbst Nachladen auslösen
        if again:
            self.log.setCurrentItem(again)
        bar.setValue(scroll)  # Scrollposition bleibt beim Neuladen/Nachladen erhalten
        bar.blockSignals(False)
        self.apply_log_filter()

    def log_item(self, fields, row, head):
        """Eine Zeile im Verlauf aus den Feldern von LOG_FORMAT; row = Graph-Daten (None ohne Graph)."""
        full, _parents, h, subject, author, date, refs = fields
        it = QTreeWidgetItem([subject, author, h, date])
        it.setData(0, GRAPH_ROLE, row)
        it.setData(0, REFS_ROLE, parse_refs(refs))
        it.setData(0, HASH_ROLE, full)
        if full == head:  # aktueller Commit fett, wie bei Fork
            it.setData(0, HEAD_ROLE, True)
            for col in (1, 2, 3):
                f = it.font(col)
                f.setBold(True)
                it.setFont(col, f)
        for col in (2, 3):
            it.setForeground(col, QColor(COLORS["dim"]) if full != head else QColor(COLORS["text"]))
        return it

    def on_log_scroll(self, value):
        """Am Ende des Verlaufs angekommen: die nächsten LOG_PAGE Commits nachladen."""
        bar = self.log.verticalScrollBar()
        if (self.log_truncated and not self.log_filter.text().strip() and bar.maximum() > 0
                and value >= bar.maximum() - 3 and self.stack.currentIndex() == 1):
            self.log_limit += LOG_PAGE
            self.render_view()
            if isinstance(self.window(), QMainWindow):
                self.window().statusBar().showMessage(f"{self.log.topLevelItemCount()} Commits geladen", 4000)

    def log_menu(self, pos):
        """Rechtsklick auf einen Commit im Verlauf."""
        item = self.log.itemAt(pos)
        h = item and item.data(0, HASH_ROLE)
        if not h:
            return
        self.log.setCurrentItem(item)
        menu = QMenu(self)
        pick = menu.addAction(f"Cherry-Pick auf „{self.branch}“…", lambda: self.apply_commit("cherry-pick", h, item.text(0)))
        revert = menu.addAction("Commit rückgängig machen (Revert)…", lambda: self.apply_commit("revert", h, item.text(0)))
        self.git("merge-base", "--is-ancestor", h, "HEAD")
        contained = self.last_rc == 0
        if contained:  # schon enthalten: Git würde mit einem leeren Cherry-Pick hängen bleiben
            pick.setText("Cherry-Pick (schon im aktuellen Branch)")
            pick.setEnabled(False)
        else:  # Revert nur für Commits, die im aktuellen Branch stecken
            revert.setText("Revert (nicht im aktuellen Branch)")
            revert.setEnabled(False)
        if self.op:
            for a, name in ((pick, "Cherry-Pick"), (revert, "Revert")):
                a.setText(f"{name} (erst {OPERATIONS[self.op]} abschließen)")
                a.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Branch hier erstellen…", lambda: self.new_branch(h[:10]))
        menu.addAction("Tag hier erstellen…", lambda: self.create_tag(h))
        rebase = menu.addAction("Interaktiv rebasen ab hier…", lambda: self.interactive_rebase(h))
        checkout = menu.addAction("Commit auschecken…", lambda: self.checkout_commit(h))
        target = f"„{self.branch}“" if self.branch != "(detached)" else "HEAD"
        reset = menu.addMenu(f"{target} hierhin zurücksetzen")
        for mode, label in (("soft", "Soft – Änderungen bleiben gestaged"),
                            ("mixed", "Mixed – Änderungen bleiben ungestaged"),
                            ("hard", "Hard – alle Änderungen verwerfen…")):
            reset.addAction(label, lambda m=mode: self.reset_to(h, m))
        if not contained or self.branch == "(detached)":
            rebase.setText("Interaktiv rebasen (nur Commits im aktuellen Branch)")
            rebase.setEnabled(False)
        if self.op:  # während Merge/Rebase lieber nicht umbiegen
            checkout.setEnabled(False)
            reset.setEnabled(False)
            rebase.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Commit-Hash kopieren", lambda: QApplication.clipboard().setText(h))
        menu.exec(self.log.viewport().mapToGlobal(pos))

    def interactive_rebase(self, h):
        if self.git("rev-list", "--merges", f"{h}..HEAD").strip():
            return QMessageBox.information(self, "Interaktiver Rebase", "Zwischen diesem Commit und HEAD liegen "
                                           "Merge-Commits – die würden beim Rebase verloren gehen. Bitte einen "
                                           "späteren Commit wählen.")
        RebaseDialog(self, h).exec()

    def create_tag(self, h):
        name, ok = QInputDialog.getText(self, "Tag erstellen", f"Name des Tags für Commit {h[:7]}:")
        if not ok or not name.strip():
            return
        msg, ok = QInputDialog.getText(self, "Tag erstellen",
                                       "Nachricht (optional – mit Nachricht entsteht ein annotierter Tag):")
        if ok:
            self.act("tag", *(["-a", "-m", msg.strip()] if msg.strip() else []), name.strip(), h)

    def checkout_commit(self, h):
        if self.confirm("Commit auschecken", f"Commit {h[:7]} auschecken?\n\nDu bist danach auf keinem Branch "
                        "(„detached HEAD“). Neue Commits dort gehen leicht verloren – lege dafür einen Branch an."):
            self.act("switch", "--detach", h)

    def reset_to(self, h, mode):
        """Aktuellen Branch auf einen Commit zurücksetzen (soft/mixed/hard), mit Warnung vor Verlusten."""
        target = f"„{self.branch}“" if self.branch != "(detached)" else "HEAD"
        text = {"soft": f"{target} auf {h[:7]} zurücksetzen?\nDie Änderungen der späteren Commits bleiben gestaged.",
                "mixed": f"{target} auf {h[:7]} zurücksetzen?\nDie Änderungen der späteren Commits bleiben als "
                         "ungestagte Änderungen erhalten.",
                "hard": f"{target} HART auf {h[:7]} zurücksetzen?\nAlle Änderungen der späteren Commits UND alle "
                        "lokalen, nicht committeten Änderungen gehen verloren."}[mode]
        later = self.git("rev-list", "--count", f"{h}..HEAD").strip()
        if later and later != "0":
            text += f"\n\n{later} Commit(s) gehören danach nicht mehr zum Branch (über den Reflog noch auffindbar)."
        if mode == "hard":
            dirty = len(self.git("status", "--porcelain").splitlines())
            if dirty:
                text += f"\n\nAchtung: {dirty} Datei(en) mit lokalen Änderungen werden verworfen."
        if self.confirm("Zurücksetzen", text):
            self.act("reset", f"--{mode}", h)

    def apply_commit(self, cmd, h, subject):
        """Cherry-Pick (übernehmen) oder Revert (per neuem Commit rückgängig machen) im aktuellen Branch.

        Konflikte landen im üblichen Konflikt-Banner mit Fortsetzen/Abbrechen.
        """
        merge = len(self.git("rev-list", "--parents", "-n", "1", h).split()) > 2
        if cmd == "cherry-pick":
            title, text = "Cherry-Pick", f"Commit {h[:7]} „{subject}“ auf „{self.branch}“ übernehmen?"
        else:
            title, text = "Revert", (f"Commit {h[:7]} „{subject}“ rückgängig machen?\n\n"
                                     f"Dafür wird auf „{self.branch}“ ein neuer Commit erstellt, der die Änderungen umkehrt.")
        if merge:
            text += "\n\nDas ist ein Merge-Commit: maßgeblich sind seine Änderungen gegenüber dem ersten Parent."
        if self.confirm(title, text):
            self.act(cmd, *(["-m", "1"] if merge else []), h)

    def all_commits_args(self):
        """Refs für „Alle Commits“ inkl. Graph-Filter; füllt nebenbei die Hinweisleiste über dem Verlauf."""
        existing = set(self.git("for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes").split())
        only, hidden = self.graph_filter()
        short = lambda refs: ", ".join(r.removeprefix("refs/heads/").removeprefix("refs/remotes/")
                                       for r in refs if r in existing)
        parts = []
        if short(only):
            parts.append(f"Graph zeigt nur: <b>{html.escape(short(only))}</b>")
        if short(hidden):
            parts.append(f"Ausgeblendet: <b>{html.escape(short(hidden))}</b>")
        self.graph_label.setText(" &nbsp;·&nbsp; ".join(parts))
        self.graph_bar.setVisible(bool(parts))
        return graph_args(only, hidden, existing)

    def apply_log_filter(self, *_):
        """Blendet Commits aus, deren Tags/Branches, Nachricht, Autor und Hash nicht zum Suchtext passen.

        Ist der Verlauf nur teilweise geladen, sucht search_older danach auch in der restlichen Historie.
        """
        for i in reversed(range(self.log.topLevelItemCount())):  # Treffer der vorigen Suche entfernen
            if self.log.topLevelItem(i).data(0, EXTRA_ROLE):
                self.log.takeTopLevelItem(i)
        text = self.log_filter.text().strip().lower()
        self.commit_delegate.filtering = bool(text)
        if text and self.log_truncated:
            self.search_timer.start()
        shown = 0
        for i in range(self.log.topLevelItemCount()):
            it = self.log.topLevelItem(i)
            names = " ".join(name for name, _kind, _synced in it.data(0, REFS_ROLE) or [])
            hay = f"{names} {it.text(0)} {it.text(1)} {it.data(0, HASH_ROLE)}".lower()
            match = not text or text in hay
            it.setHidden(not match)
            shown += match
        self.log_filter.setToolTip(f"{shown} von {self.log.topLevelItemCount()} Commits" if text else "")
        current = self.log.currentItem()
        if text and (current is None or current.isHidden()):  # Auswahl auf den ersten Treffer
            first = next((self.log.topLevelItem(i) for i in range(self.log.topLevelItemCount())
                          if not self.log.topLevelItem(i).isHidden()), None)
            self.log.setCurrentItem(first)
        self.log.viewport().update()

    def search_older(self):
        """Filter auch jenseits der geladenen Commits: passende Tags/Branches, Nachrichten, Autoren und Hashes.

        Die git-Abfragen laufen im Hintergrund; das Ergebnis zählt nur, wenn der Suchtext noch derselbe ist.
        """
        text = self.log_filter.text().strip()
        if not text or not self.log_truncated:
            return
        loaded = {self.log.topLevelItem(i).data(0, HASH_ROLE) for i in range(self.log.topLevelItemCount())}
        repo, view, args = self.repo, self.view, list(self.log_args)

        def search():
            g = lambda *a: git_out(repo, *a)
            found, all_view = set(), view[1] == "--all"
            if all_view:  # Refs, deren Name passt (annotierte Tags: der Commit dahinter)
                for line in g("for-each-ref", "--format=%(objectname) %(*objectname) %(refname:short)",
                              "refs/tags", "refs/heads", "refs/remotes").splitlines():
                    obj, peeled, name = line.split(" ", 2)
                    if text.lower() in name.lower():
                        found.add(peeled or obj)
            for option in (f"--grep={text}", f"--author={text}"):
                found.update(g("log", "-i", "-F", option, "--format=%H", "-n", "300", *args, "--").split())
            if re.fullmatch(r"[0-9a-fA-F]{4,40}", text):
                h = g("rev-parse", "--verify", "-q", f"{text}^{{commit}}").strip()
                if h and (all_view or subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", h, view[1]],
                                                     env=GIT_ENV, capture_output=True).returncode == 0):
                    found.add(h)
            new = sorted(found - loaded)[:500]
            return new and g("log", "--no-walk=sorted", "--decorate=full", *LOG_FORMAT, *new, "--")

        Background(self, search, lambda out: self.show_older(text, view, out))

    def show_older(self, text, view, out):
        if not out or self.log_filter.text().strip() != text or self.view != view:  # veraltet
            return
        head = self.git("rev-parse", "HEAD").strip()
        lines = out.splitlines()
        for line in lines:
            it = self.log_item(line.split("\x1f"), None, head)
            it.setData(0, EXTRA_ROLE, True)
            it.setToolTip(0, "Älterer Commit außerhalb der geladenen Liste")
            self.log.addTopLevelItem(it)
        shown = sum(not self.log.topLevelItem(i).isHidden() for i in range(self.log.topLevelItemCount()))
        self.log_filter.setToolTip(f"{shown} Treffer, davon {len(lines)} aus älteren Commits")
        current = self.log.currentItem()
        if current is None or current.isHidden():
            self.log.setCurrentItem(next(self.log.topLevelItem(i) for i in range(self.log.topLevelItemCount())
                                         if not self.log.topLevelItem(i).isHidden()))

    def show_commit(self, item, parent=0):
        """Details eines Commits; bei Merges die Änderungen gegenüber Parent Nr. `parent`."""
        h = item and item.data(0, HASH_ROLE)
        if not h:
            return
        info = self.git("show", "-s", "--date=format:%d.%m.%Y %H:%M:%S",
                        "--format=%H%x1f%P%x1f%an%x1f%ae%x1f%ad%x1f%cn%x1f%ce%x1f%cd%x1f%B", h)
        full, parents, an, ae, ad, cn, ce, cd, body = info.split("\x1f", 8)
        subject, _, rest = body.strip().partition("\n")
        # Merge: wie Fork die Änderungen gegenüber dem ersten Parent (das, was der Merge hereinbringt);
        # `git show` würde für Merges ein kombiniertes Diff liefern, das wir nicht darstellen
        plist = parents.split()
        base = plist[parent] if len(plist) > 1 else None
        diff = (lambda *a: self.git("diff", "-M", *a, base, h)) if base else (lambda *a: self.git("show", "--format=", "-M", *a, h))
        files = [line.split("\t") for line in diff("--name-status").splitlines()]
        self.detail_files = [f[-1] for f in files]
        self.detail_hash, self.detail_status = full, {f[-1]: f[0][:1] for f in files}
        self.tree_hash = None  # Dateibaum gehört zum vorigen Commit
        self.fill_tree()
        e = html.escape
        dim = COLORS["dim"]

        def person(title, name, mail, date):
            return (f"<td width='50%'><span style='color:{dim}'>{title}</span>"
                    f"<table cellspacing='0' cellpadding='4'><tr>"
                    f"<td bgcolor='{person_color(name)}' width='34' align='center' valign='middle'>"
                    f"<b>{e(initials(name))}</b></td>"
                    f"<td><b>{e(name)}</b> <span style='color:{dim}'>{e(mail)}</span><br>{e(date)}</td>"
                    f"</tr></table></td>")

        parent_links = " ".join(f"<a href='gitcommit:{p}'>{p[:7]}</a>" for p in parents.split())
        file_rows = "".join(
            f"<tr><td style='color:{STATUS_COLORS.get(f[0][:1], COLORS['text'])}'><b>{e(f[0][:1])}</b></td>"
            f"<td><a href='gitfile:{i}' style='color:{COLORS['text']}; text-decoration:none'>{e(f[-1])}</a></td></tr>"
            for i, f in enumerate(files))
        self.commit_info.setHtml(f"""
            <table width='100%' cellspacing='10'><tr>{person("AUTOR", an, ae, ad)}{person("COMMITTER", cn, ce, cd)}</tr></table>
            <table cellspacing='6'>
              <tr><td align='right' style='color:{dim}'>SHA</td><td>{full}</td></tr>
              <tr><td align='right' style='color:{dim}'>PARENTS</td><td>{parent_links}</td></tr>
            </table><hr>
            <p style='font-size:13pt'><b>{e(subject)}</b></p>
            <p>{e(rest.strip()).replace(chr(10), "<br>")}</p><hr>
            {self.parent_switch(plist, parent) if base else ""}
            <table cellspacing='4'>{file_rows}</table>""")
        patch = diff("--patch", *ws_args())
        self.commit_files = [f[0] for f in file_diffs(patch)]
        self.commit_view.setHtml((self.parent_switch(plist, parent) if base else "")
                                 + patch_html(patch, split=view_option("split_diff")))

    def fill_tree(self):
        """Baut den Dateibaum erst, wenn der Tab sichtbar ist (bei großen Repos teuer)."""
        if self.detail.currentIndex() != 2 or not self.detail_hash or self.tree_hash == self.detail_hash:
            return
        self.tree_hash = h = self.detail_hash
        self.tree_files.clear()
        self.tree_title.setText("Lädt…")
        self.tree_content.clear()

        def load():
            paths = [p for p in git_out(self.repo, "ls-tree", "-r", "--name-only", "-z", h).split("\0") if p]
            # Ordner vor Dateien, jeweils alphabetisch – wie im Dateimanager
            return sorted(paths, key=lambda p: [(0, d.lower()) for d in p.split("/")[:-1]]
                          + [(1, p.rsplit("/", 1)[-1].lower())])

        Background(self, load, lambda paths: self.build_tree(h, paths or []))

    def build_tree(self, h, paths):
        if h != self.tree_hash:  # inzwischen ein anderer Commit gewählt
            return
        # ponytail: bei sehr großen Repos (100k+ Dateien) dauert der Aufbau der Einträge; dann Ordner erst beim Aufklappen
        t = self.tree_files
        t.blockSignals(True)
        t.clear()
        folders, first_changed = {"": t.invisibleRootItem()}, None
        bold = QFont(t.font())
        bold.setBold(True)

        def folder(path):
            if path not in folders:
                parent, _, name = path.rpartition("/")
                it = QTreeWidgetItem(folder(parent), [name])
                it.setIcon(0, QIcon.fromTheme("folder"))
                folders[path] = it
            return folders[path]

        for path in paths:
            parent, _, name = path.rpartition("/")
            it = QTreeWidgetItem(folder(parent), [name])
            it.setData(0, Qt.UserRole, path)
            it.setIcon(0, QIcon.fromTheme("text-x-generic"))
            status = self.detail_status.get(path)
            if status:  # in diesem Commit geändert: hervorheben und Ordner aufklappen
                it.setForeground(0, QColor(STATUS_COLORS.get(status, COLORS["text"])))
                it.setFont(0, bold)
                node = it.parent()
                while node:
                    node.setExpanded(True)
                    node = node.parent()
                first_changed = first_changed or it
        t.blockSignals(False)
        self.tree_title.clear()
        self.tree_content.clear()
        if first_changed:
            t.setCurrentItem(first_changed)

    def tree_menu(self, pos):
        item = self.tree_files.itemAt(pos)
        path = item and item.data(0, Qt.UserRole)
        if path:
            menu = QMenu(self)
            menu.addAction("Historie und Blame…", lambda: FileHistoryDialog(self, path).show())
            menu.exec(self.tree_files.viewport().mapToGlobal(pos))

    def show_tree_file(self, item):
        path = item and item.data(0, Qt.UserRole)
        if not path:  # Ordner
            return
        self.tree_title.setText(path)
        r = subprocess.run(["git", "-C", self.repo, "cat-file", "blob", f"{self.tree_hash}:{path}"],
                           capture_output=True)
        data, limit = r.stdout, 2_000_000
        if b"\0" in data[:8000]:
            self.tree_content.setPlainText(f"Binärdatei ({len(data):,} Bytes)".replace(",", "."))
        else:
            try:
                text = data[:limit].decode("utf-8")
            except UnicodeDecodeError:  # ältere Dateien sind oft Latin-1
                text = data[:limit].decode("latin-1")
            self.tree_content.setPlainText(text + ("\n\n… (gekürzt)" if len(data) > limit else ""))

    def parent_switch(self, parents, current):
        """Umschalter „Änderungen gegenüber Parent 1 | Parent 2“ für Merge-Commits."""
        links = []
        for i, p in enumerate(parents):
            label = f"Parent {i + 1} ({p[:7]})"
            links.append(f"<b>{label}</b>" if i == current else
                         f"<a href='gitparent:{i}' style='color:{COLORS['accent']}'>{label}</a>")
        return (f"<p style='color:{COLORS['dim']}'>&nbsp;Merge – Änderungen gegenüber: "
                + " &nbsp;|&nbsp; ".join(links) + "</p>")

    def on_link(self, url):
        if url.scheme() == "gitcommit":  # Parent anklicken -> dorthin springen
            for i in range(self.log.topLevelItemCount()):
                if self.log.topLevelItem(i).data(0, HASH_ROLE) == url.path():
                    return self.log.setCurrentItem(self.log.topLevelItem(i))
        elif url.scheme() == "gitparent":  # Merge: anderen Parent als Vergleichsbasis
            self.show_commit(self.log.currentItem(), int(url.path()))
        elif url.scheme() == "gitfile":  # Datei anklicken -> ihr Diff im Änderungen-Tab
            self.detail.setCurrentIndex(1)
            path = self.detail_files[int(url.path())]
            if path in self.commit_files:
                self.commit_view.scrollToAnchor(f"file{self.commit_files.index(path)}")

    def add_view_buttons(self, actions):
        """Schalter „Leerzeichen ignorieren“/„Nebeneinander“ auch direkt in der Diff-Kopfzeile."""
        for i, action in enumerate(actions):
            btn = QToolButton(autoRaise=True)
            btn.setDefaultAction(action)  # Text/Häkchen bleiben mit dem Menü synchron
            self.diff_head_layout.insertWidget(1 + i, btn)

    def rerender_diffs(self):
        """Nach Umschalten der Ansicht: alle sichtbaren Diffs neu holen und zeichnen."""
        if self.diff_ctx:
            self.show_diff(*self.diff_ctx[:2])
        if self.log.currentItem():
            self.show_commit(self.log.currentItem())
        if self.view[0] == "stash":
            self.render_view()

    def selected(self, widget):
        return [it.text() for it in widget.selectedItems()]

    def stage(self, paths):
        self.act("add", "-A", "--", *(paths or ["."]))

    def unstage(self, paths):
        self.act("restore", "--staged", "--", *(paths or ["."]))

    def discard(self, paths):
        """Änderungen an Dateien unwiderruflich verwerfen (neue Dateien werden gelöscht)."""
        if not paths or not self.confirm(
                "Änderungen verwerfen", f"Änderungen an {len(paths)} Datei(en) unwiderruflich verwerfen?\n\n"
                                        + "\n".join(paths[:10]) + ("\n…" if len(paths) > 10 else "")):
            return
        codes = {self.unstaged.item(i).text(): self.unstaged.item(i).data(Qt.UserRole)
                 for i in range(self.unstaged.count())}
        untracked = [p for p in paths if codes.get(p) == "?"]
        tracked = [p for p in paths if p not in untracked]
        if tracked:
            self.git("restore", "--", *tracked, check=True)
        if untracked:
            self.git("clean", "-f", "--", *untracked, check=True)
        self.refresh()

    def file_menu(self, widget, pos):
        item = widget.itemAt(pos)
        if not item:
            return
        if not item.isSelected():
            widget.setCurrentItem(item)
        paths = self.selected(widget)
        menu = QMenu(self)
        if widget is self.unstaged:
            menu.addAction("Stagen", lambda: self.stage(paths))
            menu.addAction("Änderungen verwerfen…", lambda: self.discard(paths))
        else:
            menu.addAction("Unstagen", lambda: self.unstage(paths))
        menu.addSeparator()
        full = os.path.join(self.repo, item.text())
        menu.addAction("Historie und Blame…", lambda: FileHistoryDialog(self, item.text()).show())
        menu.addAction("Im Editor öffnen", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(full)))
        menu.addAction("Ordner öffnen",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(full))))
        menu.exec(widget.viewport().mapToGlobal(pos))

    def show_diff(self, path, cached):
        if not path:
            return
        ws = ws_args()
        text = self.git("diff", *ws, "--cached", "--", path) if cached else self.git("diff", *ws, "--", path)
        if not text and not cached:  # untracked file: diff against nothing
            text = self.git("diff", "--no-index", "--", "/dev/null", path)
        self.diff_ctx = (path, cached, text)
        self.sel_lines, self.last_line = set(), None
        self.render_diff()
        self.diff_title.setText(path)
        self.file_btn.setText("Datei unstagen" if cached else "Datei stagen")
        self.file_btn.show()
        self.discard_btn.setVisible(not cached)

    def toggle_file(self):
        if self.diff_ctx:
            path, cached, _ = self.diff_ctx
            (self.unstage if cached else self.stage)([path])

    def render_diff(self):
        path, cached, text = self.diff_ctx
        ws, split = view_option("ignore_ws"), view_option("split_diff")
        # Zeilenweise geht nicht bei gelöschten Dateien (Git verlangt dort den ganzen Inhalt), nicht nebeneinander,
        # und mit ignorierten Leerzeichen passt der Diff nicht mehr zur Datei – dann auch keine Hunks
        selectable = not ws and not split and "\ndeleted file mode" not in split_hunks(text)[0]
        action = None if ws else ("Hunk unstagen" if cached else "Hunk stagen")
        bar = self.diff.verticalScrollBar()
        pos = bar.value()  # Scrollposition beim Neuzeichnen behalten
        page, self.diff.rowmap = diff_html(text, action, self.sel_lines, selectable, path=path, split=split)
        self.diff.setHtml(page)
        bar.setValue(pos)
        n = len(self.sel_lines)
        self.lines_btn.setText(f"{n} Zeile{'n' if n != 1 else ''} {'unstagen' if cached else 'stagen'}")
        self.lines_btn.setVisible(bool(n))

    def apply_lines(self):
        """Nur die ausgewählten Zeilen stagen bzw. unstagen."""
        if not self.diff_ctx or not self.sel_lines:
            return
        path, cached, text = self.diff_ctx
        patch = line_patch(text, self.sel_lines, reverse=cached)
        self.git("apply", "--cached", "--recount", *(["--reverse"] if cached else []), "-", input=patch, check=True)
        self.refresh()

    def on_hunk(self, url):
        """Hunk stagen/unstagen (wie „Stage Hunk“ in Fork) oder eine Zeile an-/abwählen."""
        if not self.diff_ctx:
            return
        if url.scheme() == "line":  # Umschalt+Klick wählt einen Bereich im selben Hunk
            h, i = map(int, url.path().split(":"))
            if QApplication.keyboardModifiers() & Qt.ShiftModifier and self.last_line and self.last_line[0] == h:
                lines = split_hunks(self.diff_ctx[2])[1][h].splitlines()
                lo, hi = sorted((self.last_line[1], i))
                self.sel_lines |= {(h, j) for j in range(lo, hi + 1) if lines[j][:1] in "+-"}
            else:
                self.sel_lines ^= {(h, i)}
            self.last_line = (h, i)
            return self.render_diff()
        if url.scheme() != "hunk":
            return
        path, cached, text = self.diff_ctx
        head, hunks = split_hunks(text)
        patch = head + hunks[int(url.path())]
        if not patch.endswith("\n"):
            patch += "\n"
        self.git("apply", "--cached", *(["--reverse"] if cached else []), "-", input=patch, check=True)
        self.refresh()

    def on_amend(self, checked):
        if checked and not self.subject.text().strip() and not self.body.toPlainText().strip():
            subject, _, body = self.git("log", "-1", "--format=%B").strip().partition("\n")
            self.subject.setText(subject)
            self.body.setPlainText(body.strip())

    def commit(self):
        subject, body = self.subject.text().strip(), self.body.toPlainText().strip()
        msg = subject + (f"\n\n{body}" if body else "")
        if self.op == "merge" and not msg:  # Git hat schon eine Merge-Nachricht vorbereitet
            self.act("commit", "--no-edit")
            return
        if not subject:
            return QMessageBox.information(self, "Commit", "Commit-Betreff fehlt.")
        amend = self.amend.isChecked()
        if self.staged.count() == 0 and not amend and self.op != "merge":
            return QMessageBox.information(self, "Commit", "Nichts gestaged.")
        self.git("commit", *(["--amend"] if amend else []), "-m", msg, check=True)
        if self.last_rc == 0:
            self.subject.clear()
            self.body.clear()
            self.amend.setChecked(False)
        self.refresh()
