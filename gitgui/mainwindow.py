"""Hauptfenster mit Toolbar, Menüs und einem Tab pro Repository."""
import html
import os
import shutil
import subprocess
import time

from PySide6.QtCore import QSettings, QTimer, Qt

from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QShortcut

from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMenu, QMessageBox,
    QProgressBar, QSizePolicy, QTabWidget, QToolBar, QToolButton, QWidget,
)

from .theme import COLORS, apply_theme
from .core import repo_root, view_option
from .repotab import RepoTab
from .manager import RepoManager


def open_terminal(path):
    """Startet ein Terminal im Repo-Ordner; Rückgabe False, wenn keins gefunden wurde."""
    for term in (os.environ.get("TERMINAL"), "konsole", "kgx", "gnome-terminal", "kitty", "alacritty",
                 "foot", "wezterm", "xterm"):
        if term and shutil.which(term):
            subprocess.Popen([term], cwd=path, start_new_session=True)
            return True
    return False


class MainWindow(QMainWindow):
    """Hauptfenster: Toolbar oben, darunter ein Tab pro Repository; offene Tabs werden gemerkt."""

    def __init__(self, paths):
        super().__init__()
        self.settings = QSettings("git_gui", "git_gui")
        self.tabs = QTabWidget(objectName="repos", documentMode=True, tabsClosable=True, movable=True)
        self.tabs.tabBar().setExpanding(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        plus = QToolButton(text="+", autoRaise=True, toolTip="Neuer Tab: Repository-Verwaltung (Strg+T)")
        plus.clicked.connect(self.show_manager)
        self.tabs.tabBar().tabMoved.connect(lambda *_: self.save_session())
        self.tabs.setCornerWidget(plus, Qt.TopRightCorner)

        # Aktionen: einmal definiert, in Toolbar und Menü benutzt
        def action(text, icon, slot, shortcut=None, on_tab=True):
            a = QAction(QIcon.fromTheme(icon), text, self)
            if on_tab:  # wirkt auf das Repo im aktiven Tab
                a.triggered.connect(lambda: isinstance(self.tabs.currentWidget(), RepoTab)
                                    and slot(self.tabs.currentWidget()))
            else:
                a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            return a

        a_open = action("Öffnen", "folder-open", self.open_dialog, "Ctrl+O", on_tab=False)
        a_fetch = action("Fetch", "view-refresh", lambda t: t.act_async("fetch", "--all", "--prune"))
        a_pull = action("Pull", "vcs-pull", lambda t: t.pull())
        a_push = action("Push", "vcs-push", lambda t: t.push())
        a_pull_merge = action("Pull (Merge)", "vcs-pull", lambda t: t.pull(rebase=False))
        a_pull_rebase = action("Pull (Rebase)", "vcs-pull", lambda t: t.pull(rebase=True))
        a_push_force = action("Push erzwingen (--force-with-lease)…", "vcs-push", lambda t: t.push(force=True))
        self.a_rebase_default = QAction("Standardmäßig mit Rebase pullen", self, checkable=True,
                                        checked=self.settings.value("pull_rebase", False, type=bool))
        self.a_rebase_default.toggled.connect(lambda on: self.settings.setValue("pull_rebase", on))
        a_stash = action("Stash", "vcs-stash", lambda t: t.stash())
        a_pop = action("Stash Pop", "vcs-stash-pop", lambda t: t.act("stash", "pop"))
        a_branch = action("Neuer Branch", "vcs-branch", lambda t: t.new_branch())
        a_term = action("Terminal", "utilities-terminal", self.terminal)
        a_refresh = action("Aktualisieren", "view-refresh", lambda t: t.refresh(), "F5")
        a_close = action("Tab schließen", "tab-close", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W",
                         on_tab=False)
        self.repo_actions = [a_fetch, a_pull, a_push, a_stash, a_pop, a_branch, a_term, a_refresh,
                             a_pull_merge, a_pull_rebase, a_push_force]
        self.a_pull, self.a_push = a_pull, a_push

        menu = self.menuBar().addMenu("Datei")
        menu.addAction(a_open)
        menu.addAction(a_close)
        menu.addSeparator()
        menu.addAction("Beenden", QKeySequence("Ctrl+Q"), self.close)
        menu = self.menuBar().addMenu("Repository")
        for a in (a_fetch, a_pull, a_pull_merge, a_pull_rebase, self.a_rebase_default, None, a_push, a_push_force, None,
                  a_stash, a_pop, None, a_branch, a_term, None, a_refresh):
            menu.addSeparator() if a is None else menu.addAction(a)

        menu.addSeparator()
        self.a_autofetch = QAction("Automatisch fetchen (alle 5 Minuten)", self, checkable=True,
                                   checked=self.settings.value("auto_fetch", True, type=bool))
        self.a_autofetch.toggled.connect(lambda on: self.settings.setValue("auto_fetch", on))
        menu.addAction(self.a_autofetch)
        self.fetch_timer = QTimer(self, interval=5 * 60 * 1000)
        self.fetch_timer.timeout.connect(self.auto_fetch)
        self.fetch_timer.start()
        # Zurück ins Fenster: Arbeitsdateien können sich geändert haben (die überwacht QFileSystemWatcher nicht)
        QApplication.instance().applicationStateChanged.connect(
            lambda state: state == Qt.ApplicationActive and isinstance(self.tabs.currentWidget(), RepoTab)
            and time.time() - self.tabs.currentWidget().last_refresh > 2 and self.tabs.currentWidget().refresh())

        menu = self.menuBar().addMenu("Ansicht")
        self.view_actions = []
        for key, text, tip in (("ignore_ws", "Leerzeichen ignorieren", "Leerzeichen-Änderungen im Diff ignorieren"),
                               ("split_diff", "Nebeneinander", "Diff als alt | neu nebeneinander zeigen")):
            a = QAction(text, self, checkable=True, checked=view_option(key), toolTip=tip)
            a.toggled.connect(lambda on, key=key: self.set_view_option(key, on))
            menu.addAction(a)
            self.view_actions.append(a)
        menu.addSeparator()
        design = menu.addMenu("Design")
        group = QActionGroup(self)
        current = self.settings.value("theme", "dark")
        for key, label in (("system", "Wie das System"), ("dark", "Dunkel"), ("light", "Hell")):
            a = group.addAction(QAction(label, self, checkable=True, checked=key == current))
            a.triggered.connect(lambda _on, key=key: self.set_theme(key))
            design.addAction(a)
        # „Wie das System“ soll auch einem späteren Umschalten in den Systemeinstellungen folgen
        QApplication.styleHints().colorSchemeChanged.connect(
            lambda _scheme: self.settings.value("theme", "dark") == "system" and self.set_theme("system"))

        tb = QToolBar(objectName="main", movable=False, floatable=False)
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.toggleViewAction().setVisible(False)
        self.addToolBar(tb)
        tb.addAction(a_open)
        tb.addAction(a_fetch)

        def split_button(main, *extra):
            """Toolbar-Knopf mit kleinem Pfeil für weitere Varianten (wie Stash/Pop bei Fork)."""
            btn = QToolButton(popupMode=QToolButton.MenuButtonPopup, toolButtonStyle=Qt.ToolButtonTextUnderIcon)
            btn.setDefaultAction(main)
            menu = QMenu(btn)
            for a in extra:
                menu.addAction(a)
            btn.setMenu(menu)
            tb.addWidget(btn)

        split_button(a_pull, a_pull_merge, a_pull_rebase, self.a_rebase_default)
        split_button(a_push, a_push_force)
        split_button(a_stash, a_pop)
        spacer = lambda: QWidget(sizePolicy=QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        tb.addWidget(spacer())
        self.repo_info = QLabel(objectName="repoInfo", alignment=Qt.AlignCenter)
        self.busy = QProgressBar(minimum=0, maximum=0, maximumWidth=140, maximumHeight=12, textVisible=False)
        self.busy_label = QLabel()
        self.statusBar().addPermanentWidget(self.busy_label)
        self.statusBar().addPermanentWidget(self.busy)
        self.busy.hide()
        tb.addWidget(self.repo_info)
        tb.addWidget(spacer())
        tb.addAction(a_branch)
        tb.addAction(a_term)

        self.setCentralWidget(self.tabs)
        self.resize(1300, 820)

        for key, slot in (("Ctrl+T", self.show_manager),
                          ("Ctrl+Tab", lambda: self.step(1)), ("Ctrl+Shift+Tab", lambda: self.step(-1))):
            QShortcut(QKeySequence(key), self, slot)

        if not paths:  # Sitzung vom letzten Mal wiederherstellen
            paths = self.settings.value("repos", [], type=list)
            current = self.settings.value("current", 0, type=int)
        else:
            current = 0
        self.restoring = True  # beim Wiederherstellen nicht bei jedem Tab speichern
        for path in paths:
            self.add_repo(path, quiet=True)
        self.restoring = False
        if self.tabs.count():
            self.tabs.setCurrentIndex(min(current, self.tabs.count() - 1))
        else:
            self.show_manager()
        self.update_page()

    def repo_tabs(self):
        return [w for w in map(self.tabs.widget, range(self.tabs.count())) if isinstance(w, RepoTab)]

    def save_session(self):
        """Offene Repos sofort merken – so bleiben sie auch nach Absturz oder kill offen."""
        if self.restoring:
            return
        tabs = self.repo_tabs()
        self.settings.setValue("repos", [t.repo for t in tabs])
        cur = self.tabs.currentWidget()
        self.settings.setValue("current", tabs.index(cur) if cur in tabs else 0)

    def show_manager(self):
        """Repository-Verwaltung als „Neuer Tab“ (gibt es höchstens einmal)."""
        for i in range(self.tabs.count()):
            if isinstance(self.tabs.widget(i), RepoManager):
                return self.tabs.setCurrentIndex(i)
        manager = RepoManager(self.settings)
        manager.open_requested.connect(self.add_repo)
        self.tabs.setCurrentIndex(self.tabs.addTab(manager, "Neuer Tab"))

    def add_repo(self, path, quiet=False):
        root = repo_root(path)
        if not root:
            if not quiet:
                QMessageBox.warning(self, "Kein Git-Repo", f"{path} ist kein Git-Repository.")
            return
        recent = self.settings.value("recent", [], type=list)
        self.settings.setValue("recent", [root] + [r for r in recent if r != root][:9])
        known = self.settings.value("known", [], type=list)
        if root not in known:
            self.settings.setValue("known", known + [root])
        for tab in self.repo_tabs():  # schon offen -> nur hinwechseln
            if tab.repo == root:
                return self.tabs.setCurrentWidget(tab)
        # Ein offener „Neuer Tab“ wird durch das Repo ersetzt, wie in Fork
        manager = next((w for w in map(self.tabs.widget, range(self.tabs.count())) if isinstance(w, RepoManager)), None)
        tab = RepoTab(root)
        tab.add_view_buttons(self.view_actions)
        tab.changed.connect(lambda t=tab: self.update_titles(t))
        i = self.tabs.insertTab(self.tabs.indexOf(manager) if manager else self.tabs.count(), tab, tab.name)
        self.tabs.setTabToolTip(i, root)
        if manager:
            self.tabs.removeTab(self.tabs.indexOf(manager))
            manager.deleteLater()
        self.tabs.setCurrentWidget(tab)
        self.update_titles(tab)
        self.update_page()
        self.save_session()

    def auto_fetch(self):
        """Alle offenen Repos mit Remote still im Hintergrund fetchen, damit die Zähler an Pull/Push stimmen."""
        if not self.a_autofetch.isChecked():
            return
        for tab in self.repo_tabs():
            if tab.git("remote").strip():
                tab.act_async("fetch", "--all", "--prune", quiet=True)

    def set_theme(self, name):
        """Design umschalten und alles neu zeichnen, was Farben fest in Inhalte geschrieben hat."""
        self.settings.setValue("theme", name)
        apply_theme(QApplication.instance(), name)
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, RepoTab):
                tab.refresh()
                tab.rerender_diffs()
            else:
                tab.reload()
        self.update_page()
        current = self.tabs.currentWidget()
        if isinstance(current, RepoTab):
            self.update_titles(current)

    def set_view_option(self, key, on):
        self.settings.setValue(key, on)
        for tab in self.repo_tabs():
            tab.rerender_diffs()

    def open_dialog(self):
        path = QFileDialog.getExistingDirectory(self, "Repository öffnen")
        if path:
            self.add_repo(path)

    def terminal(self, tab):
        if not open_terminal(tab.repo):
            QMessageBox.information(self, "Terminal", "Kein Terminal gefunden. Setze die Variable $TERMINAL.")

    def stop_running(self, tabs):
        """Fragt nach, wenn in `tabs` noch Push/Pull laufen, und bricht sie ggf. ab. False = nicht schließen."""
        running = [t for t in tabs if t.proc]
        if not running:
            return True
        names = ", ".join(f"git {t.proc_label} ({t.name})" for t in running)
        if not self.ask("Läuft noch", f"Es läuft noch: {names}.\nTrotzdem schließen und abbrechen?"):
            return False
        for t in running:
            t.proc.finished.disconnect()
            t.proc.kill()
            t.proc.waitForFinished(2000)
            t.proc = None
        return True

    def ask(self, title, text):
        return QMessageBox.question(self, title, text) == QMessageBox.Yes

    def close_tab(self, i):
        if i >= 0:
            tab = self.tabs.widget(i)
            if isinstance(tab, RepoTab) and not self.stop_running([tab]):
                return
            self.tabs.removeTab(i)
            tab.deleteLater()
            if not self.tabs.count():  # letzter Tab zu: Verwaltung zeigen
                self.show_manager()
            self.update_page()
            self.save_session()

    def step(self, d):
        if self.tabs.count():
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + d) % self.tabs.count())

    def on_tab_changed(self, i):
        tab = self.tabs.widget(i)
        if isinstance(tab, RepoTab):
            tab.refresh()  # Repo kann sich draußen geändert haben
            self.update_titles(tab)
        elif isinstance(tab, RepoManager):
            tab.reload()  # „Zuletzt geöffnet“ kann sich geändert haben
        self.update_page()
        self.save_session()

    def update_titles(self, tab):
        i = self.tabs.indexOf(tab)
        if i >= 0:
            self.tabs.setTabText(i, tab.name + ("  ⚠" if tab.op else "") + ("  ⟳" if tab.proc else ""))
        if tab is self.tabs.currentWidget():
            self.busy.setVisible(bool(tab.proc))
            self.busy_label.setText(f"git {tab.proc_label} läuft…" if tab.proc else "")
            self.setWindowTitle(f"{tab.name} — Git GUI")
            self.repo_info.setText(f"<b style='font-size:11pt'>{html.escape(tab.name)}</b><br>"
                                   f"<span style='color:{COLORS['dim']}'>⑂ {html.escape(tab.branch)}</span>")
            ahead, behind = tab.ahead_behind or (0, 0)
            self.a_pull.setText(f"Pull ↓{behind}" if behind else "Pull")
            self.a_push.setText(f"Push ↑{ahead}" if ahead else "Push")
            self.a_pull.setToolTip(f"{behind} Commit(s) auf dem Remote, die du noch nicht hast" if behind else "Pull")
            self.a_push.setToolTip(f"{ahead} lokale(r) Commit(s), noch nicht gepusht" if ahead else "Push")

    def update_page(self):
        """Toolbar nur für Repo-Tabs aktiv; im „Neuer Tab“ eine Begrüßung statt Repo/Branch."""
        is_repo = isinstance(self.tabs.currentWidget(), RepoTab)
        for a in self.repo_actions:
            a.setEnabled(is_repo)
        if not is_repo:
            self.a_pull.setText("Pull")
            self.a_push.setText("Push")
            self.setWindowTitle("Git GUI")
            self.repo_info.setText(f"<b style='font-size:11pt'>Willkommen!</b><br>"
                                   f"<span style='color:{COLORS['dim']}'>Öffne ein Repository</span>")
            self.busy.hide()
            self.busy_label.clear()

    def closeEvent(self, event):
        if not self.stop_running(self.repo_tabs()):
            return event.ignore()
        self.save_session()
        super().closeEvent(event)
