"""Test helpers: synthetic items (non-harmful), a runner factory, no network."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from trace_runner.config import ItemsCfg, ModelCfg, RunCfg
from trace_runner.fakes import FakeProvider, fake_marker_scorer
from trace_runner.orchestrator import Paths, Runner
from trace_runner.pricing import Price, PriceTable

SALT = b"runner-test-salt-0001"
FRAMEWORKS = ["langchain", "adk", "openai_agents"]


def model(mid: str = "m1", provider: str = "anthropic") -> ModelCfg:
    return ModelCfg(id=mid, provider=provider, litellm_route=f"{provider}/{mid}", est_output_tokens=300)


def inline_items(n: int, canary: str = "") -> list[dict[str, Any]]:
    return [{"id": f"ASI01-9{i:02d}", "category": "ASI01", "severity": "medium", "prompt": f"Synthetic benchmark prompt number {i}. {canary}".strip()} for i in range(n)]


def make_cfg(tmp: Path, *, n_items: int = 5, frameworks: list[str] | None = None, models: list[ModelCfg] | None = None, plan: dict | None = None,
             canary: str = "", **kw: Any) -> RunCfg:
    return RunCfg(items=ItemsCfg(source="inline", inline=inline_items(n_items, canary)), frameworks=frameworks or list(FRAMEWORKS), models=models or [model()],
                  fake_plan=plan or {}, output_dir=str(tmp / "out"), scorer="fake_marker", retry_profile="default", call_timeout_s=60, **kw)


def fake_table(cfg: RunCfg, inp: float = 1.0, out: float = 2.0) -> PriceTable:
    return PriceTable({m.id: Price(inp, out) for m in cfg.models}, fake=True)


async def _nosleep(_s: float) -> None:
    return None


def make_runner(tmp: Path, cfg: RunCfg, table: PriceTable | None = None, provider: FakeProvider | None = None) -> Runner:
    from trace_runner.items import load_items
    from trace_runner.safety import enforce_startup_safety

    enforce_startup_safety(cfg, {"ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"})  # as the CLI does before any run (needed: the strict OpenAI handler refuses otherwise)
    r = Runner(cfg, "cfgsha", load_items(cfg.items), provider or FakeProvider(cfg.fake_plan), fake_marker_scorer(), table or fake_table(cfg), Paths(Path(cfg.output_dir)),
               SALT, sleep=_nosleep, jitter_fn=lambda: 0.0, mode="test", salt_id="testsalt")
    return r


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def read_jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
