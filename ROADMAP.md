# Roadmap

Alle 18 Punkte sind umgesetzt. Neue Ideen bitte unten ergänzen.

Aufwand: **S** = Stunden, **M** = ca. ein Tag, **L** = mehrere Tage.

## Als Nächstes

- [x] **1. Automatisch aktualisieren** (S) – `.git`-Ordner beobachten (`QFileSystemWatcher`) und neu laden, wenn im
  Terminal committet oder ein Branch gewechselt wird. Bisher nur per F5 oder Tab-Wechsel.
- [x] **2. Ahead/Behind an Pull und Push** (S) – Zähler an den Toolbar-Knöpfen, wie viele Commits zu pullen bzw.
  zu pushen sind; optional automatischer Fetch alle paar Minuten.
- [x] **3. Commit-Menü im Verlauf erweitern** (M) – „Branch hier erstellen“, „Tag hier erstellen“, „Commit
  auschecken“, „Branch auf diesen Commit zurücksetzen“ (soft/mixed/hard, hard mit Warnung).
- [x] **4. Freundlichere Fehlermeldungen** (S) – bei Konflikten kein Git-Dialog vor dem Banner; häufige Fehler
  übersetzt und mit Lösungshinweis (z. B. „Push abgelehnt – erst pullen“).
- [x] **5. Verlauf nachladen** (M) – beim Scrollen weitere Commits laden statt fest bei 1000 aufzuhören; damit findet
  auch der Verlaufsfilter ältere Tags.

## Diff-Ansicht

- [x] **6. Wort-Diff** (M) – geänderte Wörter innerhalb einer Zeile hervorheben.
- [x] **7. Syntax-Hervorhebung und Whitespace** (M) – Hervorhebung nach Dateityp; Schalter „Leerzeichen-Änderungen
  ignorieren“.
- [x] **8. Nebeneinander-Ansicht** (M) – alt | neu als Alternative zur Zeilenansicht.

## Fehlende Git-Funktionen

- [x] **9. Pull-/Push-Optionen** (S) – Pull mit Rebase statt Merge; Push mit `--force-with-lease`, z. B. nach Amend.
- [x] **10. Datei-Historie und Blame** (M) – Rechtsklick auf eine Datei zeigt ihren Verlauf und wer welche Zeile
  geändert hat.
- [x] **11. Tags anlegen, Remotes verwalten** (S) – Tags erstellen; Remotes hinzufügen, umbenennen, entfernen.
- [x] **12. Interaktiver Rebase** (L) – Commits zusammenfassen, umsortieren, umbenennen.

## Stabilität und Pflege

- [x] **13. Echte Tests** (M) – die bisherigen Testskripte als `tests/`-Sammlung mit pytest und echten Test-Repos;
  GitHub Action, die sie bei jedem Push ausführt (offscreen, `QT_QPA_PLATFORM=offscreen`).
- [x] **14. Aufteilen in Module** (M) – `git_gui.py` (> 2400 Zeilen) in Graph, Diff, Repo-Tab, Verwaltung und
  Dialoge aufteilen.
- [x] **15. Langsame Aktionen im Hintergrund** (M) – Statistik, Dateibaum und Status bei großen Repos asynchron,
  damit das Fenster nie hängt.

## Komfort

- [x] **16. Hell/Dunkel umschaltbar** (S) – oder Systemfarben übernehmen.
- [x] **17. HTTPS-Zugangsdaten** (M) – Passwort-/Token-Dialog statt Abbruch bei Passwortabfragen.
- [x] **18. Installation** (S) – Skript oder `pyproject.toml`, das GUI und Menü-Starter mit einem Befehl
  installiert; AUR-Paket `gitgui-git` in `packaging/aur`.

## Ideen für später

- [x] AUR-Paket (PKGBUILD in `packaging/aur`, Veröffentlichung noch offen)
- [ ] Submodule und Worktrees anzeigen
- [ ] Suche im Diff
