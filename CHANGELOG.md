# Changelog

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
