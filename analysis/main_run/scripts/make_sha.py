"""sha256 of every output file in this folder (sha256.txt itself excluded)."""
from common import *  # noqa
import hashlib

L = []
for p in sorted(OUT.rglob("*")):
    if p.is_file() and p.name != "sha256.txt" and "__pycache__" not in p.parts and not p.name.endswith(".pyc"):
        L.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(OUT)}")
(OUT / "sha256.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print(len(L), "files hashed")
