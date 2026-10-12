# How it works

Hearthwood works in three steps. Each one stands on its own and leaves files you can open.

1. **Read.** `manager read` takes a snapshot of the board.
2. **Facts.** `manager analyze` computes the facts with plain code.
3. **Reading.** `manager analyze` then has Claude read the facts once.

Your verdicts and criteria feed back into step 3, and only into step 3. The facts are the same
for everyone; the reading is yours.

## 1. The snapshot

An adapter (GitHub, Jira Cloud, or a folder of markdown files) reads the tracker and returns one shape for every tracker: items with a key, title,
state, column, labels, parent and sub-items, "blocked by" links, linked pull requests, dates,
description, comments and column history. It is stored as
`~/.hearthwood/boards/<board>/snapshots/<stamp>.json`.

The snapshot holds every open item. It also holds the closed items updated in the last
`closed_days` days (60 by default), because the flow numbers need them and so does the question
"is this dependency finished?".

**Dependencies written in text count.** Many teams write dependencies in the description rather
than in a field. A line that starts with "Depends on", "Blocked by", "Requires" or "Waits for"
counts, and so do the lines after it up to a blank one. Every item key on those lines that is
also on the board becomes a dependency. The item files mark these as "written dependencies".

**Comments are read, the newest 20 of each item.** The count says how many there are in all, and
an item file whose thread was cut says how many earlier comments were not read. Comments are
not searched for duplicates: the search reads titles and descriptions.

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
| `long-untouched` | low | One finding for all active or in-review work with no update for over `abandoned_days` days (180 by default), oldest first. Work that old is probably finished, dropped or forgotten; one decision for the lot beats one line per card. |
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
| `items/` | one file per item, with its description, column history and comments |
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
  open as it needs, and is told to read an item's comments before judging it.

**Comments since your decisions.** A comment can say what a card waits on, that its scope changed,
or that the work was done elsewhere, and it may have come after you decided something about the
card. Your last decision on an item is the newest verdict, answer or approval whose point names
it. In the item file, where comments are newest first so a long thread starts with what is recent,
every comment after that moment is marked NEW. In `facts.md`, an earlier
verdict on a finding says when new comments have come on its items since, and a closing section
lists the open items with comments newer than your last decision on them. An item you have never
decided about has no NEW comments: nothing was decided that they could change.

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
- with `people = false`, that it names no assignee and no author of a comment

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
- the sprint first, when the facts have a running sprint: `facts.md` then carries a **This sprint**
  section (the running sprints with their dates, goal and cards by column, the cards in them, which
  of those are ready, and the findings that touch them)

**Your criteria replace any of these.** They come first in the mission, and the instructions say
they outrank everything else.

## 4. The page

`~/.hearthwood/log.html` is one self-contained file, rebuilt after every read, analysis and
verdict. No server runs and no model writes it. It shows the numbers, the reading, the questions,
the proposals and every finding.
Its top line is the next step, the same one `manager next` prints. Badges say what kind of thing
each line is: a finding's severity (HIGH, MEDIUM, LOW, INFO), your verdict (AGREE, DISAGREE), a
proposal's state.

**Every card number opens the card** in a panel on the right, 400 px wide: its state, column,
type and labels;
its parent, sub-items, dependencies and pull requests, each clickable in turn; its dates; the
cards it reads most like; its description; its comments, those after your last decision on it
marked "new since your decision"; and a link to the card in the tracker. On a screen
1100 px wide or more the page makes room beside the panel, so both can be read side by side; on
a narrower one the panel covers the page. ✕, Esc or the browser's Back button closes the panel, and
so does a click outside it when it covers the page. Each open card has its own address
(`log.html#card=LAN-7`, or `#card=<board>/<key>` when the home holds more than one board), so it
can be bookmarked or sent.

A card number written in a sentence opens that card too: in a description, in the reading's summary,
points, questions and proposals, and in a finding. It must be a card on the board
(`#12` on GitHub, `LAN-2` in a markdown board): a pull request's number, or a key that only looks
like one, stays text.

The page carries the cards it mentions whole, and every other card on the board as its title,
state and column, so any card number opens something. On a board of 728 cards it carried 131
whole, with their 33 comments, and 597 as titles, and the page weighed 981 KB. Under `manager ui`
a card carried as its title is read whole when it is opened: the panel asks the server for it
(`/api/card`, behind the same key as the chat), from the latest snapshot, with the same rules about
people. The static page says where to read it instead.

A card's text is shown, never run: the panel builds every line with plain text and no HTML, and
the embedded cards are escaped so that no card can close the element that holds them. Assignees and
the authors of comments are not on the page unless the board has `people = true`, and anyone on
the board named in a description or a comment reads "someone".

### Four tabs, and the view

The page has four tabs; the one you last chose comes back, and `log.html#tab=stats` opens one directly.

**The view** is chosen in the top row and applies to every tab: **Last 60 days | All time**
(`recent_days` in board.toml) and, on a board with a running sprint, **This sprint | Everything**.
Last 60 days and This sprint are the defaults; the choice is remembered. Each combination is
computed when the page is built, so switching is instant and nothing is estimated in the browser.
"Open, last 60 days" means open cards touched in the last 60 days.

- **Active**: the next step, the totals, the reading, the questions, the proposals, the findings,
  all for the cards in view. Findings about recently touched cards always come first, and the
  heading says how many are recent and how many older; the reading's own points are always shown.
- **All**: every card in view, grouped by column in the board's order, closed cards folded at
  the end. On a board with sprints it groups **by sprint** instead (a switch goes back to columns):
  the running sprint first and open; then the coming ones, newest first; then the parking sprints
  (no start date, or one long gone by), the most recently worked-on first; then cards in no
  sprint; then the closed sprints, newest first. Each is folded, with its cards counted by column
  and its dates. Inside a group, cards are in the board's rank order. A filter narrows it by number, title, type or label as you type, and every row opens the
  card in the panel.
- **Stats**: the numbers of the cards in view, counted by plain code from the snapshot, with no model:
  - open, how many wait and in which columns, created against closed in the last 14 days, open
    cards under no goal, and what is in progress and in review now;
  - created, done and not planned per week for six weeks, as a chart with a table view;
  - with sprints, every running and coming sprint: its cards, how many wait, are in progress, in
    review and done, and how far along it is;
  - every goal's size and progress: its cards, how many are open and done, how many were added in
    the last 30 and 7 days and closed in the last 30, and the open goals with nothing under them;
  - what is open by type and column, how old the open cards are, and the last 14 days day by day.

  A snapshot holds the cards closed in the last `closed_days` only, so a week that reaches further
  back is marked as short rather than shown as whole. A *type* is the tracker's issue type, or the
  first label matching `[stats] type_labels`; a *goal* is a card with sub-items, or one labelled
  with `[stats] goal_labels`, so a goal with nothing under it yet still counts.
- **Claude**: everything that involves Claude. The models of the reading and of the spirit (Opus or
  Sonnet, written to `config.toml`; also `manager model reading sonnet`), **Read the board and run
  the facts** (no model, no cost) and **Run a reading** (one Claude session), each in the background,
  one at a time, the page refreshing itself when it is done; and every model call with its cost.
  The static page shows the commands instead of the buttons.

### The spirit on the page

`manager ui` serves the same page with the spirit's chat in the column on the right, on this machine
only. Ask about the board, a card or a finding; the spirit reads the home and runs `manager`
commands, and each command it runs shows as a line in the chat. Card numbers in its answers open the
card. Opening a card covers the chat; "ask the spirit about this card" closes the card and asks with
the card named, and NEXT's "do it with the spirit" asks about the next step. The conversation is one
ongoing session, kept when you reload; "new" starts another. Each answer is a model call, listed
under Model calls with its cost. When the board changes (a read, an analysis, a verdict), the page
reloads itself unless you are typing.

**Deciding on the page.** Every point of attention, question, proposal and finding carries its
actions: **Discuss this with Spirit**, which opens the chat on that point (the spirit reads it and the
cards it names, proposes the next step with the text you would post, and records your decision with
`manager verdict` when you give it), and the verdict itself: agree or disagree for a point or a
finding, approve or reject for a proposal, a line of answer for a question. Disagreeing and rejecting
ask why in a line, because the reason is what becomes a criterion. Decisions are recorded by the
same code as `manager verdict`, `approve` and `reject`, in your home and never on the board; a
decided point shows its verdict and your reason, and "change" brings the buttons back. The static
`log.html` shows the command to run instead.

The server listens on 127.0.0.1 only and prints a link with a key made at each start: see
[SECURITY](../SECURITY.md).

The page is set in a monospace face: Adwaita Mono where it is installed, else the system's own
monospace (SF Mono on a Mac, Menlo, Consolas).

## The fence

Every tool call of a hearthwood session passes `src/hearthwood/fence.py`, a Claude Code
`PreToolUse` hook. It denies by default, and any error inside it denies.

- **The reading** reads its own analysis folder. Nothing else is allowed.
- **The spirit** reads the home but never `credentials/`. It writes only its own `memory/`
  folder. It runs one `manager <command>` at a time, never `manager connect` (which takes a
  token) and never `manager chat`.

The fence is a guard rail, not a sandbox. It keeps an honest session in its lane.
