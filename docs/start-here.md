# Start here: hearthwood for project managers

This guide is for you if you look after a board and have never installed a program from GitHub.
No programming is needed. You will type a few commands into a window called Terminal; each one is
written out in full here, and you can copy and paste it.

At the end you will have hearthwood on your laptop, connected to your Jira project, and a page in
your browser that shows what needs your attention.

It takes about 20 minutes. Do it once; afterwards you only use the page.

## What you need

- **A Mac.** Linux works the same way. Windows is not tested yet (there are notes for it below).
- **A GitHub account.** Free, at [github.com/signup](https://github.com/signup). Hearthwood is in a
  private place on GitHub (a *private repository*), and you need an account to be let in.
- **An invitation** to that repository, from the person who gave you this guide.
- **Two short pieces of text from them:** an *app id* and an *app secret*. They are what lets
  hearthwood ask Jira for your permission. Keep the secret to yourself, like a password.
- **Your Jira**, the one you already use at work (Jira Cloud, an address ending in
  `.atlassian.net`).
- **A Claude plan** (Pro or Max) for the part where Claude reads your board. Without it,
  everything else still works: the facts, the page, your verdicts.

## Words you will meet

| word | what it means here |
| --- | --- |
| **Terminal** | A window where you type commands. On a Mac: press Cmd+Space, type `Terminal`, press Enter. |
| **command** | One line you paste into Terminal and run by pressing Enter. |
| **repository** | The folder on GitHub where hearthwood's files live. Yours to download, not to share. |
| **uv** | A small helper that installs hearthwood and the Python it needs, so you never deal with Python yourself. |
| **sign-in** | You allowing hearthwood to read your Jira, in your browser, the way you allow other apps. |
| **app id and secret** | Hearthwood's own name and password at Atlassian. Not your password: hearthwood never sees that. |
| **the home** | The folder `~/.hearthwood` on your laptop, where hearthwood keeps everything it reads and everything you tell it. |

## 1. Accept the invitation

GitHub sends you an email: *"… invited you to collaborate on hearthwood"*. Open it and press
**View invitation**, then **Accept invitation**. If the email is not there, open
github.com/alexandr352/hearthwood/invitations while signed in to GitHub.

You can now open the repository page: github.com/alexandr352/hearthwood. Other people see
"page not found" there; that is what private means.

## 2. Download hearthwood

On the repository page, press the green **Code** button, then **Download ZIP**.

Your Mac puts it in **Downloads** and usually unpacks it for you into a folder called
`hearthwood-main`. If you see only `hearthwood-main.zip`, double-click it.

Leave the folder there. The commands below expect `~/Downloads/hearthwood-main`.

## 3. Open Terminal

Press **Cmd+Space**, type `Terminal`, press **Enter**. A window with a blinking cursor opens.

How to run a command: copy the grey line, click into Terminal, paste it with **Cmd+V**, press
**Enter**. Wait until the cursor comes back before the next one. Text that scrolls by is normal.

## 4. Install uv (once)

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

When it finishes, **close Terminal and open it again**. That makes the next commands findable.

## 5. Install hearthwood

```sh
uv tool install ~/Downloads/hearthwood-main
```

uv downloads the Python it needs by itself. The last line says
`Installed 1 executable: manager`. `manager` is the command you will use from now on.

Check it:

```sh
manager --version
```

It answers `hearthwood` and a version number. If it says `command not found`, see
[If something goes wrong](#if-something-goes-wrong).

## 6. Try it on the demo board (two minutes, nothing leaves your laptop)

The download includes a made-up board with twenty tickets.

```sh
manager connect markdown ~/Downloads/hearthwood-main/examples/demo-board --board demo
manager analyze --facts-only
manager ui
```

The last command opens a page in your browser. Look around: **Active** is what needs attention,
**All** is every card, **Stats** is the numbers. Click any card number to read the card.

To stop the page, go back to Terminal and press **Ctrl+C**.

## 7. Install Claude Code (for the reading and the chat)

Hearthwood asks Claude to read your board once per analysis and to talk with you on the page. For
that it uses Claude Code, signed in with your own Claude plan.

```sh
curl -fsSL https://claude.ai/install.sh | bash
```

Close and reopen Terminal, then type:

```sh
claude
```

It opens your browser to sign in to your Claude account. When it says you are signed in, type
`/exit` and press Enter. Then check everything at once:

```sh
manager doctor
```

Every line should start with `ok`.

## 8. Connect your Jira

**First, the app (once).** Put in the app id you were given, in place of `PASTE-APP-ID`:

```sh
manager connect jira-app --client-id PASTE-APP-ID
```

It asks for the secret. Paste it and press Enter. Nothing appears while you paste; that is on
purpose, so nobody looking at your screen sees it.

**Then your sign-in.** Choose a short name for your board, in small letters, for example `team`:

```sh
manager connect jira --board team
```

Your browser opens Atlassian's page by itself. (If it does not, Terminal shows a long link that
starts with `https://auth.atlassian.com/`: copy it into your browser.) Atlassian asks whether hearthwood may read your Jira. Choose your
site and press **Accept**. The browser shows *"hearthwood is connected"*; close that tab.

Back in Terminal it lists your projects and asks **Which project?** Type the number in front of
yours and press Enter. It finds the project's board by itself.

Hearthwood can only read. It cannot change a ticket, a comment or a column, and the permission
you gave says so.

## 9. Read your board and open the page

```sh
manager read
manager analyze
manager ui
```

- `manager read` takes a copy of the board (a *snapshot*). On a big project it takes a few
  minutes; Claude is not involved.
- `manager analyze` works out the facts and then has Claude read them once. It takes a few
  minutes and uses a little of your Claude plan. `manager analyze --facts-only` skips Claude.
- `manager ui` opens the page.

## Your day with hearthwood

1. In Terminal: `manager read`, then `manager analyze`, then `manager ui`. (Or just `manager next`,
   which always says the one next step.)
2. On the page, go through **What needs attention**. For each point press **agree** or
   **disagree** and say why in a line. Your reasons are what hearthwood learns from.
3. **Discuss this with Spirit** opens a chat about that point, beside the board. Ask it anything
   about your board; it can also record your decision for you.
4. A reason you would give again can become a rule: the spirit offers it, and it goes into your
   criteria, which every later reading follows first.

Nothing on the page ever changes your board. Approving a proposal records your decision only.

## Getting a new version

When you are told there is a new version: delete the old `hearthwood-main` folder in Downloads,
download the ZIP again (step 2), and run

```sh
uv tool install --force ~/Downloads/hearthwood-main
```

Your boards, verdicts and criteria stay; they live in the home, not in the download.

## If something goes wrong

| what you see | what to do |
| --- | --- |
| `command not found: manager` or `uv` | Close Terminal and open it again. If it persists: `uv tool update-shell`, then reopen Terminal. |
| `no such file or directory: …/Downloads/hearthwood-main` | The folder has another name or place. In Terminal type `uv tool install ` (with a space at the end), then drag the folder from Finder into the window, and press Enter. |
| The Atlassian page says your **admin has disabled** user-installed apps | Your organization does not allow it. Tell the person who invited you; there is nothing to fix on your side. |
| The Atlassian page says the app is **not available** or **not shared** | The app's sharing is not switched on yet. Tell the person who invited you. |
| `cannot listen on 127.0.0.1:8768` | Something else uses that port, often an earlier `manager connect jira` still waiting. Close other Terminal windows, then try again. |
| `the sign-in … was revoked or has expired` | Sign in again: `manager connect jira --board team --again` |
| `Claude Code CLI: not found` in `manager doctor` | Step 7. Until then use `manager analyze --facts-only`. |
| Anything else | Run `manager doctor` and send the person who invited you what it prints. It never prints a secret. |

## What stays on your laptop, and what does not

- Your board's copies, your verdicts, reasons and criteria stay in `~/.hearthwood` on your
  laptop. Hearthwood has no server and sends nothing to its author.
- **When Claude reads your board**, the ticket titles and texts it reads go to Anthropic under
  your Claude account, as in any Claude session. Whether your company allows ticket text to go to
  Claude is your company's decision; ask if you are not sure. `--facts-only` sends nothing.
- More in [People and privacy](people-and-privacy.md).

## Removing it

```sh
uv tool uninstall hearthwood
rm -rf ~/.hearthwood
```

Then, in your Atlassian account under **Connected apps**, remove hearthwood. That withdraws the
permission you gave.

## Windows (not tested yet)

The same steps should work in **PowerShell** instead of Terminal, with these two lines instead of
the ones in steps 4 and 7:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
irm https://claude.ai/install.ps1 | iex
```

and `$HOME\Downloads\hearthwood-main` wherever this guide says `~/Downloads/hearthwood-main`. If
something does not work, that is useful to know: tell the person who invited you.

---

## For the person who invites

Before you send this guide:

1. **Invite them to the repository:** on GitHub, the repository's **Settings**, **Collaborators**,
   **Add people**, their GitHub name or email. On a repository owned by a personal account every
   collaborator can also push changes: GitHub has no read-only role there. Tell them they never
   need to.
2. **Switch on sharing for the Jira app:** at
   [developer.atlassian.com/console/myapps](https://developer.atlassian.com/console/myapps), your
   app, **Distribution**, **Edit**, set it to **Sharing** and answer what Atlassian asks (a
   vendor name, a privacy policy link, and its questions about personal data: hearthwood keeps
   what it reads on each user's own laptop and sends it nowhere else). Until then only you can
   sign in with the app.
3. **Send the app id and secret privately**, for example in a password manager's shared item or
   a message that disappears. Not in a ticket, an email thread or a group chat.
4. **Tell them which Jira project** to choose in step 8, if they have more than one.
