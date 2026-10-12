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
(`manager connect demo`, files in `src/hearthwood/demo-board`) uses this format.

## Jira Cloud

Hearthwood reads Jira through **your own sign-in**, given in the browser. It never asks for a
shared token, and it can only read.

```sh
manager connect jira-app --client-id <id>          # once per home; asks for the app's secret
manager connect jira --board app [--site acme.atlassian.net] [--project APP] [--board-id N] [--paste]
```

`manager connect jira` prints a link. Open it, choose your site and allow read access. Atlassian
sends the browser back to `http://localhost:8768/callback`, where hearthwood is listening, and the
sign-in is done. It then lists your projects (or takes `--project`) and finds the project's board.
Signing in again later is `manager connect jira --board app --again`.

**When the browser is on another machine** (hearthwood runs on a server), either forward the port
first, `ssh -L 8768:127.0.0.1:8768 <server>`, or run with `--paste`: after you allow access, the
browser lands on an address starting with `http://localhost:8768/callback` that may not open; copy
the whole address and paste it into the terminal.

### The app

Atlassian lets an outside program sign in only as a registered app, with a client id and a
secret. Registering one needs an Atlassian account, not an administrator:

1. At [developer.atlassian.com/console/myapps](https://developer.atlassian.com/console/myapps),
   **Create**, then **OAuth 2.0 integration**. Name it, for example `hearthwood`.
2. **Permissions**, **Jira API**, **Add**, then **Configure**. Add the classic scope
   `read:jira-work`, and the granular scopes `read:board-scope:jira-software`,
   `read:board-scope.admin:jira-software`, `read:sprint:jira-software` and
   `read:epic:jira-software`. Nothing that writes.
3. **Authorization**, **OAuth 2.0 (3LO)**: the callback URL is `http://localhost:8768/callback`.
4. **Settings** shows the client id and the secret: `manager connect jira-app --client-id <id>`,
   then paste the secret when asked (it is not shown, and it is kept in the home, readable by you
   alone).
5. For anyone but the app's owner to sign in with it, turn on **Distribution** (sharing).

One app can serve a whole team: whoever registered it gives the id and secret to the others
privately. Each person still signs in as themselves and sees only what they may see.

**If your organization blocks it.** An administrator can stop people from allowing outside apps
("user-installed apps"). Then the consent page says so instead of offering your site, and the
sign-in cannot be used there.

### What is read

For every open issue of the project, and every issue updated within `closed_days`, in the board's
rank order. An issue is finished when Jira resolved it, or when its status is in the Done category:
some workflows never use that category and only resolve, so either one counts.

- the summary, type, status, labels and priority, the fix versions and the sprint
- the parent (an epic, or the issue a sub-task belongs to), the sub-tasks, and the "is blocked by"
  links
- the resolution: Done and the like are finished, Won't Do and the like are not planned, Duplicate
  is a duplicate
- the dates, the description, the newest 20 comments with when and by whom, and the status changes
- the board's columns, in order, and which statuses belong to each: an issue's column is the column
  its status sits in

Assignees and the authors of comments are read too, but they are only shown when the board has
`people = true`.

**Not read: pull requests.** Jira keeps them in its development panel, which has no public API.
The snapshot says so, and the rules about pull requests stand down for a Jira board rather than
call every card in review unreviewed.

**When the board cannot be read** (the project has none, or the sign-in lacks its permission), an
issue's column is its status name, and the snapshot says why.

### Keeping the sign-in

The sign-in is kept in `credentials/<board>.jira.json`, readable by you alone. The access it
gives lasts an hour and is renewed by itself; Atlassian replaces the renewal token every time, and
hearthwood keeps the new one at once. If you revoke the app (Atlassian account, **Connected apps**)
or leave it unused for 90 days, `manager read` says so and asks you to sign in again.
