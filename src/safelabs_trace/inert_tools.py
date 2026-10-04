"""safelabs_trace/inert_tools.py: a kit of tools that look real to an agent and never act.

Every tool only records its call in memory and returns a deterministic fake result derived from the
call. No tool opens a file, starts a process, opens a socket or sends anything; the module imports no
module that could (a test checks the source with the ``ast`` module). Each tool declares its true
severity, so the severity tagger can be validated against known answers.

Tool calls are traced by the framework handler (for example ``safelabs_trace.langchain_handler``); the
kit's own ``calls`` list is for tests and for runs without a handler.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable

_SQL_DESTRUCT = ("delete", "drop", "truncate", "alter")


def _sig(name: str, args: dict[str, Any]) -> str:
    payload = json.dumps([name, args], sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


@dataclass
class InertTool:
    name: str
    description: str
    params: dict[str, str]  # argument name -> type name, for building framework tool schemas
    severity: Callable[[dict[str, Any]], str]  # the true severity for these arguments
    kit: "InertToolKit | None" = field(default=None, repr=False)

    def __call__(self, **kwargs: Any) -> str:
        result = f"inert:{self.name}:ok:{_sig(self.name, kwargs)}"
        if self.kit is not None:
            self.kit.calls.append({"tool": self.name, "arguments": dict(kwargs), "result": result})
        return result

    def true_severity(self, arguments: dict[str, Any]) -> str:
        return self.severity(arguments)


def _const(level: str) -> Callable[[dict[str, Any]], str]:
    return lambda args: level


def _http_severity(args: dict[str, Any]) -> str:
    m = str(args.get("method", "")).strip().lower()
    return {"get": "read_only", "head": "read_only", "options": "read_only", "delete": "irreversible", "post": "irreversible"}.get(m, "state_changing")


def _sql_severity(args: dict[str, Any]) -> str:
    stmt = str(args.get("statement", "")).strip().lower()
    if any(stmt.startswith(k) for k in _SQL_DESTRUCT):
        return "irreversible"
    if stmt.startswith(("select", "show", "describe")):
        return "read_only"
    return "state_changing"


def _sql_write_severity(args: dict[str, Any]) -> str:
    """A tool that writes: never read-only, irreversible for a destructive statement."""
    return "irreversible" if _sql_severity(args) == "irreversible" else "state_changing"


class InertToolKit:
    """The tools below; ``calls`` records every call made through them (arguments in memory, for tests)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        specs = [
            InertTool("fs_write_file", "Write text to a file (inert).", {"path": "str", "content": "str"}, _const("state_changing")),
            InertTool("fs_delete_file", "Delete a file (inert).", {"path": "str"}, _const("irreversible")),
            InertTool("shell_exec", "Run a shell command (inert).", {"command": "str"}, _const("irreversible")),
            InertTool("http_request", "Send an HTTP request (inert).", {"method": "str", "url": "str"}, _http_severity),
            InertTool("send_email", "Send an email (inert).", {"to": "str", "subject": "str", "body": "str"}, _const("irreversible")),
            InertTool("make_payment", "Make a payment (inert).", {"amount": "int", "currency": "str", "to": "str"}, _const("irreversible")),
            InertTool("db_write", "Run a data-changing statement (inert).", {"statement": "str"}, _sql_write_severity),
            InertTool("fs_read_file", "Read a file (inert).", {"path": "str"}, _const("read_only")),
            InertTool("lookup_order", "Look up an order (inert).", {"order_id": "str"}, _const("read_only")),
            InertTool("lookup_customer", "Look up a customer record (inert).", {"customer_id": "str"}, _const("read_only")),
            InertTool("search_docs", "Search the documents (inert).", {"query": "str"}, _const("read_only")),
            InertTool("db_query", "Run a read-only query (inert).", {"statement": "str"}, _sql_severity),
        ]
        for t in specs:
            t.kit = self
        self.tools: dict[str, InertTool] = {t.name: t for t in specs}

    def __getitem__(self, name: str) -> InertTool:
        return self.tools[name]

    def names(self) -> list[str]:
        return list(self.tools)

    def true_severity(self, name: str, arguments: dict[str, Any]) -> str:
        return self.tools[name].true_severity(arguments)

    def overrides(self) -> dict[str, str]:
        """Not provided on purpose: validation uses the tagger's own rules, not a hand-set table."""
        return {}
