# Протокол ручного прогона

Главный сценарий из [`evals/record-postgres`](../evals/record-postgres/prompt.md), прогнанный 2026-11-02 на Windows 11, Python 3.12, Git Bash. Хуки вызывались так же, как их вызывает Claude Code: JSON в stdin скрипта `hooks/run.sh`, ответ в stdout. Логи взяты из [`tests/fixtures/`](../tests/fixtures/), проект — пустой репозиторий `shop-api`.

## 1. Сессия Димы: `bootRun` падает

```
$ ./gradlew bootRun   [PostToolUseFailure, сессия dima-1, код хука 0]
(хук промолчал)
```

Записей в `.grabli/` нет, поэтому хук только запомнил падение с отпечатком `4f63b1dc`.

## 2. Дима поднял базу, `bootRun` прошёл

```
$ ./gradlew bootRun   [PostToolUse, сессия dima-1, код хука 0]
Grabli: `./gradlew bootRun` failed earlier in this session and now passes (fingerprint 4f63b1dc).
If the cause was outside the code being written (environment, local services, tool versions, config,
certificates, proxy, project setup), finish the current step and then record the fix with the grabli
skill so teammates' agents skip this. Use fingerprint 4f63b1dc and this signature exactly:

gradle
org.springframework.beans.factory.BeanCreationException: Error creating bean with name 'entityManagerFactory' …
org.postgresql.util.PSQLException: Connection to <host>:5432 refused. Check that the hostname and port …
java.net.ConnectException: Connection refused

Script: "…\python.exe" "…\grabli\skills\grabli\scripts\grabli.py"
If it was an ordinary code bug, ignore this message.
```

## 3. Агент Димы записывает решение по скиллу

Шаг «Decide»: база не была запущена, это окружение, а не код. Записываем.

```
$ grabli.py search postgres refused
Ничего не нашлось.
$ git config user.name
Дима
```

Агент пишет [`.grabli/postgres-not-running.md`](postgres-not-running.md) по шаблону: отпечаток и сигнатура из сообщения хука, причина, решение, проверка. Секретов и личных путей нет.

```
$ grabli.py check
Записей: 1, ошибок нет.
```

Ответ пользователю:

> Записал грабли «Postgres из docker-compose не запущен» в `.grabli/postgres-not-running.md`. Закоммить папку `.grabli/` вместе с остальными изменениями.

## 4. Через месяц, сессия Оли: та же ошибка на Linux

У Оли другие время, PID, хост `127.0.0.1` вместо `localhost`, путь `/home/olya/…`, версия драйвера `42.7.5` и номера строк. Отпечаток тот же.

```
$ cd /home/olya/projects/shop && ./gradlew bootRun --console=plain   [PostToolUseFailure, сессия olya-1, код хука 0]
Grabli: this failure is a known issue recorded by the team in .grabli/postgres-not-running.md
(fingerprint 4f63b1dc). Check that the cause fits, try the recorded fix before investigating further,
and tell the user the fix came from Grabli. …

## Причина
Приложение стартует раньше базы: контейнер `db` из `docker-compose.yml` не запущен. …

## Решение
docker compose up -d db
```

## 5. Агент Оли применил решение, `bootRun` прошёл

```
$ cd /home/olya/projects/shop && ./gradlew bootRun --console=plain   [PostToolUse, сессия olya-1, код хука 0]
(хук промолчал)
```

Запись уже есть, просить нечего. В журнал ушло событие «починились по известной записи».

## 6. Ошибка компиляции и её починка

```
$ ./gradlew compileJava   [PostToolUseFailure, сессия olya-1, код хука 0]
(хук промолчал)
$ ./gradlew compileJava   [PostToolUse, сессия olya-1, код хука 0]
(хук промолчал)
```

`cannot find symbol` помечен как ошибка в коде, напоминания записать нет.

## 7. Testcontainers без Docker

```
$ ./gradlew test --tests OrderRepositoryIT   [PostToolUseFailure, сессия olya-1, код хука 0]
(хук промолчал)
```

Записи нет, похожих тоже: хук не мешает и только запоминает падение.

## 8. Статистика

```
$ grabli.py stats
Грабли · проект shop-api · с 2026-11-02 по 2026-11-02 (1 дн.)

Падений команд                  4
  известные грабли              1  25%
  похожие записи                0  0%
  ошибки в коде                 1  25%
Починились                      3
  по известной записи           1
  напоминаний записать          1
Записей в .grabli/              1

Вывод: Эксперимент идёт 1 дн. из 14. Выводы делать рано.
```

## Сверка с критериями кейса

| Критерий из `evals/record-postgres` | Итог |
|---|---|
| Новый файл в `.grabli/` с `fp` из 8 символов и `title` | да, `4f63b1dc` |
| Разделы «Сигнатура», «Причина», «Решение» | да, плюс «Проверка» |
| Отпечаток из скрипта, не выдуман | да, из сообщения хука |
| В решении `docker compose up -d db` блоком кода | да |
| В сигнатуре `<host>:5432`, нет `dima` и `/Users/` | да |
| `check` прогнан, путь назван, напомнил закоммитить | да |
| Не коммитил сам | да |
