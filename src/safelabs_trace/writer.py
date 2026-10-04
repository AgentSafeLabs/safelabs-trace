"""safelabs_trace/writer.py: the JSONL trace writer (design.md section E5).

* One event per line; every trace starts with a ``trace.header`` (the coverage manifest). Appends are one
  ``os.write`` on an ``O_APPEND`` descriptor under a lock; ``close_trace`` and rotation fsync.
* Capture is **digest-only by default**. ``capture_value`` returns a ``Capture`` (salted HMAC-SHA-256 truncated
  to 16 hex characters, canonical byte length, type name, sorted keys for a dict). The content itself is not
  written anywhere in the default modes.
* The salt comes from an explicit argument, the environment variable ``SAFELABS_TRACE_SALT`` (name configurable) or
  a salt file outside any git working tree. It is never written to a trace; only a salt id is. With no salt in
  digest or full mode the writer refuses to start (no silent unsalted hashing).
* ``capture="full"`` (opt-in) additionally stores the content in a separate ``<name>.full.jsonl`` under
  ``capture_dir``, which must be git-ignored when it sits in a git working tree.
* Limits: an event over ``max_event_bytes`` has its long strings truncated and ``truncated`` set; a trace over
  ``max_trace_events`` or ``max_trace_bytes`` drops further events and gets ``trace.truncated`` markers; the file
  rotates to ``<stem>.<n>.jsonl`` at ``max_file_bytes``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from pathlib import Path
from typing import Any, Iterator

from safelabs_trace.schema import (
    EVENT_TYPES, Capture, HeaderEvent, TraceEvent, TraceTruncated, build_event, dump_event, parse_event,
)

DEFAULT_SALT_ENV = "SAFELABS_TRACE_SALT"
_DIGEST_HEX = 16


class TraceError(RuntimeError):
    """Misuse of the writer (event before its trace header, closed writer, bad configuration)."""


class SaltError(TraceError):
    """No usable salt, or a salt file in an unsafe place."""


class CaptureDirError(TraceError):
    """The full-capture directory is not safely git-ignored."""


def _find_git_root(path: Path) -> Path | None:
    for p in [path, *path.parents]:
        if (p / ".git").exists():
            return p
    return None


def resolve_salt(salt: bytes | str | None = None, env: str = DEFAULT_SALT_ENV, salt_file: str | Path | None = None) -> bytes | None:
    """Explicit argument, then the environment variable, then the file. A file inside a git working tree is refused."""
    if salt is not None:
        return salt.encode() if isinstance(salt, str) else bytes(salt)
    if os.environ.get(env):
        return os.environ[env].encode()
    if salt_file is not None:
        p = Path(salt_file).resolve()
        if _find_git_root(p.parent) is not None:
            raise SaltError(f"salt file {p} is inside a git working tree; keep it outside the repo")
        data = p.read_bytes().strip()
        if not data:
            raise SaltError(f"salt file {p} is empty")
        return data
    return None


def salt_id(salt: bytes) -> str:
    return hashlib.sha256(b"safelabs-trace-salt-id:" + salt).hexdigest()[:8]


def _canonical(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False).encode("utf-8")


def digest_value(value: Any, salt: bytes) -> tuple[str, int]:
    """(salted digest, canonical byte length)."""
    data = _canonical(value)
    return hmac.new(salt, data, hashlib.sha256).hexdigest()[:_DIGEST_HEX], len(data)


def _check_capture_dir(capture_dir: Path) -> None:
    root = _find_git_root(capture_dir.resolve())
    if root is None:
        return
    rel = capture_dir.resolve().relative_to(root)
    first = rel.parts[0] if rel.parts else ""
    gi = root / ".gitignore"
    lines = [l.strip() for l in gi.read_text().splitlines()] if gi.exists() else []
    ok = {first, first + "/", "/" + first, "/" + first + "/", str(rel), str(rel) + "/", "/" + str(rel), "/" + str(rel) + "/"}
    if not first or not (ok & set(lines)):
        raise CaptureDirError(f"{capture_dir} is in a git working tree ({root}) but is not listed in its .gitignore")


def iter_trace_files(path: str | Path) -> list[Path]:
    """The trace file and its rotated parts, in order."""
    p = Path(path)
    parts = sorted(p.parent.glob(f"{p.stem}.[0-9]*{p.suffix}"), key=lambda q: int(q.stem.rsplit(".", 1)[1]))
    return [p, *parts] if p.exists() else parts


class TraceWriter:
    def __init__(self, path: str | Path, *, capture: str = "digest", salt: bytes | str | None = None, salt_env: str = DEFAULT_SALT_ENV,
                 salt_file: str | Path | None = None, capture_dir: str | Path | None = None, max_event_bytes: int = 8192,
                 max_trace_events: int = 256, max_trace_bytes: int = 1 << 20, max_file_bytes: int = 64 << 20, fsync: bool = False) -> None:
        if capture not in ("none", "digest", "full"):
            raise TraceError("capture must be none, digest or full")
        self.path, self.capture = Path(path), capture
        self._salt = resolve_salt(salt, salt_env, salt_file)
        if capture != "none" and self._salt is None:
            raise SaltError(f"capture={capture} needs a salt: pass one, set {salt_env}, or give a salt file outside the repo")
        self.salt_id = salt_id(self._salt) if self._salt is not None else None
        self.capture_dir = Path(capture_dir) if capture_dir is not None else None
        if capture == "full":
            if self.capture_dir is None:
                raise CaptureDirError("capture=full needs capture_dir")
            _check_capture_dir(self.capture_dir)
            self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.max_event_bytes, self.max_trace_events, self.max_trace_bytes = max_event_bytes, max_trace_events, max_trace_bytes
        self.max_file_bytes, self._fsync = max_file_bytes, fsync
        self._lock = threading.Lock()
        self._traces: dict[str, dict[str, int]] = {}
        self._part, self._size = 0, 0
        self.path_current = self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._size = self.path.stat().st_size if self.path.exists() else 0
        self.closed = False

    # ---- capture -------------------------------------------------------------------------------------------
    def capture_value(self, value: Any, *, trace_id: str, event_id: str, kind: str) -> Capture:
        """What the trace may keep of ``value`` under the current mode; full mode stores the content locally."""
        keys = sorted(str(k) for k in value) if isinstance(value, dict) else None
        if self.capture == "none":
            return Capture(mode="none", type=type(value).__name__)
        digest, size = digest_value(value, self._salt)  # type: ignore[arg-type]
        cap = Capture(mode=self.capture, digest=digest, size=size, type=type(value).__name__, keys=keys, salt_id=self.salt_id)  # type: ignore[arg-type]
        if self.capture == "full":
            full = self.capture_dir / (self.path.stem + ".full.jsonl")  # type: ignore[operator]
            line = json.dumps({"trace_id": trace_id, "event_id": event_id, "kind": kind, "value": value}, default=str, ensure_ascii=False) + "\n"
            with self._lock, open(full, "ab") as f:
                f.write(line.encode("utf-8"))
                f.flush()
            cap = cap.model_copy(update={"ref": f"{full.name}#{event_id}:{kind}"})
        return cap

    def digest_text(self, text: str) -> tuple[str | None, int]:
        """(digest, length) for free text such as a plan step; (None, length) when capture is none."""
        if self.capture == "none":
            return None, len(text.encode("utf-8"))
        return digest_value(text, self._salt)  # type: ignore[arg-type]

    # ---- events --------------------------------------------------------------------------------------------
    def start_trace(self, trace_id: str, *, adapter: str, framework: str, framework_version: str | None, coverage: dict[str, str],
                    tagger_version: str | None = None, rules_version: str | None = None, package_version: str | None = None) -> HeaderEvent:
        if trace_id in self._traces:
            raise TraceError(f"trace {trace_id} already started")
        header = build_event(HeaderEvent, {"framework_version": "verified"}, trace_id=trace_id, adapter=adapter, framework=framework,
                             framework_version=framework_version, coverage=coverage, capture=self.capture, tagger_version=tagger_version,
                             rules_version=rules_version, salt_id=self.salt_id, package_version=package_version)
        self._traces[trace_id] = {"events": 0, "bytes": 0, "dropped": 0, "seq": 0}
        self._append(header, bypass_limits=True)
        return header  # type: ignore[return-value]

    def write(self, event: TraceEvent) -> bool:
        """Append one event. Returns False when the trace limit dropped it."""
        if self.closed:
            raise TraceError("writer is closed")
        st = self._traces.get(event.trace_id)
        if st is None:
            raise TraceError(f"no trace.header written for trace {event.trace_id}; call start_trace first")
        return self._append(event)

    def close_trace(self, trace_id: str) -> None:
        st = self._traces.get(trace_id)
        if st and st["dropped"]:
            marker = TraceTruncated(trace_id=trace_id, dropped_events=st["dropped"], reason="trace limit", final=True)
            self._append(marker, bypass_limits=True)
        self._sync()

    def close(self) -> None:
        for t in list(self._traces):
            self.close_trace(t)
        self.closed = True

    def _shrink(self, d: dict[str, Any]) -> dict[str, Any]:
        def cut(v: Any) -> Any:
            if isinstance(v, str) and len(v) > 200:
                return v[:200]
            if isinstance(v, dict):
                return {k: cut(x) for k, x in v.items()}
            if isinstance(v, list):
                return [cut(x) for x in v]
            return v
        d = cut(d)
        d["truncated"] = True
        for k in ("params", "tools_offered", "declared", "keys", "flags", "rule_ids", "usage"):
            if len(json.dumps(d, ensure_ascii=False).encode()) <= self.max_event_bytes:
                break
            if k in d:
                d[k] = None if k != "rule_ids" else []
            for sub in d.values():
                if isinstance(sub, dict) and k in sub:
                    sub[k] = None
        return d

    def _append(self, event: TraceEvent, bypass_limits: bool = False) -> bool:
        with self._lock:
            st = self._traces[event.trace_id]
            if event.seq is None:
                event = event.model_copy(update={"seq": st["seq"]})
            d = dump_event(event)
            line = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(line) > self.max_event_bytes:
                line = json.dumps(self._shrink(d), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            line += b"\n"
            if not bypass_limits and (st["events"] >= self.max_trace_events or st["bytes"] + len(line) > self.max_trace_bytes):
                st["dropped"] += 1
                if st["dropped"] == 1:
                    first = TraceTruncated(trace_id=event.trace_id, dropped_events=1, reason="trace limit")
                    first = first.model_copy(update={"seq": st["seq"]})
                    self._raw(json.dumps(dump_event(first), ensure_ascii=False, separators=(",", ":")).encode() + b"\n")
                    st["seq"] += 1
                return False
            self._raw(line)
            st["events"] += 1
            st["bytes"] += len(line)
            st["seq"] = max(st["seq"], (event.seq or 0)) + 1
            return True

    def _raw(self, line: bytes) -> None:
        if self._size and self._size + len(line) > self.max_file_bytes:
            self._sync()
            self._part += 1
            self.path_current = self.path.parent / f"{self.path.stem}.{self._part}{self.path.suffix}"
            self._size = 0
        target = self.path_current
        fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line)
            if self._fsync:
                os.fsync(fd)
        finally:
            os.close(fd)
        self._size += len(line)

    def _sync(self) -> None:
        target = self.path_current
        if target.exists():
            fd = os.open(target, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)


def read_trace(path: str | Path) -> Iterator[TraceEvent]:
    """Typed events from a trace file and its rotated parts."""
    for p in iter_trace_files(path):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield parse_event(line)
