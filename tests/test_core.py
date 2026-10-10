"""Tests der reinen Logik (ohne Fenster): Parser, Graph, Patches, Diff-Hilfen."""
import unittest

from tests import helpers  # noqa: F401  (setzt die Testumgebung)
from gitgui.core import (
    build_graph, file_diffs, friendly_error, graph_args, group_repos, line_patch, monthly_series, parse_blame,
    parse_conflicts, parse_file_log, parse_refs, parse_status, rebase_todo, relative_time, resolve_conflicts,
    parse_ssh_remote, split_hunks, ssh_command_for, ssh_key_from_command, ssh_test_result,
)
from gitgui.diff import code_html, diff_html, hunk_marks, word_marks


class StatusTest(unittest.TestCase):
    def test_parse_status(self):
        out = " M a.txt\0M  b.txt\0MM c.txt\0?? d.txt\0R  new.txt\0old.txt\0UU e.txt\0AA f.txt\0"
        self.assertEqual(parse_status(out), (
            [("a.txt", "M"), ("c.txt", "M"), ("d.txt", "?")],
            [("b.txt", "M"), ("c.txt", "M"), ("new.txt", "R")],
            ["e.txt", "f.txt"]))


class ConflictTest(unittest.TestCase):
    def test_parse_and_resolve(self):
        text = ("a\n<<<<<<< HEAD\nmein\n||||||| base\nalt\n=======\ndein\n>>>>>>> feat\nb\n"
                "<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> feat\n")
        segs = parse_conflicts(text)
        self.assertEqual(segs, ["a\n", ("mein\n", "dein\n", "HEAD", "feat"), "b\n", ("x\n", "y\n", "HEAD", "feat")])
        self.assertEqual(resolve_conflicts(segs, ["dein\n", "x\ny\n"]), "a\ndein\nb\nx\ny\n")

    def test_broken_marker_is_text(self):
        self.assertEqual(parse_conflicts("<<<<<<< kaputt\nz\n"), ["<<<<<<< kaputt\nz\n"])


class GraphTest(unittest.TestCase):
    def test_linear(self):
        self.assertEqual([r[0] for r in build_graph([("c", ["b"]), ("b", ["a"]), ("a", [])])], [0, 0, 0])

    def test_merge(self):
        g = build_graph([("M", ["A", "F"]), ("F", ["A"]), ("A", [])])
        self.assertEqual([r[0] for r in g], [0, 1, 0])
        self.assertTrue(g[0][2])  # Merge-Commit
        self.assertIn((1, 0, 0, .5, 1), g[2][1])  # F läuft in A zusammen

    def test_lanes_move_left_and_keep_color(self):
        g = build_graph([("a1", ["root"]), ("b1", ["b0"]), ("c1", ["c0"]), ("b0", []), ("c0", ["root"]), ("root", [])])
        self.assertEqual([r[0] for r in g], [0, 1, 2, 1, 1, 0])
        self.assertIn((2, 0, 1, 1, 2), g[3][1])
        self.assertEqual(g[4][3], 2)

    def test_parse_refs_merges_synced_remote(self):
        self.assertEqual(
            parse_refs("HEAD -> refs/heads/main, tag: refs/tags/v1, refs/remotes/origin/HEAD, "
                       "refs/remotes/origin/main, refs/remotes/origin/x, refs/stash"),
            [("main", "head", True), ("origin/x", "remote", False), ("v1", "tag", False)])

    def test_graph_args(self):
        ex = {"refs/heads/main", "refs/heads/dev", "refs/remotes/origin/main"}
        self.assertEqual(graph_args([], [], ex), ["--exclude=refs/stash", "--all"])
        self.assertEqual(graph_args(["refs/heads/dev", "refs/heads/weg"], [], ex), ["refs/heads/dev"])
        self.assertEqual(graph_args(["refs/heads/weg"], ["refs/remotes/origin/main"], ex),
                         ["--exclude=refs/stash", "--exclude=refs/remotes/origin/main", "--all"])


class PatchTest(unittest.TestCase):
    def test_split_hunks(self):
        d = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n@@ -9,2 +9,2 @@\n c\n-d\n+e\n"
        head, hunks = split_hunks(d)
        self.assertEqual(head, "diff --git a/x b/x\n--- a/x\n+++ b/x\n")
        self.assertEqual(hunks, ["@@ -1 +1 @@\n-a\n+b\n", "@@ -9,2 +9,2 @@\n c\n-d\n+e\n"])

    def test_line_patch(self):
        d = "--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n-a\n+b\n+c\n"
        self.assertEqual(line_patch(d, {(0, 3)}), "--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n a\n+c\n")
        self.assertEqual(line_patch(d, {(0, 3)}, reverse=True), "--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n b\n+c\n")

    def test_line_patch_no_newline_at_eof(self):
        d = "@@ -1,2 +1,2 @@\n x\n-y\n\\ No newline at end of file\n+Y\n\\ No newline at end of file\n"
        self.assertEqual(line_patch(d, {(0, 4)}), "@@ -1,2 +1,2 @@\n x\n-y\n\\ No newline at end of file\n+y\n+Y\n"
                                                  "\\ No newline at end of file\n")

    def test_file_diffs(self):
        patch = ("diff --git a/x b/x\nindex 1..2 100644\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
                 "diff --git a/o b/n\nsimilarity index 90%\nrename from o\nrename to n\n"
                 "diff --git a/neu b/neu\nnew file mode 100644\n--- /dev/null\n+++ b/neu\n@@ -0,0 +1 @@\n+z\n")
        self.assertEqual([f[:3] for f in file_diffs(patch)], [("x", "x", "M"), ("n", "o → n", "R"), ("neu", "neu", "A")])

    def test_rebase_todo_quotes_messages(self):
        self.assertEqual(rebase_todo([("pick", "a1", "x"), ("reword", "b2", "Neu's"), ("drop", "c3", "")]),
                         "pick a1\npick b2\nexec git commit --amend --only -q -m 'Neu'\"'\"'s'\ndrop c3\n")


class DiffRenderingTest(unittest.TestCase):
    def test_word_marks(self):
        self.assertEqual(word_marks("x = foo(1)", "x = bar(1)"), ([(4, 7)], [(4, 7)]))
        self.assertEqual(word_marks("abc", "völlig anders hier"), ([], []))
        self.assertEqual(hunk_marks(["@@", "-a = 1", "+a = 2", " c"]), {1: [(4, 5)], 2: [(4, 5)]})

    def test_code_html_escapes_and_marks(self):
        self.assertEqual(code_html("a<b", marks=[(1, 2)], mark_bg="#f00"), "a<span style='background:#f00;'>&lt;</span>b")

    def test_diff_html_rowmap(self):
        _, rowmap = diff_html("@@ -1 +1 @@\n-a\n+b\n", selectable=True)
        self.assertEqual(rowmap, [None, (0, 1), (0, 2)])
        page, rowmap = diff_html("@@ -1,2 +1,2 @@\n x\n-a\n+b\n", selectable=True, split=True)
        self.assertTrue(all(r is None for r in rowmap))  # nebeneinander keine Zeilenauswahl
        self.assertEqual(page.count("width='50%'"), 4)  # Kontextzeile und Paar a|b, je zwei Spalten


class TextTest(unittest.TestCase):
    def test_friendly_error(self):
        self.assertIsNone(friendly_error("CONFLICT (content): Merge conflict in a")[0])
        self.assertTrue(friendly_error(" ! [rejected] main -> main (fetch first)")[0].startswith("Push abgelehnt"))
        self.assertTrue(friendly_error(" ! [rejected] main (stale info)")[0].startswith("Erzwungener Push"))
        self.assertEqual(friendly_error("fatal: something odd"), ("fatal: something odd", False))

    def test_relative_time(self):
        self.assertEqual(relative_time(0, now=30), "gerade eben")
        self.assertEqual(relative_time(0, now=3 * 3600), "vor 3 Stunden")
        self.assertEqual(relative_time(0, now=86400 + 5), "gestern")
        self.assertEqual(relative_time(0, now=2 * 365 * 86400), "vor 2 Jahren")

    def test_monthly_series(self):
        months, series = monthly_series([("A", "2024-11"), ("A", "2025-01"), ("B", "2025-01"), ("C", "2025-01")], top=2)
        self.assertEqual(months, ["2024-11", "2024-12", "2025-01"])
        self.assertEqual(series, [("A", [1, 0, 1]), ("B", [0, 0, 1]), ("Andere", [0, 0, 1])])

    def test_group_repos(self):
        g = group_repos(["/x/zeta", "/x/Alpha", "/y/beta", "/y/gamma"], ["Arbeit"],
                        {"/y/beta": "Arbeit", "/y/gamma": "Gelöscht"})
        self.assertEqual(g, [("Arbeit", ["/y/beta"]), (None, ["/x/Alpha", "/y/gamma", "/x/zeta"])])

    def test_parse_blame_and_file_log(self):
        b = parse_blame("a" * 40 + " 1 1 1\nauthor Ann\nauthor-time 100\nsummary x\n\tcode 1\n"
                        + "b" * 40 + " 2 2 1\nauthor Bob\nauthor-time 200\n\tcode 2\n")
        self.assertEqual(b, [("a" * 40, "Ann", 100, "code 1"), ("b" * 40, "Bob", 200, "code 2")])
        self.assertEqual(parse_file_log("\x1eh1\x1fs1\n\nneu.txt\n\x1eh2\x1fs2\n\nalt.txt\n"),
                         [(["h1", "s1"], "neu.txt"), (["h2", "s2"], "alt.txt")])


class SshTest(unittest.TestCase):
    def test_parse_ssh_remote(self):
        self.assertEqual(parse_ssh_remote("git@github.com:a/b.git"), ("git@github.com", None))
        self.assertEqual(parse_ssh_remote("ssh://git@host.de:2222/a/b.git"), ("git@host.de", "2222"))
        self.assertEqual(parse_ssh_remote("host:repo"), ("host", None))
        self.assertIsNone(parse_ssh_remote("https://github.com/a/b.git"))
        self.assertIsNone(parse_ssh_remote("/srv/git/repo.git"))

    def test_key_roundtrip(self):
        cmd = ssh_command_for("/home/a b/.ssh/id_x")
        self.assertEqual(ssh_key_from_command(cmd), "/home/a b/.ssh/id_x")
        self.assertIsNone(ssh_key_from_command("ssh -v"))

    def test_result(self):
        self.assertTrue(ssh_test_result(1, "Hi anton! You've successfully authenticated, but GitHub does not provide shell access.")[0])
        self.assertTrue(ssh_test_result(0, "")[0])
        self.assertIn("kennt diesen Schlüssel nicht", ssh_test_result(255, "git@x: Permission denied (publickey).")[1])


if __name__ == "__main__":
    unittest.main()
