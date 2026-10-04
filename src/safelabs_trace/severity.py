"""safelabs_trace/severity.py: the action-severity tagger (design.md section E3).

Precedence:
1. A manual override for the tool name is used exactly (basis ``manual``).
2. Otherwise the severity is the maximum over the rule candidates: argument rules (SQL keywords, HTTP
   methods, shell strings), name rules (verb tokens in the tool name), and declared hints that raise.
   Declared hints can only raise: ``destructive`` raises to irreversible and an explicit non-read-only
   hint raises to state_changing; a declared ``read_only`` never lowers anything (it is recorded as
   corroboration when a name or argument rule also says read_only, and ignored otherwise unless
   ``trust_declared_read_only`` is set).
3. If no rule fires the result is ``unknown_default`` (state_changing unless the sensitivity setting
   says read_only) with basis ``default_unknown``.

Argument rules can only raise too: ``dry_run`` style arguments set a flag and never lower the severity.
The rules live in ``data/severity_rules.json``; this module has no rule strings of its own.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

SEVERITIES = ("read_only", "state_changing", "irreversible")
_RANK = {s: i for i, s in enumerate(SEVERITIES)}
_BASIS_PRIORITY = {"argument_rule": 0, "name_rule": 1, "declared": 2}  # tie-break between equal severities
_RULES_PATH = Path(__file__).parent / "data" / "severity_rules.json"
TAGGER_VERSION = "1"


def severity_rank(severity: str) -> int:
    return _RANK[severity]


def max_severity(*severities: str) -> str:
    return max(severities, key=severity_rank)


@dataclass(frozen=True)
class Tagged:
    """Result of tagging. Unpacks as (severity, basis, rule_ids)."""

    severity: str
    basis: str
    rule_ids: tuple[str, ...]
    flags: dict[str, bool] = field(default_factory=dict)
    capability_hint: str | None = None
    rules_version: str = ""

    def __iter__(self) -> Iterator[Any]:
        yield self.severity
        yield self.basis
        yield self.rule_ids


@functools.lru_cache(maxsize=1)
def _default_rules() -> dict[str, Any]:
    return json.loads(_RULES_PATH.read_text(encoding="utf-8"))


def load_rules(path: str | Path | None = None) -> dict[str, Any]:
    """The rule table: the packaged file by default, or another file with the same structure."""
    return _default_rules() if path is None else json.loads(Path(path).read_text(encoding="utf-8"))


def name_tokens(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return [t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t]


def _find_args(arguments: Any, keys: list[str]) -> list[Any]:
    """Values of arguments whose key (case-insensitive) is in keys, one level of nesting included."""
    out: list[Any] = []
    if isinstance(arguments, Mapping):
        want = {k.lower() for k in keys}
        for k, v in arguments.items():
            if str(k).lower() in want:
                out.append(v)
            elif isinstance(v, Mapping):
                out.extend(_find_args(v, keys))
    return out


def _sql_statements(text: str) -> list[str]:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"--[^\n]*", " ", text)
    return [s.strip() for s in text.split(";") if s.strip()]


def _sql_keyword(stmt: str, cte: dict[str, Any]) -> str:
    s = stmt.lstrip("( \t\n").lower()
    m = re.match(r"[a-z]+", s)
    kw = m.group(0) if m else ""
    if kw == cte["lead"]:  # a CTE: look at the statement it feeds
        for k in cte["write_keywords"]:
            if re.search(rf"\b{k}\b", s):
                return k
        return cte["default"]
    return kw


def _shell_parts(command: str) -> list[str]:
    return [p.strip() for p in re.split(r"&&|\|\||;|\n|\|", command) if p.strip()]


def _first_word(part: str, wrappers: list[str]) -> str:
    words = [w for w in part.split() if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
    while words and words[0] in wrappers:
        words = words[1:]
    return words[0].rsplit("/", 1)[-1] if words else ""


def tag_tool_call(
    name: str,
    arguments: Any = None,
    declared: Mapping[str, Any] | None = None,
    *,
    overrides: Mapping[str, str] | None = None,
    rules: dict[str, Any] | None = None,
    unknown_default: str = "state_changing",
    trust_declared_read_only: bool = False,
) -> Tagged:
    """Tag one tool call. ``arguments`` is the in-memory argument mapping (never stored by the tagger)."""
    r = rules if rules is not None else _default_rules()
    version = str(r.get("rules_version", ""))
    if unknown_default not in ("state_changing", "read_only"):
        raise ValueError("unknown_default must be state_changing or read_only")
    tokens = name_tokens(name)
    flags = {"egress": False, "external_effect": False, "arbitrary_code": False, "dry_run_seen": False}

    kind_hint = _capability_kind(tokens, r)
    if overrides and name in overrides:
        sev = overrides[name]
        if sev not in _RANK:
            raise ValueError(f"override for {name!r} is not a severity: {sev!r}")
        return Tagged(sev, "manual", ("OVERRIDE",), flags, _capability(kind_hint, sev, r), version)

    cands: list[tuple[int, int, str, str]] = []  # (rank, priority, basis, rule_id)
    fired: list[str] = []

    def add(severity: str, basis: str, rule_id: str, flag: str | None = None) -> None:
        cands.append((_RANK[severity], _BASIS_PRIORITY[basis], basis, rule_id))
        fired.append(rule_id)
        if flag:
            flags[flag] = True

    # name rules
    for rule in r["name_rules"]:
        if any(t in rule["tokens"] for t in tokens):
            add(rule["severity"], "name_rule", rule["id"], rule.get("flag"))

    # argument rules
    ak = r["arg_keys"]
    known_sql = {kw for rule in r["sql_rules"] for kw in rule["keywords"]} | {r["sql_cte"]["lead"]}
    sql_values = _find_args(arguments, ak["sql"]) + [v for v in _find_args(arguments, ak["sql_keyword_gated"])
                                                     if isinstance(v, str) and _sql_keyword(v, r["sql_cte"]) in known_sql]
    for text in sql_values:
        if isinstance(text, str):
            for stmt in _sql_statements(text):
                kw = _sql_keyword(stmt, r["sql_cte"])
                for rule in r["sql_rules"]:
                    if kw in rule["keywords"]:
                        add(rule["severity"], "argument_rule", rule["id"], rule.get("flag"))
                        break
                else:
                    add(r["sql_other"]["severity"], "argument_rule", r["sql_other"]["id"])
    for val in _find_args(arguments, ak["method"]):
        if isinstance(val, str):
            for rule in r["http_rules"]:
                if val.strip().lower() in rule["methods"]:
                    add(rule["severity"], "argument_rule", rule["id"])
    for cmd in _find_args(arguments, ak["command"]):
        if isinstance(cmd, (list, tuple)):
            cmd = " ".join(str(c) for c in cmd)
        if isinstance(cmd, str) and cmd.strip():
            _tag_shell(cmd, r, add, flags)
    if _find_args(arguments, ak["url"]):
        flags["egress"] = True
    for val in _find_args(arguments, ak["dry_run"]):
        if val in r["dry_run_truthy"]:
            flags["dry_run_seen"] = True  # recorded only; never lowers the severity

    # declared hints
    ro, destructive = _declared(declared, r)
    if destructive is True:
        add("irreversible", "declared", "D-DESTRUCTIVE")
    elif ro is False:
        add("state_changing", "declared", "D-WRITE")

    best = max(cands, key=lambda c: (c[0], -c[1])) if cands else None
    if ro is True:
        if best is None:
            if trust_declared_read_only:
                cands.append((0, _BASIS_PRIORITY["declared"], "declared", "D-READONLY"))
                fired.append("D-READONLY")
                best = cands[-1]
            else:
                fired.append("D-READONLY-IGNORED")
        elif best[0] == 0:
            fired.append("D-READONLY-CORROBORATES")
        else:
            fired.append("D-READONLY-OVERRIDDEN")

    if best is None:
        sev, basis, ids = unknown_default, "default_unknown", ["DEFAULT-UNKNOWN"] + fired
    else:
        sev, basis = SEVERITIES[best[0]], best[2]
        ids = [best[3]] + [i for i in fired if i != best[3]]
    flags["egress"] = flags["egress"] or kind_hint == "network"
    return Tagged(sev, basis, tuple(dict.fromkeys(ids)), flags, _capability(kind_hint, sev, r), version)


def _tag_shell(cmd: str, r: dict[str, Any], add: Any, flags: dict[str, bool]) -> None:
    sh = r["shell"]
    ids = sh["ids"]
    if any(re.search(p, cmd) for p in sh["irreversible_patterns"]):
        flags["arbitrary_code"] = True
        add("irreversible", "argument_rule", ids["irreversible_commands"])
        return
    parts = _shell_parts(cmd)
    redirect = bool(re.search(r"(?<![0-9&])>>?(?!&)", cmd))
    if parts and all(_first_word(p, sh["wrappers"]) in sh["read_commands"] for p in parts) and not redirect:
        add("read_only", "argument_rule", ids["read_commands"])
    else:
        flags["arbitrary_code"] = True
        add("state_changing", "argument_rule", ids["other_commands"])


def _declared(declared: Mapping[str, Any] | None, r: dict[str, Any]) -> tuple[bool | None, bool | None]:
    if not declared:
        return None, None
    def pick(names: list[str]) -> bool | None:
        for n in names:
            if n in declared and isinstance(declared[n], bool):
                return declared[n]
        return None
    return pick(r["declared_keys"]["read_only"]), pick(r["declared_keys"]["destructive"])


def _capability_kind(tokens: list[str], r: dict[str, Any]) -> str | None:
    for k in r["capability_kinds"]:
        if any(t in k["tokens"] for t in tokens):
            return k["kind"]
    return None


def _capability(kind: str | None, severity: str, r: dict[str, Any]) -> str | None:
    if kind is None:
        return None
    for k in r["capability_kinds"]:
        if k["kind"] == kind:
            return k[severity]
    return None
