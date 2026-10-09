"""Evidence check: no 41-character window of any rater note, and none of the text columns of the key, may occur in any file of this folder. Reads the local-only files in memory, prints counts only (never any text)."""
import csv
import sys
from pathlib import Path

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parent.parent
HOME = Path.home()
sources = []
for r in ("R1", "R2"):
    with open(HOME / f"Downloads/rater_{r}_labels_main_answers_VOID1.csv", newline="", encoding="utf-8") as f:
        sources += [(f"{r} note", row["note"]) for row in csv.DictReader(f)]
with open(HOME / "Desktop/Workspace/AgentSafeLabs/evidence/main_answers_sheets/KEY_DO_NOT_SHARE_main_answers.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        sources += [(f"key {k}", v) for k, v in row.items() if v]
LEN = 41
windows = {}
for name, s in sources:
    s = " ".join(s.split())
    for i in range(0, max(0, len(s) - LEN + 1)):
        windows.setdefault(s[i:i + LEN], name)
files = [p for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "sha256.txt" and "__pycache__" not in p.parts]
hits = 0
for p in files:
    text = " ".join(p.read_text(encoding="utf-8", errors="replace").split())
    n = sum(1 for w in windows if w in text)
    hits += n
    if n:
        print("MATCH in", p.relative_to(OUT), n)
longest = max((len(" ".join(s.split())) for _, s in sources), default=0)
print(f"checked {len(files)} files against {len(windows)} windows of {LEN} characters from {len(sources)} rater-note and key cells (longest cell {longest} characters): {hits} matches")
sys.exit(1 if hits else 0)
