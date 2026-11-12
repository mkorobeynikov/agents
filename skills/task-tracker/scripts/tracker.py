#!/usr/bin/env python3
"""CLI для API трекера задач GBO (task-tracker.gboteam.ru, /api/v1)."""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

STATUSES = ["backlog", "next", "in_progress", "done", "cancelled"]
TYPES = ["feature", "bug", "task"]
PRIORITIES = ["low", "normal", "high", "critical"]
PATCHABLE = ["title", "description", "type", "status", "priority", "assigneeId", "dueDate", "milestoneId", "labelIds"]
PAGE_LIMIT = 50


class TrackerError(Exception):
    pass


class Client:
    def __init__(self):
        token = os.environ.get("TASK_TRACKER_TOKEN")
        if not token:
            raise TrackerError("TASK_TRACKER_TOKEN не задан: ожидается в ~/.task-tracker.env, подключённом из ~/.zshenv")
        self.base = os.environ.get("TASK_TRACKER_URL", "https://task-tracker.gboteam.ru").rstrip("/")
        self.token = token
        # Корпоративный хост недоступен через локальный HTTP(S)_PROXY — ходим напрямую.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method, path, query=None, body=None):
        url = f"{self.base}/api/v1{path}"
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None}, doseq=True)
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            payload = error.read().decode(errors="replace")
            raise TrackerError(f"{method} {path} -> HTTP {error.code}: {payload}") from None
        except urllib.error.URLError as error:
            raise TrackerError(f"{method} {path} -> {error.reason}") from None
        return json.loads(raw) if raw else None

    def paginate(self, path, query, max_items):
        items, cursor = [], None
        while True:
            page = self.call("GET", path, {**query, "limit": PAGE_LIMIT, "cursor": cursor})
            items.extend(page.get("items", []))
            cursor = page.get("nextCursor")
            if not cursor or (max_items and len(items) >= max_items):
                return items[:max_items] if max_items else items

    def project_id(self, ref):
        if str(ref).isdigit():
            return int(ref)
        for project in self.paginate("/projects", {}, 0):
            if str(project.get("key", "")).upper() == str(ref).upper():
                return project["id"]
        raise TrackerError(f"проект {ref} не найден")

    def resolve_task(self, ref, project=None):
        """Возвращает (projectId, taskId) по ссылке, ключу KEY-N или внутреннему id."""
        match = re.search(r"/projects/(\d+)/tasks/(\d+)", ref)
        if match:
            return int(match.group(1)), int(match.group(2))
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)-(\d+)", ref)
        if match:
            project_id = self.project_id(match.group(1))
            public_key = ref.upper()
            found = [task for task in self.call("GET", f"/projects/{project_id}/tasks",
                                                {"search": public_key, "limit": PAGE_LIMIT})["items"]
                     if task.get("publicKey") == public_key]
            if not found:
                raise TrackerError(f"задача {public_key} не найдена")
            return project_id, found[0]["id"]
        if ref.isdigit() and project is not None:
            return self.project_id(project), int(ref)
        raise TrackerError("укажи ссылку на задачу, ключ вида FACTORY-12 или внутренний id вместе с --project")


def emit(value):
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def read_text(args, inline_name, file_name):
    path = getattr(args, file_name, None)
    if path:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    return getattr(args, inline_name, None)


def cmd_projects(client, args):
    emit(client.paginate("/projects", {}, 0))


def cmd_list(client, args):
    query = {"status": args.status, "type": args.type, "priority": args.priority,
             "assigneeId": args.assignee_id, "search": args.search}
    tasks = client.paginate(f"/projects/{client.project_id(args.project)}/tasks", query, args.max)
    if args.full:
        emit(tasks)
        return
    emit([{key: task.get(key) for key in ("id", "publicKey", "type", "status", "priority", "title", "dueDate")}
          | {"assignee": (task.get("assignee") or {}).get("login")} for task in tasks])


def cmd_get(client, args):
    project_id, task_id = client.resolve_task(args.task, args.project)
    task = client.call("GET", f"/projects/{project_id}/tasks/{task_id}")
    task["url"] = f"{client.base}/projects/{project_id}/tasks/{task_id}"
    if not args.no_comments:
        timeline = client.paginate(f"/projects/{project_id}/tasks/{task_id}/comments", {}, 0)
        task["timeline"] = timeline if args.with_audit else [item for item in timeline if item.get("kind") == "comment"]
    emit(task)


def cmd_comment(client, args):
    body = read_text(args, "body", "body_file")
    if not body:
        raise TrackerError("пустой комментарий: передай --body или --body-file")
    project_id, task_id = client.resolve_task(args.task, args.project)
    emit(client.call("POST", f"/projects/{project_id}/tasks/{task_id}/comments", body={"body": body}))


def cmd_update(client, args):
    project_id, task_id = client.resolve_task(args.task, args.project)
    current = client.call("GET", f"/projects/{project_id}/tasks/{task_id}")
    changes = {"title": args.title, "description": read_text(args, "description", "description_file"),
               "type": args.type, "status": args.status, "priority": args.priority, "dueDate": args.due_date}
    changes = {key: value for key, value in changes.items() if value is not None}
    if args.assignee_id is not None:
        changes["assigneeId"] = None if args.assignee_id == 0 else args.assignee_id
    if args.label_ids is not None:
        changes["labelIds"] = args.label_ids
    if not changes:
        raise TrackerError("нечего менять")
    body = {"expectedVersion": current["version"], **{key: current.get(key) for key in PATCHABLE}, **changes}
    body["labelIds"] = body.get("labelIds") or []
    if args.dry_run:
        emit(body)
        return
    emit(client.call("PATCH", f"/projects/{project_id}/tasks/{task_id}", body=body))


def cmd_create(client, args):
    body = {"title": args.title, "description": read_text(args, "description", "description_file") or "",
            "type": args.type, "priority": args.priority, "status": args.status,
            "assigneeId": args.assignee_id, "dueDate": args.due_date, "labelIds": args.label_ids or []}
    body = {key: value for key, value in body.items() if value is not None}
    if args.dry_run:
        emit(body)
        return
    emit(client.call("POST", f"/projects/{client.project_id(args.project)}/tasks", body=body))


def cmd_api(client, args):
    body = json.loads(args.body) if args.body else None
    query = dict(pair.split("=", 1) for pair in args.query)
    emit(client.call(args.method.upper(), args.path, query, body))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("projects", help="список проектов").set_defaults(handler=cmd_projects)

    listing = sub.add_parser("list", help="задачи проекта с фильтрами")
    listing.add_argument("--project", required=True, help="id или ключ проекта (FACTORY)")
    listing.add_argument("--status", choices=STATUSES)
    listing.add_argument("--type", choices=TYPES)
    listing.add_argument("--priority", choices=PRIORITIES)
    listing.add_argument("--assignee-id", type=int)
    listing.add_argument("--search", help="полнотекстовый поиск, в том числе по ключу задачи")
    listing.add_argument("--max", type=int, default=200, help="максимум задач, 0 — все")
    listing.add_argument("--full", action="store_true", help="полные объекты вместо сводки")
    listing.set_defaults(handler=cmd_list)

    def task_arg(command):
        command.add_argument("task", help="ссылка на задачу, ключ FACTORY-12 или внутренний id")
        command.add_argument("--project", help="id или ключ проекта, если task — внутренний id")

    get = sub.add_parser("get", help="задача с комментариями")
    task_arg(get)
    get.add_argument("--no-comments", action="store_true")
    get.add_argument("--with-audit", action="store_true", help="включить аудит-события ленты")
    get.set_defaults(handler=cmd_get)

    comment = sub.add_parser("comment", help="добавить комментарий")
    task_arg(comment)
    comment.add_argument("--body")
    comment.add_argument("--body-file")
    comment.set_defaults(handler=cmd_comment)

    update = sub.add_parser("update", help="изменить поля задачи")
    task_arg(update)
    update.add_argument("--title")
    update.add_argument("--description")
    update.add_argument("--description-file")
    update.add_argument("--type", choices=TYPES)
    update.add_argument("--status", choices=STATUSES)
    update.add_argument("--priority", choices=PRIORITIES)
    update.add_argument("--assignee-id", type=int, help="0 — снять исполнителя")
    update.add_argument("--due-date", help="YYYY-MM-DD")
    update.add_argument("--label-ids", type=int, nargs="*")
    update.add_argument("--dry-run", action="store_true")
    update.set_defaults(handler=cmd_update)

    create = sub.add_parser("create", help="создать задачу")
    create.add_argument("--project", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--description")
    create.add_argument("--description-file")
    create.add_argument("--type", choices=TYPES, default="task")
    create.add_argument("--priority", choices=PRIORITIES, default="normal")
    create.add_argument("--status", choices=STATUSES, default="backlog")
    create.add_argument("--assignee-id", type=int)
    create.add_argument("--due-date")
    create.add_argument("--label-ids", type=int, nargs="*")
    create.add_argument("--dry-run", action="store_true")
    create.set_defaults(handler=cmd_create)

    raw = sub.add_parser("api", help="произвольный запрос к /api/v1")
    raw.add_argument("method")
    raw.add_argument("path", help="путь после /api/v1, например /projects/1/labels")
    raw.add_argument("--query", nargs="*", default=[], help="key=value")
    raw.add_argument("--body", help="JSON-тело")
    raw.set_defaults(handler=cmd_api)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        args.handler(Client(), args)
    except TrackerError as error:
        print(f"ошибка: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
