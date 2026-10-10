# Git GUI

Eine schlanke Git-Oberfläche für Linux im Stil von [Fork](https://git-fork.com/) – eine einzige Python-Datei,
die für alles das `git`-Kommandozeilenprogramm aufruft.

## Funktionen

- **Mehrere Repositories** in Tabs; offene Tabs werden laufend gemerkt und beim nächsten Start wiederhergestellt
- **Repository-Verwaltung** im „Neuer Tab“: zuletzt geöffnete und bekannte Repos, Übersicht und Statistik
  („Commits pro Monat“ je Autor), eigene Ordner (per Rechtsklick oder Drag & Drop), Festplatte nach Repos durchsuchen
- **Verlauf** mit gezeichnetem Commit-Graph, farbigen Branch-/Tag-Labels und Autor-Avataren (Initialen);
  lädt beim Scrollen weitere Commits nach; Suchfeld filtert nach Tag, Branch, Nachricht, Autor oder Hash –
  auch in älteren, noch nicht geladenen Commits
- **Graph-Filter**: „Alle Commits“ auf ausgewählte Branches beschränken oder einzelne Branches ausblenden
- **Commit-Menü** im Verlauf: Cherry-Pick, Revert, Branch/Tag hier erstellen, Commit auschecken,
  Branch zurücksetzen (soft/mixed/hard)
- **Commit-Details**: Autor, Committer, Parents, Dateiliste und Diff; bei Merges umschaltbar zwischen den Parents;
  Dateibaum mit allen Dateien zum Stand des Commits
- **Lokale Änderungen**: Dateien, einzelne Hunks oder einzelne Zeilen stagen/unstagen, Änderungen verwerfen,
  Commit mit Betreff, Beschreibung und Amend
- **Diffs** mit Syntaxfarben, hervorgehobenen Wort-Änderungen, optional nebeneinander und ohne Leerzeichen-Änderungen
- **Branches**: wechseln, anlegen, umbenennen, löschen, mergen, rebasen – per Doppelklick oder Rechtsklick in der Seitenleiste
- **Remotes**: Fetch, Pull, Push im Hintergrund (das Fenster bleibt bedienbar), Upstream beim ersten Push,
  Remote-Branches löschen; Zähler an Pull/Push und automatischer Fetch alle 5 Minuten
- **Aktualisiert sich selbst**, wenn im Terminal committet oder ein Branch gewechselt wird
- **Stashes**: anlegen, anwenden, poppen, löschen, Inhalt ansehen
- **Konflikte lösen** bei Merge, Rebase, Cherry-Pick und Revert: Block für Block mit editierbarem Ergebnis,
  Abbrechen/Fortsetzen über ein Banner
- Seitenleiste mit Filter, Favoriten-Branches (wie „Starred“ in Fork), Branch-Ordnern (`feature/…`) und
  Ahead/Behind-Anzeige
- Dunkles Theme, Terminal im Repo-Ordner öffnen

## Voraussetzungen

- Python 3.10 oder neuer (entwickelt mit 3.14)
- [PySide6](https://pypi.org/project/PySide6/) (entwickelt mit 6.11)
- optional [Pygments](https://pygments.org/) für Syntaxfarben im Diff (`python-pygments`)
- `git` (entwickelt mit 2.55)

Arch / CachyOS:

```bash
sudo pacman -S pyside6 git python-pygments
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
| Verlauf filtern | Strg+F |
| Branch auschecken | Doppelklick in der Seitenleiste |
| Branch-Aktionen | Rechtsklick auf Branch, Remote-Branch, Tag oder Stash |
| Datei stagen | Doppelklick, „Stagen“-Knopf oder Rechtsklick |
| Hunk stagen | „Hunk stagen“ im Diff-Kopf |
| Zeilen stagen | Zeilen im Diff anklicken (Umschalt+Klick für Bereiche), dann „n Zeilen stagen“ |
| Cherry-Pick, Revert, Reset, Tag … | Rechtsklick auf einen Commit im Verlauf |
| Diff-Ansicht umschalten | Menü „Ansicht“ oder Knöpfe über dem Diff |
| Konflikt lösen | Doppelklick auf die Datei unter „Konflikte“ |

## Selbsttest

Die reine Logik (Status-Parser, Graph, Konflikt-Marker, Zeilen-Patches) hat einen eingebauten Test:

```bash
python3 git_gui.py --selftest
```

## Bekannte Grenzen

- Git-Meldungen in der Statusleiste sind englisch; Fehler werden auf Deutsch erklärt.
- Passwortabfragen (z. B. HTTPS ohne gespeicherte Zugangsdaten) werden nicht unterstützt – Git bricht dann mit einer
  Fehlermeldung ab. SSH-Agent oder ein Credential-Helper funktionieren.
- Sehr große Diffs werden langsam dargestellt.
- Das Theme ist immer dunkel.

Geplante Verbesserungen stehen in der [ROADMAP](ROADMAP.md).
