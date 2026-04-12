"""Prompt templates and prompt-loading helpers."""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent
_SOUL_PATH = _PROMPTS_DIR / "system" / "SOUL.md"


def load_soul_prompt() -> str:
    """Load the startup persona prompt that should always be present."""
    if not _SOUL_PATH.exists():
        raise FileNotFoundError(f"SOUL prompt not found: {_SOUL_PATH}")
    return _SOUL_PATH.read_text(encoding="utf-8").strip()


def save_soul_prompt(content: str) -> None:
    """Persist the startup persona prompt so the model can update it over time."""
    _SOUL_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SOUL_PATH.write_text(content.strip() + "\n", encoding="utf-8")


SOUL_PROMPT = load_soul_prompt()


def build_system_prompt(*parts: str | None, include_core: bool = True) -> str:
    """Join prompt fragments into a single system prompt."""
    fragments: list[str] = []
    if include_core and SOUL_PROMPT:
        fragments.append(SOUL_PROMPT)

    for part in parts:
        if part is None:
            continue
        cleaned = part.strip()
        if cleaned:
            fragments.append(cleaned)

    return "\n\n".join(fragments)


CORE_PERSONA_PROMPT = SOUL_PROMPT


def load_core_persona_prompt() -> str:
    """Backward-compatible alias for loading the SOUL prompt."""
    return load_soul_prompt()


def save_core_persona_prompt(content: str) -> None:
    """Backward-compatible alias for updating the SOUL prompt."""
    save_soul_prompt(content)


__all__ = [
    "CORE_PERSONA_PROMPT",
    "SOUL_PROMPT",
    "build_system_prompt",
    "load_core_persona_prompt",
    "load_soul_prompt",
    "save_core_persona_prompt",
    "save_soul_prompt",
]
