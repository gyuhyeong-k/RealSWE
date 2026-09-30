from __future__ import annotations

from .errors import RealSWEError


FIELD_NAMES: dict[str, dict[str, str]] = {
    "bug": {
        "P": "describe_the_bug",
        "D": "expected_behavior",
        "R": "reproduction_code",
        "E": "environment",
        "A": "additional_context",
    },
    "feature": {
        "P": "desired_solution",
        "M": "problem_motivation",
        "A": "additional_context",
    },
}
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    issue_type: tuple(names) for issue_type, names in FIELD_NAMES.items()
}


def validate_composition(issue_type: str, value: str) -> str:
    if issue_type not in FIELD_ALIASES:
        raise RealSWEError(f"unsupported issue type: {issue_type}")
    if not value:
        raise RealSWEError(f"{issue_type} composition cannot be empty")
    allowed = set(FIELD_ALIASES[issue_type])
    invalid = [alias for alias in value if alias not in allowed]
    if invalid:
        raise RealSWEError(
            f"invalid {issue_type} composition {value!r}; allowed aliases are "
            + "".join(FIELD_ALIASES[issue_type])
        )
    duplicates = sorted({alias for alias in value if value.count(alias) > 1})
    if duplicates:
        raise RealSWEError(
            f"duplicate aliases in {issue_type} composition {value!r}: {''.join(duplicates)}"
        )
    return value


def compose(
    *,
    instance_id: str,
    issue_type: str,
    fields: dict[str, str | None],
    composition: str,
    interface_suffix: str | None,
) -> str:
    validate_composition(issue_type, composition)
    missing = [alias for alias in composition if not (fields.get(alias) or "").strip()]
    if missing:
        raise RealSWEError(
            f"{instance_id}: selected {issue_type} fields are null or empty: {''.join(missing)}"
        )
    body = "\n\n".join(fields[alias] for alias in composition if fields[alias]).rstrip()
    if interface_suffix:
        body += "\n\n" + interface_suffix
    return body
