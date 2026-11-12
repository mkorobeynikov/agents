---
name: task-tracker
description: "Читает и меняет задачи во внутреннем трекере GBO (task-tracker.gboteam.ru) через REST API с токеном из окружения — задачу с комментариями, списки с фильтрами, проекты; комментирует, меняет статус и поля, создаёт задачи только по явной команде. Использовать, когда пользователь даёт ссылку task-tracker.gboteam.ru/projects/…/tasks/… или ключ вида FACTORY-12, TRACKER-5, ASSTOOL-3, просит разобраться с задачей, посмотреть задачи проекта, отписаться в задачу, перевести её в другой статус. Keywords: трекер, задача, task tracker, gboteam, FACTORY, issue."
---

# Трекер задач GBO

Трекер — `https://task-tracker.gboteam.ru`, API — `/api/v1`, аутентификация `Authorization: Bearer <token>`.
Все обращения делать скриптом `scripts/tracker.py` (только stdlib Python 3.9+): он сам берёт токен,
обходит прокси и знает правила API. Веб-страницы трекера, WebFetch и Playwright не использовать.

## Окружение

- `TASK_TRACKER_TOKEN` и `TASK_TRACKER_URL` лежат в `~/.task-tracker.env` (права `600`), файл подключает
  `~/.zshenv`, поэтому переменные есть в любом новом shell. Если токена нет в окружении, выполнить
  `. ~/.task-tracker.env`; если нет и файла — попросить пользователя создать его, не прося прислать токен в чат.
- Токен никогда не печатать: ни в ответах, ни в командах (`echo $TASK_TRACKER_TOKEN`, `env`, `set -x`).
- Хост недоступен через локальный `HTTP(S)_PROXY` (запрос виснет до таймаута). Скрипт ходит напрямую;
  для ручного `curl` обязательно `--noproxy '*'`.

## Команды

```bash
T=~/.agents/skills/task-tracker/scripts/tracker.py

python3 $T get https://task-tracker.gboteam.ru/projects/1/tasks/12   # задача + комментарии
python3 $T get FACTORY-12                                            # то же по ключу
python3 $T get FACTORY-12 --with-audit                               # плюс аудит-события ленты
python3 $T projects
python3 $T list --project FACTORY --status in_progress --type bug
python3 $T list --project FACTORY --assignee-id 3 --max 0            # все задачи исполнителя
python3 $T list --project FACTORY --search "кэш"

# Изменения — только по явной команде пользователя (см. «Правила»):
python3 $T comment FACTORY-12 --body-file /path/comment.md
python3 $T update FACTORY-12 --status done
python3 $T update FACTORY-12 --priority high --due-date 2026-10-02 --dry-run
python3 $T create --project FACTORY --type bug --title "..." --description-file /path/desc.md --dry-run

# Всё остальное API — сырой запрос (путь после /api/v1):
python3 $T api GET /projects/1/labels
python3 $T api GET /me/work
```

Вывод — JSON в stdout, ошибка — `ошибка: ...` в stderr и код выхода 1. Ошибки API приходят как
`{"code", "message", "requestId"}`; `requestId` приводить при диагностике.

## Модель данных

- **Идентификаторы.** В URL интерфейса и в путях API стоит внутренний `id` задачи, а не её номер в проекте:
  `TRACKER-1` — это `/projects/2/tasks/114`. Ключ `publicKey` = `<ключ проекта>-<taskNumber>`. Голое число
  без `--project` скрипт не принимает — чтобы не перепутать `id` и номер.
- **Проекты:** `FACTORY` (id 1, AI Фабрика), `TRACKER` (2), `ASSTOOL` (3); актуальный список — `projects`.
- **Перечисления:** `status` — `backlog`, `next`, `in_progress`, `done`, `cancelled`; `type` — `feature`,
  `bug`, `task`; `priority` — `low`, `normal`, `high`, `critical`.
- **Лента задачи** (`/tasks/{id}/comments`) смешивает комментарии (`kind: comment`, текст в `body`, Markdown)
  и аудит-события (`kind: audit`, `eventType`, `details`). `get` по умолчанию оставляет только комментарии.
- **Списки** постраничные: `items` + `nextCursor`, `limit` до 50; скрипт дочитывает страницы сам.
  Фильтры API: `status`, `type`, `priority`, `assigneeId`, `search`.
- **Изменение задачи** — `PATCH` с полным набором полей и `expectedVersion` (оптимистическая блокировка).
  Скрипт перечитывает задачу и подставляет текущую `version`; при `stale_version` задачу успели изменить —
  перечитать и повторить, не затирая чужие правки вслепую.
- Задачи, перенесённые из GitLab, содержат в описании ссылку на исходный work item и первый комментарий
  с историей обсуждения из GitLab.

## Правила

1. Чтение (`get`, `list`, `projects`, `api GET`) выполнять без подтверждения.
2. Комментарий, смену статуса или полей делать только по явной команде пользователя на это конкретное
   действие. Текст комментария сначала показать в чате, если пользователь не продиктовал его сам.
3. Создавать задачу только после того, как пользователь одобрил конкретные заголовок и описание: сначала
   `--dry-run`, показать тело, дождаться согласия.
4. «Разобраться с задачей» = прочитать задачу целиком (описание, все комментарии, ссылки на GitLab/MR),
   пересказать суть и текущее состояние расследования, затем работать в коде по правилам репозитория.
   Ничего в трекере при этом не менять без отдельной команды.
