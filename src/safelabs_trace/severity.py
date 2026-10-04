"""safelabs_trace/severity.py: the action-severity tagger (design.md section E3), rules version 2b.

Signals (all vocabulary lives in ``data/severity_rules.json``; this module has no rule strings of its own):
* name rules: verb/noun tokens in the tool name. A rule is ``strong`` (an explicit verb) or ``weak`` (a noun or a soft verb).
* description rules (new in 2b): the tool DESCRIPTION, used when name and arguments leave the effect open. Verbs are matched
  with guards against nouns read as verbs (determiner before the word, verb position for ambiguous words, negation window,
  money object for transfer-type verbs). Rule ids are ``D-DESC-*`` and the basis is ``name_rule`` (no schema change).
* argument rules: an action/operation field, SQL keywords, HTTP methods (POST is irreversible), and shell commands in three
  tiers (read, editing, destructive). A positively classified argument is ``hard``; an unrecognised statement or command is ``soft``.
* declared hints (raise only, unchanged).

Precedence (DECIDED, 2b):
1. A manual override for the tool name is used exactly (basis ``manual``).
2. If any HARD argument signal exists, description signals and WEAK name signals are dropped: arguments override the
   description and weak name nouns. STRONG name signals (an explicit destructive, send or write verb in the tool name) are kept:
   arguments never lower an explicit verb in the name.
3. The most severe surviving signal wins (ties: argument, name, description, declared).
4. Declared hints can only raise; a declared ``read_only`` never lowers anything (recorded as corroboration when a rule also
   says read_only, and ignored otherwise unless ``trust_declared_read_only`` is set).
5. Only when there is no signal at all the result is ``unknown_default`` (state_changing unless the sensitivity setting says
   read_only) with basis ``default_unknown``.

``dry_run`` style arguments set a flag and never lower the severity. ``rule_ids`` lists the decisive rule first, then every other
rule that matched (including signals dropped by the precedence). The description is used in memory only; this module never stores it.
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
# tie-break between equal severities; description-derived tags still carry the basis name_rule
_PRIORITY = {"argument": 0, "name": 1, "description": 2, "declared": 3}
_BASIS = {"argument": "argument_rule", "name": "name_rule", "description": "name_rule", "declared": "declared"}
_RULES_PATH = Path(__file__).parent / "data" / "severity_rules.json"
TAGGER_VERSION = "2b"


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


@dataclass
class _Cand:
    rank: int
    group: str  # name | description | argument | declared
    rule_id: str
    kind: str  # strong | weak | hard | soft | plain
    flag: str | None = None


def tag_tool_call(
    name: str,
    arguments: Any = None,
    declared: Mapping[str, Any] | None = None,
    *,
    overrides: Mapping[str, str] | None = None,
    rules: dict[str, Any] | None = None,
    unknown_default: str = "state_changing",
    trust_declared_read_only: bool = False,
    description: str | None = None,
) -> Tagged:
    """Tag one tool call. ``arguments`` and ``description`` are in-memory values (never stored by the tagger)."""
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

    cands: list[_Cand] = []

    def add(severity: str, group: str, rule_id: str, kind: str, flag: str | None = None) -> None:
        cands.append(_Cand(_RANK[severity], group, rule_id, kind, flag))

    # name rules (a phrase rule can replace a plain rule: the guard against a noun-like context)
    matched = [rule for rule in r["name_rules"] if any(t in rule["tokens"] for t in tokens)]
    for pr in r.get("name_phrase_rules", []):
        if all(t in tokens for t in pr["requires_tokens"]) and any(t in tokens for t in pr["requires_any"]):
            matched = [m for m in matched if m["id"] not in pr["replaces"]]
            add(pr["severity"], "name", pr["id"], pr.get("strength", "strong"), pr.get("flag"))
    for rule in matched:
        add(rule["severity"], "name", rule["id"], rule.get("strength", "strong"), rule.get("flag"))

    # description rules
    if isinstance(description, str) and description.strip() and r.get("description_layer"):
        for rid, sev, flag in _description_signals(description, r["description_layer"]):
            add(sev, "description", rid, "plain", flag)

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
                        add(rule["severity"], "argument", rule["id"], "hard", rule.get("flag"))
                        break
                else:
                    add(r["sql_other"]["severity"], "argument", r["sql_other"]["id"], "soft")
    for val in _find_args(arguments, ak["method"]):
        if isinstance(val, str):
            for rule in r["http_rules"]:
                if val.strip().lower() in rule["methods"]:
                    add(rule["severity"], "argument", rule["id"], "hard")
    for val in _find_args(arguments, ak.get("action", [])):
        if isinstance(val, str):
            vtoks = set(name_tokens(val))
            for rule in r.get("action_rules", []):
                if vtoks & set(rule["words"]):
                    add(rule["severity"], "argument", rule["id"], "hard", rule.get("flag"))
    for cmd in _find_args(arguments, ak["command"]):
        if isinstance(cmd, (list, tuple)):
            cmd = " ".join(str(c) for c in cmd)
        if isinstance(cmd, str) and cmd.strip():
            _tag_shell(cmd, r, add)
    if _find_args(arguments, ak["url"]):
        flags["egress"] = True
    for val in _find_args(arguments, ak["dry_run"]):
        if val in r["dry_run_truthy"]:
            flags["dry_run_seen"] = True  # recorded only; never lowers the severity

    # precedence: a hard argument signal drops description signals and weak name signals
    hard = any(c.group == "argument" and c.kind == "hard" for c in cands)
    live = [c for c in cands if not (hard and (c.group == "description" or (c.group == "name" and c.kind == "weak")))]
    fired = [c.rule_id for c in cands]
    for c in live:
        if c.flag:
            flags[c.flag] = True

    # declared hints
    ro, destructive = _declared(declared, r)
    if destructive is True:
        live.append(_Cand(2, "declared", "D-DESTRUCTIVE", "plain"))
        fired.append("D-DESTRUCTIVE")
    elif ro is False:
        live.append(_Cand(1, "declared", "D-WRITE", "plain"))
        fired.append("D-WRITE")

    best = max(live, key=lambda c: (c.rank, -_PRIORITY[c.group])) if live else None
    if ro is True:
        if best is None:
            if trust_declared_read_only:
                best = _Cand(0, "declared", "D-READONLY", "plain")
                fired.append("D-READONLY")
            else:
                fired.append("D-READONLY-IGNORED")
        elif best.rank == 0:
            fired.append("D-READONLY-CORROBORATES")
        else:
            fired.append("D-READONLY-OVERRIDDEN")

    if best is None:
        sev, basis, ids = unknown_default, "default_unknown", ["DEFAULT-UNKNOWN"] + fired
    else:
        sev, basis = SEVERITIES[best.rank], _BASIS[best.group]
        ids = [best.rule_id] + [i for i in fired if i != best.rule_id]
    flags["egress"] = flags["egress"] or kind_hint == "network"
    return Tagged(sev, basis, tuple(dict.fromkeys(ids)), flags, _capability(kind_hint, sev, r), version)


def _tag_shell(cmd: str, r: dict[str, Any], add: Any) -> None:
    """Three tiers per command part (read, editing, destructive); the command's severity is the maximum over its parts.
    A fully classified command is a hard signal; a command with an unrecognised part is a soft state_changing signal."""
    sh = r["shell"]
    ids = sh["ids"]
    destructive = [re.compile(p) for p in sh["irreversible_patterns"]]
    editing = [re.compile(p) for p in sh.get("editing_patterns", [])]
    reading = [re.compile(p) for p in sh.get("read_patterns", [])]
    whole_irreversible = any(p.search(cmd) for p in destructive)
    redirect = bool(re.search(r"(?<![0-9&])>>?(?!&)", cmd))
    rank, classified = 0, True
    for part in _shell_parts(cmd):
        word = _first_word(part, sh["wrappers"])
        if word in sh.get("destructive_commands", []):
            rank = max(rank, 2)
        elif any(p.search(part) for p in editing) or word in sh.get("editing_commands", []):
            rank = max(rank, 1)
        elif word in sh["read_commands"] or any(p.search(part) for p in reading):
            pass
        else:
            classified, rank = False, max(rank, 1)
    if redirect:
        rank = max(rank, 1)
    if whole_irreversible:
        rank = 2
    flag = None if rank == 0 and not whole_irreversible else "arbitrary_code"
    if rank == 2:
        add("irreversible", "argument", ids["irreversible_commands"], "hard", flag)
    elif rank == 1 and classified:
        add("state_changing", "argument", ids["editing_commands"], "hard", flag)
    elif rank == 1:
        add("state_changing", "argument", ids["other_commands"], "soft", flag)
    elif _shell_parts(cmd):
        add("read_only", "argument", ids["read_commands"], "hard")
    else:
        add("state_changing", "argument", ids["other_commands"], "soft", "arbitrary_code")


def _inflections(base: str) -> dict[str, str]:
    """Surface forms of a verb: base, third person (s) and -ing."""
    forms = {base: "base", base + "s": "s", base + "es": "s", base + "ing": "ing", base + base[-1] + "ing": "ing"}
    if base.endswith("y"):
        forms[base[:-1] + "ies"] = "s"
    if base.endswith("e"):
        forms[base[:-1] + "ing"] = "ing"
    return forms


_DESC_CACHE: dict[int, tuple[Any, dict[str, list[tuple[Any, ...]]]]] = {}


def _compile_description(dl: dict[str, Any]) -> dict[str, list[tuple[Any, ...]]]:
    """first-token surface form -> [(rule, rest_tokens, form, ambiguous, lemma)]."""
    hit = _DESC_CACHE.get(id(dl))
    if hit is not None and hit[0] is dl:
        return hit[1]
    index: dict[str, list[tuple[Any, ...]]] = {}
    for rule in dl["rules"]:
        for ambiguous, verbs in ((False, rule.get("verbs", [])), (True, rule.get("ambiguous", []))):
            for v in verbs:
                first, *rest = v.split()
                for surface, form in _inflections(first).items():
                    index.setdefault(surface, []).append((rule, tuple(rest), form, ambiguous, first))
    _DESC_CACHE[id(dl)] = (dl, index)
    return index


def _description_signals(text: str, dl: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    """(rule_id, severity, flag) for every description rule that fires. Guards: see the module docstring and the rule file."""
    text = text[: int(dl.get("max_chars", 2000))]
    breaks, cues = set(dl["clause_breaks"]), set(dl["verb_cues"])
    dets, preps, negs = set(dl["determiners"]), set(dl["noun_prepositions"]), set(dl["negators"])
    window, obj_window = int(dl["negation_window"]), int(dl["object_window"])
    toks = re.findall(r"[A-Za-z]+(?:'[a-z]+)?|[.;:!?,\n()]", text.lower().replace("’", "'"))
    index = _compile_description(dl)
    out: list[tuple[str, str, str | None]] = []
    for i, tok in enumerate(toks):
        for rule, rest, form, ambiguous, lemma in index.get(tok, ()):
            if tuple(toks[i + 1:i + 1 + len(rest)]) != rest:
                continue
            nxt = toks[i + 1 + len(rest)] if i + 1 + len(rest) < len(toks) else ""
            prev = toks[i - 1] if i else ""
            if any(t in negs for t in toks[max(0, i - window):i]) or prev in dets:
                continue
            if form != "ing" and prev in preps:
                continue
            if ambiguous and form != "ing" and not (i == 0 or prev in breaks or prev in cues):
                continue
            if nxt in dl["skip_if_next"].get(lemma, ()):
                continue
            objs = dl["requires_object"].get(lemma)
            if objs and not any(t in objs for t in toks[i + 1:i + 1 + obj_window]):
                continue
            out.append((rule["id"], rule["severity"], rule.get("flag")))
    for pr in dl.get("phrase_rules", []):
        for m in re.finditer(pr["pattern"], text.lower()):
            before = text.lower()[max(0, m.start() - 25):m.start()]
            if re.search(r"\b(" + "|".join(re.escape(n) for n in negs) + r")\b[^.;]*$", before):
                continue
            out.append((pr["id"], pr["severity"], pr.get("flag")))
            break
    return list(dict.fromkeys(out))


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
