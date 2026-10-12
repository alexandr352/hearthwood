"""`manager`: the command line of hearthwood."""

import argparse
import json
import os
import shutil
import sqlite3
import ssl
import urllib.error
import subprocess
import sys
import textwrap
from urllib.parse import urlparse

from . import __version__, criteria, credentials, facts, guide, home, jira_auth, reading, search, snapshot, spirit, worklog
from .adapters import jira


def out(msg=""):
    print(msg, flush=True)


def fail(msg):
    print(f"manager: {msg}", file=sys.stderr)
    return 2


def wrap(text, indent="  "):
    return textwrap.fill(text or "", width=96, initial_indent=indent, subsequent_indent=indent)


def use_system_certificates():
    """Trust what the computer trusts (the Mac's Keychain, Windows' store, Linux's CA files), including a
    company's own certificate where its network inspects secure connections. Without this, Python trusts
    only its own list, and a Python installed from python.org on a Mac trusts nothing until its
    "Install Certificates" step was run."""
    try:
        import truststore
        truststore.inject_into_ssl()
        return True
    except Exception:
        return False


def network_message(e):
    """A network failure, said plainly."""
    reason = getattr(e, "reason", e)
    text = str(reason)
    if "CERTIFICATE_VERIFY_FAILED" in text or isinstance(reason, ssl.SSLCertVerificationError):
        return ("the other side's certificate could not be verified, so nothing was sent. Hearthwood trusts the "
                "certificates your computer trusts; if this persists, your network inspects secure connections "
                "with a certificate this computer does not know. See \"If something goes wrong\" in "
                "docs/start-here.md.")
    return f"the network did not answer ({text}). Check the connection and try again."


def board_of(args):
    return home.resolve_board(getattr(args, "board", None))


def analysis_of(b, args=None):
    name = getattr(args, "analysis", None) if args else None
    if name:
        d = b.analyses / name
        if not d.is_dir():
            raise ValueError(f"no analysis {name!r} for board {b.name}")
        return d
    d = b.latest_analysis()
    if not d:
        raise ValueError(f"board {b.name} has no analysis yet: `manager analyze`")
    return d


def rebuild_log():
    try:
        worklog.build()
    except Exception as e:  # the page must never break a command
        print(f"manager: the page was not rebuilt: {e}", file=sys.stderr)


# --- setting up ------------------------------------------------------------------

def cmd_init(args):
    h, created = home.init_home()
    out(f"home: {h}")
    for p in created:
        out(f"  created {p.relative_to(h) if p != h else '.'}")
    if not created:
        out("  (already set up)")
    out("\nnext: manager connect github --board <name> --repo <owner/repo>")
    out("  or: manager connect demo                               (a made-up board to try it on)")
    return 0


def cmd_connect_github(args):
    home.init_home()
    extra = []
    if args.project:
        extra.append(f"project = {int(args.project)}              # the Projects board's number (in its URL)")
        if args.project_owner:
            extra.append(f'project_owner = "{args.project_owner}"')
    extra.append(f'token = "{args.token_from}"          # credentials | env | gh')
    b = home.add_board(args.board, "github", args.repo, extra="\n".join(extra) + "\n")
    out(f"board {b.name}: GitHub {args.repo}" + (f", Projects board #{args.project}" if args.project else ", issues only"))
    if args.token_from == "credentials":
        out("A read-only token is enough. docs/connecting.md says exactly which permissions to give it.")
        try:
            n = credentials.save_token(b, credentials.ask_token(stdin=args.token_stdin))
        except ValueError as e:
            out(f"  {e}; the board is set up, the token is not.")
            out(f"  try again: manager connect token --board {b.name}")
            return 2
        out(f"  token saved for this board ({n} characters), readable by you alone")
    else:
        out(f"  the token will be taken from {'the ' + credentials.ENV_VAR + ' variable' if args.token_from == 'env' else 'the GitHub CLI'}")
    out(f"  settings: {b.dir / 'board.toml'}  (how your columns are used: check them once)")
    out("\nnext: manager read")
    return 0


def cmd_connect_token(args):
    b = board_of(args)
    n = credentials.save_token(b, credentials.ask_token(stdin=args.token_stdin))
    out(f"token saved for board {b.name} ({n} characters), readable by you alone")
    return 0


def cmd_connect_jira_app(args):
    h, _ = home.init_home()
    if args.secret_stdin or not sys.stdin.isatty():
        secret = sys.stdin.readline().strip()
    else:
        import getpass
        secret = getpass.getpass("Paste the app's client secret (it will not be shown): ").strip()
    jira_auth.save_app(h, args.client_id, secret)
    out(f"Jira app saved in {jira_auth.app_path(h)}, readable by you alone")
    out("\nnext: manager connect jira --board <name>")
    return 0


def _choose(what, options, given, label, names, flag):
    """One of `options`: the one `given` names, the only one, or one the person picks from a list. Never a guess."""
    if given:
        hit = [o for o in options if given.lower() in [n.lower() for n in names(o) if n]]
        if len(hit) == 1:
            return hit[0]
        raise ValueError(f"no {what} {given!r} here; there are: " + ", ".join(label(o) for o in options))
    if len(options) == 1:
        return options[0]
    if not options:
        raise ValueError(f"no {what} can be read with this sign-in")
    if not sys.stdin.isatty():
        raise ValueError(f"more than one {what}; choose with {flag}: " + ", ".join(label(o) for o in options))
    for n, o in enumerate(options, 1):
        out(f"  {n}. {label(o)}")
    pick = input(f"Which {what}? ").strip()
    if pick.isdigit() and 1 <= int(pick) <= len(options):
        return options[int(pick) - 1]
    return _choose(what, options, pick, label, names, flag)


def cmd_connect_jira(args):
    h, _ = home.init_home()
    app = jira_auth.load_app(h)
    if not home.BOARD_NAME.match(args.board):
        return fail("a board name is lowercase letters, digits, '.', '_' or '-', starting with a letter or digit "
                    f"(for example {args.board.lower()!r})")
    existing = next((x for x in home.boards(h) if x.name == args.board), None)
    if existing and not args.again:
        return fail(f"board {args.board} already exists; `--again` signs it in again")
    if args.again and (not existing or existing.source != "jira"):
        return fail(f"no Jira board named {args.board} to sign in again")
    verifier, challenge = jira_auth.new_pkce()
    state = jira_auth.new_state()
    link = jira_auth.authorize_url(app["client_id"], state, challenge)
    out("Open this link, choose your site and allow hearthwood to read it:\n")
    out("  " + link + "\n")
    if not args.paste and home.has_browser():
        import webbrowser
        try:
            webbrowser.open(link)
        except Exception:
            pass
    if args.paste:
        out("After you allow it, the browser lands on an address starting with http://localhost:8768/callback (the page "
            "itself may not open). Copy that whole address.")
        code = jira_auth.code_from(input("Paste it here: "), state)
    else:
        out(f"Waiting for the browser on 127.0.0.1:{jira_auth.PORT} (5 minutes). If the browser runs on another "
            f"machine, forward the port first (ssh -L {jira_auth.PORT}:127.0.0.1:{jira_auth.PORT} <this machine>), or "
            "run this again with --paste.")
        code = jira_auth.wait_for_code(state)
    grant = jira_auth.exchange(app, code, verifier)
    sites = jira_auth.resources(grant["access_token"])
    want = args.site or (existing.settings.get("cloud_id") if existing else "")
    site = _choose("site", sites, want, lambda s: s.get("url", ""),
                   lambda s: [s.get("url", ""), s.get("name", ""), s.get("id", ""), urlparse(s.get("url", "")).netloc], "--site")
    grant.update(cloud_id=site["id"], site_url=site["url"])
    if existing:
        if existing.settings.get("cloud_id") != site["id"]:
            return fail(f"board {existing.name} reads {existing.settings.get('site')}; this sign-in chose {site['url']}")
        jira_auth.save_grant(existing, grant)
        out(f"board {existing.name}: signed in again to {site['url']}")
        return 0
    client = jira.Jira(site["id"], lambda: f"Bearer {grant['access_token']}")
    if args.project:
        project = args.project
    else:
        found = client.get("/rest/api/3/project/search", {"maxResults": 100, "orderBy": "key"}).get("values") or []
        project = _choose("project", found, "", lambda p: f"{p.get('key')} ({p.get('name')})",
                          lambda p: [p.get("key", ""), p.get("name", "")], "--project")["key"]
    board_id, board_note = int(args.board_id or 0), ""
    if not board_id:
        try:
            boards = jira.find_board(client, project)
        except jira.JiraError as e:            # the sign-in is kept: the board is tried again at every read
            boards, board_note = [], str(e)
        if boards:
            board_id = boards[0][0]
            if len(boards) > 1:
                out(f"  project {project} has {len(boards)} boards; using \"{boards[0][1]}\" (#{board_id}). "
                    "Others: " + ", ".join(f"#{i} {n}" for i, n, _ in boards[1:]) + " (set board_id in board.toml)")
    extra = (f"site = {json.dumps(site['url'])}\ncloud_id = {json.dumps(site['id'])}\nproject = {json.dumps(project)}\n"
             f"board_id = {board_id}                 # the board whose columns and order are read; 0 = none\n")
    b = home.add_board(args.board, "jira", f"{site['url']} {project}", extra=extra)
    jira_auth.save_grant(b, grant)
    out(f"board {b.name}: Jira {site['url']}, project {project}" + (f", board #{board_id}" if board_id else ", no board"))
    if board_note:
        out(f"  the board could not be read ({board_note}). Until it can, each card's column is its status; "
            "every `manager read` tries the board again.")
    out(f"  signed in; the sign-in is kept in {jira_auth.grant_path(b)}, readable by you alone")
    out(f"  settings: {b.dir / 'board.toml'}  (how your columns are used: check them once)")
    out("\nnext: manager read")
    return 0


def demo_folder():
    """The demo board's tickets, shipped inside the package."""
    from importlib import resources
    return str(resources.files("hearthwood").joinpath("demo-board"))


def cmd_connect_demo(args):
    home.init_home()
    b = home.add_board(args.board, "markdown", demo_folder())
    out(f"board {b.name}: the demo board, twenty made-up tickets of an imaginary notes app")
    out("\nnext: manager analyze --facts-only     (the facts alone; nothing leaves this machine)")
    return 0


def update_source():
    """'git', 'directory' or '' : where uv installed hearthwood from, read from uv's own receipt."""
    uv = shutil.which("uv")
    if not uv:
        return ""
    p = subprocess.run([uv, "tool", "dir"], capture_output=True, text=True, timeout=30)
    receipt = os.path.join(p.stdout.strip(), "hearthwood", "uv-receipt.toml")
    try:
        text = open(receipt, encoding="utf-8").read()
    except OSError:
        return ""
    return "git" if "git = " in text else "directory" if ("directory = " in text or "path = " in text) else "other"


GIT_SOURCE = "git+https://github.com/alexandr352/hearthwood"
INSTALL = f"uv tool install --python-preference only-managed {GIT_SOURCE}"


def cmd_update(args):
    uv, source = shutil.which("uv"), update_source()
    if not source:
        return fail("hearthwood was not installed with uv here, so it cannot update itself. Install it that way once:\n"
                    f"  {INSTALL}")
    if source == "directory":
        out("hearthwood was installed from a downloaded folder, which does not change by itself. Switch to the")
        out("version on GitHub once, and from then on `manager update` fetches the newest:")
        out(f"  {INSTALL.replace('install', 'install --force', 1)}")
        return 1
    out(f"hearthwood {__version__}: looking for a newer version ...")
    if subprocess.run([uv, "tool", "upgrade", "hearthwood"]).returncode != 0:
        return fail("the update did not complete; what uv said is above")
    m = shutil.which("manager")
    now = subprocess.run([m, "--version"], capture_output=True, text=True).stdout.strip() if m else ""
    out(f"now {now or 'updated'}. Your boards, verdicts and criteria are untouched.")
    return 0


def cmd_connect_markdown(args):
    home.init_home()
    folder = os.path.abspath(os.path.expanduser(args.folder))
    if not os.path.isdir(folder):
        return fail(f"no such folder: {folder}")
    b = home.add_board(args.board, "markdown", folder)
    out(f"board {b.name}: the markdown files in {folder}")
    out("\nnext: manager read")
    return 0


def cmd_disconnect(args):
    """Forget one board: its folder (snapshots, analyses, settings) and its token or Jira sign-in. Your
    criteria and your verdicts stay: they are how you judge, not the board."""
    b = home.resolve_board(args.board)
    snaps = len(list(b.snapshots.glob("*.json"))) if b.snapshots.exists() else 0
    analyses = len([p for p in b.analyses.iterdir() if p.is_dir()]) if b.analyses.exists() else 0
    secrets_ = [p for p in (credentials.token_path(b), jira_auth.grant_path(b)) if p.exists()]
    out(f"board {b.name} ({b.source} {b.where}): {count(snaps, 'snapshot')}, {count(analyses, 'analysis', 'analyses')}"
        + (", and its sign-in" if secrets_ else ""))
    if not args.yes:
        if not sys.stdin.isatty():
            return fail("nothing removed: add --yes to remove it without being asked")
        if input("Remove it from this computer? Nothing on the board itself changes. [y/N] ").strip().lower() not in ("y", "yes"):
            out("nothing removed")
            return 0
    for p in secrets_:
        p.unlink()
    shutil.rmtree(b.dir)
    rebuild_log()
    out(f"board {b.name} removed. Your criteria and verdicts stay.")
    if b.source == "jira":
        out("  To withdraw hearthwood's permission at Atlassian too: your Atlassian account, Connected apps.")
    elif b.source == "github" and b.settings.get("token", "credentials") == "credentials":
        out("  If no other board uses that GitHub token, revoke it on GitHub.")
    return 0


def count(n, word, plural=None):
    return f"{n} {word if n == 1 else plural or word + 's'}"


def cmd_model(args):
    h = home.home_dir()
    cfg = home.config(h)
    if not args.role:
        out(f"reading: {cfg['models']['analyst']}    spirit: {cfg['models']['spirit']}")
        return 0
    if not args.model:
        return fail("say which model: manager model reading opus|sonnet")
    home.set_model(h, args.role, args.model)
    out(f"{args.role}: {args.model} (in {h / 'config.toml'})")
    rebuild_log()
    return 0


def cmd_boards(args):
    bs = home.boards()
    if not bs:
        out("no board yet: manager connect github ... | manager connect markdown <folder>")
    for b in bs:
        snap = b.latest_snapshot()
        out(f"{b.name:16} {b.source:9} {b.where}   last read: {snap.stem if snap else 'never'}")
    return 0


# --- reading and analysing ------------------------------------------------------

def cmd_read(args):
    b = board_of(args)
    out(f"reading {b.name} ({b.source} {b.where}) ...")
    board, path = snapshot.take(b, progress=(lambda n: print(f"\r  {n} items", end="", flush=True)) if sys.stdout.isatty() else None)
    if sys.stdout.isatty():
        print()
    out(f"  {len(board.items)} items, {sum(1 for i in board.items if i.state == 'open')} open -> {path.name}")
    for n in board.notes:
        out(wrap("note: " + n))
    rebuild_log()
    out("\nnext: manager analyze            (facts, then one reading by Claude)")
    out("  or: manager analyze --facts-only  (facts alone, no model call)")
    return 0


def cmd_analyze(args):
    b = board_of(args)
    snap = b.latest_snapshot()
    if args.read or not snap:
        if not snap:
            out("no snapshot yet, reading first")
        board, snap = snapshot.take(b)
    else:
        board = snapshot.load(snap)
    a = facts.Analysis(board, b.settings).run()
    verdicts = criteria.latest_by_target(b.home, b.name)
    d = reading.prepare(b, board, a, verdicts)
    counts = {}
    for f in a.findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    out(f"analysis {d.name} of {snap.stem}: {len(a.findings)} findings "
        f"({', '.join(f'{v} {k}' for k, v in counts.items())}); {len(a.ready)} ready")
    if args.facts_only:
        rebuild_log()
        out(f"  facts: {d / 'facts.md'}")
        out("\nnext: manager show   |   manager review")
        return 0
    cfg = home.config(b.home)
    out(f"reading with {args.model or cfg['models']['analyst']} (one Claude session; it may take a few minutes) ...")
    r, records, status = reading.run(b, d, board, a, model=args.model)
    cost = sum(x.get("cost_usd") or 0 for x in records)
    out(f"  {status}; {sum(x.get('seconds') or 0 for x in records):.0f} s, ${cost:.2f} API-equivalent")
    rebuild_log()
    if r:
        out("")
        show_reading(r, board.by_key())
    out("\nnext: manager review     (agree or disagree, one point at a time)")
    return 0 if r else 1


def show_reading(r, items):
    out(wrap(r.get("summary", ""), ""))
    for n, a in enumerate(r.get("attention") or [], 1):
        out(f"\nA{n}  {a['title']}  [{a.get('confidence')}]")
        out(wrap(", ".join(f"{k} {items[k].title[:60]}" if k in items else k for k in a.get("keys", [])[:6])))
        out(wrap(a["why"]))
        out(wrap("next step: " + a["next_step"]))
    for n, q in enumerate(r.get("questions") or [], 1):
        out(f"\nQ{n}  (for {q.get('for')}) {q['question']}")
    for n, p in enumerate(r.get("proposals") or [], 1):
        out(f"\nP{n}  {p['action']} {' '.join(p.get('keys', []))}: {p['change']}")


def cmd_show(args):
    b = board_of(args)
    d = analysis_of(b, args)
    snap = b.latest_snapshot()
    items = snapshot.load(snap).by_key() if snap else {}
    fx = json.loads((d / "facts.json").read_text(encoding="utf-8"))
    if args.target:
        kind, rule, keys, text = criteria.resolve(d, args.target)
        if kind == "finding":
            f = next(x for x in fx["findings"] if x["id"] == args.target)
            out(f"{f['id']}  [{f['rule']}, {f['severity']}]  {f['title']}")
            out(wrap(f["says"]))
        else:
            r = reading.load(d) or {}
            n = int(args.target[1:]) - 1
            out(json.dumps((r.get(kind) or [])[n], indent=1, ensure_ascii=False))
        for k in keys[:30]:
            it = items.get(k)
            out(f"  {k:8} {(it.column or '-') if it else '?':12} {it.title if it else '(not in the snapshot)'}")
        return 0
    out(f"board {b.name}, analysis {d.name}")
    r = reading.load(d)
    if r:
        show_reading(r, items)
    else:
        out("(no reading for this analysis)")
    out(f"\n{len(fx['findings'])} findings; `manager findings` lists them, `manager show <id>` opens one")
    return 0


def cmd_findings(args):
    b = board_of(args)
    d = analysis_of(b, args)
    fx = json.loads((d / "facts.json").read_text(encoding="utf-8"))
    seen = criteria.latest_by_target(b.home, b.name)
    for f in fx["findings"]:
        if args.rule and f["rule"] != args.rule or args.severity and f["severity"] != args.severity:
            continue
        v = seen.get(f["id"])
        out(f"{f['id']:28} {f['severity']:7} {f['title']}" + (f"   [{v['verdict']}]" if v else ""))
    return 0


# --- verdicts and criteria --------------------------------------------------------

def cmd_verdict(args):
    b = board_of(args)
    d = analysis_of(b, args)
    row = criteria.record(b.home, b, d, args.target, args.verdict or "", why=args.why or "", answer=args.answer or "")
    out(f"{args.target}: {row['verdict']}" + (f" — {row['why']}" if row["why"] else "") + (f" — {row['answer']}" if row["answer"] else ""))
    if args.rule:
        out("criterion added: " + criteria.add_rule(b.home, args.rule, source=f"{d.name} {args.target}"))
    rebuild_log()
    return 0


def cmd_proposal(args, status):
    b = board_of(args)
    d = analysis_of(b, args)
    p = criteria.set_proposal(d, args.target, status, args.why or "")
    criteria.record(b.home, b, d, args.target, "agree" if status == "approved" else "disagree", why=args.why or "")
    out(f"{p['id']} {status}: {p['action']} {' '.join(p.get('keys', []))}")
    if status == "approved":
        out("  hearthwood does not write to your board in this version. To make the change:")
        out(wrap(p["change"], "    "))
    rebuild_log()
    return 0


def cmd_review(args):
    """Walk the latest analysis one point at a time and record what the person says."""
    b = board_of(args)
    d = analysis_of(b, args)
    snap = b.latest_snapshot()
    items = snapshot.load(snap).by_key() if snap else {}
    fx = json.loads((d / "facts.json").read_text(encoding="utf-8"))
    r = reading.load(d) or {}
    done = {v["target"] for v in criteria.all_verdicts(b.home, b.name) if v.get("analysis") == d.name or v.get("kind") == "finding"}
    queue = [(f"A{n}", a["title"], a["why"], a.get("keys", [])) for n, a in enumerate(r.get("attention") or [], 1)]
    queue += [(f["id"], f["title"], f["says"], f["keys"]) for f in fx["findings"]
              if f["severity"] in ("high", "medium") or args.all]
    queue = [q for q in queue if q[0] not in done]
    if not queue:
        out("nothing waits for your verdict in this analysis (`manager review --all` includes the low findings)")
    out("For each point: a = agree, d = disagree, w = right finding, wrong reason, n = not now, s = skip, q = stop.\n")
    stopped = False
    for target, title, says, keys in queue:
        out(f"{target}  {title}")
        out(wrap(says))
        for k in keys[:5]:
            it = items.get(k)
            if it:
                out(f"    {k} {it.title[:80]}")
        ans = input("  verdict [a/d/w/n/s/q]: ").strip().lower()[:1]
        if ans == "q":
            stopped = True
            break
        if ans not in ("a", "d", "w", "n"):
            out("")
            continue
        verdict = {"a": "agree", "d": "disagree", "w": "wrong-reason", "n": "not-now"}[ans]
        why = input("  why, in a line (enter to skip): ").strip()
        criteria.record(b.home, b, d, target, verdict, why=why)
        if why:
            rule = input("  keep it as a rule for every reading? write the rule, or enter to skip: ").strip()
            if rule:
                criteria.add_rule(b.home, rule, source=f"{d.name} {target}")
                out("  added to your criteria")
        out("")
    for n, q in enumerate(r.get("questions") or [], 1):
        if stopped or f"Q{n}" in done:
            continue
        out(f"Q{n}  (for {q.get('for')}) {q['question']}")
        ans = input("  your answer (enter to skip, q to stop): ").strip()
        if ans.lower() == "q":
            break
        if ans:
            criteria.record(b.home, b, d, f"Q{n}", "", answer=ans)
            rule = input("  keep it as a rule? write the rule, or enter to skip: ").strip()
            if rule:
                criteria.add_rule(b.home, rule, source=f"{d.name} Q{n}")
        out("")
    rebuild_log()
    out("recorded. `manager criteria` shows your criteria; the next `manager analyze` reads them.")
    return 0


def cmd_criteria(args):
    h = home.home_dir()
    p = h / "criteria.md"
    if args.action == "add":
        if not args.text:
            return fail('manager criteria add "the rule, in your words"')
        out("added: " + criteria.add_rule(h, " ".join(args.text)))
        rebuild_log()
        return 0
    if args.action == "edit":
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
        return subprocess.call([editor, str(p)])
    out(p.read_text(encoding="utf-8") if p.exists() else "(no criteria yet)")
    t = criteria.tallies(h)
    if t:
        out("\nyour verdicts by rule: " + "; ".join(f"{k} " + ", ".join(f"{v} {n}" for n, v in c.items()) for k, c in sorted(t.items())))
    return 0


def cmd_share(args):
    p = criteria.share(home.home_dir())
    out(f"written: {p}")
    out("Read it before you send it to anyone: item numbers and quoted titles are replaced, but your reasons are")
    out("as you wrote them. Nothing has been sent.")
    return 0


# --- the page, the spirit, the state ------------------------------------------------

def cmd_log(args):
    p = worklog.build()
    out(f"page: {p}")
    if args.open:
        import webbrowser
        webbrowser.open(p.as_uri())
    return 0


def cmd_next(args):
    cmd, why = guide.next_step()
    out(f"next: {cmd}")
    out(f"  ({why})")
    return 0


def cmd_status(args):
    h = home.home_dir()
    out(f"hearthwood {__version__}, home {h}")
    for b in home.boards(h):
        snap, d = b.latest_snapshot(), b.latest_analysis()
        out(f"\nboard {b.name}: {b.source} {b.where}")
        out(f"  last read: {snap.stem if snap else 'never'}")
        if d and (d / "facts.json").exists():
            fx = json.loads((d / "facts.json").read_text(encoding="utf-8"))
            r = reading.load(d)
            out(f"  last analysis: {d.name}: {len(fx['findings'])} findings, {len(fx['ready'])} ready, "
                + ("a reading" if r else "no reading"))
            props = []
            try:
                props = json.loads((d / "proposals.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            if props:
                out(f"  proposals: " + ", ".join(f"{p['id']} {p.get('status')}" for p in props))
    n = len(criteria.all_verdicts(h))
    rules = sum(1 for line in (h / "criteria.md").read_text(encoding="utf-8").splitlines()
                if line.startswith("- ")) if (h / "criteria.md").exists() else 0
    out(f"\nverdicts given: {n}; criteria lines: {rules}")
    cmd, why = guide.next_step()
    out(f"next: {cmd}  ({why})")
    return 0


def cmd_chat(args):
    h = home.home_dir()
    if not (h / "config.toml").exists():
        home.init_home(h)
    home.refresh_spirit(h)
    cfg = home.config(h)
    tail, env = spirit.launch(h)
    argv = [cfg["claude"]["bin"], "--model", args.model or cfg["models"]["spirit"]] + tail
    if args.resume:
        argv += ["--continue"]
    try:
        return subprocess.call(argv, cwd=str(h / "spirit"), env=env)
    except FileNotFoundError:
        return fail(f"the Claude Code CLI was not found: {cfg['claude']['bin']}")


def cmd_ui(args):
    from . import server
    return server.serve(port=args.port, open_browser=not args.no_open)


def cmd_doctor(args):
    h = home.home_dir()
    ok = True

    def line(good, text):
        nonlocal ok
        ok = ok and good
        out(("  ok   " if good else "  !!   ") + text)

    out(f"hearthwood {__version__}")
    line(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}")
    if search.available():
        line(True, f"SQLite {sqlite3.sqlite_version} with FTS5: duplicates are searched by full text")
    else:
        out(f"  --   SQLite {sqlite3.sqlite_version} has no FTS5: duplicates are compared by title words only")
    cfg = home.config(h)
    claude_bin = shutil.which(cfg["claude"]["bin"])
    line(bool(claude_bin), f"Claude Code CLI: {claude_bin or 'not found (' + cfg['claude']['bin'] + ')'}")
    line((h / "config.toml").exists(), f"home: {h}" + ("" if (h / "config.toml").exists() else " (run manager init)"))
    for b in home.boards(h):
        if b.source == "github":
            token, where = credentials.load_token(b)
            line(bool(token), f"board {b.name}: token from {where}" + ("" if token else " NOT FOUND"))
        elif b.source == "jira":
            app = jira_auth.app_path(h).exists()
            signed = jira_auth.grant_path(b).exists()
            line(app and signed, f"board {b.name}: Jira {b.where}" + ("" if app else "; no Jira app (manager connect jira-app)")
                 + ("" if signed else f"; not signed in (manager connect jira --board {b.name} --again)"))
        else:
            line(os.path.isdir(b.where), f"board {b.name}: folder {b.where}")
    return 0 if ok else 1


# --- the parser ----------------------------------------------------------------------

def parser():
    p = argparse.ArgumentParser(prog="manager", description="Read a project board, see what needs attention, "
                                "and teach it how you judge. Nothing is ever written to your board.")
    p.add_argument("--version", action="version", version=f"hearthwood {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    def cmd(name, fn, help_, board=True, analysis=False):
        s = sub.add_parser(name, help=help_, description=help_)
        s.set_defaults(fn=fn)
        if board:
            s.add_argument("-b", "--board", help="which board, when there is more than one")
        if analysis:
            s.add_argument("--analysis", help="an older analysis by its stamp (default: the latest)")
        return s

    cmd("init", cmd_init, "set up the home (~/.hearthwood)", board=False)
    c = sub.add_parser("connect", help="connect a board: github, jira, markdown, the demo, or a new token for a board")
    cs = c.add_subparsers(dest="kind", metavar="<kind>")
    g = cs.add_parser("github", help="a GitHub repository's issues, and its Projects board when the token may read it")
    g.add_argument("--board", required=True, help="a short name for this board, e.g. web")
    g.add_argument("--repo", required=True, help="owner/repo")
    g.add_argument("--project", type=int, default=0, help="the Projects board's number, from its URL (optional)")
    g.add_argument("--project-owner", default="", help="who owns the Projects board, if not the repository's owner")
    g.add_argument("--token-from", choices=("credentials", "env", "gh"), default="credentials",
                   help="where the token lives: pasted once into the home (default), an environment variable, or the GitHub CLI")
    g.add_argument("--token-stdin", action="store_true", help="read the token from standard input instead of a hidden prompt")
    g.set_defaults(fn=cmd_connect_github)
    t = cs.add_parser("token", help="give a GitHub board a new token")
    t.add_argument("--board", required=True)
    t.add_argument("--token-stdin", action="store_true")
    t.set_defaults(fn=cmd_connect_token)
    j = cs.add_parser("jira", help="a Jira Cloud project and its board, through your own sign-in in the browser")
    j.add_argument("--board", required=True, help="a short name for this board, e.g. app")
    j.add_argument("--site", default="", help="which site, when your sign-in reaches more than one (e.g. acme.atlassian.net)")
    j.add_argument("--project", default="", help="the project key, e.g. APP (default: choose from a list)")
    j.add_argument("--board-id", type=int, default=0, help="which of the project's boards (default: its first)")
    j.add_argument("--paste", action="store_true", help="paste the address the browser lands on, instead of listening for it")
    j.add_argument("--again", action="store_true", help="sign an existing board in again")
    j.set_defaults(fn=cmd_connect_jira)
    ja = cs.add_parser("jira-app", help="the OAuth app hearthwood signs in to Jira with (once per home)")
    ja.add_argument("--client-id", required=True)
    ja.add_argument("--secret-stdin", action="store_true", help="read the client secret from standard input")
    ja.set_defaults(fn=cmd_connect_jira_app)
    dm = cs.add_parser("demo", help="the demo board: twenty made-up tickets, to try hearthwood on")
    dm.add_argument("--board", default="demo")
    dm.set_defaults(fn=cmd_connect_demo)
    m = cs.add_parser("markdown", help="a folder of markdown tickets (the demo board's format)")
    m.add_argument("folder")
    m.add_argument("--board", required=True)
    m.set_defaults(fn=cmd_connect_markdown)
    cmd("boards", cmd_boards, "list the connected boards", board=False)
    mo = cmd("model", cmd_model, "show or set the model of the reading or the spirit", board=False)
    mo.add_argument("role", nargs="?", choices=("reading", "spirit"))
    mo.add_argument("model", nargs="?", choices=home.MODELS)
    dc = sub.add_parser("disconnect", help="remove a board from this computer (its copies and its sign-in); the board itself is untouched")
    dc.add_argument("board", help="the board's name, as `manager boards` lists it")
    dc.add_argument("--yes", action="store_true", help="do not ask first")
    dc.set_defaults(fn=cmd_disconnect)
    cmd("read", cmd_read, "take a snapshot of the board (reads only; no model is called)")
    a = cmd("analyze", cmd_analyze, "compute the facts, then one reading by Claude")
    a.add_argument("--facts-only", action="store_true", help="the facts alone; no model call, no cost")
    a.add_argument("--read", action="store_true", help="take a fresh snapshot first")
    a.add_argument("--model", help="the model for this reading (default: [models] analyst in config.toml)")
    s = cmd("show", cmd_show, "the latest analysis, or one point of it: a finding id, A<n>, Q<n> or P<n>", analysis=True)
    s.add_argument("target", nargs="?")
    f = cmd("findings", cmd_findings, "list the findings of the latest analysis", analysis=True)
    f.add_argument("--rule")
    f.add_argument("--severity", choices=("high", "medium", "low", "info"))
    r = cmd("review", cmd_review, "give your verdict on each point, one at a time", analysis=True)
    r.add_argument("--all", action="store_true", help="include the low and info findings")
    v = cmd("verdict", cmd_verdict, "record a verdict on one point", analysis=True)
    v.add_argument("target", help="a finding id, A<n> or Q<n>")
    v.add_argument("verdict", nargs="?", choices=criteria.VERDICTS)
    v.add_argument("--why", help="your reason, in a line")
    v.add_argument("--answer", help="the answer to a question Q<n>")
    v.add_argument("--rule", help="also keep this as a rule in your criteria")
    for name, status in (("approve", "approved"), ("reject", "rejected")):
        x = cmd(name, lambda a, s=status: cmd_proposal(a, s), f"{name} a proposal P<n> (nothing is written to the board)",
                analysis=True)
        x.add_argument("target")
        x.add_argument("--why")
    k = sub.add_parser("criteria", help="show your criteria; add a rule; or edit the file")
    k.add_argument("action", nargs="?", choices=("show", "add", "edit"), default="show")
    k.add_argument("text", nargs="*")
    k.set_defaults(fn=cmd_criteria)
    cmd("share", cmd_share, "prepare your criteria and reasons to send, with item numbers and titles taken out", board=False)
    lg = cmd("log", cmd_log, "rebuild the page (~/.hearthwood/log.html)", board=False)
    lg.add_argument("--open", action="store_true", help="open it in the browser")
    u = cmd("ui", cmd_ui, "serve the page with the spirit's chat, on this machine only", board=False)
    u.add_argument("--port", type=int, default=0, help="a fixed port (default: a free one)")
    u.add_argument("--no-open", action="store_true", help="print the link, do not open a browser")
    ch = cmd("chat", cmd_chat, "talk with the spirit about your board", board=False)
    ch.add_argument("--model")
    ch.add_argument("--resume", action="store_true", help="continue the last conversation")
    cmd("next", cmd_next, "the one next step", board=False)
    cmd("status", cmd_status, "where things stand", board=False)
    cmd("doctor", cmd_doctor, "check the setup", board=False)
    cmd("update", cmd_update, "fetch the newest hearthwood from GitHub (when it was installed with uv)", board=False)
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 0
    use_system_certificates()
    try:
        return args.fn(args) or 0
    except (ValueError, FileNotFoundError) as e:
        return fail(str(e))
    except urllib.error.URLError as e:
        return fail(network_message(e))
    except KeyboardInterrupt:
        print()
        return 130
    except BrokenPipeError:  # the output was cut off (`manager findings | head`): stop quietly
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0
    except Exception as e:  # a network or tracker error is told plainly, not as a traceback
        from .adapters.github import GitHubError
        if isinstance(e, GitHubError):
            return fail(f"GitHub: {e}")
        if isinstance(e, (jira.JiraError, jira_auth.JiraAuthError)):
            return fail(f"Jira: {e}")
        raise
