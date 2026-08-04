#!/bin/bash
# In den Projektordner legen und doppelklicken (oder: bash push.command).
# Fragt nach einer Commit-Nachricht und pusht alle Aenderungen nach GitHub.
cd "$(dirname "$0")" || exit 1

if [ ! -d ".git" ]; then
  echo "Kein Git-Repo hier gefunden."
  read -n 1 -s -r -p "Taste zum Schliessen..."
  exit 1
fi

read -r -p "Commit-Nachricht: " MSG
git add -A
git commit -m "${MSG:-Update}"
git push

echo ""
echo "Fertig."
read -n 1 -s -r -p "Taste zum Schliessen..."
