# How it works

Hearthwood works in three steps. Each one stands on its own and leaves files you can open.

1. **Read.** `manager read` takes a snapshot of the board.
2. **Facts.** `manager analyze` computes the facts with plain code.
3. **Reading.** `manager analyze` then has Claude read the facts once.

Your verdicts and criteria feed back into step 3, and only into step 3. The facts are the same
for everyone; the reading is yours.

## 1. The snapshot

An adapter reads the tracker and returns one shape for every tracker: items with a key, title,
state, column, labels, parent and sub-items, "blocked by" links, linked pull requests, dates,
description and column history. It is stored as
`~/.hearthwood/boards/<board>/snapshots/<stamp>.json`.

The snapshot holds every open item. It also holds the closed items updated in the last
`closed_days` days (60 by default), because the flow numbers need them and so does the question
"is this dependency finished?".

**Dependencies written in text count.** Many teams write dependencies in the description rather
than in a field. A line that starts with "Depends on", "Blocked by", "Requires" or "Waits for"
counts, and so do the lines after it up to a blank one. Every item key on those lines that is
also on the board becomes a dependency. The item files mark these as "written dependencies".

**What could not be read is said.** It is listed under "What could not be read" in `facts.md`
and on the page, and it is never treated as fine. For example, a token that cannot read the
Projects board is noted.

## 2. The facts

Every rule is plain code in `src/hearthwood/facts.py`. A finding has:

- an **id**, such as `blocked-74df94`. It stays the same as long as the same items are involved,
  so your verdict follows it from one analysis to the next.
- a **severity**: high, medium, low or info.
- the **keys** it is about, and **a sentence saying why**.

### Column roles

Rules never look at column names directly. They look at what a column is for, as set in
`board.toml`:

| role | meaning | default names |
| --- | --- | --- |
| startable | work waits here to be picked up | Todo, To Do, Ready |
| active | work is being done | In Progress, Doing |
| review | done, not yet accepted or merged | In Review, Review |
| done | finished | Done, Closed |
| parked | deliberately not now | Backlog, Icebox |

A **dependency is finished** when its item is closed as completed or sits in a done column. **In
review is not finished.** Work cannot be built on something that has not been accepted.

An item with open sub-items is a **goal**. It is judged by its sub-items, never as work itself, so
it is never "ready" and never "not moving".

### The rules

| rule | severity | what it says |
| --- | --- | --- |
| `ready` | info | Items ready to start: open, in a startable column, every dependency finished, no blocking label, not a goal. Items under a goal that is already in progress come first, deepest goal first. After that comes the board's own order, or the item number when the order cannot be read. |
| `blocked` | high to low | An item waiting or in progress that cannot move, with every reason: an unfinished dependency, a blocking label, or a dependency not in the snapshot (unknown, so counted as not done). It is **high** when a dependency was closed as not planned or duplicate, because then it will never finish. |
| `blocked-by-parked` | medium | An item blocked by a parked item: it waits on work nobody plans to do now. |
| `waits-on-review` | low | Items whose only blockers are in review. The quickest unblock is a merge or an acceptance. |
| `cycle` | high | Items that wait on each other, so none of them can start. |
| `stale` | medium, low | Active or in-review work with no update for `stale_days` days. It is medium at twice the limit. |
| `merged-not-done` | medium | An open item with a merged pull request. |
| `review-without-pr` | medium | An item in review with no open or merged pull request linked to it. |
| `pr-not-in-review` | low | An item still waiting or in progress, with an open, non-draft pull request. |
| `open-in-done` | medium | An item in a done column that is still open. Anything that depends on it counts it as finished. |
| `closed-not-done` | low | A completed item whose board column still says otherwise. This is only reported when the column was read from the board itself or from a markdown file, not guessed from history. |
| `parent-closed-children-open` | medium | A closed parent with open sub-items. |
| `children-done-parent-open` | low | An open parent all of whose sub-items (at least two) are closed. |
| `wip` | medium | A column over its work-in-progress limit (`wip` in `board.toml`). |
| `duplicate` | low | Two open items that are each other's closest match by the words of their titles and descriptions, at least `duplicate_match` alike, and not already tied by the board (parent and sub-item, or a dependency); or two open items whose titles share at least `duplicate_similarity` of their words. They are named, never closed. How the search works, and why it is full-text search and not embeddings: [Finding duplicates](experiments/duplicate-search.md). |
| `done-before` | low | An open item and a completed one that are each other's closest match, at least `duplicate_match` alike: already done, or a follow-up that should say which work it follows. |
| `no-column` | low | Open items on no column. |
| `no-parent` | low | Items in play that belong to no parent, on a board where most items have one. |
| `thin` | low | Items in play with almost no description. |
| `load` | medium | Only with `people = true`: a person holding more than `person_wip` items in progress or review. It measures load, never a score. |

Beside the rules, `flow` gives numbers rather than findings:

- open items per column
- items finished in the last 7 and 30 days
- the median days from opened to finished
- the median age of open items by column role
- the median days spent in each column, from the status history

### What the analysis folder holds

`~/.hearthwood/boards/<board>/analyses/<stamp>/`:

| file | what it is |
| --- | --- |
| `facts.json`, `facts.md` | the findings and flow, for programs and for people |
| `board.md` | every item, one per line |
| `similar.md` | for every open item, the items whose titles and descriptions read most like it: candidates, never verdicts |
| `items/` | one file per item, with its description and column history |
| `criteria.md` | a copy of your criteria as they were for this reading |
| `CLAUDE.md` | the reading's instructions ([source](../src/hearthwood/doctrine/analyst/CLAUDE.md)) |
| `mission.md`, `answer-N.txt`, `reading.json` | what the reading was asked, every answer, the accepted one |
| `proposals.json` | the proposals and your decisions on them |
| `calls.jsonl`, `fence.log` | every model call with its cost, and every tool call the fence allowed or refused |

## 3. The reading

The reading is one Claude Code session, started in the analysis folder:

- **Tools:** `Read`, `Grep` and `Glob`. The fence (below) keeps them inside the folder. It has no
  shell, no network and no writing.
- **Instructions:** only its own `CLAUDE.md`. Your global Claude Code instructions and any
  `CLAUDE.md` in parent folders are excluded, so a reading behaves the same on every machine.
- **Mission:** your criteria and the facts, whole, never cut short. It also has the item files to
  open as it needs.

It answers with one JSON object:

- `summary`: two to four sentences.
- `attention`: at most ten points. Each has the keys it is about, the finding ids it rests on,
  why it matters, the next step, and a confidence.
- `questions`: at most five. `"for": "you"` marks a question about how you judge, whose answer can
  become a criterion. Other questions are tagged scope, product or engineering.
- `proposals`: at most ten changes the reading would make to the board. Each has an action, the
  keys, the exact change, and why.

### The contract

`src/hearthwood/reading.py` checks the answer:

- the shape and the lengths
- that every key it cites is on the board
- that every finding id it cites is in the facts
- with `people = false`, that it names no assignee

A broken answer goes back **to the same session**, with each deviation named. The session already
holds the mission and its own answer, so only what is wrong is sent. After `reconsider` tries
(3 by default), the reading is recorded as broken in `reading-broken.json` and the facts stand
alone. If the session cannot be resumed, the retry is a fresh call carrying the whole mission and
the whole previous answer.

### What the reading is taught

Its instructions are short:

- flow before tidiness
- in review is not finished
- what cannot be known is not fine
- goals in flight first
- a card that does not move is a question, not a fault
- duplicates are named, never closed
- small, observable cards

**Your criteria replace any of these.** They come first in the mission, and the instructions say
they outrank everything else.

## The fence

Every tool call of a hearthwood session passes `src/hearthwood/fence.py`, a Claude Code
`PreToolUse` hook. It denies by default, and any error inside it denies.

- **The reading** reads its own analysis folder. Nothing else is allowed.
- **The spirit** reads the home but never `credentials/`. It writes only its own `memory/`
  folder. It runs one `manager <command>` at a time, never `manager connect` (which takes a
  token) and never `manager chat`.

The fence is a guard rail, not a sandbox. It keeps an honest session in its lane.
