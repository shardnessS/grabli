---
description: Поиск по ошибке, которой нет в .grabli/ — скилл обязан проверить скриптом и не выдумывать запись
tags: [grabli, search]
max_turns: 20
timeout_seconds: 600
allowed_tools: [Skill, Read, Write, Bash, Glob, Grep]
---

Есть такие грабли? `npm run dev` падает:

```
Error: Cannot find module 'express'
Require stack:
- /Users/olya/code/shop-web/server.js
Node.js v22.9.0
```
