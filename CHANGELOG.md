# Changelog

## 0.10.0 — 2026-10-12

Sprint-shaped pages for a board with sprints (Jira). A board without sprints looks as before.

- **This sprint | Everything** on the Active tab. This sprint is the default: the points,
  questions, proposals, findings and ready list narrow to what concerns the running sprint's
  cards. The facts do not change; the choice is remembered.
- **The All tab groups by sprint**: the running sprint first and open, then the coming sprints and
  the parking ones ("Groomed", "Ideas") by start date, then no sprint, then the closed sprints,
  each with its dates and its cards counted by column, cards in rank order. A switch goes back to
  columns.
- **Stats: a Sprints table**, every running and coming sprint with its cards, where they are, and
  its progress.
- **The reading puts the sprint first.** `facts.md` has a This sprint section, and the reading is
  told to lead with the running sprint and say when a point is outside it.
- **The sprint's state, dates and goal are read from Jira**, and a card carried over several
  sprints counts in the running one.

## 0.9.4 — 2026-10-12

- **`manager disconnect <board>`** removes a board from this computer: its snapshots, analyses,
  settings, and its token or Jira sign-in. It asks first (`--yes` skips the question). Your
  criteria and verdicts stay, and nothing changes on the board itself. For Jira it says where to
  withdraw the permission at Atlassian too. The guide mentions it after the demo.

## 0.9.3 — 2026-10-12

- **The Jira sign-in asks for `read:project:jira` too.** Jira Software's board endpoints take
  granular scopes only, and each needs `read:project:jira` beside its own; without it the board
  list answered "scope does not match". An app registered before this needs that scope added in
  the Atlassian console (Permissions, Jira API, granular scopes), and each person allows it once
  more at their next sign-in.
- **A refused board no longer throws the sign-in away.** `manager connect jira` keeps the board and
  the sign-in, says the columns will be statuses until the board can be read, and every `manager
  read` tries the board again.

## 0.9.2 — 2026-10-12

- **The computer's own certificates.** Hearthwood now trusts what the computer trusts (the Mac's
  Keychain, Windows' store, Linux's certificate files) through `truststore`, its first outside
  dependency, small and kept by pip's maintainers. Before, a Python installed from python.org on a
  Mac, or a company network that inspects secure connections, made the Jira sign-in fail at its
  last step with a certificate error.
- **Network failures are said in a sentence**, not a traceback; a certificate failure is not
  retried, since retrying cannot help.
- **A board name is checked before the Jira sign-in**, so a name with capitals or spaces no longer
  wastes one.
- The install line asks uv for its own Python (`--python-preference only-managed`), so an older
  Python already on the computer is not picked up; the guide's troubleshooting has the certificate
  row.

## 0.9.1 — 2026-10-12

- **Public, and installed from GitHub in one line:** `uv tool install
  git+https://github.com/alexandr352/hearthwood`. No account, no token, no download to unpack.
- **`manager update`** fetches the newest version with uv. Installed from a downloaded folder, it
  says the one line that switches to the GitHub version; not installed with uv, it says how to.
- **`manager connect demo`**: the demo board now ships inside the package, so it is there however
  hearthwood was installed (its tickets moved from `examples/demo-board` to
  `src/hearthwood/demo-board`).
- [Start here](docs/start-here.md) follows: no GitHub account or invitation, the one-line install,
  the demo by name, updates by `manager update`; the README's install says the same.

## 0.9.0 — 2026-10-12

- **Jira Cloud.** `manager connect jira` reads a Jira project and its board through **your own
  sign-in in the browser** (Atlassian OAuth 2.0): open the link, choose your site, allow read
  access. No shared token is ever asked for. The access renews itself, the replaced renewal token
  is kept at once, and a revoked or expired sign-in asks for `--again`. On a server, forward port
  8768 or use `--paste`. The OAuth app's id and secret live in the home (`manager connect
  jira-app`); [Connecting](docs/connecting.md#jira-cloud) says how to register one, which needs
  no administrator.
- **What is read from Jira:** open issues and those updated within `closed_days`, in the board's
  rank order; columns and their statuses from the board; parent and epics, sub-tasks, "is blocked
  by" links, resolutions (finished, not planned, duplicate), sprint, priority, fix versions, the
  description and the newest 20 comments (Jira's document format turned into text), and the status
  changes. Without the board, or its permission, the column is the status, and the snapshot says
  so; a missing permission is named, not mistaken for a lost sign-in.
- **Pull requests are not read from Jira** (its development panel has no public API). The snapshot
  says so, and the rules about pull requests stand down for that board.
- The default columns know Jira's "Selected for Development" and "Code Review".
- **[Start here](docs/start-here.md)**, a guide for a project manager who is not a developer: the
  GitHub invitation, Download ZIP, uv, the demo, Claude Code, the Jira sign-in, the day with the
  page, updating, what goes wrong, removing it. Proven on a clean home with uv 0.13 and its own
  Python 3.15; the suite also passes on 3.15.
- `manager connect jira` opens the sign-in page in the browser by itself, where there is one.
- `manager ui` no longer calls `os.uname()`, which Windows does not have.

## 0.8.1 — 2026-10-12

- **A filter on Active.** It narrows the points, questions, proposals, findings and the ready list as
  you type: a line stays when its own words match, or the number, title, type or label of a card it
  names. "N of M shown" says how much is left.
- **Every card whole under `manager ui`.** The page carries whole only the cards Active mentions; the
  rest, which the All tab lists, were titles alone, and their panel said so. Now the panel reads such a
  card from the server when it is opened (`/api/card`, behind the chat's key and host check), with its
  description, comments and new marks, and the same rules about people. The static `log.html` stays
  small and says to open it with `manager ui` to read every card whole.

## 0.8.0 — 2026-10-12

- **Comments are read.** The newest 20 comments of every issue, with when and by whom, and how
  many there are in all; a markdown board's tickets take a `## Comments` section. They are at the
  end of every item file, newest first, and the reading is told to read them before it judges an item: a comment
  often says what a card waits on, that its scope changed, or that the work was done elsewhere.
- **Comments since your decisions.** Your last decision on an item is the newest verdict, answer
  or approval that names it. Comments after it are marked NEW in the item file and "new since your
  decision" in the card panel; `board.md` counts them; an earlier verdict in `facts.md` says when
  comments have come on its items since; and `facts.md` closes with the open items that have them.
- **People stay out of comments too.** With `people = false`, a comment's author is "someone";
  anyone on the board named in a description or a comment, as an @mention or a bare login, reads
  "someone" (in item files and on the page); and the reading's contract refuses an answer that
  names a comment's author.
- The demo board has comments on LAN-7 and LAN-12.

## 0.7.1 — 2026-10-11

- **The spirit knows the page.** Its instructions say it may be talked to on the page, what the
  person can do there, that its card numbers become links, and to record a decision about what the
  person pointed at with that board and analysis. They are refreshed whenever `manager chat` or
  `manager ui` starts, so installing this version is enough.
- **Docs.** The README's demo and daily loop lead with `manager ui`; Cost lists a spirit message;
  "What it does not do" says the spirit sends what it reads to Claude, as the reading does.
  Commands notes `-b` and `--analysis` on the verdict commands; Contributing has the server's rule.

## 0.7.0 — 2026-10-11

- **Decide on the page.** With `manager ui`, every point of attention, question, proposal and
  finding has **Discuss this with Spirit** and its verdict buttons: agree / disagree, approve /
  reject, or an answer in a line. Disagree and reject ask why. Recorded by the same code as
  `manager verdict`, `approve` and `reject`; never written to the board. "change" reopens a
  decision. The static page shows the command instead.
- **Discuss this with Spirit** tells the spirit the point, where its cards are, and how to record
  your decision; it shows the command when it does. The card panel's and NEXT's buttons now read
  "Discuss this card with Spirit" and "Discuss the next step with Spirit".

## 0.6.0 — 2026-10-11

- **The spirit on the page.** `manager ui` serves the page with the spirit's chat in the right
  column, on 127.0.0.1 only, behind a key made at each start (a same-site HttpOnly cookie, a header
  on every API call, a host check, a content security policy). Answers stream in; each command the
  spirit runs shows as a line; card numbers in its answers open the card; a card's panel and NEXT
  can ask the spirit about themselves. The conversation survives a reload; "new" starts afresh.
  Each answer is listed under Model calls with its cost.
- **Monospace.** The page is set in Adwaita Mono, else the system's own monospace.
- The Model calls table scrolls inside its box on a narrow screen.

## 0.5.0 — 2026-10-11

- **Three tabs on the page: Active, All, Stats.** The last one chosen comes back; `#tab=<name>`
  opens one directly.
- **All:** every card on the board, grouped by column in the board's order, with a filter.
- **Stats:** the board's numbers, counted by plain code: the headline numbers, created and closed
  per week (a chart with a table view), every goal's size, progress and growth, open cards by type
  and column, their ages, and the last 14 days. New settings `[stats] type_labels` and
  `goal_labels`.
- **Fixed: long lists were cut at the first page.** A goal with more than 50 sub-items, or a card
  with more than 30 dependencies, was read only up to that number, silently. The rest is now read
  page by page.

## 0.4.0 — 2026-10-11

- **A new look for the page,** in the family of hearthwork's: outlined badges for severity
  (HIGH, MEDIUM, LOW, INFO), verdicts (AGREE, DISAGREE) and proposal states; outlined chips for a
  card's state, column and labels; quieter ids; the header's tools as a row of outlined buttons
  (criteria, model calls, theme).
- **NEXT** at the top of the page: the step `manager next` prints, and why.
- **The card panel is on the right, 400 px wide.** On a wide screen the page makes room beside it;
  on a narrow one it covers the page. Its close button says "close".
- The numbers sit in one row beside the panel.

## 0.3.3 — 2026-10-11

- **Card numbers in the page's sentences open the card.** The reading's summary, its points
  (title, why, next step), questions and proposals, and each finding's title and sentence now link
  every card number they name, by the same rule as descriptions: real cards on the board, whole
  words. A card named there is carried whole. Each piece of text around a number is escaped on its
  own. Clicking a number in a finding's title opens the card without expanding the finding.

## 0.3.2 — 2026-10-11

- **Card numbers in a description open the card.** "Depends on LAN-2" links to LAN-2. Only the
  numbers of real cards on the board are linked, as whole words; anything else stays text.
- **Every card can open.** The page carries every card on the board, the ones it does not
  mention as title, state and column (on a 728-card board: +95 KB).
- **The findings' arrow** sits on the same line as the finding, not above it.
- The screenshot shows the page beside the panel.

## 0.3.1 — 2026-10-11

- **The page moves aside for the panel.** On a screen 1100 px wide or more, the page shifts right of
  the card panel instead of sitting under it, and a click on the page no longer closes the panel.
  On a narrower screen the panel covers the page, as before.

## 0.3.0 — 2026-10-11

- **Cards open on the page.** Every card number on `log.html` opens the card in a panel on the
  left. The panel shows state, column, labels, parent, sub-items, dependencies, pull requests,
  dates, the cards it reads most like and the full description, and links to the tracker. Esc, ✕,
  a click outside or Back closes it, and `#card=<key>` opens a card directly. The page carries the
  cards it mentions, and stubs for the cards they point to. A card's text is shown as text, never
  run. Assignees stay out unless `people = true`.
- `facts.json` keeps each open card's closest matches (`similar`).

## 0.2.1 — 2026-10-11

- **README.** Says what a markdown board is and links its format; names the full-text duplicate
  search and `done-before`; no longer calls itself version 0.1.

## 0.2.0 — 2026-10-11

- **Duplicates by full text.** Possible duplicates are now found by searching titles AND
  descriptions with SQLite FTS5, over open and closed items alike, where 0.1 compared open
  titles only. A pair is named when each item is the other's closest match and the board
  does not already tie them; open items with nearly the same title are still named too. New
  rule `done-before`: open work that reads like work already completed. Why full-text search and not embeddings:
  [Finding duplicates](docs/experiments/duplicate-search.md).
- **similar.md.** The reading is handed every open item's closest matches, marked as
  candidates, and decides what is the same work and what is only related.
- **New settings:** `duplicate_search`, `duplicate_match`, `duplicate_candidates`. Where a
  Python's SQLite lacks FTS5, the title rule runs instead, and `facts.md` and
  `manager doctor` say so.

## 0.1.0 — 2026-10-11

The first version: read, analyse, and learn how you judge. Nothing is written to a board.

- **Boards.** GitHub can be read two ways. With issues only, columns come from each issue's last
  status change. With a Projects board, columns and order come from the board itself. A folder of
  markdown tickets also works, and the demo board uses that format. Dependencies written in
  ticket text ("Depends on #12") count.
- **Facts.** Plain code works out what is ready, what is blocked and why, loops, work that is
  not moving, pull requests against columns, columns against state, parents and sub-items, WIP,
  possible duplicates, unplaced and thin items, and flow numbers. People are off by default.
- **The reading.** One Claude Code session reads the facts and your criteria, fenced to its
  analysis folder. Its answer is checked by code: keys on the board, real finding ids, no
  people. A broken answer goes back to the same session, and after three tries the facts stand
  alone.
- **Verdicts and criteria.** `manager review` and `manager verdict` record your verdicts. Your
  reasons become rules in `criteria.md`, which every reading reads first. `manager share`
  prepares them, scrubbed, for you to send if you choose.
- **The page and the spirit.** `~/.hearthwood/log.html` is a static page. `manager chat` talks
  with you about the board, through `manager` commands only.
