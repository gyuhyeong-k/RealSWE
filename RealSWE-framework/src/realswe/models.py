from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StyleAxes(StrictModel):
    formality: Literal["casual", "formal", "preserve"] = "preserve"
    sentence_type: Literal["imperative", "declarative", "interrogative", "preserve"] = (
        "preserve"
    )
    certainty: Literal["confident", "uncertain", "preserve"] = "preserve"
    perspective: Literal["first_person", "non_first_person", "preserve"] = "preserve"


class ConstructSettings(StrictModel):
    name: str | None = None
    style: str = "paper-default"
    bug: str | dict[str, float] | None = None
    feature: str | dict[str, float] | None = None
    seed: str | None = None
    output_dir: str | None = None
    families: str | None = None
    styles_dir: str | None = None

    @field_validator("seed", mode="before")
    @classmethod
    def normalize_seed(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("seed must not be empty")
        return normalized

    @field_validator("bug", "feature", mode="before")
    @classmethod
    def validate_composition_weights_input(cls, value: Any) -> Any:
        if value is None or isinstance(value, str):
            return value
        if not isinstance(value, dict) or not value:
            raise ValueError("composition mix must be a non-empty mapping")
        for composition, weight in value.items():
            if not isinstance(composition, str) or not composition:
                raise ValueError("composition names must be non-empty strings")
            if isinstance(weight, bool):
                raise ValueError(f"weight for {composition} must be numeric")
        return value

    @field_validator("bug", "feature")
    @classmethod
    def validate_composition_weights(
        cls, value: str | dict[str, float] | None
    ) -> str | dict[str, float] | None:
        if not isinstance(value, dict):
            return value
        for composition, weight in value.items():
            if not math.isfinite(weight) or weight <= 0:
                raise ValueError(f"weight for {composition} must be greater than zero")
        return value



class RephraseSettings(StrictModel):
    name: str | None = None
    model: str | None = None
    reasoning_effort: Literal["minimal", "low", "medium", "high"] = "low"
    workers: int = Field(default=4, ge=1)
    max_retries: int = Field(default=6, ge=1)
    output_dir: str | None = None
    families: str | None = None
    style: StyleAxes = Field(default_factory=StyleAxes)


class BugRephrasedFields(StrictModel):
    describe_the_bug: str | None
    expected_behavior: str | None
    reproduction_code: str | None
    environment: str | None
    additional_context: str | None


class FeatureRephrasedFields(StrictModel):
    desired_solution: str | None
    problem_motivation: str | None
    additional_context: str | None
