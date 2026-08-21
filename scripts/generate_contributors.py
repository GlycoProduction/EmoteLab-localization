#!/usr/bin/env python3
"""Generate a dense contributor grid and inject it into README.md.

Contributors are keyed by durable GitHub user id. Current login/avatar are
resolved via GET /user/{id}; accounts that no longer resolve are skipped.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contributors.config.json"
README_PATH = ROOT / "README.md"

START_MARKER = "<!-- CONTRIBUTORS:START -->"
END_MARKER = "<!-- CONTRIBUTORS:END -->"
AVATAR_SIZE = 128
COLUMNS = 6
API_VERSION = "2022-11-28"


def load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    ignore_ids: set[int] = set()
    ignore_logins: set[str] = set()
    for entry in data.get("ignore", []):
        if isinstance(entry, int):
            ignore_ids.add(entry)
        elif isinstance(entry, str) and entry.isdigit():
            ignore_ids.add(int(entry))
        elif isinstance(entry, str):
            ignore_logins.add(entry.lower())

    exclude_dirs = set(data.get("exclude_dirs", []))
    return {
        "ignore_ids": ignore_ids,
        "ignore_logins": ignore_logins,
        "exclude_dirs": exclude_dirs,
    }


def discover_languages(exclude_dirs: set[str]) -> list[str]:
    langs = []
    for entry in ROOT.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name in exclude_dirs:
            continue
        langs.append(entry.name)
    return sorted(langs, key=str.casefold)


def repo_slug() -> tuple[str, str]:
    env = os.environ.get("GITHUB_REPOSITORY", "GlycoProduction/EmoteLab-localization")
    owner, _, repo = env.partition("/")
    if not owner or not repo:
        raise SystemExit(f"Invalid GITHUB_REPOSITORY: {env!r}")
    return owner, repo


def api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "EmoteLab-localization-contributors",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        match = re.match(r"<([^>]+)>", section)
        if match:
            return match.group(1)
    return None


def api_get_json(url: str) -> tuple[object, str | None]:
    """GET JSON; returns (payload, next_link). Raises SystemExit on hard errors."""
    req = urllib.request.Request(url, headers=api_headers())
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            next_url = parse_next_link(resp.headers.get("Link"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API error {exc.code} for {url}: {detail}") from exc
    return json.loads(body), next_url


def fetch_author_ids(owner: str, repo: str, path: str) -> set[int]:
    """Return unique GitHub user ids that authored commits touching path."""
    query = urllib.parse.urlencode({"path": path, "per_page": "100"})
    url: str | None = (
        f"https://api.github.com/repos/{owner}/{repo}/commits?{query}"
    )
    ids: set[int] = set()

    while url:
        payload, next_url = api_get_json(url)
        if not isinstance(payload, list):
            raise SystemExit(f"Unexpected API response for path={path!r}")

        for commit in payload:
            author = commit.get("author")
            if not author:
                continue
            user_id = author.get("id")
            if isinstance(user_id, int):
                ids.add(user_id)

        url = next_url

    return ids


def resolve_login(user_id: int, cache: dict[int, str | None]) -> str | None:
    """Return current login for user_id, or None if the account is gone."""
    if user_id in cache:
        return cache[user_id]

    url = f"https://api.github.com/user/{user_id}"
    req = urllib.request.Request(url, headers=api_headers())
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        # 404: deleted / unknown. 403 without rate-limit: often inaccessible account.
        # Rate-limit 403 must not drop contributors.
        if exc.code == 403 and "rate limit" in detail.lower():
            raise SystemExit(
                f"GitHub API rate limit while resolving user {user_id}: {detail}"
            ) from exc
        if exc.code in (404, 403):
            print(f"Skipping missing user id={user_id} (HTTP {exc.code})")
            cache[user_id] = None
            return None
        raise SystemExit(
            f"GitHub API error {exc.code} resolving user {user_id}: {detail}"
        ) from exc

    login = data.get("login")
    if not isinstance(login, str) or not login:
        print(f"Skipping user id={user_id} (no login in response)")
        cache[user_id] = None
        return None

    cache[user_id] = login
    return login


def collect_contributors(
    langs: list[str],
    ignore_ids: set[int],
    ignore_logins: set[str],
    owner: str,
    repo: str,
) -> dict[str, list[str]]:
    """Map current login -> sorted language codes."""
    by_id: dict[int, set[str]] = defaultdict(set)
    for lang in langs:
        for user_id in fetch_author_ids(owner, repo, lang):
            if user_id in ignore_ids:
                continue
            by_id[user_id].add(lang)

    login_cache: dict[int, str | None] = {}
    by_login: dict[str, set[str]] = defaultdict(set)

    for user_id, langs_for in by_id.items():
        login = resolve_login(user_id, login_cache)
        if login is None:
            continue
        if login.lower() in ignore_logins:
            continue
        by_login[login].update(langs_for)

    return {
        login: sorted(langs_for, key=str.casefold)
        for login, langs_for in sorted(
            by_login.items(), key=lambda item: item[0].casefold()
        )
    }


def render_contributor_cell(login: str, langs: list[str]) -> str:
    avatar = f"https://github.com/{login}.png?size={AVATAR_SIZE}"
    profile = f"https://github.com/{login}"
    lang_line = " ".join(f"<code>{lang}</code>" for lang in langs)
    return (
        f'<td align="center" valign="top">'
        f'<a href="{profile}">'
        f'<img src="{avatar}" width="{AVATAR_SIZE}" height="{AVATAR_SIZE}" '
        f'alt="@{login}"/></a><br/>'
        f'<a href="{profile}"><sub><b>@{login}</b></sub></a>'
        f'{f"<br/><sub>{lang_line}</sub>" if lang_line else ""}'
        f"</td>"
    )


def render_grid(contributors: dict[str, list[str]]) -> str:
    items = list(contributors.items())
    if not items:
        return "_No community contributors found yet._\n"

    width = COLUMNS
    rows: list[str] = []
    for i in range(0, len(items), width):
        chunk = items[i : i + width]
        cells = [render_contributor_cell(login, langs) for login, langs in chunk]
        # Pad so every row has the same column count (keeps layout stable).
        while len(cells) < width:
            cells.append('<td align="center" valign="top"></td>')
        rows.append("<tr>\n" + "\n".join(cells) + "\n</tr>")

    return (
        '<table>\n'
        "<tbody>\n"
        + "\n".join(rows)
        + "\n</tbody>\n"
        "</table>\n"
    )


def build_contributors_markdown(
    langs: list[str],
    ignore_ids: set[int],
    ignore_logins: set[str],
    owner: str,
    repo: str,
) -> str:
    contributors = collect_contributors(
        langs, ignore_ids, ignore_logins, owner, repo
    )
    return render_grid(contributors)


def inject_readme(body: str) -> None:
    text = README_PATH.read_text(encoding="utf-8")
    if START_MARKER not in text or END_MARKER not in text:
        raise SystemExit(
            f"README.md must contain {START_MARKER} and {END_MARKER} markers"
        )

    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER),
        re.DOTALL,
    )
    replacement = f"{START_MARKER}\n{body.rstrip()}\n{END_MARKER}"
    new_text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit("Failed to replace contributors block in README.md")

    if new_text != text:
        README_PATH.write_text(new_text, encoding="utf-8", newline="\n")
        print("Updated README.md contributors section")
    else:
        print("README.md contributors section already up to date")


def main() -> int:
    config = load_config()
    langs = discover_languages(config["exclude_dirs"])
    if not langs:
        print("No language directories found", file=sys.stderr)
        return 1

    owner, repo = repo_slug()
    print(f"Scanning {len(langs)} languages in {owner}/{repo}")
    body = build_contributors_markdown(
        langs,
        config["ignore_ids"],
        config["ignore_logins"],
        owner,
        repo,
    )
    inject_readme(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
