"""Crash-safe local JSON writes; original files survive serialization/IO failures."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path, data, *, indent=None):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp",
                                     dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=indent,
                      allow_nan=False, separators=None if indent else (",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
