# Security

Hearthwood reads a project board with a token you give it, and it starts Claude Code sessions.
Both deserve care.

## What it does to keep you safe

- **It only reads.** No code path writes to a tracker. The GitHub adapter sends GraphQL queries
  and no mutations.
- **Tokens stay private.** A token lives in `~/.hearthwood/credentials/`. The folder has mode 700
  and the file mode 600. A token is read at a hidden prompt or from standard input, never from
  the command line. It is never printed or logged, and the spirit's fence refuses to read it.
- **Sessions are fenced.** Every tool call passes a `PreToolUse` hook that denies by default.
  The reading reads its analysis folder and nothing else. The spirit reads the home (never
  `credentials/`), writes its own memory, and runs one `manager` command at a time. The fence is
  a guard rail, not a sandbox. See [How it works](docs/how-it-works.md#the-fence).
- **The page's chat stays on your machine.** `manager ui` listens on 127.0.0.1 only. Each start
  makes a random key; the printed link sets it as an HttpOnly, same-site cookie, and every API
  call must also carry it in a header, which a page on another site cannot send. A request for
  another host name is refused, and the page is served with a content security policy that loads
  nothing from anywhere else. The chat is the same fenced spirit as `manager chat`.
- **Sessions carry only their own instructions.** Your global Claude Code instructions and any
  `CLAUDE.md` above the home are excluded from hearthwood's sessions.

## Use the least access

Give hearthwood a fine-grained, read-only token for the one repository it reads.
[Connecting](docs/connecting.md) lists the permissions. Revoke the token when you stop using it.

## Reporting a problem

Please do not open a public issue for a security problem. Write to the maintainer through
GitHub (the profile of the repository's owner) and say what you found and how to reproduce it.
