# Note format

A note is one Markdown file in `.grabli/` at the project root. One file describes one cause. The folder is committed to git, so teammates and their agents read the same notes.

## Header

| Field | Required | Meaning |
|---|---|---|
| `fp` | yes | Fingerprint, 8 characters `0-9a-f`. Several fingerprints of the same cause go comma-separated: `fp: 4f63b1dc, 1c4e9a20` |
| `title` | yes | The cause in a few words, in Russian |
| `tool` | no | The tool from the first line of the signature |
| `date` | no | When the note was written, `YYYY-MM-DD` |
| `author` | no | Who wrote it |
| `updated` | no | When the note was last corrected |

Values stay on one line. The script reads only `key: value` lines between the two `---` lines.

## Sections

`## Сигнатура`, `## Причина` and `## Решение` are required, `check` reports a missing one. `## Проверка` is recommended.

The first code block under `## Сигнатура` is the signature. The hook compares it with new failures to suggest similar notes, so paste it exactly as printed.

## How the fingerprint is made

The script takes the output of the failed command, keeps the lines that identify the error and replaces everything that changes from run to run:

| In the log | In the signature |
|---|---|
| `2026-09-12T10:14:03.512+03:00`, `10:21:44.118` | `<time>` |
| `PID 48213`, `in 6s` | `PID <n>`, `<dur>` |
| `localhost`, `127.0.0.1`, `10.0.3.7` | `<host>` |
| `/Users/dima/work/shop/app.log`, `C:\Users\olya\app.log` | `<path>/app.log` |
| `https://nexus.shop.local/repository/...` | `https://nexus.shop.local/<path>` |
| `ConnectionFactoryImpl.java:346` | `ConnectionFactoryImpl.java:<n>` |
| `postgresql-42.7.4.jar`, `1.4.0-SNAPSHOT` | `postgresql-<ver>.jar`, `<ver>` |
| `3f2a9c1e8b7d`, UUID, `0x7f3a` | `<hash>`, `<uuid>`, `<addr>` |
| `:54873` (random port) | `:<port>` |

Well-known ports like `5432` stay: they say which service is missing.

Lines that identify the error, in order of priority:

1. Spring Boot `APPLICATION FAILED TO START`: the first two lines of `Description:`.
2. Exceptions: `org.foo.BarException: …`, `Caused by: …`, `ModuleNotFoundError: …`, `Error: Cannot find module …`. When there are more than three, the top wrapper and the two deepest causes are kept.
3. Gradle `* What went wrong:` block without generic lines like `Execution failed for task`.
4. Maven `[ERROR]` lines, nested causes cut to the last three links.
5. Lines with words like error, failed, refused, denied, not found.

The first line of the signature is the tool (`gradle`, `maven`, `node`, `python`, `docker`, …). The fingerprint is the first 8 characters of the SHA-256 of the signature.

## Example

````markdown
---
fp: 4f63b1dc
title: Postgres из docker-compose не запущен
tool: gradle
date: 2026-11-02
author: Дима
---

## Сигнатура

```text
gradle
org.springframework.beans.factory.BeanCreationException: Error creating bean with name 'entityManagerFactory' …
org.postgresql.util.PSQLException: Connection to <host>:5432 refused. …
java.net.ConnectException: Connection refused
```

## Причина

Приложение стартует раньше базы: контейнер `db` из docker-compose.yml не запущен.

## Решение

```bash
docker compose up -d db
```

Поднимает только базу, остальные сервисы не трогает.

## Проверка

`./gradlew bootRun` доходит до строки `Started ShopApplication`.
````
