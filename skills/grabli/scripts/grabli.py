"""Грабли: отпечатки ошибок, хуки Claude Code и поиск по папке .grabli/ проекта.

    python grabli.py hook failure               хук PostToolUseFailure: ищет известные грабли
    python grabli.py hook success               хук PostToolUse: просит записать, что помогло
    python grabli.py fp [--command КОМАНДА]     отпечаток ошибки из stdin
    python grabli.py match [--command КОМАНДА]  записи, которые подходят к ошибке из stdin
    python grabli.py search ЗАПРОС              поиск записей по словам или отпечатку
    python grabli.py list                       все записи проекта
    python grabli.py check                      проверка записей: поля, дубли, секреты
    python grabli.py stats [--days N] [--all]   счётчики эксперимента

Только стандартная библиотека Python 3.8+, без сети.
Хуки никогда не мешают работе: любая ошибка внутри них — тихий выход с кодом 0.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ENTRY_DIR = ".grabli"
PENDING_TTL = datetime.timedelta(hours=24)
MAX_NUDGES_PER_SESSION = 3
SIMILAR_THRESHOLD = 0.5
CONTEXT_LIMIT = 6000
LINE_LIMIT = 240
EXPERIMENT_DAYS = 14

# --- команда -------------------------------------------------------------

TOOLS = (
    ("gradle", re.compile(r"^gradlew?$")),
    ("maven", re.compile(r"^mvnw?$")),
    ("docker", re.compile(r"^docker(?:-compose)?$")),
    ("node", re.compile(r"^(?:npm|npx|pnpm|yarn|bun|node)$")),
    ("python", re.compile(r"^(?:python\d?(?:\.\d+)?|py|pytest|pip\d?|uv|poetry)$")),
    ("go", re.compile(r"^go$")),
    ("rust", re.compile(r"^cargo$")),
    ("make", re.compile(r"^make$")),
)
WRAPPERS = {"sudo", "time", "env", "exec", "nohup", "command"}
BENIGN = {
    "grep", "rg", "egrep", "fgrep", "test", "[", "[[", "diff", "cmp", "ls", "cat", "head", "tail",
    "find", "which", "where", "type", "true", "false", "echo", "printf", "cd", "pwd", "sleep",
    "wc", "stat", "file", "sort", "uniq", "jq", "kill", "pkill", "pgrep", "lsof",
}
GIT_READONLY = {
    "status", "diff", "log", "show", "grep", "rev-parse", "ls-files", "branch", "check-ignore",
    "merge-base", "describe", "blame", "cat-file", "config", "remote", "stash",
}


def program_name(word):
    name = re.split(r"[\\/]", word)[-1].lower()
    return re.sub(r"\.(?:exe|bat|cmd|sh|ps1)$", "", name)


def tool_of(word):
    name = program_name(word)
    for tool, pattern in TOOLS:
        if pattern.match(name):
            return tool
    return None


def command_words(segment):
    words = [w.strip("'\"") for w in segment.split()]
    while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in WRAPPERS
                     or program_name(words[0]) == "grabli"):
        words = words[1:]
    return words


def parse_command(command):
    """Программа, инструмент и ключ, по которому успешный запуск находит своё падение."""
    segments = [s for s in re.split(r"\s*(?:&&|\|\||;|\||\n)\s*", (command or "").strip()) if s.strip()]
    chosen = None
    for segment in reversed(segments):
        words = command_words(segment)
        if words and tool_of(words[0]):
            chosen = words
            break
    if chosen is None:
        chosen = command_words(segments[-1]) if segments else []
    if not chosen:
        return {"program": "other", "tool": "other", "key": "other", "args": []}
    program = program_name(chosen[0])
    args = [a for a in chosen[1:] if not a.startswith("-") and "=" not in a and not re.match(r"^\d*[<>&]", a)]
    return {
        "program": program,
        "tool": tool_of(chosen[0]) or program,
        "key": " ".join([program] + args[:2]),
        "args": args,
    }


def is_benign(cmd):
    if cmd["program"] in BENIGN:
        return True
    return cmd["program"] == "git" and bool(cmd["args"]) and cmd["args"][0] in GIT_READONLY


# --- отпечаток -----------------------------------------------------------

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
QUALIFIED_EXC = re.compile(
    r'^(?:Caused by:\s*|Exception in thread "[^"]*"\s*)?((?:[a-z_$][\w$]*\.)+[A-Z][\w$]*(?:Exception|Error)\b.*)$')
BARE_EXC = re.compile(r"^(?:E\s+|Uncaught\s+|Caused by:\s*)?((?:[A-Z][A-Za-z0-9_]*)?(?:Error|Exception)\b:\s*\S.*)$")
GRADLE_GENERIC = re.compile(
    r"^(?:Execution failed for task|There were failing tests|Process 'command|Run with --|Get more help)", re.I)
MAVEN_NOISE = re.compile(
    r"^(?:To see the full stack trace|Re-run Maven|For more information|\[Help \d+\]|After correcting the problems)", re.I)
KEYWORDS = re.compile(
    r"(?i)\b(?:error|errors|failed|failure|fatal|refused|denied|not found|cannot|can't|could not|unable to|"
    r"no such|timed? ?out|unknown host|permission|unauthorized|forbidden|already in use|already allocated|"
    r"not recognized)\b")
KEYWORD_NOISE = re.compile(
    r"(?i)^(?:BUILD FAILED|BUILD FAILURE|FAILURE: Build failed|> Task \S+ FAILED|\d+ tests? completed|"
    r"npm (?:error|ERR!) A complete log|npm (?:error|ERR!)\s*$|.*for more information|.*--stacktrace|.*--debug\b)")
CODE_RE = re.compile(
    r"\b(?:AssertionError|AssertionFailedError|ComparisonFailure|SyntaxError|TypeError|ReferenceError|NameError|"
    r"IndentationError|ZeroDivisionError|NullPointerException|ArrayIndexOutOfBoundsException|ClassCastException|"
    r"NumberFormatException)\b|\berror TS\d+|\bcannot find symbol\b|\bUnresolved reference\b|"
    r"\b[Cc]ompilation failed\b|\bcompilation errors?\b|\bexpected:? ?<.*> but was\b|^e: |(?:^|: )error: ")
BUILD_END = re.compile(r"^BUILD (?:FAILED|SUCCESSFUL|FAILURE|SUCCESS)\b")

NORMALIZE = (
    (re.compile(r"\b([a-z][a-z0-9+.-]*)://([^\s/'\"<>)\]]*)(/[^\s'\"<>)\]]*)?", re.I),
     lambda m: f"{m.group(1)}://{m.group(2)}" + ("/<path>" if m.group(3) and m.group(3) != "/" else "")),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), "<time>"),
    (re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), "<time>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<addr>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<host>"),
    (re.compile(r"\blocalhost\b|\[::1\]", re.I), "<host>"),
    (re.compile(r"\b[A-Za-z]:[\\/](?:[^\s\\/:'\"()<>\[\],]+[\\/])*([^\s\\/:'\"()<>\[\],]*)"),
     lambda m: "<path>/" + m.group(1)),
    (re.compile(r"(?<![\w.<>/:])(?:~|\.{1,2})?/(?:[^\s/:'\"()<>\[\],]+/)+([^\s/:'\"()<>\[\],]*)"),
     lambda m: "<path>/" + m.group(1)),
    (re.compile(r"\b\d+\.\d+\.\d+(?:-[A-Za-z]\w*(?:\.\d+)?|\.(?:Final|RELEASE|GA))?\b"), "<ver>"),
    (re.compile(r"(\.(?:java|kt|kts|scala|groovy|py|js|mjs|cjs|ts|tsx|jsx|go|rs|rb|php|cs|cpp|cc|c|h|swift|gradle))"
                r":\d+(?::\d+)?\b"), r"\1:<n>"),
    (re.compile(r"\bline \d+\b"), "line <n>"),
    (re.compile(r"\b(pid|PID)\s*[=:]?\s*\d+"), r"\1 <n>"),
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|secs|seconds|min|mins|minutes)\b"), "<dur>"),
    (re.compile(r"\$\$[\w$]*"), ""),
    (re.compile(r"\blambda\$[\w$]*"), "lambda"),
    (re.compile(r"\$\d+\b"), "$<n>"),
    (re.compile(r"(?i)\b(?:tmp|temp)[\w.-]*\d{3,}[\w.-]*"), "<tmp>"),
    (re.compile(r"(?i)(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])\b[0-9a-f]{7,}\b"), "<hash>"),
    (re.compile(r":(\d{5})\b"), lambda m: ":<port>" if int(m.group(1)) >= 32768 else m.group(0)),
    (re.compile(r"(?<![\w.])-?\d{6,}\b"), "<n>"),
    (re.compile(r"\s+"), " "),
)
PLACEHOLDERS = {"host", "path", "time", "hash", "uuid", "ver", "dur", "port", "tmp", "pid", "addr"}


def clean(text):
    """Убирает цвета терминала и перерисовки прогресс-баров."""
    text = ANSI_RE.sub("", text or "")
    return "\n".join(line.split("\r")[-1] for line in text.splitlines())


def normalize(line):
    for pattern, replacement in NORMALIZE:
        line = pattern.sub(replacement, line)
    return line.strip()


def cut_chain(line):
    """Maven вкладывает причины через «: » — оставляем последние три звена, там корень."""
    line = re.sub(r"\s*-> \[Help \d+\]$", "", line)
    if len(line) > 160 and line.count(": ") >= 3:
        line = ": ".join(line.split(": ")[-3:])
    return line


def spring_description(lines):
    if "APPLICATION FAILED TO START" not in lines:
        return []
    out, inside = [], False
    for line in lines[lines.index("APPLICATION FAILED TO START") + 1:]:
        if line == "Description:":
            inside = True
        elif line == "Action:":
            break
        elif inside and line:
            out.append(line)
            if len(out) == 2:
                break
    return out


def exception_lines(lines):
    out = []
    for line in lines:
        if not line or line.startswith(("at ", "...")):
            continue
        match = QUALIFIED_EXC.match(line) or BARE_EXC.match(line)
        if match:
            out.append(match.group(1))
    return out


def gradle_lines(lines):
    out, inside = [], False
    for line in lines:
        if line == "* What went wrong:":
            inside = True
        elif inside and (line.startswith("* ") or BUILD_END.match(line)):
            inside = False
        elif inside:
            text = line.lstrip("> ").strip()
            if text and not GRADLE_GENERIC.match(text):
                out.append(text)
    return out


def maven_lines(lines):
    out = []
    for line in lines:
        if line.startswith("[ERROR]"):
            text = line[len("[ERROR]"):].strip()
            if text and not MAVEN_NOISE.match(text):
                out.append(text)
    return out[:2]


def keyword_lines(lines):
    return [l for l in lines if l and KEYWORDS.search(l) and not KEYWORD_NOISE.match(l)][:3]


def signature_lines(text):
    """Строки, по которым узнаётся ошибка: описание Spring Boot и исключения, иначе блок Gradle, Maven или ключевые слова."""
    lines = [line.strip() for line in clean(text).splitlines()]
    group = spring_description(lines) + exception_lines(lines)
    chained = False  # у исключений цепочку не режем: имя класса стоит в начале строки
    for fallback in (gradle_lines, maven_lines, keyword_lines):
        if group:
            break
        group, chained = fallback(lines), True
    if not group:
        group = [line for line in lines if line][-3:]
    result = []
    for line in group:
        line = normalize(line)
        line = (cut_chain(line) if chained else line)[:LINE_LIMIT].rstrip()
        if line and line not in result:
            result.append(line)
    if len(result) > 3:
        # обёртка сверху и две самые глубокие причины: в них обычно хост, порт или имя модуля
        result = result[:1] + result[-2:]
    return result


def fingerprint(signature):
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:8]


def analyze(command, output, skip_benign=True):
    """Отпечаток упавшей команды. None — команда безобидная или вывода нет."""
    cmd = parse_command(command)
    if skip_benign and is_benign(cmd):
        return None
    if not clean(output).strip():
        return None
    lines = signature_lines(output)
    if not lines:
        return None
    signature = "\n".join([cmd["tool"]] + lines)
    return {
        "fp": fingerprint(signature),
        "signature": signature,
        "tool": cmd["tool"],
        "key": cmd["key"],
        "kind": "code" if any(CODE_RE.search(line) for line in lines) else "env",
        "command": " ".join((command or "").split())[:160],
    }


def tokens(text):
    return {t for t in re.findall(r"[a-zа-яё0-9_]{3,}", (text or "").lower()) if t not in PLACEHOLDERS}


def similarity(a, b):
    a, b = tokens(a), tokens(b)
    return len(a & b) / len(a | b) if a and b else 0.0


# --- записи в .grabli/ ---------------------------------------------------

def find_root(start):
    start = Path(start).resolve()
    for folder in [start, *start.parents]:
        if (folder / ENTRY_DIR).is_dir() or (folder / ".git").exists():
            return folder
    return start


def project_dir(payload=None):
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return Path(os.environ["CLAUDE_PROJECT_DIR"])
    if payload and payload.get("cwd"):
        return find_root(payload["cwd"])
    return find_root(Path.cwd())


def parse_front(text):
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        return None, text
    fields = {}
    for line in match.group(1).splitlines():
        m = re.match(r"^([a-z][a-z_-]*):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip().strip("\"'")
    return fields, text[match.end():]


def section(body, title):
    match = re.search(r"^##\s+" + re.escape(title) + r"\s*$(.*?)(?=^##\s|\Z)", body, re.S | re.M)
    return match.group(1).strip() if match else None


def first_code_block(text):
    match = re.search(r"```[\w-]*\n(.*?)```", text or "", re.S)
    return match.group(1).strip() if match else ""


def load_entries(root):
    folder = Path(root) / ENTRY_DIR
    entries = []
    if not folder.is_dir():
        return entries
    for path in sorted(folder.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        fields, body = parse_front(text)
        fields = fields or {}
        entries.append({
            "path": path,
            "rel": path.relative_to(root).as_posix(),
            "fields": fields,
            "has_front": bool(fields),
            "fps": [f.lower() for f in re.split(r"[,\s]+", fields.get("fp", "")) if f],
            "title": fields.get("title", ""),
            "signature": first_code_block(section(body, "Сигнатура")),
            "body": body.strip(),
        })
    return entries


def find_matches(entries, fp, signature):
    exact = [e for e in entries if fp in e["fps"]]
    if exact:
        return exact, []
    scored = sorted(((similarity(signature, e["signature"] or e["title"]), e) for e in entries),
                    key=lambda pair: -pair[0])
    return [], [e for score, e in scored if score >= SIMILAR_THRESHOLD][:3]


# --- состояние и журнал событий ------------------------------------------

def data_dir():
    """Журнал и состояние хуков. Не CLAUDE_PLUGIN_DATA: её видят только хуки, а stats запускают из обычного Bash."""
    if os.environ.get("GRABLI_DATA"):
        return Path(os.environ["GRABLI_DATA"])
    return Path.home() / ".grabli"


def project_id(root):
    return os.path.normcase(str(Path(root).resolve()))


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def load_state():
    path = data_dir() / "state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state.setdefault("pending", {})
    state.setdefault("nudges", {})
    limit = now() - PENDING_TTL
    state["pending"] = {k: v for k, v in state["pending"].items()
                        if datetime.datetime.fromisoformat(v["at"]) > limit}
    return state


def save_state(state):
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False)
    os.replace(tmp, folder / "state.json")


def log_event(event, **fields):
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    record = {"t": now().isoformat(timespec="seconds"), "event": event, **fields}
    with (folder / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_events():
    path = data_dir() / "events.jsonl"
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


# --- хуки ----------------------------------------------------------------

def script_call():
    return f'"{sys.executable}" "{Path(__file__).resolve()}"'


def parse_error(error):
    """У Bash и PowerShell первая строка — «Exit code N», дальше общий вывод."""
    lines = (error or "").splitlines()
    match = re.match(r"^Exit code (-?\d+)\s*$", lines[0].strip()) if lines else None
    if not match:
        return None, ""
    return int(match.group(1)), "\n".join(lines[1:])


def context_exact(entry, info):
    return (
        f"Grabli: this failure is a known issue recorded by the team in {entry['rel']} "
        f"(fingerprint {info['fp']}). Check that the cause fits, try the recorded fix before investigating "
        f"further, and tell the user the fix came from Grabli. If the fix is outdated or does not help, "
        f"update the entry with the grabli skill.\n\n{entry['body']}"
    )


def context_similar(entries, info):
    listed = "; ".join(f"{e['rel']} ({e['title']})" for e in entries)
    return (
        f"Grabli: no exact match for fingerprint {info['fp']}, but the team has similar known issues: {listed}. "
        f"Read them if the cause looks the same. If it is the same issue, add fingerprint {info['fp']} "
        f"to the fp line of that entry."
    )


def context_nudge(item):
    return (
        f"Grabli: `{item['command']}` failed earlier in this session and now passes (fingerprint {item['fp']}). "
        f"If the cause was outside the code being written (environment, local services, tool versions, config, "
        f"certificates, proxy, project setup), finish the current step and then record the fix with the grabli "
        f"skill so teammates' agents skip this. Use fingerprint {item['fp']} and this signature exactly:\n\n"
        f"```text\n{item['signature']}\n```\n\n"
        f"Script: {script_call()}\n"
        f"If it was an ordinary code bug, ignore this message."
    )


def hook_failure(payload):
    if payload.get("is_interrupt") or payload.get("tool_name") not in ("Bash", "PowerShell"):
        return None
    command = (payload.get("tool_input") or {}).get("command", "")
    code, output = parse_error(payload.get("error", ""))
    if not code:
        return None
    info = analyze(command, output)
    if info is None:
        return None
    root = project_dir(payload)
    exact, similar = find_matches(load_entries(root), info["fp"], info["signature"])
    state = load_state()
    state["pending"][f"{payload.get('session_id', '')}|{info['key']}"] = {
        **info, "known": bool(exact), "at": now().isoformat()}
    save_state(state)
    log_event("failure", fp=info["fp"], tool=info["tool"], kind=info["kind"], project=project_id(root),
              match="exact" if exact else "similar" if similar else "none")
    if exact:
        return context_exact(exact[0], info)
    if similar:
        return context_similar(similar, info)
    return None


def hook_success(payload):
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return None
    state = load_state()
    session = payload.get("session_id", "")
    if not any(key.startswith(session + "|") for key in state["pending"]):
        return None
    cmd = parse_command((payload.get("tool_input") or {}).get("command", ""))
    item = state["pending"].pop(f"{session}|{cmd['key']}", None)
    if item is None:
        return None
    root = project_dir(payload)
    fields = {"fp": item["fp"], "tool": item["tool"], "kind": item["kind"], "project": project_id(root)}
    recorded = any(item["fp"] in e["fps"] for e in load_entries(root))
    if item["known"] or recorded:
        save_state(state)
        log_event("fixed_known", **fields)
        return None
    if item["kind"] == "code":
        save_state(state)
        log_event("fixed_code", **fields)
        return None
    nudges = state["nudges"].get(session, 0)
    if nudges >= MAX_NUDGES_PER_SESSION:
        save_state(state)
        log_event("fixed_quiet", **fields)
        return None
    state["nudges"][session] = nudges + 1
    save_state(state)
    log_event("nudge", **fields)
    return context_nudge(item)


def run_hook(event):
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")
        handler = {"failure": hook_failure, "success": hook_success}.get(event)
        text = handler(payload) if handler else None
        if text:
            name = "PostToolUseFailure" if event == "failure" else "PostToolUse"
            out = {"hookSpecificOutput": {"hookEventName": name, "additionalContext": text[:CONTEXT_LIMIT]}}
            sys.stdout.write(json.dumps(out, ensure_ascii=True))
    except Exception as exc:  # хук не имеет права ломать работу агента
        try:
            log_event("hook_error", hook=event, error=repr(exc)[:300])
        except Exception:
            pass
    return 0


# --- проверка записей ----------------------------------------------------

SECRETS = (
    ("ключ AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("приватный ключ", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("токен GitHub", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("токен GitLab", re.compile(r"\bglpat-[\w-]{20,}")),
    ("токен Slack", re.compile(r"\bxox[abprs]-[\w-]{10,}")),
    ("ключ API", re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{20,}|\bAIza[0-9A-Za-z_-]{35}\b")),
    ("JWT", re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}")),
    ("пароль в URL", re.compile(r"://[^/\s:@<>]+:[^/\s@<>$]{3,}@")),
    ("пароль или токен", re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\b\s*[=:]\s*['\"]?(?![<$*{])[^\s'\"<>]{6,}")),
)


def check_entries(root):
    errors = []
    entries = load_entries(root)
    owners = {}
    for entry in entries:
        rel = entry["rel"]
        if not entry["has_front"]:
            errors.append(f"{rel}: нет шапки между строками ---")
            continue
        if not entry["fps"]:
            errors.append(f"{rel}: нет поля fp")
        for fp in entry["fps"]:
            if not re.fullmatch(r"[0-9a-f]{8}", fp):
                errors.append(f"{rel}: отпечаток «{fp}» — нужно 8 символов 0-9a-f")
            owners.setdefault(fp, []).append(rel)
        if not entry["title"]:
            errors.append(f"{rel}: нет поля title")
        for title in ("Сигнатура", "Причина", "Решение"):
            if section(entry["body"], title) is None:
                errors.append(f"{rel}: нет раздела «{title}»")
        text = entry["path"].read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            for kind, pattern in SECRETS:
                if pattern.search(line):
                    errors.append(f"{rel}:{number}: похоже на секрет ({kind}) — замени на заглушку вроде <token>")
    for fp, files in owners.items():
        if len(files) > 1:
            errors.append(f"отпечаток {fp} записан в нескольких файлах: {', '.join(files)} — объедини записи")
    return entries, errors


# --- команды для людей ---------------------------------------------------

def read_stdin():
    return sys.stdin.buffer.read().decode("utf-8", errors="replace")


def print_entries(entries, root):
    for e in entries:
        print(f"  {', '.join(e['fps']) or '—':<18} {e['rel']:<40} {e['title']}")


def cmd_fp(args):
    info = analyze(args.command, read_stdin(), skip_benign=False)
    if info is None:
        print("Вывод пустой, отпечаток не из чего снять.")
        return 1
    kind = "ошибка в коде" if info["kind"] == "code" else "окружение"
    print(f"Отпечаток: {info['fp']}\nИнструмент: {info['tool']}\nТип: {kind}\nСигнатура:\n{info['signature']}")
    return 0


def cmd_match(args):
    info = analyze(args.command, read_stdin(), skip_benign=False)
    if info is None:
        print("Вывод пустой, сравнивать не с чем.")
        return 1
    root = find_root(args.dir)
    exact, similar = find_matches(load_entries(root), info["fp"], info["signature"])
    print(f"Отпечаток: {info['fp']}")
    if exact:
        print("Известные грабли:")
        print_entries(exact, root)
    elif similar:
        print("Точного совпадения нет. Похожие записи:")
        print_entries(similar, root)
    else:
        print("Таких граблей в .grabli/ нет.")
    return 0


def cmd_search(args):
    root = find_root(args.dir)
    entries = load_entries(root)
    query = " ".join(args.query).strip().lower()
    if re.fullmatch(r"[0-9a-f]{8}", query):
        found = [e for e in entries if query in e["fps"]]
    else:
        wanted = tokens(query)
        scored = []
        for e in entries:
            words = tokens(" ".join([e["title"], e["body"]]))
            hits = len(wanted & words)
            if hits:
                scored.append((hits, e))
        found = [e for _, e in sorted(scored, key=lambda pair: -pair[0])[:5]]
    if not found:
        print("Ничего не нашлось.")
        return 0
    print_entries(found, root)
    return 0


def cmd_list(args):
    root = find_root(args.dir)
    entries = load_entries(root)
    if not entries:
        print(f"В {ENTRY_DIR}/ пока нет записей.")
        return 0
    print(f"Записей: {len(entries)}")
    print_entries(entries, root)
    return 0


def cmd_check(args):
    root = find_root(args.dir)
    entries, errors = check_entries(root)
    if errors:
        print(f"Ошибок: {len(errors)}")
        for error in errors:
            print(f"  {error}")
        return 1
    print(f"Записей: {len(entries)}, ошибок нет.")
    return 0


def cmd_stats(args):
    root = find_root(args.dir)
    events = read_events()
    if not args.all:
        events = [e for e in events if e.get("project") == project_id(root)]
    if args.days:
        limit = now() - datetime.timedelta(days=args.days)
        events = [e for e in events if datetime.datetime.fromisoformat(e["t"]) >= limit]
    failures = [e for e in events if e["event"] == "failure"]
    count = lambda name: sum(1 for e in events if e["event"] == name)
    exact = sum(1 for e in failures if e.get("match") == "exact")
    similar = sum(1 for e in failures if e.get("match") == "similar")
    code = sum(1 for e in failures if e.get("kind") == "code")
    pct = lambda n: f"{round(100 * n / len(failures))}%" if failures else "—"
    scope = "все проекты" if args.all else f"проект {root.name}"
    if events:
        first = datetime.datetime.fromisoformat(events[0]["t"]).date()
        last = datetime.datetime.fromisoformat(events[-1]["t"]).date()
        days = (last - first).days + 1
        period = f"с {first} по {last} ({days} дн.)"
    else:
        days, period = 0, "данных пока нет"
    entries = len(load_entries(root))
    rows = [
        ("Падений команд", len(failures), ""),
        ("  известные грабли", exact, pct(exact)),
        ("  похожие записи", similar, pct(similar)),
        ("  ошибки в коде", code, pct(code)),
        ("Починились", count("fixed_known") + count("fixed_code") + count("nudge") + count("fixed_quiet"), ""),
        ("  по известной записи", count("fixed_known"), ""),
        ("  напоминаний записать", count("nudge"), ""),
        (f"Записей в {ENTRY_DIR}/", entries, ""),
    ]
    print(f"Грабли · {scope} · {period}\n")
    for label, value, share in rows:
        print(f"{label:<28}{value:>5}  {share}".rstrip())
    print()
    if not failures:
        verdict = "Хуки ещё не видели ни одного падения. Выводы делать рано."
    elif days < EXPERIMENT_DAYS:
        verdict = f"Эксперимент идёт {days} дн. из {EXPERIMENT_DAYS}. Выводы делать рано."
    elif exact / (days / 7) < 1:
        verdict = ("Известные грабли срабатывают реже раза в неделю. Похоже, повторов в этой команде мало "
                   "и Грабли себя не окупают.")
    else:
        verdict = f"Известные грабли срабатывают {exact / (days / 7):.1f} раза в неделю. Повторы есть, идея работает."
    print(f"Вывод: {verdict}")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:
        return run_hook(argv[1] if len(argv) > 1 else "")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="grabli", description="Командная память ошибок окружения")
    parser.add_argument("--dir", default=".", help="папка проекта, по умолчанию текущая")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("fp", "match"):
        p = sub.add_parser(name)
        p.add_argument("--command", default="", help="команда, которая упала, — от неё зависит отпечаток")
    p = sub.add_parser("search")
    p.add_argument("query", nargs="+")
    sub.add_parser("list")
    sub.add_parser("check")
    p = sub.add_parser("stats")
    p.add_argument("--days", type=int, default=0, help="только последние N дней")
    p.add_argument("--all", action="store_true", help="все проекты, а не только текущий")
    args = parser.parse_args(argv)
    handlers = {"fp": cmd_fp, "match": cmd_match, "search": cmd_search, "list": cmd_list,
                "check": cmd_check, "stats": cmd_stats}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
