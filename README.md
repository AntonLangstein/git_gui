# Git GUI

Eine schlanke Git-Oberfläche für Linux im Stil von [Fork](https://git-fork.com/). Geschrieben in Python mit PySide6;
für alles wird das `git`-Kommandozeilenprogramm aufgerufen.

## Funktionen

- **Mehrere Repositories** in Tabs; offene Tabs werden laufend gemerkt und beim nächsten Start wiederhergestellt
- **Repository-Verwaltung** im „Neuer Tab“: zuletzt geöffnete und bekannte Repos, Übersicht und Statistik
  („Commits pro Monat“ je Autor, auch als Tabelle), eigene Ordner (per Rechtsklick oder Drag & Drop),
  Festplatte nach Repos durchsuchen
- **Verlauf** mit gezeichnetem Commit-Graph, farbigen Branch-/Tag-Labels und Autor-Avataren (Initialen);
  lädt beim Scrollen weitere Commits nach; Suchfeld filtert nach Tag, Branch, Nachricht, Autor oder Hash –
  auch in älteren, noch nicht geladenen Commits
- **Graph-Filter**: „Alle Commits“ auf ausgewählte Branches beschränken oder einzelne Branches ausblenden
- **Commit-Menü** im Verlauf: Cherry-Pick, Revert, interaktiver Rebase (umsortieren, umbenennen, zusammenfassen,
  entfernen), Branch/Tag hier erstellen, Commit auschecken, Branch zurücksetzen (soft/mixed/hard)
- **Commit-Details**: Autor, Committer, Parents, Dateiliste und Diff; bei Merges umschaltbar zwischen den Parents;
  Dateibaum mit allen Dateien zum Stand des Commits
- **Datei-Historie und Blame** (Rechtsklick auf eine Datei), auch über Umbenennungen hinweg
- **Lokale Änderungen**: Dateien, einzelne Hunks oder einzelne Zeilen stagen/unstagen, Änderungen verwerfen,
  Commit mit Betreff, Beschreibung und Amend
- **Diffs** mit Syntaxfarben, hervorgehobenen Wort-Änderungen, optional nebeneinander und ohne Leerzeichen-Änderungen
- **Branches**: wechseln, anlegen, umbenennen, löschen, mergen, rebasen – per Doppelklick oder Rechtsklick in der Seitenleiste
- **Remotes**: Fetch, Pull (Merge oder Rebase), Push (auch sicher erzwungen mit `--force-with-lease`) im Hintergrund;
  Zähler an Pull/Push, automatischer Fetch alle 5 Minuten; Remotes hinzufügen, umbenennen, entfernen
- **Tags** anlegen (auch annotiert) und pushen
- **Aktualisiert sich selbst**, wenn im Terminal committet oder ein Branch gewechselt wird
- **Stashes**: anlegen, anwenden, poppen, löschen, Inhalt ansehen
- **Konflikte lösen** bei Merge, Rebase, Cherry-Pick und Revert: Block für Block mit editierbarem Ergebnis,
  Abbrechen/Fortsetzen über ein Banner
- **Zugangsdaten**: fragt Git nach Benutzer, Passwort/Token oder SSH-Passphrase, erscheint ein Dialog;
  eigener SSH-Schlüssel für die ganze GUI (Menü „Einstellungen“) und SSH-Verbindungstest
- Seitenleiste mit Filter, Favoriten-Branches (wie „Starred“ in Fork), Branch-Ordnern (`feature/…`) und
  Ahead/Behind-Anzeige
- Dunkles oder helles Design (oder wie das System), Terminal im Repo-Ordner öffnen

## Voraussetzungen

- Python 3.10 oder neuer (entwickelt mit 3.14)
- [PySide6](https://pypi.org/project/PySide6/) (entwickelt mit 6.11)
- optional [Pygments](https://pygments.org/) für Syntaxfarben im Diff
- `git` (entwickelt mit 2.55)

Arch / CachyOS:

```bash
sudo pacman -S pyside6 git python-pygments
```

## Installieren

**Aus diesem Ordner** (empfohlen, wenn du das Repo ohnehin geklont hast): legt den Befehl `gitgui` in `~/.local/bin`
und einen Eintrag „Git GUI“ im Anwendungsmenü an. Updates per `git pull` wirken sofort.

```bash
./install.sh
```

Entfernen mit `./install.sh --uninstall`.

**Als Python-Paket** mit pip oder pipx (installiert ebenfalls den Befehl `gitgui`, aber keinen Menü-Eintrag):

```bash
pipx install '.[syntax]'
```

**Als Arch-Paket** (AUR-Paket `gitgui-git`, siehe [packaging/aur](packaging/aur/README.md)):

```bash
cd packaging/aur/gitgui-git && makepkg -si
```

Der Befehl heißt bewusst `gitgui` und nicht `git-gui` – so heißt schon das Tk-Programm, das Git selbst mitbringt.

## Starten

```bash
gitgui                     # letzte Sitzung, sonst die Repository-Verwaltung
gitgui ~/repo1 ~/repo2     # bestimmte Repositories öffnen
python3 git_gui.py         # ohne Installation direkt aus dem Ordner
```

## Bedienung

| Aktion | So geht's |
|---|---|
| Repository-Verwaltung | `+` neben den Tabs oder Strg+T |
| Repository öffnen | „Öffnen“ oder Strg+O |
| Tab schließen / wechseln | Strg+W / Strg+Tab, Strg+Umschalt+Tab |
| Aktualisieren | F5 (passiert auch beim Tab-Wechsel und automatisch) |
| Committen | Enter im Betreff oder Strg+Enter |
| Verlauf filtern | Strg+F |
| Pull mit Rebase, Push erzwingen | Pfeil an den Knöpfen Pull/Push oder Menü „Repository“ |
| Branch auschecken | Doppelklick in der Seitenleiste |
| Branch-Aktionen | Rechtsklick auf Branch, Remote-Branch, Tag oder Stash |
| Remotes verwalten, Tags anlegen | Rechtsklick auf „Remotes“, einen Remote oder „Tags“ |
| SSH-Schlüssel wählen, Verbindung testen | Menü „Einstellungen“ (Test auch per Rechtsklick auf einen Remote) |
| Datei stagen | Doppelklick, „Stagen“-Knopf oder Rechtsklick |
| Hunk stagen | „Hunk stagen“ im Diff-Kopf |
| Zeilen stagen | Zeilen im Diff anklicken (Umschalt+Klick für Bereiche), dann „n Zeilen stagen“ |
| Commit-Aktionen (Cherry-Pick, Rebase, Reset …) | Rechtsklick auf einen Commit im Verlauf |
| Datei-Historie und Blame | Rechtsklick auf eine Datei (Änderungen oder Dateibaum) |
| Diff-Ansicht, Design | Menü „Ansicht“ oder Knöpfe über dem Diff |
| Konflikt lösen | Doppelklick auf die Datei unter „Konflikte“ |

## Tests

Logik-Tests und Abläufe in der Oberfläche mit echten Git-Repos in Temp-Ordnern (Qt läuft dabei ohne Bildschirm,
Einstellungen und Git-Konfiguration sind isoliert):

```bash
python3 -m unittest discover -s tests -t .
```

Auf GitHub laufen sie bei jedem Push (`.github/workflows/tests.yml`).

## Aufbau

| Datei | Inhalt |
|---|---|
| `gitgui/core.py` | Reine Git-Logik ohne Oberfläche: Ausgaben parsen, Patches bauen, Einstellungen |
| `gitgui/theme.py` | Farben, Designs, Stylesheet |
| `gitgui/diff.py` | Diff-Darstellung (Syntaxfarben, Wort-Diff, Nebeneinander) |
| `gitgui/widgets.py` | Bausteine: Hintergrund-Aufgaben, Graph/Autor-Darstellung, Diagramm, Zugangsdaten-Dialog |
| `gitgui/dialogs.py` | Datei-Historie/Blame, interaktiver Rebase, Konflikte lösen |
| `gitgui/repotab.py` | Ein Repository-Tab: Seitenleiste, Änderungen, Verlauf, Details |
| `gitgui/manager.py` | Repository-Verwaltung („Neuer Tab“) |
| `gitgui/mainwindow.py` | Hauptfenster, Toolbar, Menüs |
| `gitgui/app.py` | Programmstart |

## Bekannte Grenzen

- Git-Meldungen in der Statusleiste sind englisch; Fehler werden auf Deutsch erklärt.
- Sehr große Diffs werden langsamer dargestellt; ab 4000 Zeilen ohne Syntaxfarben und Wort-Diff.
- Syntaxfarben werden Zeile für Zeile bestimmt (mehrzeilige Strings/Kommentare nicht durchgehend erkannt).
- Interaktiver Rebase nur ohne Merge-Commits im gewählten Bereich.

Geplante und erledigte Verbesserungen stehen in der [ROADMAP](ROADMAP.md).

## Lizenz

MIT – siehe [LICENSE](LICENSE).
