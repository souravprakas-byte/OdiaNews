from __future__ import annotations

from pathlib import Path
from typing import Any

from odisha_ai_news.models import Language, Source

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal runtimes.
    yaml = None


def load_sources(path: str | Path) -> list[Source]:
    config_path = Path(path)
    text = config_path.read_text(encoding="utf-8")
    payload: dict[str, Any]
    if yaml is not None:
        payload = yaml.safe_load(text)
    else:
        payload = {"sources": _parse_simple_sources_yaml(text)}
    sources = []

    for item in payload.get("sources", []):
        sources.append(
            Source(
                id=item["id"],
                name=item["name"],
                language=Language(item["language"]),
                homepage=item["homepage"],
                priority=int(item.get("priority", 3)),
                methods=tuple(item.get("methods", ["rss", "sitemap", "html"])),
                notes=item.get("notes"),
            )
        )

    return sources


def _parse_simple_sources_yaml(text: str) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "sources:":
            continue

        if line.startswith("- "):
            if current:
                sources.append(current)
            current = {}
            key, value = _split_yaml_pair(line[2:])
            current[key] = _parse_yaml_value(value)
            continue

        if current is not None and ":" in line:
            key, value = _split_yaml_pair(line)
            current[key] = _parse_yaml_value(value)

    if current:
        sources.append(current)

    return sources


def _split_yaml_pair(line: str) -> tuple[str, str]:
    key, value = line.split(":", 1)
    return key.strip(), value.strip()


def _parse_yaml_value(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        items = value[1:-1].split(",")
        return [item.strip().strip("'\"") for item in items if item.strip()]

    if value.isdigit():
        return int(value)

    return value.strip("'\"")
