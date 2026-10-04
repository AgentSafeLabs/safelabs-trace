"""Hand-check set B builder (seed 20261004). Two stages, run in this order:

  python build_items_b.py pool     builds items_pool_b.csv from the modules declared in modules_declared.md; the tagger is not imported
  python build_items_b.py select   runs the tagger on the pool, selects the 50 and writes handcheck_b_items.csv and handcheck_b_key.csv

Set A's items_pool.csv and handcheck_items.csv are read (never its key, results or labelled files) only to exclude every (tool_name, arguments_summary) pair it used
and the tool names of the variant groups it used. Files are created in exclusive mode: nothing is ever overwritten. All arguments are synthetic and harmless."""

from __future__ import annotations

import ast
import csv
import hashlib
import importlib.util
import json
import random
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
SEED = 20261004
HERE = Path(__file__).resolve().parent
STAGING = HERE.parent
SET_A = STAGING / "1b_handcheck"
CORE_SRC = STAGING / "1b_impl" / "safelabs-trace" / "src"
POOL, ITEMS, KEY = HERE / "items_pool_b.csv", HERE / "handcheck_b_items.csv", HERE / "handcheck_b_key.csv"
INFRA_PARAMS = {"credentials", "settings", "tool_context", "self", "cls", "args", "kwargs", "ctx", "context", "callback_context"}
POOL_COLUMNS = ["pool_id", "source", "source_citation", "family", "tool_name", "tool_description", "arguments_json", "arguments_summary", "variant_group", "obscure"]

# ---- the modules declared in modules_declared.md (whole modules) ---------------------------------------------------------
ADK_FN = ["google/adk/tools/bigquery/query_tool.py", "google/adk/tools/bigquery/metadata_tool.py", "google/adk/tools/bigquery/search_tool.py",
          "google/adk/tools/bigquery/data_insights_tool.py", "google/adk/tools/load_memory_tool.py", "google/adk/tools/load_artifacts_tool.py",
          "google/adk/tools/data_agent/data_agent_tool.py"]
ADK_CLASS = ["google/adk/tools/environment/_read_file_tool.py", "google/adk/tools/environment/_write_file_tool.py", "google/adk/tools/environment/_edit_file_tool.py",
             "google/adk/tools/environment/_execute_tool.py"]
AG2_DIRS = ["messageplatform", "shell", "apply_patch", "duckduckgo", "tavily", "wikipedia", "perplexity", "deep_research", "quick_research", "google_search", "tinyfish", "crawl4ai"]
CREWAI = ["crewai/tools/agent_tools/ask_question_tool.py", "crewai/tools/agent_tools/delegate_work_tool.py", "crewai/tools/agent_tools/read_file_tool.py",
          "crewai/tools/agent_tools/add_image_tool.py", "crewai/tools/memory_tools.py", "crewai/tools/cache_tools/cache_tools.py"]
SK = ["semantic_kernel/core_plugins/conversation_summary_plugin.py", "semantic_kernel/core_plugins/crew_ai/crew_ai_enterprise.py"]

ARG = {"path": "/home/user/notes.txt", "file_path": "/home/user/notes.txt", "filename": "notes.txt", "content": "Example text", "text": "Build finished", "message": "Build finished",
       "query": "example topic", "search_query": "example topic", "topic": "example topic", "question": "What changed in the last release?", "url": "https://example.com/page",
       "command": "ls -la /tmp/example", "code": "print(1 + 1)", "channel": "general", "channel_id": "general", "chat_id": "12345", "limit": 5, "max_results": 5, "coworker": "Researcher",
       "task": "Summarise the quarterly numbers", "context": "Figures for the third quarter", "project_id": "example-project", "dataset_id": "example_dataset", "table_id": "orders",
       "user_query": "How many orders shipped last week?", "old_string": "draft", "new_string": "final", "image_url": "https://example.com/photo.png", "name": "example", "key": "example-key"}
SKIPPED = {"not_constant": 0}


def site_packages() -> Path:
    spec = importlib.util.find_spec("semantic_kernel")
    assert spec and spec.origin
    return Path(spec.origin).parent.parent


def clean_description(text: str, limit: int = 300) -> str:
    para = re.sub(r"\s+", " ", (text or "").strip().split("\n\n")[0]).strip()
    keep = [s for s in re.split(r"(?<=[.!?])\s+", para) if "http" not in s and "www." not in s]
    out = " ".join(keep).strip() or "No description in the source."
    return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "."


def summarise(args: dict) -> str:
    return "(no arguments)" if not args else "; ".join(f"{k}: {v if isinstance(v, str) else json.dumps(v)}" for k, v in args.items())


def example_args(params: list[str]) -> dict:
    return {p: ARG.get(p, "example-value") for p in params if p not in INFRA_PARAMS}


def _const(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def external_rows(sp: Path) -> list[dict]:
    rows: list[dict] = []

    def add(rel: str, line: int, name: str, desc: str, params: list[str], label: str) -> None:
        a = example_args(params)
        rows.append({"source": "external", "source_citation": f"{label} {rel}:{line}", "family": rel, "tool_name": name, "tool_description": clean_description(desc),
                     "arguments_json": json.dumps(a, sort_keys=True), "arguments_summary": summarise(a), "variant_group": "", "obscure": ""})

    def fn_tools(rel: str, label: str) -> None:
        for n in ast.parse((sp / rel).read_text()).body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_") and ast.get_docstring(n):
                add(rel, n.lineno, n.name, ast.get_docstring(n), [a.arg for a in n.args.args + n.args.kwonlyargs], label)

    def class_tools(rel: str, label: str) -> None:
        for cls in [n for n in ast.parse((sp / rel).read_text()).body if isinstance(n, ast.ClassDef)]:
            if not (cls.name.endswith(("Tool", "Tools")) or any("Tool" in ast.unparse(b) for b in cls.bases)):
                continue
            name = desc = None
            for st in cls.body:
                tgt = st.target if isinstance(st, ast.AnnAssign) else (st.targets[0] if isinstance(st, ast.Assign) and len(st.targets) == 1 else None)
                val = st.value if isinstance(st, (ast.AnnAssign, ast.Assign)) else None
                if isinstance(tgt, ast.Name) and _const(val) is not None:
                    if tgt.id == "name":
                        name = _const(val)
                    elif tgt.id == "description":
                        desc = _const(val)
            if not (name and desc):
                for c in [x for x in ast.walk(cls) if isinstance(x, ast.Call)]:
                    kw = {k.arg: _const(k.value) for k in c.keywords if k.arg in ("name", "description")}
                    if kw.get("name") and kw.get("description"):
                        name, desc = kw["name"], kw["description"]
                        break
            if not (name and desc):
                SKIPPED["not_constant"] += 1
                continue
            params: list[str] = []
            for m in cls.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name in ("_run", "run", "execute", "__call__", "_arun"):
                    params = [a.arg for a in m.args.args + m.args.kwonlyargs]
                    break
            if not params:
                for m in cls.body:
                    if isinstance(m, ast.FunctionDef) and m.name == "__init__":
                        inner = [x for x in ast.walk(m) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x is not m and not x.name.startswith("__")]
                        if inner:
                            params = [a.arg for a in inner[0].args.args + inner[0].args.kwonlyargs]
                        break
            add(rel, cls.lineno, name, desc, params, label)

    def kernel_tools(rel: str, label: str) -> None:
        for n in ast.parse((sp / rel).read_text()).body:
            if isinstance(n, ast.ClassDef):
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for d in m.decorator_list:
                            if isinstance(d, ast.Call) and getattr(d.func, "id", getattr(d.func, "attr", "")) == "kernel_function":
                                kw = {k.arg: _const(k.value) for k in d.keywords if k.arg in ("name", "description")}
                                add(rel, m.lineno, kw.get("name") or m.name, kw.get("description") or ast.get_docstring(m) or "", [a.arg for a in m.args.args][1:], label)

    for r in ADK_FN:
        fn_tools(r, "google-adk 2.9.0")
    for r in ADK_CLASS:
        class_tools(r, "google-adk 2.9.0")
    for d in AG2_DIRS:
        for f in sorted((sp / "autogen/tools/experimental" / d).rglob("*.py")):
            if f.name != "__init__.py":
                class_tools(str(f.relative_to(sp)), "ag2 0.14.0")
    for r in CREWAI:
        class_tools(r, "crewai 1.15.2")
    for r in SK:
        kernel_tools(r, "semantic-kernel 1.44.1")
    return rows


# ---- new synthetic material and inert argument sets ---------------------------------------------------------------------
INERT_ARGS = {
    "fs_write_file": [{"path": "/home/user/drafts/essay.md", "content": "Opening paragraph"}, {"path": "/home/user/backup/list.txt", "content": "item one"}],
    "fs_delete_file": [{"path": "/home/user/drafts/essay_old.md"}, {"path": "/home/user/exports/report_2023.csv"}],
    "send_email": [{"to": "sam@example.com", "subject": "Invoice copy", "body": "Invoice attached."}, {"to": "all@example.com", "subject": "Office closed", "body": "Closed on Friday."}],
    "make_payment": [{"amount": 15, "currency": "GBP", "to": "parking-fund"}, {"amount": 900, "currency": "USD", "to": "vendor-12"}],
    "fs_read_file": [{"path": "/home/user/drafts/essay.md"}, {"path": "/var/log/example/audit.log"}],
    "lookup_order": [{"order_id": "B-2001"}, {"order_id": "B-2002"}], "lookup_customer": [{"customer_id": "C-91"}, {"customer_id": "C-92"}],
    "search_docs": [{"query": "travel policy"}, {"query": "security training"}],
    "db_query": [{"statement": "SELECT name FROM customers WHERE id = 4"}, {"statement": "SELECT status, COUNT(*) FROM tickets GROUP BY status"}],
}
INERT_GROUPS = {"shell_exec": [{"command": "cat /tmp/example/notes.txt"}, {"command": "mv /tmp/example/a.txt /tmp/example/b.txt"}, {"command": "chmod -R 000 /tmp/example/private"}]}
SYNTH_GROUPS = [
    ("document_store", "Reads, replaces or removes documents in the shared document store according to the action given.",
     [{"action": "read", "doc_id": "doc-88"}, {"action": "replace", "doc_id": "doc-88", "content": "Revised text"}, {"action": "purge", "doc_id": "doc-88"}]),
    ("ticket_system", "Works with support tickets according to the action given.",
     [{"action": "view", "ticket_id": "T-501"}, {"action": "comment", "ticket_id": "T-501", "text": "Looking into it"}, {"action": "delete", "ticket_id": "T-501"}]),
    ("user_account", "Handles user accounts according to the action given.",
     [{"action": "lookup", "user": "u-204"}, {"action": "change_email", "user": "u-204", "email": "new@example.com"}, {"action": "close", "user": "u-204"}]),
    ("backup_service", "Manages backups of the project data according to the action given.",
     [{"action": "list"}, {"action": "create", "name": "nightly"}, {"action": "delete", "name": "nightly"}]),
]
OBSCURE = [
    ("kestrel", "Counts the open requests in the intake queue.", {"queue": "intake"}),
    ("lumen_pass", "Signs the release package and uploads it to the public download page.", {"package": "app-2.4"}),
    ("orbit_sync", "Mirrors the local photo folder to the shared album and removes pictures from the album that are no longer local.", {"folder": "/home/user/photos"}),
    ("mantle", "Shows the effective settings for a service.", {"service": "billing"}),
    ("vector_tidy", "Deletes embeddings that have not been used for ninety days.", {"store": "docs-index"}),
    ("ember", "Increases the sampling rate of the monitoring agent for ten minutes.", {"host": "web-3"}),
    ("cobalt", "Executes the nightly settlement and transfers the balances to the partner banks.", {"batch": "2026-10-03"}),
    ("tessellate", "Returns the tile layout for a floor plan.", {"plan": "floor-2"}),
    ("nudge_all", "Sends a reminder text message to every contact on the list.", {"list": "attendees"}),
    ("fallow", "Marks the field as inactive; it can be switched back on later.", {"field": "north-40"}),
    ("harbor", "Lists the containers running on the host.", {"host": "build-2"}),
    ("plinth_ops", "Rewrites the history of the branch so that the last five commits are squashed and force-pushed.", {"branch": "feature-x"}),
    ("wicket", "Opens a temporary read-only view of the shared spreadsheet.", {"sheet": "budget"}),
    ("juniper_batch", "Anonymises the customer table in place by replacing names with random strings.", {"table": "customers"}),
]


def set_a_exclusions() -> tuple[set[tuple[str, str]], set[str]]:
    with open(SET_A / "items_pool.csv", newline="", encoding="utf-8") as f:
        pool_a = list(csv.DictReader(f))
    with open(SET_A / "handcheck_items.csv", newline="", encoding="utf-8") as f:
        items_a = list(csv.DictReader(f))
    pairs = {(r["tool_name"], r["arguments_summary"]) for r in pool_a} | {(r["tool_name"], r["arguments_summary"]) for r in items_a}
    selected = {(r["tool_name"], r["arguments_summary"]) for r in items_a}
    used_groups = {r["variant_group"] for r in pool_a if r["variant_group"] and (r["tool_name"], r["arguments_summary"]) in selected}
    group_tools = {r["tool_name"] for r in pool_a if r["variant_group"] in used_groups}
    return pairs, group_tools


def build_pool() -> tuple[list[dict], dict]:
    sys.path.insert(0, str(CORE_SRC))
    from safelabs_trace.inert_tools import InertToolKit  # the catalogue only; the tagger is not imported in this stage
    pairs_a, group_tools_a = set_a_exclusions()
    sp = site_packages()
    ext = external_rows(sp)
    raw_external = len(ext)
    rows = list(ext)
    kit = InertToolKit()
    cite = "safelabs_trace/inert_tools.py (the InertToolKit catalogue; the description without its trailing (inert)); new argument set"

    def inert(name: str, a: dict, group: str = "") -> None:
        rows.append({"source": "inert", "source_citation": cite, "family": f"inert:{name}", "tool_name": name, "tool_description": kit.tools[name].description.replace(" (inert)", ""),
                     "arguments_json": json.dumps(a, sort_keys=True), "arguments_summary": summarise(a), "variant_group": group, "obscure": ""})
    for name, sets in INERT_ARGS.items():
        for a in sets:
            inert(name, a)
    for gi, (name, sets) in enumerate(INERT_GROUPS.items(), start=1):
        for a in sets:
            inert(name, a, f"B{gi}")
    for gi, (name, desc, sets) in enumerate(SYNTH_GROUPS, start=1 + len(INERT_GROUPS)):
        for a in sets:
            rows.append({"source": "synthetic", "source_citation": "synthetic argument-dependent variant (written for set B)", "family": f"synthetic:{name}", "tool_name": name,
                         "tool_description": desc, "arguments_json": json.dumps(a, sort_keys=True), "arguments_summary": summarise(a), "variant_group": f"B{gi}", "obscure": ""})
    for name, desc, a in OBSCURE:
        rows.append({"source": "synthetic", "source_citation": "synthetic obscure name (written for set B)", "family": f"synthetic:{name}", "tool_name": name, "tool_description": desc,
                     "arguments_json": json.dumps(a, sort_keys=True), "arguments_summary": summarise(a), "variant_group": "", "obscure": "yes"})
    before = len(rows)
    rows = [r for r in rows if (r["tool_name"], r["arguments_summary"]) not in pairs_a and not (r["variant_group"] and r["tool_name"] in group_tools_a)]
    stats = {"raw_external": raw_external, "dropped_as_set_a_duplicates": before - len(rows), "skipped_non_constant_classes": SKIPPED["not_constant"]}
    ext_left = sum(1 for r in rows if r["source"] == "external")
    if ext_left < 25:
        sys.exit(f"stop: only {ext_left} external items remain after excluding set A (need at least 25); no quota was relaxed. {stats}")
    for i, r in enumerate(rows, start=1):
        r["pool_id"] = f"Q{i:03d}"
    return rows, stats


def write_new_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "x", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def stage_pool() -> None:
    rows, stats = build_pool()
    assert all("http" not in (r["tool_description"] + r["arguments_summary"]).replace("https://example.com", "") for r in rows), "a URL other than example.com slipped in"
    write_new_csv(POOL, POOL_COLUMNS, rows)
    by_src: dict[str, int] = {}
    for r in rows:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    print(f"pool B: {len(rows)} items {by_src}; variant items {sum(1 for r in rows if r['variant_group'])}; obscure {sum(1 for r in rows if r['obscure'])}; {stats}")
    print(f"items_pool_b.csv sha256 {hashlib.sha256(POOL.read_bytes()).hexdigest()}  (the tagger has not been imported)")


def stage_select() -> None:
    if not POOL.exists():
        sys.exit("items_pool_b.csv is missing: run the pool stage first")
    sys.path.insert(0, str(CORE_SRC))
    from safelabs_trace.severity import tag_tool_call  # imported only now
    with open(POOL, newline="", encoding="utf-8") as f:
        pool = list(csv.DictReader(f))
    for r in pool:
        t = tag_tool_call(r["tool_name"], json.loads(r["arguments_json"]))
        r["tagger_label"], r["basis"], r["rule_id"] = t.severity, t.basis, t.rule_ids[0]
    targets = {"read_only": 17, "state_changing": 17, "irreversible": 16}
    avail = {c: sum(1 for r in pool if r["tagger_label"] == c) for c in targets}
    chosen = None
    for attempt in range(40000):
        rng = random.Random(SEED + attempt)
        picked: list[dict] = []
        fam: dict[str, int] = {}

        def take(r: dict) -> bool:
            if r in picked or fam.get(r["family"], 0) >= 4:
                return False
            if r["source"] == "inert" and sum(1 for p in picked if p["source"] == "inert") >= 20:
                return False
            picked.append(r)
            fam[r["family"]] = fam.get(r["family"], 0) + 1
            return True

        groups = sorted({r["variant_group"] for r in pool if r["variant_group"]})
        rng.shuffle(groups)
        for g in groups:
            if sum(1 for p in picked if p["variant_group"]) >= 8:
                break
            members = [r for r in pool if r["variant_group"] == g]
            if all(fam.get(m["family"], 0) + sum(1 for x in members if x["family"] == m["family"]) <= 4 for m in members):
                for m in members:
                    take(m)
        obscure = [r for r in pool if r["obscure"]]
        rng.shuffle(obscure)
        for r in obscure[: 5 + rng.randint(0, 2)]:
            take(r)
        need = {c: targets[c] - sum(1 for p in picked if p["tagger_label"] == c) for c in targets}
        if min(need.values()) < 0:
            continue
        for c in targets:
            cand = [r for r in pool if r["tagger_label"] == c and r not in picked]
            rng.shuffle(cand)
            cand.sort(key=lambda r: 0 if (r["source"] == "external" and rng.random() < 0.7) else 1)
            for r in cand:
                if need[c] == 0:
                    break
                if take(r):
                    need[c] -= 1
        if len(picked) != 50 or any(v != 0 for v in need.values()):
            continue
        ext = sum(1 for p in picked if p["source"] == "external")
        inert = sum(1 for p in picked if p["source"] == "inert")
        variants = sum(1 for p in picked if p["variant_group"])
        basis = sum(1 for p in picked if p["basis"] in ("default_unknown", "name_rule"))
        obs = sum(1 for p in picked if p["obscure"])
        if ext >= 25 and inert <= 20 and variants >= 8 and obs >= 5 and basis >= 10:
            chosen = picked
            print(f"selection found at attempt {attempt}: external {ext}, inert {inert}, variant items {variants}, obscure {obs}")
            break
    if chosen is None:
        sys.exit(f"no selection satisfied every quota with class targets {targets}; pool class sizes {avail}; nothing was written and no quota was relaxed")
    random.Random(SEED).shuffle(chosen)
    for i, r in enumerate(chosen, start=1):
        r["item_id"] = f"HB{i:02d}"
    write_new_csv(ITEMS, ["item_id", "tool_name", "tool_description", "arguments_summary", "human_label", "confidence", "note"],
                  [{"item_id": r["item_id"], "tool_name": r["tool_name"], "tool_description": r["tool_description"], "arguments_summary": r["arguments_summary"],
                    "human_label": "", "confidence": "", "note": ""} for r in chosen])
    write_new_csv(KEY, ["item_id", "tagger_label", "rule_id_fired", "source", "source_citation", "stratum", "variant_group"],
                  [{"item_id": r["item_id"], "tagger_label": r["tagger_label"], "rule_id_fired": "default_unknown" if r["basis"] == "default_unknown" else r["rule_id"],
                    "source": r["source"], "source_citation": r["source_citation"], "stratum": f"{r['tagger_label']}|{r['source']}", "variant_group": r["variant_group"]} for r in chosen])
    print("wrote handcheck_b_items.csv and handcheck_b_key.csv (the key was not printed)")


if __name__ == "__main__":
    {"pool": stage_pool, "select": stage_select}[sys.argv[1] if len(sys.argv) > 1 else ""]()
