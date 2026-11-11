"""HTTP client for the EzClassify REST API."""

from .client import (
    EzClassifyClient,
    EzClassifyClientError,
    MalformedResponseError,
    PingResult,
    RequestTimeoutError,
    RestClientCredentials,
)
from .context import (
    CtxAccess,
    CtxDocument,
    CtxGuide,
    CtxScheme,
    CtxSchemes,
    CtxCrosswalk,
    EzClassifyContext,
    connect_context,
)
from .offsets import utf8_byte_offset, utf8_index

try:
    from importlib.metadata import version, PackageNotFoundError

    __version__ = version("ezclassify-rest-client")
except PackageNotFoundError:
    __version__ = "1.0.0.dev0"

__all__ = [
    "EzClassifyClient",
    "EzClassifyClientError",
    "MalformedResponseError",
    "PingResult",
    "RequestTimeoutError",
    "RestClientCredentials",
    "connect_context",
    "utf8_byte_offset",
    "utf8_index",
    "EzClassifyContext",
    "CtxScheme",
    "CtxSchemes",
    "CtxGuide",
    "CtxAccess",
    "CtxDocument",
    "CtxCrosswalk",
]
