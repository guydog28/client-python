"""Small adapter from the published Context client to the demo workflow."""

from __future__ import annotations

import os

from ezclassify_rest_client import (
    EzClassifyContext,
    RestClientCredentials,
    connect_context,
)
from ezclassify_contract import AggregateResult, DocumentAuditReport


def credentials_from_env() -> RestClientCredentials | None:
    """Read the caller and Context tokens a secured runtime asks for.

    ``EZCLASSIFY_ACCESS_TOKEN`` identifies the caller and
    ``EZCLASSIFY_CONTEXT_TOKEN`` is the signed Context credential. Returns
    ``None`` when neither is set, which is what a local runtime without
    authentication expects.
    """
    access = os.environ.get("EZCLASSIFY_ACCESS_TOKEN") or None
    context = os.environ.get("EZCLASSIFY_CONTEXT_TOKEN") or None
    if access is None and context is None:
        return None
    return RestClientCredentials(access_token=access, context_token=context)


class EzClassifyClient:
    """Bind the demo to one published Context using the real Python SDK."""

    def __init__(
        self,
        base_url: str,
        context_id: str,
        context_version: str | None = None,
        credentials: RestClientCredentials | None = None,
    ) -> None:
        self._context: EzClassifyContext = connect_context(
            base_url,
            context_id=context_id,
            context_version=context_version,
            credentials=credentials,
        )

    def audit(self, text: str) -> DocumentAuditReport:
        """Audit a document through the bound Context's composed scheme."""
        return self._context.document.audit(text).result

    def aggregate(self, markings: list[str]) -> AggregateResult:
        """Aggregate markings through the bound Context's composed scheme."""
        return self._context.scheme.aggregate(markings).result

    def close(self) -> None:
        """Release the underlying SDK connection pool."""
        self._context.close()

    def __enter__(self) -> "EzClassifyClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
