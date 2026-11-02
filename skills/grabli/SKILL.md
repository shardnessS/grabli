---
name: grabli
description: Team memory of environment errors for Claude Code. Records how a failed build, test, migration or local run was fixed into the .grabli/ folder of the repository, applies known fixes found by error fingerprint, and shows experiment stats. Use when a Grabli hook message says a command failed earlier and now passes, when a hook reports a known or similar issue, or when the user says "запиши грабли", "сохрани в грабли", "это уже чинили?", "есть такие грабли?", "найди в граблях", "проверь грабли", "статистика граблей", "record this fix for the team". Do not use for ordinary code bugs fixed by changing application logic, or for errors that any developer fixes from the message alone.
---

# Grabli

The team keeps short notes about environment errors in `.grabli/` inside the repository. Hooks fingerprint every failed command: a known fingerprint brings its note into the session, and a command that starts passing after a failure asks for a new note. The folder is committed, so every teammate's agent sees every note.

Speak Russian to the user unless they write in another language. No emojis.

## Where things live

| What | Where |
|---|---|
| Notes | `.grabli/<short-name>.md` in the project root, one cause per file |
| Note format | [references/entry-format.md](references/entry-format.md), skeleton in [templates/entry.md](templates/entry.md) |
| Script | `scripts/grabli.py` in this skill's directory; hook messages print the full command |

Script commands, run from the project root:

| Command | Does |
|---|---|
| `python scripts/grabli.py fp --command "<cmd>" < log.txt` | Fingerprint and signature of an error log |
| `python scripts/grabli.py match --command "<cmd>" < log.txt` | Notes that match an error log, exact first |
| `python scripts/grabli.py search <words or fingerprint>` | Notes by words or by fingerprint |
| `python scripts/grabli.py list` | All notes |
| `python scripts/grabli.py check` | Validates notes: fields, sections, duplicate fingerprints, secrets |
| `python scripts/grabli.py stats` | Experiment counters for the current project |

The fingerprint depends on the command, so always pass the exact failed command with `--command`.

## Situations

| Trigger | Do |
|---|---|
| Hook: "failed earlier in this session and now passes" | Record, if worth it |
| Hook: "known issue recorded by the team" | Apply the note |
| Hook: "similar known issues" | Compare, then apply or extend the note |
| «запиши грабли», «сохрани в грабли» | Record what was just fixed |
| «это уже чинили?», an error pasted | Search |
| «статистика граблей» | Stats |

## Record

1. **Decide.** Record only when a teammate's agent would lose real time without the note: the cause was outside the code being written. Typical causes: a local service is not running, a wrong tool version, a missing or stale config value, certificates and proxies, registry credentials, OS or shell quirks, a required setup step, a flaky local resource. Do not record a bug fixed in application code, a typo in the command, or a fix that the error message states directly. If unsure, ask the user one short question.
2. **Look for an existing note.** Run `search` with two or three key words from the error. If a note describes the same cause, add the new fingerprint to its `fp:` line, comma-separated, and stop.
3. **Write the note** by [templates/entry.md](templates/entry.md):
   - `fp` and the signature exactly as the hook gave them. Without a hook message, save the error output to a temporary file and run `fp --command "<cmd>"`. Never invent a fingerprint.
   - `title`: the cause in a few words, for example «Postgres из docker-compose не запущен».
   - `Причина`: one or two sentences, why it happens.
   - `Решение`: the exact commands in a `bash` block, then one line on what they do.
   - `Проверка`: how to see the fix worked.
   - `author`: the git user name from `git config user.name`, otherwise ask.
   - File name: short kebab-case from the title, Latin letters: `postgres-not-running.md`.
4. **Clean secrets.** Replace tokens, passwords, keys and personal paths with placeholders: `<token>`, `$HOME`, `<password>`. Internal host names may stay.
5. **Check.** Run `check` and fix everything it reports.
6. **Report** in two lines: what was recorded and the file path. Remind the user to commit `.grabli/` together with the change. Do not commit unless asked.

## Apply

1. Read the note the hook pointed to and check that the cause fits the current situation.
2. Run the recorded fix following the normal permission rules, and tell the user: «Это известные грабли: <title> (`.grabli/<file>`)».
3. If the fix did not help or is outdated, update the note: correct `Решение`, or add a line «Не помогает, если …». Run `check`.
4. For a similar match, read the suggested notes. If one describes the same cause, apply it and add the new fingerprint to its `fp:` line.

## Search

- With an error text: save it to a temporary file, run `match --command "<cmd>" < file`, show exact matches first, then similar ones with their titles.
- With words: run `search <words>`.
- Nothing found: say so in one line and offer to record the fix once the problem is solved.

## Stats

Run `stats` and show its output in a code block. Then add one or two sentences in plain words. The script's own verdict is the rule: until 14 days of data it is too early to judge; after that, fewer than one known-issue hit per week means the team rarely repeats errors and Grabli is probably not worth it. Say that plainly if so.

## Rules

- One cause per note. A note fits on one screen.
- Fingerprints and signatures come from the hook or the script, never from guessing.
- No secrets in notes, ever. `check` must pass before reporting.
- Never record ordinary code bugs. A failed test because of wrong logic is not a grabli.
- Keep the original `author` when editing someone else's note; add `updated:` with today's date.
