"""Integrity metadata for files exposed through the Agent tool contract."""

from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path
from typing import Any


_CONTENT_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".log": "text/plain",
}


def build_artifact_metadata(path: str, artifact_name: str) -> dict[str, Any]:
    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise FileNotFoundError(path)

    digest = hashlib.sha256()
    with artifact_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)

    suffix = artifact_path.suffix.lower()
    content_type = _CONTENT_TYPES.get(suffix) or mimetypes.guess_type(artifact_path.name)[0] or "application/octet-stream"
    return {
        "name": str(artifact_name),
        "content_type": content_type,
        "size_bytes": artifact_path.stat().st_size,
        "sha256": digest.hexdigest(),
        "created_at": _isoformat_mtime(artifact_path),
    }


def _isoformat_mtime(path: Path) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
