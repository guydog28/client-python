"""Tests for the Python release version contract."""

import re
from pathlib import Path
from typing import Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_MANIFEST = Path("pyproject.toml")
CANONICAL_MANIFESTS = {
    ROOT_MANIFEST,
    Path("client/pyproject.toml"),
}
VERSION_LINE = re.compile(r'^version\s*=\s*"(?P<version>[^"]+)"')


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


def test_package_versions_move_in_lockstep():
    """Keep the harness and the published client on one release number."""
    versions = {
        relative: _project_version(REPO_ROOT / relative)
        for relative in CANONICAL_MANIFESTS
    }
    assert all(version is not None for version in versions.values())
    assert len({version[0] for version in versions.values() if version}) == 1


def test_the_client_has_no_first_party_dependency():
    """The client is the only published package, so nothing pins a sibling."""
    client_manifest = (REPO_ROOT / "client/pyproject.toml").read_text(encoding="utf-8")
    assert (
        "ezclassify-rest"
        not in client_manifest.split("dependencies = [", 1)[1].split("]", 1)[0]
    )
