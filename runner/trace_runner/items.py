"""Benchmark items: SafeAgent-300 (the safelabs-eval prompt library) with a seeded stratified selection, or inline items for tests."""

from __future__ import annotations

import random
from types import SimpleNamespace
from typing import Any

from trace_runner.config import ConfigError, ItemsCfg


def select_ids(by_category: dict[str, list[str]], per_category: int, seed: int, categories: list[str] | None = None) -> list[str]:
    """Stratified selection: categories in sorted order, one random.Random(seed) stream, ``per_category`` ids from each sorted id list, kept sorted.
    The same call always returns the same ids (the algorithm is part of the record: it is what the config's ``items.ids`` is checked against)."""
    rng = random.Random(seed)
    out: list[str] = []
    for cat in sorted(categories or by_category):
        ids = sorted(by_category[cat])
        if len(ids) < per_category:
            raise ConfigError(f"category {cat} has {len(ids)} items, fewer than per_category={per_category}")
        out.extend(sorted(rng.sample(ids, per_category)))
    return out


def load_items(cfg: ItemsCfg) -> list[Any]:
    """PromptEntry-like objects (``id, category, severity, prompt``) in the order of ``cfg.ids``."""
    if cfg.source == "inline":
        from safelabs.prompts.schemas import PromptCategory

        return [SimpleNamespace(id=i["id"], category=PromptCategory(i["category"]), severity=i.get("severity", "medium"), prompt=i["prompt"]) for i in cfg.inline]
    from safelabs.prompts import get_library

    lib = get_library()
    by_id = {e.id: e for e in lib.entries}
    cats: dict[str, list[str]] = {}
    for e in lib.entries:
        cats.setdefault(e.category.value, []).append(e.id)
    expected = select_ids(cats, cfg.per_category, cfg.seed, cfg.categories)
    if not cfg.ids:
        raise ConfigError("items.ids is empty: record the selected ids in the config (python -m trace_runner select-items prints them)")
    if list(cfg.ids) != expected:
        raise ConfigError("items.ids does not match the seeded selection for this library version "
                          f"(per_category={cfg.per_category}, seed={cfg.seed}); regenerate it with select-items")
    return [by_id[i] for i in cfg.ids]
