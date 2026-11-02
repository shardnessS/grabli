"""Тесты движка Граблей: python -m unittest discover -s tests -v"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "skills" / "grabli" / "scripts"))

import grabli  # noqa: E402

SAME = (
    ("postgres-dima", "postgres-olya"),
    ("testcontainers-1", "testcontainers-2"),
    ("pkix-billing", "pkix-orders"),
    ("flyway-v3", "flyway-v5"),
    ("node-express-mac", "node-express-win"),
    ("pytest-requests-linux", "pytest-requests-mac"),
)
DIFFERENT = (
    "postgres-dima", "datasource-url", "port-in-use", "testcontainers-1", "pkix-billing", "flyway-v3",
    "node-express-mac", "node-lodash", "pytest-requests-linux", "compile-error", "assertion", "gradle-401",
)

ENTRY = """\
---
fp: {fp}
title: Postgres из docker-compose не запущен
tool: gradle
date: 2026-11-02
author: Дима
---

## Сигнатура

```text
{signature}
```

## Причина

Приложение стартует раньше базы: контейнер `db` из docker-compose.yml не запущен.

## Решение

```bash
docker compose up -d db
```

## Проверка

`./gradlew bootRun` доходит до строки `Started ShopApplication`.
"""


def fixture(name):
    text = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")
    first, output = text.split("\n", 1)
    return first[2:], output


def analyze(name):
    return grabli.analyze(*fixture(name))


def payload(name, session="s1", event="failure"):
    command, output = fixture(name)
    data = {"session_id": session, "tool_name": "Bash", "tool_input": {"command": command}}
    if event == "failure":
        data["error"] = "Exit code 1\n" + output
    else:
        data["tool_response"] = {"stdout": "ok", "stderr": ""}
    return data


class Fingerprints(unittest.TestCase):
    def test_same_error_on_different_machines(self):
        for a, b in SAME:
            with self.subTest(pair=(a, b)):
                self.assertEqual(analyze(a)["fp"], analyze(b)["fp"])

    def test_different_errors_do_not_collide(self):
        fps = [analyze(name)["fp"] for name in DIFFERENT]
        self.assertEqual(len(fps), len(set(fps)))

    def test_code_errors_are_marked(self):
        self.assertEqual(analyze("compile-error")["kind"], "code")
        self.assertEqual(analyze("assertion")["kind"], "code")
        for name in ("postgres-dima", "node-express-mac", "pkix-billing", "testcontainers-1"):
            self.assertEqual(analyze(name)["kind"], "env", name)

    def test_postgres_signature_keeps_port_and_root_cause(self):
        signature = analyze("postgres-dima")["signature"]
        self.assertIn("Connection to <host>:5432 refused", signature)
        self.assertIn("java.net.ConnectException: Connection refused", signature)
        self.assertNotIn("dima", signature)

    def test_maven_chain_is_cut_to_root(self):
        signature = analyze("pkix-billing")["signature"]
        self.assertTrue(signature.splitlines()[1].startswith("PKIX path building failed"))

    def test_tool_is_part_of_signature(self):
        output = "Error: Cannot find module 'express'"
        self.assertNotEqual(grabli.analyze("npm start", output)["fp"], grabli.analyze("python app.py", output)["fp"])

    def test_benign_commands_are_skipped(self):
        self.assertIsNone(grabli.analyze("grep -r TODO src", "src/a.txt: No such file or directory"))
        self.assertIsNone(grabli.analyze("git diff --exit-code", "diff --git a/x b/x"))
        self.assertIsNone(grabli.analyze("./gradlew test", "   \n"))

    def test_normalize(self):
        cases = {
            "at 2026-09-12T10:14:03.512+03:00 pid=48213": "at <time> pid <n>",
            r"open C:\Users\olya\code\shop\server.js": "open <path>/server.js",
            "open /home/olya/shop/tests/test_orders.py": "open <path>/test_orders.py",
            "GET https://nexus.shop.local/repository/x.pom": "GET https://nexus.shop.local/<path>",
            "container 3f2a9c1e8b7d failed": "container <hash> failed",
            "id 123e4567-e89b-12d3-a456-426614174000": "id <uuid>",
            "Foo.java:346 and bar.py:12": "Foo.java:<n> and bar.py:<n>",
            "localhost:5432 and 10.0.3.7:54873": "<host>:5432 and <host>:<port>",
            "postgresql-42.7.4.jar in 6s": "postgresql-<ver>.jar in <dur>",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(grabli.normalize(raw), expected)


class Commands(unittest.TestCase):
    def test_key_ignores_flags_and_pipes(self):
        cmd = grabli.parse_command("cd api && ./gradlew test --tests OrderIT 2>&1 | tail -50")
        self.assertEqual(cmd["tool"], "gradle")
        self.assertEqual(cmd["key"], "gradlew test OrderIT")

    def test_key_skips_env_and_wrappers(self):
        cmd = grabli.parse_command("JAVA_HOME=/opt/jdk21 sudo docker compose up -d db")
        self.assertEqual(cmd["key"], "docker compose up")

    def test_parse_error(self):
        self.assertEqual(grabli.parse_error("Exit code 2\nboom"), (2, "boom"))
        self.assertEqual(grabli.parse_error("bash: not found"), (None, ""))


class HookFlow(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.project = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"GRABLI_DATA": self.data.name,
                                                "CLAUDE_PROJECT_DIR": self.project.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.data.cleanup()
        self.project.cleanup()

    def events(self):
        return [e["event"] for e in grabli.read_events()]

    def write_entry(self, info, name="postgres-not-running.md"):
        folder = Path(self.project.name) / ".grabli"
        folder.mkdir(exist_ok=True)
        (folder / name).write_text(ENTRY.format(fp=info["fp"], signature=info["signature"]), encoding="utf-8")

    def test_unknown_failure_then_fix_asks_to_record(self):
        self.assertIsNone(grabli.hook_failure(payload("postgres-dima")))
        text = grabli.hook_success(payload("postgres-dima", event="success"))
        self.assertIn(analyze("postgres-dima")["fp"], text)
        self.assertIn("record the fix", text)
        self.assertEqual(self.events(), ["failure", "nudge"])

    def test_known_failure_shows_the_entry(self):
        self.write_entry(analyze("postgres-dima"))
        text = grabli.hook_failure(payload("postgres-olya", session="s2"))
        self.assertIn("known issue", text)
        self.assertIn("docker compose up -d db", text)
        self.assertIsNone(grabli.hook_success(payload("postgres-olya", session="s2", event="success")))
        self.assertEqual(self.events(), ["failure", "fixed_known"])

    def test_similar_entry_is_suggested(self):
        info = analyze("postgres-dima")
        info["fp"] = "00000000"
        self.write_entry(info)
        text = grabli.hook_failure(payload("postgres-olya"))
        self.assertIn("similar known issues", text)

    def test_code_fix_is_not_nudged(self):
        grabli.hook_failure(payload("compile-error"))
        self.assertIsNone(grabli.hook_success(payload("compile-error", event="success")))
        self.assertEqual(self.events(), ["failure", "fixed_code"])

    def test_success_of_other_command_does_not_pair(self):
        grabli.hook_failure(payload("postgres-dima"))
        other = {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "./gradlew clean"}}
        self.assertIsNone(grabli.hook_success(other))

    def test_nudges_are_capped(self):
        for i in range(grabli.MAX_NUDGES_PER_SESSION + 1):
            command = f"./gradlew bootRun{i}"
            grabli.hook_failure({"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": command},
                                 "error": f"Exit code 1\nError: Cannot connect to service {i}x"})
            grabli.hook_success({"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": command}})
        self.assertEqual(self.events().count("nudge"), grabli.MAX_NUDGES_PER_SESSION)
        self.assertEqual(self.events().count("fixed_quiet"), 1)

    def test_interrupt_and_other_tools_are_ignored(self):
        data = payload("postgres-dima")
        data["is_interrupt"] = True
        self.assertIsNone(grabli.hook_failure(data))
        data = payload("postgres-dima")
        data["tool_name"] = "Read"
        self.assertIsNone(grabli.hook_failure(data))
        self.assertEqual(self.events(), [])

    def test_run_hook_never_fails(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"{not json"))), \
                contextlib.redirect_stdout(out):
            self.assertEqual(grabli.run_hook("failure"), 0)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(self.events(), ["hook_error"])

    def test_check_accepts_good_entry_and_catches_problems(self):
        info = analyze("postgres-dima")
        self.write_entry(info)
        _, errors = grabli.check_entries(Path(self.project.name))
        self.assertEqual(errors, [])

        self.write_entry(info, name="copy.md")
        bad = Path(self.project.name) / ".grabli" / "bad.md"
        bad.write_text("---\nfp: xyz\n---\n\n## Решение\n\nexport TOKEN=ghp_" + "a" * 36 + "\n", encoding="utf-8")
        _, errors = grabli.check_entries(Path(self.project.name))
        text = "\n".join(errors)
        self.assertIn("нескольких файлах", text)
        self.assertIn("«xyz»", text)
        self.assertIn("нет поля title", text)
        self.assertIn("«Причина»", text)
        self.assertIn("токен GitHub", text)

    def test_placeholders_are_not_secrets(self):
        info = analyze("postgres-dima")
        self.write_entry(info)
        entry = Path(self.project.name) / ".grabli" / "postgres-not-running.md"
        entry.write_text(entry.read_text(encoding="utf-8") + "\nexport NEXUS_TOKEN=<token>\npassword: $DB_PASSWORD\n",
                         encoding="utf-8")
        _, errors = grabli.check_entries(Path(self.project.name))
        self.assertEqual(errors, [])

    def test_hooks_and_cli_share_data_dir(self):
        # CLAUDE_PLUGIN_DATA видят только хуки; stats из обычного Bash должен читать тот же журнал
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": self.project.name}):
            self.assertEqual(grabli.data_dir(), Path(self.data.name))
        with mock.patch.dict(os.environ):
            del os.environ["GRABLI_DATA"]
            self.assertEqual(grabli.data_dir(), Path.home() / ".grabli")

    def test_stats(self):
        self.write_entry(analyze("postgres-dima"))
        grabli.hook_failure(payload("postgres-olya"))
        grabli.hook_failure(payload("node-express-mac"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            grabli.main(["--dir", self.project.name, "stats"])
        report = out.getvalue()
        self.assertRegex(report, r"Падений команд\s+2")
        self.assertRegex(report, r"известные грабли\s+1\s+50%")
        self.assertIn("Выводы делать рано", report)


if __name__ == "__main__":
    unittest.main()
