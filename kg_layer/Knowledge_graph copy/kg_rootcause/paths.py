"""Paths shared by offline commands and tests."""
from pathlib import Path


def dataset_directory(anchor):
    """Find the repository's supplied test dataset from a package location."""
    path = Path(anchor).resolve()
    for parent in (path, *path.parents):
        candidate = parent / "viseca-2026/data"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("Could not find viseca-2026/data from the knowledge-graph package")