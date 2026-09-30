from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from .composition import FIELD_NAMES
from .errors import RealSWEError
from .io import (
    append_jsonl,
    index_unique,
    read_jsonl,
    read_yaml,
    write_jsonl,
    write_yaml,
)
from .llm import call_structured, configure_client
from .models import BugRephrasedFields, FeatureRephrasedFields, RephraseSettings
from .paths import data_root, default_style_root
from .prompt import PROMPT_VERSION, build_prompt


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SCHEMAS: dict[str, type[BaseModel]] = {
    "bug": BugRephrasedFields,
    "feature": FeatureRephrasedFields,
}


@dataclass(frozen=True)
class RephraseResult:
    path: Path
    completed: int
    expected: int

    @property
    def is_complete(self) -> bool:
        return self.completed == self.expected


def _validate_output(
    instance_id: str,
    source_fields: dict[str, str | None],
    output_fields: dict[str, str | None],
) -> None:
    if source_fields.keys() != output_fields.keys():
        raise RealSWEError(f"{instance_id}: model returned a different field set")
    for alias, source in source_fields.items():
        output = output_fields[alias]
        if source is None and output is not None:
            raise RealSWEError(f"{instance_id}: model invented content for null field {alias}")
        if source is not None and not (output or "").strip():
            raise RealSWEError(f"{instance_id}: model emptied non-null field {alias}")


def _latest_successes(checkpoint_path: Path) -> dict[str, dict[str, Any]]:
    if not checkpoint_path.is_file():
        return {}
    successes: dict[str, dict[str, Any]] = {}
    for record in read_jsonl(checkpoint_path):
        if record.get("error") is None and record.get("rephrased_fields") is not None:
            successes[record["instance_id"]] = record
    return successes


def rephrase(
    settings: RephraseSettings,
    *,
    resume: bool = False,
    base_url: str | None = None,
    api_key: str | None = None,
    caller: Callable[..., tuple[BaseModel, dict[str, Any]]] = call_structured,
) -> RephraseResult:
    if not settings.name:
        raise RealSWEError("rephrase requires --name (or name in the config)")
    if not _SAFE_NAME.fullmatch(settings.name):
        raise RealSWEError(
            "style name must start with an alphanumeric character and contain only "
            "letters, digits, '.', '_' or '-'"
        )
    if not settings.model:
        raise RealSWEError("rephrase requires --model (or model in the config)")

    families_path = (
        Path(settings.families).expanduser().resolve()
        if settings.families
        else data_root() / "task-families.jsonl"
    )
    families = read_jsonl(families_path)
    index_unique(families, "family data")

    output_root = (
        Path(settings.output_dir).expanduser().resolve()
        if settings.output_dir
        else default_style_root()
    )
    target = output_root / settings.name
    request = {
        "format_version": 1,
        "name": settings.name,
        "families": str(families_path),
        "model": settings.model,
        "reasoning_effort": settings.reasoning_effort,
        "style": settings.style.model_dump(),
        "prompt_version": PROMPT_VERSION,
        "base_url": base_url,
    }

    if target.exists():
        if not resume:
            raise RealSWEError(f"style profile already exists; use --resume: {target}")
        stored = read_yaml(target / "request.yaml")
        if stored != request:
            raise RealSWEError("resume configuration does not match the existing profile")
    else:
        if resume:
            raise RealSWEError(f"cannot resume a profile that does not exist: {target}")
        output_root.mkdir(parents=True, exist_ok=True)
        target.mkdir()
        write_yaml(target / "request.yaml", request)
        write_jsonl(target / "data.jsonl", [])
        write_yaml(
            target / "manifest.yaml",
            {
                "format_version": 1,
                "artifact": "realswe_style_profile",
                "name": settings.name,
                "status": "incomplete",
                "instances": 0,
                "expected_instances": len(families),
                "data_file": "data.jsonl",
            },
        )

    checkpoint_path = target / "checkpoint.jsonl"
    successes = _latest_successes(checkpoint_path)
    pending = [family for family in families if family["instance_id"] not in successes]
    configure_client(base_url=base_url, api_key=api_key)
    developer_prompt = build_prompt(settings.style)

    def run_one(family: dict[str, Any]) -> dict[str, Any]:
        instance_id = family["instance_id"]
        issue_type = family["issue_type"]
        public_fields = family["restructured_fields"]
        field_names = FIELD_NAMES[issue_type]
        if set(public_fields) != set(field_names):
            raise RealSWEError(
                f"{instance_id}: family field aliases do not match the {issue_type} schema"
            )
        source_fields = {
            field_name: public_fields[alias]
            for alias, field_name in field_names.items()
        }
        messages = [
            {"role": "developer", "content": developer_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {"issue_type": issue_type, "fields": source_fields},
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]
        started = time.perf_counter()
        try:
            parsed, metadata = caller(
                messages=messages,
                schema=_SCHEMAS[issue_type],
                model=settings.model,
                reasoning_effort=settings.reasoning_effort,
                max_retries=settings.max_retries,
            )
            output_fields = parsed.model_dump()
            _validate_output(instance_id, source_fields, output_fields)
            public_output = {
                alias: output_fields[field_name]
                for alias, field_name in field_names.items()
            }
            return {
                "instance_id": instance_id,
                "rephrased_fields": public_output,
                **metadata,
                "error": None,
            }
        except Exception as exc:
            return {
                "instance_id": instance_id,
                "rephrased_fields": None,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }

    if pending:
        with ThreadPoolExecutor(max_workers=settings.workers) as executor:
            futures = {executor.submit(run_one, family): family for family in pending}
            for future in as_completed(futures):
                record = future.result()
                append_jsonl(checkpoint_path, record)
                if record["error"] is None:
                    successes[record["instance_id"]] = record

    data_records = [
        {
            "instance_id": family["instance_id"],
            "rephrased_fields": successes[family["instance_id"]]["rephrased_fields"],
        }
        for family in families
        if family["instance_id"] in successes
    ]
    data_path = target / "data.jsonl"
    write_jsonl(data_path, data_records)
    status = "complete" if len(data_records) == len(families) else "incomplete"
    write_yaml(
        target / "manifest.yaml",
        {
            "format_version": 1,
            "artifact": "realswe_style_profile",
            "name": settings.name,
            "status": status,
            "instances": len(data_records),
            "expected_instances": len(families),
            "data_file": "data.jsonl",
            "model": settings.model,
            "reasoning_effort": settings.reasoning_effort,
            "style": settings.style.model_dump(),
            "prompt_version": PROMPT_VERSION,
        },
    )
    return RephraseResult(target, len(data_records), len(families))
