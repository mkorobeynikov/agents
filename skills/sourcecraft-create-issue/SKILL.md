---
name: sourcecraft-create-issue
description: Use when Codex needs to create a SourceCraft issue/task/задачу in a repository via the public SourceCraft REST API, especially from a user request, implementation plan, bug report, or generated task description.
---

# SourceCraft Create Issue

## Overview

Создавать задачи SourceCraft через Public REST API. В API сущность задачи называется `issue`; в пользовательских запросах "задача", "task" и "issue" считать одним и тем же.

Использовать официальный endpoint `POST https://api.sourcecraft.tech/repos/.../issues` и аутентификацию `Authorization: Bearer <token>`.

## Required Configuration

Никогда не просить пользователя прислать токен в чат и не печатать токен в ответах. Перед созданием задачи проверить переменные окружения:

- `SOURCECRAFT_TOKEN` или `SOURCECRAFT_PAT` - bearer token. В CI SourceCraft может быть доступен `SOURCECRAFT_TOKEN`; локально обычно используется PAT.
- `SOURCECRAFT_ORG_SLUG` - slug организации по умолчанию. Использовать, если пользователь работает в одной организации и часто меняет только репозитории.
- `SOURCECRAFT_API_BASE` - опционально, по умолчанию `https://api.sourcecraft.tech`.

Репозиторий не брать из переменных окружения. Пользователь работает с несколькими репозиториями, поэтому при каждом создании задачи явно указывать репозиторий одним способом:

- `--repo repo-slug` - основной вариант, если задан `SOURCECRAFT_ORG_SLUG`;
- `--repo org-slug/repo-slug` - полный явный вариант, переопределяет организацию из env;
- `--repo-id repo-id`;
- `--org-slug org-slug --repo-slug repo-slug`.

Если токена нет, остановиться и дать пользователю короткую команду с нужным `export`, без выдуманных реальных значений. Если `SOURCECRAFT_ORG_SLUG` не задан и пользователь указал только короткий repo slug, попросить указать организацию или использовать полный `org/repo`. Если репозиторий не указан в запросе пользователя, задать один уточняющий вопрос: в какой репозиторий создать задачу.

## Workflow

1. Сформировать понятные `title` и `description` из запроса пользователя или текущего контекста. Если не хватает сути задачи, задать один уточняющий вопрос.
2. Определить целевой репозиторий из запроса пользователя. Если организация задана в `SOURCECRAFT_ORG_SLUG`, передавать только `--repo repo-slug`. Для неоднозначных слов вроде "фронт" или "бэк" использовать только известное из текущего контекста соответствие; иначе уточнить точный repo slug.
3. Использовать `scripts/create_issue.py`; не собирать `curl` и JSON вручную, если скрипт подходит.
4. Для связанных рабочих задач по умолчанию использовать `--status-slug open` и `--priority normal`, если пользователь не указал другое.
5. Для дочерних BE/FE задач к parent US обязательно передавать parent issue:
   - `--parent-issue tz#9`, если parent в организации `SOURCECRAFT_ORG_SLUG`;
   - `--parent-issue tcp-org/tz#9`, если нужно указать организацию явно;
   - `--parent-issue-id <issue-id>`, если известен ID parent issue.
   Скрипт создаст связь `parent_of` от parent US к новой задаче, то есть новая задача станет sub-task.
6. Передавать labels только одним способом: либо `--label-slug`, либо `--label-id`. Не смешивать их в одном запросе.
7. После успешного создания сообщить `id`, `slug`, `title`, ссылку и созданную связь, если она создавалась.

## Command Examples

Постоянная настройка организации в пользовательском окружении:

```bash
export SOURCECRAFT_ORG_SLUG="tcp-org"
```

Минимальный вызов:

```bash
python3 ~/.agents/skills/sourcecraft-create-issue/scripts/create_issue.py \
  --repo backend-repo \
  --title "Исправить обработку ошибок авторизации" \
  --description "Контекст, ожидаемое поведение и критерии готовности."
```

Дочерняя backend/frontend задача, сразу привязанная к parent US:

```bash
python3 ~/.agents/skills/sourcecraft-create-issue/scripts/create_issue.py \
  --repo workskill-be \
  --title "[BE] D9/S12: Реализовать backend отчетности по обучению" \
  --description-file /tmp/sourcecraft-issue.md \
  --parent-issue tz#9 \
  --status-slug open \
  --priority normal
```

С описанием из файла и метками:

```bash
python3 ~/.agents/skills/sourcecraft-create-issue/scripts/create_issue.py \
  --repo backend-repo \
  --title "Добавить аудит изменений ролей" \
  --description-file /tmp/sourcecraft-issue.md \
  --priority critical \
  --label-slug backend \
  --label-slug security
```

Проверить тело запроса без отправки:

```bash
python3 ~/.agents/skills/sourcecraft-create-issue/scripts/create_issue.py \
  --repo frontend-repo \
  --title "Проверочная задача" \
  --description "Dry run." \
  --dry-run
```

## API Notes

Тело создания issue поддерживает:

- `title` - обязательно, до 1024 символов;
- `description` - до 64 KiB;
- `status_slug` - системные значения включают `open`, `inProgress`, `paused`, `closed`, `declined`, `duplicate`;
- `priority` - `trivial`, `minor`, `normal`, `critical`, `blocker`;
- `visibility` - `public` или `private`;
- `assignee_id`, `milestone_id`, `milestone_slug`, `deadline`;
- `label_ids` или `label_slugs`;
- `linked_pr_ids` или `linked_pr_slugs`.

Связь дочерней задачи с parent US создается отдельным API-вызовом `POST /issues/id:{issue_id}/issue_links` или `POST /repos/{org}/{repo}/issues/{issue}/issue_links` с `link_type=parent_of`. В терминах API link читается как `{sourceIssue} {verb} {targetIssue}`: parent US `parent_of` новая BE/FE задача.

При ошибке API использовать `error_code`, `message` и `request_id` из ответа для краткой диагностики.
