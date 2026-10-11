import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hearthwood import home  # noqa: E402
from hearthwood.model import Board, Item, PullRequest  # noqa: E402

DEMO = ROOT / "examples" / "demo-board"
FAKE = Path(__file__).resolve().parent / "fake_claude.py"


def settings(**rules):
    try:
        import tomllib as t
    except ModuleNotFoundError:
        import tomli as t
    s = t.loads(home.DEFAULT_BOARD.format(name="t", source="markdown", where="x", extra=""))
    s["rules"].update(rules)
    return s


def item(key, state="open", column="Todo", **kw):
    return Item(key=key, title=kw.pop("title", f"Item {key}"), state=state, column=column,
                column_source=kw.pop("column_source", "board"), body=kw.pop("body", "A description long enough to count as one."),
                created=kw.pop("created", "2026-09-01T00:00:00Z"), updated=kw.pop("updated", "2026-10-09T00:00:00Z"), **kw)


def board(*items, notes=()):
    return Board(name="t", source="github", where="o/r", fetched_at="2026-10-10T00:00:00Z", items=list(items),
                 notes=list(notes))


class TempHome:
    """A home in a temporary folder, with the fake Claude as its CLI."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Path(self.tmp.name) / "home"
        self.state = Path(self.tmp.name) / "fake"
        self.old = {k: os.environ.get(k) for k in ("HEARTHWOOD_HOME", "FAKE_STATE")}
        os.environ["HEARTHWOOD_HOME"] = str(self.h)
        os.environ["FAKE_STATE"] = str(self.state)
        home.init_home(self.h)
        cfg = (self.h / "config.toml").read_text()
        claude = Path(self.tmp.name) / "claude"
        claude.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
        claude.chmod(0o755)
        (self.h / "config.toml").write_text(cfg.replace('bin = "claude"', f'bin = "{claude}"'))
        return self

    def flag(self, name):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / name).write_text("1")

    def calls(self):
        import json
        p = self.state / "calls.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()


__all__ = ["Board", "Item", "PullRequest", "settings", "item", "board", "TempHome", "DEMO", "ROOT", "home"]
