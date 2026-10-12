# Commands

Every command takes `--help`. Commands about one board take `-b <board>` when there is more than
one. Commands about an analysis use the latest one unless you name another with
`--analysis <stamp>`.

## Setting up

| command | what it does |
| --- | --- |
| `manager init` | Creates the home, `~/.hearthwood` (or `$HEARTHWOOD_HOME`). It never overwrites what is there. |
| `manager connect github --board <name> --repo <owner/repo> [--project N] [--project-owner X] [--token-from credentials\|env\|gh] [--token-stdin]` | Connects a GitHub repository, and its Projects board if you give its number. It asks for the token unless it comes from `env` or `gh`. See [Connecting](connecting.md). |
| `manager connect token --board <name> [--token-stdin]` | Gives a GitHub board a new token. |
| `manager connect jira-app --client-id <id> [--secret-stdin]` | Keeps the OAuth app hearthwood signs in to Jira with, once per home. See [Connecting](connecting.md#jira-cloud). |
| `manager connect jira --board <name> [--site S] [--project KEY] [--board-id N] [--paste] [--again]` | Connects a Jira Cloud project through your own sign-in in the browser. `--again` signs an existing board in again. |
| `manager connect markdown <folder> --board <name>` | Connects a folder of markdown tickets. |
| `manager connect demo [--board demo]` | Connects the demo board that ships with hearthwood: twenty made-up tickets. |
| `manager boards` | Lists the boards and when each was last read. |
| `manager disconnect <board> [--yes]` | Removes a board from this computer: its snapshots, analyses, settings and token or Jira sign-in. It asks first. Your criteria and verdicts stay, and nothing changes on the board itself. |
| `manager doctor` | Checks Python, the Claude Code CLI, the home, and every board's token, Jira sign-in or folder. |
| `manager model [reading\|spirit] [opus\|sonnet]` | Shows the models, or sets the model of the reading or of the spirit in `config.toml`. The Claude tab does the same. |
| `manager update` | Fetches the newest hearthwood from GitHub, when it was installed with uv. Your home is untouched. |

## Reading and analysing

| command | what it does |
| --- | --- |
| `manager read` | Takes a snapshot of the board. It calls no model. |
| `manager analyze [--read] [--facts-only] [--model M] [--view V]` | Computes the facts on the latest snapshot, then has Claude read them once. `--read` takes a fresh snapshot first. `--facts-only` stops before the reading, so there is no model call and no cost. `--model` picks the model for this one reading. `--view` gives the reading one part of the board: `sprint-recent`, `sprint-all`, `all-recent` or `all-all` (the default). |
| `manager show [<id> \| A<n> \| Q<n> \| P<n>]` | With nothing after it, the reading's summary, attention, questions and proposals. With a finding id or one of those points, that one point and its items. |
| `manager findings [--rule R] [--severity S]` | Lists the findings, each with your last verdict on it. |

## Your verdicts and criteria

| command | what it does |
| --- | --- |
| `manager review [--all]` | Goes through the reading's points and the high and medium findings, one at a time: agree, disagree, wrong reason, not now, skip, or stop. Then come the reading's questions. It offers to keep any reason you give as a rule. `--all` includes the low and info findings. |
| `manager verdict <id\|A<n>> agree\|disagree\|wrong-reason\|not-now [--why "..."] [--rule "..."]` | Records one verdict, the same as in `review`. `--rule` also keeps a rule in your criteria. |
| `manager verdict Q<n> --answer "..." [--rule "..."]` | Answers one of the reading's questions. |
| `manager approve P<n> [--why "..."]`, `manager reject P<n> [--why "..."]` | Records your decision on a proposal. Nothing is written to the board; an approval prints the change for you to make. |

Each of these takes `-b <board>` when the home has more than one board, and `--analysis <stamp>` for
an analysis other than the latest. The page's buttons (`manager ui`) record through the same code.
| `manager criteria` | Shows your criteria and how your verdicts fall per rule. |
| `manager criteria add "..."` | Adds a rule, in your words. |
| `manager criteria edit` | Opens `criteria.md` in `$VISUAL`, `$EDITOR`, or `nano`. |
| `manager share` | Writes your criteria and reasons, with item keys and titles taken out, to `~/.hearthwood/share/` for you to read and, if you choose, send. Nothing is sent. |

## The page, the spirit, the state

| command | what it does |
| --- | --- |
| `manager log [--open]` | Rebuilds `~/.hearthwood/log.html` (which also happens after every read, analysis and verdict). `--open` opens it in the browser. |
| `manager ui [--port N] [--no-open]` | Serves the page with the spirit's chat beside it, on this machine only, and prints a link that carries a key. The chat is the same spirit as `manager chat`. Ctrl-C stops it; the static page keeps working without it. |
| `manager chat [--resume] [--model M]` | Talks with the spirit in the home. It walks through an analysis with you and records your verdicts as you give them. It runs `manager` commands, one at a time, and shows each one. |
| `manager next` | The one next step. |
| `manager status` | Where each board stands: the last read, the last analysis, the proposals, your verdicts and criteria. |

## Settings

`~/.hearthwood/config.toml`:

| key | default | meaning |
| --- | --- | --- |
| `[claude] bin` | `claude` | the Claude Code CLI |
| `[models] analyst` | `opus` | the model that reads the facts |
| `[models] spirit` | `sonnet` | the model you talk to |
| `[timeouts] reading` | `900` | seconds a reading may take |
| `[reading] reconsider` | `3` | tries for an answer that breaks its contract |

`~/.hearthwood/boards/<board>/board.toml`:

| key | meaning |
| --- | --- |
| `source`, `where`, `project`, `project_owner`, `token` | where the board is and where its token comes from |
| `[columns] startable`, `active`, `review`, `done`, `parked` | which of your columns play which role ([How it works](how-it-works.md#column-roles)) |
| `[rules] blocking_labels` | labels that stop work; `*` matches anything, e.g. `needs:*` |
| `[rules] stale_days` | days without an update before active or in-review work counts as not moving |
| `[rules] abandoned_days` | days without an update after which such work goes into one "long untouched" finding instead (180) |
| `[rules] recent_days` | what "Last N days" on the Active tab means: findings and ready cards about cards touched this recently (60) |
| `[rules] duplicate_search` | `full-text` (the default: titles and descriptions, by SQLite FTS5) or `titles` (title words only) |
| `[rules] duplicate_match` | 0 to 1: how closely two items must read alike to be named (full-text); 1 is as close as an item is to itself |
| `[rules] duplicate_candidates` | how many closest matches per item go into `similar.md` for the reading |
| `[rules] duplicate_similarity` | 0 to 1: how alike two open titles must be to be named (titles) |
| `[rules] closed_days` | how far back closed items are read |
| `[rules] wip` | limits per column, e.g. `{ "In Progress" = 3 }` |
| `[rules] people`, `person_wip` | off by default; see [People and privacy](people-and-privacy.md) |
| `[stats] type_labels` | label patterns that give a card its type on the Stats tab, e.g. `["type:*"]`; empty = the tracker's issue type |
| `[stats] goal_labels` | label patterns that make a card a goal even with nothing under it, e.g. `["epic"]` |
