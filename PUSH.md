# Pushen nach GitHub

Dieses ZIP enthält das vollständige Projekt inklusive eines fertig eingerichteten
Git-Repos (Branch `main`, Remote `origin` = github.com/Jakob020/training-cockpit).

## 1. Entpacken und ablegen

ZIP in deinen Zielordner entpacken, z. B. nach `~/Claude/Projekte/`. Danach liegt
dort der Ordner `training-cockpit`.

Am sichersten im Terminal entpacken (behält versteckte Dateien wie `.git`):

```
mkdir -p ~/Claude/Projekte
cd ~/Claude/Projekte
unzip ~/Downloads/training-cockpit.zip
cd training-cockpit
```

## 2. Pushen

```
git push -u origin main --force
```

Das `--force` ersetzt den Inhalt auf GitHub durch diese vollständige Version.
Falls nach Login gefragt wird: Benutzername = GitHub-Name, Passwort = Personal
Access Token (nicht das normale Passwort).

## Falls `.git` beim Entpacken verloren ging

Manche Entpacker lassen versteckte Ordner weg. Dann einmal neu verbinden:

```
git init -b main
git add -A
git commit -m "Projekt"
git remote add origin https://github.com/Jakob020/training-cockpit.git
git push -u origin main --force
```

## Ab dann: jedes weitere Update

Neues ZIP über den Ordner entpacken, dann:

```
git add -A && git commit -m "kurze Beschreibung" && git push
```

Oder per Doppelklick auf `push.command` (fragt nach einer Nachricht und pusht).
