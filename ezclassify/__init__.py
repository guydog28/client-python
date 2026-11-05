"""EzClassify Python SDK dev harness (not published to PyPI).

This repo-root package exists for the conformance suite: it provides the
recorded-response HTTP replayer (``ezclassify._replayer``) that replays the
engine's conformance vectors. Everything user-facing is delegated to the
published packages; there is no parallel implementation here.

The client entry points are re-exported for convenience::

    from ezclassify import EzClassifyClient, connect_context

Wire-format model types live in ``ezclassify_contract``.
"""

from ezclassify_rest_client import EzClassifyClient, connect_context

__all__ = [
    "EzClassifyClient",
    "connect_context",
]

try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError

    __version__ = _pkg_version("ezclassify")
except PackageNotFoundError:
    __version__ = "1.0.0.dev0"
