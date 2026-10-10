"""Diff-Darstellung als HTML: Zeilennummern, Syntaxfarben, Wort-Diff, Nebeneinander-Ansicht."""
import difflib
import html
import itertools
import os
import re

try:  # Syntaxfarben im Diff sind optional
    from pygments.lexers import get_lexer_for_filename
    from pygments.util import ClassNotFound
except ImportError:
    get_lexer_for_filename = None

from PySide6.QtCore import QRectF, Qt

from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

from .theme import COLORS, STATUS_BADGES, _syntax
from .core import file_diffs, split_hunks


FANCY_LIMIT = 4000  # ab so vielen Diff-Zeilen ohne Syntaxfarben/Wort-Diff, damit es schnell bleibt


TOKEN = re.compile(r"\w+|\s+|[^\w\s]")


_lexers = {}


def lexer_for(path):
    """Pygments-Lexer passend zum Dateinamen (zwischengespeichert) oder None."""
    if not path or get_lexer_for_filename is None:
        return None
    key = os.path.splitext(path)[1] or os.path.basename(path)
    if key not in _lexers:
        try:
            _lexers[key] = get_lexer_for_filename(path, stripnl=False, ensurenl=False)
        except ClassNotFound:
            _lexers[key] = None
    return _lexers[key]


def syntax_colors(text, lexer):
    """Vordergrundfarbe pro Zeichen (None = Standard)."""
    colors = [None] * len(text)
    if lexer is None or _syntax["style"] is None:
        return colors
    # ponytail: jede Zeile einzeln gelext – mehrzeilige Strings/Kommentare werden nicht erkannt
    pos = 0
    for ttype, value in lexer.get_tokens(text):
        color = _syntax["style"].style_for_token(ttype)["color"]
        for k in range(pos, min(pos + len(value), len(text))):
            colors[k] = f"#{color}" if color else None
        pos += len(value)
    return colors


def word_marks(a, b):
    """Zeichenbereiche, in denen sich zwei ähnliche Zeilen unterscheiden: ([(von, bis)] in a, [...] in b)."""
    ta, tb = TOKEN.findall(a), TOKEN.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    if sm.ratio() < 0.4:  # völlig verschieden: nichts hervorheben, sonst wird alles bunt
        return [], []
    oa = [0, *itertools.accumulate(map(len, ta))]
    ob = [0, *itertools.accumulate(map(len, tb))]
    ma, mb = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            if i2 > i1:
                ma.append((oa[i1], oa[i2]))
            if j2 > j1:
                mb.append((ob[j1], ob[j2]))
    return ma, mb


def hunk_marks(lines):
    """Wort-Unterschiede für Blöcke „-…“ direkt gefolgt von „+…“, paarweise: {zeilenindex: marks}."""
    marks, i = {}, 0
    while i < len(lines):
        if lines[i][:1] != "-":
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j][:1] == "-":
            j += 1
        k = j
        while k < len(lines) and lines[k][:1] == "+":
            k += 1
        for a, b in zip(range(i, j), range(j, k)):
            marks[a], marks[b] = word_marks(lines[a][1:], lines[b][1:])
        i = max(k, j)
    return marks


def code_html(text, lexer=None, marks=(), mark_bg=None):
    """Eine Code-Zeile als HTML: Syntaxfarben im Vordergrund, geänderte Wörter mit kräftigerem Hintergrund."""
    fg = syntax_colors(text, lexer)
    marked = [False] * len(text)
    for start, end in marks:
        for k in range(start, min(end, len(text))):
            marked[k] = True
    out, k = [], 0
    while k < len(text):
        j = k
        while j < len(text) and fg[j] == fg[k] and marked[j] == marked[k]:
            j += 1
        style = (f"color:{fg[k]};" if fg[k] else "") + (f"background:{mark_bg};" if marked[k] else "")
        chunk = html.escape(text[k:j])
        out.append(f"<span style='{style}'>{chunk}</span>" if style else chunk)
        k = j
    return "".join(out) or " "


def diff_html(diff, hunk_action=None, selected=(), selectable=False, path=None, split=False):
    """Diff einer Datei -> HTML wie bei Fork: Zeilennummern, Syntaxfarben, Wort-Diff; optional nebeneinander.

    hunk_action = Linktext im Hunk-Kopf; selectable = +/- Zeilen sind auswählbar (Kästchen als Hinweis),
    selected = ausgewählte Zeilen als {(hunk, zeile)}; split = alt | neu nebeneinander (ohne Zeilenauswahl).
    Rückgabe (html, rowmap): rowmap[Tabellenzeile] = (hunk, zeile) bzw. None, für Klicks auf ganze Zeilen.
    """
    _, hunks = split_hunks(diff)
    e = html.escape
    if not hunks:  # z.B. Binärdatei oder leer
        return f"<pre style='color:{COLORS['dim']}'>{e(diff) or 'Keine Änderungen.'}</pre>", []
    c = COLORS
    fancy = diff.count("\n") < FANCY_LIMIT
    lexer = lexer_for(path) if fancy else None
    rows, rowmap = [], []
    box = lambda on: (f"<span style='color:{c['accent'] if on else c['lineno']}'>{'☑' if on else '☐'}</span>")
    num = lambda n: f"<td width='44' align='right' style='color:{c['lineno']}'>{n}&nbsp;</td>"
    wrap = "pre-wrap" if split else "pre"
    # ponytail: sehr große Diffs werden als HTML langsam; bei Bedarf ab x Zeilen kürzen
    for h, hunk in enumerate(hunks):
        lines = hunk.splitlines()
        m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", lines[0])
        old, new = (int(m[1]), int(m[2])) if m else (0, 0)
        marks = hunk_marks(lines) if fancy else {}
        link = (f"<a href='hunk:{h}' style='color:{COLORS['accent']}; text-decoration:none'>{hunk_action}</a>"
                if hunk_action else "")
        rowmap.append(None)
        head = f"<td style='color:{COLORS['dim']}'{' colspan=2' if split else ''}>{e(lines[0])}</td>"
        lead = "<td width='44'></td>" if split else "<td width='18'></td><td width='44'></td><td width='44'></td>"
        rows.append(f"<tr bgcolor='{c['hunk_bg']}'>{lead}{head}<td align='right'>{link}&nbsp;</td></tr>")

        def code(i, mark_bg):
            return code_html(lines[i][1:], lexer, marks.get(i, ()), mark_bg)

        if split:
            i = 1
            while i < len(lines):
                kind = lines[i][:1]
                if kind in ("-", "+"):  # Block entfernter Zeilen neben Block hinzugefügter Zeilen
                    j = i
                    while j < len(lines) and lines[j][:1] == "-":
                        j += 1
                    k = j
                    while k < len(lines) and lines[k][:1] == "+":
                        k += 1
                    for a, b in itertools.zip_longest(range(i, j), range(j, k)):
                        left = (f"{num(old)}<td bgcolor='{c['del_bg']}' width='50%' style='white-space:{wrap}'>"
                                f"{code(a, c['del_mark'])}</td>") if a is not None else f"{num('')}<td bgcolor='{c['empty_bg']}'></td>"
                        right = (f"{num(new)}<td bgcolor='{c['add_bg']}' width='50%' style='white-space:{wrap}'>"
                                 f"{code(b, c['add_mark'])}</td>") if b is not None else f"{num('')}<td bgcolor='{c['empty_bg']}'></td>"
                        old += a is not None
                        new += b is not None
                        rowmap.append(None)
                        rows.append(f"<tr>{left}{right}</tr>")
                    i = max(k, j)
                    continue
                if kind != "\\":  # Kontextzeile auf beiden Seiten
                    same = code(i, None)
                    rowmap.append(None)
                    rows.append(f"<tr>{num(old)}<td width='50%' style='white-space:{wrap}'>{same}</td>"
                                f"{num(new)}<td width='50%' style='white-space:{wrap}'>{same}</td></tr>")
                    old += 1
                    new += 1
                i += 1
            continue

        for i, line in enumerate(lines[1:], 1):
            kind = line[:1]
            on = (h, i) in selected
            if kind == "+":
                o, n, bg, mark = "", new, c['add_sel'] if on else c['add_bg'], c['add_mark']
                new += 1
            elif kind == "-":
                o, n, bg, mark = old, "", c['del_sel'] if on else c['del_bg'], c['del_mark']
                old += 1
            elif kind == "\\":  # "\ No newline at end of file"
                o, n, bg, mark = "", "", "", None
            else:
                o, n, bg, mark = old, new, "", None
                old += 1
                new += 1
            pickable = selectable and kind in ("+", "-")
            rowmap.append((h, i) if pickable else None)
            check = box(on) if pickable else ""
            text = (f"<span style='color:{COLORS['dim']}'>{e(line)}</span>" if kind == "\\"
                    else f"<span style='color:{c['lineno']}'>{e(kind or ' ')}</span>{code(i, mark)}")
            rows.append(f"<tr{f' bgcolor={bg}' if bg else ''}>"
                        f"<td width='18' align='center'>{check}</td>{num(o)}{num(n)}"
                        f"<td width='100%' colspan='2' style='white-space:pre'>{text}</td></tr>")
    return f"<table width='100%' cellspacing='0' cellpadding='1'>{''.join(rows)}</table>", rowmap


def patch_html(patch, split=False):
    """Ganzer Commit/Stash im Fork-Stil: pro Datei eine Kopfzeile, darunter der Diff mit Zeilennummern."""
    e = html.escape
    parts = []
    for i, (path, name, status, diff) in enumerate(file_diffs(patch)):
        char, color = STATUS_BADGES.get(status, (status, COLORS["dim"]))
        parts.append(f"<a name='file{i}'></a><table width='100%' cellspacing='0' cellpadding='5'>"
                     f"<tr bgcolor='{COLORS['panel']}'><td><b style='color:{color}'>{char}</b>&nbsp; <b>{e(name)}</b></td></tr></table>")
        if split_hunks(diff)[1]:
            parts.append(diff_html(diff, path=path, split=split)[0])
        else:
            parts.append(f"<p style='color:{COLORS['dim']}'>&nbsp;Keine Textänderungen (z.B. Binärdatei oder nur Rechte).</p>")
        parts.append("<br>")
    return "".join(parts) or f"<p style='color:{COLORS['dim']}'>Keine Änderungen.</p>"


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
