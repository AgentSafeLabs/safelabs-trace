"""Syntax-tree extraction of tools from the declared modules (modules_declared_c.md). Never imports the packages. Writes extract_c.json."""
import ast, json, sys, glob, os
sys.dont_write_bytecode = True
SP = os.path.expanduser("~/Desktop/Workspace/AgentSafeLabs/safelabs-eval/.venv/lib/python3.12/site-packages/")
D = "~/Desktop/Workspace/AgentSafeLabs/safelabs-eval/.venv/lib/python3.12/site-packages/"
def py(pattern): return sorted(glob.glob(SP + pattern, recursive=True))
MODS = {
 "ag2 0.14.0": py("autogen/tools/experimental/google/drive/*.py") + [SP+"autogen/tools/experimental/reliable/reliable.py", SP+"autogen/tools/experimental/browser_use/browser_use.py"],
 "openai-agents 0.18.0": [SP+"agents/sandbox/capabilities/"+f for f in ("shell.py","filesystem.py","memory.py","skills.py")] + py("agents/sandbox/capabilities/tools/*.py") + [SP+"agents/sandbox/apply_patch.py"] + py("agents/extensions/experimental/codex/*.py"),
 "google-adk 2.9.0": [SP+"google/adk/tools/"+f for f in ("skill_toolset.py","url_context_tool.py","google_maps_grounding_tool.py","vertex_ai_load_profiles_tool.py","set_model_response_tool.py","example_tool.py","preload_memory_tool.py","long_running_tool.py")] + [SP+"google/adk/tools/retrieval/"+f for f in ("files_retrieval.py","vertex_ai_rag_retrieval.py","llama_index_retrieval.py")],
 "semantic-kernel 1.44.1": [SP+"semantic_kernel/core_plugins/wait_plugin.py"],
 "llama-index-core": [SP+"llama_index/core/tools/"+f for f in ("retriever_tool.py","query_engine.py","query_plan.py","ondemand_loader_tool.py")] + py("llama_index/core/tools/tool_spec/*.py"),
}
FALLBACK = {
 "google-adk 2.9.0": [SP+"google/adk/tools/"+f for f in ("bash_tool.py","exit_loop_tool.py","get_user_choice_tool.py","load_web_page.py","transfer_to_agent_tool.py")] + py("google/adk/tools/spanner/*.py")+py("google/adk/tools/bigtable/*.py")+py("google/adk/tools/pubsub/*.py") +
     [SP+"google/adk/tools/bigquery/"+f for f in ("query_tool.py","metadata_tool.py","search_tool.py","data_insights_tool.py")] + [SP+"google/adk/tools/load_memory_tool.py", SP+"google/adk/tools/load_artifacts_tool.py", SP+"google/adk/tools/data_agent/data_agent_tool.py"] + [SP+"google/adk/tools/environment/"+f for f in ("_read_file_tool.py","_write_file_tool.py","_edit_file_tool.py","_execute_tool.py")],
 "semantic-kernel 1.44.1": [SP+"semantic_kernel/core_plugins/"+f for f in ("http_plugin.py","math_plugin.py","text_plugin.py","time_plugin.py","web_search_engine_plugin.py","text_memory_plugin.py","conversation_summary_plugin.py")] + py("semantic_kernel/core_plugins/sessions_python_tool/*.py") + py("semantic_kernel/core_plugins/crew_ai/*.py"),
 "ag2 0.14.0": sum([py("autogen/tools/experimental/%s/**/*.py" % d) for d in ("messageplatform","shell","apply_patch","duckduckgo","tavily","wikipedia","perplexity","deep_research","quick_research","google_search","tinyfish","crawl4ai")], []),
 "crewai 1.15.2": [SP+"crewai/tools/agent_tools/"+f for f in ("ask_question_tool.py","delegate_work_tool.py","read_file_tool.py","add_image_tool.py")] + [SP+"crewai/tools/memory_tools.py", SP+"crewai/tools/cache_tools/cache_tools.py"],
}
import sys as _s
if "--fallback" in _s.argv:
    MODS = FALLBACK
def const(n):
    return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None
out, skipped = [], []
for pkg, files in MODS.items():
    for f in files:
        if not os.path.exists(f): skipped.append((pkg, f, "missing file")); continue
        rel = f.replace(SP, "")
        tree = ast.parse(open(f).read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                kf = any((isinstance(d, ast.Name) and d.id == "kernel_function") or (isinstance(d, ast.Call) and getattr(d.func, "id", "") == "kernel_function") for d in node.decorator_list)
                doc = ast.get_docstring(node)
                # only top-level functions or kernel_function methods
                if not (kf or node in tree.body): continue
                if not doc: continue
                if node.name in ("get_runner_prompt","get_validator_prompt","reliable_function_wrapper","create_output_schema_file"): continue  # amendment 1, role exclusions
                params = [a.arg for a in node.args.args + node.args.kwonlyargs if a.arg not in ("self", "cls", "tool_context", "credentials")]
                out.append({"pkg": pkg, "file": rel, "line": node.lineno, "style": "kernel_function" if kf else "function", "name": node.name, "description": " ".join(doc.split())[:300], "params": params})
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                nm = ds = None
                for sub in ast.walk(node):
                    if isinstance(sub, ast.AnnAssign) and getattr(sub.target, "id", "") in ("name", "description") and sub.value is not None:
                        v = const(sub.value)
                        if sub.target.id == "name": nm = nm or v
                        else: ds = ds or v
                    if isinstance(sub, ast.Assign):
                        for t in sub.targets:
                            if isinstance(t, ast.Name) and t.id in ("name", "description"):
                                v = const(sub.value)
                                if t.id == "name": nm = nm or v
                                else: ds = ds or v
                    if isinstance(sub, ast.Call):
                        kws = {k.arg: const(k.value) for k in sub.keywords if k.arg in ("name", "description")}
                        if kws.get("name"): nm = nm or kws["name"]
                        if kws.get("description"): ds = ds or kws["description"]
                for sub in node.body:  # amendment 1: name/description as a property or method returning one string constant
                    if isinstance(sub, ast.FunctionDef) and sub.name in ("name", "description") and len(sub.body) >= 1:
                        last = [x for x in sub.body if isinstance(x, ast.Return)]
                        v = const(last[0].value) if last else None
                        if v is None and last and isinstance(last[0].value, ast.Name):  # a module-level string constant
                            for top in tree.body:
                                if isinstance(top, ast.Assign) and any(isinstance(t, ast.Name) and t.id == last[0].value.id for t in top.targets):
                                    v = const(top.value)
                        if v:
                            if sub.name == "name": nm = nm or v
                            else: ds = ds or v
                if nm and ds:
                    out.append({"pkg": pkg, "file": rel, "line": node.lineno, "style": "class", "name": nm, "description": " ".join(ds.split())[:300], "params": []})
                elif any(isinstance(b, ast.Name) and "Tool" in b.id or isinstance(b, ast.Attribute) and "Tool" in b.attr for b in node.bases):
                    skipped.append((pkg, rel + ":" + str(node.lineno), node.name))
json.dump({"tools": out, "skipped": skipped}, open("extract_c_fallback.json" if "--fallback" in _s.argv else "extract_c.json", "w"), indent=1)
print(len(out), "extracted;", len(skipped), "skipped")
for t in out: print(f"{t['pkg'][:8]:8} {t['file'].split('/',2)[-1][:50]:50} {t['style'][:6]:6} {t['name']:36} | {t['description'][:90]} | {t['params']}")
print("SKIPPED", len(skipped)); [print(" ", s) for s in skipped[:40]]
