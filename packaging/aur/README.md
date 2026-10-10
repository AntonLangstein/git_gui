# AUR-Paket `gitgui-git`

`gitgui-git/PKGBUILD` baut die Git GUI aus dem aktuellen Stand von GitHub (`-git`-Paket): Befehl `gitgui`,
Menü-Eintrag, Icon. Beim Bauen laufen alle Tests (`check()`).

## Lokal bauen und installieren

```bash
cd packaging/aur/gitgui-git
makepkg -si
```

Solange das GitHub-Repo privat ist, kann `makepkg` den Code nur mit Zugriff auf das Repo laden
(z.B. über `gh auth setup-git` für HTTPS).

## Im AUR veröffentlichen

1. GitHub-Repo öffentlich machen (sonst scheitert der Download für alle anderen).
2. Konto auf <https://aur.archlinux.org> anlegen und dort den öffentlichen SSH-Schlüssel hinterlegen.
3. Version und `.SRCINFO` aktualisieren – `makepkg` schreibt beim Bauen die aktuelle Version ins PKGBUILD:
   ```bash
   cd packaging/aur/gitgui-git
   makepkg -o                       # nur Quellen holen und Version bestimmen
   makepkg --printsrcinfo > .SRCINFO
   ```
4. Hochladen (der Name `gitgui-git` war beim Anlegen des Pakets noch frei):
   ```bash
   git clone ssh://aur@aur.archlinux.org/gitgui-git.git aur-gitgui-git
   cp PKGBUILD .SRCINFO aur-gitgui-git/
   cd aur-gitgui-git && git add PKGBUILD .SRCINFO && git commit -m "Erste Version" && git push
   ```

Danach können alle mit einem AUR-Helfer installieren, z.B. `paru -S gitgui-git`.
