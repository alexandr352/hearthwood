"""The page: one static, self-contained HTML file, rebuilt from the home after every read and analysis.

No server and no model writes it. Open ~/.hearthwood/log.html in a browser; reload after a command.

A card number on the page opens that card in a panel. The page carries the cards it mentions, whole,
as JSON beside the board's section, and the panel's script builds every node with textContent: a
card's text is shown, never run. Every other card on the board is carried as a stub (key, title,
state, column, link), so a card number met anywhere in the panel, a description included, opens.
"""

import html
import json
import re

from . import __version__, criteria, guide, home, reading

CSS = """
:root{--bg:#f6f4ee;--panel:#fff;--ink:#22231f;--mute:#6b6c62;--line:#e1ddd2;--green:#2f7d4f;--amber:#b47b10;--red:#b8412d;--accent:#55743a;--chip:#eef0e6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#151613;--panel:#1e201b;--ink:#e9e8e0;--mute:#9a9b8f;--line:#33352e;--green:#58b07c;--amber:#d9a441;--red:#e0654e;--accent:#93b76c;--chip:#2a2d25}}
:root[data-theme=dark]{--bg:#151613;--panel:#1e201b;--ink:#e9e8e0;--mute:#9a9b8f;--line:#33352e;--green:#58b07c;--amber:#d9a441;--red:#e0654e;--accent:#93b76c;--chip:#2a2d25}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;transition:padding-right .18s ease}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:6px}
h1{font-size:22px;margin:0}h1 span{color:var(--accent)}h1 small{color:var(--mute);font-weight:400;font-size:13px;margin-left:8px}
h2{font-size:18px;margin:36px 0 12px}h2 .where{color:var(--mute);font-weight:400;font-size:13px;margin-left:6px;word-break:break-all}
h3{margin:0;font-size:16px}
.mute{color:var(--mute)}.small{font-size:13px}
.tools{display:flex;gap:8px;flex-wrap:wrap}
button.theme,a.theme{background:none;border:1px solid var(--line);color:var(--mute);border-radius:8px;padding:4px 10px;cursor:pointer;font:13px system-ui,sans-serif;text-decoration:none;line-height:normal}
button.theme:hover,a.theme:hover{color:var(--ink);border-color:var(--mute)}
.nextstep{background:color-mix(in srgb,var(--accent) 9%,var(--panel));border:1px solid color-mix(in srgb,var(--accent) 45%,var(--line));border-radius:10px;padding:12px 14px;margin:14px 0}
.nextstep .hint{color:var(--mute);font-size:13px;margin-top:4px}
.nlabel{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);margin-right:6px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;margin:14px 0 8px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;color:var(--mute);font-size:13px}
.tile b{display:block;color:var(--ink);font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:10px 0}
.card p{margin:8px 0}.card h3{display:inline}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:baseline}
.badge{display:inline-block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;padding:2px 7px;border-radius:99px;border:1px solid var(--line);color:var(--mute);line-height:1.4;white-space:nowrap}
.badge.high,.badge.disagree,.badge.rejected{color:var(--red);border-color:var(--red)}
.badge.medium{color:var(--amber);border-color:var(--amber)}
.badge.info,.badge.agree,.badge.approved{color:var(--green);border-color:var(--green)}
.chip{display:inline-block;font-size:11px;padding:1px 7px;border-radius:99px;border:1px solid var(--line);color:var(--mute);white-space:nowrap}
.chip.closed{color:var(--green);border-color:var(--green)}.chip.open{color:var(--ink);border-color:var(--ink)}
.keys{font-size:13px;margin-top:4px}
a{color:var(--accent)}code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--chip);padding:0 4px;border-radius:4px}
.id{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--mute)}
pre{white-space:pre-wrap;word-break:break-word;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
details>summary{cursor:pointer;list-style:none;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}details>summary::-webkit-details-marker{display:none}details>summary::before{content:'▸';color:var(--mute);flex:none}details[open]>summary::before{content:'▾'}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line)}
button.key{font:inherit;color:var(--accent);background:none;border:0;padding:0;cursor:pointer;text-decoration:underline;text-underline-offset:2px}
button.key:hover,button.key:focus-visible{color:var(--ink)}
#panel{position:fixed;top:0;right:0;bottom:0;width:min(400px,100vw);background:var(--panel);border-left:1px solid var(--line);
box-shadow:-4px 0 24px rgba(0,0,0,.18);transform:translateX(105%);transition:transform .18s ease;overflow-y:auto;z-index:10;padding:16px 18px 40px}
#panel.open{transform:none}
#panel header{display:flex;align-items:flex-start;gap:10px;position:sticky;top:-16px;margin:-16px -18px 8px;padding:16px 18px 10px;background:var(--panel);border-bottom:1px solid var(--line);z-index:1}
#panel h2{margin:0;font-size:16px;line-height:1.35;flex:1}
#panel .close{background:none;border:1px solid var(--line);border-radius:8px;color:var(--mute);cursor:pointer;font-size:13px;line-height:1;padding:5px 9px}
#panel .close:hover{color:var(--ink);border-color:var(--mute)}
#panel dl{display:grid;grid-template-columns:max-content 1fr;gap:3px 12px;font-size:13px;margin:12px 0}
#panel dt{color:var(--mute)}#panel dd{margin:0;overflow-wrap:anywhere}
#panel .desc{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;border-top:1px solid var(--line);padding-top:10px;margin-top:10px}
#panel h3{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:16px 0 4px}
@media (min-width:1100px){body.panel-open{padding-right:400px}body.panel-open #panel{box-shadow:none}}
@media (prefers-reduced-motion:reduce){#panel,body{transition:none}}
"""

E = html.escape

JS = r"""
(function(){
var P=document.getElementById('panel'),data={},last=null,WIDE=matchMedia('(min-width:1100px)');
document.querySelectorAll('script.cards').forEach(function(s){try{data[s.dataset.board]=JSON.parse(s.textContent)}catch(e){}});
var boards=Object.keys(data);
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function txt(x){return document.createTextNode(x)}
function card(b,k){return (data[b]||{})[k]}
function key(b,k,extra){var c=card(b,k);if(!c)return txt(k+(extra||''));var x=el('button','key',k);x.type='button';x.dataset.key=k;
  x.title=c.title||'';var s=el('span');s.appendChild(x);if(extra)s.appendChild(txt(extra));return s}
function keys(b,ks){var s=el('span');(ks||[]).forEach(function(k,i){if(i)s.appendChild(txt(', '));s.appendChild(key(b,k))});return s}
function row(dl,label,node){if(!node)return;dl.appendChild(el('dt',null,label));var d=el('dd');d.appendChild(typeof node==='string'?txt(node):node);dl.appendChild(d)}
function linked(b,text){var d=el('div','desc'),re=/#\d+|[A-Z][A-Z0-9_]*-\d+/g,at=0,m;
  while((m=re.exec(text))){var before=m.index?text.charAt(m.index-1):'',after=text.charAt(m.index+m[0].length);
    if(/[\w#-]/.test(before)||/[\w-]/.test(after)||!card(b,m[0]))continue;
    if(m.index>at)d.appendChild(txt(text.slice(at,m.index)));d.appendChild(key(b,m[0]));at=m.index+m[0].length}
  if(at<text.length)d.appendChild(txt(text.slice(at)));return d}
function day(x){return x?String(x).slice(0,10):''}
function state(c){return c.state+(c.close_reason?' ('+String(c.close_reason).replace('_',' ')+')':'')}
function hashOf(b,k){return 'card='+(boards.length>1?encodeURIComponent(b)+'/':'')+encodeURIComponent(k)}
function parse(){var h=location.hash.slice(1);if(h.indexOf('card=')!==0)return null;h=h.slice(5);var i=h.indexOf('/'),b,k;
  if(boards.length>1&&i>0){b=decodeURIComponent(h.slice(0,i));k=decodeURIComponent(h.slice(i+1))}
  else{k=decodeURIComponent(h);b=boards.filter(function(x){return card(x,k)})[0]}
  return b&&card(b,k)?[b,k]:null}
function show(b,k){var c=card(b,k);if(!c)return;P.textContent='';P.dataset.board=b;
  var hd=el('header');var h=el('h2',null,k+' '+(c.title||''));h.id='panel-title';hd.appendChild(h);
  var x=el('button','close','close');x.type='button';x.setAttribute('aria-label','Close');x.onclick=close;hd.appendChild(x);P.appendChild(hd);
  var chips=el('div','row');chips.appendChild(el('span','chip '+(c.state==='closed'?(c.close_reason==='completed'?'closed':''):'open'),state(c)));[c.column,c.kind].concat(c.labels||[]).forEach(function(v){if(v)chips.appendChild(el('span','chip',v))});P.appendChild(chips);
  if(c.stub){P.appendChild(el('p','mute small','The page carries in full only the cards it mentions; this card\'s description is not on it.'))}
  else{var dl=el('dl');
    row(dl,'parent',c.parent?key(b,c.parent):null);
    row(dl,'sub-items',c.children&&c.children.length?keys(b,c.children):null);
    row(dl,'blocked by',c.blocked_by&&c.blocked_by.length?keys(b,c.blocked_by):null);
    row(dl,'written dependencies',c.depends_in_text&&c.depends_in_text.length?keys(b,c.depends_in_text):null);
    row(dl,'blocking',c.blocking&&c.blocking.length?keys(b,c.blocking):null);
    if(c.prs&&c.prs.length){var ps=el('span');c.prs.forEach(function(p,i){if(i)ps.appendChild(txt(', '));
      var t=(p.number?'#'+p.number+' ':'')+p.state+(p.draft?' (draft)':'');
      if(/^https?:\/\//.test(p.url||'')){var a=el('a',null,t);a.href=p.url;a.rel='noopener';ps.appendChild(a)}else ps.appendChild(txt(t))});row(dl,'pull requests',ps)}
    if(c.assignees)row(dl,'assignees',c.assignees.join(', ')||'-');
    row(dl,'milestone',c.milestone||null);
    row(dl,'created',day(c.created));row(dl,'updated',day(c.updated));row(dl,'closed',day(c.closed)||null);
    row(dl,'comments',c.comments?String(c.comments):null);
    P.appendChild(dl);
    if(c.similar&&c.similar.length){P.appendChild(el('h3',null,'Reads like'));var ul=el('div','small');
      c.similar.forEach(function(m,i){if(i)ul.appendChild(txt(' · '));var o=card(b,m[0]);
        ul.appendChild(key(b,m[0],' '+Number(m[1]).toFixed(2)+(o&&o.state&&o.state!=='open'?' ('+o.state+')':'')))});
      P.appendChild(ul);P.appendChild(el('p','mute small','A search, not a verdict: close matches are often related work.'))}
    P.appendChild(el('h3',null,'Description'));P.appendChild(linked(b,(c.body||'').trim()||'(empty)'))}
  if(/^https?:\/\//.test(c.url||'')){var a=el('a',null,/^https:\/\/github\.com\//.test(c.url)?'Open on GitHub':'Open in the tracker');
    a.href=c.url;a.rel='noopener';var pp=el('p','small');pp.appendChild(a);P.appendChild(pp)}
  P.classList.add('open');document.body.classList.add('panel-open');P.setAttribute('aria-hidden','false');P.scrollTop=0;x.focus()}
function close(){if(!P.classList.contains('open'))return;P.classList.remove('open');document.body.classList.remove('panel-open');P.setAttribute('aria-hidden','true');
  if(location.hash.indexOf('#card=')===0)location.hash='';if(last&&document.contains(last))last.focus();last=null}
function sync(){var r=parse();if(r)show(r[0],r[1]);else close()}
document.addEventListener('click',function(e){var t=e.target.closest?e.target.closest('button.key'):null;
  if(t){e.preventDefault();var sec=P.contains(t)?P:t.closest('[data-board]');var b=sec?sec.dataset.board:boards[0];
    if(!P.contains(t))last=t;var h='#'+hashOf(b,t.dataset.key);if(location.hash===h)sync();else location.hash=h;return}
  if(P.classList.contains('open')&&!P.contains(e.target)&&!WIDE.matches)close()});
document.addEventListener('keydown',function(e){if(e.key==='Escape')close()});
window.addEventListener('hashchange',sync);
sync();
})();
"""


def _keys(keys, items, ref):
    """Card numbers as buttons that open the panel; each one shown is recorded in `ref`."""
    out = []
    for k in keys[:20]:
        if k in items:
            ref.add(k)
            out.append(f'<button type=button class=key data-key="{E(k)}">{E(k)}</button>')
        else:
            out.append(E(k))
    return " ".join(out) + (f' <span class=mute>+{len(keys) - 20}</span>' if len(keys) > 20 else "")


KEY = re.compile(r"#\d+|[A-Z][A-Z0-9_]*-\d+")


def _prose(text, items, ref):
    """Escaped text in which every whole-word number of a real card on the board is a button that opens it.
    The text is cut around each number and every piece escaped on its own, so no text becomes markup.
    The same rule as the panel's descriptions: LAN-2 inside LAN-20, xLAN-2 or #LAN-2 stays text."""
    text = text or ""
    out, at = [], 0
    for m in KEY.finditer(text):
        k = m.group(0)
        before = text[m.start() - 1] if m.start() else ""
        after = text[m.end():m.end() + 1]
        if (before and re.match(r"[\w#-]", before)) or (after and re.match(r"[\w-]", after)) or k not in items:
            continue
        out.append(E(text[at:m.start()]))
        ref.add(k)
        out.append(f'<button type=button class=key data-key="{E(k)}">{E(k)}</button>')
        at = m.end()
    out.append(E(text[at:]))
    return "".join(out)


CARD_FIELDS = ("key", "title", "state", "close_reason", "column", "kind", "labels", "parent", "children", "blocked_by",
               "blocking", "created", "updated", "closed", "url", "body", "comments", "milestone")


def card_data(items, ref, similar, people):
    """What the panel shows: the cards in `ref` whole, every other card on the board as a stub, so any card
    number the panel meets, in a field or in a description, opens something."""
    cards = {}
    for k in sorted(ref):
        it = items[k]
        c = {f: it.get(f) for f in CARD_FIELDS}
        c["depends_in_text"] = (it.get("fields") or {}).get("depends_in_text", [])
        c["prs"] = [{"number": p.get("number"), "state": p.get("state"), "draft": p.get("draft"),
                     "url": p.get("url") or ""} for p in it.get("prs") or []]
        c["similar"] = similar.get(k, [])
        if people:
            c["assignees"] = it.get("assignees") or []
        cards[k] = c
    for k in sorted(set(items) - set(cards)):
        it = items[k]
        cards[k] = {"key": k, "title": it.get("title"), "state": it.get("state"), "column": it.get("column"),
                    "close_reason": it.get("close_reason"), "url": it.get("url"), "stub": True}
    return cards


def embed(obj):
    """JSON safe inside a script element: no "<" survives, so no text can close the element."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def board_section(h, b):
    snap = b.latest_snapshot()
    d = b.latest_analysis()
    parts = [f"<h2>{E(b.name)}<span class=where>{E(b.source)} · {E(b.where)}</span></h2>"]
    if not snap:
        return parts + ["<p class=mute>Not read yet: <code>manager read</code>.</p>"]
    items = {i["key"]: i for i in json.loads(snap.read_text(encoding="utf-8"))["items"]}
    ref = set()
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
        parts.append(f"<h2>What needs attention</h2><div class=card>{_prose(r.get('summary', ''), items, ref)}</div>")
        for n, a in enumerate(r.get("attention") or [], 1):
            v = verdicts.get(f"A{n}")
            parts.append(f"<div class=card><div class=row><span class=id>A{n}</span><h3>{_prose(a['title'], items, ref)}</h3>"
                         + (f"<span class=badge>{E(a['confidence'])} confidence</span>" if a.get('confidence') else "")
                         + (f"<span class='badge {E(v['verdict'])}'>{E(v['verdict'])}</span>" if v else "")
                         + f"</div><div class=keys>{_keys(a.get('keys', []), items, ref)}</div><p>{_prose(a['why'], items, ref)}</p>"
                         f"<p class=small><b>Next step:</b> {_prose(a['next_step'], items, ref)}</p></div>")
        qs = r.get("questions") or []
        if qs:
            parts.append("<h2>Questions</h2>")
            for n, q in enumerate(qs, 1):
                v = verdicts.get(f"Q{n}")
                parts.append(f"<div class=card><div class=row><span class=id>Q{n}</span><span class=badge>for {E(q.get('for', ''))}</span>"
                             f"{_prose(q['question'], items, ref)}</div>"
                             + (f"<p class=small><b>Answered:</b> {E(v.get('answer', ''))}</p>" if v else "") + "</div>")
        try:
            props = json.loads((d / "proposals.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            props = []
        if props:
            parts.append("<h2>Proposals <span class='mute small'>nothing is written to the board; approving records your decision</span></h2>")
            for p in props:
                parts.append(f"<div class=card><div class=row><span class=id>{E(p['id'])}</span><span class=badge>{E(p['action'])}</span>"
                             f"<span class='badge {E(p.get('status', 'proposed'))}'>{E(p.get('status', 'proposed'))}</span>{_keys(p.get('keys', []), items, ref)}</div>"
                             f"<p>{_prose(p['change'], items, ref)}</p><p class='mute small'>{_prose(p['why'], items, ref)}</p></div>")
    elif (d / "reading-broken.json").exists() or (d / "reading-failed.txt").exists():
        parts.append("<p class=mute>The reading did not complete for this analysis; the facts below stand alone.</p>")
    else:
        parts.append("<p class=mute>Facts only (no reading): <code>manager analyze</code> adds one.</p>")
    if facts["ready"]:
        parts.append(f"<h2>Ready to start <span class='mute small'>{len(facts['ready'])}</span></h2>"
                     f"<div class=card>{_keys(facts['ready'], items, ref)}</div>")
    parts.append("<h2>Findings</h2>")
    for f in facts["findings"]:
        if f["rule"] == "ready":
            continue
        v = verdicts.get(f["id"])
        parts.append(f"<details class=card><summary><span class=row><span class='badge {E(f['severity'])}'>{E(f['severity'])}</span>"
                     f"<span>{_prose(f['title'], items, ref)}</span><span class=id>{E(f['id'])}</span>"
                     + (f"<span class='badge {E(v['verdict'])}'>{E(v['verdict'])}</span>" if v else "")
                     + f"</span></summary><p>{_prose(f['says'], items, ref)}</p><div class=keys>{_keys(f['keys'], items, ref)}</div>"
                     + (f"<p class='mute small'>Your reason: {E(v['why'])}</p>" if v and v.get("why") else "")
                     + "</details>")
    people = bool(b.settings["rules"].get("people"))
    cards = card_data(items, ref, facts.get("similar") or {}, people)
    parts.append(f"<script type=application/json class=cards data-board=\"{E(b.name)}\">{embed(cards)}</script>")
    return parts


def build(h=None):
    h = h or home.home_dir()
    cmd, why = guide.next_step(h)
    body = [f"<div class=top><h1>hearth<span>wood</span><small>version {E(__version__)} · built {E(home.now_iso())}</small></h1>"
            "<span class=tools><a class=theme href=#criteria>criteria</a><a class=theme href=#calls>model calls</a>"
            "<button class=theme onclick=\"var r=document.documentElement,d=r.dataset.theme==='dark'||(!r.dataset.theme&&"
            "matchMedia('(prefers-color-scheme: dark)').matches);r.dataset.theme=d?'light':'dark'\">theme</button></span></div>",
            f"<div class=nextstep><span class=nlabel>next</span><code>{E(cmd)}</code><div class=hint>{E(why)}</div></div>"]
    bs = home.boards(h)
    if not bs:
        body.append("<p>No board yet. <code>manager connect github</code> or <code>manager connect markdown &lt;folder&gt;</code>.</p>")
    for b in bs:
        body.append(f"<section class=board data-board=\"{E(b.name)}\">")
        body += board_section(h, b)
        body.append("</section>")
    crit = (h / "criteria.md").read_text(encoding="utf-8") if (h / "criteria.md").exists() else ""
    body.append(f"<h2 id=criteria>Your criteria</h2><pre>{E(crit.strip() or '(none yet)')}</pre>")
    runs = home.read_jsonl(h / "runs.jsonl")[-10:]
    if runs:
        rows = "".join(f"<tr><td>{E(str(r.get('at', '')))}</td><td>{E(str(r.get('board', '')))}</td><td>{E(str(r.get('label', '')))}</td>"
                       f"<td>{E(str(r.get('model', '')))}</td><td>{E(str(r.get('seconds', '')))} s</td>"
                       f"<td>{'$%.2f' % r['cost_usd'] if isinstance(r.get('cost_usd'), (int, float)) else '-'}</td>"
                       f"<td>{E(str(r.get('error') or ''))}</td></tr>" for r in reversed(runs))
        total = sum(r.get("cost_usd") or 0 for r in home.read_jsonl(h / "runs.jsonl"))
        body.append(f"<h2 id=calls>Model calls <span class='mute small'>all time ${total:.2f}, API-equivalent</span></h2>"
                    f"<table><tr><th>when</th><th>board</th><th>call</th><th>model</th><th>time</th><th>cost</th><th></th></tr>{rows}</table>")
    page = ("<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>hearthwood</title><style>{CSS}</style></head><body><main>" + "\n".join(body) + "</main>"
            "<aside id=panel role=dialog aria-modal=false aria-labelledby=panel-title aria-hidden=true></aside>"
            f"<script>{JS}</script></body></html>")
    out = h / "log.html"
    out.write_text(page, encoding="utf-8")
    return out
