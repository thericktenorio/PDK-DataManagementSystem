"""
Drake PDF outline registry — maps bookmark titles to parser roles.

Loads ``fixtures/drake_samples/outline_registry.yaml`` (override via settings).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from django.conf import settings


@dataclass(frozen=True)
class OutlineRule:
    role: str
    priority: int
    match: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class DrakeRegistry:
    schema_version: int
    roles: dict[str, dict[str, Any]]
    rules: tuple[OutlineRule, ...]
    packets: dict[str, dict[str, list[str]]]
    ocr_roles: frozenset[str]
    main_section_order: tuple[str, ...]

    def role_for_title(self, title: str | None) -> str:
        if not title or not str(title).strip():
            return "form_other"
        return self._best_role_for_titles([str(title).strip()])

    def role_for_titles(self, titles: list[str]) -> str:
        cleaned = [str(t).strip() for t in titles if t and str(t).strip()]
        if not cleaned:
            return "form_other"
        return self._best_role_for_titles(cleaned)

    def _best_role_for_titles(self, titles: list[str]) -> str:
        best_role = "form_other"
        best_priority = -1
        for title in titles:
            for rule in self.rules:
                if _title_matches(rule, title) and rule.priority > best_priority:
                    best_priority = rule.priority
                    best_role = rule.role
        return best_role

    def packet_for_role(self, role: str) -> str:
        for packet_name, spec in self.packets.items():
            if role in spec.get("include_roles", []):
                return packet_name
        if role in self.packets.get("main", {}).get("exclude_roles", []):
            return "exclude"
        return "main"

    def ocr_required_if_no_text(self, role: str) -> bool:
        return role in self.ocr_roles

    def main_role_rank(self, role: str) -> int:
        try:
            return self.main_section_order.index(role)
        except ValueError:
            return len(self.main_section_order)


def _title_matches(rule: OutlineRule, title: str) -> bool:
    title_lower = title.lower()
    for pattern in rule.patterns:
        p = pattern.lower()
        if rule.match == "exact":
            if title_lower == p:
                return True
        elif rule.match == "prefix":
            if title_lower.startswith(p):
                return True
        elif rule.match == "substring":
            if p in title_lower:
                return True
        elif rule.match == "exact_or_page_variant":
            if title_lower == p or title_lower.startswith(p + " page"):
                return True
        elif rule.match == "regex":
            if re.search(pattern, title, re.IGNORECASE):
                return True
    return False


def _registry_path() -> Path:
    configured = getattr(settings, "PARSER_OUTLINE_REGISTRY", None)
    if configured:
        return Path(configured).expanduser().resolve()
    base = Path(settings.BASE_DIR)
    return base / "fixtures" / "drake_samples" / "outline_registry.yaml"


@lru_cache(maxsize=1)
def load_drake_registry() -> DrakeRegistry:
    path = _registry_path()
    if not path.is_file():
        raise FileNotFoundError(f"Drake outline registry not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules_raw = raw.get("rules") or []
    rules: list[OutlineRule] = []
    for entry in rules_raw:
        rules.append(
            OutlineRule(
                role=str(entry["role"]),
                priority=int(entry.get("priority", 0)),
                match=str(entry.get("match", "substring")),
                patterns=tuple(str(p) for p in entry.get("patterns") or []),
            )
        )
    rules.sort(key=lambda r: r.priority, reverse=True)

    ocr_roles: set[str] = set()
    for entry in (raw.get("ocr") or {}).get("target_pages") or []:
        if entry.get("pages") == "first_only":
            ocr_roles.add(str(entry["role"]))

    roles_cfg = raw.get("roles") or {}
    for role_name, spec in roles_cfg.items():
        if spec.get("ocr_policy") == "required_if_no_text":
            ocr_roles.add(role_name)

    main_spec = (raw.get("packets") or {}).get("main") or {}
    section_order = tuple(str(r) for r in (main_spec.get("section_order") or []))

    return DrakeRegistry(
        schema_version=int(raw.get("schema_version", 1)),
        roles=roles_cfg,
        rules=tuple(rules),
        packets=raw.get("packets") or {},
        ocr_roles=frozenset(ocr_roles),
        main_section_order=section_order,
    )


def normalize_section_key(title: str | None) -> str | None:
    if not title:
        return None
    normalized = title.strip().upper()
    for ch in (" ", "-", "/"):
        normalized = normalized.replace(ch, "_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized or None
