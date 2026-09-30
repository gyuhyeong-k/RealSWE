from __future__ import annotations

from .models import StyleAxes


PROMPT_VERSION = "realswe-rephrase-v3-paper-template"


PROMPT_TEMPLATE = """
# Identity
You are a rephraser. Your task is to rephrase each field of a GitHub issue into content that users actually send to an AI coding agent (such as Claude Code, Codex, or Cursor) in the real world.

# Input
You will receive a structured GitHub issue, which is either a bug report or a feature request.

Bug reports are structured with five fields:
- describe_the_bug
- expected_behavior
- reproduction_code
- environment
- additional_context

Feature requests are structured with three fields:
- desired_solution
- problem_motivation
- additional_context

# Task
Rephrase each field following the instructions below while preserving the original meaning and intent.

# Rephrasing Instructions

1. Formality
   {formality_instruction}

2. Sentence type
   {sentence_type_instruction}

3. Certainty
   {certainty_instruction}

4. Perspective
   {perspective_instruction}

# Rules

1. Preserve code blocks, error messages, tracebacks, version numbers, file paths, and other technical content exactly as-is.

2. Preserve the original meaning and intent.
"""


def _formality(value: str) -> str:
    if value == "preserve":
        return "Preserve the original level of formality."
    return f"If the vocabulary or expressions are not {value}, convert them to {value} ones."


def _certainty(value: str) -> str:
    if value == "preserve":
        return "Preserve the original level of certainty."
    return f"If the vocabulary or expressions are not {value}, convert them to {value} ones."


def _sentence_type(value: str) -> str:
    if value == "preserve":
        return "Preserve the original sentence types."
    alternatives = {
        "imperative": "Declarative and interrogative",
        "declarative": "Imperative and interrogative",
        "interrogative": "Imperative and declarative",
    }
    return f"Prefer {value} types. {alternatives[value]} types are acceptable when more natural."


def _perspective(value: str) -> str:
    if value == "preserve":
        return "Preserve the original perspective."
    target = "first-person" if value == "first_person" else "non-first-person"
    alternative = "Non-first-person" if value == "first_person" else "First-person"
    return f"Prefer {target} perspectives. {alternative} perspectives are acceptable when more natural."


def build_prompt(style: StyleAxes) -> str:
    return PROMPT_TEMPLATE.format(
        formality_instruction=_formality(style.formality),
        certainty_instruction=_certainty(style.certainty),
        sentence_type_instruction=_sentence_type(style.sentence_type),
        perspective_instruction=_perspective(style.perspective),
    )
