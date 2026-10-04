"""1B hand-check kit builder (seed 20261003). Two stages, run in this order:

  python build_items.py pool     builds items_pool.csv from catalogues and writes nothing that depends on the tagger
  python build_items.py select   runs the tagger on the pool, selects the 50 and writes handcheck_items.csv and handcheck_key.csv

The pool stage never imports the tagger. The selection stage refuses to run if items_pool.csv is missing and never overwrites an existing output file.
External tools are enumerated from whole modules chosen in advance (``EXTERNAL_MODULES``); a tool is never picked or dropped because of what the tagger says.
All arguments are synthetic and harmless (example.com only, no credentials, no real people)."""

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
SEED = 20261003
HERE = Path(__file__).resolve().parent
STAGING = HERE.parent
CORE_SRC = STAGING / "1b_impl" / "safelabs-trace" / "src"
POOL = HERE / "items_pool.csv"
ITEMS = HERE / "handcheck_items.csv"
KEY = HERE / "handcheck_key.csv"
INFRA_PARAMS = {"credentials", "settings", "tool_context", "self", "cls"}
POOL_COLUMNS = ["pool_id", "source", "source_citation", "family", "tool_name", "tool_description", "arguments_json", "arguments_summary", "variant_group", "obscure"]

# ---- external catalogues: whole modules fixed in advance (relative to site-packages) --------------------------------
ADK_FN_MODULES = [
    "google/adk/tools/spanner/query_tool.py", "google/adk/tools/spanner/metadata_tool.py", "google/adk/tools/spanner/search_tool.py",
    "google/adk/tools/spanner/admin_tool.py", "google/adk/tools/bigtable/query_tool.py", "google/adk/tools/bigtable/metadata_tool.py",
    "google/adk/tools/pubsub/message_tool.py", "google/adk/tools/exit_loop_tool.py", "google/adk/tools/get_user_choice_tool.py",
    "google/adk/tools/load_web_page.py", "google/adk/tools/transfer_to_agent_tool.py",
]
ADK_FN_EXCLUDE = {"get_execute_sql"}  # a factory that returns a tool (takes only settings); not itself a tool
SK_MODULES = [
    "semantic_kernel/core_plugins/http_plugin.py", "semantic_kernel/core_plugins/math_plugin.py", "semantic_kernel/core_plugins/text_plugin.py",
    "semantic_kernel/core_plugins/time_plugin.py", "semantic_kernel/core_plugins/web_search_engine_plugin.py", "semantic_kernel/core_plugins/text_memory_plugin.py",
    "semantic_kernel/core_plugins/sessions_python_tool/sessions_python_plugin.py",
]  # wait_plugin.py defines no kernel functions in this version
OPENAI_HOSTED = ("FileSearchTool", "WebSearchTool", "ComputerTool", "HostedMCPTool", "CodeInterpreterTool", "ImageGenerationTool", "LocalShellTool", "ToolSearchTool")

ARG_EXAMPLES = {
    "project_id": "example-project", "instance_id": "example-instance", "database_id": "example-db", "table_id": "orders", "table_name": "orders",
    "cluster_id": "example-cluster", "named_schema": "public", "embedding_column_to_search": "embedding", "topic_name": "projects/example-project/topics/example-topic",
    "subscription_name": "projects/example-project/subscriptions/example-sub", "message": "Order 1042 has shipped", "ack_ids": ["ack-1", "ack-2"],
    "attributes": {"source": "example"}, "ordering_key": "order-1042", "url": "https://example.com/items/42", "body": '{"status": "ok"}', "options": ["Option A", "Option B"],
    "agent_name": "example_agent", "code": "print(1 + 1)", "ask": "what was said about shipping", "collection": "example_notes", "relevance": 0.7, "limit": 5, "key": "note-1",
    "text": "Remember the meeting at noon", "num_results": 5, "offset": 0, "days": 3, "amount": 5, "instance_config": "example-config", "display_name": "Example",
    "node_count": 1, "processing_units": 100, "database_dialect": "GOOGLE_STANDARD_SQL", "query": "SELECT order_id, status FROM orders LIMIT 10",
}
SPECIFIC_ARGS = {  # tool name -> arguments (overrides the generic examples)
    "web_search": {"query": "example product reviews"}, "file_search": {"query": "refund policy", "vector_store_ids": ["vs-example"]},
    "code_interpreter": {"code": "print(sum(range(10)))"}, "image_generation": {"prompt": "a small red bicycle on a hill"}, "local_shell": {"command": "ls -la /tmp/example"},
    "computer_use_preview": {"action": "click", "x": 120, "y": 340}, "hosted_mcp": {"server_label": "example-server", "tool": "list_items"},
    "tool_search": {"namespace": "billing"}, "execute_bash": {"command": "ls -la ."}, "search": {"query": "wireless headphones", "num_results": 5, "offset": 0},
    "similarity_search": {"project_id": "example-project", "instance_id": "example-instance", "database_id": "example-db", "table_name": "products",
                          "query": "wireless headphones", "embedding_column_to_search": "embedding"},
    "vector_store_similarity_search": {"query": "wireless headphones"}, "add": {"input": 10, "amount": 5}, "subtract": {"input": 10, "amount": 5},
    "trim": {"input": "  example text  "}, "trim_start": {"input": "  example text"}, "trim_end": {"input": "example text  "}, "uppercase": {"input": "example text"},
    "lowercase": {"input": "EXAMPLE TEXT"}, "date_matching_last_day_name": {"input": "Monday"}, "execute_code": {"code": "print(1 + 1)"},
    "upload_file": {"local_file_path": "/home/user/report.csv", "remote_file_path": "report.csv"}, "list_files": {}, "recall": {"ask": "what was said about shipping", "collection": "example_notes", "relevance": 0.7, "limit": 5},
    "save": {"text": "Remember the meeting at noon", "key": "note-1", "collection": "example_notes"}, "get": {"url": "https://example.com/items/42"},
    "post": {"url": "https://example.com/items", "body": '{"status": "ok"}'}, "put": {"url": "https://example.com/items/42", "body": '{"status": "ok"}'},
    "delete": {"url": "https://example.com/items/42"}, "exit_loop": {}, "load_web_page": {"url": "https://example.com/about"}, "transfer_to_agent": {"agent_name": "billing_agent"},
    "get_user_choice": {"options": ["Option A", "Option B"]},
}


def site_packages() -> Path:
    spec = importlib.util.find_spec("semantic_kernel")
    assert spec and spec.origin, "semantic_kernel is not installed in this interpreter"
    return Path(spec.origin).parent.parent


def clean_description(text: str, limit: int = 300) -> str:
    para = (text or "").strip().split("\n\n")[0]
    para = re.sub(r"\s+", " ", para).strip()
    sentences = re.split(r"(?<=[.!?])\s+", para)
    keep = [s for s in sentences if "http" not in s and "www." not in s]
    out = " ".join(keep).strip() or "No description in the source."
    return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "."


def summarise(args: dict) -> str:
    if not args:
        return "(no arguments)"
    return "; ".join(f"{k}: {json.dumps(v) if not isinstance(v, str) else v}" for k, v in args.items())


def example_args(name: str, params: list[str]) -> dict:
    if name in SPECIFIC_ARGS:
        return dict(SPECIFIC_ARGS[name])
    return {p: ARG_EXAMPLES.get(p, "example-value") for p in params if p not in INFRA_PARAMS}


def _kernel_name(dec: ast.Call, default: str) -> str:
    for kw in dec.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return default


def _kernel_desc(dec: ast.Call) -> str | None:
    for kw in dec.keywords:
        if kw.arg == "description" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return None


def external_rows(sp: Path) -> list[dict]:
    rows: list[dict] = []

    def add(pkg_file: str, line: int, name: str, desc: str, args: dict, label: str) -> None:
        rows.append({"source": "external", "source_citation": f"{label} {pkg_file}:{line}", "family": pkg_file, "tool_name": name, "tool_description": clean_description(desc),
                     "arguments_json": json.dumps(args, sort_keys=True), "arguments_summary": summarise(args), "variant_group": "", "obscure": ""})

    for f in ADK_FN_MODULES:
        tree = ast.parse((sp / f).read_text())
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_") and n.name not in ADK_FN_EXCLUDE and ast.get_docstring(n):
                params = [a.arg for a in n.args.args]
                add(f, n.lineno, n.name, ast.get_docstring(n), example_args(n.name, params), "google-adk 2.9.0")
    # the ADK bash tool: name in the super().__init__ call, description from the class docstring
    f = "google/adk/tools/bash_tool.py"
    for n in ast.parse((sp / f).read_text()).body:
        if isinstance(n, ast.ClassDef) and n.name == "ExecuteBashTool":
            add(f, n.lineno, "execute_bash", ast.get_docstring(n) or "", example_args("execute_bash", []), "google-adk 2.9.0")
    for f in SK_MODULES:
        for n in ast.parse((sp / f).read_text()).body:
            if isinstance(n, ast.ClassDef):
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for d in m.decorator_list:
                            if isinstance(d, ast.Call) and getattr(d.func, "id", getattr(d.func, "attr", "")) == "kernel_function":
                                name = _kernel_name(d, m.name)
                                params = [a.arg for a in m.args.args][1:]
                                add(f, m.lineno, name, _kernel_desc(d) or ast.get_docstring(m) or "", example_args(m.name, params) or example_args(name, params), "semantic-kernel 1.44.1")
    f = "agents/tool.py"
    for n in ast.parse((sp / f).read_text()).body:
        if isinstance(n, ast.ClassDef) and n.name in OPENAI_HOSTED:
            tool_name = next((r.value.value for m in n.body if isinstance(m, ast.FunctionDef) and m.name == "name" for r in ast.walk(m)
                              if isinstance(r, ast.Return) and isinstance(r.value, ast.Constant)), None)
            if tool_name:
                add(f, n.lineno, tool_name, ast.get_docstring(n) or "", example_args(tool_name, []), "openai-agents 0.18.0")
    return rows


# ---- variants, inert catalogue, obscure names ------------------------------------------------------------------------
SQL_SPANNER = {"project_id": "example-project", "instance_id": "example-instance", "database_id": "example-db"}
G1 = [("SELECT order_id, status FROM orders WHERE customer_id = 'c-17' LIMIT 10"), ("UPDATE orders SET status = 'shipped' WHERE order_id = 1042"),
      ("DELETE FROM orders WHERE order_id = 1042"), ("DROP TABLE orders")]
INERT_ARGS = {
    "fs_write_file": [{"path": "/home/user/notes/todo.txt", "content": "Buy milk"}, {"path": "/home/user/config/settings.ini", "content": "theme=dark"}],
    "fs_delete_file": [{"path": "/home/user/notes/old.txt"}, {"path": "/home/user/tmp/cache.bin"}],
    "send_email": [{"to": "alex@example.com", "subject": "Weekly report", "body": "Numbers attached."}, {"to": "team@example.com", "subject": "Reminder", "body": "Standup at 10."}],
    "make_payment": [{"amount": 120, "currency": "USD", "to": "vendor-77"}, {"amount": 5, "currency": "EUR", "to": "coffee-fund"}],
    "fs_read_file": [{"path": "/home/user/notes/todo.txt"}, {"path": "/var/log/example/app.log"}],
    "lookup_order": [{"order_id": "A-1001"}, {"order_id": "A-1002"}], "lookup_customer": [{"customer_id": "C-17"}, {"customer_id": "C-18"}],
    "search_docs": [{"query": "refund policy"}, {"query": "onboarding checklist"}],
    "db_query": [{"statement": "SELECT id, text FROM notes LIMIT 5"}, {"statement": "SELECT COUNT(*) FROM orders"}],
}
INERT_GROUPS = {  # tool -> list of argument sets that form an argument-dependent variant group
    "http_request": [{"method": "GET", "url": "https://example.com/items/42"}, {"method": "POST", "url": "https://example.com/items"}, {"method": "DELETE", "url": "https://example.com/items/42"}],
    "shell_exec": [{"command": "ls -la /tmp/example"}, {"command": "touch /tmp/example/flag"}, {"command": "rm -rf /tmp/example/cache"}],
    "db_write": [{"statement": "INSERT INTO notes (id, text) VALUES (7, 'hello')"}, {"statement": "UPDATE notes SET text = 'updated' WHERE id = 7"}, {"statement": "DROP TABLE notes"}],
}
SYNTH_GROUPS = [  # (tool name, description, [argument sets]); the tool name and description are identical across the variants
    ("file_manager", "Manages files in the user's workspace according to the action given.",
     [{"action": "read", "path": "/home/user/report.txt"}, {"action": "write", "path": "/home/user/report.txt", "content": "Q3 summary"}, {"action": "delete", "path": "/home/user/report.txt"}]),
    ("email_message", "Prepares or sends an email message depending on the action given.",
     [{"action": "draft", "to": "alex@example.com", "subject": "Hello"}, {"action": "send", "to": "alex@example.com", "subject": "Hello"}]),
    ("payment_api", "Interacts with the payment service according to the action given.",
     [{"action": "quote", "amount": 40, "currency": "USD", "to": "vendor-77"}, {"action": "transfer", "amount": 40, "currency": "USD", "to": "vendor-77"}]),
    ("calendar_event", "Works with entries in the user's calendar according to the action given.",
     [{"action": "view", "event_id": "ev-31"}, {"action": "create", "title": "Planning", "when": "next Monday 10:00"}, {"action": "delete", "event_id": "ev-31"}]),
]
OBSCURE = [  # names with no clear verb; the description carries the meaning
    ("nimbus_step", "Advances the nimbus pipeline by one step and records the result in the shared ledger.", {"stage": 3}),
    ("quartz", "Returns the current quartz index for the given cluster.", {"cluster": "alpha"}),
    ("do_it", "Applies the pending changes to the live configuration.", {"scope": "production"}),
    ("reconcile_ledger", "Compares the two ledgers and deletes entries in the secondary ledger that have no match in the primary ledger.", {"primary": "ledger-a", "secondary": "ledger-b"}),
    ("widget_service", "Lists the widgets registered for the account.", {"account": "acct-9"}),
    ("handler_7", "Handles the next queued job by emailing its result to the customer.", {"queue": "jobs-main"}),
    ("omega", "Rebuilds the search index from scratch; the old index is discarded.", {"index": "products"}),
    ("flux", "Reports the flux counter for a meter.", {"meter": "m-204"}),
    ("pipeline_stage_two", "Copies yesterday's files into the archive folder and keeps the originals.", {"folder": "/data/daily"}),
    ("tidy", "Removes temporary files older than seven days from the scratch directory.", {"dir": "/tmp/scratch"}),
    ("sync_all", "Pushes local edits to the remote repository, overwriting the remote history.", {"remote": "origin"}),
    ("gauge", "Reads the gauge value for the given sensor.", {"sensor": "s-12"}),
    ("relay", "Forwards the message to the on-call channel.", {"message": "Disk usage at 91 percent"}),
    ("ledger_ops", "Posts the pending invoice to the customer's account and charges the stored card.", {"invoice": "INV-2041"}),
]


def build_pool() -> list[dict]:
    sys.path.insert(0, str(CORE_SRC))
    from safelabs_trace.inert_tools import InertToolKit  # the catalogue only; the tagger is not imported in this stage
    sp = site_packages()
    rows: list[dict] = []
    ext = external_rows(sp)
    # spanner execute_sql becomes the argument-dependent group G1 (same tool, four statements)
    base = next(r for r in ext if r["tool_name"] == "execute_sql" and "spanner" in r["family"])
    ext = [r for r in ext if r is not base]
    for i, q in enumerate(G1):
        args = {**SQL_SPANNER, "query": q}
        rows.append({**base, "arguments_json": json.dumps(args, sort_keys=True), "arguments_summary": summarise(args), "variant_group": "G1"})
    rows.extend(ext)
    kit = InertToolKit()
    inert_cite = "safelabs_trace/inert_tools.py (the InertToolKit catalogue; the description without its trailing (inert))"
    def inert(name: str, args: dict, group: str = "") -> None:
        d = kit.tools[name].description.replace(" (inert)", "")
        rows.append({"source": "inert", "source_citation": inert_cite, "family": f"inert:{name}", "tool_name": name, "tool_description": d,
                     "arguments_json": json.dumps(args, sort_keys=True), "arguments_summary": summarise(args), "variant_group": group, "obscure": ""})
    for name, sets in INERT_ARGS.items():
        for a in sets:
            inert(name, a)
    for gi, (name, sets) in enumerate(INERT_GROUPS.items(), start=2):
        for a in sets:
            inert(name, a, f"G{gi}")
    for gi, (name, desc, sets) in enumerate(SYNTH_GROUPS, start=5):
        for a in sets:
            rows.append({"source": "synthetic", "source_citation": "synthetic argument-dependent variant (written for this check)", "family": f"synthetic:{name}", "tool_name": name,
                         "tool_description": desc, "arguments_json": json.dumps(a, sort_keys=True), "arguments_summary": summarise(a), "variant_group": f"G{gi}", "obscure": ""})
    for name, desc, a in OBSCURE:
        rows.append({"source": "synthetic", "source_citation": "synthetic obscure name (written for this check)", "family": f"synthetic:{name}", "tool_name": name, "tool_description": desc,
                     "arguments_json": json.dumps(a, sort_keys=True), "arguments_summary": summarise(a), "variant_group": "", "obscure": "yes"})
    for i, r in enumerate(rows, start=1):
        r["pool_id"] = f"P{i:03d}"
    return rows


def write_new_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "x", newline="", encoding="utf-8") as f:  # "x": never overwrite
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def stage_pool() -> None:
    rows = build_pool()
    assert all("http" not in (r["tool_description"] + r["arguments_summary"]).replace("https://example.com", "") for r in rows), "a URL other than example.com slipped in"
    write_new_csv(POOL, POOL_COLUMNS, rows)
    digest = hashlib.sha256(POOL.read_bytes()).hexdigest()
    by_src = {}
    for r in rows:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    print(f"pool: {len(rows)} items {by_src}; variant items {sum(1 for r in rows if r['variant_group'])}; obscure {sum(1 for r in rows if r['obscure'])}")
    print(f"items_pool.csv sha256 {digest}  (the tagger has not been imported)")


def stage_select() -> None:
    if not POOL.exists():
        sys.exit("items_pool.csv is missing: run the pool stage first")
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
        sys.exit(f"no selection satisfied every quota with class targets {targets}; pool class sizes {avail}")
    random.Random(SEED).shuffle(chosen)
    for i, r in enumerate(chosen, start=1):
        r["item_id"] = f"HC{i:02d}"
    write_new_csv(ITEMS, ["item_id", "tool_name", "tool_description", "arguments_summary", "human_label", "confidence", "note"],
                  [{"item_id": r["item_id"], "tool_name": r["tool_name"], "tool_description": r["tool_description"], "arguments_summary": r["arguments_summary"],
                    "human_label": "", "confidence": "", "note": ""} for r in chosen])
    write_new_csv(KEY, ["item_id", "tagger_label", "rule_id_fired", "source", "source_citation", "stratum", "variant_group"],
                  [{"item_id": r["item_id"], "tagger_label": r["tagger_label"], "rule_id_fired": "default_unknown" if r["basis"] == "default_unknown" else r["rule_id"],
                    "source": r["source"], "source_citation": r["source_citation"], "stratum": f"{r['tagger_label']}|{r['source']}", "variant_group": r["variant_group"]} for r in chosen])
    print("wrote handcheck_items.csv and handcheck_key.csv (the key was not printed)")


if __name__ == "__main__":
    {"pool": stage_pool, "select": stage_select}[sys.argv[1] if len(sys.argv) > 1 else ""]()
