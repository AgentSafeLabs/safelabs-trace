"""Sampling rules of build_main_answers_sheet.py on SYNTHETIC in-memory records (no files, no evidence)."""
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True
import build_main_answers_sheet as B  # noqa: E402


def synth(n_per_cell=3, scarce=None):
    recs = []
    for m in B.ALL_MODELS:
        tier = B.TIER_OF[m]
        fws = ["langchain", "adk", "openai_agents"] if tier == "cheap" else ["langchain", "adk"]
        for fw in fws:
            for c in range(1, 11):
                for j in range(n_per_cell):
                    for verdict in ("uncertain", "pass", "fail"):
                        recs.append({"tier": tier, "model": m, "framework": fw, "category": f"ASI{c:02d}", "prompt_id": f"SYN-{c}-{j}-{verdict}", "trial_seed": 0, "verdict": verdict, "status": "scored", "error_class": None,
                                     "tool_call_only_row": False, "final_text": "SYNTHETIC text", "run": "synthetic"})
    if scarce:
        recs = [r for r in recs if not (r["verdict"] == "fail" and r["model"] not in scarce)]
    return recs


def test_counts_and_spread():
    rows = B.build_sample(synth())
    kinds = collections.Counter(k for k, _ in rows)
    assert kinds == {"uncertain": 120, "pass_control": 10, "fail_control": 10}
    for m in B.ALL_MODELS:
        u = [r for k, r in rows if k == "uncertain" and r["model"] == m]
        assert len(u) == 20
        fw = collections.Counter(r["framework"] for r in u)
        assert sorted(fw.values()) == ([6, 7, 7] if B.TIER_OF[m] == "cheap" else [10, 10])
        assert len({r["category"] for r in u}) >= 7  # spread over the ASI categories
    ctrl_models = collections.Counter(r["model"] for k, r in rows if k == "fail_control")
    assert set(ctrl_models) == set(B.ALL_MODELS) and max(ctrl_models.values()) <= 2
    assert len({(r["model"], r["framework"], r["prompt_id"]) for _, r in rows}) == len(rows)


def test_deterministic_and_seed_sensitive():
    a = [(k, r["prompt_id"], r["model"]) for k, r in B.build_sample(synth())]
    assert a == [(k, r["prompt_id"], r["model"]) for k, r in B.build_sample(synth())]
    assert a != [(k, r["prompt_id"], r["model"]) for k, r in B.build_sample(synth(), seed=1)]


def test_only_eligible_trials():
    recs = synth()
    for r in recs[::7]:
        r["error_class"] = "content_policy"
    for r in recs[::11]:
        r["tool_call_only_row"] = True
    for r in recs[::13]:
        r["final_text"] = "  "
    bad = {id(r) for r in recs if r["error_class"] or r["tool_call_only_row"] or not r["final_text"].strip()}
    rows = B.build_sample(recs)
    assert all(id(r) not in bad for _, r in rows) and len(rows) == 140


def test_shortage_hands_places_over_and_all_fail_if_fewer():
    recs = [r for r in synth(2) if not (r["model"] == "gpt-5.5" and r["verdict"] == "uncertain" and r["framework"] == "adk" and r["category"] != "ASI01")]
    rows = B.build_sample(recs)
    g = [r for k, r in rows if k == "uncertain" and r["model"] == "gpt-5.5"]
    assert len(g) == 20 and collections.Counter(r["framework"] for r in g)["adk"] == 2 and collections.Counter(r["framework"] for r in g)["langchain"] == 18
    few = [r for r in synth(1) if r["verdict"] != "fail"] + [r for r in synth(1) if r["verdict"] == "fail" and r["category"] == "ASI01" and r["framework"] == "langchain"][:4]
    rows = B.build_sample(few)
    assert sum(1 for k, _ in rows if k == "fail_control") == 4  # all of them when fewer than 10 exist


def test_population_counts():
    recs = synth(1)
    recs[0]["error_class"] = "no_output_text"
    pop = B.population(recs)
    m = recs[0]["model"]
    assert pop["models"][m]["provider_no_output_text"] == 1 and pop["models"][m]["N"] == len([r for r in recs if r["model"] == m])
    assert pop["models"][m]["U"] == pop["models"][m]["uncertain_all"] - 1 + (0 if recs[0]["verdict"] == "uncertain" else 1)
