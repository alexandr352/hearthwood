"""What to do next: one command and why, read from the home. `manager next` prints it; the page shows it."""

import json

from . import credentials, criteria, home, jira_auth, reading


def next_step(h=None):
    h = h or home.home_dir()
    if not (h / "config.toml").exists():
        return "manager init", "set up the home"
    bs = home.boards(h)
    if not bs:
        return "manager connect github --board <name> --repo <owner/repo>", "connect a board (or `manager connect jira`, or `manager connect markdown <folder>`)"
    for b in bs:
        if b.source == "github" and b.settings.get("token", "credentials") == "credentials" \
                and not credentials.token_path(b).exists():
            return f"manager connect token --board {b.name}", f"board {b.name} has no token"
        if b.source == "jira" and not jira_auth.grant_path(b).exists():
            return f"manager connect jira --board {b.name} --again", f"board {b.name} has no Jira sign-in"
        if not b.latest_snapshot():
            return f"manager read -b {b.name}", f"board {b.name} has not been read"
        d = b.latest_analysis()
        if not d:
            return f"manager analyze -b {b.name}", f"board {b.name} has not been analysed"
        r = reading.load(d) or {}
        fx = json.loads((d / "facts.json").read_text(encoding="utf-8"))
        done = {v["target"] for v in criteria.all_verdicts(h, b.name) if v.get("analysis") == d.name or v.get("kind") == "finding"}
        waiting = [f"A{n}" for n in range(1, len(r.get("attention") or []) + 1)] + \
                  [f["id"] for f in fx["findings"] if f["severity"] in ("high", "medium")]
        open_ = [t for t in waiting if t not in done]
        if open_:
            return f"manager review -b {b.name}", f"{len(open_)} points of analysis {d.name} wait for your verdict"
    return "manager analyze --read", "everything is answered; read the board again when it has moved"
