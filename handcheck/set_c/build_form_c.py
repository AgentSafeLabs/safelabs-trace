"""Builds rater_form_c.html (set C) from handcheck_c_items.csv, controls_c.csv and the accepted guide text. Adapted from 1b_rater_packet/build_form.py (unchanged). Reads no key, result or labelled file. Create-only: never overwrites."""

from __future__ import annotations

import csv
import html
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
STAGING = HERE.parent  # _release-staging
FIELDS = ["item_id", "tool_name", "tool_description", "arguments_summary"]


def read_items(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return [{k: r[k] for k in FIELDS} for r in csv.DictReader(f)]


def inline(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)


def guide_html(guide: str) -> str:
    """Definitions, decision rules and worked examples, word for word from the accepted guide; the notes about files, the key and the design are left out."""
    sec = {m.group(1): m.group(2) for m in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", guide, re.S | re.M)}
    defs_key = next(k for k in sec if k.startswith("Definitions"))
    defs = [l[2:] for l in sec[defs_key].splitlines() if l.startswith("- ")]
    rules = [re.sub(r"^\d+\.\s*", "", l) for l in sec["Decision rules"].splitlines() if re.match(r"^\d+\.", l)]
    ex_rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in sec[next(k for k in sec if k.startswith("Worked examples"))].splitlines() if l.startswith("| `")]
    out = ["<h3>What each label means</h3><ul>" + "".join(f"<li>{inline(d)}</li>" for d in defs) + "</ul>",
           "<h3>Decision rules</h3><ol>" + "".join(f"<li>{inline(r)}</li>" for r in rules) + "</ol>",
           "<h3>Worked examples</h3><table><thead><tr><th>tool</th><th>description</th><th>arguments</th><th>label</th><th>why</th></tr></thead><tbody>"
           + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in ex_rows) + "</tbody></table>",
           "<h3>Notes</h3><p>Write a note when your confidence is 1 (guess), when you chose the more severe of two readings, or when the description and the arguments disagree. "
           "Never put anything sensitive in a note; describe the item by what it does.</p>"]
    assert len(defs) == 3 and len(rules) == 5 and len(ex_rows) == 3, (len(defs), len(rules), len(ex_rows))
    return "\n".join(out)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Action labelling form (set C)</title>
<style>
  body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; margin: 0; color: #1b1b1b; background: #f6f6f4; line-height: 1.45; }
  header { position: sticky; top: 0; z-index: 5; background: #ffffff; border-bottom: 1px solid #cfcfca; padding: 10px 16px; }
  header h1 { font-size: 1.05rem; margin: 0 0 6px 0; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; }
  .bar label { font-weight: 600; }
  button { font-size: 0.95rem; padding: 6px 12px; border-radius: 6px; border: 1px solid #5b5b57; background: #ffffff; cursor: pointer; }
  button:disabled { opacity: 0.45; cursor: not-allowed; }
  button.primary { background: #1f5fbf; color: #ffffff; border-color: #1f5fbf; }
  main, details, .note { max-width: 880px; margin: 14px auto; padding: 0 16px; }
  details { background: #ffffff; border: 1px solid #cfcfca; border-radius: 8px; padding: 10px 16px; }
  summary { cursor: pointer; font-weight: 700; }
  table { border-collapse: collapse; width: 100%; font-size: 0.92rem; }
  th, td { border: 1px solid #cfcfca; padding: 5px 7px; text-align: left; vertical-align: top; }
  code { background: #eeeeea; padding: 0 3px; border-radius: 3px; }
  .item { background: #ffffff; border: 1px solid #cfcfca; border-radius: 8px; padding: 12px 16px; margin: 14px 0; }
  .item.done { border-left: 6px solid #2e8b57; }
  .item h2 { font-size: 0.95rem; margin: 0 0 8px 0; color: #444; }
  .field { margin: 2px 0; } .field span { font-weight: 600; display: inline-block; min-width: 7.2em; }
  fieldset { border: 0; padding: 0; margin: 10px 0 0 0; } legend { font-weight: 600; padding: 0; }
  fieldset label { display: block; margin: 3px 0; cursor: pointer; }
  textarea { width: 100%; box-sizing: border-box; min-height: 52px; font: inherit; margin-top: 4px; }
  #status { font-size: 0.92rem; } #warn { color: #a33; font-size: 0.9rem; }
  @media (max-width: 600px) { .field span { display: block; } }
</style>
</head>
<body>
<header>
  <h1>Action labelling form (set C)</h1>
  <div class="bar">
    <label for="rater">Rater ID</label>
    <select id="rater"><option value="">(choose)</option><option value="R1">R1</option><option value="R2">R2</option></select>
    <span id="progress">Answered 0 of 0</span>
    <button type="button" id="next">Jump to next unanswered</button>
    <button type="button" id="download" class="primary" disabled>Download my answers</button>
  </div>
  <div id="status"></div><div id="warn"></div>
</header>
<details id="guide" open>
<summary>Guide: what the labels mean, rules, examples (click to open or close)</summary>
<p>For each action below, decide what it does to the world if it really ran. Pick one label, say how sure you are, and add a note if needed. Work alone. There are no trick questions.</p>
@@GUIDE@@
</details>
<div class="note" id="choose">Choose your Rater ID above to see the items. Your answers are saved in this browser automatically; use the same browser and do not clear its data until you have downloaded your file.</div>
<main id="list"></main>
<script id="items-data" type="application/json">@@DATA@@</script>
<script>
/* PURE-START */
function hashString(s) { var h = 2166136261 >>> 0; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; } return h >>> 0; }
function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; var t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function orderFor(ids, raterId) {
  var a = ids.slice().sort(); var rnd = mulberry32(hashString("safelabs-hand-check-c:" + raterId));
  for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(rnd() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; }
  return a;
}
function csvEscape(v) { v = String(v == null ? "" : v).replace(/\r?\n/g, " "); return /[",]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
function isComplete(ids, answers) { for (var i = 0; i < ids.length; i++) { var x = answers[ids[i]]; if (!x || !x.label || !x.conf) return false; } return true; }
function buildCsv(ids, answers) {
  var lines = ["item_id,human_label,confidence,note"]; var sorted = ids.slice().sort();
  for (var i = 0; i < sorted.length; i++) { var x = answers[sorted[i]] || {}; lines.push([sorted[i], x.label || "", x.conf || "", x.note || ""].map(csvEscape).join(",")); }
  return lines.join("\n") + "\n";
}
/* PURE-END */
(function () {
  var ITEMS = JSON.parse(document.getElementById("items-data").textContent);
  var IDS = ITEMS.map(function (x) { return x.item_id; });
  var BY_ID = {}; ITEMS.forEach(function (x) { BY_ID[x.item_id] = x; });
  var LABELS = [["read_only", "read_only: only looks"], ["state_changing", "state_changing: changes, can be undone"], ["irreversible", "irreversible: cannot be undone"]];
  var CONFS = [["1", "1: guess"], ["2", "2: fairly sure"], ["3", "3: certain"]];
  var raterEl = document.getElementById("rater"), listEl = document.getElementById("list"), progEl = document.getElementById("progress");
  var dlEl = document.getElementById("download"), nextEl = document.getElementById("next"), statusEl = document.getElementById("status"), warnEl = document.getElementById("warn");
  var chooseEl = document.getElementById("choose");
  var rater = "", answers = {}, order = [], storageOk = true;

  function storageKey() { return "safelabs_trace_hand_check_c_v1_" + rater; }
  function load() { answers = {}; try { var raw = window.localStorage.getItem(storageKey()); if (raw) answers = JSON.parse(raw) || {}; } catch (e) { storageOk = false; } }
  function save() { try { window.localStorage.setItem(storageKey(), JSON.stringify(answers)); } catch (e) { storageOk = false; } warnEl.textContent = storageOk ? "" : "Autosave is not available in this browser: download your answers before you close the page."; }
  function el(tag, attrs, text) { var e = document.createElement(tag); for (var k in (attrs || {})) e.setAttribute(k, attrs[k]); if (text != null) e.textContent = text; return e; }

  function render() {
    listEl.textContent = "";
    order.forEach(function (id, n) {
      var it = BY_ID[id], box = el("section", { "class": "item", id: "it-" + id });
      box.appendChild(el("h2", {}, "Item " + (n + 1) + " of " + order.length + " (" + id + ")"));
      [["Tool", it.tool_name], ["Description", it.tool_description], ["Arguments", it.arguments_summary]].forEach(function (p) {
        var f = el("div", { "class": "field" }); f.appendChild(el("span", {}, p[0] + ":")); f.appendChild(document.createTextNode(" " + p[1])); box.appendChild(f);
      });
      var fs = el("fieldset"); fs.appendChild(el("legend", {}, "What does it do?"));
      LABELS.forEach(function (l) { var lab = el("label"); var r = el("input", { type: "radio", name: "label-" + id, value: l[0] }); r.setAttribute("data-id", id); r.setAttribute("data-kind", "label"); lab.appendChild(r); lab.appendChild(document.createTextNode(" " + l[1])); fs.appendChild(lab); });
      box.appendChild(fs);
      var fc = el("fieldset"); fc.appendChild(el("legend", {}, "How sure are you?"));
      CONFS.forEach(function (c) { var lab = el("label"); var r = el("input", { type: "radio", name: "conf-" + id, value: c[0] }); r.setAttribute("data-id", id); r.setAttribute("data-kind", "conf"); lab.appendChild(r); lab.appendChild(document.createTextNode(" " + c[1])); fc.appendChild(lab); });
      box.appendChild(fc);
      var nl = el("label", {}, "Note (optional)"); nl.setAttribute("for", "note-" + id); box.appendChild(nl);
      var ta = el("textarea", { id: "note-" + id }); ta.setAttribute("data-id", id); ta.setAttribute("data-kind", "note"); box.appendChild(ta);
      listEl.appendChild(box);
      var a = answers[id] || {};
      if (a.label) box.querySelector('input[name="label-' + id + '"][value="' + a.label + '"]').checked = true;
      if (a.conf) box.querySelector('input[name="conf-' + id + '"][value="' + a.conf + '"]').checked = true;
      if (a.note) ta.value = a.note;
      box.className = "item" + (a.label && a.conf ? " done" : "");
    });
    refresh();
  }
  function answered() { return order.filter(function (id) { var a = answers[id]; return a && a.label && a.conf; }).length; }
  function refresh() {
    var n = answered(), total = order.length, complete = total > 0 && isComplete(order, answers);
    progEl.textContent = "Answered " + n + " of " + total;
    dlEl.disabled = !complete; nextEl.disabled = total === 0 || complete;
    statusEl.textContent = !rater ? "" : complete ? "All items answered. You can download your answers." : (total - n) + " item(s) still need a label and a confidence.";
    order.forEach(function (id) { var a = answers[id], b = document.getElementById("it-" + id); if (b) b.className = "item" + (a && a.label && a.conf ? " done" : ""); });
  }
  listEl.addEventListener("change", function (e) {
    var t = e.target, id = t.getAttribute("data-id"); if (!id) return;
    answers[id] = answers[id] || {};
    if (t.getAttribute("data-kind") === "label") answers[id].label = t.value; else if (t.getAttribute("data-kind") === "conf") answers[id].conf = t.value;
    save(); refresh();
  });
  listEl.addEventListener("input", function (e) {
    var t = e.target; if (t.getAttribute("data-kind") !== "note") return;
    var id = t.getAttribute("data-id"); answers[id] = answers[id] || {}; answers[id].note = t.value; save();
  });
  nextEl.addEventListener("click", function () {
    for (var i = 0; i < order.length; i++) { var a = answers[order[i]]; if (!a || !a.label || !a.conf) { document.getElementById("it-" + order[i]).scrollIntoView({ block: "center" }); return; } }
  });
  dlEl.addEventListener("click", function () {
    if (!isComplete(order, answers)) return;
    var blob = new Blob([buildCsv(IDS, answers)], { type: "text/csv;charset=utf-8" });
    var url = URL.createObjectURL(blob), a = document.createElement("a");
    a.href = url; a.download = "rater_" + rater + "_labels_c.csv"; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); document.body.removeChild(a); }, 1000);
  });
  raterEl.addEventListener("change", function () {
    rater = raterEl.value;
    if (!rater) { order = []; answers = {}; listEl.textContent = ""; chooseEl.style.display = ""; refresh(); return; }
    chooseEl.style.display = "none"; load(); order = orderFor(IDS, rater); render(); save();
    window.scrollTo(0, 0);
  });
  refresh();
})();
</script>
</body>
</html>
"""


def main() -> int:
    out = HERE / "rater_form_c.html"
    items = read_items(HERE / "handcheck_c_items.csv") + read_items(HERE / "controls_c.csv")
    assert len(items) == 104 and len({i["item_id"] for i in items}) == 104
    guide = (STAGING / "1b_handcheck" / "labelling_guide.md").read_text(encoding="utf-8")
    data = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    with open(out, "x", encoding="utf-8") as f:  # create-only
        f.write(PAGE.replace("@@GUIDE@@", guide_html(guide)).replace("@@DATA@@", data))
    print(f"wrote {out.name}: {len(items)} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
