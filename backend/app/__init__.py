"""WhisperNotes-Backend. Die Version steht nur in backend/pyproject.toml."""

import tomllib
from pathlib import Path


def _version() -> str:
    try:
        with open(Path(__file__).resolve().parent.parent / "pyproject.toml", "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0.0.0"


__version__ = _version()
