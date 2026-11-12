"""The dependency quarantine gate, driven against a local stand-in registry.

scripts/check_dependency_age.py refuses third-party distributions uploaded to
PyPI inside the quarantine window. These tests run the real script as a
subprocess against an in-process HTTP server that mimics
``/pypi/<name>/<version>/json``, so no network is touched.
"""

import json
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_dependency_age.py"


def _stamp(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


class _Registry:
    """Serves canned PyPI JSON documents keyed by ``name/version``."""

    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}
        self.statuses: dict[str, int] = {}
        self.hang: set[str] = set()
        registry = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # http.server hook name
                parts = self.path.strip("/").split("/")
                key = f"{parts[1]}/{parts[2]}" if len(parts) == 4 else self.path
                if key in registry.hang:
                    time.sleep(5)
                status = registry.statuses.get(key)
                if status is None and key not in registry.documents:
                    status = 404
                if status is not None:
                    self.send_response(status)
                    self.end_headers()
                    return
                body = json.dumps(registry.documents[key]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def publish(self, name: str, version: str, *days_ago: float) -> None:
        self.documents[f"{name}/{version}"] = {
            "urls": [{"upload_time_iso_8601": _stamp(d)} for d in days_ago]
        }


@pytest.fixture
def registry():
    stand_in = _Registry()
    yield stand_in
    stand_in.server.shutdown()
    stand_in.server.server_close()


def _run(
    registry: _Registry,
    tmp_path: Path,
    lock: str,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    lockfile = tmp_path / "requirements.txt"
    lockfile.write_text(lock, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            f"--lockfile={lockfile}",
            f"--registry={registry.url}",
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", **(env or {})},
        timeout=60,
    )


def test_a_version_uploaded_inside_the_window_is_refused_with_its_clear_time(
    registry, tmp_path
):
    registry.publish("fresh-lib", "2.0.0", 2)
    result = _run(registry, tmp_path, "fresh-lib==2.0.0\n")
    assert result.returncode == 1
    assert "fresh-lib==2.0.0 uploaded" in result.stderr
    assert "clears" in result.stderr


def test_a_version_older_than_the_window_passes(registry, tmp_path):
    registry.publish("old-lib", "1.0.0", 30)
    result = _run(registry, tmp_path, "old-lib==1.0.0  # pinned\n")
    assert result.returncode == 0, result.stderr
    assert "passed: 1 third-party" in result.stdout


def test_the_newest_file_of_a_version_decides_its_age(registry, tmp_path):
    registry.publish("late-wheel", "1.0.0", 90, 1)
    result = _run(registry, tmp_path, "late-wheel==1.0.0\n")
    assert result.returncode == 1


def test_the_window_is_configurable(registry, tmp_path):
    registry.publish("mid-lib", "1.0.0", 10)
    assert _run(registry, tmp_path, "mid-lib==1.0.0\n").returncode == 0
    assert _run(registry, tmp_path, "mid-lib==1.0.0\n", "--days=14").returncode == 1


def test_first_party_distributions_are_exempt_without_a_registry_lookup(
    registry, tmp_path
):
    # Nothing is published to the stand-in, so any lookup would answer 404.
    result = _run(
        registry,
        tmp_path,
        "ezclassify-rest-client==1.0.0\nEzClassify_Contract==1.0.0\nezclassify==1.0.0\n",
    )
    assert result.returncode == 0, result.stderr
    assert "passed: 0 third-party" in result.stdout


def test_a_third_party_name_that_only_starts_like_ours_is_not_exempt(
    registry, tmp_path
):
    registry.publish("ezclassifyish", "1.0.0", 1)
    assert _run(registry, tmp_path, "ezclassifyish==1.0.0\n").returncode == 1


def test_a_registry_error_fails_closed(registry, tmp_path):
    registry.statuses["broken-lib/1.0.0"] = 503
    result = _run(registry, tmp_path, "broken-lib==1.0.0\n")
    assert result.returncode == 1
    assert "broken-lib==1.0.0" in result.stderr


def test_an_unreachable_registry_fails_closed(tmp_path):
    lockfile = tmp_path / "requirements.txt"
    lockfile.write_text("any-lib==1.0.0\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            f"--lockfile={lockfile}",
            "--registry=http://127.0.0.1:9",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 1


def test_a_version_with_no_upload_time_fails_closed(registry, tmp_path):
    registry.documents["bare-lib/1.0.0"] = {"urls": []}
    result = _run(registry, tmp_path, "bare-lib==1.0.0\n")
    assert result.returncode == 1
    assert "no upload time" in result.stderr


def test_a_registry_that_never_answers_is_cut_off_by_the_overall_bound(
    registry, tmp_path
):
    registry.hang.add("slow-lib/1.0.0")
    started = time.monotonic()
    result = _run(
        registry,
        tmp_path,
        "slow-lib==1.0.0\n",
        env={"EZCLASSIFY_DEPENDENCY_AGE_OVERALL_TIMEOUT_MS": "800"},
    )
    assert result.returncode == 1
    assert time.monotonic() - started < 4


def test_a_requirement_that_is_not_pinned_fails_closed(registry, tmp_path):
    result = _run(registry, tmp_path, "loose-lib>=1.0\n")
    assert result.returncode == 1
    assert "pin it with name==version" in result.stderr


def test_every_offender_is_listed_even_when_another_package_is_unconfirmed(
    registry, tmp_path
):
    registry.publish("fresh-a", "1.0.0", 1)
    registry.statuses["broken-lib/1.0.0"] = 500
    registry.publish("fresh-b", "1.0.0", 3)
    result = _run(
        registry, tmp_path, "fresh-a==1.0.0\nbroken-lib==1.0.0\nfresh-b==1.0.0\n"
    )
    assert result.returncode == 1
    assert "fresh-a==1.0.0 uploaded" in result.stderr
    assert "fresh-b==1.0.0 uploaded" in result.stderr
    assert "broken-lib==1.0.0" in result.stderr
