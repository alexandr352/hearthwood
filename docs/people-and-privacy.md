# People and privacy

A board is about work, but it is made by people. People's names are on the cards, and their
habits show in the dates. Hearthwood is built so that what it says about a board never becomes
something said about a person.

## It looks at the work, not at the people

- **Assignees are off by default.** With `people = false`, the setting in every new board's
  `board.toml`:
  - no finding names a person
  - no item file the reading can open lists an assignee
  - the reading's contract refuses an answer that names one
- **Load, never a score.** With `people = true`, one rule (`load`) appears. It flags a person
  holding more than `person_wip` items in progress or review at once, because too much at once
  slows every item. Nothing in hearthwood measures, ranks or compares how much anyone finishes,
  how fast, or how well, and nothing will.
- **The reading is told the same.** Its instructions say never to judge, rank or compare a person.
  When a problem lies with how work was handed out, it says what the work needs, not who failed.
  The spirit's instructions say the same, even when you ask it to.

If you use hearthwood on a team's board, tell the team. Something that reads their work should
not be a secret.

## What stays on your machine

Everything is in `~/.hearthwood`:

- the snapshots of your board
- the facts
- the readings
- your verdicts, reasons and criteria
- the page

Hearthwood has no server and sends no telemetry, and the author receives nothing.

Tokens stay in `~/.hearthwood/credentials/`, readable by you alone. They are never printed,
logged, or passed on a command line.

## What leaves your machine

**The reading.** `manager analyze` (without `--facts-only`) starts one Claude Code session, and
everything it reads goes to Anthropic under your Claude account, as in any Claude Code session:

- the facts, which include ticket keys, titles and some sentences about them
- your criteria
- whichever ticket files it chooses to open, which hold titles and descriptions

Whether your organization allows ticket text to go to Claude is your organization's decision.
`manager analyze --facts-only` sends nothing.

**The spirit.** `manager chat` is a Claude Code session too, and so are the files it reads.

**Reading the tracker.** `manager read` talks to GitHub (or later Jira) with your token. It only
reads.

## Sharing what you have taught it

Your criteria and reasons are the most useful thing hearthwood collects. They are also yours.
`manager share` prepares them for you to send, if you choose. It writes
`~/.hearthwood/share/criteria-<date>.md`, with item keys replaced by `[item]` and quoted titles
by `[title]`. It does not send anything. Read it before you pass it on: your reasons are kept as
you wrote them, and a reason can still name something you would rather not share.

## Deleting

- Delete a board's folder under `~/.hearthwood/boards/` to forget the board.
- Delete `~/.hearthwood` to forget everything.
- Revoke the token on GitHub when you stop using hearthwood.
