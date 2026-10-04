// Runs the script of rater_form.html against a minimal DOM shim (no browser, no network) and prints the observed behaviour as JSON.
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const dataText = html.match(/id="items-data" type="application\/json">([\s\S]*?)<\/script>/)[1].replace(/<\\\//g, "</");
const DATA = JSON.parse(dataText);
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

class Text { constructor(t) { this.data = t; } get textContent() { return this.data; } }
class El {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.children = []; this.listeners = {}; this._text = ""; this.value = ""; this.checked = false; this.disabled = false; this.className = ""; this.style = {}; this.id = ""; this.href = ""; this.download = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "id") this.id = String(v); if (k === "value") this.value = String(v); if (k === "class") this.className = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); }
  set textContent(t) { this.children = []; this._text = String(t); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  dispatch(t, target) { (this.listeners[t] || []).forEach((f) => f({ target: target || this })); }
  click() {}
  scrollIntoView() { scrolled.push(this.id); }
  all() { return [this].concat(...this.children.map((c) => (c.all ? c.all() : []))); }
  querySelector(sel) {
    const tag = sel.match(/^[a-z]+/)[0]; const conds = [...sel.matchAll(/\[([a-z-]+)="([^"]*)"\]/g)].map((m) => [m[1], m[2]]);
    return this.all().find((e) => e !== this && e.tag === tag && conds.every(([k, v]) => (k === "value" ? e.value === v : e.attrs[k] === v))) || null;
  }
}
const scrolled = [], downloads = [];
function makeEnv(storage) {
  const ids = ["rater", "progress", "download", "next", "status", "warn", "choose", "list"];
  const root = new El("body"); const reg = {};
  ids.forEach((i) => { const e = new El(i === "rater" ? "select" : "div"); e.id = i; reg[i] = e; root.appendChild(e); });
  const dataEl = new El("script"); dataEl.id = "items-data"; dataEl._text = dataText; reg["items-data"] = dataEl; root.appendChild(dataEl);
  const document = {
    getElementById(id) { return root.all().find((e) => e.id === id) || null; },
    createElement(t) { const e = new El(t); if (t === "a") downloads.push(e); return e; },
    createTextNode(t) { return new Text(t); }, body: root,
  };
  const window = { localStorage: { getItem: (k) => (k in storage ? storage[k] : null), setItem: (k, v) => { storage[k] = String(v); } }, scrollTo() {} };
  class Blob { constructor(parts, opts) { this.text = parts.join(""); this.type = opts.type; } }
  const URLshim = { createObjectURL(b) { downloads.blob = b; return "blob:x"; }, revokeObjectURL() {} };
  new Function("document", "window", "Blob", "URL", "setTimeout", script)(document, window, Blob, URLshim, (f) => {});
  return { document, window, el: (i) => document.getElementById(i) };
}
const storage = {};
function choose(env, rater) { const r = env.el("rater"); r.value = rater; r.dispatch("change"); }
function items(env) { return env.el("list").children; }
function answer(env, id, label, conf, note) {
  const box = env.document.getElementById("it-" + id);
  if (label) { const r = box.querySelector(`input[name="label-${id}"][value="${label}"]`); r.checked = true; env.el("list").dispatch("change", r); }
  if (conf) { const c = box.querySelector(`input[name="conf-${id}"][value="${conf}"]`); c.checked = true; env.el("list").dispatch("change", c); }
  if (note != null) { const t = env.document.getElementById("note-" + id); t.value = note; env.el("list").dispatch("input", t); }
}
const out = {};
let env = makeEnv(storage);
out.beforeChoice = { progress: env.el("progress").textContent, downloadDisabled: env.el("download").disabled, items: items(env).length };
choose(env, "R1");
const order1 = items(env).map((b) => b.id.slice(3));
out.afterR1 = { items: order1.length, progress: env.el("progress").textContent, downloadDisabled: env.el("download").disabled, anyChecked: env.el("list").all().filter((e) => e.tag === "input" && e.checked).length,
  labelTexts: [...new Set(env.el("list").all().filter((e) => e.tag === "label").map((e) => e.textContent.trim()))].filter((t) => /^(read_only|state_changing|irreversible):/.test(t)),
  confTexts: [...new Set(env.el("list").all().filter((e) => e.tag === "label").map((e) => e.textContent.trim()))].filter((t) => /^[123]:/.test(t)),
  noteBoxes: env.el("list").all().filter((e) => e.tag === "textarea").length, ids: [...order1].sort() };
choose(env, "R2"); const order2 = items(env).map((b) => b.id.slice(3)); choose(env, "R1");
out.orders = { r1StableOnReselect: JSON.stringify(items(env).map((b) => b.id.slice(3))) === JSON.stringify(order1), r1VersusR2Differ: JSON.stringify(order1) !== JSON.stringify(order2), r2Count: order2.length, r2Progress: "" };
const labels = ["read_only", "state_changing", "irreversible"];
order1.slice(0, 103).forEach((id, i) => answer(env, id, labels[i % 3], String((i % 3) + 1), i === 0 ? 'has, comma "quote"\nnewline' : null));
out.at103 = { progress: env.el("progress").textContent, downloadDisabled: env.el("download").disabled };
answer(env, order1[103], "irreversible", null, null);
out.labelOnly = { downloadDisabled: env.el("download").disabled, progress: env.el("progress").textContent };
answer(env, order1[103], null, "2", null);
out.complete = { downloadDisabled: env.el("download").disabled, progress: env.el("progress").textContent };
env.el("download").dispatch("click");
const a = downloads.filter((d) => d.tag === "a").pop();
out.download = { filename: a && a.download, csv: downloads.blob && downloads.blob.text, type: downloads.blob && downloads.blob.type };
// resume in a new page load with the same storage
const env2 = makeEnv(storage); choose(env2, "R1");
out.resume = { progress: env2.el("progress").textContent, downloadDisabled: env2.el("download").disabled, checked: env2.el("list").all().filter((e) => e.tag === "input" && e.checked).length, firstNote: env2.document.getElementById("note-" + order1[0]).value };
const env3 = makeEnv(storage); choose(env3, "R2");
out.otherRater = { progress: env3.el("progress").textContent, downloadDisabled: env3.el("download").disabled };
const env4 = makeEnv({}); choose(env4, "R1"); const nx = env4.el("next"); const before = scrolled.length; nx.dispatch("click");
out.nextButton = { scrolledTo: scrolled[before] === "it-" + order1[0] };
console.log(JSON.stringify(out));
