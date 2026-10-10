"""Gemeinsame Test-Helfer: isolierte Umgebung, echte Git-Repos in Temp-Ordnern, Qt ohne Bildschirm.

Muss vor gitgui importiert werden – es setzt Umgebungsvariablen, die gitgui beim Import liest.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

# Isolation: eigener Einstellungsordner, keine globale/systemweite Git-Konfiguration, Qt ohne Bildschirm
_CONFIG = tempfile.mkdtemp(prefix="gitgui-tests-")
open(os.path.join(_CONFIG, "gitconfig"), "w").close()
os.environ.update({
    "QT_QPA_PLATFORM": "offscreen", "XDG_CONFIG_HOME": _CONFIG, "GIT_CONFIG_GLOBAL": os.path.join(_CONFIG, "gitconfig"),
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox  # noqa: E402

from gitgui import manager, repotab  # noqa: E402
from gitgui.theme import setup_app  # noqa: E402


def git(repo, *args, input=None):
    """git im Test (unabhängig von der GUI); bricht bei Fehlern ab."""
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True, input=input).stdout


def make_repo(path, branch="main"):
    os.makedirs(path, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    return path


def commit(repo, message, **files):
    """Dateien schreiben (Name -> Inhalt; Punkte im Namen als __ schreiben) und committen."""
    for name, content in files.items():
        full = os.path.join(repo, name.replace("__", "."))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


def write(repo, name, content):
    with open(os.path.join(repo, name), "w") as f:
        f.write(content)


class FakeMenu(QMenu):
    """Kontextmenüs nicht anzeigen, sondern für den Test merken."""
    last = None

    def exec(self, *args):
        FakeMenu.last = self

    @classmethod
    def actions_by_text(cls):
        found = {}
        for a in cls.last.actions():
            if a.menu():
                found.update({f"{a.text()} > {s.text()}": s for s in a.menu().actions()})
            elif a.text():
                found[a.text()] = a
        return found


class GuiTestCase(unittest.TestCase):
    """Basis für GUI-Tests: Dialoge beantworten sich selbst, Meldungen werden mitgeschrieben."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        setup_app(cls.app)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gitgui-repo-")
        self.addCleanup(self.tmp.cleanup)
        QSettings("git_gui", "git_gui").clear()
        self.answers, self.messages, self.confirm = [], [], True
        patches = {
            (QMessageBox, "exec"): lambda box: self.messages.append(box.text()),
            (QMessageBox, "question"): staticmethod(
                lambda *a, **k: QMessageBox.Yes if self.confirm else QMessageBox.No),
            (QMessageBox, "information"): staticmethod(lambda parent, title, text, *a: self.messages.append(text)),
            (QMessageBox, "warning"): staticmethod(lambda parent, title, text, *a: self.messages.append(text)),
            (QInputDialog, "getText"): staticmethod(lambda *a, **k: (self.answers.pop(0), True)),
            (repotab, "QMenu"): FakeMenu,
            (manager, "QMenu"): FakeMenu,
        }
        for (owner, name), value in patches.items():
            old = owner.__dict__.get(name, getattr(owner, name))
            setattr(owner, name, value)
            self.addCleanup(setattr, owner, name, old)
        self.addCleanup(self.close_windows)

    def close_windows(self):
        for w in QApplication.topLevelWidgets():
            w.close()
            w.deleteLater()
        self.app.processEvents()

    def path(self, *parts):
        return os.path.join(self.tmp.name, *parts)

    def wait(self, condition, timeout=15):
        """Ereignisse verarbeiten, bis condition() wahr ist (für Hintergrund-Aufgaben)."""
        end = time.time() + timeout
        while not condition():
            if time.time() > end:
                self.fail("Zeitüberschreitung beim Warten")
            self.app.processEvents()
            time.sleep(0.01)

    def window(self, *repos):
        from gitgui.mainwindow import MainWindow
        w = MainWindow(list(repos))
        w.resize(1200, 800)
        w.show()
        return w
