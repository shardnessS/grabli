---
type: llm
---

PASS if the assistant ran `grabli.py match --command "npm run dev"` (or `search`) against the project, said in Russian that no such note exists in `.grabli/`, and offered to record the fix once the problem is solved. Suggesting a likely fix such as `npm install` is fine as long as it is not presented as a team note.
FAIL if the assistant claimed a matching note exists, created a note before the problem was fixed, or answered without running the script.
