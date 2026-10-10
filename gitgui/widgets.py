"""Wiederverwendbare Bausteine: Hintergrund-Aufgaben, Zugangsdaten-Dialog, Delegates, Diagramm, Listen."""
import html
import os
import shlex
import sys
import threading

from PySide6.QtCore import QObject, QPointF, QRectF, QUrl, Qt, Signal, Slot

from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPainterPath, QPen

from PySide6.QtWidgets import (
    QInputDialog, QLineEdit, QStyle, QStyledItemDelegate, QTextBrowser, QToolTip,
    QTreeWidget, QWidget,
)

from .theme import CHART_COLORS, COLORS, LANE_COLORS, LANE_W, OTHER_COLOR
from .core import GIT_ENV, MONTHS


class Background(QObject):
    """func() in einem Hintergrund-Thread ausführen, danach callback(ergebnis) im GUI-Thread.

    func darf nur rechnen und git aufrufen (git_out), keine Widgets anfassen. Bei einer Ausnahme
    bekommt callback None.
    """
    finished = Signal(object)

    def __init__(self, parent, func, callback):
        super().__init__(parent)
        self.callback = callback
        self.finished.connect(self.deliver)  # Empfänger lebt im GUI-Thread -> Aufruf wird dorthin übergeben
        threading.Thread(target=self.run, args=(func,), daemon=True).start()

    def run(self, func):
        try:
            result = func()
        except Exception:  # noqa: BLE001 – im Thread verschluckt würde der Aufrufer sonst ewig warten
            result = None
        self.finished.emit(result)

    @Slot(object)
    def deliver(self, result):
        self.callback(result)
        self.deleteLater()


def ask_credentials(prompt):
    """Dialog für Git/SSH-Zugangsdaten (als GIT_ASKPASS/SSH_ASKPASS aufgerufen). Rückgabe (text, ok)."""
    lower = prompt.lower()
    secret = any(word in lower for word in ("password", "passphrase", "token", "passwort"))
    if "username" in lower:
        label = "Benutzername"
    elif "passphrase" in lower:
        label = "Passphrase für den SSH-Schlüssel"
    elif secret:
        label = "Passwort oder Token"
    else:
        label = "Eingabe"
    return QInputDialog.getText(None, "Git braucht Zugangsdaten", f"{label}:\n\n{prompt.strip()}",
                                QLineEdit.Password if secret else QLineEdit.Normal)


def install_askpass():
    """Kleines Startskript, das Git/SSH bei Passwortabfragen aufrufen; zeigt ask_credentials als Dialog."""
    folder = os.path.join(os.path.expanduser("~"), ".cache", "git_gui")
    path = os.path.join(folder, "askpass.sh")
    package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = (f"#!/bin/sh\nPYTHONPATH={shlex.quote(package_parent)}${{PYTHONPATH:+:$PYTHONPATH}} "
              f"exec {shlex.quote(sys.executable)} -m gitgui --askpass \"$@\"\n")
    os.makedirs(folder, exist_ok=True)
    if not os.path.exists(path) or open(path).read() != script:
        with open(path, "w") as f:
            f.write(script)
        os.chmod(path, 0o755)
    GIT_ENV.update({"GIT_ASKPASS": path, "SSH_ASKPASS": path, "SSH_ASKPASS_REQUIRE": "prefer"})


# Datenrollen der Verlaufs-Einträge
GRAPH_ROLE, REFS_ROLE, HASH_ROLE, HEAD_ROLE, EXTRA_ROLE = (Qt.ItemDataRole.UserRole + i for i in range(5))


NODE_ROLE = Qt.ItemDataRole.UserRole + 10  # Pfad von Abschnitten/Ordnern in der Seitenleiste


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
                fill, border, fg = QColor(COLORS["tag_fill"]), QColor(COLORS["tag_border"]), QColor(COLORS["tag_text"])
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


class CommitChart(QWidget):
    """Liniendiagramm „Commits pro Monat“ je Autor, mit Fadenkreuz und Tooltip beim Überfahren."""

    def __init__(self):
        super().__init__(mouseTracking=True, minimumHeight=380)
        self.months, self.series, self.hover, self.message = [], [], None, "Keine Commits."

    def set_data(self, months, series, message="Keine Commits."):
        self.months, self.series, self.hover, self.message = months, series, None, message
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
        dim, grid = QColor(COLORS["dim"]), QColor(COLORS["grid"])
        if not self.months:
            p.setPen(dim)
            p.drawText(self.rect(), Qt.AlignCenter, self.message)
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
            p.setPen(QPen(QColor(COLORS["crosshair"]), 1, Qt.DashLine))
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


class RepoTree(QTreeWidget):
    """Repository-Liste, in der man Repos per Drag & Drop in Ordner zieht."""
    dropped = Signal()

    def dropEvent(self, event):
        super().dropEvent(event)
        self.dropped.emit()
