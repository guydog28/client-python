"""Verify CI handoff wheels contain the production installation's exact payload."""

import email
import importlib.metadata
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath


def normalized_name(name: str) -> str:
    """Compare Python distribution names using the registry normalization rule."""
    return re.sub(r"[-_.]+", "-", name).lower()


def installed_payload(path: str) -> bool:
    """Exclude records written by the installer rather than shipped by a wheel."""
    if path.endswith(".pyc"):
        return False
    return not (
        ".dist-info/" in path
        and PurePosixPath(path).name
        in {"RECORD", "INSTALLER", "REQUESTED", "direct_url.json"}
    )


def check_wheel(wheel: Path, distribution: importlib.metadata.Distribution) -> None:
    """Refuse renamed, reversioned, added, removed or changed production payloads."""
    with zipfile.ZipFile(wheel) as archive:
        files = {name for name in archive.namelist() if not name.endswith("/")}
        if any(
            PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
            for name in files
        ):
            raise ValueError("Wheel contains a path outside its installation")
        metadata_files = [
            name for name in files if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise ValueError("Wheel must name exactly one distribution")
        metadata = email.message_from_bytes(archive.read(metadata_files[0]))
        if (
            normalized_name(metadata.get("Name", ""))
            != normalized_name(distribution.metadata["Name"])
            or metadata.get("Version") != distribution.version
        ):
            raise ValueError(
                "Wheel name/version differs from the production installation"
            )
        expected = {
            str(path)
            for path in distribution.files or []
            if installed_payload(str(path))
        }
        shipped = {name for name in files if installed_payload(name)}
        if shipped != expected:
            raise ValueError("Wheel file set differs from the production installation")
        for name in shipped:
            if archive.read(name) != distribution.locate_file(name).read_bytes():
                raise ValueError(
                    f"Wheel payload differs from the production installation: {name}"
                )


def main(directory: Path) -> None:
    """Require one exact handoff wheel per installed first-party distribution."""
    for name in ("ezclassify-rest-client",):
        distribution = importlib.metadata.distribution(name)
        candidates = []
        for wheel in directory.glob("*.whl"):
            with zipfile.ZipFile(wheel) as archive:
                metadata_paths = [
                    path
                    for path in archive.namelist()
                    if path.endswith(".dist-info/METADATA")
                ]
                if len(metadata_paths) != 1:
                    raise ValueError("Wheel must name exactly one distribution")
                metadata = email.message_from_bytes(archive.read(metadata_paths[0]))
                if normalized_name(metadata.get("Name", "")) == name:
                    candidates.append(wheel)
        if len(candidates) != 1:
            raise ValueError(f"Expected exactly one handoff wheel for {name}")
        check_wheel(candidates[0], distribution)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
