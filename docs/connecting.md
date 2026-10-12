# Connecting a board

Hearthwood only ever reads. Whatever you connect, give it the least access that lets it read.

## GitHub

```sh
manager connect github --board web --repo your-org/your-repo [--project 3] [--project-owner your-org]
```

- `--repo` is the repository whose issues make up the board.
- `--project` is the number of the Projects board, from its URL. For example,
  `github.com/orgs/your-org/projects/3` means `--project 3`. It is optional.
- `--project-owner` is only needed when the Projects board belongs to someone other than the
  repository's owner.

### The token

Make a **fine-grained personal access token** at
[github.com/settings/personal-access-tokens](https://github.com/settings/personal-access-tokens):

| setting | value |
| --- | --- |
| Resource owner | the organization (or the user) that owns the repository |
| Repository access | only the repository you connect |
| Repository permissions | **Issues: Read-only**, **Pull requests: Read-only** (Metadata: Read-only is added by GitHub) |
| Organization permissions | **Projects: Read-only**, if you use `--project` and an organization owns the board |
| Expiration | whatever your organization allows; hearthwood says plainly when a token stops working |

When you run `manager connect github`, you paste the token at a hidden prompt, or pipe it in
with `--token-stdin`. It is written to `~/.hearthwood/credentials/<board>.token`. Only you can
read that file (mode 600, in a folder with mode 700). It is never printed, logged or put on a
command line. The spirit cannot read it.

The token can come from somewhere else instead:

- `--token-from env` reads `HEARTHWOOD_GITHUB_TOKEN` each time.
- `--token-from gh` uses the GitHub CLI's own login (`gh auth token`). That token usually has
  much wider access than hearthwood needs.

`manager connect token --board web` replaces a board's token.

### When the token cannot read the Projects board

Hearthwood still works. Each issue's column becomes its **last status change**, which GitHub
records in the issue's timeline. `manager read` says this in a note, and so do `facts.md` and the
page. Three things change:

- An issue whose status was set when it was added to the board, and never changed after, has no
  column.
- The columns' order is a guess, and so is the board's own ranking. "Ready" is then ordered by
  issue number.
- A status changed by an automation may not appear in the timeline, so a column can lag.

Give the token **Projects: Read-only** and these limits go away.

### What is read

For every open issue, and every issue closed within `closed_days`, hearthwood reads:

- the title, state and close reason, and the type
- the labels and the milestone
- the parent and sub-issues, and the "blocked by" and "blocking" links
- the pull requests that close it
- the dates, the description, and the last 40 status changes
- the newest 20 comments, with when and by whom, and how many there are in all

Assignees and the authors of comments are read too, but they are only shown when the board has
`people = true`.

## A folder of markdown files

```sh
manager connect markdown path/to/folder --board demo
```

Each ticket is one `.md` file with front matter:

```markdown
---
key: LAN-12
title: Show the sync status in the header
status: In Progress
type: Task
labels: [ui, needs:design]
parent: LAN-3
blocked_by: [LAN-10]
pr: open                 # none | open | draft | merged | closed
created: 2026-09-01
updated: 2026-10-01
closed:                  # a date once it is finished
close_reason:            # completed | not_planned | duplicate
---
What the ticket is about.

## Comments

### 2026-10-02 sam
A comment: a date, optionally who wrote it, and the text below.
```

An optional `_board.md` names the columns in order: `columns: [Backlog, Todo, In Progress, In Review, Done]`.
A ticket in a done column is closed unless it says `state: open`. A `## Comments` heading ends the
description; each `### <date> [who]` under it starts one comment. The demo board in
`examples/demo-board` uses this format.

## Jira (planned)

Jira Cloud is next. It will connect the same way, with an API token from
[id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens) and your email,
kept in the home like a GitHub token. A browser sign-in ("connect your account") may follow,
once it is clear whether organizations allow it. Columns, epics, issue links, sprints and
ranking map onto the same shape as GitHub's, so the facts, the reading and your criteria stay
the same.
