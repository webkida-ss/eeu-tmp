#!/usr/bin/env python3
"""Fail-closed identity and default-branch gates for online agent workflows."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

ASCII_ID_RE = re.compile(r"[1-9][0-9]*", re.ASCII)
ISSUE_RE = ASCII_ID_RE
RUN_RE = ASCII_ID_RE
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.ASCII)
SHA_RE = re.compile(r"[0-9a-f]{40}", re.ASCII)
BRANCH_RE = re.compile(r"[A-Za-z0-9._/-]+", re.ASCII)


class OnlinePolicyError(ValueError):
    """A request that fails the online workflow trust policy."""


def parse_actor_allowlist(raw: str) -> tuple[str, ...]:
    if not isinstance(raw, str) or not raw:
        raise OnlinePolicyError("Trusted actor ID allowlist is unset")
    if raw != raw.strip() or any(character.isspace() for character in raw):
        raise OnlinePolicyError("Trusted actor IDs cannot contain whitespace")
    values = raw.split(",")
    if any(not value or not ASCII_ID_RE.fullmatch(value) for value in values):
        raise OnlinePolicyError(
            "Trusted actor IDs must be canonical ASCII decimal IDs separated by commas"
        )
    if len(set(values)) != len(values):
        raise OnlinePolicyError("Trusted actor IDs cannot contain duplicates")
    return tuple(values)


def authorize_actor(raw_allowlist: str, actor_id: str) -> str:
    trusted = parse_actor_allowlist(raw_allowlist)
    if not isinstance(actor_id, str) or not ASCII_ID_RE.fullmatch(actor_id):
        raise OnlinePolicyError("Request actor ID must be a canonical ASCII decimal ID")
    if actor_id not in trusted:
        raise OnlinePolicyError("Request actor ID is not trusted")
    return actor_id


def require_repository(value: str) -> str:
    if not isinstance(value, str) or not REPOSITORY_RE.fullmatch(value):
        raise OnlinePolicyError("Repository must be canonical OWNER/REPOSITORY")
    return value


def require_sha(value: str, name: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise OnlinePolicyError(f"{name} must be a lowercase full commit SHA")
    return value


def require_positive_ascii(value: str, name: str) -> str:
    if not isinstance(value, str) or not RUN_RE.fullmatch(value):
        raise OnlinePolicyError(f"{name} must be a canonical positive ASCII integer")
    return value


def validate_pre_api_context(
    *,
    trusted_actor_ids: str,
    actor_id: str,
    repository: str,
    issue_number: str | None,
    git_ref: str,
    workflow_ref: str,
    workflow_path: str,
    checked_out_sha: str,
    run_id: str,
    run_attempt: str,
    ref_protected: str,
) -> None:
    authorize_actor(trusted_actor_ids, actor_id)
    require_repository(repository)
    require_sha(checked_out_sha, "Checked-out SHA")
    require_positive_ascii(run_id, "Run ID")
    require_positive_ascii(run_attempt, "Run attempt")
    if ref_protected != "true":
        raise OnlinePolicyError("Workflow ref must be protected by a branch rule or ruleset")
    if issue_number is not None and not ISSUE_RE.fullmatch(issue_number):
        raise OnlinePolicyError("Issue number must be a canonical positive ASCII integer")
    if not workflow_path.startswith(".github/workflows/") or not workflow_path.endswith(
        (".yml", ".yaml")
    ):
        raise OnlinePolicyError("Workflow path is not an approved workflow path")
    expected_prefix = f"{repository}/{workflow_path}@refs/heads/"
    if not workflow_ref.startswith(expected_prefix):
        raise OnlinePolicyError("Workflow ref must name this repository and workflow path")
    branch = workflow_ref.removeprefix(expected_prefix)
    if not BRANCH_RE.fullmatch(branch) or git_ref != f"refs/heads/{branch}":
        raise OnlinePolicyError("Workflow and Git refs must name the same branch")


def validate_default_branch_context(
    *,
    api_get: Callable[[str], dict[str, Any]],
    repository: str,
    git_ref: str,
    workflow_ref: str,
    workflow_path: str,
    checked_out_sha: str,
) -> tuple[str, str]:
    repository_data = api_get(f"/repos/{repository}")
    if repository_data.get("full_name") != repository or repository_data.get("fork") is not False:
        raise OnlinePolicyError("Repository identity or fork state is not trusted")
    default_branch = repository_data.get("default_branch")
    if not isinstance(default_branch, str) or not BRANCH_RE.fullmatch(default_branch):
        raise OnlinePolicyError("Repository default branch is invalid")
    expected_ref = f"refs/heads/{default_branch}"
    expected_workflow_ref = f"{repository}/{workflow_path}@{expected_ref}"
    if git_ref != expected_ref or workflow_ref != expected_workflow_ref:
        raise OnlinePolicyError("Workflow must run from the protected default branch")
    commit_data = api_get(
        f"/repos/{repository}/commits/{urllib.parse.quote(default_branch, safe='')}"
    )
    default_commit = require_sha(commit_data.get("sha"), "Default-branch commit")
    if checked_out_sha != default_commit:
        raise OnlinePolicyError(
            "Checked-out SHA is not the current protected default-branch commit"
        )
    return default_branch, default_commit


def fetch_intake_payload(
    *,
    api_get: Callable[[str], dict[str, Any]],
    trusted_actor_ids: str,
    actor_id: str,
    repository: str,
    issue_number: str,
    git_ref: str,
    workflow_ref: str,
    workflow_path: str,
    checked_out_sha: str,
    run_id: str,
    run_attempt: str,
    ref_protected: str = "true",
) -> dict[str, Any]:
    # This entire validation block intentionally runs before the first API call.
    validate_pre_api_context(
        trusted_actor_ids=trusted_actor_ids,
        actor_id=actor_id,
        repository=repository,
        issue_number=issue_number,
        git_ref=git_ref,
        workflow_ref=workflow_ref,
        workflow_path=workflow_path,
        checked_out_sha=checked_out_sha,
        run_id=run_id,
        run_attempt=run_attempt,
        ref_protected=ref_protected,
    )
    default_branch, default_commit = validate_default_branch_context(
        api_get=api_get,
        repository=repository,
        git_ref=git_ref,
        workflow_ref=workflow_ref,
        workflow_path=workflow_path,
        checked_out_sha=checked_out_sha,
    )
    issue = api_get(f"/repos/{repository}/issues/{issue_number}")
    if issue.get("number") != int(issue_number):
        raise OnlinePolicyError("Issue number does not match the requested issue")
    if issue.get("state") != "open":
        raise OnlinePolicyError("Issue must be open")
    if issue.get("pull_request") is not None:
        raise OnlinePolicyError("Pull requests are not accepted as issue intake")
    author = issue.get("user")
    if not isinstance(author, dict) or not isinstance(author.get("id"), int):
        raise OnlinePolicyError("Issue author immutable ID is unavailable")
    title = issue.get("title")
    body = issue.get("body") or ""
    if not isinstance(title, str) or not isinstance(body, str):
        raise OnlinePolicyError("Issue title and body must be text")
    return {
        "request": {
            "repository": repository,
            "actor_id": actor_id,
            "issue_number": int(issue_number),
            "source_sha": checked_out_sha,
            "workflow_ref": workflow_ref,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "default_branch": default_branch,
            "default_branch_commit": default_commit,
        },
        "repository": {
            "full_name": repository,
            "fork": False,
            "default_branch": default_branch,
        },
        "issue": {
            "number": issue["number"],
            "title": title,
            "body": body,
            "state": issue["state"],
            "user": {"id": author["id"]},
            "pull_request": None,
        },
    }


class GitHubApi:
    def __init__(self, *, token: str, api_url: str) -> None:
        if not token:
            raise OnlinePolicyError("GitHub token is unavailable")
        self.token = token
        self.api_url = api_url.rstrip("/")

    def get(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                parsed = json.loads(response.read())
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise OnlinePolicyError(f"GitHub API request failed for {path}") from error
        if not isinstance(parsed, dict):
            raise OnlinePolicyError(f"GitHub API returned invalid data for {path}")
        return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    intake = subparsers.add_parser("intake")
    intake.add_argument("--output", required=True, type=Path)
    intake.add_argument("--trusted-actor-ids", required=True)
    intake.add_argument("--actor-id", required=True)
    intake.add_argument("--repository", required=True)
    intake.add_argument("--issue-number", required=True)
    intake.add_argument("--git-ref", required=True)
    intake.add_argument("--workflow-ref", required=True)
    intake.add_argument("--workflow-path", required=True)
    intake.add_argument("--checked-out-sha", required=True)
    intake.add_argument("--run-id", required=True)
    intake.add_argument("--run-attempt", required=True)
    intake.add_argument("--ref-protected", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        api = GitHubApi(
            token=os.environ.get("GITHUB_TOKEN", ""),
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        )
        payload = fetch_intake_payload(
            api_get=api.get,
            trusted_actor_ids=args.trusted_actor_ids,
            actor_id=args.actor_id,
            repository=args.repository,
            issue_number=args.issue_number,
            git_ref=args.git_ref,
            workflow_ref=args.workflow_ref,
            workflow_path=args.workflow_path,
            checked_out_sha=args.checked_out_sha,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            ref_protected=args.ref_protected,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (OnlinePolicyError, OSError) as error:
        print(f"Online policy gate rejected request: {error}", file=sys.stderr)
        return 1
    print("Trusted default-branch issue metadata fetched for local sanitization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
