#!/bin/sh
# Installiert Git GUI aus diesem Ordner für den aktuellen Benutzer:
# Befehl `gitgui` in ~/.local/bin und einen Eintrag im Anwendungsmenü (KDE, GNOME, …).
#   ./install.sh              installieren bzw. aktualisieren
#   ./install.sh --uninstall  wieder entfernen
set -eu

DIR=$(cd "$(dirname "$0")" && pwd)
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP="$APPS/git_gui.desktop"

refresh_menu() {
    update-desktop-database "$APPS" 2>/dev/null || true
    kbuildsycoca6 >/dev/null 2>&1 || true
}

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$BIN/gitgui" "$DESKTOP"
    refresh_menu
    echo "Git GUI entfernt (Einstellungen in ~/.config/git_gui bleiben erhalten)."
    exit 0
fi

command -v git >/dev/null || { echo "git fehlt – bitte zuerst installieren." >&2; exit 1; }
python3 -c "import PySide6" 2>/dev/null || {
    echo "PySide6 fehlt – z.B. 'sudo pacman -S pyside6' oder 'pip install PySide6'." >&2; exit 1; }
python3 -c "import pygments" 2>/dev/null || echo "Hinweis: ohne Pygments gibt es keine Syntaxfarben im Diff (optional)."

mkdir -p "$BIN" "$APPS"
chmod +x "$DIR/git_gui.py"
ln -sf "$DIR/git_gui.py" "$BIN/gitgui"
cat > "$DESKTOP" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Git GUI
GenericName=Git-Oberfläche
Comment=Git-Repositories verwalten, im Stil von Fork
Exec=$BIN/gitgui %F
Icon=$DIR/gitgui/icon.svg
Terminal=false
Categories=Development;RevisionControl;
Keywords=git;fork;commit;branch;
StartupWMClass=git_gui
DESKTOP
refresh_menu

echo "Installiert: Befehl 'gitgui' ($BIN) und Menü-Eintrag 'Git GUI'."
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "Hinweis: $BIN ist nicht im PATH – im Menü funktioniert es trotzdem." ;;
esac
