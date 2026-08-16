#!/usr/bin/env python3
"""Create a SourceCraft issue using the public REST API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


API_BASE_DEFAULT = "https://api.sourcecraft.tech"
PRIORITIES = ("trivial", "minor", "normal", "critical", "blocker")
VISIBILITIES = ("public", "private")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a SourceCraft issue in a repository.",
    )
    parser.add_argument("--title", required=True, help="Issue title.")
    parser.add_argument("--description", help="Issue description text.")
    parser.add_argument("--description-file", help="Read issue description from this file.")
    parser.add_argument("--status-slug", default=os.getenv("SOURCECRAFT_DEFAULT_STATUS", "open"))
    parser.add_argument(
        "--priority",
        choices=PRIORITIES,
        default=os.getenv("SOURCECRAFT_DEFAULT_PRIORITY", "normal"),
    )
    parser.add_argument("--visibility", choices=VISIBILITIES)
    parser.add_argument("--assignee-id")
    parser.add_argument("--milestone-id")
    parser.add_argument("--milestone-slug")
    parser.add_argument("--deadline", help="RFC3339 date-time, for example 2026-06-30T18:00:00Z.")
    parser.add_argument("--label-id", action="append", default=[])
    parser.add_argument("--label-slug", action="append", default=[])
    parser.add_argument("--linked-pr-id", action="append", default=[])
    parser.add_argument("--linked-pr-slug", action="append", default=[])
    parser.add_argument(
        "--parent-issue-id",
        help="Create a parent_of link from this existing parent issue ID to the created issue.",
    )
    parser.add_argument(
        "--parent-issue",
        help=(
            "Create a parent_of link from this existing parent issue to the created issue. "
            "Format: repo#issue, org/repo#issue, or https://sourcecraft.dev/org/repo/issues/issue."
        ),
    )
    parser.add_argument("--repo", help="Repository slug, or org-slug/repo-slug.")
    parser.add_argument("--repo-id", help="Repository ID.")
    parser.add_argument(
        "--org-slug",
        help="Organization slug. Defaults to SOURCECRAFT_ORG_SLUG for slug-based targets.",
    )
    parser.add_argument("--repo-slug", help="Repository slug. Alternative to --repo.")
    parser.add_argument("--api-base", default=os.getenv("SOURCECRAFT_API_BASE", API_BASE_DEFAULT))
    parser.add_argument("--silent", action="store_true", help="Ask SourceCraft not to notify subscribers.")
    parser.add_argument("--dry-run", action="store_true", help="Print the request without sending it.")
    return parser.parse_args()


def read_description(args: argparse.Namespace) -> str | None:
    if args.description and args.description_file:
        raise SystemExit("Use either --description or --description-file, not both.")
    if args.description_file:
        with open(args.description_file, "r", encoding="utf-8") as handle:
            return handle.read()
    return args.description


def validate_args(args: argparse.Namespace) -> None:
    if args.label_id and args.label_slug:
        raise SystemExit("Use either --label-id or --label-slug, not both.")
    if args.linked_pr_id and args.linked_pr_slug:
        raise SystemExit("Use either --linked-pr-id or --linked-pr-slug, not both.")
    if args.parent_issue_id and args.parent_issue:
        raise SystemExit("Use either --parent-issue-id or --parent-issue, not both.")
    if args.milestone_id and args.milestone_slug:
        raise SystemExit("Use either --milestone-id or --milestone-slug, not both.")
    if args.priority not in PRIORITIES:
        raise SystemExit(f"--priority must be one of: {', '.join(PRIORITIES)}")
    repo_forms = sum(1 for value in (args.repo, args.repo_id, args.repo_slug) if value)
    if repo_forms != 1:
        raise SystemExit(
            "Specify exactly one repository target: --repo repo, --repo org/repo, "
            "--repo-id id, or --repo-slug repo.",
        )
    if args.repo_id and args.org_slug:
        raise SystemExit("Do not use --org-slug with --repo-id.")
    if args.repo_slug and "/" in args.repo_slug:
        raise SystemExit("--repo-slug must not contain '/'. Use --repo org-slug/repo-slug instead.")
    if args.repo and args.repo.count("/") > 1:
        raise SystemExit("--repo must be repo-slug or org-slug/repo-slug.")
    if args.repo == "" or args.repo_slug == "":
        raise SystemExit("Repository slug must not be empty.")
    if not args.repo_id:
        resolve_slug_target(args)
    if args.parent_issue:
        resolve_parent_issue(args.parent_issue, args)


def resolve_slug_target(args: argparse.Namespace) -> tuple[str, str]:
    repo_value = args.repo_slug or args.repo
    if not repo_value:
        raise SystemExit("Specify a repository with --repo or --repo-slug.")
    if "/" in repo_value:
        org_slug, repo_slug = repo_value.split("/", 1)
        if not org_slug or not repo_slug:
            raise SystemExit("--repo must be repo-slug or org-slug/repo-slug.")
        return org_slug, repo_slug
    org_slug = args.org_slug or os.getenv("SOURCECRAFT_ORG_SLUG")
    if not org_slug:
        raise SystemExit(
            "Set SOURCECRAFT_ORG_SLUG, pass --org-slug, or use --repo org-slug/repo-slug.",
        )
    return org_slug, repo_value


def resolve_parent_issue(parent_issue: str, args: argparse.Namespace) -> tuple[str, str, str]:
    if parent_issue.startswith("http://") or parent_issue.startswith("https://"):
        parsed = urllib.parse.urlparse(parent_issue)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 4 and parts[-2] == "issues":
            return parts[-4], parts[-3], parts[-1]
        raise SystemExit(
            "--parent-issue URL must look like https://sourcecraft.dev/org/repo/issues/issue.",
        )

    if "#" not in parent_issue:
        raise SystemExit("--parent-issue must be repo#issue, org/repo#issue, or SourceCraft issue URL.")

    repo_value, issue_slug = parent_issue.split("#", 1)
    if not repo_value or not issue_slug:
        raise SystemExit("--parent-issue must include both repository and issue slug.")
    if "/" in repo_value:
        org_slug, repo_slug = repo_value.split("/", 1)
        if not org_slug or not repo_slug:
            raise SystemExit("--parent-issue repository must be repo or org/repo.")
        return org_slug, repo_slug, issue_slug

    org_slug = args.org_slug or os.getenv("SOURCECRAFT_ORG_SLUG")
    if not org_slug:
        raise SystemExit(
            "Set SOURCECRAFT_ORG_SLUG, pass --org-slug, or use --parent-issue org/repo#issue.",
        )
    return org_slug, repo_value, issue_slug


def build_body(args: argparse.Namespace) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": args.title,
        "status_slug": args.status_slug,
        "priority": args.priority,
    }
    optional_values = {
        "description": read_description(args),
        "visibility": args.visibility,
        "assignee_id": args.assignee_id,
        "milestone_id": args.milestone_id,
        "milestone_slug": args.milestone_slug,
        "deadline": args.deadline,
    }
    body.update({key: value for key, value in optional_values.items() if value})
    if args.label_id:
        body["label_ids"] = args.label_id
    if args.label_slug:
        body["label_slugs"] = args.label_slug
    if args.linked_pr_id:
        body["linked_pr_ids"] = args.linked_pr_id
    if args.linked_pr_slug:
        body["linked_pr_slugs"] = args.linked_pr_slug
    return body


def build_url(args: argparse.Namespace) -> str:
    base = args.api_base.rstrip("/")
    if args.repo_id:
        repo_id = urllib.parse.quote(args.repo_id, safe="")
        path = f"/repos/id:{repo_id}/issues"
    else:
        org_slug_raw, repo_slug_raw = resolve_slug_target(args)
        org_slug = urllib.parse.quote(org_slug_raw, safe="")
        repo_slug = urllib.parse.quote(repo_slug_raw, safe="")
        path = f"/repos/{org_slug}/{repo_slug}/issues"
    query = "?silent=true" if args.silent else ""
    return f"{base}{path}{query}"


def build_parent_link_url(args: argparse.Namespace) -> str | None:
    if not args.parent_issue_id and not args.parent_issue:
        return None

    base = args.api_base.rstrip("/")
    if args.parent_issue_id:
        issue_id = urllib.parse.quote(args.parent_issue_id, safe="")
        path = f"/issues/id:{issue_id}/issue_links"
    else:
        org_slug_raw, repo_slug_raw, issue_slug_raw = resolve_parent_issue(args.parent_issue, args)
        org_slug = urllib.parse.quote(org_slug_raw, safe="")
        repo_slug = urllib.parse.quote(repo_slug_raw, safe="")
        issue_slug = urllib.parse.quote(issue_slug_raw, safe="")
        path = f"/repos/{org_slug}/{repo_slug}/issues/{issue_slug}/issue_links"
    query = "?silent=true" if args.silent else ""
    return f"{base}{path}{query}"


def build_parent_link_body(issue: dict[str, Any]) -> dict[str, Any]:
    issue_id = issue.get("id")
    if not issue_id:
        raise SystemExit("Created issue response did not include id; cannot create parent issue link.")
    return {
        "target_issue_id": issue_id,
        "link_type": "parent_of",
    }


def auth_token() -> str:
    token = os.getenv("SOURCECRAFT_TOKEN") or os.getenv("SOURCECRAFT_PAT")
    if not token:
        raise SystemExit("Set SOURCECRAFT_TOKEN or SOURCECRAFT_PAT before creating an issue.")
    return token


def post_json(url: str, body: dict[str, Any], token: str) -> dict[str, Any]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"message": raw}
        print(f"SourceCraft API returned HTTP {error.code}", file=sys.stderr)
        print(json.dumps(parsed, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1) from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Could not reach SourceCraft API: {error.reason}") from error


def issue_url(issue: dict[str, Any]) -> str | None:
    repository = issue.get("repository") or {}
    repo_slug = repository.get("slug")
    org_slug = (repository.get("organization") or {}).get("slug")
    issue_slug = issue.get("slug")
    if org_slug and repo_slug and issue_slug:
        return f"https://sourcecraft.dev/{org_slug}/{repo_slug}/issues/{issue_slug}"
    return None


def print_result(issue: dict[str, Any]) -> None:
    print(json.dumps(issue, ensure_ascii=False, indent=2))
    summary = {
        "id": issue.get("id"),
        "slug": issue.get("slug"),
        "title": issue.get("title"),
        "url": issue_url(issue),
    }
    print("\nCreated SourceCraft issue:")
    for key, value in summary.items():
        if value:
            print(f"{key}: {value}")


def print_link_result(link: dict[str, Any]) -> None:
    print("\nCreated SourceCraft issue link:")
    print(json.dumps(link, ensure_ascii=False, indent=2))


def main() -> int:
    args = parse_args()
    validate_args(args)
    body = build_body(args)
    url = build_url(args)
    parent_link_url = build_parent_link_url(args)
    if args.dry_run:
        dry_run: dict[str, Any] = {"url": url, "body": body}
        if parent_link_url:
            dry_run["parent_link"] = {
                "url": parent_link_url,
                "body": {
                    "target_issue_id": "<created issue id>",
                    "link_type": "parent_of",
                },
            }
        print(json.dumps(dry_run, ensure_ascii=False, indent=2))
        return 0
    token = auth_token()
    issue = post_json(url, body, token)
    print_result(issue)
    if parent_link_url:
        print_link_result(post_json(parent_link_url, build_parent_link_body(issue), token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
