---
description: Ошибка в коде — скилл не записывает её в грабли и объясняет почему
tags: [grabli, record, refuse]
max_turns: 15
timeout_seconds: 600
allowed_tools: [Skill, Read, Write, Bash, Glob, Grep]
---

Запиши в грабли: тест `OrderServiceTest.totalIncludesDelivery` падал с `AssertionFailedError: expected: <1490> but was: <1290>`. Я забыл прибавить доставку в `calculateTotal`, поправил — тест зелёный.
