"""Programmstart: normales Fenster oder (von Git/SSH aufgerufen) der Zugangsdaten-Dialog."""
import sys

from PySide6.QtWidgets import QApplication

from .mainwindow import MainWindow
from .theme import setup_app
from .widgets import ask_credentials, install_askpass


def main():
    if sys.argv[1:2] == ["--askpass"]:  # von Git/SSH aufgerufen: Antwort auf stdout, Abbruch = Exit-Code 1
        app = QApplication(sys.argv[:1])
        setup_app(app)
        text, ok = ask_credentials(" ".join(sys.argv[2:]))
        if ok:
            print(text)
        sys.exit(0 if ok else 1)
    app = QApplication(sys.argv)
    setup_app(app)
    install_askpass()
    # Ohne Argumente: letzte Sitzung, sonst die Repository-Verwaltung
    win = MainWindow(sys.argv[1:])
    win.show()
    sys.exit(app.exec())
