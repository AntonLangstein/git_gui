# Git GUI

Eine schlanke Git-Oberfläche für Linux im Stil von [Fork](https://git-fork.com/) – eine einzige Python-Datei,
die für alles das `git`-Kommandozeilenprogramm aufruft.

## Funktionen

- **Mehrere Repositories** in Tabs; offene Tabs werden laufend gemerkt und beim nächsten Start wiederhergestellt
- **Repository-Verwaltung** im „Neuer Tab“: zuletzt geöffnete und bekannte Repos, Übersicht und Statistik
  („Commits pro Monat“ je Autor), eigene Ordner (per Rechtsklick oder Drag & Drop), Festplatte nach Repos durchsuchen
- **Verlauf** mit gezeichnetem Commit-Graph, farbigen Branch-/Tag-Labels und Autor-Avataren (Initialen)
- **Commit-Details**: Autor, Committer, Parents, Dateiliste und Diff; bei Merges umschaltbar zwischen den Parents;
  Dateibaum mit allen Dateien zum Stand des Commits
- **Lokale Änderungen**: Dateien, einzelne Hunks oder einzelne Zeilen stagen/unstagen, Änderungen verwerfen,
  Commit mit Betreff, Beschreibung und Amend
- **Branches**: wechseln, anlegen, umbenennen, löschen, mergen, rebasen – per Doppelklick oder Rechtsklick in der Seitenleiste
- **Remotes**: Fetch, Pull, Push im Hintergrund (das Fenster bleibt bedienbar), Upstream beim ersten Push,
  Remote-Branches löschen
- **Stashes**: anlegen, anwenden, poppen, löschen, Inhalt ansehen
- **Konflikte lösen** bei Merge, Rebase, Cherry-Pick und Revert: Block für Block mit editierbarem Ergebnis,
  Abbrechen/Fortsetzen über ein Banner
- Seitenleiste mit Filter, Branch-Ordnern (`feature/…`) und Ahead/Behind-Anzeige
- Dunkles Theme, Terminal im Repo-Ordner öffnen

## Voraussetzungen

- Python 3.10 oder neuer (entwickelt mit 3.14)
- [PySide6](https://pypi.org/project/PySide6/) (entwickelt mit 6.11)
- `git` (entwickelt mit 2.55)

Arch / CachyOS:

```bash
sudo pacman -S pyside6 git
```

Sonst per pip:

```bash
pip install PySide6
```

## Starten

```bash
python3 git_gui.py                 # letzte Sitzung, sonst das aktuelle Verzeichnis
python3 git_gui.py ~/repo1 ~/repo2 # bestimmte Repositories öffnen
```

## Bedienung

| Aktion | So geht's |
|---|---|
| Repository-Verwaltung | `+` neben den Tabs oder Strg+T |
| Repository öffnen | „Öffnen“ oder Strg+O |
| Tab schließen / wechseln | Strg+W / Strg+Tab, Strg+Umschalt+Tab |
| Aktualisieren | F5 (passiert auch beim Tab-Wechsel) |
| Committen | Enter im Betreff oder Strg+Enter |
| Branch auschecken | Doppelklick in der Seitenleiste |
| Branch-Aktionen | Rechtsklick auf Branch, Remote-Branch, Tag oder Stash |
| Datei stagen | Doppelklick, „Stagen“-Knopf oder Rechtsklick |
| Hunk stagen | „Hunk stagen“ im Diff-Kopf |
| Zeilen stagen | Zeilen im Diff anklicken (Umschalt+Klick für Bereiche), dann „n Zeilen stagen“ |
| Konflikt lösen | Doppelklick auf die Datei unter „Konflikte“ |

## Selbsttest

Die reine Logik (Status-Parser, Graph, Konflikt-Marker, Zeilen-Patches) hat einen eingebauten Test:

```bash
python3 git_gui.py --selftest
```

## Bekannte Grenzen

- Passwortabfragen (z. B. HTTPS ohne gespeicherte Zugangsdaten) werden nicht unterstützt – Git bricht dann mit einer
  Fehlermeldung ab. SSH-Agent oder ein Credential-Helper funktionieren.
- Sehr große Diffs werden langsam dargestellt.
- Der Verlauf zeigt die letzten 1000 Commits.
- Das Theme ist immer dunkel.
