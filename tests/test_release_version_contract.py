"""Tests for the Python release version contract."""

import re
from pathlib import Path
from typing import Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_MANIFEST = Path("pyproject.toml")
CANONICAL_MANIFESTS = {
    ROOT_MANIFEST,
    Path("types/pyproject.toml"),
    Path("client/pyproject.toml"),
}
VERSION_LINE = re.compile(r'^version\s*=\s*"(?P<version>[^"]+)"')
INTERNAL_DEPENDENCY_LINE = re.compile(
    r'^\s*"(?P<name>ezclassify-contract)>='
    r'(?P<version>[^"]+)",\s*$'
)


def _project_version(path: Path) -> Optional[Tuple[str, str]]:
    """Return the project version and its source line, if the TOML declares one."""
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
            continue
        if section == "[project]" and (match := VERSION_LINE.match(stripped)):
            return match.group("version"), line
    return None


def _version_bearing_manifests() -> set[Path]:
    """Discover repository package manifests that carry a project version."""
    manifests = set()
    for path in REPO_ROOT.rglob("pyproject.toml"):
        relative = path.relative_to(REPO_ROOT)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if _project_version(path) is not None:
            manifests.add(relative)
    return manifests


def test_canonical_manifests_are_every_versioned_package():
    """Keep every version-bearing package manifest in the lockstep set."""
    assert _version_bearing_manifests() == CANONICAL_MANIFESTS


def test_package_versions_and_internal_floors_move_in_lockstep():
    """Keep package versions and client dependency floors on one release number."""
    versions = {
        relative: _project_version(REPO_ROOT / relative)
        for relative in CANONICAL_MANIFESTS
    }
    assert all(version is not None for version in versions.values())
    current_versions = {version[0] for version in versions.values() if version}
    assert len(current_versions) == 1
    current_version = current_versions.pop()

    dependency_versions = {}
    client_manifest = (REPO_ROOT / "client/pyproject.toml").read_text(encoding="utf-8")
    for line in client_manifest.splitlines():
        if match := INTERNAL_DEPENDENCY_LINE.match(line):
            dependency_versions[match.group("name")] = match.group("version")

    assert dependency_versions == {
        "ezclassify-contract": current_version,
    }
