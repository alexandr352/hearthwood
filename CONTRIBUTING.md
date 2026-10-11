# Contributing

Hearthwood is young, and its most important input is not code. It is how project managers
actually judge a board. If you use it, your verdicts and criteria are the most useful thing you
can share (`manager share`, read before you send).

## Ideas and problems

Open an issue and say:

- what you expected
- what happened
- which command you ran

For a judgement you disagree with, include the finding's rule (for example `stale`) and why,
in your own words. Please leave out your board's ticket text unless it is public.

## Working on the code

```sh
git clone https://github.com/alexandr352/hearthwood && cd hearthwood
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -t tests
```

- The code is plain Python 3.10+ with the standard library only (`tomli` on 3.10).
- The tests never call a real model or a real tracker. `tests/fake_claude.py` stands in for the
  Claude Code CLI, and a fake transport stands in for GitHub.
- A new rule in `facts.py` comes with a test that shows the board it fires on and one it does
  not fire on, and with a row in [How it works](docs/how-it-works.md).
- A change to what the reading may answer changes `reading.check`, `SCHEMA`, a test and the docs
  together.
- The page's server (`server.py`, `manager ui`) listens on 127.0.0.1 only. A new endpoint checks
  the key in its `X-HW-Key` header and the host, and comes with a test that it refuses a request
  without them. Anything it writes goes through the same code as the matching `manager` command.
- Nothing may write to a tracker without a person approving that exact change first.
- Nothing may judge, rank or compare people. See [People and privacy](docs/people-and-privacy.md).

## Commits

Commits carry their author's own name and email.
