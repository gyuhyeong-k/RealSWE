from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from pydantic import ValidationError

from .construct import construct
from .errors import RealSWEError
from .io import read_jsonl, read_yaml
from .models import ConstructSettings, RephraseSettings
from .paths import config_path
from .rephrase import rephrase


def _config(value: str | None, command: str) -> dict[str, Any]:
    if not value:
        return {}
    raw = read_yaml(config_path(value))
    section = raw.get(command, raw)
    if not isinstance(section, dict):
        raise RealSWEError(f"{command} config must be a YAML mapping")
    return section


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="realswe",
        description="Construct and linguistically rephrase RealSWE benchmarks.",
    )
    parser.add_argument("--version", action="version", version="realswe 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)

    construct_parser = commands.add_parser(
        "construct", help="Materialize a benchmark from ordered information fields."
    )
    construct_parser.add_argument("--config", help="YAML path or name under configs/.")
    construct_parser.add_argument("--name")
    construct_parser.add_argument("--style")
    construct_parser.add_argument(
        "--bug", help="One composition (PDREA) or weighted mix (PA=25,PDREA=75)."
    )
    construct_parser.add_argument(
        "--feature", help="One composition (PMA) or weighted mix (P=75,PA=25)."
    )
    construct_parser.add_argument(
        "--seed", help="Reproducible sampling seed; defaults to the current time."
    )
    construct_parser.add_argument("--output-dir")
    construct_parser.add_argument("--families", help=argparse.SUPPRESS)
    construct_parser.add_argument("--styles-dir", help=argparse.SUPPRESS)

    rephrase_parser = commands.add_parser(
        "rephrase", help="Generate a new linguistic style profile."
    )
    rephrase_parser.add_argument("--config", help="YAML path or name under configs/.")
    rephrase_parser.add_argument("--name")
    rephrase_parser.add_argument("--model")
    rephrase_parser.add_argument(
        "--reasoning-effort", choices=("minimal", "low", "medium", "high")
    )
    rephrase_parser.add_argument("--workers", type=int)
    rephrase_parser.add_argument("--max-retries", type=int)
    rephrase_parser.add_argument("--output-dir")
    rephrase_parser.add_argument("--families", help=argparse.SUPPRESS)
    rephrase_parser.add_argument("--base-url")
    rephrase_parser.add_argument("--api-key")
    rephrase_parser.add_argument("--resume", action="store_true")
    return parser


def _overrides(namespace: argparse.Namespace, names: Sequence[str]) -> dict[str, Any]:
    return {
        name: getattr(namespace, name)
        for name in names
        if getattr(namespace, name, None) is not None
    }


def _composition_spec(value: str | None, label: str) -> str | dict[str, float] | None:
    if value is None or ("=" not in value and ":" not in value):
        return value
    weights: dict[str, float] = {}
    for item in value.split(","):
        item = item.strip()
        separator = "=" if "=" in item else ":" if ":" in item else None
        if not item or separator is None:
            raise RealSWEError(
                f"{label} mix must use COMPOSITION=WEIGHT, e.g. PA=25,PDREA=75"
            )
        composition, raw_weight = (part.strip() for part in item.split(separator, 1))
        if composition in weights:
            raise RealSWEError(f"duplicate {label} composition: {composition}")
        try:
            weights[composition] = float(raw_weight)
        except ValueError as exc:
            raise RealSWEError(
                f"invalid {label} weight for {composition!r}: {raw_weight!r}"
            ) from exc
    return weights


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "construct":
            settings = ConstructSettings.model_validate(_config(args.config, "construct"))
            construct_overrides = _overrides(
                args,
                (
                    "name",
                    "style",
                    "seed",
                    "output_dir",
                    "families",
                    "styles_dir",
                ),
            )
            if args.bug is not None:
                construct_overrides["bug"] = _composition_spec(args.bug, "bug")
            if args.feature is not None:
                construct_overrides["feature"] = _composition_spec(args.feature, "feature")
            settings = ConstructSettings.model_validate(
                {
                    **settings.model_dump(),
                    **construct_overrides,
                }
            )
            target = construct(settings)
            print(f"created benchmark: {target}")
            print(f"sampling seed: {read_yaml(target / 'manifest.yaml')['seed']}")
            return 0

        settings = RephraseSettings.model_validate(_config(args.config, "rephrase"))
        settings = RephraseSettings.model_validate(
            {
                **settings.model_dump(),
                **_overrides(
                    args,
                    (
                        "name",
                        "model",
                        "reasoning_effort",
                        "workers",
                        "max_retries",
                        "output_dir",
                        "families",
                    ),
                ),
            }
        )
        result = rephrase(
            settings,
            resume=args.resume,
            base_url=args.base_url,
            api_key=args.api_key,
        )
        print(f"style profile: {result.path}")
        print(f"completed: {result.completed}/{result.expected}")
        if not result.is_complete:
            latest = {r["instance_id"]: r for r in read_jsonl(result.path / "checkpoint.jsonl")}
            errors = Counter(
                f"{r['error']['type']}: {r['error']['message']}"
                for r in latest.values()
                if r.get("error")
            )
            if errors:
                print(f"most common error: {errors.most_common(1)[0][0]}", file=sys.stderr)
            print("fix the problem and run the same command again with --resume", file=sys.stderr)
        return 0 if result.is_complete else 1
    except (RealSWEError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
