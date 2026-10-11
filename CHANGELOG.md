# Changelog

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
