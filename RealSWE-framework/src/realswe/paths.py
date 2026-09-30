from __future__ import annotations

import os
import sys
from pathlib import Path

from .errors import RealSWEError


def framework_root() -> Path:
    override = os.environ.get("REALSWE_FRAMEWORK_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        if not (root / "data/task-families.jsonl").is_file():
            raise RealSWEError(f"REALSWE_FRAMEWORK_ROOT has no data/task-families.jsonl: {root}")
        return root

    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "data/task-families.jsonl").is_file():
        return checkout

    installed = Path(sys.prefix) / "share/realswe"
    if (installed / "task-families.jsonl").is_file():
        return installed
    raise RealSWEError(
        "could not locate RealSWE data; set REALSWE_FRAMEWORK_ROOT to the RealSWE-framework directory"
    )


def data_root() -> Path:
    root = framework_root()
    return root / "data" if (root / "data").is_dir() else root


def repository_root() -> Path | None:
    root = framework_root()
    candidate = root.parent
    return candidate if (candidate / "benchmarks").is_dir() else None


def default_benchmark_root() -> Path:
    repo = repository_root()
    return repo / "benchmarks" if repo else Path.cwd() / "benchmarks"


def default_style_root() -> Path:
    return data_root() / "styles"


def config_path(value: str | Path) -> Path:
    direct = Path(value).expanduser()
    if direct.is_file():
        return direct.resolve()
    root = framework_root()
    for name in (str(value), f"{value}.yaml", f"{value}.yml"):
        candidate = root / "configs" / name
        if candidate.is_file():
            return candidate
    raise RealSWEError(f"config does not exist: {value}")

