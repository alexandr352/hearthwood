"""The home: where hearthwood keeps everything it reads and everything you tell it.

    $HEARTHWOOD_HOME (default ~/.hearthwood)
      config.toml              models, the claude binary, timeouts
      criteria.md              YOUR criteria: how you judge a board. Every reading reads it.
      verdicts.jsonl           every agree / disagree you gave a finding, with your reason
      runs.jsonl               every model call: what it was for, seconds, cost
      credentials/             tokens and Jira sign-ins, one file per board, readable by you alone
      boards/<name>/
        board.toml             where the board is and how its columns are used
        snapshots/<stamp>.json what `manager read` took from the tracker
        analyses/<stamp>/      what `manager analyze` found: facts, the reading, proposals
      spirit/                  the one you talk to (CLAUDE.md, persona.md, memory/)
      log.html                 the page, rebuilt after every read and analysis
      share/                   what `manager share` prepared for you to send, if you choose

Nothing in the home leaves your machine unless you send it. The one exception is the
reading: `manager analyze` hands the facts and the ticket text to Claude, as any Claude
Code session would. docs/people-and-privacy.md says exactly what goes where.
"""

import fnmatch
import json
import os
import re
import time
from importlib import resources
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

BOARD_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

DEFAULT_CONFIG = """\
# hearthwood configuration. Every key is optional; these are the defaults.

[claude]
bin = "claude"                 # the Claude Code CLI

[models]
# Aliases float to the newest model of the family; pin a full model id to hold one.
analyst = "opus"               # reads the facts and says what needs your attention
spirit = "sonnet"              # the one you talk to (manager chat)

[timeouts]                     # seconds
reading = 900

[reading]
reconsider = 3                 # tries for an answer that breaks its contract
"""

DEFAULT_BOARD = """\
# hearthwood board: {name}
source = "{source}"
where = "{where}"
{extra}
# How your columns are used. Names are matched exactly, as the board spells them.
# A board with no columns at all (issues only) is judged by open and closed.
[columns]
startable = ["Todo", "To Do", "Ready", "Selected for Development"]   # where work waits to be picked up
active = ["In Progress", "Doing"]            # where work is being done
review = ["In Review", "Review", "Code Review"]   # done but not yet accepted or merged
done = ["Done", "Closed"]                     # finished
parked = ["Backlog", "Icebox"]               # deliberately not now

[rules]
blocking_labels = ["blocked", "needs:*"]     # a label that stops work; * matches anything
stale_days = 7                               # active or in review, untouched this long
abandoned_days = 180                         # untouched this long: one "long untouched" finding for them all
recent_days = 60                             # the page shows findings about cards touched this recently first
duplicate_search = "full-text"               # full-text (title and description) | titles
duplicate_match = 0.5                        # 0..1, how closely two items must read alike (full-text)
duplicate_candidates = 5                     # closest matches kept per item, for the reading
duplicate_similarity = 0.7                   # 0..1, how alike two open titles must be (titles)
closed_days = 60                             # closed items read for the flow numbers
# Work in progress limits per column, e.g. {{ "In Progress" = 3, "In Review" = 5 }}
wip = {{}}
# People. Off by default: hearthwood looks at the work, not at the people doing it.
# true shows how much active work each person holds, as load, never as a score.
people = false
person_wip = 0                               # with people = true: flag a person above this many

# The Stats tab. A type is the tracker's issue type, or the first label matching one of these
# patterns, e.g. ["op:*"]. A goal is an item with sub-items, or one labelled with these patterns.
[stats]
type_labels = []
goal_labels = []
"""

SPIRIT_FILES = ("CLAUDE.md", "persona.md")


def has_browser():
    """True where opening a link shows a browser: a Mac, Windows, or a Linux desktop. On a server with no
    display Python would fall back to a text browser inside the terminal, so nothing is opened there."""
    import sys
    return sys.platform in ("darwin", "win32") or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def home_dir():
    return Path(os.environ.get("HEARTHWOOD_HOME") or Path.home() / ".hearthwood").expanduser()


def doctrine(*parts):
    """Text of a doctrine file shipped in the package."""
    return resources.files("hearthwood").joinpath("doctrine", *parts).read_text(encoding="utf-8")


def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def init_home(h=None):
    """Create the home and anything missing in it; never overwrite what is there."""
    h = h or home_dir()
    created = []
    for d in (h, h / "boards", h / "spirit" / "memory", h / "share"):
        if not d.exists():
            d.mkdir(parents=True)
            created.append(d)
    creds = h / "credentials"
    if not creds.exists():
        creds.mkdir(mode=0o700)
        created.append(creds)
    os.chmod(creds, 0o700)
    files = {
        h / "config.toml": DEFAULT_CONFIG,
        h / "criteria.md": doctrine("criteria-seed.md"),
    }
    for name in SPIRIT_FILES:
        files[h / "spirit" / name] = doctrine("spirit", name)
    for p, text in files.items():
        if not p.exists():
            p.write_text(text, encoding="utf-8")
            created.append(p)
    return h, created


def refresh_spirit(h=None):
    """Bring the spirit's doctrine up to this version; its memory and your persona edits stay."""
    h = h or home_dir()
    (h / "spirit" / "memory").mkdir(parents=True, exist_ok=True)
    (h / "spirit" / "CLAUDE.md").write_text(doctrine("spirit", "CLAUDE.md"), encoding="utf-8")
    persona = h / "spirit" / "persona.md"
    if not persona.exists():
        persona.write_text(doctrine("spirit", "persona.md"), encoding="utf-8")


def config(h=None):
    h = h or home_dir()
    base = tomllib.loads(DEFAULT_CONFIG)
    try:
        return _merge(base, tomllib.loads((h / "config.toml").read_text(encoding="utf-8")))
    except FileNotFoundError:
        return base


MODEL_ROLES = {"reading": "analyst", "spirit": "spirit"}
MODELS = ("opus", "sonnet")


def set_model(h, role, model):
    """Write `[models] <analyst|spirit> = "<model>"` into config.toml, keeping every other line as it is."""
    key = MODEL_ROLES.get(role)
    if not key:
        raise ValueError(f"a model is set for the reading or the spirit, not {role!r}")
    if model not in MODELS:
        raise ValueError(f"the model is one of {', '.join(MODELS)}")
    p = h / "config.toml"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out, section, done = [], None, False
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if section == "models" and not done:
                out.append(f'{key} = "{model}"')
                done = True
            section = s[1:-1].strip()
        elif section == "models" and re.match(rf"^{key}\s*=", s):
            comment = line[line.index("#"):] if "#" in line else ""
            line = f'{key} = "{model}"' + (f"{' ' * max(1, 31 - len(key) - len(model))}{comment}" if comment else "")
            done = True
        out.append(line)
    if not done:
        if section != "models":
            out += ["", "[models]"]
        out.append(f'{key} = "{model}"')
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


class BoardHome:
    """One board's folder and its settings."""

    def __init__(self, name, h=None):
        self.home = h or home_dir()
        self.name = name
        self.dir = self.home / "boards" / name
        self.settings = self._load()

    def _load(self):
        text = (self.dir / "board.toml").read_text(encoding="utf-8")
        base = tomllib.loads(DEFAULT_BOARD.format(name=self.name, source="x", where="x", extra=""))
        return _merge(base, tomllib.loads(text))

    @property
    def source(self):
        return self.settings["source"]

    @property
    def where(self):
        return self.settings["where"]

    @property
    def snapshots(self):
        return self.dir / "snapshots"

    @property
    def analyses(self):
        return self.dir / "analyses"

    def latest_snapshot(self):
        snaps = sorted(self.snapshots.glob("*.json")) if self.snapshots.exists() else []
        return snaps[-1] if snaps else None

    def latest_analysis(self):
        found = sorted(p for p in self.analyses.iterdir() if p.is_dir()) if self.analyses.exists() else []
        return found[-1] if found else None

    def column_role(self, column):
        """startable | active | review | done | parked | other, for a column name."""
        if column is None:
            return None
        for role in ("done", "review", "active", "startable", "parked"):
            if column in self.settings["columns"].get(role, []):
                return role
        return "other"

    def blocking_label(self, label):
        return any(fnmatch.fnmatchcase(label, pat) for pat in self.settings["rules"].get("blocking_labels", []))


def add_board(name, source, where, extra="", h=None):
    h = h or home_dir()
    if not BOARD_NAME.match(name):
        raise ValueError("a board name is lowercase letters, digits, '.', '_' or '-', starting with a letter or digit")
    d = h / "boards" / name
    if (d / "board.toml").exists():
        raise ValueError(f"board {name!r} already exists: {d / 'board.toml'}")
    (d / "snapshots").mkdir(parents=True, exist_ok=True)
    (d / "analyses").mkdir(parents=True, exist_ok=True)
    (d / "board.toml").write_text(DEFAULT_BOARD.format(name=name, source=source, where=where, extra=extra),
                                  encoding="utf-8")
    return BoardHome(name, h)


def boards(h=None):
    h = h or home_dir()
    root = h / "boards"
    if not root.exists():
        return []
    return [BoardHome(p.name, h) for p in sorted(root.iterdir()) if (p / "board.toml").exists()]


def resolve_board(name=None, h=None):
    """The board a command means: the one named, or the only one there is."""
    found = boards(h)
    if name:
        for b in found:
            if b.name == name:
                return b
        raise ValueError(f"no board named {name!r}; `manager boards` lists them")
    if not found:
        raise ValueError("no board yet: `manager connect github ...` or `manager connect markdown <folder>`")
    if len(found) > 1:
        raise ValueError("more than one board: name it with -b <board> (`manager boards` lists them)")
    return found[0]


def stamp():
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append_jsonl(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except FileNotFoundError:
        pass
    return rows
