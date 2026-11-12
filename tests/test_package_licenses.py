from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("client",)


def test_distribution_licenses_match_the_canonical_license() -> None:
    canonical = (ROOT / "LICENSE").read_bytes()

    for package in PACKAGES:
        assert (ROOT / package / "LICENSE").read_bytes() == canonical


def test_distribution_metadata_points_at_the_packaged_license() -> None:
    for package in PACKAGES:
        with (ROOT / package / "pyproject.toml").open("rb") as handle:
            pyproject = tomllib.load(handle)

        assert pyproject["project"]["license"] == {"file": "LICENSE"}
