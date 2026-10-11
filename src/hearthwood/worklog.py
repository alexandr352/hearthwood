"""The page: one static, self-contained HTML file, rebuilt from the home after every read and analysis.

No server and no model writes it. Open ~/.hearthwood/log.html in a browser; reload after a command.
"""

import html
import json

from . import __version__, criteria, home, reading

CSS = """
:root{--bg:#f6f4ee;--panel:#fff;--ink:#22231f;--mute:#6b6c62;--line:#e1ddd2;--green:#2f7d4f;--amber:#b47b10;--red:#b8412d;--accent:#55743a;--chip:#eef0e6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#151613;--panel:#1e201b;--ink:#e9e8e0;--mute:#9a9b8f;--line:#33352e;--green:#58b07c;--amber:#d9a441;--red:#e0654e;--accent:#93b76c;--chip:#2a2d25}}
:root[data-theme=dark]{--bg:#151613;--panel:#1e201b;--ink:#e9e8e0;--mute:#9a9b8f;--line:#33352e;--green:#58b07c;--amber:#d9a441;--red:#e0654e;--accent:#93b76c;--chip:#2a2d25}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:20px 16px 60px}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 16px;margin-bottom:12px}
h1{font-size:20px;margin:0}h1 span{color:var(--accent)}h2{font-size:16px;margin:28px 0 8px}h3{font-size:14px;margin:0}
.mute{color:var(--mute)}.small{font-size:13px}
button.theme{margin-left:auto;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:3px 10px;cursor:pointer}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:22px;font-variant-numeric:tabular-nums}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:8px 0}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:baseline}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:0 8px;font-size:12px;color:var(--mute)}
.sev-high{color:var(--red)}.sev-medium{color:var(--amber)}.sev-low{color:var(--mute)}.sev-info{color:var(--green)}
.v-agree{color:var(--green)}.v-disagree{color:var(--red)}
a{color:var(--accent)}code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--chip);padding:0 4px;border-radius:4px}
pre{white-space:pre-wrap;word-break:break-word;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
details>summary{cursor:pointer}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line)}
"""

E = html.escape


def _keys(keys, items):
    out = []
    for k in keys[:20]:
        it = items.get(k)
        url = (it or {}).get("url") or ""
        out.append(f'<a href="{E(url)}">{E(k)}</a>' if url.startswith("http") else E(k))
    return " ".join(out) + (f' <span class=mute>+{len(keys) - 20}</span>' if len(keys) > 20 else "")


def board_section(h, b):
    snap = b.latest_snapshot()
    d = b.latest_analysis()
    parts = [f"<h2>Board <span>{E(b.name)}</span> <span class='mute small'>{E(b.source)} {E(b.where)}</span></h2>"]
    if not snap:
        return parts + ["<p class=mute>Not read yet: <code>manager read</code>.</p>"]
    items = {i["key"]: i for i in json.loads(snap.read_text(encoding="utf-8"))["items"]}
    if not d or not (d / "facts.json").exists():
        return parts + [f"<p class=mute>Read {E(snap.stem)}; not analysed yet: <code>manager analyze</code>.</p>"]
    facts = json.loads((d / "facts.json").read_text(encoding="utf-8"))
    flow = facts["flow"]
    by_rule = {}
    for f in facts["findings"]:
        by_rule.setdefault(f["rule"], []).append(f)
    blocked = len(by_rule.get("blocked", [])) + len(by_rule.get("blocked-by-parked", []))
    tiles = [("open", flow["open"]), ("ready", len(facts["ready"])), ("blocked", blocked),
             ("not moving", len(by_rule.get("stale", []))), ("finished, 7 days", flow["finished_last_7_days"]),
             ("finished, 30 days", flow["finished_last_30_days"]),
             ("median days to finish", flow["median_days_open_to_finished_30d"] if flow["median_days_open_to_finished_30d"] is not None else "-")]
    parts.append("<div class=tiles>" + "".join(f"<div class=tile><b>{E(str(v))}</b><span class='mute small'>{E(k)}</span></div>"
                                                for k, v in tiles) + "</div>")
    parts.append(f"<p class='mute small'>Analysis {E(d.name)} of the read {E(facts['fetched_at'])}. "
                 + " ".join(E(n) for n in facts.get("notes", [])) + "</p>")
    r = reading.load(d)
    verdicts = {}
    for v in criteria.all_verdicts(h, b.name):
        if v.get("analysis") == d.name or v.get("kind") == "finding":
            verdicts[v["target"] if v.get("kind") != "finding" else v["target"]] = v
    if r:
        parts.append(f"<h2>What needs attention</h2><div class=card>{E(r.get('summary', ''))}</div>")
        for n, a in enumerate(r.get("attention") or [], 1):
            v = verdicts.get(f"A{n}")
            parts.append(f"<div class=card><div class=row><code>A{n}</code><h3>{E(a['title'])}</h3>"
                         f"<span class=chip>{E(a.get('confidence', ''))}</span>"
                         + (f"<span class='chip v-{E(v['verdict'])}'>{E(v['verdict'])}</span>" if v else "")
                         + f"</div><div class=small>{_keys(a.get('keys', []), items)}</div><p>{E(a['why'])}</p>"
                         f"<p class=small><b>Next step:</b> {E(a['next_step'])}</p></div>")
        qs = r.get("questions") or []
        if qs:
            parts.append("<h2>Questions</h2>")
            for n, q in enumerate(qs, 1):
                v = verdicts.get(f"Q{n}")
                parts.append(f"<div class=card><div class=row><code>Q{n}</code><span class=chip>for {E(q.get('for', ''))}</span>"
                             f"{E(q['question'])}</div>"
                             + (f"<p class=small><b>Answered:</b> {E(v.get('answer', ''))}</p>" if v else "") + "</div>")
        try:
            props = json.loads((d / "proposals.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            props = []
        if props:
            parts.append("<h2>Proposals <span class='mute small'>nothing is written to the board; approving records your decision</span></h2>")
            for p in props:
                parts.append(f"<div class=card><div class=row><code>{E(p['id'])}</code><span class=chip>{E(p['action'])}</span>"
                             f"<span class=chip>{E(p.get('status', 'proposed'))}</span>{_keys(p.get('keys', []), items)}</div>"
                             f"<p>{E(p['change'])}</p><p class='mute small'>{E(p['why'])}</p></div>")
    elif (d / "reading-broken.json").exists() or (d / "reading-failed.txt").exists():
        parts.append("<p class=mute>The reading did not complete for this analysis; the facts below stand alone.</p>")
    else:
        parts.append("<p class=mute>Facts only (no reading): <code>manager analyze</code> adds one.</p>")
    if facts["ready"]:
        parts.append(f"<h2>Ready to start <span class='mute small'>{len(facts['ready'])}</span></h2>"
                     f"<div class=card small>{_keys(facts['ready'], items)}</div>")
    parts.append("<h2>Findings</h2>")
    for f in facts["findings"]:
        if f["rule"] == "ready":
            continue
        v = verdicts.get(f["id"])
        parts.append(f"<details class=card><summary><span class=row><code>{E(f['id'])}</code>"
                     f"<span class='chip sev-{E(f['severity'])}'>{E(f['severity'])}</span>{E(f['title'])}"
                     + (f"<span class='chip v-{E(v['verdict'])}'>{E(v['verdict'])}</span>" if v else "")
                     + f"</span></summary><p>{E(f['says'])}</p><div class=small>{_keys(f['keys'], items)}</div>"
                     + (f"<p class='mute small'>Your reason: {E(v['why'])}</p>" if v and v.get("why") else "")
                     + "</details>")
    return parts


def build(h=None):
    h = h or home.home_dir()
    body = [f"<header><h1>hearth<span>wood</span></h1><span class='mute small'>version {E(__version__)} · built {E(home.now_iso())}</span>"
            "<button class=theme onclick=\"var r=document.documentElement,d=r.dataset.theme==='dark'||(!r.dataset.theme&&"
            "matchMedia('(prefers-color-scheme: dark)').matches);r.dataset.theme=d?'light':'dark'\">theme</button></header>"]
    bs = home.boards(h)
    if not bs:
        body.append("<p>No board yet. <code>manager connect github</code> or <code>manager connect markdown &lt;folder&gt;</code>.</p>")
    for b in bs:
        body += board_section(h, b)
    crit = (h / "criteria.md").read_text(encoding="utf-8") if (h / "criteria.md").exists() else ""
    body.append(f"<h2>Your criteria</h2><pre>{E(crit.strip() or '(none yet)')}</pre>")
    runs = home.read_jsonl(h / "runs.jsonl")[-10:]
    if runs:
        rows = "".join(f"<tr><td>{E(str(r.get('at', '')))}</td><td>{E(str(r.get('board', '')))}</td><td>{E(str(r.get('label', '')))}</td>"
                       f"<td>{E(str(r.get('model', '')))}</td><td>{E(str(r.get('seconds', '')))} s</td>"
                       f"<td>{'$%.2f' % r['cost_usd'] if isinstance(r.get('cost_usd'), (int, float)) else '-'}</td>"
                       f"<td>{E(str(r.get('error') or ''))}</td></tr>" for r in reversed(runs))
        total = sum(r.get("cost_usd") or 0 for r in home.read_jsonl(h / "runs.jsonl"))
        body.append(f"<h2>Model calls <span class='mute small'>all time ${total:.2f}, API-equivalent</span></h2>"
                    f"<table><tr><th>when</th><th>board</th><th>call</th><th>model</th><th>time</th><th>cost</th><th></th></tr>{rows}</table>")
    page = ("<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>hearthwood</title><style>{CSS}</style></head><body><main>" + "\n".join(body) + "</main></body></html>")
    out = h / "log.html"
    out.write_text(page, encoding="utf-8")
    return out
