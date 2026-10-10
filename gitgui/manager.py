"""„Neuer Tab“: Repository-Verwaltung mit Übersicht und Statistik."""
import html
import json
import os

from PySide6.QtCore import QTimer, QUrl, Qt, Signal

from PySide6.QtGui import QColor, QDesktopServices, QIcon

from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QMenu, QMessageBox, QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QTabWidget, QTextBrowser, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .theme import COLORS
from .core import MONTHS, git_out, group_repos, monthly_series, relative_time, repo_root
from .widgets import Background, CommitChart, NODE_ROLE, RepoTree


class RepoManager(QWidget):
    """„Neuer Tab“: zuletzt geöffnete und bekannte Repositories, mit Übersicht und Statistik – wie in Fork."""
    open_requested = Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.current = None
        self.stats_for = None

        self.list = RepoTree(objectName="sidebar", headerHidden=True, indentation=14)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.invisibleRootItem().setFlags(Qt.ItemIsEnabled)  # nicht auf oberste Ebene ablegen
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.dropped.connect(self.on_drop)
        self.list.currentItemChanged.connect(lambda cur, _prev: self.select(cur))
        self.list.itemDoubleClicked.connect(lambda it: it.data(0, Qt.UserRole) and self.open(it.data(0, Qt.UserRole)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.list_menu)
        add_btn = QPushButton("Hinzufügen…")
        add_btn.clicked.connect(self.add_repo)
        scan_btn = QPushButton("Durchsuchen…", toolTip="Einen Ordner auf der Festplatte nach Git-Repositories durchsuchen")
        scan_btn.clicked.connect(self.scan_folder)
        folder_btn = QToolButton(icon=QIcon.fromTheme("folder-new"), toolTip="Neuer Ordner in der Liste", autoRaise=True)
        folder_btn.clicked.connect(lambda: self.new_folder())
        if folder_btn.icon().isNull():  # ohne Icon-Theme nicht unsichtbar sein
            folder_btn.setText("Neuer Ordner")
        btns = QHBoxLayout()
        btns.setContentsMargins(8, 6, 8, 8)
        btns.addWidget(add_btn)
        btns.addWidget(scan_btn)
        btns.addWidget(folder_btn)
        left = QWidget(objectName="sidebarPane")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        lv.addWidget(self.list)
        lv.addLayout(btns)

        # Rechts: Kopf mit Name/Pfad/letztem Commit und „Öffnen“, darunter Übersicht/Statistik
        self.headline = QLabel(objectName="repoHeadline")
        self.path_label = QLabel()
        self.last_label = QLabel()
        self.open_btn = QPushButton("Öffnen", objectName="commitBtn")
        self.open_btn.clicked.connect(lambda: self.current and self.open(self.current))
        head = QHBoxLayout()
        info = QVBoxLayout()
        info.addWidget(self.headline)
        info.addWidget(self.path_label)
        info.addWidget(self.last_label)
        head.addLayout(info)
        head.addStretch()
        head.addWidget(self.open_btn, alignment=Qt.AlignTop)
        self.summary = QTextBrowser(openLinks=False)
        self.chart = CommitChart()
        stats = QWidget()
        sv = QVBoxLayout(stats)
        head_row = QHBoxLayout()
        head_row.addWidget(QLabel("<b style='font-size:12pt'>Commits pro Monat</b>"))
        head_row.addStretch()
        self.table_btn = QPushButton("Als Tabelle", checkable=True)
        head_row.addWidget(self.table_btn)
        sv.addLayout(head_row)
        # Tabelle als Alternative zum Diagramm: genaue Zahlen, und lesbar ohne Farben zu unterscheiden
        self.stats_table = QTreeWidget(rootIsDecorated=False, uniformRowHeights=True)
        self.chart_stack = QStackedWidget()
        self.chart_stack.addWidget(self.chart)
        self.chart_stack.addWidget(self.stats_table)
        self.table_btn.toggled.connect(lambda on: self.chart_stack.setCurrentIndex(int(on)))
        sv.addWidget(self.chart_stack, 1)
        self.pages = QTabWidget(objectName="detail", documentMode=True)
        self.pages.addTab(self.summary, "Übersicht")
        self.pages.addTab(stats, "Statistik")
        self.pages.currentChanged.connect(lambda _i: self.load_stats())
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(16, 12, 16, 0)
        rv.addLayout(head)
        rv.addWidget(self.pages)
        self.empty = QLabel("Wähle links ein Repository oder füge eines hinzu.", alignment=Qt.AlignCenter)
        self.right = QStackedWidget()
        self.right.addWidget(self.empty)
        self.right.addWidget(right)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.right)
        split.setSizes([280, 1000])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        title = QLabel("Repository-Verwaltung", objectName="managerTitle")
        title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        outer.addWidget(title)
        outer.addWidget(split)
        self.reload()

    # --- Listen in den Einstellungen ---------------------------------------

    def known(self):
        return self.settings.value("known", [], type=list)

    def recent(self):
        return self.settings.value("recent", [], type=list)

    def reload(self):
        """Liste neu aufbauen: „Zuletzt geöffnet“ und alle bekannten Repos in ihren eigenen Ordnern."""
        t = self.list
        t.blockSignals(True)
        t.clear()
        selected = None

        def entry(parent, path, draggable=False):
            nonlocal selected
            it = QTreeWidgetItem(parent, [os.path.basename(path)])
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | (Qt.ItemIsDragEnabled if draggable else Qt.NoItemFlags))
            it.setData(0, Qt.UserRole, path)
            it.setToolTip(0, path)
            it.setIcon(0, QIcon.fromTheme("folder-git", QIcon.fromTheme("vcs-branch")))
            if not os.path.isdir(path):
                it.setForeground(0, QColor(COLORS["dim"]))
                it.setToolTip(0, f"{path} (nicht gefunden)")
            if path == self.current and selected is None:
                selected = it

        def section(title):
            it = QTreeWidgetItem(t, [title])
            it.setFlags(Qt.ItemIsEnabled)
            f = it.font(0)
            f.setBold(True)
            it.setFont(0, f)
            return it

        sec = section("Zuletzt geöffnet")
        for path in self.recent():
            entry(sec, path)
        sec = section("Repositories")
        sec.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled)  # hierher ziehen = aus dem Ordner nehmen
        sec.setData(0, NODE_ROLE, "")
        self.repos_section = sec
        folders, folder_of = self.folder_data()
        for name, paths in group_repos(self.known(), folders, folder_of):
            parent = sec
            if name is not None:
                parent = QTreeWidgetItem(sec, [name])
                parent.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled)
                parent.setData(0, NODE_ROLE, name)
                parent.setIcon(0, QIcon.fromTheme("folder"))
            for path in paths:
                entry(parent, path, draggable=True)
        t.expandAll()
        t.blockSignals(False)
        if selected is None:  # sonst den zuletzt geöffneten zeigen
            sec = t.topLevelItem(0)
            selected = sec.child(0) if sec.childCount() else None
        if selected:
            t.setCurrentItem(selected)
        else:
            self.select(None)

    def remember(self, paths):
        known = self.known()
        self.settings.setValue("known", known + [p for p in paths if p not in known])

    def forget(self, path):
        self.settings.setValue("known", [p for p in self.known() if p != path])
        self.settings.setValue("recent", [p for p in self.recent() if p != path])
        folders, folder_of = self.folder_data()
        folder_of.pop(path, None)
        self.save_folders(folders, folder_of)
        if self.current == path:
            self.current = None
        self.reload()

    # --- eigene Ordner -----------------------------------------------------

    def folder_data(self):
        """(ordnernamen, {repo-pfad: ordner}) aus den Einstellungen."""
        try:
            data = json.loads(self.settings.value("folders", "{}"))
        except ValueError:
            data = {}
        return data.get("names", []), data.get("assign", {})

    def save_folders(self, folders, folder_of):
        folder_of = {p: f for p, f in folder_of.items() if f in folders}
        self.settings.setValue("folders", json.dumps({"names": sorted(folders, key=str.lower), "assign": folder_of}))

    def ask_folder_name(self, title, text=""):
        name, ok = QInputDialog.getText(self, title, "Name des Ordners:", text=text)
        name = name.strip()
        if not ok or not name or name == text:
            return None
        if name in self.folder_data()[0]:
            QMessageBox.information(self, title, f"Einen Ordner „{name}“ gibt es schon.")
            return None
        return name

    def new_folder(self, move=None):
        """Neuen Ordner anlegen; mit `move` gleich dieses Repo hineinlegen."""
        name = self.ask_folder_name("Neuer Ordner")
        if name:
            folders, folder_of = self.folder_data()
            if move:
                folder_of[move] = name
            self.save_folders(folders + [name], folder_of)
            self.reload()

    def rename_folder(self, old):
        new = self.ask_folder_name("Ordner umbenennen", old)
        if new:
            folders, folder_of = self.folder_data()
            self.save_folders([new if f == old else f for f in folders],
                              {p: new if f == old else f for p, f in folder_of.items()})
            self.reload()

    def delete_folder(self, name):
        """Ordner entfernen; die Repos darin bleiben in der Liste (ohne Ordner)."""
        folders, folder_of = self.folder_data()
        self.save_folders([f for f in folders if f != name], folder_of)
        self.reload()

    def move_to(self, path, folder):
        folders, folder_of = self.folder_data()
        folder_of.pop(path, None)
        if folder:
            folder_of[path] = folder
        self.save_folders(folders, folder_of)
        self.reload()

    def on_drop(self):
        """Nach Drag & Drop die neue Zuordnung aus dem Baum lesen und speichern."""
        folders, folder_of = self.folder_data()[0], {}
        sec = self.repos_section
        for i in range(sec.childCount()):
            child = sec.child(i)
            name = child.data(0, NODE_ROLE)
            for j in range(child.childCount() if name else 0):
                folder_of[child.child(j).data(0, Qt.UserRole)] = name
        self.save_folders(folders, folder_of)
        QTimer.singleShot(0, self.reload)  # erst nach Ende des Drops neu aufbauen (sortiert wieder)

    # --- Aktionen ----------------------------------------------------------

    def open(self, path):
        self.open_requested.emit(path)

    def add_repo(self):
        path = QFileDialog.getExistingDirectory(self, "Repository hinzufügen")
        root = path and repo_root(path)
        if path and not root:
            return QMessageBox.warning(self, "Kein Git-Repo", f"{path} ist kein Git-Repository.")
        if root:
            self.remember([root])
            self.current = root
            self.reload()

    def scan_folder(self):
        """Findet Git-Repositories unterhalb eines Ordners (bis 4 Ebenen tief) und nimmt sie in die Liste auf."""
        base = QFileDialog.getExistingDirectory(self, "Ordner nach Repositories durchsuchen")
        if not base:
            return
        found = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for dirpath, dirnames, _files in os.walk(base):
                if ".git" in dirnames or os.path.isfile(os.path.join(dirpath, ".git")):
                    found.append(os.path.realpath(dirpath))
                    dirnames.clear()  # in Repos nicht weitersuchen
                elif dirpath[len(base):].count(os.sep) >= 4:
                    dirnames.clear()
                else:
                    dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules"]
        finally:
            QApplication.restoreOverrideCursor()
        new = [p for p in found if p not in self.known()]
        self.remember(found)
        self.reload()
        QMessageBox.information(self, "Ordner durchsuchen",
                                f"{len(found)} Repositories gefunden, davon {len(new)} neu in der Liste.")

    def list_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return
        path, folder = item.data(0, Qt.UserRole), item.data(0, NODE_ROLE)
        menu = QMenu(self)
        if path:
            menu.addAction("Öffnen", lambda: self.open(path))
            menu.addAction("Im Dateimanager zeigen", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
            sub = menu.addMenu("In Ordner verschieben")
            folders, folder_of = self.folder_data()
            for name in folders:
                a = sub.addAction(name, lambda n=name: self.move_to(path, n))
                a.setEnabled(folder_of.get(path) != name)
            if folders:
                sub.addSeparator()
            sub.addAction("Neuer Ordner…", lambda: self.new_folder(move=path))
            if folder_of.get(path) in folders:
                sub.addAction("Aus dem Ordner nehmen", lambda: self.move_to(path, None))
            menu.addSeparator()
            menu.addAction("Aus der Liste entfernen", lambda: self.forget(path))
        elif folder:
            menu.addAction("Umbenennen…", lambda: self.rename_folder(folder))
            menu.addAction("Ordner löschen", lambda: self.delete_folder(folder))
        elif folder == "":  # Abschnitt „Repositories“
            menu.addAction("Neuer Ordner…", lambda: self.new_folder())
        else:
            return
        menu.exec(self.list.viewport().mapToGlobal(pos))

    # --- Details -----------------------------------------------------------

    def select(self, item):
        path = item and item.data(0, Qt.UserRole)
        if not path:
            self.right.setCurrentIndex(0)
            return
        self.current = path
        self.right.setCurrentIndex(1)
        self.headline.setText(os.path.basename(path))
        self.path_label.setText(f"<span style='color:{COLORS['dim']}'>{html.escape(path)}</span>")
        if not repo_root(path):
            self.last_label.setText("Nicht gefunden – evtl. verschoben oder gelöscht.")
            self.open_btn.setEnabled(False)
            self.summary.clear()
            self.chart.set_data([], [])
            self.stats_table.clear()
            self.stats_for = path
            return
        self.open_btn.setEnabled(True)
        last = git_out(path, "log", "-1", "--format=%ct").strip()
        self.last_label.setText(f"Letzter Commit: <b>{relative_time(int(last))}</b>" if last else "Noch keine Commits.")
        self.show_summary(path)
        self.stats_for = None
        self.load_stats()

    def show_summary(self, path):
        """Kennzahlen im Hintergrund sammeln (rev-list/shortlog über alle Commits können dauern)."""
        self.summary.setHtml(f"<p style='color:{COLORS['dim']}'>Lädt…</p>")

        def collect():
            g = lambda *a: git_out(path, *a).strip()
            return [
                ("Aktueller Branch", g("branch", "--show-current") or "(detached)"),
                ("Commits (alle Branches)", g("rev-list", "--count", "--all") or "0"),
                ("Autoren", str(len(g("shortlog", "-sn", "--all").splitlines()))),
                ("Branches", str(len(g("for-each-ref", "--format=x", "refs/heads").splitlines()))),
                ("Tags", str(len(g("for-each-ref", "--format=x", "refs/tags").splitlines()))),
                ("Remote origin", g("remote", "get-url", "origin") or "–"),
                ("Lokale Änderungen", f"{len(g('status', '--porcelain').splitlines())} Datei(en)"),
                ("Erster Commit", g("log", "--max-parents=0", "--format=%cd", "--date=format:%d.%m.%Y", "-1") or "–"),
            ]

        def show(rows):
            if rows is None or path != self.current:  # inzwischen ein anderes Repo gewählt
                return
            dim, e = COLORS["dim"], html.escape
            self.summary.setHtml("<table cellspacing='8'>" + "".join(
                f"<tr><td style='color:{dim}'>{e(k)}</td><td><b>{e(v)}</b></td></tr>" for k, v in rows) + "</table>")

        Background(self, collect, show)

    def fill_stats_table(self, months, series):
        """Monate als Zeilen (neueste oben), Autoren als Spalten, dazu die Summe."""
        t = self.stats_table
        t.clear()
        t.setHeaderLabels(["Monat", *[name for name, _ in series], "Summe"])
        items = []
        for i in reversed(range(len(months))):
            y, m = months[i].split("-")
            counts = [c[i] for _, c in series]
            it = QTreeWidgetItem([f"{MONTHS[int(m) - 1]} {y}", *map(str, counts), str(sum(counts))])
            for col in range(1, len(series) + 2):
                it.setTextAlignment(col, Qt.AlignRight)
            items.append(it)
        t.addTopLevelItems(items)
        for col in range(len(series) + 2):
            t.resizeColumnToContents(col)

    def load_stats(self):
        """Statistik erst berechnen, wenn der Tab sichtbar ist (git log über alle Commits)."""
        if self.pages.currentIndex() != 1 or not self.current or self.stats_for == self.current:
            return
        self.stats_for = path = self.current
        self.chart.set_data([], [], message="Lädt…")
        self.stats_table.clear()

        def compute():
            out = git_out(path, "log", "--all", "--no-merges", "--format=%aN%x1f%ad", "--date=format:%Y-%m")
            return monthly_series([tuple(line.split("\x1f", 1)) for line in out.splitlines() if "\x1f" in line])

        def show(result):
            if result is None or path != self.current:
                return
            self.chart.set_data(*result)
            self.fill_stats_table(*result)

        Background(self, compute, show)
