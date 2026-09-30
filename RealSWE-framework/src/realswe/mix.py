from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from time import time_ns
from typing import Any

from .composition import validate_composition
from .errors import RealSWEError


@dataclass(frozen=True)
class CompositionPlan:
    by_instance: dict[str, str]
    policy: dict[str, str | dict[str, float]]
    seed: str


_SOURCE_NAMESPACE = {
    "swebench_verified": "verified",
    "swebench_pro": "pro",
}


def _weights(
    issue_type: str, spec: str | dict[str, float]
) -> dict[str, float]:
    if isinstance(spec, str):
        validate_composition(issue_type, spec)
        return {spec: 1.0}
    if not spec:
        raise RealSWEError(f"{issue_type} composition mix cannot be empty")
    for composition, weight in spec.items():
        validate_composition(issue_type, composition)
        if weight <= 0:
            raise RealSWEError(
                f"{issue_type} composition weight must be positive: {composition}={weight}"
            )
    return dict(spec)


def _largest_remainder(total: int, weights: dict[str, float | int]) -> dict[str, int]:
    denominator = sum(Decimal(str(weight)) for weight in weights.values())
    if total < 0 or not weights or denominator <= 0:
        raise RealSWEError(f"invalid allocation weights: {weights}")
    raw = {
        key: Decimal(total) * Decimal(str(weight)) / denominator
        for key, weight in weights.items()
    }
    result = {
        key: int(value.to_integral_value(rounding=ROUND_FLOOR))
        for key, value in raw.items()
    }
    remaining = total - sum(result.values())
    ranked = sorted(
        weights,
        key=lambda key: (-(raw[key] - result[key]), key),
    )
    for key in ranked[:remaining]:
        result[key] += 1
    return result


def _stable_rank(
    records: list[dict[str, Any]],
    seed: str,
    source: str,
    issue_type: str,
) -> list[dict[str, Any]]:
    namespace = _SOURCE_NAMESPACE.get(source, source)
    prefix = f"{seed}|assign-arm|{namespace}|{issue_type}"

    def key(record: dict[str, Any]) -> tuple[bytes, str]:
        instance_id = record["instance_id"]
        digest = hashlib.sha256(f"{prefix}|{instance_id}".encode("utf-8")).digest()
        return digest, instance_id

    return sorted(records, key=key)


def _composition_quotas_by_source(
    composition_counts: dict[str, int],
    source_counts: dict[str, int],
) -> dict[str, dict[str, int]]:
    """Preserve global composition counts while stratifying across sources."""
    remaining_by_source = dict(source_counts)
    result = {source: {} for source in source_counts}
    compositions = sorted(composition_counts)
    for composition in compositions[:-1]:
        if composition_counts[composition] == 0:
            allocation = dict.fromkeys(remaining_by_source, 0)
        else:
            allocation = _largest_remainder(
                composition_counts[composition], remaining_by_source
            )
        for source, count in allocation.items():
            result[source][composition] = count
            remaining_by_source[source] -= count
    last = compositions[-1]
    for source, count in remaining_by_source.items():
        result[source][last] = count
    return result


def build_composition_plan(
    families: list[dict[str, Any]],
    *,
    bug_spec: str | dict[str, float],
    feature_spec: str | dict[str, float],
    seed: str | None = None,
) -> CompositionPlan:
    resolved_seed = str(seed).strip() if seed is not None else str(time_ns())
    if not resolved_seed:
        raise RealSWEError("seed must not be empty")
    specs = {"bug": bug_spec, "feature": feature_spec}
    policy: dict[str, str | dict[str, float]] = {}
    by_instance: dict[str, str] = {}

    for issue_type in ("bug", "feature"):
        records = [
            record for record in families if record.get("issue_type") == issue_type
        ]
        if not records:
            raise RealSWEError(f"family data contains no {issue_type} instances")
        weights = _weights(issue_type, specs[issue_type])
        composition_counts = _largest_remainder(len(records), weights)
        sources = sorted({record["source"] for record in records})
        source_counts = {
            source: sum(record["source"] == source for record in records)
            for source in sources
        }
        quotas = _composition_quotas_by_source(
            composition_counts,
            source_counts,
        )
        for source in sources:
            source_records = [record for record in records if record["source"] == source]
            ranked = _stable_rank(source_records, resolved_seed, source, issue_type)
            offset = 0
            for composition in sorted(weights):
                count = quotas[source][composition]
                for record in ranked[offset : offset + count]:
                    by_instance[record["instance_id"]] = composition
                offset += count
            if offset != len(ranked):
                raise RealSWEError("internal composition allocation error")
        policy[issue_type] = (
            specs[issue_type] if isinstance(specs[issue_type], str) else weights
        )

    if len(by_instance) != len(families):
        raise RealSWEError("family data contains unsupported issue types")
    return CompositionPlan(
        by_instance=by_instance,
        policy=policy,
        seed=resolved_seed,
    )
