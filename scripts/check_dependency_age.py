#!/usr/bin/env python3
"""Dependency quarantine gate.

Refuses third-party distributions that were uploaded to PyPI inside a
quarantine window, so a freshly compromised release has to sit on the registry
for a while before it can enter this repository's dependency tree.

Reads pinned requirement files (``name==version`` lines, the ``pip freeze``
shape) because they name the exact versions that would be installed, including
transitive ones. The age comes from the registry's own record: the upload time
of each distribution file of that version at
``<registry>/pypi/<name>/<version>/json``. The newest upload counts, so a file
added to an old version later is held to the window too.

First-party distributions (``ezclassify`` and ``ezclassify-*``) are exempt: a
package published minutes ago by this project must stay installable in the
ordinary publish-then-refresh loop. The window belongs on third-party intake.

The gate fails closed. A registry that cannot be read, a version with no
upload time, a requirement that is not pinned with ``==`` and a run that
exceeds its overall time bound each fail it, and every offender is listed with
the time it clears the window.

Usage::

    python3 scripts/check_dependency_age.py [--days=N] [--lockfile=PATH ...] [--registry=URL]

Each option has an environment form: ``EZCLASSIFY_DEPENDENCY_AGE_DAYS``,
``EZCLASSIFY_DEPENDENCY_AGE_REGISTRY`` and, to shorten the whole-run bound,
``EZCLASSIFY_DEPENDENCY_AGE_OVERALL_TIMEOUT_MS``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_QUARANTINE_DAYS = 7
DEFAULT_REGISTRY = "https://pypi.org"
# One request may not outlast this; a required check must fail on a registry
# that accepts the connection and never answers, not hang the job.
REQUEST_TIMEOUT_SECONDS = 20.0
DEFAULT_OVERALL_TIMEOUT_MS = 5 * 60_000
DEFAULT_LOCKFILE = (
    Path(__file__).resolve().parents[1] / "tools" / "requirements-regen.txt"
)

# PEP 503 names owned by this project.
_FIRST_PARTY = re.compile(r"^ezclassify(-.+)?$")
_PINNED = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==\s*(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)$"
)


class GateError(Exception):
    """A condition that fails the gate without naming one offending package."""


@dataclass(frozen=True)
class Requirement:
    name: str
    version: str


def normalize(name: str) -> str:
    """PEP 503 normalization, the form the registry and the exemption compare."""
    return re.sub(r"[-_.]+", "-", name).lower()


def is_first_party(name: str) -> bool:
    return _FIRST_PARTY.match(normalize(name)) is not None


def read_requirements(path: Path) -> list[Requirement]:
    """Pinned requirements from one file; anything not pinned with ``==`` is an error."""
    requirements: list[Requirement] = []
    logical = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].strip() if not raw.lstrip().startswith("#") else ""
        if line.endswith("\\"):
            logical += line[:-1] + " "
            continue
        logical += line
        statement, logical = logical.strip(), ""
        if not statement:
            continue
        # Drop hash options and environment markers; the pin is what matters.
        statement = statement.split(";", 1)[0]
        statement = re.split(r"\s+--", statement, maxsplit=1)[0].strip()
        match = _PINNED.match(statement)
        if match is None:
            raise GateError(
                f"{path}: cannot confirm the age of '{statement}'; pin it with name==version."
            )
        requirements.append(Requirement(match["name"], match["version"]))
    return requirements


def third_party(requirements: list[Requirement]) -> list[Requirement]:
    """Distinct third-party ``name==version`` pairs, in first-seen order."""
    seen: dict[tuple[str, str], Requirement] = {}
    for requirement in requirements:
        if is_first_party(requirement.name):
            continue
        seen.setdefault((normalize(requirement.name), requirement.version), requirement)
    return list(seen.values())


def fetch_upload_time(
    registry: str, requirement: Requirement, deadline: float
) -> datetime:
    """Newest upload time among the version's distribution files."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GateError(
            f"Ran out of time before checking {requirement.name}=={requirement.version}."
        )
    url = (
        f"{registry}/pypi/{urllib.parse.quote(normalize(requirement.name))}"
        f"/{urllib.parse.quote(requirement.version)}/json"
    )
    if urllib.parse.urlparse(url).scheme not in {"http", "https"}:
        raise GateError(f"Registry {registry} is not an http(s) URL.")
    try:
        with urllib.request.urlopen(  # noqa: S310  # scheme checked above
            url, timeout=min(REQUEST_TIMEOUT_SECONDS, remaining)
        ) as response:
            document = json.load(response)
    except (OSError, ValueError) as cause:
        # URLError, HTTPError, timeouts and socket errors are OSError;
        # json.JSONDecodeError is ValueError.
        raise GateError(
            f"Could not read the publish date of {requirement.name}=={requirement.version} "
            f"from {registry}: {cause}"
        ) from cause
    files = document.get("urls") if isinstance(document, dict) else None
    times: list[datetime] = []
    for entry in files if isinstance(files, list) else []:
        stamp = entry.get("upload_time_iso_8601") if isinstance(entry, dict) else None
        if not isinstance(stamp, str):
            continue
        try:
            parsed = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        times.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC))
    if not times:
        raise GateError(
            f"{registry} reports no upload time for {requirement.name}=={requirement.version}."
        )
    return max(times)


def overall_timeout_seconds() -> float:
    raw = os.environ.get("EZCLASSIFY_DEPENDENCY_AGE_OVERALL_TIMEOUT_MS")
    if raw is None:
        return DEFAULT_OVERALL_TIMEOUT_MS / 1000
    if not raw.isdecimal() or int(raw) <= 0:
        raise GateError(
            f'EZCLASSIFY_DEPENDENCY_AGE_OVERALL_TIMEOUT_MS must be a positive integer, got "{raw}".'
        )
    return int(raw) / 1000


def check(
    requirements: list[Requirement], registry: str, days: float, deadline: float
) -> tuple[list[str], list[str]]:
    """Return (offender lines, unconfirmed lines) for the third-party requirements."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    offenders: list[str] = []
    unconfirmed: list[str] = []
    for requirement in requirements:
        label = f"{requirement.name}=={requirement.version}"
        try:
            uploaded = fetch_upload_time(registry, requirement, deadline)
        except GateError as error:
            unconfirmed.append(f"{label}: {error}")
            continue
        if uploaded > cutoff:
            clears = uploaded + timedelta(days=days)
            offenders.append(
                f"  {label} uploaded {uploaded.isoformat()}, clears {clears.isoformat()}"
            )
    return offenders, unconfirmed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--days", default=None)
    parser.add_argument("--lockfile", action="append", type=Path, default=None)
    parser.add_argument("--registry", default=None)
    options = parser.parse_args(argv)
    try:
        raw_days = options.days or os.environ.get(
            "EZCLASSIFY_DEPENDENCY_AGE_DAYS", str(DEFAULT_QUARANTINE_DAYS)
        )
        try:
            days = float(raw_days)
        except ValueError:
            days = -1.0
        if days < 0 or days != days:
            raise GateError(
                f'Quarantine window must be a non-negative number of days, got "{raw_days}".'
            )
        registry = (
            options.registry
            or os.environ.get("EZCLASSIFY_DEPENDENCY_AGE_REGISTRY")
            or DEFAULT_REGISTRY
        ).rstrip("/")
        deadline = time.monotonic() + overall_timeout_seconds()
        requirements: list[Requirement] = []
        for lockfile in options.lockfile or [DEFAULT_LOCKFILE]:
            requirements += read_requirements(lockfile)
        packages = third_party(requirements)
        if days == 0:
            print("Dependency quarantine window is 0 days; nothing to check.")
            return 0
        offenders, unconfirmed = check(packages, registry, days, deadline)
    except GateError as error:
        print(error, file=sys.stderr)
        return 1
    for line in unconfirmed:
        print(f"Dependency quarantine: {line}", file=sys.stderr)
    if offenders:
        print(
            f"Dependency quarantine: {len(offenders)} third-party package(s) were "
            f"uploaded less than {days:g} day(s) ago.",
            file=sys.stderr,
        )
        print("\n".join(offenders), file=sys.stderr)
        print(
            "Wait out the window, or pin an older version, before taking these in.",
            file=sys.stderr,
        )
    if offenders or unconfirmed:
        return 1
    print(
        f"Dependency quarantine passed: {len(packages)} third-party package(s) "
        f"are all older than {days:g} day(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
