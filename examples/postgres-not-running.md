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
org.springframework.beans.factory.BeanCreationException: Error creating bean with name 'entityManagerFactory' defined in class path resource [org/springframework/boot/autoconfigure/orm/jpa/HibernateJpaConfiguration.class]: Unable to create
org.postgresql.util.PSQLException: Connection to <host>:5432 refused. Check that the hostname and port are correct and that the postmaster is accepting TCP/IP connections.
java.net.ConnectException: Connection refused
```

## Причина

Приложение стартует раньше базы: контейнер `db` из `docker-compose.yml` не запущен. Чаще всего после перезагрузки ноутбука или `docker compose down`.

## Решение

```bash
docker compose up -d db
```

Поднимает только базу, остальные сервисы не трогает.

## Проверка

`./gradlew bootRun` доходит до строки `Started ShopApplication`.
