"""Abläufe in der Oberfläche mit echten Git-Repos (Qt ohne Bildschirm, Dialoge beantworten sich selbst)."""
import base64
import functools
import http.server
import os
import shlex
import subprocess
import sys
import threading
import time
import unittest

from tests.helpers import FakeMenu, GuiTestCase, commit, git, make_repo, write
from PySide6.QtCore import QPoint, QSettings, QUrl, Qt

from gitgui.core import GIT_ENV, split_hunks
from gitgui.dialogs import ConflictDialog, FileHistoryDialog, RebaseDialog
from gitgui.manager import RepoManager
from gitgui.repotab import LOG_PAGE, RepoTab
from gitgui.theme import COLORS
from gitgui.widgets import EXTRA_ROLE, NODE_ROLE


def item_named(tree, text, parent=None):
    """Erstes Element mit genau diesem Text (optional unter einem Elternknoten mit diesem Text)."""
    for it in tree.findItems(text, Qt.MatchExactly | Qt.MatchRecursive):
        if parent is None or (it.parent() and it.parent().text(0) == parent):
            return it
    raise AssertionError(f"{text!r} nicht gefunden")


class StagingTest(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.path("r"))
        commit(self.repo, "init", f__txt="".join(f"{i}\n" for i in range(1, 31)), nonl__txt="x\ny")
        self.win = self.window(self.repo)
        self.tab = self.win.tabs.currentWidget()

    def select(self, widget, name):
        widget.setCurrentItem(widget.findItems(name, Qt.MatchExactly)[0])

    def index(self, name):
        return git(self.repo, "show", f":{name}")

    def test_stage_single_hunk(self):
        write(self.repo, "f.txt", "".join(f"{i}\n" for i in range(1, 31)).replace("3\n", "drei\n", 1).replace("25\n", "X\n"))
        self.tab.refresh()
        self.select(self.tab.unstaged, "f.txt")
        self.assertEqual(len(split_hunks(self.tab.diff_ctx[2])[1]), 2)
        self.tab.on_hunk(QUrl("hunk:0"))
        cached = git(self.repo, "diff", "--cached")
        self.assertIn("+drei", cached)
        self.assertNotIn("+X", cached)
        self.assertEqual(self.tab.diff_ctx[:2], ("f.txt", False))  # Auswahl bleibt erhalten

    def test_stage_and_unstage_lines(self):
        write(self.repo, "f.txt", "1\nB1\nB2\n" + "".join(f"{i}\n" for i in range(3, 31)))
        self.tab.refresh()
        self.select(self.tab.unstaged, "f.txt")
        self.tab.on_hunk(QUrl("line:0:3"))  # -2 bleibt, nur +B1 und (per Umschalt) +B2
        self.tab.sel_lines.add((0, 4))
        self.tab.apply_lines()
        self.assertEqual(self.index("f.txt").split()[:5], ["1", "2", "B1", "B2", "3"])
        self.select(self.tab.staged, "f.txt")
        self.tab.on_hunk(QUrl("line:0:3"))  # +B1 wieder unstagen (Zeile 1 und 2 sind Kontext)
        self.tab.apply_lines()
        self.assertEqual(self.index("f.txt").split()[:4], ["1", "2", "B2", "3"])

    def test_stage_line_without_newline_at_eof(self):
        write(self.repo, "nonl.txt", "x\nY")
        self.tab.refresh()
        self.select(self.tab.unstaged, "nonl.txt")
        self.tab.on_hunk(QUrl("line:0:4"))  # nur +Y
        self.tab.apply_lines()
        self.assertEqual(self.index("nonl.txt"), "x\ny\nY")

    def test_commit_amend_and_discard(self):
        write(self.repo, "neu.txt", "n\n")
        write(self.repo, "f.txt", "anders\n")
        self.tab.refresh()
        self.tab.stage(["neu.txt"])
        self.tab.subject.setText("Neue Datei")
        self.tab.body.setPlainText("Beschreibung")
        self.tab.commit()
        self.assertEqual(git(self.repo, "log", "-1", "--format=%B").strip(), "Neue Datei\n\nBeschreibung")
        self.tab.amend.setChecked(True)
        self.assertEqual(self.tab.subject.text(), "Neue Datei")  # Amend übernimmt die alte Nachricht
        self.tab.subject.setText("Neue Datei (geändert)")
        self.tab.commit()
        self.assertEqual(git(self.repo, "log", "--format=%s").split("\n")[:2], ["Neue Datei (geändert)", "init"])
        self.tab.discard(["f.txt"])
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    def test_view_options_disable_staging(self):
        write(self.repo, "f.txt", "  1\n" + "".join(f"{i}\n" for i in range(2, 31)))
        self.tab.refresh()
        self.select(self.tab.unstaged, "f.txt")
        self.assertTrue(any(self.tab.diff.rowmap))
        ws, split = self.win.view_actions
        ws.setChecked(True)  # nur Leerzeichen geändert -> leerer Diff, kein Stagen
        self.assertNotIn("hunk:", self.tab.diff.toHtml())
        self.assertFalse(any(self.tab.diff.rowmap))
        ws.setChecked(False)
        split.setChecked(True)
        self.assertIn("hunk:", self.tab.diff.toHtml())
        self.assertFalse(any(self.tab.diff.rowmap))
        split.setChecked(False)


class HistoryTest(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.path("r"))
        commit(self.repo, "init", t__txt="a\nb\nc\n")
        git(self.repo, "switch", "-q", "-c", "feature")
        commit(self.repo, "Neue Datei", neu__txt="n\n")
        commit(self.repo, "b ändern (feature)", t__txt="a\nB-feature\nc\n")
        git(self.repo, "switch", "-q", "main")
        commit(self.repo, "b ändern (main)", t__txt="a\nB-main\nc\n")
        self.win = self.window(self.repo)
        self.tab = self.win.tabs.currentWidget()
        self.tab.view = ("log", "--all", "all")
        self.tab.render_view()

    def menu_for(self, subject):
        self.tab.render_view()
        log = self.tab.log
        item = next(log.topLevelItem(i) for i in range(log.topLevelItemCount()) if log.topLevelItem(i).text(0) == subject)
        log.scrollToItem(item)
        self.tab.log_menu(log.visualItemRect(item).center())
        return FakeMenu.actions_by_text()

    def subjects(self, ref="main"):
        return git(self.repo, "log", "--format=%s", ref).split("\n")[:-1]

    def test_cherry_pick_with_conflict_and_continue(self):
        self.assertFalse(self.menu_for("init")["Cherry-Pick (schon im aktuellen Branch)"].isEnabled())
        self.menu_for("Neue Datei")["Cherry-Pick auf „main“…"].trigger()
        self.assertEqual(self.subjects()[0], "Neue Datei")
        self.menu_for("b ändern (feature)")["Cherry-Pick auf „main“…"].trigger()
        self.assertEqual(self.tab.op, "cherry-pick")
        self.assertEqual(self.messages, [])  # Konflikt: Banner statt Fehlerdialog
        dialog = ConflictDialog(self.tab, "t.txt")
        dialog.blocks[0][0].buttons()[1].click()  # Seite „feature“
        dialog.save()
        self.tab.act(self.tab.op, "--continue")
        self.assertIsNone(self.tab.op)
        self.assertEqual(open(os.path.join(self.repo, "t.txt")).read(), "a\nB-feature\nc\n")

    def test_revert_only_for_commits_in_branch(self):
        self.assertFalse(self.menu_for("Neue Datei")["Revert (nicht im aktuellen Branch)"].isEnabled())
        commit(self.repo, "x hinzufügen", x__txt="x\n")
        self.menu_for("x hinzufügen")["Commit rückgängig machen (Revert)…"].trigger()
        self.assertEqual(self.subjects()[0], 'Revert "x hinzufügen"')
        self.assertFalse(os.path.exists(os.path.join(self.repo, "x.txt")))

    def test_branch_tag_reset_from_commit_menu(self):
        self.answers += ["von-init"]
        self.menu_for("init")["Branch hier erstellen…"].trigger()
        self.assertEqual(self.tab.branch, "von-init")
        git(self.repo, "switch", "-q", "main")
        self.answers += ["v1", "Release"]
        self.menu_for("init")["Tag hier erstellen…"].trigger()
        self.assertEqual(git(self.repo, "cat-file", "-t", "v1").strip(), "tag")
        write(self.repo, "t.txt", "lokal\n")
        self.menu_for("init")["„main“ hierhin zurücksetzen > Hard – alle Änderungen verwerfen…"].trigger()
        self.assertEqual(self.subjects(), ["init"])
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    def test_interactive_rebase(self):
        for i in range(1, 5):
            commit(self.repo, f"c{i}", **{f"f{i}__txt": f"{i}\n"})
        start = git(self.repo, "log", "--format=%H", "--grep=^c1$", "main").split()[0]
        dialog = RebaseDialog(self.tab, start)
        rows = {dialog.list.topLevelItem(i).text(2): dialog.list.topLevelItem(i) for i in range(4)}
        for subject, action in (("c1", "drop"), ("c3", "squash")):
            combo = dialog.list.itemWidget(rows[subject], 0)
            combo.setCurrentIndex(combo.findData(action))
        rows["c2"].setText(2, "c2 umbenannt")
        self.assertEqual(dialog.action(rows["c2"]), "reword")  # Tippen stellt automatisch auf reword
        dialog.list.setCurrentItem(rows["c4"])
        dialog.move(-1)
        dialog.move(-1)  # c4 vor c2
        dialog.start()
        self.assertEqual(self.subjects()[:3], ["c2 umbenannt", "c4", "b ändern (main)"])
        self.assertEqual(git(self.repo, "log", "-1", "--format=%B").strip(), "c2 umbenannt\n\nc3")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "f1.txt")))

    def test_stash_roundtrip(self):
        write(self.repo, "t.txt", "geändert\n")
        write(self.repo, "neu2.txt", "neu\n")
        self.tab.refresh()
        self.answers.append("wip")
        self.tab.stash()
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(self.tab.refs_stash(), [["stash@{0}", "On main: wip"]])
        self.tab.act("stash", "pop")
        self.assertIn("neu2.txt", git(self.repo, "status", "--porcelain"))

    def test_file_history_follows_rename(self):
        git(self.repo, "mv", "t.txt", "u.txt")
        commit(self.repo, "umbenennen")
        commit(self.repo, "u ändern", u__txt="a\nB-main\nc\nd\n")
        dialog = FileHistoryDialog(self.tab, "u.txt")
        entries = [(dialog.commits.topLevelItem(i).text(0), dialog.commits.topLevelItem(i).data(0, Qt.UserRole)[1])
                   for i in range(dialog.commits.topLevelItemCount())]
        self.assertEqual(entries, [("u ändern", "u.txt"), ("umbenennen", "u.txt"),
                                   ("b ändern (main)", "t.txt"), ("init", "t.txt")])
        dialog.views.setCurrentIndex(1)  # Blame
        self.assertIn("d", dialog.blame.toPlainText())


class BranchTest(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.path("r"))
        commit(self.repo, "init", a__txt="a\n")
        git(self.repo, "branch", "feature/x")
        commit(self.repo, "main weiter", a__txt="b\n")
        self.win = self.window(self.repo)
        self.tab = self.win.tabs.currentWidget()

    def menu(self, text, parent):
        item = item_named(self.tab.sidebar, text, parent)
        self.tab.sidebar.scrollToItem(item)
        self.tab.sidebar_menu(self.tab.sidebar.visualItemRect(item).center())
        return FakeMenu.actions_by_text()

    def test_star_and_graph_filter_follow_rename_and_delete(self):
        self.menu("x", "feature")["Zu Favoriten hinzufügen"].trigger()
        self.menu("x", "feature")["Im Graph filtern (nur gefilterte zeigen)"].trigger()
        self.assertEqual(item_named(self.tab.sidebar, "feature/x", "Favoriten").text(0), "feature/x")
        self.assertEqual(self.tab.log.topLevelItemCount(), 1)  # nur feature/x im Graph
        self.assertTrue(self.tab.graph_bar.isVisible())
        self.answers.append("feature/y")
        self.menu("x", "feature")["Umbenennen…"].trigger()
        self.assertEqual(self.tab.graph_filter(), (["refs/heads/feature/y"], []))
        self.menu("y", "feature")["Löschen…"].trigger()
        self.assertEqual(self.tab.graph_filter(), ([], []))
        self.assertNotIn("Favoriten", [self.tab.sidebar.topLevelItem(i).text(0)
                                       for i in range(self.tab.sidebar.topLevelItemCount())])

    def test_merge_conflict_banner(self):
        git(self.repo, "switch", "-q", "feature/x")
        commit(self.repo, "x ändert a", a__txt="x\n")
        git(self.repo, "switch", "-q", "main")
        self.tab.refresh()
        self.menu("x", "feature")["„feature/x“ in „main“ mergen"].trigger()
        self.assertEqual((self.tab.op, self.tab.n_conflicts), ("merge", 1))
        self.assertTrue(self.tab.banner.isVisible())
        self.assertIn("⚠", self.win.tabs.tabText(0))
        self.assertEqual(self.messages, [])


class LogFilterTest(GuiTestCase):
    def test_paging_and_search_in_older_commits(self):
        repo = make_repo(self.path("big"))
        stream = []
        for i in range(LOG_PAGE + 300):
            msg = f"Commit {i}" + ("\n\nSPEZIALWORT im Text" if i == 5 else "")
            stream.append(f"commit refs/heads/main\nmark :{i + 1}\nauthor Dev <d@x> {1600000000 + i} +0000\n"
                          f"committer Dev <d@x> {1600000000 + i} +0000\ndata {len(msg.encode())}\n{msg}\n"
                          + (f"from :{i}\n" if i else "") + f"M 644 inline f.txt\ndata {len(str(i)) + 1}\n{i}\n\n")
        stream.append("tag uralt\nfrom :3\ntagger Dev <d@x> 1600000000 +0000\ndata 1\nx\n")
        subprocess.run(["git", "-C", repo, "fast-import", "--quiet"], input="".join(stream), text=True, check=True)
        git(repo, "checkout", "-q", "main")
        win = self.window(repo)
        tab = win.tabs.currentWidget()
        tab.view = ("log", "--all", "all")
        tab.render_view()
        self.assertEqual(tab.log.topLevelItemCount(), LOG_PAGE)
        bar = tab.log.verticalScrollBar()
        bar.setValue(bar.maximum())  # ans Ende scrollen lädt nach
        self.assertEqual(tab.log.topLevelItemCount(), LOG_PAGE + 300)
        tab.log_limit = LOG_PAGE
        tab.render_view()
        for text, expected in (("uralt", "Commit 2"), ("spezialwort", "Commit 5")):
            tab.log_filter.setText(text)
            self.wait(lambda: any(tab.log.topLevelItem(i).data(0, EXTRA_ROLE) for i in range(tab.log.topLevelItemCount())))
            visible = [tab.log.topLevelItem(i).text(0) for i in range(tab.log.topLevelItemCount())
                       if not tab.log.topLevelItem(i).isHidden()]
            self.assertEqual(visible, [expected])


class RemoteTest(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.remote = self.path("remote.git")
        git(self.tmp.name, "init", "-q", "--bare", "-b", "main", self.remote)
        self.repo = make_repo(self.path("r"))
        git(self.repo, "remote", "add", "origin", self.remote)
        commit(self.repo, "init", a__txt="a\n")
        git(self.repo, "push", "-q", "-u", "origin", "main")
        other = self.path("other")
        git(self.tmp.name, "clone", "-q", "-b", "main", self.remote, other)
        commit(other, "von anderswo", o__txt="o\n")
        git(other, "push", "-q")
        commit(self.repo, "lokal", m__txt="m\n")
        self.win = self.window(self.repo)
        self.tab = self.win.tabs.currentWidget()

    def run_async(self, func):
        func()
        self.wait(lambda: not self.tab.proc)

    def test_counters_pull_rebase_and_force_with_lease(self):
        self.run_async(lambda: self.tab.act_async("fetch"))
        self.assertEqual((self.win.a_pull.text(), self.win.a_push.text()), ("Pull ↓1", "Push ↑1"))
        self.run_async(self.tab.push)
        self.assertTrue(self.messages[-1].startswith("Push abgelehnt"))  # verständliche Meldung
        self.run_async(lambda: self.tab.pull(rebase=True))
        self.assertEqual(git(self.repo, "log", "--format=%s").split("\n")[:3], ["lokal", "von anderswo", "init"])
        self.run_async(self.tab.push)
        self.tab.act("commit", "--amend", "-q", "-m", "lokal (amend)")
        self.run_async(lambda: self.tab.push(force=True))
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s", "origin/main").strip(), "lokal (amend)")

    def test_remote_management_and_tags(self):
        backup = self.path("backup.git")
        git(self.tmp.name, "init", "-q", "--bare", backup)
        self.answers += ["backup", backup]
        self.tab.add_remote()
        self.wait(lambda: not self.tab.proc)
        self.assertIn("Remotes/backup", [it.data(0, NODE_ROLE) for it in self.tab.sidebar.findItems(
            "", Qt.MatchContains | Qt.MatchRecursive)])
        self.answers.append("sicherung")
        self.tab.rename_remote("backup")
        self.tab.remove_remote("sicherung")
        self.assertEqual(git(self.repo, "remote").split(), ["origin"])
        self.answers += ["v1.0", ""]
        self.tab.create_tag(git(self.repo, "rev-parse", "HEAD").strip())
        self.run_async(lambda: self.tab.act_async("push", "origin", "--tags"))
        self.assertIn("refs/tags/v1.0", git(self.repo, "ls-remote", "--tags", "origin"))


class SshKeyTest(GuiTestCase):
    def test_program_wide_key_used_by_git_and_connection_test(self):
        from PySide6.QtWidgets import QFileDialog
        from gitgui.core import apply_ssh_key
        self.addCleanup(apply_ssh_key, None)
        repo = make_repo(self.path("r"))
        commit(repo, "init")
        git(repo, "remote", "add", "origin", "git@example.com:name/repo.git")
        git(repo, "remote", "add", "web", "https://example.com/name/repo.git")
        key = self.path("id test")  # Leerzeichen im Pfad: muss sauber gequotet werden
        for suffix in ("", ".pub"):
            write(self.tmp.name, f"id test{suffix}", "schlüssel")
        old = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (key + ".pub", ""))  # aus Versehen die .pub
        self.addCleanup(setattr, QFileDialog, "getOpenFileName", old)
        win = self.window(repo)
        win.choose_ssh_key()
        self.assertEqual(GIT_ENV["GIT_SSH_COMMAND"], f"ssh -i '{key}' -o IdentitiesOnly=yes")
        self.assertEqual(win.a_ssh_key.text(), "SSH-Schlüssel wählen… (aktuell: id test)")
        unset = subprocess.run(["git", "-C", repo, "config", "--get", "core.sshCommand"], capture_output=True)
        self.assertEqual(unset.returncode, 1)  # Repo-Konfiguration bleibt unberührt
        apply_ssh_key(None)
        self.assertEqual(self.window().ssh_key(), key)  # neues Fenster liest die Einstellung und setzt sie wieder
        self.assertEqual(GIT_ENV["GIT_SSH_COMMAND"], f"ssh -i '{key}' -o IdentitiesOnly=yes")
        # Stand-in für ssh, das die Argumente mitschreibt und wie GitHub antwortet
        fake = self.path("fake-ssh")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\necho "$*" >> "$(dirname "$0")/ssh-args"\n'
                    'echo "Hi test! You\'ve successfully authenticated, but there is no shell." >&2\nexit 1\n')
        os.chmod(fake, 0o755)
        GIT_ENV["GIT_SSH_COMMAND"] = f"{fake} -i '{key}' -o IdentitiesOnly=yes"
        tab = win.tabs.currentWidget()
        win.test_ssh()  # über das Menü: nimmt origin
        self.wait(lambda: self.messages)
        self.assertIn("Anmeldung klappt", self.messages[-1])
        tab.git("ls-remote", "origin")  # echter git-Aufruf der GUI benutzt denselben Schlüssel
        with open(self.path("ssh-args")) as f:
            calls = f.read().splitlines()
        self.assertTrue(calls[0].startswith(f"-i {key} -o IdentitiesOnly=yes -T"))
        self.assertTrue(calls[1].startswith(f"-i {key} -o IdentitiesOnly=yes"))
        self.assertIn("git@example.com", calls[1])
        tab.test_ssh("web")
        self.assertIn("keine SSH-Adresse", self.messages[-1])
        win.set_ssh_key(None)
        self.assertNotIn("GIT_SSH_COMMAND", GIT_ENV)
        self.assertFalse(win.a_ssh_clear.isEnabled())


class AutoRefreshTest(GuiTestCase):
    def test_external_commit_and_branch_switch(self):
        repo = make_repo(self.path("r"))
        commit(repo, "init")
        win = self.window(repo)
        tab = win.tabs.currentWidget()
        tab.view = ("log", "--all", "all")
        tab.render_view()
        self.wait(lambda: time.time() - tab.last_refresh > 1.2)
        commit(repo, "Commit aus dem Terminal")
        self.wait(lambda: tab.log.topLevelItem(0).text(0) == "Commit aus dem Terminal")
        git(repo, "switch", "-q", "-c", "neu")
        self.wait(lambda: tab.branch == "neu")


class ManagerTest(GuiTestCase):
    def test_folders_session_and_statistics(self):
        repos = [make_repo(self.path(n)) for n in ("a", "b")]
        for r in repos:
            commit(r, "init", x__txt="x\n")
        win = self.window()
        manager = win.tabs.currentWidget()
        self.assertIsInstance(manager, RepoManager)
        manager.remember(repos)
        self.answers.append("Arbeit")
        manager.new_folder(move=repos[0])
        self.assertEqual(manager.folder_data(), (["Arbeit"], {repos[0]: "Arbeit"}))
        manager.current = repos[0]
        manager.reload()
        manager.pages.setCurrentIndex(1)
        self.wait(lambda: bool(manager.chart.months))
        manager.open(repos[0])
        self.assertIsInstance(win.tabs.currentWidget(), RepoTab)
        win2 = self.window()  # neues Fenster ohne Schließen des alten: Sitzung ist trotzdem gespeichert
        self.assertEqual([win2.tabs.widget(i).repo for i in range(win2.tabs.count())], [repos[0]])

    def test_theme_switch(self):
        repo = make_repo(self.path("r"))
        commit(repo, "init")
        win = self.window(repo)
        win.set_theme("light")
        self.assertEqual(COLORS["base"], "#ffffff")
        self.assertEqual(self.app.palette().base().color().name(), "#ffffff")
        win.set_theme("dark")
        self.assertEqual(COLORS["base"], "#1f1f22")
        self.assertEqual(QSettings("git_gui", "git_gui").value("theme"), "dark")


class AskpassTest(GuiTestCase):
    def test_auto_fetch_never_asks_for_credentials(self):
        """Ein Remote, der eine Anmeldung verlangt: der automatische Fetch bleibt still, ein normaler fragt nach."""
        url = self.auth_server()
        repo = make_repo(self.path("r"))
        commit(repo, "init")
        git(repo, "remote", "add", "github", url)
        asked = self.path("asked")
        recorder = self.path("askpass-recorder.sh")
        with open(recorder, "w") as f:
            f.write(f'#!/bin/sh\necho "$*" >> {shlex.quote(asked)}\necho falsch\n')
        os.chmod(recorder, 0o755)
        old = GIT_ENV.get("GIT_ASKPASS")
        GIT_ENV["GIT_ASKPASS"] = recorder
        self.addCleanup(lambda: GIT_ENV.update(GIT_ASKPASS=old) if old else GIT_ENV.pop("GIT_ASKPASS", None))
        win = self.window(repo)
        tab = win.tabs.currentWidget()
        tab.act_async("fetch", "github", quiet=True)
        self.wait(lambda: not tab.proc)
        self.assertFalse(os.path.exists(asked))  # kein Anmeldedialog im Hintergrund
        self.assertIn("Automatischer Fetch", win.statusBar().currentMessage())
        self.assertEqual(self.messages, [])
        tab.act_async("fetch", "github")
        self.wait(lambda: not tab.proc)
        self.assertTrue(os.path.exists(asked))  # selbst angestoßen: Git darf fragen
        self.assertTrue(self.messages and self.messages[-1].startswith("Anmeldung fehlgeschlagen"))

    def auth_server(self):
        """Passwortgeschütztes HTTP-Git-Repo (Benutzer anton, Passwort geheim); gibt die Adresse zurück."""
        web = self.path("web")
        git(self.tmp.name, "init", "-q", "--bare", "-b", "main", os.path.join(web, "repo.git"))
        git(os.path.join(web, "repo.git"), "update-server-info")

        class Auth(http.server.SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.headers.get("Authorization") != "Basic " + base64.b64encode(b"anton:geheim").decode():
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="t"')
                    self.end_headers()
                    return
                super().do_GET()

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Auth, directory=web))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}/repo.git"

    def test_credentials_dialog_answers_git(self):
        """Ein passwortgeschütztes HTTP-Repo: Git fragt über unseren --askpass-Weg nach Benutzer und Passwort."""
        url = self.auth_server()
        # Startskript wie install_askpass, nur dass der Dialog sich selbst beantwortet
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = ("import sys; from PySide6.QtWidgets import QInputDialog; "
                "QInputDialog.getText = staticmethod(lambda p, t, label, mode: "
                "('anton' if 'Benutzer' in label else 'geheim', True)); "
                "sys.argv = ['gitgui', '--askpass', *sys.argv[1:]]; from gitgui.app import main; main()")
        askpass = self.path("askpass.sh")
        with open(askpass, "w") as f:
            f.write(f"#!/bin/sh\nPYTHONPATH={shlex.quote(root)} exec {shlex.quote(sys.executable)} -c "
                    f"{shlex.quote(code)} \"$@\"\n")
        os.chmod(askpass, 0o755)
        result = subprocess.run(["git", "ls-remote", url], capture_output=True, text=True,
                                env={**GIT_ENV, "GIT_ASKPASS": askpass})
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
