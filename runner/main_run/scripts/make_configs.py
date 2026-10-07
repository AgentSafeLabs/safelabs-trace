"""Generates the 1B main-run configs and the main price table (decisions of 2026-10-07). Offline. The item ids come from the runner's own `--select-items` (run on a skeleton config written under
/tmp/safelabs-trace-tests/, then copied into the config). Writes only into 1b_main_run/ (configs/, price_table_main.yaml). Run with the safelabs-eval venv python and
PYTHONPATH=<repo>/safelabs-trace/runner:<repo>/safelabs-trace/src:<repo>/safelabs-eval."""
import contextlib, io, sys
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent.parent
REPO = Path.home() / "Desktop/Workspace/AgentSafeLabs"
TMP = Path("/tmp/safelabs-trace-tests"); TMP.mkdir(exist_ok=True)
from trace_runner.cli import main as runner_main

SEED = 20261004
CHEAP = [("claude-haiku-4-5-20251001", "anthropic", "anthropic/claude-haiku-4-5-20251001", 384), ("gpt-5.4-nano", "openai", "openai/gpt-5.4-nano", 286), ("gemini-3.1-flash-lite", "google", "gemini/gemini-3.1-flash-lite", 201)]
FRONT = [("claude-opus-4-8", "anthropic", "anthropic/claude-opus-4-8", 384), ("gpt-5.5", "openai", "openai/gpt-5.5", 286), ("gemini-3.5-flash", "google", "gemini/gemini-3.5-flash", 201)]
HEAD = "# {title}\n# Written 2026-10-07 for the 1B main run; copy into safelabs-trace/runner/configs/ (see 1b_main_run/RUNBOOK.md). No keys here (keys come from the environment at run time).\n# Decisions D1-D10 of runner/DECISIONS.md: max_model_calls 8 (D8), retry_profile benchmark, evidence sidecar on for every real run (D10: pass an EVIDENCE_DIR to run_pilot.sh), tagger rules v2b frozen.\n"


def select(per_category: int) -> list[str]:
    skel = TMP / f"skel_pc{per_category}.yaml"
    skel.write_text(f"run_name: skel\nitems: {{source: safeagent300, per_category: {per_category}, seed: {SEED}, ids: []}}\nmodels:\n  - {{id: m, provider: anthropic, litellm_route: anthropic/m}}\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = runner_main(["--config", str(skel), "--select-items"])
    assert rc == 0
    ids = buf.getvalue().split()
    assert len(ids) == 10 * per_category and len(set(ids)) == len(ids)
    return ids


def models_block(models, verified_note):
    lines = ["models:", f"  # {verified_note}"]
    for mid, prov, route, est in models:
        tier = "cheap" if (mid, prov, route, est) in CHEAP else "frontier"
        lines.append(f"  - {{id: {mid}, provider: {prov}, litellm_route: {route}, tier: {tier}, verified: false, est_output_tokens: {est}}}")
    return "\n".join(lines)


def config(title, run_name, per_category, ids, frameworks, models, trials, cap, out, note, verified_note):
    idl = "\n".join(f"    - {i}" for i in ids)
    return (HEAD.format(title=title) + note + f"""run_name: {run_name}
items:
  source: safeagent300
  per_category: {per_category}
  seed: {SEED}
  ids:
{idl}
frameworks: [{', '.join(frameworks)}]
{models_block(models, verified_note)}
tools: null            # null = all 12 inert tools
trials: {trials}
max_model_calls: 8   # D8 (pilot setting); cap_hit stays recorded as its own stop status
output_dir: ../../runs/{out}   # outside the repo; relative to the runner/ folder, so run from runner/
retry_profile: benchmark
call_timeout_s: 120
price_table: price_table_main.yaml
budget:
  cap_usd: {cap}
  schema_tokens: 1500   # INFERRED
  prompt_tokens: 70     # INFERRED
  calls_per_trial: 3    # INFERRED (for --estimate only), as in the pilot configs
scorer: safelabs
""")


CH_NOTE = "# Cheap tier: the three pilot models, which ran in the pilot (ids verified there; re-check before the run anyway).\n"
SF_NOTE = ("# FRONTIER SMOKE: for COST AND PLUMBING ONLY (MAIN_RUN_PLAN.md). Its data are not part of the main-run results. 20 items (the same 20 as smoke_openai_agents; 2 per category, seed 20261004, ids from --select-items)\n"
           "# x langchain+adk x 3 frontier models x 1 trial = 120 trials. Cap USD 8. Its real per-trial usage projects main_frontier (scripts/frontier_projection.py).\n")
FR_NOTE = ("# Frontier tier: the SAME frontier models as AgentPort-Bench (claude-opus-4-8, gpt-5.5, gemini-3.5-flash; v2_ship/.../AgentPort-Bench_Merged.tex 'Experimental Matrix').\n"
           "# VERIFY BEFORE RUN: model ids and LiteLLM routes (anthropic/..., openai/..., gemini/... by the pattern of the cheap models) are NOT checked by --estimate or --dry-run.\n"
           "# est_output_tokens are INFERRED stand-ins (the same provider's cheap model); the budget stop uses actual reported usage.\n"
           "# Prices in price_table_main.yaml: list prices as of 2026-10-07 (standard tier); confirm on each provider's page before running.\n")
VN_CHEAP = "ids ran in the pilot; the runner marks them verified: false until a real run uses them (checked against the providers at real-run time only)."
VN_FRONT = "VERIFY BEFORE RUN: ids and routes below come from the AgentPort-Bench paper, not from a provider check; verified: false until you have checked them."
OA_NOTE = "# ADD openai_agents ONLY IF the smoke gate passed (MAIN_RUN_PLAN.md, 'OpenAI Agents smoke gate'). The file without _with_oa is the langchain+adk version.\n"
ids20, ids300 = select(2), select(30)
assert select(2) == ids20  # deterministic: the frontier smoke uses the SAME 20 items as the OpenAI Agents smoke
W = lambda name, text: (HERE / "configs" / name).write_text(text, encoding="utf-8")
W("smoke_openai_agents.yaml", config("1B main run: OpenAI Agents SDK smoke (gate decided in MAIN_RUN_PLAN.md before this run)", "smoke_openai_agents", 2, ids20, ["openai_agents"], CHEAP, 1, 2.0, "smoke_openai_agents",
  "# 20 items (2 per category, seed 20261004, ids filled with the runner's --select-items) x openai_agents x 3 cheap models x 1 trial = 60 trials. Cap USD 2.\n", VN_CHEAP))
W("main_cheap.yaml", config("1B main run, cheap tier: 300 items x langchain+adk x 3 cheap models x 3 trials", "main_cheap", 30, ids300, ["langchain", "adk"], CHEAP, 3, 30.0, "main_cheap", CH_NOTE + OA_NOTE, VN_CHEAP))
W("main_cheap_with_oa.yaml", config("1B main run, cheap tier WITH openai_agents (only if the smoke gate passed): 300 items x 3 frameworks x 3 cheap models x 3 trials", "main_cheap", 30, ids300, ["langchain", "adk", "openai_agents"], CHEAP, 3, 30.0, "main_cheap", CH_NOTE, VN_CHEAP))
W("main_frontier.yaml", config("1B main run, frontier tier: 300 items x langchain+adk x 3 frontier models x 1 trial", "main_frontier", 30, ids300, ["langchain", "adk"], FRONT, 1, 60.0, "main_frontier", FR_NOTE + OA_NOTE, VN_FRONT))
W("main_frontier_with_oa.yaml", config("1B main run, frontier tier WITH openai_agents (only if the smoke gate passed): 300 items x 3 frameworks x 3 frontier models x 1 trial", "main_frontier", 30, ids300, ["langchain", "adk", "openai_agents"], FRONT, 1, 60.0, "main_frontier", FR_NOTE, VN_FRONT))
W("smoke_frontier.yaml", config("1B main run: frontier smoke (cost and plumbing only; not part of the main-run results)", "smoke_frontier", 2, ids20, ["langchain", "adk"], FRONT, 1, 8.0, "smoke_frontier", SF_NOTE + FR_NOTE, VN_FRONT))
pt = (REPO / "safelabs-trace/runner/price_table.yaml").read_text()
cheap_lines = [l for l in pt.splitlines() if l.startswith("  claude-haiku") or l.startswith("  gpt-5.4-nano") or l.startswith("  gemini-3.1-flash-lite")]
assert len(cheap_lines) == 3
(HERE / "price_table_main.yaml").write_text("""# PRICE TABLE for the 1B main run. Cheap prices: copied from safelabs-trace/runner/price_table.yaml (standard tier, not batch; reasoning tokens are charged as output).
# Frontier prices: list prices as of 2026-10-07, standard tier, USD per million tokens; CONFIRM ON EACH PROVIDER'S PAGE BEFORE RUNNING (change them here, and in the plan if they differ, before the run).
currency: USD
unit: per_million_tokens
prices:
""" + "\n".join(cheap_lines) + """
  claude-opus-4-8:   {input_per_mtok: 5.00, output_per_mtok: 25.00}   # list price as of 2026-10-07; confirm on the provider's page before running
  gpt-5.5:           {input_per_mtok: 5.00, output_per_mtok: 30.00}   # list price as of 2026-10-07; confirm on the provider's page before running
  gemini-3.5-flash:  {input_per_mtok: 1.50, output_per_mtok: 9.00}    # list price as of 2026-10-07; confirm on the provider's page before running
""", encoding="utf-8")
print("ok", len(ids20), len(ids300))
