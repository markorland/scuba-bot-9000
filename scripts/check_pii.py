#!/usr/bin/env python3
"""Fail if personal data reaches this public repository.

This repo is public and holds no personal data: the roster, real schedule
emails and database snapshots live in the private companion repo. That rule is
easy to state and easy to forget at 11pm, so it is enforced here rather than
remembered.

Three modes:

    --tracked   every tracked file (CI, and the default)
    --staged    the staged snapshot only (pre-commit hook)
    --history   every commit's message and diff (the periodic standing sweep;
                author metadata is out of scope, see main())

Findings are reported **masked**. CI logs on a public repo are themselves
public, so a check that printed the address it found would publish the thing it
exists to catch.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files that must never exist here at all, whatever they contain.
FORBIDDEN_PATHS = (
    "roster.yaml",
    "roster.yml",
    "*/roster.yaml",
    "*/roster.yml",
    "config/config.yaml",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    ".env",
    ".env.*",
    "snapshots/*",
    "tests/fixtures/real/*",
)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# RFC 2606 / RFC 6761 reserved names. Documentation and synthetic test fixtures
# use these, so they are always allowed; anything else is a real address.
RESERVED_DOMAINS = ("example.com", "example.net", "example.org")
RESERVED_SUFFIXES = (".test", ".example", ".invalid", ".localhost")

ALLOWLIST_FILE = REPO_ROOT / ".pii-allowlist"


def load_allowlist() -> set[str]:
    """Explicit exceptions, one address or bare domain per line."""
    if not ALLOWLIST_FILE.exists():
        return set()
    entries: set[str] = set()
    for line in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            entries.add(line)
    return entries


def is_allowed(address: str, allowlist: set[str]) -> bool:
    address = address.lower()
    if address in allowlist:
        return True
    domain = address.rpartition("@")[2]
    if domain in allowlist:
        return True
    if domain in RESERVED_DOMAINS:
        return True
    if any(domain.endswith("." + d) for d in RESERVED_DOMAINS):
        return True
    return any(domain.endswith(s) for s in RESERVED_SUFFIXES)


def mask(address: str) -> str:
    """b****@g****.com — enough to locate, not enough to publish."""
    local, _, domain = address.partition("@")
    name, dot, tld = domain.rpartition(".")
    return f"{local[:1]}****@{name[:1]}****{dot}{tld}"


def forbidden_path(path: str) -> str | None:
    for pattern in FORBIDDEN_PATHS:
        if fnmatch.fnmatch(path, pattern):
            return pattern
    return None


def scan_text(text: str, allowlist: set[str]) -> list[tuple[int, str]]:
    """Return (line number, masked address) for every disallowed address."""
    found: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in EMAIL_RE.findall(line):
            if not is_allowed(match, allowlist):
                found.append((lineno, mask(match)))
    return found


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout


def listed_files(staged: bool) -> list[str]:
    if staged:
        out = git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    else:
        out = git("ls-files", "-z")
    return [p for p in out.split("\0") if p]


def file_text(path: str, staged: bool) -> str | None:
    """Read from the index when staged, so we check what is being committed."""
    try:
        if staged:
            raw = subprocess.run(
                ["git", "show", f":{path}"],
                cwd=REPO_ROOT,
                capture_output=True,
                check=True,
            ).stdout
        else:
            raw = (REPO_ROOT / path).read_bytes()
    except (subprocess.CalledProcessError, OSError):
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None  # binary; nothing to scan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--tracked", action="store_true", help="all tracked files (default)")
    mode.add_argument("--staged", action="store_true", help="staged snapshot only")
    mode.add_argument("--history", action="store_true", help="all commits, messages and diffs")
    args = parser.parse_args()

    allowlist = load_allowlist()
    problems: list[str] = []

    if args.history:
        # --format drops the Author/Commit headers deliberately. Commit author
        # metadata is a known, accepted exposure on this repo; what this sweep
        # is for is file content and commit messages. Scanning the headers would
        # only tempt someone into writing a real address into .pii-allowlist,
        # which is a public file, to silence it.
        log = git("log", "--all", "-p", "--no-color", "--format=%H%n%B")
        for lineno, masked in scan_text(log, allowlist):
            problems.append(f"git history (line {lineno} of the log): {masked}")
    else:
        staged = args.staged
        for path in listed_files(staged):
            pattern = forbidden_path(path)
            if pattern:
                problems.append(f"{path}: forbidden path (matches {pattern!r})")
                continue
            content = file_text(path, staged)
            if content is None:
                continue
            for lineno, masked in scan_text(content, allowlist):
                problems.append(f"{path}:{lineno}: {masked}")

    if not problems:
        return 0

    print("Personal data must not enter this public repository.\n", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    print(
        "\nAddresses are masked above on purpose: this output is public.\n"
        "Roster data, real schedule emails and snapshots belong in the private\n"
        "companion repo. Documentation may use example.com/.org/.net addresses.\n"
        "Genuine exceptions go in .pii-allowlist.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
