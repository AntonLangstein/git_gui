#!/usr/bin/env python3
"""Minimal git GUI im Stil von Fork. Usage: git_gui.py [repo ...]"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time

from PySide6.QtCore import QPointF, QProcess, QProcessEnvironment, QRectF, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction, QColor, QCursor, QDesktopServices, QFont, QIcon, QPixmap, QKeySequence, QPainter, QPainterPath, QPalette,
    QPen, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QHeaderView,
    QAbstractItemView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QStyle,
    QStyledItemDelegate, QTabWidget, QTextBrowser, QToolBar, QToolButton, QToolTip, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

# Dunkles Theme angelehnt an Fork
COLORS = {
    "window": "#2b2b2e", "base": "#1f1f22", "alt": "#262629", "text": "#dddddd", "dim": "#8a8a8a",
    "button": "#3a3a3e", "highlight": "#46464c", "border": "#141416", "accent": "#3794ff",
}

STYLE = """
QToolBar#main { background: #333337; border: none; border-bottom: 1px solid #141416; padding: 2px 6px; spacing: 2px; }
QToolBar#main QToolButton { padding: 2px 8px; border-radius: 4px; }
QToolBar#main QToolButton:hover { background: #45454a; }
QLabel#repoInfo { padding: 0 24px; }
QTabWidget#repos::pane { border: none; }
QTabWidget#repos > QTabBar { background: #262629; }
QTabWidget#repos > QTabBar::tab { background: #262629; color: #9a9a9a; padding: 6px 14px; border: none;
                                  border-right: 1px solid #141416; border-bottom: 1px solid #141416; min-width: 110px; }
QTabWidget#repos > QTabBar::tab:selected { background: #38383c; color: #ffffff; }
QTabWidget#repos > QTabBar::tab:hover:!selected { background: #2f2f33; }
QTabWidget#detail::pane { border: none; border-top: 1px solid #3a3a3e; }
QTabWidget#detail > QTabBar::tab { background: transparent; padding: 7px 22px; border: none; font-weight: bold; color: #bbbbbb; }
QTabWidget#detail > QTabBar::tab:selected { color: #3794ff; border-bottom: 2px solid #3794ff; }
QWidget#sidebarPane, QTreeWidget#sidebar { background: #252528; border: none; }
QTreeWidget#sidebar::item { padding: 2px 0; }
QLabel#repoTitle { font-weight: bold; font-size: 11pt; padding: 8px 10px 4px 10px; }
QLineEdit#filter { background: #1b1b1d; border: 1px solid #3a3a3e; border-radius: 4px; padding: 3px 6px; margin: 4px 8px; }
QTreeWidget#log { border: none; }
QHeaderView::section { background: #2b2b2e; color: #9a9a9a; border: none; border-right: 1px solid #141416;
                       border-bottom: 1px solid #141416; padding: 3px 6px; }
QPlainTextEdit, QTextBrowser, QListWidget { border: none; }
QSplitter::handle { background: #141416; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QStatusBar { background: #2b2b2e; color: #9a9a9a; }
QMenuBar { background: #2b2b2e; }
QMenuBar::item:selected { background: #45454a; }
QFrame#listHeader, QFrame#diffHeader { background: #2b2b2e; border-bottom: 1px solid #141416; }
QFrame#listHeader QLabel, QFrame#diffHeader QLabel { font-weight: bold; }
QFrame#listHeader QPushButton, QFrame#diffHeader QPushButton { padding: 2px 10px; }
QListWidget#files::item { padding: 2px 4px; }
QWidget#commitBox { background: #252528; }
QLineEdit#subject, QPlainTextEdit#body { background: #1b1b1d; border: 1px solid #3a3a3e; border-radius: 4px; padding: 4px; }
QPushButton#commitBtn { background: #2f6fd0; color: white; border: none; border-radius: 4px; padding: 6px 16px; font-weight: bold; }
QPushButton#commitBtn:hover { background: #3a7fe6; }
QPushButton#commitBtn:disabled { background: #3a3a3e; color: #777; }
QLabel#managerTitle { font-size: 17pt; font-weight: bold; padding: 10px 14px; }
QLabel#repoHeadline { font-size: 16pt; font-weight: bold; }
QFrame#banner { background: rgba(229, 83, 75, 45); border-radius: 6px; }
"""


def setup_app(app):
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg")))
    app.setDesktopFileName("git_gui")  # ordnet das Fenster unter Wayland dem Starter git_gui.desktop zu
    pal = QPalette()
    for role, key in ((QPalette.Window, "window"), (QPalette.WindowText, "text"), (QPalette.Base, "base"),
                      (QPalette.AlternateBase, "alt"), (QPalette.Text, "text"), (QPalette.Button, "button"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "highlight"),
                      (QPalette.HighlightedText, "text"), (QPalette.ToolTipBase, "window"),
                      (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "dim"), (QPalette.Link, "accent"),
                      (QPalette.Mid, "button"), (QPalette.Midlight, "highlight"), (QPalette.Dark, "border")):
        pal.setColor(role, QColor(COLORS[key]))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor("#6a6a6a"))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)


# Netzwerk-Ops sollen fehlschlagen statt unsichtbar auf eine Passwortabfrage zu warten,
# und Befehle wie `rebase --continue` dürfen keinen Editor öffnen.
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true"}

OPERATIONS = {"merge": "Merge", "rebase": "Rebase", "cherry-pick": "Cherry-Pick", "revert": "Revert"}
CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}

LANE_COLORS = ["#4c9aff", "#e5534b", "#57ab5a", "#c69026", "#986ee2", "#39c5cf", "#e0823d", "#d16d9e"]
LANE_W = 14
STATUS_COLORS = {"A": "#57ab5a", "M": "#c69026", "D": "#e5534b", "R": "#4c9aff", "C": "#4c9aff"}

# Datenrollen der Verlaufs-Einträge
GRAPH_ROLE, REFS_ROLE, HASH_ROLE, HEAD_ROLE = (Qt.ItemDataRole.UserRole + i for i in range(4))
NODE_ROLE = Qt.ItemDataRole.UserRole + 10  # Pfad von Abschnitten/Ordnern in der Seitenleiste


def build_graph(commits):
    """[(hash, [parents])] neueste zuerst -> pro Zeile (spalte, segmente, ist_merge, farbe).

    Segment = (lane1, y1, lane2, y2, farbe), y in {0, .5, 1} relativ zur Zeilenhöhe.
    Oben gelten die Lane-Positionen der Zeile davor, unten die nach dem Nachrücken.
    Jede Lane behält ihre Farbe, auch wenn sie nach links rückt.
    """
    lanes, rows, next_color = [], [], 0  # lanes: [(erwarteter_hash, farbe)]
    for h, parents in commits:
        ids = [lane[0] for lane in lanes]
        known = h in ids
        if known:
            col = ids.index(h)
        else:  # Branch-Spitze: neue Lane ganz rechts
            col = len(lanes)
            lanes.append((h, next_color))
            next_color += 1
        color = lanes[col][1]

        after = [None if lane[0] == h else lane for lane in lanes]  # in h endende Lanes fallen weg
        targets = []
        for n, p in enumerate(parents):
            open_ids = [lane and lane[0] for lane in after]
            if n == 0:  # erster Parent bleibt in der eigenen Lane
                j = col
                after[col] = (p, color)
            elif p in open_ids:  # Merge in eine schon laufende Lane
                j = open_ids.index(p)
            else:
                j = open_ids.index(None) if None in open_ids else len(after)
                if j == len(after):
                    after.append(None)
                after[j] = (p, next_color)
                next_color += 1
            targets.append(j)

        pos = {}  # Nachrücken: Index in `after` -> Index ohne Lücken
        for i, lane in enumerate(after):
            if lane:
                pos[i] = len(pos)
        segs = []
        for i, (lh, lc) in enumerate(lanes):
            if lh == h:
                if known:
                    segs.append((i, 0, col, .5, lc))
            else:  # läuft durch, rückt evtl. nach links
                segs.append((i, 0, pos[i], 1, lc))
        for j in targets:
            segs.append((col, .5, pos[j], 1, after[j][1]))
        lanes = [lane for lane in after if lane]
        rows.append((col, segs, len(parents) > 1, color))
    return rows


def parse_refs(decor):
    """`%D` mit --decorate=full -> [(name, art, remote_gleich)], art in head/branch/remote/tag.

    Zeigt ein Remote-Branch auf denselben Commit wie der gleichnamige lokale Branch,
    wird er weggelassen und der lokale bekommt remote_gleich=True (Wolke wie bei Fork).
    """
    out = []
    for r in filter(None, decor.split(", ")):
        if r.startswith("HEAD -> "):
            out.append((r[8:].removeprefix("refs/heads/"), "head"))
        elif r == "HEAD":  # detached
            out.append(("HEAD", "head"))
        elif r.startswith("tag: "):
            out.append((r[5:].removeprefix("refs/tags/"), "tag"))
        elif r.startswith("refs/heads/"):
            out.append((r[11:], "branch"))
        elif r.startswith("refs/remotes/") and not r.endswith("/HEAD"):
            out.append((r[13:], "remote"))
    local = {n for n, k in out if k in ("head", "branch")}
    short = lambda n: n.split("/", 1)[1]  # origin/feature/x -> feature/x
    synced = {short(n) for n, k in out if k == "remote" and short(n) in local}
    out = [(n, k, k != "remote" and n in synced) for n, k in out
           if not (k == "remote" and short(n) in local)]
    order = ("head", "branch", "remote", "tag")
    return sorted(out, key=lambda ref: order.index(ref[1]))


def initials(name):
    return "".join(part[0] for part in name.split()[:2]).upper() or "?"


def person_color(name):
    return LANE_COLORS[sum(map(ord, name)) % len(LANE_COLORS)]


def draw_background(painter, opt, index, delegate):
    """Hintergrund/Auswahl wie gewohnt zeichnen, Text macht der Delegate selbst."""
    delegate.initStyleOption(opt, index)
    text, opt.text = opt.text, ""
    opt.icon = QIcon()
    opt.widget.style().drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
    return text


class CommitDelegate(QStyledItemDelegate):
    """Graph, Branch-/Tag-Labels und Commit-Nachricht in einer Spalte, wie bei Fork."""
    filtering = False  # beim Filtern fehlen Zeilen: dann nur Punkte statt zerrissener Linien

    def paint(self, painter, opt, index):
        text = draw_background(painter, opt, index, self)
        r = opt.rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        x = r.left() + 6
        row = index.data(GRAPH_ROLE)
        if row:
            col, segs, merge, color = row
            lx = lambda lane: r.left() + 4 + LANE_W * lane + LANE_W / 2
            ly = lambda f: r.top() + r.height() * f
            painter.setBrush(Qt.NoBrush)
            for l1, y1, l2, y2, lane in ([] if self.filtering else segs):
                path = QPainterPath(QPointF(lx(l1), ly(y1)))
                if l1 == l2:
                    path.lineTo(lx(l2), ly(y2))
                else:  # weiche Kurve wie bei Fork
                    ym = (ly(y1) + ly(y2)) / 2
                    path.cubicTo(lx(l1), ym, lx(l2), ym, lx(l2), ly(y2))
                painter.setPen(QPen(QColor(LANE_COLORS[lane % len(LANE_COLORS)]), 2))
                painter.drawPath(path)
            painter.setPen(QPen(QColor(COLORS["base"]), 1.5))
            painter.setBrush(QColor(LANE_COLORS[color % len(LANE_COLORS)]))
            rad = 3.5 if merge else 5
            painter.drawEllipse(QPointF(lx(col), ly(.5)), rad, rad)
            used = max([col] + [max(s[0], s[2]) for s in ([] if self.filtering else segs)]) + 1  # Text hinter dem Graph
            x = r.left() + 4 + LANE_W * used + 6
            lane_color = QColor(LANE_COLORS[color % len(LANE_COLORS)])
        else:
            lane_color = QColor(LANE_COLORS[0])

        font = QFont(opt.font)
        for name, kind, synced in index.data(REFS_ROLE) or []:
            font.setBold(kind == "head")
            painter.setFont(font)
            label = ("✓ " if kind == "head" else "") + name + (" ☁" if synced else "")
            w = painter.fontMetrics().horizontalAdvance(label) + 12
            box = QRectF(x, r.top() + 2.5, w, r.height() - 5)
            if kind == "tag":
                fill, border, fg = QColor("#4a4a50"), QColor("#8b949e"), QColor("#e6e6e6")
            elif kind == "remote":  # Remote: dunkel mit farbigem Rand, wie bei Fork
                fill, border, fg = QColor(lane_color), lane_color, lane_color.lighter(130)
                fill.setAlpha(45)
            else:
                fill, border, fg = lane_color.darker(115), lane_color, QColor("white")
            painter.setPen(QPen(border, 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(fg)
            painter.drawText(box, Qt.AlignCenter, label)
            x += w + 5

        font.setBold(bool(index.data(HEAD_ROLE)))
        painter.setFont(font)
        painter.setPen(opt.palette.text().color())
        rest = QRectF(x + 2, r.top(), max(0, r.right() - x - 6), r.height())
        painter.drawText(rest, Qt.AlignVCenter | Qt.AlignLeft,
                         painter.fontMetrics().elidedText(text, Qt.ElideRight, int(rest.width())))
        painter.restore()


class AuthorDelegate(QStyledItemDelegate):
    """Autor mit rundem Initialen-Avatar davor."""

    def paint(self, painter, opt, index):
        name = draw_background(painter, opt, index, self)
        r = opt.rect
        d = r.height() - 4
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        avatar = QRectF(r.left() + 4, r.top() + 2, d, d)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(person_color(name)))
        painter.drawRoundedRect(avatar, 3, 3)
        small = QFont(opt.font)
        small.setPointSizeF(opt.font.pointSizeF() * 0.7)
        small.setBold(True)
        painter.setFont(small)
        painter.setPen(QColor("white"))
        painter.drawText(avatar, Qt.AlignCenter, initials(name))
        painter.setFont(opt.font)
        painter.setPen(opt.palette.text().color())
        rest = r.adjusted(d + 10, 0, -4, 0)
        painter.drawText(rest, Qt.AlignVCenter | Qt.AlignLeft,
                         painter.fontMetrics().elidedText(name, Qt.ElideRight, rest.width()))
        painter.restore()


def parse_status(out):
    """`git status --porcelain=v1 -z` -> (unstaged, staged, conflicts).

    unstaged/staged: [(pfad, status)], status z.B. M, A, D, R oder ? (neu, unversioniert).
    """
    parts, unstaged, staged, conflicts, i = out.split("\0"), [], [], [], 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if not entry:
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        if x in "RC":
            i += 1  # rename/copy: next field is the original path
        if x + y in CONFLICT_CODES:
            conflicts.append(path)
            continue
        if x not in " ?":
            staged.append((path, x))
        if y != " ":
            unstaged.append((path, y))
    return unstaged, staged, conflicts


def split_hunks(diff):
    """Diff einer Datei -> (Kopf, [Hunks]); jeder Hunk beginnt mit @@ und ist einzeln anwendbar."""
    head, hunks = [], []
    for line in diff.splitlines(keepends=True):
        if line.startswith("@@"):
            hunks.append([line])
        elif hunks:
            hunks[-1].append(line)
        else:
            head.append(line)
    return "".join(head), ["".join(h) for h in hunks]


def diff_html(diff, hunk_action=None, selected=(), selectable=False):
    """Diff -> HTML mit Zeilennummern alt/neu wie bei Fork.

    hunk_action = Linktext im Hunk-Kopf; selectable = +/- Zeilen sind auswählbar (Kästchen als Hinweis),
    selected = ausgewählte Zeilen als {(hunk, zeile)}.
    Rückgabe (html, rowmap): rowmap[Tabellenzeile] = (hunk, zeile) bzw. None, für Klicks auf ganze Zeilen.
    """
    _, hunks = split_hunks(diff)
    e = html.escape
    if not hunks:  # z.B. Binärdatei oder leer
        return f"<pre style='color:{COLORS['dim']}'>{e(diff) or 'Keine Änderungen.'}</pre>", []
    rows, rowmap = [], []
    box = lambda on: (f"<span style='color:{COLORS['accent'] if on else '#6a6a6a'}'>{'☑' if on else '☐'}</span>")
    # ponytail: sehr große Diffs werden als HTML langsam; bei Bedarf ab x Zeilen kürzen
    for h, hunk in enumerate(hunks):
        lines = hunk.splitlines()
        m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", lines[0])
        old, new = (int(m[1]), int(m[2])) if m else (0, 0)
        link = (f"<a href='hunk:{h}' style='color:{COLORS['accent']}; text-decoration:none'>{hunk_action}</a>"
                if hunk_action else "")
        rowmap.append(None)
        rows.append(f"<tr bgcolor='#2c3340'><td width='18'></td><td width='44'></td><td width='44'></td>"
                    f"<td style='color:{COLORS['dim']}'>{e(lines[0])}</td><td align='right'>{link}&nbsp;</td></tr>")
        for i, line in enumerate(lines[1:], 1):
            kind = line[:1]
            on = (h, i) in selected
            if kind == "+":
                o, n, bg = "", new, "#2f6b40" if on else "#1e3a26"
                new += 1
            elif kind == "-":
                o, n, bg = old, "", "#7a3038" if on else "#46252a"
                old += 1
            elif kind == "\\":  # "\ No newline at end of file"
                o, n, bg = "", "", ""
            else:
                o, n, bg = old, new, ""
                old += 1
                new += 1
            pickable = selectable and kind in ("+", "-")
            rowmap.append((h, i) if pickable else None)
            check = box(on) if pickable else ""
            rows.append(f"<tr{f' bgcolor={bg}' if bg else ''}>"
                        f"<td width='18' align='center'>{check}</td>"
                        f"<td width='44' align='right' style='color:#6a6a6a'>{o}&nbsp;</td>"
                        f"<td width='44' align='right' style='color:#6a6a6a'>{n}&nbsp;</td>"
                        f"<td width='100%' colspan='2' style='white-space:pre'>{e(line) or ' '}</td></tr>")
    return f"<table width='100%' cellspacing='0' cellpadding='1'>{''.join(rows)}</table>", rowmap


def line_patch(diff, selected, reverse=False):
    """Patch, der nur die ausgewählten +/- Zeilen enthält; für `git apply --cached --recount [--reverse]`.

    Nicht ausgewählte Zeilen behalten den Stand im Index: beim Stagen wird ein nicht gewähltes „-“
    zur Kontextzeile und ein „+“ fällt weg, beim Unstagen (reverse) genau umgekehrt.
    """
    head, hunks = split_hunks(diff)
    keep_as_context, drop = ("+", "-") if reverse else ("-", "+")
    parts = []
    for h, hunk in enumerate(hunks):
        rows = {i for hh, i in selected if hh == h}
        if not rows:
            continue
        lines = hunk.splitlines(keepends=True)
        body = lines[1:]
        emitted = lambda j: body[j][:1] == " " or (body[j][:1] in "+-" and (j + 1 in rows or body[j][:1] == keep_as_context))
        out, last_kept = [lines[0]], True
        for j, line in enumerate(body):
            i, kind = j + 1, line[:1]
            if kind in "+-" and i not in rows:
                if kind == keep_as_context:
                    marker = j + 1 < len(body) and body[j + 1].startswith("\\")
                    # ponytail: nur beim Stagen behandelt; beim Unstagen steht so eine Zeile praktisch immer am Ende
                    if marker and not reverse and any(emitted(k) for k in range(j + 2, len(body))):
                        # Zeile ohne Umbruch am Dateiende bleibt nicht die letzte: alt ohne, neu mit Umbruch
                        out += [line, body[j + 1], "+" + line[1:]]
                        last_kept = False  # Marker ist schon ausgegeben
                        continue
                    out.append(" " + line[1:])
                    last_kept = True
                else:  # kind == drop
                    last_kept = False
                continue
            if kind == "\\" and not last_kept:  # gehört zu einer weggelassenen Zeile
                continue
            out.append(line)
            last_kept = True
        parts.append("".join(out))
    patch = head + "".join(parts)
    return patch if patch.endswith("\n") else patch + "\n"


def file_diffs(patch):
    """Mehrdatei-Patch (`git show`/`stash show -p`) -> [(pfad, anzeigename, status, diff)] pro Datei."""
    chunks = []
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            chunks.append([line])
        elif chunks:
            chunks[-1].append(line)
    out = []
    for chunk in chunks:
        path = chunk[0].rstrip("\n").partition(" b/")[2]  # "diff --git a/x b/x"
        status, old = "M", None
        for line in chunk[1:]:
            if line.startswith("@@"):
                break
            if line.startswith("new file mode"):
                status = "A"
            elif line.startswith("deleted file mode"):
                status = "D"
            elif line.startswith("rename from "):
                status, old = "R", line[12:].rstrip("\n")
            elif line.startswith("rename to "):
                path = line[10:].rstrip("\n")
        out.append((path, f"{old} → {path}" if old else path, status, "".join(chunk)))
    return out


def patch_html(patch):
    """Ganzer Commit/Stash im Fork-Stil: pro Datei eine Kopfzeile, darunter der Diff mit Zeilennummern."""
    e = html.escape
    parts = []
    for i, (_, name, status, diff) in enumerate(file_diffs(patch)):
        char, color = STATUS_BADGES.get(status, (status, COLORS["dim"]))
        parts.append(f"<a name='file{i}'></a><table width='100%' cellspacing='0' cellpadding='5'>"
                     f"<tr bgcolor='#2b2b2e'><td><b style='color:{color}'>{char}</b>&nbsp; <b>{e(name)}</b></td></tr></table>")
        if split_hunks(diff)[1]:
            parts.append(diff_html(diff)[0])
        else:
            parts.append(f"<p style='color:{COLORS['dim']}'>&nbsp;Keine Textänderungen (z.B. Binärdatei oder nur Rechte).</p>")
        parts.append("<br>")
    return "".join(parts) or f"<p style='color:{COLORS['dim']}'>Keine Änderungen.</p>"


STATUS_BADGES = {"M": ("M", "#c69026"), "A": ("+", "#57ab5a"), "?": ("+", "#57ab5a"), "D": ("−", "#e5534b"),
                 "R": ("R", "#4c9aff"), "C": ("C", "#4c9aff"), "T": ("T", "#c69026")}
_badge_cache = {}


def status_icon(code):
    """Kleines farbiges Kästchen mit Status-Zeichen, wie die Datei-Symbole in Fork."""
    if code not in _badge_cache:
        char, color = STATUS_BADGES.get(code, (code, COLORS["dim"]))
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(2, 2, 28, 28), 6, 6)
        f = QFont()
        f.setPixelSize(22)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(QRectF(0, 0, 32, 32), Qt.AlignCenter, char)
        p.end()
        _badge_cache[code] = QIcon(pm)
    return _badge_cache[code]


def parse_conflicts(text):
    """Text mit Konfliktmarkern -> Liste aus str (unverändert) und (ours, theirs, label_ours, label_theirs)."""
    lines = text.splitlines(keepends=True)
    segs, buf, i = [], [], 0
    while i < len(lines):
        if not lines[i].startswith("<<<<<<<"):
            buf.append(lines[i])
            i += 1
            continue
        ours, theirs, part, end = [], [], "ours", None
        for j in range(i + 1, len(lines)):
            line = lines[j]
            if part == "ours" and line.startswith("|||||||"):  # diff3: Basis überspringen
                part = "base"
            elif part in ("ours", "base") and line.startswith("======="):
                part = "theirs"
            elif part == "theirs" and line.startswith(">>>>>>>"):
                end = j
                break
            elif part == "ours":
                ours.append(line)
            elif part == "theirs":
                theirs.append(line)
        if end is None:  # unvollständiger Marker: als normalen Text behandeln
            buf.append(lines[i])
            i += 1
            continue
        if buf:
            segs.append("".join(buf))
            buf = []
        segs.append(("".join(ours), "".join(theirs), lines[i][7:].strip(), lines[end][7:].strip()))
        i = end + 1
    if buf:
        segs.append("".join(buf))
    return segs


def resolve_conflicts(segs, results):
    """Setzt die Datei wieder zusammen; results = Ersatztext pro Konflikt."""
    results = iter(results)
    return "".join(seg if isinstance(seg, str) else next(results) for seg in segs)


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


def load_stars(repo):
    """Favoriten (Starred) eines Repos als ["branch:main", "remote:origin/dev", …]."""
    try:
        return json.loads(QSettings("git_gui", "git_gui").value("starred", "{}")).get(repo, [])
    except ValueError:
        return []


def save_stars(repo, stars):
    settings = QSettings("git_gui", "git_gui")
    try:
        data = json.loads(settings.value("starred", "{}"))
    except ValueError:
        data = {}
    if stars:
        data[repo] = stars
    else:
        data.pop(repo, None)
    settings.setValue("starred", json.dumps(data))


def repo_root(path):
    """Wurzel des Git-Repos, in dem `path` liegt, oder None."""
    r = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return None if r.returncode else r.stdout.strip()


class DiffView(QTextBrowser):
    """Diff-Anzeige, in der ein Klick auf eine ganze +/- Zeile sie auswählt (Ziehen markiert weiter Text)."""

    def __init__(self, on_line):
        super().__init__(openLinks=False)
        self.on_line = on_line  # bekommt QUrl("line:hunk:zeile")
        self.rowmap = []
        self.press = None

    def mousePressEvent(self, event):
        self.press = event.position().toPoint()
        super().mousePressEvent(event)

    def line_at(self, pos):
        """(hunk, zeile) der auswählbaren Zeile unter `pos`, sonst None."""
        cursor = self.cursorForPosition(pos)
        table = cursor.currentTable()
        row = table.cellAt(cursor).row() if table else -1
        return self.rowmap[row] if 0 <= row < len(self.rowmap) else None

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        pos = event.position().toPoint()
        if not event.buttons() and not self.anchorAt(pos):  # über Links setzt Qt selbst die Hand
            self.viewport().setCursor(Qt.PointingHandCursor if self.line_at(pos) else Qt.IBeamCursor)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        pos = event.position().toPoint()
        if (event.button() != Qt.LeftButton or self.press is None or self.anchorAt(pos)
                or (pos - self.press).manhattanLength() > 4):  # Link oder Text-Markieren
            return
        line = self.line_at(pos)
        if line:
            self.on_line(QUrl("line:%d:%d" % line))


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
        self.log.setItemDelegateForColumn(1, AuthorDelegate(self.log))
        header = self.log.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 180), (2, 80), (3, 130)):
            self.log.setColumnWidth(col, width)
        self.log.currentItemChanged.connect(lambda cur, _prev: self.show_commit(cur))

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

        self.refresh()

    # --- git ---------------------------------------------------------------

    def git(self, *args, check=False, input=None):
        """Schnelle, lokale git-Befehle synchron; Netzwerk-Befehle laufen über act_async."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            stdin = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
            r = subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env=GIT_ENV, **stdin)
        finally:
            QApplication.restoreOverrideCursor()
        self.last_rc = r.returncode
        if check:
            if r.returncode:
                QMessageBox.warning(self, "git " + args[0], r.stderr or r.stdout)
            else:
                self.show_status(args[0], r.stderr or r.stdout)
        return r.stdout

    def show_status(self, cmd, output):
        last = output.strip().splitlines()
        if isinstance(self.window(), QMainWindow):
            self.window().statusBar().showMessage(f"git {cmd}: " + (last[-1] if last else "ok"), 8000)

    def act_async(self, *args):
        """Fetch/Pull/Push im Hintergrund: das Fenster bleibt bedienbar, danach wird aktualisiert."""
        if self.proc:
            return QMessageBox.information(self, "Git", f"Es läuft noch „git {self.proc_label}“. Bitte kurz warten.")
        proc = QProcess(self)
        env = QProcessEnvironment()
        for key, value in GIT_ENV.items():
            env.insert(key, value)
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(self.repo)
        proc.finished.connect(lambda code, status: self.async_done(proc, args, code, status))
        proc.errorOccurred.connect(lambda err: err == QProcess.FailedToStart and self.async_done(proc, args, -1, None))
        self.proc, self.proc_label = proc, args[0]
        self.changed.emit()
        proc.start("git", list(args))
        proc.closeWriteChannel()  # keine Eingaben: Git soll nie auf stdin warten

    def async_done(self, proc, args, code, status):
        if self.proc is not proc:  # schon behandelt (z.B. Startfehler + finished)
            return
        out = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        err = bytes(proc.readAllStandardError()).decode(errors="replace")
        self.proc = None
        proc.deleteLater()
        if code != 0 or status == QProcess.CrashExit:
            QMessageBox.warning(self, "git " + args[0], err or out or "Der Befehl wurde abgebrochen.")
        else:
            self.show_status(args[0], err or out)
        self.refresh()

    def act(self, *args):
        self.git(*args, check=True)
        self.refresh()

    def push(self, branch=None):
        """Pusht `branch` (Standard: aktueller Branch)."""
        upstream = self.git("rev-parse", "--abbrev-ref", f"{branch or ''}@{{u}}").strip()
        if upstream and not branch:
            self.act_async("push")
        elif upstream:  # ponytail: nimmt an, dass Remote-Namen keinen "/" enthalten
            self.act_async("push", upstream.split("/", 1)[0], branch)
        else:  # erster Push eines Branches: Upstream setzen
            self.act_async("push", "-u", "origin", branch or "HEAD")

    def new_branch(self, start=None):
        name, ok = QInputDialog.getText(self, "Neuer Branch", f"Name (wird von {start or 'HEAD'} erstellt):")
        if ok and name.strip():
            self.act("switch", "-c", name.strip(), *([start] if start else []))

    def rename_branch(self, old):
        new, ok = QInputDialog.getText(self, "Branch umbenennen", f"Neuer Name für „{old}“:", text=old)
        new = new.strip()
        if ok and new and new != old:
            self.git("branch", "-m", old, new, check=True)
            if self.last_rc == 0:  # Favorit wandert mit
                save_stars(self.repo, [f"branch:{new}" if x == f"branch:{old}" else x for x in load_stars(self.repo)])
            self.refresh()

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
        if not self.refs(f"refs/heads/{name}"):  # gelöscht: auch aus den Favoriten
            save_stars(self.repo, [x for x in load_stars(self.repo) if x != f"branch:{name}"])
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
            self.conflicts.item(i).setForeground(QColor("#e5534b"))
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
        self.changed.emit()
        self.build_sidebar(len({p for p, _ in unstaged} | {p for p, _ in staged} | set(conflicts)))
        self.render_view()

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
        add(t, "Alle Commits", ("log", "--all", "all"), "view-history")

        heads = self.refs("refs/heads", "%(HEAD)\t%(refname:short)\t%(upstream:track,nobracket)")
        remotes = [n for (n,) in self.refs("refs/remotes") if "/" in n and not n.endswith("/HEAD")]  # "origin" = origin/HEAD
        current = next((n for h, n, _ in heads if h == "*"), None)

        # Favoriten (Starred) oben, wie bei Fork; gelöschte Branches werden einfach nicht gezeigt
        existing = {f"branch:{n}" for _, n, _ in heads} | {f"remote:{n}" for n in remotes}
        stars = sorted((x for x in load_stars(self.repo) if x in existing), key=lambda x: x.split(":", 1)[1].lower())
        if stars:
            sec = node(t, "Favoriten", "Favoriten")
            for sid in stars:
                kind, name = sid.split(":", 1)
                add(sec, name, ("log", name, kind), "starred", bold=kind == "branch" and name == current)

        sec = node(t, "Branches", "Branches")
        for head, name, track in heads:
            track = track.replace("ahead ", "↑").replace("behind ", "↓").replace(",", "")
            current = head == "*"
            add_path(sec, name, ("log", name, "branch"), "checkmark" if current else "vcs-branch",
                     bold=current, suffix=f"  {track}" if track else "")

        sec = node(t, "Remotes", "Remotes")
        for name in remotes:
            add_path(sec, name, ("log", name, "remote"), "vcs-branch", first_icon="folder-cloud")

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
            self.view = tuple(key)
            self.render_view()

    def on_double(self, item):
        key = item.data(0, Qt.UserRole)
        if key and key[0] == "stash":
            return self.act("stash", "apply", key[1])
        if not key or key[0] != "log":
            return
        self.checkout(key[1], key[2])

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
            self.stash_view.setHtml(patch_html(self.git("stash", "show", "-p", "-u", ref)))
            return
        self.stack.setCurrentIndex(1)
        self.log.clear()
        self.commit_info.clear()
        self.commit_view.clear()
        head = self.git("rev-parse", "HEAD").strip()
        out = self.git("log", "--date-order", "--decorate=full", "-n", "1000", "--date=format:%d.%m.%Y %H:%M",
                       "--format=%H%x1f%P%x1f%h%x1f%s%x1f%an%x1f%ad%x1f%D",
                       *(["--exclude=refs/stash", "--all"] if self.view[1] == "--all" else [self.view[1]]), "--")
        commits = [line.split("\x1f") for line in out.splitlines()]
        graph = build_graph([(c[0], c[1].split()) for c in commits])
        items = []
        for (full, _, h, subject, author, date, refs), row in zip(commits, graph):
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
            items.append(it)
        self.log.addTopLevelItems(items)
        self.apply_log_filter()

    def apply_log_filter(self, *_):
        """Blendet Commits aus, deren Tags/Branches, Nachricht, Autor und Hash nicht zum Suchtext passen."""
        # ponytail: durchsucht nur die geladenen 1000 Commits; ältere Tags bräuchten `git log --grep`/Ref-Suche
        text = self.log_filter.text().strip().lower()
        self.commit_delegate.filtering = bool(text)
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
        patch = diff("--patch")
        self.commit_files = [f[0] for f in file_diffs(patch)]
        self.commit_view.setHtml((self.parent_switch(plist, parent) if base else "") + patch_html(patch))

    def fill_tree(self):
        """Baut den Dateibaum erst, wenn der Tab sichtbar ist (bei großen Repos teuer)."""
        if self.detail.currentIndex() != 2 or not self.detail_hash or self.tree_hash == self.detail_hash:
            return
        self.tree_hash = h = self.detail_hash
        # ponytail: bei sehr großen Repos (100k+ Dateien) langsam; dann Ordner erst beim Aufklappen laden
        paths = [p for p in self.git("ls-tree", "-r", "--name-only", "-z", h).split("\0") if p]
        # Ordner vor Dateien, jeweils alphabetisch – wie im Dateimanager
        paths.sort(key=lambda p: [(0, d.lower()) for d in p.split("/")[:-1]] + [(1, p.rsplit("/", 1)[-1].lower())])
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
        menu.addAction("Im Editor öffnen", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(full)))
        menu.addAction("Ordner öffnen",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(full))))
        menu.exec(widget.viewport().mapToGlobal(pos))

    def show_diff(self, path, cached):
        if not path:
            return
        text = self.git("diff", "--cached", "--", path) if cached else self.git("diff", "--", path)
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
        # Zeilenweise geht nicht bei gelöschten Dateien (Git verlangt dort den ganzen Inhalt)
        selectable = "\ndeleted file mode" not in split_hunks(text)[0]
        bar = self.diff.verticalScrollBar()
        pos = bar.value()  # Scrollposition beim Neuzeichnen behalten
        page, self.diff.rowmap = diff_html(text, "Hunk unstagen" if cached else "Hunk stagen", self.sel_lines, selectable)
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


def git_out(repo, *args):
    """git-Ausgabe für Repos ohne eigenen Tab (Repository-Übersicht)."""
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", stdin=subprocess.DEVNULL, env=GIT_ENV)
    return r.stdout if r.returncode == 0 else ""


MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


def relative_time(ts, now=None):
    """Unix-Zeit -> „vor 3 Stunden“, „gestern“ usw."""
    d = int((now or time.time()) - ts)
    for limit, unit, one, many in ((60, 1, "gerade eben", "gerade eben"), (3600, 60, "vor 1 Minute", "vor {} Minuten"),
                                   (86400, 3600, "vor 1 Stunde", "vor {} Stunden"),
                                   (30 * 86400, 86400, "gestern", "vor {} Tagen"),
                                   (365 * 86400, 30 * 86400, "vor 1 Monat", "vor {} Monaten")):
        if d < limit:
            n = max(1, d // unit)
            return one if n == 1 else many.format(n)
    n = d // (365 * 86400)
    return "vor 1 Jahr" if n == 1 else f"vor {n} Jahren"


def monthly_series(rows, top=7):
    """[(autor, "JJJJ-MM")] -> (monate, [(autor, zähler)]): die `top` aktivsten Autoren, Rest als „Andere“.

    Die Monate sind lückenlos vom ersten bis zum letzten Commit.
    """
    if not rows:
        return [], []
    first, last = min(m for _, m in rows), max(m for _, m in rows)
    y, mo = int(first[:4]), int(first[5:])
    months = []
    while f"{y:04d}-{mo:02d}" <= last:
        months.append(f"{y:04d}-{mo:02d}")
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    index = {m: i for i, m in enumerate(months)}
    totals = {}
    for author, _ in rows:
        totals[author] = totals.get(author, 0) + 1
    leaders = sorted(totals, key=lambda a: (-totals[a], a))[:top]
    series = {a: [0] * len(months) for a in leaders}
    other = [0] * len(months)
    for author, month in rows:
        (series[author] if author in series else other)[index[month]] += 1
    result = [(a, series[a]) for a in leaders]
    if any(other):
        result.append(("Andere", other))
    return months, result


# Kategorische Palette für den dunklen Hintergrund (geprüft auf Farbsehschwächen); „Andere“ ist neutral grau
CHART_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"]
OTHER_COLOR = "#8a8a8a"


class CommitChart(QWidget):
    """Liniendiagramm „Commits pro Monat“ je Autor, mit Fadenkreuz und Tooltip beim Überfahren."""

    def __init__(self):
        super().__init__(mouseTracking=True, minimumHeight=380)
        self.months, self.series, self.hover = [], [], None

    def set_data(self, months, series):
        self.months, self.series, self.hover = months, series, None
        self.update()

    def color(self, i, name):
        return QColor(OTHER_COLOR if name == "Andere" else CHART_COLORS[i % len(CHART_COLORS)])

    def legend_rows(self, fm, width):
        """Legende in Zeilen umbrechen: [[(x, i, name)], ...]."""
        rows, row, x = [], [], 0
        for i, (name, _) in enumerate(self.series):
            w = 22 + fm.horizontalAdvance(name) + 18
            if row and x + w > width:
                rows.append(row)
                row, x = [], 0
            row.append((x, i, name))
            x += w
        return rows + ([row] if row else [])

    def plot_rect(self):
        fm = self.fontMetrics()
        legend_h = (len(self.legend_rows(fm, self.width() - 60)) * (fm.height() + 6)) if len(self.series) > 1 else 0
        return QRectF(52, 12, max(10, self.width() - 70), max(10, self.height() - 12 - 46 - legend_h))

    def x_at(self, r, i):
        return r.left() + (r.width() * i / max(1, len(self.months) - 1))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = p.fontMetrics()
        dim, grid = QColor(COLORS["dim"]), QColor("#303034")
        if not self.months:
            p.setPen(dim)
            p.drawText(self.rect(), Qt.AlignCenter, "Keine Commits.")
            return
        r = self.plot_rect()
        peak = max(max(c) for _, c in self.series) or 1
        raw = peak / 5
        mag = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 1
        step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
        top = step * -(-peak // step)
        y_of = lambda v: r.bottom() - r.height() * v / top

        # Raster und Achsenbeschriftung zurückhaltend
        for v in range(0, int(top) + 1, int(step)):
            y = y_of(v)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(dim)
            p.drawText(QRectF(0, y - 8, r.left() - 8, 16), Qt.AlignRight | Qt.AlignVCenter, str(v))
        every = max(1, -(-len(self.months) // max(1, int(r.width() // 70))))
        for i in range(0, len(self.months), every):
            y, m = self.months[i].split("-")
            label = f"{MONTHS[int(m) - 1]} {y}"
            x = min(max(self.x_at(r, i), 40), self.width() - 40)  # Randbeschriftungen nicht abschneiden
            p.drawText(QRectF(x - 40, r.bottom() + 6, 80, 18), Qt.AlignCenter, label)

        # Linien: „Andere“ zuerst, damit sie unter den benannten Autoren liegt
        order = sorted(range(len(self.series)), key=lambda i: self.series[i][0] != "Andere")
        for i in order:
            name, counts = self.series[i]
            path = QPainterPath(QPointF(self.x_at(r, 0), y_of(counts[0])))
            for j, c in enumerate(counts[1:], 1):
                path.lineTo(self.x_at(r, j), y_of(c))
            p.setPen(QPen(self.color(i, name), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)

        # Fadenkreuz am überfahrenen Monat
        if self.hover is not None:
            x = self.x_at(r, self.hover)
            p.setPen(QPen(QColor("#6a6a70"), 1, Qt.DashLine))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            for i, (name, counts) in enumerate(self.series):
                if counts[self.hover]:
                    p.setPen(QPen(QColor(COLORS["base"]), 2))
                    p.setBrush(self.color(i, name))
                    p.drawEllipse(QPointF(x, y_of(counts[self.hover])), 4.5, 4.5)

        # Legende unter dem Diagramm (Text in Textfarbe, Farbe nur am Strich)
        if len(self.series) > 1:
            y0 = r.bottom() + 34
            for row_i, row in enumerate(self.legend_rows(fm, self.width() - 60)):
                y = y0 + row_i * (fm.height() + 6)
                for x, i, name in row:
                    x += r.left()
                    p.setPen(QPen(self.color(i, name), 3, Qt.SolidLine, Qt.RoundCap))
                    p.drawLine(QPointF(x, y + fm.height() / 2), QPointF(x + 16, y + fm.height() / 2))
                    p.setPen(QColor(COLORS["text"]))
                    p.drawText(QPointF(x + 22, y + fm.ascent()), name)

    def mouseMoveEvent(self, event):
        if not self.months:
            return
        r = self.plot_rect()
        pos = event.position()
        if not r.adjusted(-10, -10, 10, 10).contains(pos):
            return self.leaveEvent(None)
        i = round((pos.x() - r.left()) / max(1, r.width()) * (len(self.months) - 1))
        i = min(max(i, 0), len(self.months) - 1)
        if i != self.hover:
            self.hover = i
            self.update()
            y, m = self.months[i].split("-")
            lines = [f"<b>{MONTHS[int(m) - 1]} {y}</b>"]
            values = sorted(((c[i], n) for n, c in self.series if c[i]), reverse=True)
            lines += [f"{html.escape(n)}: {v}" for v, n in values] or ["keine Commits"]
            QToolTip.showText(QCursor.pos(), "<br>".join(lines), self)

    def leaveEvent(self, _event):
        self.hover = None
        QToolTip.hideText()
        self.update()


def group_repos(known, folders, folder_of):
    """-> [(ordner, [pfade])]: eigene Ordner in ihrer Reihenfolge, zuletzt (None, Repos ohne Ordner).

    Repos sind innerhalb jeder Gruppe nach Namen sortiert; Zuordnungen zu gelöschten Ordnern zählen als „ohne“.
    """
    key = lambda p: (os.path.basename(p).lower(), p)
    groups = [(f, sorted((p for p in known if folder_of.get(p) == f), key=key)) for f in folders]
    return groups + [(None, sorted((p for p in known if folder_of.get(p) not in folders), key=key))]


class RepoTree(QTreeWidget):
    """Repository-Liste, in der man Repos per Drag & Drop in Ordner zieht."""
    dropped = Signal()

    def dropEvent(self, event):
        super().dropEvent(event)
        self.dropped.emit()


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
        sv.addWidget(QLabel("<b style='font-size:12pt'>Commits pro Monat</b>"))
        sv.addWidget(self.chart)
        sv.addStretch()
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
            self.stats_for = path
            return
        self.open_btn.setEnabled(True)
        last = git_out(path, "log", "-1", "--format=%ct").strip()
        self.last_label.setText(f"Letzter Commit: <b>{relative_time(int(last))}</b>" if last else "Noch keine Commits.")
        self.show_summary(path)
        self.stats_for = None
        self.load_stats()

    def show_summary(self, path):
        g = lambda *a: git_out(path, *a).strip()
        dim, e = COLORS["dim"], html.escape
        first = g("log", "--max-parents=0", "--format=%cd", "--date=format:%d.%m.%Y", "-1")
        rows = [
            ("Aktueller Branch", g("branch", "--show-current") or "(detached)"),
            ("Commits (alle Branches)", g("rev-list", "--count", "--all") or "0"),
            ("Autoren", str(len(g("shortlog", "-sn", "--all").splitlines()))),
            ("Branches", str(len(g("for-each-ref", "--format=x", "refs/heads").splitlines()))),
            ("Tags", str(len(g("for-each-ref", "--format=x", "refs/tags").splitlines()))),
            ("Remote origin", g("remote", "get-url", "origin") or "–"),
            ("Lokale Änderungen", f"{len(g('status', '--porcelain').splitlines())} Datei(en)"),
            ("Erster Commit", first or "–"),
        ]
        self.summary.setHtml("<table cellspacing='8'>" + "".join(
            f"<tr><td style='color:{dim}'>{e(k)}</td><td><b>{e(v)}</b></td></tr>" for k, v in rows) + "</table>")

    def load_stats(self):
        """Statistik erst berechnen, wenn der Tab sichtbar ist (git log über alle Commits)."""
        if self.pages.currentIndex() != 1 or not self.current or self.stats_for == self.current:
            return
        self.stats_for = self.current
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out = git_out(self.current, "log", "--all", "--no-merges", "--format=%aN%x1f%ad", "--date=format:%Y-%m")
        finally:
            QApplication.restoreOverrideCursor()
        rows = [tuple(line.split("\x1f", 1)) for line in out.splitlines() if "\x1f" in line]
        self.chart.set_data(*monthly_series(rows))


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
        a_pull = action("Pull", "vcs-pull", lambda t: t.act_async("pull"))
        a_push = action("Push", "vcs-push", lambda t: t.push())
        a_stash = action("Stash", "vcs-stash", lambda t: t.stash())
        a_pop = action("Stash Pop", "vcs-stash-pop", lambda t: t.act("stash", "pop"))
        a_branch = action("Neuer Branch", "vcs-branch", lambda t: t.new_branch())
        a_term = action("Terminal", "utilities-terminal", self.terminal)
        a_refresh = action("Aktualisieren", "view-refresh", lambda t: t.refresh(), "F5")
        a_close = action("Tab schließen", "tab-close", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W",
                         on_tab=False)
        self.repo_actions = [a_fetch, a_pull, a_push, a_stash, a_pop, a_branch, a_term, a_refresh]

        menu = self.menuBar().addMenu("Datei")
        menu.addAction(a_open)
        menu.addAction(a_close)
        menu.addSeparator()
        menu.addAction("Beenden", QKeySequence("Ctrl+Q"), self.close)
        menu = self.menuBar().addMenu("Repository")
        for a in (a_fetch, a_pull, a_push, None, a_stash, a_pop, None, a_branch, a_term, None, a_refresh):
            menu.addSeparator() if a is None else menu.addAction(a)

        tb = QToolBar(objectName="main", movable=False, floatable=False)
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.toggleViewAction().setVisible(False)
        self.addToolBar(tb)
        for a in (a_open, a_fetch, a_pull, a_push):
            tb.addAction(a)
        stash_btn = QToolButton(popupMode=QToolButton.MenuButtonPopup, toolButtonStyle=Qt.ToolButtonTextUnderIcon)
        stash_btn.setDefaultAction(a_stash)
        stash_menu = QMenu(stash_btn)
        stash_menu.addAction(a_pop)
        stash_btn.setMenu(stash_menu)
        tb.addWidget(stash_btn)
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

    def update_page(self):
        """Toolbar nur für Repo-Tabs aktiv; im „Neuer Tab“ eine Begrüßung statt Repo/Branch."""
        is_repo = isinstance(self.tabs.currentWidget(), RepoTab)
        for a in self.repo_actions:
            a.setEnabled(is_repo)
        if not is_repo:
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


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        out = " M a.txt\0M  b.txt\0MM c.txt\0?? d.txt\0R  new.txt\0old.txt\0"
        out += "UU e.txt\0AA f.txt\0"
        assert parse_status(out) == ([("a.txt", "M"), ("c.txt", "M"), ("d.txt", "?")],
                                     [("b.txt", "M"), ("c.txt", "M"), ("new.txt", "R")], ["e.txt", "f.txt"])
        d = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n@@ -9,2 +9,2 @@\n c\n-d\n+e\n"
        head, hunks = split_hunks(d)
        assert head == "diff --git a/x b/x\n--- a/x\n+++ b/x\n" and hunks == ["@@ -1 +1 @@\n-a\n+b\n",
                                                                           "@@ -9,2 +9,2 @@\n c\n-d\n+e\n"]
        text = ("a\n<<<<<<< HEAD\nmein\n||||||| base\nalt\n=======\ndein\n>>>>>>> feat\nb\n"
                "<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> feat\n")
        segs = parse_conflicts(text)
        assert segs == ["a\n", ("mein\n", "dein\n", "HEAD", "feat"), "b\n", ("x\n", "y\n", "HEAD", "feat")]
        assert resolve_conflicts(segs, ["dein\n", "x\ny\n"]) == "a\ndein\nb\nx\ny\n"
        assert parse_conflicts("<<<<<<< kaputt\nz\n") == ["<<<<<<< kaputt\nz\n"]
        # Linear: alles in Lane 0. Merge M(A, F), F(A), A: F in Lane 1, beide laufen in A zusammen.
        assert [r[0] for r in build_graph([("c", ["b"]), ("b", ["a"]), ("a", [])])] == [0, 0, 0]
        g = build_graph([("M", ["A", "F"]), ("F", ["A"]), ("A", [])])
        assert [r[0] for r in g] == [0, 1, 0] and g[0][2] and (1, 0, 0, .5, 1) in g[2][1]
        # Nachrücken: b0 beendet Lane 1, Lane 2 (c, Farbe 2) rückt in derselben Zeile auf 1.
        g = build_graph([("a1", ["root"]), ("b1", ["b0"]), ("c1", ["c0"]), ("b0", []),
                         ("c0", ["root"]), ("root", [])])
        assert [r[0] for r in g] == [0, 1, 2, 1, 1, 0] and (2, 0, 1, 1, 2) in g[3][1]
        assert g[4][3] == 2  # c behält seine Farbe
        assert parse_refs("HEAD -> refs/heads/main, tag: refs/tags/v1, refs/remotes/origin/HEAD, "
                          "refs/remotes/origin/main, refs/remotes/origin/x, refs/stash") == [
            ("main", "head", True), ("origin/x", "remote", False), ("v1", "tag", False)]
        # Zeilen: aus „-a +b +c“ nur „+c“ stagen -> a bleibt, b fehlt; Unstagen umgekehrt.
        d = "--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n-a\n+b\n+c\n"
        assert line_patch(d, {(0, 3)}) == "--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n a\n+c\n"
        assert line_patch(d, {(0, 3)}, reverse=True) == "--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n b\n+c\n"
        d = "@@ -1,2 +1,2 @@\n x\n-y\n\\ No newline at end of file\n+Y\n\\ No newline at end of file\n"
        assert line_patch(d, {(0, 4)}) == ("@@ -1,2 +1,2 @@\n x\n-y\n\\ No newline at end of file\n+y\n+Y\n"
                                           "\\ No newline at end of file\n")
        patch = ("diff --git a/x b/x\nindex 1..2 100644\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
                 "diff --git a/o b/n\nsimilarity index 90%\nrename from o\nrename to n\n"
                 "diff --git a/neu b/neu\nnew file mode 100644\n--- /dev/null\n+++ b/neu\n@@ -0,0 +1 @@\n+z\n")
        assert [f[:3] for f in file_diffs(patch)] == [("x", "x", "M"), ("n", "o → n", "R"), ("neu", "neu", "A")]
        months, series = monthly_series([("A", "2024-11"), ("A", "2025-01"), ("B", "2025-01"), ("C", "2025-01")], top=2)
        assert months == ["2024-11", "2024-12", "2025-01"]
        assert series == [("A", [1, 0, 1]), ("B", [0, 0, 1]), ("Andere", [0, 0, 1])]
        assert relative_time(0, now=30) == "gerade eben" and relative_time(0, now=3 * 3600) == "vor 3 Stunden"
        assert relative_time(0, now=86400 + 5) == "gestern" and relative_time(0, now=2 * 365 * 86400) == "vor 2 Jahren"
        g = group_repos(["/x/zeta", "/x/Alpha", "/y/beta", "/y/gamma"], ["Arbeit"],
                        {"/y/beta": "Arbeit", "/y/gamma": "Gelöscht"})
        assert g == [("Arbeit", ["/y/beta"]), (None, ["/x/Alpha", "/y/gamma", "/x/zeta"])]
        print("ok")
        sys.exit(0)
    app = QApplication(sys.argv)
    setup_app(app)
    # Ohne Argumente: letzte Sitzung, sonst das aktuelle Verzeichnis (falls Repo)
    win = MainWindow(sys.argv[1:])
    win.show()
    sys.exit(app.exec())
