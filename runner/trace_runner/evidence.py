"""LOCAL-ONLY evidence sidecar (decision D10). Opt-in with ``--evidence-dir PATH``.

Why: the public traces keep digests only, so after the pilot nobody could check what a shell command was or what a model answered. The sidecar keeps, for each
trial's final attempt, the final answer text and for every tool call the raw arguments exactly as the model sent them, the stub result the inert tool returned,
and the trace's own event ids, severity, rule ids and basis. It is written ONLY to the evidence folder, one JSON line per trial in ``evidence.jsonl``.
Nothing from it goes into results.jsonl, the traces, the manifests or the summaries (the only value derived from it that does is ``final_text_len``, an integer, in trace_manifest.json only).

Safety, enforced in code:
* the folder must not be inside ANY git working tree (a ``.git`` entry in the folder or any parent; ignored or not), and must not be, contain or sit inside the run's output folder;
* the folder is created with mode 700 and the file with mode 600 (set from code, whatever the umask); a README.txt says LOCAL ONLY, NEVER COMMIT, NEVER UPLOAD;
* before writing, key-like strings are replaced by ``[REDACTED]``: sk-ant-..., sk-..., AIza..., Bearer tokens, a few other common provider token shapes, and the value of the
  trace salt the runner already holds. Environment variables are never read for this; patterns plus that one value only. Redaction is best effort: the file is still sensitive.
* size: each stored final answer and each raw-argument string is cut at 20,000 characters (after redaction, so a key can never be cut in half and leak a fragment); the record says what was cut
  (``final_text_truncated``, per call ``arguments_truncated`` and ``arguments_truncated_fields``) and keeps the original ``final_text_len``.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from safelabs_trace.writer import read_trace

SCHEMA = "1b-evidence/1"
REDACTED = "[REDACTED]"
README = """LOCAL ONLY. NEVER COMMIT. NEVER UPLOAD.

evidence.jsonl in this folder holds model answers and raw tool-call arguments from a benchmark run (shell commands, file paths, SQL, e-mail text, answers that may be
harmful or sensitive). Key-like strings were replaced by [REDACTED] before writing, but that is best effort.
Keep it on this machine. Do not add it to any git repository, do not put it in a tarball, a release, a bucket or an e-mail.
The run's public outputs (results.jsonl, traces, manifests, divergence summaries) do not contain any of it.
"""

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
MAX_FIELD_CHARS = 20_000  # cap for each stored final answer and each raw-argument string (characters, after redaction)
MIN_SALT_CHARS = 6  # a shorter salt would mangle ordinary text; real salts are long random strings


class EvidenceRefusal(RuntimeError):
    """The evidence folder is not acceptable; the runner refuses to start."""


class Redactor:
    def __init__(self, salt: bytes | None = None) -> None:
        s = salt.decode("utf-8", "ignore") if salt else ""
        self.salt = s if len(s) >= MIN_SALT_CHARS else ""
        self.count = 0

    def text(self, s: str) -> str:
        for p in _PATTERNS:
            s, n = p.subn(REDACTED, s)
            self.count += n
        if self.salt and self.salt in s:
            self.count += s.count(self.salt)
            s = s.replace(self.salt, REDACTED)
        return s

    def obj(self, o: Any) -> Any:
        if isinstance(o, str):
            return self.text(o)
        if isinstance(o, dict):
            return {self.text(str(k)): self.obj(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [self.obj(v) for v in o]
        if isinstance(o, (int, float, bool)) or o is None:
            return o
        return self.text(str(o))


def inside_git_tree(path: Path) -> Path | None:
    """The nearest folder (the path itself or a parent) that has a ``.git`` entry, else None. No git command is run."""
    p = path.resolve()
    for q in (p, *p.parents):
        if (q / ".git").exists():
            return q
    return None


def check_evidence_dir(path: str | Path, out_dir: str | Path) -> Path:
    """Resolve and validate the evidence folder; raises EvidenceRefusal. Symlinks are resolved first, so a link into a repository is caught."""
    p, o = Path(path).expanduser().resolve(), Path(out_dir).expanduser().resolve()
    if p == o or o in p.parents or p in o.parents:
        raise EvidenceRefusal(f"refusing to start: the evidence folder {p} is, contains or lies inside the run's output folder {o}")
    g = inside_git_tree(p)
    if g is not None:
        raise EvidenceRefusal(f"refusing to start: the evidence folder {p} is inside a git working tree ({g}); choose a folder outside every repository")
    if p.exists() and not p.is_dir():
        raise EvidenceRefusal(f"refusing to start: {p} exists and is not a folder")
    if p.exists() and any(p.iterdir()) and not (p / "README.txt").exists():
        raise EvidenceRefusal(f"refusing to start: {p} is not empty and was not made by this runner (no README.txt)")
    return p


class EvidenceWriter:
    def __init__(self, path: str | Path, out_dir: str | Path, salt: bytes | None = None, max_chars: int = MAX_FIELD_CHARS) -> None:
        self.max_chars = max_chars
        self.dir = check_evidence_dir(path, out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o700)
        readme = self.dir / "README.txt"
        if not readme.exists():
            fd = os.open(readme, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(README)
        os.chmod(readme, 0o600)
        self.file = self.dir / "evidence.jsonl"
        fd = os.open(self.file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.close(fd)
        os.chmod(self.file, 0o600)
        self.redactor = Redactor(salt)
        self.lines = 0

    def write(self, rec: dict[str, Any]) -> None:
        """One record per trial's final attempt. Redaction is applied to every string in the record."""
        self.redactor.count = 0
        red = self.redactor.obj(rec)
        red["redactions"] = self.redactor.count
        cap = self.max_chars
        red["max_field_chars"] = cap
        text = red.get("final_text") or ""
        red["final_text_truncated"] = len(text) > cap
        if red["final_text_truncated"]:
            red["final_text"] = text[:cap]
        for c in red.get("tool_calls", []):
            cut: list[str] = []
            c["arguments"] = _cap(c.get("arguments"), cap, "", cut)
            c["arguments_truncated"] = bool(cut)
            c["arguments_truncated_fields"] = cut
        fd = os.open(self.file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(red, ensure_ascii=False, sort_keys=True) + "\n")
        os.chmod(self.file, 0o600)
        self.lines += 1


def build_record(*, trial: Any, row: Any, attempt: int, run_pass: int, trace_path: Path, final_text: str, kit_calls: list[dict[str, Any]], category: str | None) -> dict[str, Any]:
    """Join the in-process evidence (final text, raw arguments, stub results; ``kit_calls`` in call order) to the trace events of the final attempt."""
    events: list[Any] = []
    if trace_path.exists():
        allev = list(read_trace(trace_path))
        att = {}
        for e in allev:
            if e.type == "session.start" and getattr(e, "trial", None):
                att[e.trace_id] = int(e.trial.get("attempt", 0))
        want = [t for t, a in att.items() if a == attempt] or [max(att, key=att.get)] if att else []
        events = sorted([e for e in allev if want and e.trace_id == want[-1]], key=lambda e: e.seq)
    trace_id = events[0].trace_id if events else None
    req = {e.event_id: e for e in events if e.type == "tool.call.requested"}
    executed = [e for e in events if e.type == "tool.call.executed"]
    calls: list[dict[str, Any]] = []
    used: set[int] = set()
    for i, kc in enumerate(kit_calls):
        match = None
        for j, ex in enumerate(executed):  # first unused executed event with the same tool name, in order
            if j not in used and ex.tool_name == kc["tool"]:
                match = ex
                used.add(j)
                break
        rq = req.get(match.requested_event_id) if match is not None else None
        calls.append({"index": i + 1, "matched_to_trace": match is not None, "tool": kc["tool"], "arguments": kc.get("arguments"), "stub_result": kc.get("result"),
                      "requested_event_id": rq.event_id if rq else None, "executed_event_id": match.event_id if match else None,
                      "severity": (rq.severity if rq else (match.severity if match else None)), "rule_ids": (list(rq.rule_ids) if rq else None),
                      "severity_basis": (rq.severity_basis if rq else (match.severity_basis if match else None))})
    return {"schema": SCHEMA, "written": datetime.now(timezone.utc).isoformat(), "framework": trial.framework, "model": trial.model.id, "prompt_id": trial.item.id, "category": category,
            "trial_seed": trial.seed, "attempt": attempt, "run_pass": run_pass, "trace_id": trace_id, "status": row.status or "scored",
            "verdict": (row.verdict.value if row.verdict else None), "tool_call_only": bool(row.tool_call_only), "final_text": final_text, "final_text_len": len(final_text),
            "tool_calls": calls}


def _cap(o: Any, cap: int, path: str, cut: list[str]) -> Any:
    """Cut every string longer than ``cap`` characters (values inside dicts and lists too); ``cut`` collects the key paths that were cut."""
    if isinstance(o, str):
        if len(o) > cap:
            cut.append(path or "(value)")
            return o[:cap]
        return o
    if isinstance(o, dict):
        return {k: _cap(v, cap, f"{path}.{k}" if path else str(k), cut) for k, v in o.items()}
    if isinstance(o, list):
        return [_cap(v, cap, f"{path}[{i}]", cut) for i, v in enumerate(o)]
    return o
