"""Signing in to Jira Cloud: the user's own grant, given in the browser (Atlassian OAuth 2.0, "3LO").

Hearthwood never takes a shared token for Jira. The person runs `manager connect jira`, opens the
link it prints, chooses their site and allows read access; Atlassian sends the browser back to
this machine with a one-time code, which is exchanged for an access token (an hour) and a refresh
token. The refresh token is replaced at every renewal and the new one is kept. A grant that was
revoked, or left unused for 90 days, says so and asks for a new sign-in; it never fails silently.

The app: Atlassian wants a registered OAuth app with a client id and secret. They live in the
home (`manager connect jira-app`), readable by you alone, never in this code.

Files, readable by you alone:
    credentials/jira-app.json       {"client_id", "client_secret"}
    credentials/<board>.jira.json   {"access_token", "refresh_token", "expires_at", "cloud_id", "site_url"}
"""

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

AUTH_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"
PORT = 8768
REDIRECT = f"http://localhost:{PORT}/callback"
# Read only. Jira Software's board endpoints take granular scopes only, and each also needs
# read:project:jira beside its own. offline_access brings the refresh token, so one sign-in lasts.
SCOPES = ("read:jira-work", "read:project:jira", "read:board-scope:jira-software",
          "read:board-scope.admin:jira-software", "read:sprint:jira-software", "read:epic:jira-software",
          "offline_access")


class JiraAuthError(Exception):
    pass


def urllib_transport(method, url, headers, body=None, timeout=60):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


def _write_private(path, obj):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)
    os.chmod(path, 0o600)


def _read_private(path):
    try:
        if os.stat(path).st_mode & 0o077:
            os.chmod(path, 0o600)
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


# --- the app ---------------------------------------------------------------------------

def app_path(h):
    return h / "credentials" / "jira-app.json"


def save_app(h, client_id, client_secret):
    client_id, client_secret = (client_id or "").strip(), (client_secret or "").strip()
    if not client_id or not client_secret:
        raise ValueError("the app needs both its client id and its secret")
    if any(c.isspace() for c in client_id + client_secret):
        raise ValueError("a client id or secret has no spaces or line breaks in it; was something else pasted?")
    _write_private(app_path(h), {"client_id": client_id, "client_secret": client_secret})


def load_app(h):
    app = _read_private(app_path(h))
    if not app:
        raise JiraAuthError("no Jira app in this home yet: `manager connect jira-app --client-id <id>` "
                            "(docs/connecting.md says how to register one)")
    return app


# --- the browser sign-in -----------------------------------------------------------------

def new_pkce():
    """(verifier, challenge): the code is useless to anyone who intercepts it without the verifier."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def new_state():
    return secrets.token_urlsafe(24)


def authorize_url(client_id, state, challenge, redirect=REDIRECT):
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "audience": "api.atlassian.com", "client_id": client_id, "scope": " ".join(SCOPES),
        "redirect_uri": redirect, "state": state, "response_type": "code", "prompt": "consent",
        "code_challenge": challenge, "code_challenge_method": "S256"})


def code_from(address, state):
    """The code in the address the browser came back to, after checking it answers this sign-in."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse((address or "").strip()).query)
    if q.get("error"):
        raise JiraAuthError(f"Atlassian refused: {q['error'][0]}" + (f" ({q['error_description'][0]})"
                                                                      if q.get("error_description") else ""))
    if not q.get("code"):
        raise JiraAuthError("that address carries no code; paste the whole address the browser landed on")
    if not secrets.compare_digest(q.get("state", [""])[0], state):
        raise JiraAuthError("that address belongs to another sign-in (its state does not match); start again")
    return q["code"][0]


DONE_PAGE = (b"<!doctype html><meta charset=utf-8><title>hearthwood</title>"
             b"<body style='font:16px monospace;margin:3em'><p>hearthwood is connected. You can close this tab.</p>")


def wait_for_code(state, port=PORT, timeout=300):
    """Listen on 127.0.0.1:<port> for the one redirect of this sign-in and return its code."""
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if urllib.parse.urlparse(self.path).path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            try:
                got["code"] = code_from(f"http://localhost{self.path}", state)
                body, status = DONE_PAGE, 200
            except JiraAuthError as e:
                got["error"] = str(e)
                body, status = f"hearthwood: {e}".encode(), 400
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if status == 200 else "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    try:
        httpd = HTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        raise JiraAuthError(f"cannot listen on 127.0.0.1:{port} ({e.strerror}); stop what holds it, or use --paste")
    httpd.timeout = 1
    end = time.monotonic() + timeout
    try:
        while not got and time.monotonic() < end:
            httpd.handle_request()
    finally:
        httpd.server_close()
    if "error" in got:
        raise JiraAuthError(got["error"])
    if "code" not in got:
        raise JiraAuthError(f"no answer from the browser within {timeout // 60} minutes; run it again, or use --paste")
    return got["code"]


def _token_call(fields, transport):
    status, _, raw = transport("POST", TOKEN_URL, {"Content-Type": "application/json", "User-Agent": "hearthwood"},
                               json.dumps(fields).encode())
    try:
        out = json.loads(raw or b"{}")
    except ValueError:
        out = {}
    if status != 200 or not out.get("access_token"):
        return None, out.get("error") or f"HTTP {status}", out.get("error_description") or ""
    return out, None, None


def exchange(app, code, verifier, transport=None, now=None):
    out, err, why = _token_call({"grant_type": "authorization_code", "client_id": app["client_id"],
                                 "client_secret": app["client_secret"], "code": code, "redirect_uri": REDIRECT,
                                 "code_verifier": verifier}, transport or urllib_transport)
    if err:
        raise JiraAuthError(f"the code could not be exchanged: {err}" + (f" ({why})" if why else ""))
    return _grant(out, now)


def _grant(out, now=None, old=None):
    g = dict(old or {})
    g.update(access_token=out["access_token"], expires_at=int((now or time.time()) + int(out.get("expires_in") or 3600)),
             scope=out.get("scope", g.get("scope", "")))
    if out.get("refresh_token"):
        g["refresh_token"] = out["refresh_token"]
    return g


def resources(access_token, transport=None):
    """The sites this grant may read: [{"id", "url", "name", "scopes"}]."""
    status, _, raw = (transport or urllib_transport)("GET", RESOURCES_URL, {
        "Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": "hearthwood"})
    if status != 200:
        raise JiraAuthError(f"Atlassian would not list the sites of this grant (HTTP {status})")
    return json.loads(raw or b"[]")


# --- a board's grant -------------------------------------------------------------------

def grant_path(b):
    return b.home / "credentials" / f"{b.name}.jira.json"


def save_grant(b, grant):
    _write_private(grant_path(b), grant)


class BoardAuth:
    """The Authorization header for one board's requests, renewed before it expires and once after a 401.
    Every renewal keeps the new refresh token at once: Atlassian accepts each refresh token only once."""

    def __init__(self, b, transport=None, clock=time.time):
        self.b, self.transport, self.clock = b, transport or urllib_transport, clock
        self.app = load_app(b.home)
        self.grant = _read_private(grant_path(b))
        if not self.grant:
            raise JiraAuthError(f"board {b.name} has no sign-in: `manager connect jira --board {b.name} --again`")

    def header(self):
        if self.grant.get("expires_at", 0) - 60 <= self.clock():
            self.renew()
        return f"Bearer {self.grant['access_token']}"

    def renew(self):
        if not self.grant.get("refresh_token"):
            raise JiraAuthError(f"the sign-in of board {self.b.name} cannot be renewed: "
                                f"`manager connect jira --board {self.b.name} --again`")
        out, err, why = _token_call({"grant_type": "refresh_token", "client_id": self.app["client_id"],
                                     "client_secret": self.app["client_secret"],
                                     "refresh_token": self.grant["refresh_token"]}, self.transport)
        if err:
            raise JiraAuthError(f"the sign-in of board {self.b.name} was revoked or has expired ({err}); sign in "
                                f"again: `manager connect jira --board {self.b.name} --again`")
        self.grant = _grant(out, self.clock(), self.grant)
        save_grant(self.b, self.grant)
        return True
