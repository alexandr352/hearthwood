"""Where a board's token comes from. A token is never printed, logged or passed as an argument.

Three places, chosen per board in board.toml (`token = ...`):
    credentials   a file in the home's credentials/ folder, readable by you alone (the default)
    env           the HEARTHWOOD_GITHUB_TOKEN environment variable
    gh            the GitHub CLI's own login (`gh auth token`), if you use the GitHub CLI
"""

import getpass
import os
import shutil
import subprocess
import sys

ENV_VAR = "HEARTHWOOD_GITHUB_TOKEN"


def token_path(board):
    return board.home / "credentials" / f"{board.name}.token"


def save_token(board, value):
    value = (value or "").strip()
    if not value:
        raise ValueError("no token was given")
    if any(c.isspace() for c in value):
        raise ValueError("a token has no spaces or line breaks in it; was something else pasted?")
    d = board.home / "credentials"
    d.mkdir(mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    p = token_path(board)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value)
    os.chmod(p, 0o600)
    return len(value)


def ask_token(stdin=False):
    """Read a token from standard input (piped) or from a hidden prompt."""
    if stdin or not sys.stdin.isatty():
        return sys.stdin.readline().strip()
    return getpass.getpass("Paste the token (it will not be shown): ").strip()


def load_token(board):
    """(token, where it came from). The token is None when it cannot be found."""
    source = board.settings.get("token", "credentials")
    if source == "env":
        return os.environ.get(ENV_VAR) or None, f"the {ENV_VAR} environment variable"
    if source == "gh":
        gh = shutil.which("gh")
        if not gh:
            return None, "the GitHub CLI (not installed)"
        p = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=20)
        return (p.stdout.strip() or None), "the GitHub CLI's login"
    p = token_path(board)
    try:
        mode = os.stat(p).st_mode & 0o777
        if mode & 0o077:
            os.chmod(p, 0o600)
        return p.read_text().strip() or None, f"{p}"
    except FileNotFoundError:
        return None, f"{p} (missing: `manager connect github --board {board.name}` asks for it again)"
