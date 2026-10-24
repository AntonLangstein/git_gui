"""Farben und Design (dunkel/hell), Stylesheet und App-Grundeinstellungen."""
import os
import string

try:  # ohne Pygments gibt es einfach keine Syntaxfarben
    from pygments.styles import get_style_by_name
except ImportError:
    get_style_by_name = None

from PySide6.QtCore import QSettings, Qt

from PySide6.QtGui import QColor, QIcon, QPalette

from PySide6.QtWidgets import QApplication


# Farben angelehnt an Fork; COLORS wird beim Umschalten des Designs an Ort und Stelle aktualisiert
THEMES = {
    "dark": {
        "window": "#2b2b2e", "base": "#1f1f22", "alt": "#262629", "text": "#dddddd", "dim": "#8a8a8a",
        "button": "#3a3a3e", "highlight": "#46464c", "border": "#141416", "accent": "#3794ff",
        "toolbar": "#333337", "hover": "#45454a", "tabbar": "#262629", "tab_sel": "#38383c", "tab_sel_text": "#ffffff",
        "tab_text": "#9a9a9a", "tab_hover": "#2f2f33", "sidebar": "#252528", "input": "#1b1b1d", "panel": "#2b2b2e",
        "lineno": "#6a6a6a", "hunk_bg": "#2c3340", "grid": "#303034", "crosshair": "#6a6a70", "conflict": "#e5534b",
        "tag_fill": "#4a4a50", "tag_border": "#8b949e", "tag_text": "#e6e6e6", "commit_btn": "#2f6fd0",
        "commit_hover": "#3a7fe6", "add_bg": "#1e3a26", "del_bg": "#46252a", "add_sel": "#2f6b40", "del_sel": "#7a3038",
        "add_mark": "#2f7a45", "del_mark": "#8a3a40", "empty_bg": "#262629", "syntax": "one-dark",
        # Diagramm: kategorische Palette für dunklen Hintergrund (auf Farbsehschwächen geprüft)
        "chart": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"],
    },
    "light": {
        "window": "#f3f3f5", "base": "#ffffff", "alt": "#f5f5f7", "text": "#1f1f1f", "dim": "#6b6b6b",
        "button": "#e4e4e7", "highlight": "#d6e4f7", "border": "#cfcfd4", "accent": "#0a63d6",
        "toolbar": "#ececee", "hover": "#dcdce0", "tabbar": "#e4e4e7", "tab_sel": "#ffffff", "tab_sel_text": "#000000",
        "tab_text": "#555555", "tab_hover": "#f0f0f2", "sidebar": "#f7f7f9", "input": "#ffffff", "panel": "#ececee",
        "lineno": "#9a9a9a", "hunk_bg": "#e7eef8", "grid": "#e4e4e8", "crosshair": "#9a9aa0", "conflict": "#c62828",
        "tag_fill": "#e4e4e7", "tag_border": "#8b949e", "tag_text": "#333333", "commit_btn": "#1f6feb",
        "commit_hover": "#388bfd", "add_bg": "#e6f6e9", "del_bg": "#fbe9eb", "add_sel": "#b7e4c2", "del_sel": "#f4c3c9",
        "add_mark": "#abf2bc", "del_mark": "#ffc0c6", "empty_bg": "#f3f3f5", "syntax": "default",
        "chart": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"],
    },
}


COLORS = dict(THEMES["dark"])


STYLE = string.Template("""
QToolBar#main { background: $toolbar; border: none; border-bottom: 1px solid $border; padding: 2px 6px; spacing: 2px; }
QToolBar#main QToolButton { padding: 2px 8px; border-radius: 4px; }
QToolBar#main QToolButton:hover { background: $hover; }
QLabel#repoInfo { padding: 0 24px; }
QTabWidget#repos::pane { border: none; }
QTabWidget#repos > QTabBar { background: $tabbar; }
QTabWidget#repos > QTabBar::tab { background: $tabbar; color: $tab_text; padding: 6px 14px; border: none;
                                  border-right: 1px solid $border; border-bottom: 1px solid $border; min-width: 110px; }
QTabWidget#repos > QTabBar::tab:selected { background: $tab_sel; color: $tab_sel_text; }
QTabWidget#repos > QTabBar::tab:hover:!selected { background: $tab_hover; }
QTabWidget#detail::pane { border: none; border-top: 1px solid $button; }
QTabWidget#detail > QTabBar::tab { background: transparent; padding: 7px 22px; border: none; font-weight: bold; color: $tab_text; }
QTabWidget#detail > QTabBar::tab:selected { color: $accent; border-bottom: 2px solid $accent; }
QWidget#sidebarPane, QTreeWidget#sidebar { background: $sidebar; border: none; }
QTreeWidget#sidebar::item { padding: 2px 0; }
QLabel#repoTitle { font-weight: bold; font-size: 11pt; padding: 8px 10px 4px 10px; }
QLineEdit#filter { background: $input; border: 1px solid $button; border-radius: 4px; padding: 3px 6px; margin: 4px 8px; }
QTreeWidget#log { border: none; }
QHeaderView::section { background: $panel; color: $tab_text; border: none; border-right: 1px solid $border;
                       border-bottom: 1px solid $border; padding: 3px 6px; }
QPlainTextEdit, QTextBrowser, QListWidget { border: none; }
QLabel#lineStat { background: $input; border-radius: 4px; padding: 0 5px; margin: 1px 4px; font-weight: bold; }
QSplitter::handle { background: $border; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QStatusBar { background: $panel; color: $tab_text; }
QMenuBar { background: $panel; }
QMenuBar::item:selected { background: $hover; }
QFrame#listHeader, QFrame#diffHeader { background: $panel; border-bottom: 1px solid $border; }
QFrame#listHeader QLabel, QFrame#diffHeader QLabel { font-weight: bold; }
QFrame#listHeader QPushButton, QFrame#diffHeader QPushButton { padding: 2px 10px; }
QTreeWidget#files::item { padding: 2px 4px; }
QWidget#commitBox { background: $sidebar; }
QLineEdit#subject, QPlainTextEdit#body { background: $input; border: 1px solid $button; border-radius: 4px; padding: 4px; }
QPushButton#commitBtn { background: $commit_btn; color: white; border: none; border-radius: 4px; padding: 6px 16px; font-weight: bold; }
QPushButton#commitBtn:hover { background: $commit_hover; }
QPushButton#commitBtn:disabled { background: $button; color: $lineno; }
QLabel#managerTitle { font-size: 17pt; font-weight: bold; padding: 10px 14px; }
QLabel#repoHeadline { font-size: 16pt; font-weight: bold; }
QFrame#banner { background: rgba(229, 83, 75, 45); border-radius: 6px; }
""")


_syntax = {"style": None}  # Pygments-Stil passend zum Design


def resolve_theme(name):
    """"system" -> "light"/"dark" je nach Systemeinstellung."""
    if name == "system":
        return "light" if QApplication.styleHints().colorScheme() == Qt.ColorScheme.Light else "dark"
    return name if name in THEMES else "dark"


def apply_theme(app, name):
    """Design anwenden: Farben, Palette, Stylesheet, Syntax- und Diagrammfarben."""
    theme = THEMES[resolve_theme(name)]
    COLORS.update(theme)
    CHART_COLORS[:] = theme["chart"]
    if get_style_by_name is not None:
        _syntax["style"] = get_style_by_name(theme["syntax"])
    pal = QPalette()
    for role, key in ((QPalette.Window, "window"), (QPalette.WindowText, "text"), (QPalette.Base, "base"),
                      (QPalette.AlternateBase, "alt"), (QPalette.Text, "text"), (QPalette.Button, "button"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "highlight"),
                      (QPalette.HighlightedText, "text"), (QPalette.ToolTipBase, "window"),
                      (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "dim"), (QPalette.Link, "accent"),
                      (QPalette.Mid, "button"), (QPalette.Midlight, "highlight"), (QPalette.Dark, "border")):
        pal.setColor(role, QColor(COLORS[key]))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(COLORS["lineno"]))
    app.setPalette(pal)
    app.setStyleSheet(STYLE.substitute(COLORS))


def setup_app(app):
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg")))
    app.setDesktopFileName("git_gui")  # ordnet das Fenster unter Wayland dem Starter git_gui.desktop zu
    apply_theme(app, QSettings("git_gui", "git_gui").value("theme", "dark"))


LANE_COLORS = ["#4c9aff", "#e5534b", "#57ab5a", "#c69026", "#986ee2", "#39c5cf", "#e0823d", "#d16d9e"]


LANE_W = 14


STATUS_COLORS = {"A": "#57ab5a", "M": "#c69026", "D": "#e5534b", "R": "#4c9aff", "C": "#4c9aff"}


STATUS_BADGES = {"M": ("M", "#c69026"), "A": ("+", "#57ab5a"), "?": ("+", "#57ab5a"), "D": ("−", "#e5534b"),
                 "R": ("R", "#4c9aff"), "C": ("C", "#4c9aff"), "T": ("T", "#c69026")}


# Kategorische Palette des aktuellen Designs (siehe THEMES "chart"); „Andere“ ist neutral grau
CHART_COLORS = list(THEMES["dark"]["chart"])


OTHER_COLOR = "#8a8a8a"
