import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_project_metadata_is_private_and_proprietary():
    p = PYPROJECT["project"]
    assert p["name"] == "safelabs-trace" and p["version"] == "0.1.0"
    assert p["license"] == {"text": "Proprietary — all rights reserved, Safe Labs AI Inc."}
    assert not any(c.startswith("License ::") for c in p["classifiers"]) and "Private :: Do Not Upload" in p["classifiers"]
    assert "safelabs-eval>=0.11.2" in p["dependencies"]
    assert "langchain" in p["optional-dependencies"] and any(d.startswith("langchain-core") for d in p["optional-dependencies"]["langchain"])
    assert not any("langchain" in d for d in p["dependencies"])


def test_version_matches_the_package():
    import safelabs_trace
    assert safelabs_trace.__version__ == PYPROJECT["project"]["version"]


def test_gitignore_excludes_captures_salts_and_secrets():
    lines = {l.strip() for l in (ROOT / ".gitignore").read_text().splitlines()}
    assert {"captures/", "*.salt", ".env", "Credential.txt", "__pycache__/", ".venv", ".venv/", "dist/", "build/"} & lines >= {"captures/", "*.salt", ".env", "Credential.txt", "__pycache__/", "dist/", "build/"}
    assert ".venv/" in lines or ".venv" in lines


def test_readme_is_source_available_and_carries_the_exporter_warning():
    text = (ROOT / "README.md").read_text()
    assert text.splitlines()[0] == "# safelabs-trace" and "Source available for research reproducibility" in text and "not an open-source licence" in text
    assert "default trace exporter" in text and "OpenAI Agents SDK" in text and "set_trace_processors" in text
    lic = (ROOT / "LICENSE").read_text()
    assert lic.startswith("Copyright (c) 2026 Safe Labs AI Inc. All rights reserved.") and "NOT an open-source licence" in lic


def test_data_file_ships_with_the_package():
    data = ROOT / "src" / "safelabs_trace" / "data" / "severity_rules.json"
    assert data.exists()
    assert PYPROJECT["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/safelabs_trace"]


def test_importing_the_core_package_imports_no_framework():
    code = ("import sys, safelabs_trace, safelabs_trace.schema, safelabs_trace.severity, safelabs_trace.writer, safelabs_trace.inert_tools, "
            "safelabs_trace.divergence; bad=[m for m in ('langchain_core','langchain','google.adk','agents','crewai','llama_index') if m in sys.modules]; assert not bad, bad")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr


def test_the_tree_has_no_secret_files():
    names = {p.name for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert not names & {".env", "Credential.txt"} and not any(n.endswith(".salt") for n in names)
