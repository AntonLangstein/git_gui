"""Reine Git-Logik ohne Oberfläche: Ausgaben parsen, Patches bauen, Einstellungen pro Repo."""
import json
import os
import re
import shlex
import subprocess
import time

from PySide6.QtCore import QSettings


# Netzwerk-Ops sollen fehlschlagen statt unsichtbar auf eine Passwortabfrage zu warten,
# und Befehle wie `rebase --continue` dürfen keinen Editor öffnen.
# Git antwortet einheitlich auf Englisch (für die Fehlererkennung in friendly_error), und `git status`
# schreibt den Index nicht neu (GIT_OPTIONAL_LOCKS) – sonst löst jedes Neuladen die Dateiüberwachung erneut aus.
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "LC_ALL": "C.UTF-8",
           "GIT_OPTIONAL_LOCKS": "0"}


# Bekannte Git-Fehler -> verständliche Meldung; None = Konflikt, den das Banner schon erklärt
ERROR_HINTS = [
    (("CONFLICT", "could not apply", "after resolving the conflicts", "Automatic merge failed"), None),
    (("stale info", "(stale info)"),
     "Erzwungener Push abgebrochen: Auf dem Remote hat sich seit dem letzten Fetch etwas geändert.\n"
     "Erst fetchen und prüfen, dann erneut versuchen."),
    (("[rejected]", "fetch first", "non-fast-forward"),
     "Push abgelehnt: Auf dem Remote gibt es Commits, die du lokal noch nicht hast.\nErst pullen, dann erneut pushen."),
    (("would be overwritten by", "Please commit your changes or stash them"),
     "Deine lokalen Änderungen würden dabei überschrieben.\nErst committen oder stashen, dann erneut versuchen."),
    (("you need to resolve your current index first", "unmerged files", "Unmerged paths"),
     "Es gibt noch ungelöste Konflikte. Erst lösen, dann erneut versuchen."),
    (("Could not resolve host", "Connection timed out", "Network is unreachable", "Connection refused"),
     "Keine Verbindung zum Server. Internetverbindung und Remote-Adresse prüfen."),
    (("terminal prompts disabled", "could not read Username", "Authentication failed", "Invalid username or password"),
     "Anmeldung fehlgeschlagen oder abgebrochen.\nBei GitHub & Co. statt des Passworts ein Zugriffstoken verwenden; "
     "mit einem Credential-Helper (z.B. `git config --global credential.helper store`) muss man es nur einmal eingeben."),
    (("Permission denied (publickey)", "Could not read from remote repository", "Repository not found",
      "does not appear to be a git repository"),
     "Kein Zugriff auf das Remote-Repository.\nStimmen Adresse und Zugangsrechte (z.B. SSH-Schlüssel)?"),
    (("divergent branches", "Need to specify how to reconcile"),
     "Lokaler und Remote-Branch sind auseinandergelaufen.\nWähle „Pull (Merge)“ oder „Pull (Rebase)“."),
    (("There is no tracking information", "has no upstream branch"),
     "Der Branch hat noch kein Gegenstück auf dem Remote.\nErst pushen – das legt es an."),
    (("nothing to commit", "nothing added to commit"), "Es gibt nichts zu committen."),
    (("already exists",), "Ein Branch oder Tag mit diesem Namen gibt es schon."),
    (("is not a valid branch name", "not a valid tag name", "is not a valid ref name"),
     "Ungültiger Name. Keine Leerzeichen und keine Zeichen wie ~ ^ : ? * [ \\ verwenden."),
    (("is already checked out at",), "Dieser Branch ist schon in einem anderen Arbeitsverzeichnis (Worktree) ausgecheckt."),
]


def friendly_error(output):
    """Gits Fehlerausgabe -> (Meldung, übersetzt?); Meldung None heißt: Konflikt, kein Dialog nötig."""
    for patterns, message in ERROR_HINTS:
        if any(p in output for p in patterns):
            return message, True
    return output.strip() or "Unbekannter Fehler.", False


OPERATIONS = {"merge": "Merge", "rebase": "Rebase", "cherry-pick": "Cherry-Pick", "revert": "Revert"}


CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


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


def parse_blame(text):
    """`git blame --line-porcelain` -> [(sha, autor, unixzeit, zeile)]."""
    rows, meta = [], {}
    for line in text.splitlines():
        if line.startswith("\t"):
            rows.append((meta.get("sha", ""), meta.get("author", ""), int(meta.get("author-time", 0)), line[1:]))
        elif re.match(r"[0-9a-f]{40} ", line):  # Kopfzeile einer Quellzeile
            meta = {"sha": line[:40]}
        else:
            key, _, value = line.partition(" ")
            meta[key] = value
    return rows


def parse_file_log(text):
    """`git log --follow --name-only --format=%x1e…` -> [(felder, pfad_in_diesem_commit)]."""
    entries = []
    for record in filter(None, text.split("\x1e")):
        lines = [line for line in record.splitlines() if line.strip()]
        if lines:
            entries.append((lines[0].split("\x1f"), lines[-1] if len(lines) > 1 else ""))
    return entries


REBASE_ACTIONS = [("pick", "Behalten"), ("reword", "Nachricht ändern"), ("squash", "Mit vorherigem zusammenfassen"),
                  ("fixup", "In vorherigen einschmelzen (Nachricht verwerfen)"), ("drop", "Entfernen")]


def rebase_todo(rows):
    """[(aktion, sha, neue_nachricht)] -> Inhalt der Todo-Datei für `git rebase -i`.

    „reword“ wird als pick + `git commit --amend -m …` umgesetzt, damit kein Editor aufgeht.
    """
    lines = []
    for action, sha, message in rows:
        if action == "reword":
            lines += [f"pick {sha}", "exec git commit --amend --only -q -m " + shlex.quote(message)]
        else:
            lines.append(f"{action} {sha}")
    return "\n".join(lines) + "\n"


def repo_value(key, repo, default):
    """Pro-Repo-Einstellung (als JSON {repo: wert} unter `key` gespeichert)."""
    try:
        return json.loads(QSettings("git_gui", "git_gui").value(key, "{}")).get(repo, default)
    except ValueError:
        return default


def set_repo_value(key, repo, value):
    settings = QSettings("git_gui", "git_gui")
    try:
        data = json.loads(settings.value(key, "{}"))
    except ValueError:
        data = {}
    if value:
        data[repo] = value
    else:
        data.pop(repo, None)
    settings.setValue(key, json.dumps(data))


def view_option(key):
    """Globale Ansichts-Schalter: "ignore_ws" (Leerzeichen ignorieren), "split_diff" (nebeneinander)."""
    return QSettings("git_gui", "git_gui").value(key, False, type=bool)


def ws_args():
    return ["-w"] if view_option("ignore_ws") else []


def load_stars(repo):
    """Favoriten (Starred) eines Repos als ["branch:main", "remote:origin/dev", …]."""
    return repo_value("starred", repo, [])


def save_stars(repo, stars):
    set_repo_value("starred", repo, stars)


def graph_args(only, hidden, existing):
    """Ref-Argumente für `git log` in „Alle Commits“ mit Graph-Filter.

    only = nur diese Refs zeigen, hidden = diese Refs ausblenden; Refs, die es nicht mehr gibt, zählen nicht.
    """
    only = [r for r in only if r in existing and r not in hidden]
    if only:
        return only
    return ["--exclude=refs/stash", *(f"--exclude={r}" for r in hidden if r in existing), "--all"]


def parse_ssh_remote(url):
    """SSH-Adresse -> (ziel, port), z.B. „git@github.com:a/b.git“ oder „ssh://git@host:2222/a.git“.

    None bei HTTPS-Adressen oder lokalen Pfaden.
    """
    m = re.match(r"ssh://(?:([^@/]+)@)?([^:/]+)(?::(\d+))?/", url)
    if m:
        return (f"{m[1]}@{m[2]}" if m[1] else m[2]), m[3]
    m = re.match(r"(?:([^@/]+)@)?([^:/]+):(?!//)", url)  # scp-Schreibweise: [user@]host:pfad
    if m and "://" not in url:
        return (f"{m[1]}@{m[2]}" if m[1] else m[2]), None
    return None


def ssh_command_for(key):
    """SSH-Befehl, der genau diesen Schlüssel nimmt (IdentitiesOnly: keine anderen aus dem Agent probieren)."""
    return f"ssh -i {shlex.quote(key)} -o IdentitiesOnly=yes"


_ORIGINAL_SSH_COMMAND = GIT_ENV.get("GIT_SSH_COMMAND")


def apply_ssh_key(key):
    """Programmweiten SSH-Schlüssel für alle git-Aufrufe der GUI setzen (None = Standard von SSH).

    Wirkt nur auf die GUI, nicht auf das Terminal oder die globale Git-Konfiguration.
    """
    if key:
        GIT_ENV["GIT_SSH_COMMAND"] = ssh_command_for(key)
    elif _ORIGINAL_SSH_COMMAND:
        GIT_ENV["GIT_SSH_COMMAND"] = _ORIGINAL_SSH_COMMAND
    else:
        GIT_ENV.pop("GIT_SSH_COMMAND", None)


def ssh_test_result(code, output):
    """(erfolg, meldung) aus `ssh -T host`. GitHub & Co. beenden mit Code 1, melden aber die Anmeldung."""
    if code == 0 or any(s in output for s in ("successfully authenticated", "Welcome to GitLab",
                                              "authenticated via", "logged in as")):
        return True, "Anmeldung klappt – Git kann diesen Server ohne Passwort nutzen."
    if "Permission denied" in output:
        return False, ("Abgelehnt: Der Server kennt diesen Schlüssel nicht.\n"
                       "Den öffentlichen Schlüssel (.pub) im Konto hinterlegen oder einen anderen Schlüssel wählen.")
    if any(s in output for s in ("Could not resolve hostname", "timed out", "Connection refused", "No route")):
        return False, "Server nicht erreichbar. Internetverbindung und Adresse prüfen."
    if "Host key verification failed" in output or "REMOTE HOST IDENTIFICATION HAS CHANGED" in output:
        return False, "Der Server-Schlüssel stimmt nicht mit dem bekannten überein (~/.ssh/known_hosts prüfen)."
    return False, "Anmeldung hat nicht geklappt."


def repo_root(path):
    """Wurzel des Git-Repos, in dem `path` liegt, oder None."""
    r = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return None if r.returncode else r.stdout.strip()


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


def group_repos(known, folders, folder_of):
    """-> [(ordner, [pfade])]: eigene Ordner in ihrer Reihenfolge, zuletzt (None, Repos ohne Ordner).

    Repos sind innerhalb jeder Gruppe nach Namen sortiert; Zuordnungen zu gelöschten Ordnern zählen als „ohne“.
    """
    key = lambda p: (os.path.basename(p).lower(), p)
    groups = [(f, sorted((p for p in known if folder_of.get(p) == f), key=key)) for f in folders]
    return groups + [(None, sorted((p for p in known if folder_of.get(p) not in folders), key=key))]
