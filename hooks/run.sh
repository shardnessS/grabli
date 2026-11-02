#!/bin/sh
# Запускает хук Граблей: находит Python 3.8+ и передаёт ему stdin от Claude Code.
# Нет подходящего Python — хук молча выходит и ничему не мешает.
root="$1"
event="$2"
script="$root/skills/grabli/scripts/grabli.py"
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1 &&
     "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' </dev/null >/dev/null 2>&1; then
    exec "$py" "$script" hook "$event"
  fi
done
exit 0
