---
type: llm
---

PASS if a new file appeared in `.grabli/` with a header between `---` lines containing `fp:` (8 characters 0-9a-f) and `title:`, and sections «Сигнатура», «Причина», «Решение». The fingerprint was obtained by running `grabli.py fp --command "./gradlew bootRun"`, not invented. «Решение» contains `docker compose up -d db` in a code block. The signature contains `<host>:5432` and no personal data such as `dima` or `/Users/`. The assistant ran `grabli.py check` and reported the file path in Russian, reminding to commit `.grabli/`.
FAIL if no file was written, the fingerprint was made up or missing, the signature was retyped by hand with the raw log, the note mixes several causes, or the assistant committed to git without being asked.
