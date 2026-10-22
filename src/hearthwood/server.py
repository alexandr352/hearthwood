"""`manager ui`: the page and a chat with the spirit, served on this machine only.

It listens on 127.0.0.1, never on the network. Each start makes a random key and prints a link
carrying it; the page sets a cookie from it, and every API call must also carry the key in a
header, which a page on another site cannot send. A request whose Host is not this server's is
refused (that stops DNS-rebinding tricks), and the page is served with a content security policy
that allows nothing from anywhere else.

The chat is the same spirit as `manager chat`: the same fence, the same memory, the same doctrine,
and one ongoing session that the "new" button starts afresh. Without `manager ui` the page is the
static ~/.hearthwood/log.html, and it still works.
"""

import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
import threading
import time
import webbrowser
import os
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import re

from . import claude, criteria, home, spirit, sprints, worklog

KEY = secrets.token_urlsafe(24)
CHAT_LOCK = threading.Lock()
MAX_BODY = 64 * 1024
HISTORY_KEEP = 300
CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; "
       "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def spirit_dir(h):
    return h / "spirit"


def session_path(h):
    return spirit_dir(h) / "chat-session"


def history_path(h):
    return spirit_dir(h) / "chat-history.jsonl"


def history_add(h, kind, text):
    """The conversation as the page shows it, so a reload brings it back."""
    with open(history_path(h), "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": kind, "text": text}) + "\n")


def history_read(h):
    try:
        lines = history_path(h).read_text(encoding="utf-8").splitlines()[-HISTORY_KEEP:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# --- runs started from the page ------------------------------------------------------

RUN_LOCK = threading.Lock()


def run_path(h):
    return h / "run.json"


def run_state(h):
    """What the page last started: {"kind", "board", "pid", "started", "running", "code", "ended", "log"}."""
    try:
        st = json.loads(run_path(h).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"running": False}
    if st.get("running"):
        try:
            os.kill(int(st["pid"]), 0)
        except (OSError, ValueError, KeyError, TypeError):
            st.update(running=False, code=st.get("code"), ended=st.get("ended") or home.now_iso())
    return st


def start_run(h, board, kind, view="all-all"):
    """In the background, one at a time: kind 'facts' reads the board and works out the facts (`manager analyze
    --read --facts-only`); kind 'reading' has Claude read the latest copy for a view (`manager analyze --view`)."""
    if kind not in ("facts", "reading"):
        raise ValueError("a run is facts or reading")
    if view not in sprints.VIEWS:
        raise ValueError(f"a view is one of {', '.join(sprints.VIEWS)}")
    names = [b.name for b in home.boards(h)]
    if board not in names:
        raise ValueError(f"no board named {board!r}")
    with RUN_LOCK:
        if run_state(h).get("running"):
            raise RuntimeError("something is already running; wait until it is done")
        logs = h / "runs"
        logs.mkdir(exist_ok=True)
        log = logs / f"{home.stamp()}-{board}-{kind}.log"
        cmd = [sys.executable, "-m", "hearthwood", "analyze", "-b", board] + (
            ["--read", "--facts-only"] if kind == "facts" else ["--view", view])
        here = str(Path(__file__).resolve().parent.parent)         # the same hearthwood as this server, however installed
        env = dict(os.environ, HEARTHWOOD_HOME=str(h),
                   PYTHONPATH=os.pathsep.join(x for x in (here, os.environ.get("PYTHONPATH", "")) if x))
        f = open(log, "w", encoding="utf-8")
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        st = {"kind": kind, "board": board, "view": view, "pid": p.pid, "started": home.now_iso(), "running": True, "log": str(log)}
        run_path(h).write_text(json.dumps(st), encoding="utf-8")

    def wait():
        code = p.wait()
        f.close()
        done = dict(st, running=False, code=code, ended=home.now_iso())
        run_path(h).write_text(json.dumps(done), encoding="utf-8")
    threading.Thread(target=wait, daemon=True).start()
    return st


def stamp(h):
    """Changes whenever something the page shows changes: a read, an analysis, a verdict, a call."""
    m = 0.0
    paths = [h / "criteria.md", h / "runs.jsonl", h / "verdicts.jsonl", h / "run.json", h / "config.toml"]
    for b in home.boards(h):
        paths += [b.dir / "board.toml", b.snapshots, b.analyses]
        d = b.latest_analysis()
        if d:
            paths += [d, d / "proposals.json", d / "reading.json"]
        paths += list(b.dir.glob("*.jsonl"))
    for p in paths:
        try:
            m = max(m, p.stat().st_mtime)
        except OSError:
            pass
    return str(m)


def describe_tool(name, inp, h=None):
    """One line per tool call; a path inside the hearthwood home is shown relative to it."""
    inp = inp or {}
    def short(text):
        text = str(text)
        if h is not None:
            root = str(h).rstrip("/")
            text = text.replace(root + "/", "").replace(root, ".")
        return text[:160]
    if name == "Bash":
        return "$ " + short(inp.get("command", ""))
    for k in ("file_path", "path", "pattern"):
        if inp.get(k):
            return f"{name.lower()} {short(inp[k])}"
    return name


NAME = re.compile(r"^[A-Za-z0-9#._-]{1,64}$")


def locate(h, board, analysis):
    """(board home, analysis folder) for names the page sent, or ValueError. Only an analysis folder that
    exists under that board is ever touched."""
    if not (isinstance(board, str) and NAME.match(board) and isinstance(analysis, str) and NAME.match(analysis)):
        raise ValueError("a board and an analysis are needed")
    b = next((x for x in home.boards(h) if x.name == board), None)
    if b is None:
        raise ValueError(f"no board {board!r}")
    d = b.analyses / analysis
    if not d.is_dir():
        raise ValueError(f"no analysis {analysis!r} for board {board}")
    return b, d


def decide(h, body):
    """Record what the person decided on the page, through the code `manager verdict`, `approve` and `reject` use.
    Writes only the home's own records, never the board."""
    b, d = locate(h, body.get("board"), body.get("analysis"))
    target, act = str(body.get("target") or ""), str(body.get("act") or "")
    why, answer = str(body.get("why") or "").strip()[:500], str(body.get("answer") or "").strip()[:500]
    kind = criteria.resolve(d, target)[0]
    if act in ("disagree", "reject") and not why:
        raise ValueError("say why, in a line: the reason is what becomes a criterion")
    if kind == "proposals":
        if act not in ("approve", "reject"):
            raise ValueError("a proposal is approved or rejected")
        criteria.set_proposal(d, target, "approved" if act == "approve" else "rejected", why)
        row = criteria.record(h, b, d, target, "agree" if act == "approve" else "disagree", why=why)
    elif kind == "questions":
        if act != "answer":
            raise ValueError("a question takes an answer")
        row = criteria.record(h, b, d, target, "", answer=answer)
    else:
        if act not in ("agree", "disagree"):
            raise ValueError("a point or a finding is agreed or disagreed with")
        row = criteria.record(h, b, d, target, act, why=why)
    worklog.build(h)
    return row


def context_for(about, h=None):
    """What the person pointed at, said to the spirit before their message."""
    if not isinstance(about, dict):
        return ""
    if about.get("ask") == "item" and h is not None:
        try:
            b, d = locate(h, about.get("board"), about.get("analysis"))
            target = str(about.get("target") or "")
            kind, _, keys, text = criteria.resolve(d, target)
        except ValueError:
            return ""
        how = {"proposals": f"`manager approve {target} --why \"...\"` or `manager reject {target} --why \"...\"`",
               "questions": f"`manager verdict {target} --answer \"...\"`"}.get(
            kind, f"`manager verdict {target} agree|disagree --why \"...\"`")
        what = {"attention": "point", "questions": "question", "proposals": "proposal"}.get(kind, "finding")
        return (f"[The person wants to discuss {what} {target} of analysis {d.name} on board {b.name}: \"{text}\". "
                f"It is in ../boards/{b.name}/analyses/{d.name}/ (reading.json, facts.json, proposals.json), and the cards "
                f"it names ({', '.join(keys[:12]) or 'none'}) are under items/ there. Read them, explain what matters, and "
                f"propose the concrete next step with the exact text they would post. When they decide, record it with "
                f"{how} -b {b.name} --analysis {d.name}, in their words, and show the command.]\n\n")
    if about.get("ask") == "next":
        return ("[The person clicked the page's next step. Run `manager next`, and help them take that step: do it "
                "for them where they ask, and show the command each time.]\n\n")
    if about.get("ask") == "card":
        board, key = str(about.get("board") or "")[:64], str(about.get("key") or "")[:64]
        return (f"[The person is looking at card {key} of board {board}. The latest analysis folder of that board "
                f"holds it whole: ../boards/{board}/analyses/<latest>/items/.]\n\n")
    return ""


class Handler(BaseHTTPRequestHandler):
    server_version = "hearthwood"
    h = None
    cfg = None

    def log_message(self, fmt, *args):
        pass

    # --- guards ----------------------------------------------------------------

    def host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def cookie_key(self):
        c = SimpleCookie(self.headers.get("Cookie") or "")
        return c["hw"].value if "hw" in c else None

    def authed(self, api=False):
        if not self.host_ok():
            return False
        if api:
            return secrets.compare_digest(self.headers.get("X-HW-Key") or "", KEY)
        return secrets.compare_digest(self.cookie_key() or "", KEY)

    def send(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    # --- routes ----------------------------------------------------------------

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/" and q.get("k") and self.host_ok():
            if not secrets.compare_digest(q["k"][0], KEY):
                return self.send(HTTPStatus.FORBIDDEN, "wrong key: use the link `manager ui` printed")
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Set-Cookie", f"hw={KEY}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Location", "/")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            return
        if url.path == "/":
            if not self.authed():
                return self.send(HTTPStatus.FORBIDDEN, "open the link `manager ui` printed (it carries the key)")
            page = worklog.render(self.h, ui=True).replace(worklog.CHAT, CHAT_UI.replace("{{KEY}}", KEY), 1)
            return self.send(HTTPStatus.OK, page, "text/html; charset=utf-8", {"Content-Security-Policy": CSP})
        if url.path == "/api/stamp":
            if not self.authed(api=True):
                return self.send(HTTPStatus.FORBIDDEN, "no")
            return self.send(HTTPStatus.OK, json.dumps({"stamp": stamp(self.h)}), "application/json")
        if url.path == "/api/card":
            if not self.authed(api=True):
                return self.send(HTTPStatus.FORBIDDEN, "no")
            c = worklog.full_card(self.h, (q.get("board") or [""])[0], (q.get("key") or [""])[0])
            if c is None:
                return self.send(HTTPStatus.NOT_FOUND, "no such card")
            return self.send(HTTPStatus.OK, json.dumps(c, ensure_ascii=False), "application/json")
        if url.path == "/api/run":
            if not self.authed(api=True):
                return self.send(HTTPStatus.FORBIDDEN, "no")
            st = run_state(self.h)
            if st.get("log"):
                try:
                    st["tail"] = Path(st["log"]).read_text(encoding="utf-8", errors="replace")[-600:]
                except OSError:
                    pass
            return self.send(HTTPStatus.OK, json.dumps(st), "application/json")
        if url.path == "/api/history":
            if not self.authed(api=True):
                return self.send(HTTPStatus.FORBIDDEN, "no")
            return self.send(HTTPStatus.OK, json.dumps(history_read(self.h)), "application/json")
        return self.send(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self):
        url = urlparse(self.path)
        if not self.authed(api=True):
            return self.send(HTTPStatus.FORBIDDEN, "no")
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self.send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too long")
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self.send(HTTPStatus.BAD_REQUEST, "bad json")
        if url.path == "/api/new":
            for f in (session_path(self.h), history_path(self.h)):
                try:
                    f.unlink()
                except FileNotFoundError:
                    pass
            return self.send(HTTPStatus.OK, '{"ok":true}', "application/json")
        if url.path == "/api/chat":
            return self.chat(str(body.get("message") or "").strip(), body.get("about"))
        if url.path == "/api/run":
            try:
                st = start_run(self.h, str(body.get("board") or ""), str(body.get("kind") or ""), str(body.get("view") or "all-all"))
            except ValueError as e:
                return self.send(HTTPStatus.BAD_REQUEST, str(e))
            except RuntimeError as e:
                return self.send(HTTPStatus.CONFLICT, str(e))
            return self.send(HTTPStatus.OK, json.dumps(st), "application/json")
        if url.path == "/api/model":
            try:
                home.set_model(self.h, str(body.get("role") or ""), str(body.get("model") or ""))
            except ValueError as e:
                return self.send(HTTPStatus.BAD_REQUEST, str(e))
            return self.send(HTTPStatus.OK, '{"ok":true}', "application/json")
        if url.path == "/api/decide":
            try:
                row = decide(self.h, body)
            except ValueError as e:
                return self.send(HTTPStatus.BAD_REQUEST, str(e))
            return self.send(HTTPStatus.OK, json.dumps({"verdict": row["verdict"], "target": row["target"]}), "application/json")
        return self.send(HTTPStatus.NOT_FOUND, "not found")

    # --- the chat ----------------------------------------------------------------

    def chat(self, message, about):
        if not message:
            return self.send(HTTPStatus.BAD_REQUEST, "empty")
        if not CHAT_LOCK.acquire(blocking=False):
            return self.send(HTTPStatus.CONFLICT, "the spirit is still answering the last message")
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.stream_spirit(message, about)
        finally:
            CHAT_LOCK.release()

    def emit(self, obj):
        try:
            self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def stream_spirit(self, message, about):
        h, sdir = self.h, spirit_dir(self.h)
        home.refresh_spirit(h)
        prompt = context_for(about, h) + message
        sid_path = session_path(h)
        sid = sid_path.read_text().strip() if sid_path.exists() else None
        tail, env = spirit.launch(h)
        bin_ = shutil.which(self.cfg["claude"]["bin"]) or self.cfg["claude"]["bin"]
        cmd = [bin_, "--print", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
               "--model", self.cfg["models"]["spirit"], *tail]
        if sid:
            cmd += ["--resume", sid]
        t0 = time.time()
        try:
            p = subprocess.Popen(cmd, cwd=sdir, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, bufsize=1)
        except FileNotFoundError:
            return self.emit({"type": "error", "text": f"the Claude Code CLI was not found: {bin_}"})
        history_add(h, "me", message)
        final, said, err = None, "", ""
        with p:                                        # closes the pipes and waits, whatever happens
            p.stdin.write(prompt)
            p.stdin.close()
            for line in p.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                t = ev.get("type")
                if t == "stream_event":
                    e = ev.get("event") or {}
                    d = e.get("delta") or {}
                    if e.get("type") == "content_block_delta" and d.get("type") == "text_delta":
                        said += d.get("text", "")
                        self.emit({"type": "text", "text": d.get("text", "")})
                elif t == "assistant":
                    for block in (ev.get("message") or {}).get("content") or []:
                        if block.get("type") == "tool_use":
                            if said.strip():
                                history_add(h, "spirit", said)
                                said = ""
                            shown = describe_tool(block.get("name"), block.get("input"), h)
                            history_add(h, "tool", shown)
                            self.emit({"type": "tool", "text": shown})
                elif t == "rate_limit_event":
                    claude.note_usage(ev.get("rate_limit_info"))
                elif t == "result":
                    final = ev
            if final is None:
                err = (p.stderr.read() or "").strip()[:400]
        if said.strip():
            history_add(h, "spirit", said)
        if final is None:
            return self.emit({"type": "error", "text": err or f"the spirit exited with {p.returncode}"})
        new_sid = final.get("session_id")
        if new_sid:
            tmp = sid_path.with_name(f".{sid_path.name}.tmp")
            tmp.write_text(new_sid + "\n")
            os.replace(tmp, sid_path)
        cost, basis = claude.CostLedger(sdir / "session-cost.json").cost(new_sid, final.get("total_cost_usd"), bool(sid))
        rec = {"at": home.now_iso(), "board": "", "label": "spirit (ui)", "model": self.cfg["models"]["spirit"],
               "seconds": round(time.time() - t0, 1), "cost_usd": cost, "cost_basis": basis,
               "error": str(final.get("result"))[:200] if final.get("is_error") else None}
        home.append_jsonl(h / "runs.jsonl", rec)
        if final.get("is_error"):
            self.emit({"type": "error", "text": str(final.get("result"))[:400]})
        history_add(h, "meta", f"${(cost or 0):.3f} · {rec['seconds']}s")
        self.emit({"type": "done", "cost_usd": cost, "seconds": rec["seconds"]})


def serve(port=0, open_browser=True):
    h = home.home_dir()
    if not (h / "config.toml").exists():
        home.init_home(h)
    home.refresh_spirit(h)
    Handler.h = h
    Handler.cfg = home.config(h)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        print(f"manager: cannot listen on 127.0.0.1:{port}: {e.strerror} "
              "(another `manager ui` may be running; omit --port to take a free one)", flush=True)
        return 2
    link = f"http://127.0.0.1:{httpd.server_address[1]}/?k={KEY}"
    print(f"hearthwood is served on this machine only:\n\n  {link}\n\nCtrl-C stops it.", flush=True)
    if open_browser and home.has_browser():
        threading.Timer(0.5, lambda: webbrowser.open(link)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


CHAT_UI = r"""
<aside id=chat aria-label="the spirit">
  <header><b>Spirit</b><span id=chat-cost></span><button type=button id=chat-new title="start a new conversation">new</button><button type=button id=chat-min title="hide" aria-label="hide the spirit">&ndash;</button></header>
  <div id=chat-log><div class="msg sys">Ask about the board, a card, a finding, or what to do next. The spirit reads the home and acts only through <code>manager</code> commands; it never writes to your board.</div></div>
  <div id=chat-about hidden><span></span><button type=button title="clear">&times;</button></div>
  <form id=chat-form><textarea id=chat-in rows=1 placeholder="Ask the spirit&hellip;"></textarea><button class=pill>Send</button></form>
</aside>
<button type=button id=chat-open class=pill hidden>Spirit</button>
<style>
#chat{position:fixed;top:0;right:0;width:400px;height:100vh;background:var(--panel);border-left:1px solid var(--line);display:flex;flex-direction:column;z-index:5}
@media (min-width:1100px){body.ui:not(.chat-hidden){padding-right:400px}body.ui.chat-hidden #chat{display:none}body.ui.panel-open{padding-right:max(400px,var(--pw,400px))}}
@media (max-width:1099px){#chat{width:100%;display:none;z-index:8}body.chat-shown #chat{display:flex}}
#chat header{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--line)}
#chat header b{flex:1}#chat-cost{color:var(--mute);font-size:12px}
#chat header button,#chat-about button{background:none;border:1px solid var(--line);color:var(--mute);border-radius:8px;padding:2px 8px;cursor:pointer;font:13px var(--font)}
#chat-log{flex:1;overflow:auto;padding:12px 14px;display:flex;flex-direction:column;gap:10px}
.msg{white-space:pre-wrap;word-break:break-word;font-size:14px;line-height:1.5}
.msg.me{align-self:flex-end;background:color-mix(in srgb,var(--accent) 14%,var(--panel));border-radius:12px 12px 2px 12px;padding:8px 11px;max-width:85%}
.msg.sys{color:var(--mute);font-size:13px}
.msg.md{white-space:normal}.msg.md p{margin:0 0 8px}.msg.md ul,.msg.md ol{margin:0 0 8px;padding-left:20px}.msg.md li{margin:2px 0}
.msg.md code{font:12.5px var(--font);background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:0 4px}
.mdpre{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 8px;margin:4px 0 8px;overflow-x:auto;white-space:pre}
.msg.md .mdpre code{border:0;padding:0;background:none;border-radius:0}
table.md{border-collapse:collapse;font-size:12.5px;margin:4px 0 8px;width:100%}table.md th,table.md td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left}
table.md th{color:var(--mute);font-weight:600}.msg.err{color:var(--red)}
.tool{font:12px var(--font);color:var(--mute);border-left:2px solid var(--line);padding-left:8px;white-space:pre-wrap;word-break:break-all}
.meta-line{font-size:11px;color:var(--mute)}
#chat-about{display:flex;align-items:center;gap:8px;margin:0 14px;padding:6px 10px;border:1px dashed var(--accent);border-radius:8px;font-size:12px;color:var(--accent)}
#chat-about span{flex:1}
#chat-about[hidden],.pill[hidden]{display:none}
#chat-form{display:flex;align-items:flex-end;gap:8px;padding:12px 16px 16px 14px;border-top:1px solid var(--line)}
#chat-in{flex:1;height:40px;min-height:40px;max-height:120px;resize:none;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:20px;padding:9px 16px;font:14px/20px var(--font);overflow-y:hidden;box-sizing:border-box}
#chat-in:focus{outline:none;border-color:var(--accent)}
.pill{height:40px;min-width:80px;padding:0 18px;border:0;border-radius:20px;background:var(--accent);color:#fff;font:600 14px/40px var(--font);cursor:pointer;box-sizing:border-box}
.pill:disabled{opacity:.5;cursor:wait}
#chat-open{position:fixed;right:16px;bottom:16px;z-index:6}
</style>
<script>
function hwMarkdown(src){
  function esc(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
  function inline(t){return esc(t).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:!?]|$)/g,'$1<i>$2</i>')}
  var out=[],lines=src.replace(/\r/g,'').split('\n'),i=0;
  while(i<lines.length){var l=lines[i];
    if(/^\s*```/.test(l)){var code=[];i++;while(i<lines.length&&!/^\s*```/.test(lines[i])){code.push(lines[i]);i++}i++;
      out.push('<pre class=mdpre><code>'+esc(code.join('\n'))+'</code></pre>');continue}
    if(/^\s*\|/.test(l)){var rows=[];while(i<lines.length&&/^\s*\|/.test(lines[i])){rows.push(lines[i]);i++}
      var cells=function(r){return r.trim().replace(/^\||\|$/g,'').split('|').map(function(c){return c.trim()})};
      var body=rows.filter(function(r){return !/^\s*\|[\s:|-]+\|\s*$/.test(r)});
      var hd=cells(body[0]||'');out.push('<table class=md><thead><tr>'+hd.map(function(c){return '<th>'+inline(c)+'</th>'}).join('')+'</tr></thead><tbody>'+
        body.slice(1).map(function(r){return '<tr>'+cells(r).map(function(c){return '<td>'+inline(c)+'</td>'}).join('')+'</tr>'}).join('')+'</tbody></table>');continue}
    if(/^\s*[-*] /.test(l)){var items=[];while(i<lines.length&&(/^\s*[-*] /.test(lines[i])||(/^\s{2,}\S/.test(lines[i])&&items.length))){
        if(/^\s*[-*] /.test(lines[i]))items.push(lines[i].replace(/^\s*[-*] /,''));else items[items.length-1]+=' '+lines[i].trim();i++}
      out.push('<ul>'+items.map(function(t){return '<li>'+inline(t)+'</li>'}).join('')+'</ul>');continue}
    if(/^\s*\d+\. /.test(l)){var its=[];while(i<lines.length&&/^\s*\d+\. /.test(lines[i])){its.push(lines[i].replace(/^\s*\d+\. /,''));i++}
      out.push('<ol>'+its.map(function(t){return '<li>'+inline(t)+'</li>'}).join('')+'</ol>');continue}
    if(/^#{1,6} /.test(l)){out.push('<p><b>'+inline(l.replace(/^#+ /,''))+'</b></p>');i++;continue}
    if(!l.trim()){i++;continue}
    var para=[];while(i<lines.length&&lines[i].trim()&&!/^\s*(\||[-*] |\d+\. |#{1,6} )/.test(lines[i])){para.push(lines[i]);i++}
    out.push('<p>'+inline(para.join(' '))+'</p>')}
  return out.join('')}
(function(){
var KEY="{{KEY}}",log=document.getElementById('chat-log'),form=document.getElementById('chat-form'),input=document.getElementById('chat-in'),
    aboutBox=document.getElementById('chat-about'),about=null,spent=0,costEl=document.getElementById('chat-cost'),pill=document.getElementById('chat-open'),
    WIDE=matchMedia('(min-width:1100px)'),busy=false;
function add(cls,text){var d=document.createElement('div');d.className=cls;d.textContent=text;log.appendChild(d);log.scrollTop=log.scrollHeight;return d}
function md(node,text){node.className='msg md';node.innerHTML=hwMarkdown(text);if(window.hwLink)window.hwLink(node)}
function visible(){return WIDE.matches?!document.body.classList.contains('chat-hidden'):document.body.classList.contains('chat-shown')}
function paint(){pill.hidden=visible()}
function show(on){if(WIDE.matches){document.body.classList.toggle('chat-hidden',!on);try{localStorage.setItem('hearthwood-chat',on?'1':'0')}catch(e){}}
  else document.body.classList.toggle('chat-shown',on);paint();if(on)setTimeout(fit,0)}
document.getElementById('chat-min').onclick=function(){show(false)};pill.onclick=function(){show(true);input.focus()};
try{if(localStorage.getItem('hearthwood-chat')==='0')document.body.classList.add('chat-hidden')}catch(e){}
WIDE.addEventListener('change',paint);paint();
function setAbout(a){about=a;aboutBox.hidden=!a;if(a)aboutBox.querySelector('span').textContent=a.ask==='next'?'the next step':a.ask==='item'?'about '+a.target:'about card '+a.key+(a.board?' on '+a.board:'')}
aboutBox.querySelector('button').onclick=function(){setAbout(null)};
document.addEventListener('click',function(e){var b=e.target.closest?e.target.closest('button.ask'):null;if(!b)return;
  var a=b.dataset.ask==='next'?{ask:'next'}:b.dataset.ask==='item'?{ask:'item',board:b.dataset.board,analysis:b.dataset.analysis,target:b.dataset.target}
    :{ask:'card',board:b.dataset.board,key:b.dataset.key};setAbout(a);
  var pc=document.querySelector('#panel.open .close');if(pc)pc.click();show(true);input.focus();
  if(!input.value)input.value=a.ask==='next'?'What is the next step, and can you take it with me?':a.ask==='item'?
    'Let\'s discuss '+a.target+': what matters here, and what would you do?':'What should I know about '+a.key+'?';fit()});
document.addEventListener('click',async function(e){var b=e.target.closest?e.target.closest('.acts button.act'):null;if(!b)return;
  var row=b.closest('.acts'),act=b.dataset.act,why=row.querySelector('.whyline');
  if(act==='change'){b.hidden=true;row.querySelector('.choices').hidden=false;return}
  if(act==='disagree'||act==='reject'){row.dataset.pending=act;why.hidden=false;why.querySelector('input').focus();return}
  if(act==='record')act=row.dataset.pending;
  var input2=row.querySelector('input.why'),body={board:row.dataset.board,analysis:row.dataset.analysis,target:row.dataset.target,act:act};
  if(act==='answer')body.answer=input2.value;else if(input2)body.why=input2.value;
  row.querySelectorAll('button').forEach(function(x){x.disabled=true});var old=row.querySelector('.err');if(old)old.remove();
  try{var r=await fetch('/api/decide',{method:'POST',headers:{'X-HW-Key':KEY,'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok)throw new Error(await r.text());location.reload()}
  catch(err){var m=document.createElement('span');m.className='err';m.textContent=err.message||String(err);row.appendChild(m);
    row.querySelectorAll('button').forEach(function(x){x.disabled=false})}});
document.addEventListener('keydown',function(e){var i=e.target;if(!i.classList||!i.classList.contains('why'))return;var row=i.closest('.acts');
  if(e.key==='Enter'){e.preventDefault();var go=row.querySelector('[data-act=record]')||row.querySelector('[data-act=answer]');if(go)go.click()}
  if(e.key==='Escape'&&row.querySelector('.whyline')){row.querySelector('.whyline').hidden=true;delete row.dataset.pending}});
document.getElementById('chat-new').onclick=function(){fetch('/api/new',{method:'POST',headers:{'X-HW-Key':KEY},body:'{}'});log.textContent='';
  add('msg sys','A new conversation. The spirit still remembers what it wrote to its memory.')};
input.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit()}});
function fit(){input.style.height='40px';var hh=Math.min(input.scrollHeight+2,120);input.style.height=(hh>42?hh:40)+'px';input.style.overflowY=input.scrollHeight+2>120?'auto':'hidden'}
input.addEventListener('input',fit);window.addEventListener('resize',fit);setTimeout(fit,0);
form.onsubmit=async function(e){e.preventDefault();var text=input.value.trim();if(!text||busy)return;input.value='';fit();add('msg me',text);
  var btn=form.querySelector('button');btn.disabled=true;busy=true;var out=add('msg','…'),got=false,a=about,raw='';setAbout(null);
  try{var r=await fetch('/api/chat',{method:'POST',headers:{'X-HW-Key':KEY,'Content-Type':'application/json'},body:JSON.stringify({message:text,about:a})});
    if(!r.ok){out.className='msg err';out.textContent=await r.text();return}
    var rd=r.body.getReader(),dec=new TextDecoder(),buf='';
    while(true){var c=await rd.read();if(c.done)break;buf+=dec.decode(c.value,{stream:true});var lines=buf.split('\n');buf=lines.pop();
      lines.forEach(function(l){if(!l)return;var ev=JSON.parse(l);
        if(ev.type==='text'){if(!got){raw='';got=true}raw+=ev.text;md(out,raw)}
        else if(ev.type==='tool'){var t=document.createElement('div');t.className='tool';t.textContent=ev.text;log.insertBefore(t,out);if(got){out=add('msg','');got=false}}
        else if(ev.type==='error'){add('msg err',ev.text)}
        else if(ev.type==='done'){spent+=ev.cost_usd||0;costEl.textContent='$'+spent.toFixed(2)+' this page';add('meta-line','$'+(ev.cost_usd||0).toFixed(3)+' · '+ev.seconds+'s')}
        log.scrollTop=log.scrollHeight})}
    if(!got&&out.textContent==='…')out.remove();
  }catch(err){add('msg err',String(err))}finally{btn.disabled=false;busy=false;input.focus();check()}};
document.querySelectorAll('[data-model-role]').forEach(function(g){g.addEventListener('click',async function(e){
  var x=e.target.closest('button[data-model]');if(!x)return;
  var r=await fetch('/api/model',{method:'POST',headers:{'X-HW-Key':KEY,'Content-Type':'application/json'},
    body:JSON.stringify({role:g.dataset.modelRole,model:x.dataset.model})});
  if(r.ok)g.querySelectorAll('button[data-model]').forEach(function(y){y.setAttribute('aria-pressed',String(y===x))})})});
function runText(st){if(!st||!st.kind)return '';var what=st.kind==='reading'?'reading by Claude':'read of the board';
  if(st.running)return 'Running the '+what+' for '+st.board+' since '+String(st.started).slice(11,16)+' UTC. The page refreshes when it is done.';
  return 'Last: the '+what+' for '+st.board+(st.code===0?' finished at ':' stopped with an error at ')+String(st.ended||'').slice(11,16)+' UTC.'
    +(st.code!==0&&st.tail?' '+st.tail.trim().split('\n').slice(-2).join(' '):'')}
async function runPoll(){try{var st=await (await fetch('/api/run',{headers:{'X-HW-Key':KEY}})).json();
  document.querySelectorAll('.runbox').forEach(function(bx){bx.querySelector('.runstate').textContent=st.board===bx.dataset.board?runText(st):'';
    bx.querySelectorAll('button[data-run]').forEach(function(x){x.disabled=!!st.running})})}catch(e){}}
document.querySelectorAll('.runbox').forEach(function(bx){bx.addEventListener('click',async function(e){var x=e.target.closest('button[data-run]');if(!x)return;
  if(x.dataset.run==='reading'){var line=bx.querySelector('[data-variant]:not([hidden])');
    if(!confirm('Ask Claude to read '+bx.dataset.board+'?\n\n'+(line?line.textContent:'One Claude session with the model chosen above.')))return}
  var view=window.variantOf?variantOf(bx.dataset.board):'all-all';
  var r=await fetch('/api/run',{method:'POST',headers:{'X-HW-Key':KEY,'Content-Type':'application/json'},body:JSON.stringify({board:bx.dataset.board,kind:x.dataset.run,view:view})});
  if(!r.ok)bx.querySelector('.runstate').textContent=await r.text();runPoll()})});
if(document.querySelector('.runbox')){runPoll();setInterval(runPoll,4000)}
window.hwCard=function(b,k){return fetch('/api/card?board='+encodeURIComponent(b)+'&key='+encodeURIComponent(k),
  {headers:{'X-HW-Key':KEY}}).then(function(r){return r.ok?r.json():null}).catch(function(){return null})};
fetch('/api/history',{headers:{'X-HW-Key':KEY}}).then(function(r){return r.json()}).then(function(items){
  items.forEach(function(m){if(m.kind==='me')add('msg me',m.text);else if(m.kind==='tool')add('tool',m.text);
    else if(m.kind==='meta')add('meta-line',m.text);else md(add('msg',''),m.text)});log.scrollTop=log.scrollHeight}).catch(function(){});
var last=null,told=false;async function check(){try{var s=(await (await fetch('/api/stamp',{headers:{'X-HW-Key':KEY}})).json()).stamp;
  if(last!==null&&s!==last){if(!busy&&!input.value.trim())location.reload();else if(!told){told=true;add('msg sys','The board changed: reload the page to see it.')}}
  last=s}catch(e){}}
check();setInterval(check,5000);
})();
</script>
"""
