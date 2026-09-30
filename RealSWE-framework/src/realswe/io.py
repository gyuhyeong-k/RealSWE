from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

import yaml

from .errors import RealSWEError


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise RealSWEError(f"could not read JSONL {path}: {exc}") from exc


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RealSWEError(f"could not read YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RealSWEError(f"expected a YAML mapping in {path}")
    return value


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )


def index_unique(
    records: Iterable[dict[str, Any]], label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        instance_id = record.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise RealSWEError(f"{label} contains a row without instance_id")
        if instance_id in result:
            raise RealSWEError(f"duplicate instance_id in {label}: {instance_id}")
        result[instance_id] = record
    return result
