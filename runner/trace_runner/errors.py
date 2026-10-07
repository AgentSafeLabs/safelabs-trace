"""Runner-side error rules (added after the main_cheap incident of 2026-10-07).

The hole: safelabs-eval's ``classify_error`` (safelabs/agents/errors.py) sorts a failed call into infrastructure, content_policy, no_output_text or ``other``; ``run_trial``
(agentport_bench/harness.py) records ``missing_infrastructure`` only for the infrastructure class, and an ``other`` error is "kept and scored as before": the empty text is scored UNCERTAIN and the row gets status
"scored" with a non-null error_class. A litellm.BadRequestError "Your credit balance is too low" (HTTP 400) matches no rule there, so 11 claude-haiku-4-5 trials became scored UNCERTAIN rows. safelabs-eval is read-only for this
work, so the runner closes the hole itself (orchestrator._run_one calls ``to_missing``; the repair command calls the same rules on existing folders).

Rules:
* Billing, credit and quota failures are infrastructure with error_subclass ``billing``; they are not retried inside the trial (retrying cannot help): the adapter answers a repeated attempt of the same trial from the first
  failure without calling the model, and the row records the real number of attempts.
* Any other trial whose final attempt ended in an error before the agent produced a response (error_class ``other``) is ``missing_infrastructure`` with its error_class and error_subclass kept.
* content_policy and no_output_text are NOT touched: by the study's convention (AgentPort-Bench, MAIN_RUN_PLAN: content-policy and no-output-text trials stay in and are scored UNCERTAIN) they remain scored rows.
  ``RECLASSIFY_CLASSES`` is the set the runner and the repair command act on; ``--reclassify-classes`` can widen it for the repair command.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

BILLING = "billing"
RECLASSIFY_CLASSES = ("other", "infrastructure")  # a scored row with one of these error classes is wrong

_BILLING_TYPES = {"BudgetExceededError", "InsufficientQuotaError", "InsufficientQuota", "PaymentRequiredError", "PaymentRequired", "BillingError"}
_BILLING_TEXT = (
    re.compile(r"credit balance is too low", re.I),                       # Anthropic
    re.compile(r"insufficient[_ ]quota", re.I),                           # OpenAI error code
    re.compile(r"exceeded your current quota", re.I),                     # OpenAI and Google wording
    re.compile(r"billing[_ ]hard[_ ]limit|billing is not active|billing account|check your plan and billing|plans? (?:&|and) billing", re.I),
    re.compile(r"payment required", re.I),
)
_QUOTA_OR_BILLING = re.compile(r"quota|billing", re.I)


def is_billing(message: str | None, meta: Mapping[str, Any] | None = None) -> bool:
    """True when the failure is a billing, credit or quota problem (not a per-minute rate limit): the text of Anthropic's credit error, OpenAI's insufficient_quota / exceeded-your-current-quota,
    HTTP 402, Google RESOURCE_EXHAUSTED with a quota or billing message, or a litellm / provider exception type that carries one."""
    meta = meta or {}
    if meta.get("status_code") == 402 or (set(meta.get("exception_mro") or ()) & _BILLING_TYPES):
        return True
    text = message or ""
    if any(p.search(text) for p in _BILLING_TEXT):
        return True
    return "RESOURCE_EXHAUSTED" in text and bool(_QUOTA_OR_BILLING.search(text))


def reclassify_reason(row: Any, classes: tuple[str, ...] = RECLASSIFY_CLASSES) -> str | None:
    """The reason a SCORED row must become missing_infrastructure, or None. A scored row (status scored or absent) whose error_class is in ``classes``."""
    if getattr(row, "status", None) not in (None, "scored") or getattr(row, "error_class", None) not in classes:
        return None
    sub = getattr(row, "error_subclass", None)
    if is_billing(getattr(row, "error", None)):
        return f"billing, credit or quota failure scored as {row.error_class}/{sub}: the final attempt ended in an error before any agent response"
    return f"scored row with error_class {row.error_class}/{sub}: the final attempt ended in an error before any agent response"


def to_missing_fields(row: Any, *, billing: bool = False, attempts: int | None = None) -> dict[str, Any]:
    """The fields of the missing_infrastructure version of ``row`` (as the harness writes a missing row: no verdict, confidence, weight, indicators or usage; error fields kept)."""
    d = row.model_dump()
    d.update(status="missing_infrastructure", verdict=None, confidence=None, attack_success_weight=None, indicators=[], usage=None)
    if billing:
        d.update(error_class="infrastructure", error_subclass=BILLING)
        n = attempts or d.get("attempts") or 1
        d.update(attempts=n, attempt_errors=[BILLING] * n)
    return d


def exception_message(exc: BaseException) -> str:
    """The text of an exception and of its cause chain (frameworks often wrap the provider's error)."""
    parts, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        parts.append(str(exc))
        exc = exc.__cause__ or exc.__context__
    return " | ".join(parts)


def exception_meta(exc: BaseException) -> dict[str, Any]:
    """status code and class names (MRO) of an exception and of its cause chain, in the shape ``is_billing`` reads."""
    names: list[str] = []
    code = None
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        names += [c.__name__ for c in type(exc).__mro__]
        code = code if code is not None else getattr(exc, "status_code", None)
        exc = exc.__cause__ or exc.__context__
    return {"exception_mro": names, "status_code": code}
