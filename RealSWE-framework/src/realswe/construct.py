from __future__ import annotations

import os
import re
import shutil
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .composition import compose
from .errors import RealSWEError
from .io import index_unique, read_jsonl, read_yaml, write_jsonl, write_yaml
from .models import ConstructSettings
from .paths import data_root, default_benchmark_root, default_style_root
from .mix import build_composition_plan


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _checked_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise RealSWEError(f"{label} does not exist: {path}")


def _resolve_style(value: str, styles_dir: Path) -> Path:
    direct = Path(value).expanduser()
    if direct.is_dir():
        return direct.resolve()
    candidate = styles_dir / value
    if candidate.is_dir():
        return candidate.resolve()
    raise RealSWEError(f"style profile does not exist: {value}")


def _counts(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(records),
        "by_source": dict(sorted(Counter(r["source"] for r in records).items())),
        "by_issue_type": dict(sorted(Counter(r["issue_type"] for r in records).items())),
        "by_composition": dict(
            sorted(Counter(r["composition"] for r in records).items())
        ),
    }


def construct(settings: ConstructSettings) -> Path:
    if not settings.name:
        raise RealSWEError("construct requires --name (or name in the config)")
    if not _SAFE_NAME.fullmatch(settings.name):
        raise RealSWEError(
            "benchmark name must start with an alphanumeric character and contain only "
            "letters, digits, '.', '_' or '-'"
        )
    if not settings.bug or not settings.feature:
        raise RealSWEError("construct requires both --bug and --feature compositions")

    families_path = (
        Path(settings.families).expanduser().resolve()
        if settings.families
        else data_root() / "task-families.jsonl"
    )
    _checked_file(families_path, "family data")
    families = read_jsonl(families_path)
    family_index = index_unique(families, "family data")
    composition_plan = build_composition_plan(
        families,
        bug_spec=settings.bug,
        feature_spec=settings.feature,
        seed=settings.seed,
    )

    styles_dir = (
        Path(settings.styles_dir).expanduser().resolve()
        if settings.styles_dir
        else default_style_root()
    )
    style_dir = _resolve_style(settings.style, styles_dir)
    style_manifest = read_yaml(style_dir / "manifest.yaml")
    if style_manifest.get("status") != "complete":
        raise RealSWEError(
            f"style profile {style_manifest.get('name', settings.style)!r} is incomplete"
        )
    style_path = style_dir / style_manifest.get("data_file", "data.jsonl")
    _checked_file(style_path, "style data")
    styles = read_jsonl(style_path)
    style_index = index_unique(styles, "style data")
    if style_index.keys() != family_index.keys():
        missing = sorted(family_index.keys() - style_index.keys())
        extra = sorted(style_index.keys() - family_index.keys())
        raise RealSWEError(
            f"family/style ID sets differ (missing={len(missing)}, extra={len(extra)})"
        )

    missing_fields: list[tuple[str, str]] = []
    for family in families:
        composition = composition_plan.by_instance[family["instance_id"]]
        style_fields = style_index[family["instance_id"]].get("rephrased_fields") or {}
        unavailable = [
            alias for alias in composition if not (style_fields.get(alias) or "").strip()
        ]
        if unavailable:
            missing_fields.append((family["instance_id"], "".join(unavailable)))
    if missing_fields:
        examples = ", ".join(f"{iid}({aliases})" for iid, aliases in missing_fields[:5])
        more = " ..." if len(missing_fields) > 5 else ""
        raise RealSWEError(
            f"selected compositions reference null/empty fields in {len(missing_fields)} "
            f"instances: {examples}{more}"
        )

    records: list[dict[str, Any]] = []
    for family in families:
        instance_id = family["instance_id"]
        composition = composition_plan.by_instance[instance_id]
        problem_statement = compose(
            instance_id=instance_id,
            issue_type=family["issue_type"],
            fields=style_index[instance_id]["rephrased_fields"],
            composition=composition,
            interface_suffix=family.get("interface_suffix"),
        )
        records.append(
            {
                "instance_id": instance_id,
                "repo": family["repo"],
                "base_commit": family["base_commit"],
                "issue_type": family["issue_type"],
                "problem_statement": problem_statement,
                "composition": composition,
                "source": family["source"],
                "image_name": family["image_name"],
            }
        )

    output_root = (
        Path(settings.output_dir).expanduser().resolve()
        if settings.output_dir
        else default_benchmark_root()
    )
    target = output_root / settings.name
    if target.exists():
        raise RealSWEError(f"output already exists; refusing to overwrite: {target}")
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = output_root / f".{settings.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary.mkdir()
        data_path = temporary / "tasks.jsonl"
        write_jsonl(data_path, records)
        manifest = {
            "format_version": 1,
            "artifact": "realswe_benchmark",
            "name": settings.name,
            "instances": len(records),
            "data_file": "tasks.jsonl",
            "style_profile": style_manifest.get("name", settings.style),
            "composition": composition_plan.policy,
            "seed": composition_plan.seed,
            "counts": _counts(records),
            "schema": [
                "instance_id",
                "repo",
                "base_commit",
                "issue_type",
                "problem_statement",
                "composition",
                "source",
                "image_name",
            ],
        }
        write_yaml(temporary / "manifest.yaml", manifest)
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target
