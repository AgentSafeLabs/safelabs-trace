import os
import socket

import pytest

KEY_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "SAFELABS_TRACE_SALT")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No internet sockets (AF_UNIX stays for asyncio); no exporter variables and no provider keys or salt in the environment of a test."""
    real = socket.socket

    class GuardSocket(real):
        def __init__(self, family=-1, *a, **k):
            if family in (socket.AF_INET, socket.AF_INET6):
                raise AssertionError("network access attempted in an offline test")
            super().__init__(family, *a, **k)

    def refuse(*a, **k):
        raise AssertionError("network access attempted in an offline test")

    monkeypatch.setattr(socket, "socket", GuardSocket)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    for name in [k for k in os.environ if k.startswith("OTEL_")] + list(KEY_NAMES) + ["OPENAI_AGENTS_DISABLE_TRACING"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", "false")


@pytest.fixture
def openai_sdk(monkeypatch):
    """Isolated OpenAI Agents global state with an exporter that fails the test if it is ever asked to upload (as in safelabs-trace's own tests)."""
    pytest.importorskip("agents")
    from agents.tracing import processors, setup

    uploads = []

    def exploding_export(self, items):
        uploads.append(len(items))
        raise AssertionError("BackendSpanExporter.export was called: a trace would have been uploaded")

    monkeypatch.setattr(processors.BackendSpanExporter, "export", exploding_export)
    monkeypatch.setattr(processors, "_global_exporter", None)
    monkeypatch.setattr(processors, "_global_processor", None)
    monkeypatch.setattr(setup, "GLOBAL_TRACE_PROVIDER", None)
    yield uploads
    assert uploads == [], "the OpenAI exporter was asked to upload"
