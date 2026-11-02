"""Проверка проекта и сборка zip-архивов скиллов для claude.ai.

    python tools/build.py          проверить и собрать dist/<skill>.zip
    python tools/build.py check    только проверить

Только стандартная библиотека Python 3.8+.
"""

import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED = ("claude", "anthropic")
LINK_RE = re.compile(r"\]\(([^)#\s]+)\)")
PLACEHOLDER = "{" * 2
SKIP = {"__pycache__", ".DS_Store", "Thumbs.db"}
TEXT_SUFFIXES = {".md", ".json", ".svg", ".py", ".txt", ".yaml", ".yml"}


def frontmatter(text):
    """Поля вида `key: value` из YAML-шапки SKILL.md (значения в одну строку)."""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    fields = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([a-z][a-z-]*):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip().strip("\"'")
    return fields, text[end + 4:]


def check_name(name, where, errors):
    if not NAME_RE.match(name) or len(name) > 64:
        errors.append(f"{where}: имя «{name}» — только a-z, 0-9 и дефисы, до 64 символов")
    if any(word in name.split("-") for word in RESERVED):
        errors.append(f"{where}: в имени «{name}» нельзя использовать {', '.join(RESERVED)}")


def check_plugin(errors):
    path = ROOT / ".claude-plugin" / "plugin.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: {exc}")
        return
    check_name(manifest.get("name", ""), "plugin.json", errors)
    for field in ("version", "description", "author"):
        if not manifest.get(field):
            errors.append(f"plugin.json: нет поля {field}")
    icon = manifest.get("icon")
    if icon and not (ROOT / icon).is_file():
        errors.append(f"plugin.json: иконка {icon} не найдена")


def check_skill(skill_dir, errors):
    where = skill_dir.relative_to(ROOT).as_posix()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        errors.append(f"{where}: нет SKILL.md")
        return
    text = skill_md.read_text(encoding="utf-8")
    fields, body = frontmatter(text)
    if fields is None:
        errors.append(f"{where}/SKILL.md: нет YAML-шапки между строками ---")
        return
    name = fields.get("name", "")
    check_name(name, f"{where}/SKILL.md", errors)
    if name != skill_dir.name:
        errors.append(f"{where}/SKILL.md: name «{name}» не совпадает с папкой «{skill_dir.name}»")
    description = fields.get("description", "")
    if not description or description in (">", "|", ">-", "|-"):
        errors.append(f"{where}/SKILL.md: description пустой или многострочный — нужна одна строка")
    elif len(description) > 1024:
        errors.append(f"{where}/SKILL.md: description {len(description)} символов, максимум 1024")
    lines = body.count("\n")
    if lines > 500:
        errors.append(f"{where}/SKILL.md: {lines} строк, максимум 500 — вынеси детали в references/")
    for md in skill_dir.rglob("*.md"):
        for target in LINK_RE.findall(md.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("mailto:"):
                continue
            if not (md.parent / target).exists() and not (skill_dir / target).exists():
                errors.append(f"{md.relative_to(ROOT).as_posix()}: битая ссылка {target}")


def check_leftovers(errors):
    for path in ROOT.rglob("*"):
        parts = set(path.relative_to(ROOT).parts)
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES or parts & {".git", "dist", "results"}:
            continue
        if path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if PLACEHOLDER in text:
            errors.append(f"{path.relative_to(ROOT).as_posix()}: осталась заглушка шаблона")
        if path.name == "README.md" and "<!--" in text:
            errors.append(f"{path.relative_to(ROOT).as_posix()}: остались подсказки шаблона <!-- -->")


def build(skills):
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for skill_dir in skills:
        target = dist / f"{skill_dir.name}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(skill_dir.rglob("*")):
                if path.is_file() and not SKIP & set(path.parts):
                    archive.write(path, Path(skill_dir.name) / path.relative_to(skill_dir))
        print(f"  {target.relative_to(ROOT).as_posix()}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    errors = []
    for required in ("README.md", "LICENSE", "assets/icon.svg"):
        if not (ROOT / required).is_file():
            errors.append(f"нет файла {required}")
    check_plugin(errors)
    skills = sorted(p for p in (ROOT / "skills").glob("*") if p.is_dir()) if (ROOT / "skills").is_dir() else []
    if not skills:
        errors.append("в skills/ нет ни одного скилла")
    for skill_dir in skills:
        check_skill(skill_dir, errors)
    check_leftovers(errors)

    if errors:
        print(f"Ошибок: {len(errors)}")
        for error in errors:
            print(f"  {error}")
        return 1
    print(f"Проверка пройдена: скиллов {len(skills)}")
    if sys.argv[1:2] != ["check"]:
        print("Сборка:")
        build(skills)
    return 0


if __name__ == "__main__":
    sys.exit(main())
