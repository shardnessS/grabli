---
fp: <8 hex characters from the hook or `grabli.py fp`; several, comma-separated, if the same cause has several fingerprints>
title: <the cause in a few words, in Russian>
tool: <gradle | maven | node | python | docker | ...>
date: <YYYY-MM-DD>
author: <git user name>
---

## Сигнатура

```text
<signature exactly as the hook or `grabli.py fp` printed it>
```

## Причина

<One or two sentences: why it happens.>

## Решение

```bash
<exact commands>
```

<One line: what the commands do.>

## Проверка

<How to see the fix worked: a command and the expected result.>
