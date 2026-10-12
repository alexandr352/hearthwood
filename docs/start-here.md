# Start here: hearthwood for project managers

This guide is for you if you look after a board and have never installed a program from GitHub.
No programming is needed. You will type a few commands into a window called Terminal; each one is
written out in full here, and you can copy and paste it.

At the end you will have hearthwood on your laptop, connected to your Jira project, and a page in
your browser that shows what needs your attention.

It takes about 20 minutes. Do it once; afterwards you only use the page, and an update is one
command.

## What you need

- **A Mac.** Linux works the same way. Windows is not tested yet (there are notes for it below).
- **Two short pieces of text, an *app id* and an *app secret*.** They are what lets hearthwood ask
  Jira for your permission. Usually whoever set hearthwood up for your team sends them to you. If
  that is you, they are on your Atlassian app's page (step 6 says where). Keep the secret to
  yourself, like a password.
- **Your Jira**, the one you already use at work (Jira Cloud, an address ending in
  `.atlassian.net`).
- **A Claude plan** (Pro or Max) for the part where Claude reads your board. Without it,
  everything else still works: the facts, the page, your verdicts.

No GitHub account is needed: hearthwood is public, at
[github.com/alexandr352/hearthwood](https://github.com/alexandr352/hearthwood).

## Words you will meet

| word | what it means here |
| --- | --- |
| **Terminal** | A window where you type commands. On a Mac: press Cmd+Space, type `Terminal`, press Enter. |
| **command** | One line you paste into Terminal and run by pressing Enter. |
| **uv** | A small helper that installs hearthwood, the Python it needs, and its updates, so you never deal with Python yourself. |
| **git** | The tool that fetches hearthwood from GitHub. Your Mac installs it for you when it is first needed. |
| **sign-in** | You allowing hearthwood to read your Jira, in your browser, the way you allow other apps. |
| **app id and secret** | Hearthwood's own name and password at Atlassian; Atlassian calls them **Client ID** and **Secret**. Not your password: hearthwood never sees that. |
| **the home** | The folder `~/.hearthwood` on your laptop, where hearthwood keeps everything it reads and everything you tell it. |

## 1. Open Terminal

Press **Cmd+Space**, type `Terminal`, press **Enter**. A window with a blinking cursor opens.

How to run a command: copy the grey line, click into Terminal, paste it with **Cmd+V**, press
**Enter**. Wait until the cursor comes back before the next one. Text that scrolls by is normal.

## 2. Install uv (once)

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

When it finishes, **close Terminal and open it again**. That makes the next commands findable.

## 3. Install hearthwood

```sh
uv tool install git+https://github.com/alexandr352/hearthwood
```

**If a window pops up** saying the `git` command needs the *command line developer tools*, press
**Install**, wait until it is done (a few minutes), and run the same line again. That happens
once.

uv downloads the Python it needs by itself. The last line says
`Installed 1 executable: manager`. `manager` is the command you will use from now on. Check it:

```sh
manager --version
```

It answers `hearthwood` and a version number. If it says `command not found`, see
[If something goes wrong](#if-something-goes-wrong).

## 4. Try it on the demo board (two minutes, nothing leaves your laptop)

Hearthwood comes with a made-up board of twenty tickets.

```sh
manager connect demo
manager analyze --facts-only
manager ui
```

The last command opens a page in your browser. Look around: **Active** is what needs attention,
**All** is every card, **Stats** is the numbers. Click any card number to read the card.

To stop the page, go back to Terminal and press **Ctrl+C**.

## 5. Install Claude Code (for the reading and the chat)

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

## 6. Connect your Jira

**First, the app (once).** You need its two pieces of text, the app id and the app secret:

- **Someone sent them to you:** use those.
- **You registered the app yourself** ([Connecting](connecting.md#jira-cloud) shows how): open
  [developer.atlassian.com/console/myapps](https://developer.atlassian.com/console/myapps), click
  your app, then **Settings** in the menu on the left. The **Client ID** is the app id. The
  **Secret** is below it: copy it when the command asks for it.

Put in the app id in place of `PASTE-APP-ID`:

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
starts with `https://auth.atlassian.com/`: copy it into your browser.) Atlassian asks whether
hearthwood may read your Jira. Choose your site and press **Accept**. The browser shows
*"hearthwood is connected"*; close that tab.

Back in Terminal it lists your projects and asks **Which project?** Type the number in front of
yours and press Enter. It finds the project's board by itself.

Hearthwood can only read. It cannot change a ticket, a comment or a column, and the permission
you gave says so.

## 7. Read your board and open the page

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

```sh
manager update
```

It fetches the newest hearthwood from GitHub. Your boards, verdicts and criteria stay; they live in
the home, not in the program.

## If something goes wrong

| what you see | what to do |
| --- | --- |
| `command not found: manager` or `uv` | Close Terminal and open it again. If it persists: `uv tool update-shell`, then reopen Terminal. |
| `git` not found, or the install stops with an error about git | Run `xcode-select --install`, press **Install** in the window that opens, wait, then run step 3 again. |
| The Atlassian page says your **admin has disabled** user-installed apps | Your organization does not allow it. Tell whoever set hearthwood up; there is nothing to fix on your side. |
| The Atlassian page says the app is **not available** or **not shared** | The app's sharing is not switched on yet. Tell whoever set hearthwood up. |
| `cannot listen on 127.0.0.1:8768` | Something else uses that port, often an earlier `manager connect jira` still waiting. Close other Terminal windows, then try again. |
| `the sign-in … was revoked or has expired` | Sign in again: `manager connect jira --board team --again` |
| `Claude Code CLI: not found` in `manager doctor` | Step 5. Until then use `manager analyze --facts-only`. |
| `manager update` says it was installed from a downloaded folder | Run the line it shows once; from then on `manager update` works. |
| Anything else | Run `manager doctor` and send what it prints to whoever set hearthwood up. It never prints a secret. |

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
the ones in steps 2 and 5:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
irm https://claude.ai/install.ps1 | iex
```

Git for Windows comes from [git-scm.com](https://git-scm.com/download/win). If something does not
work, that is useful to know: tell whoever set hearthwood up.

---

## For whoever sets it up for a team

Hearthwood signs in to Jira as a registered Atlassian app. One app serves the whole team; each
person still signs in as themselves and sees only what they may see. Should hearthwood one day need
more permissions (writing a comment it suggested, say), you add them to the same app; nobody else
changes anything, and each person simply allows it once more the next time they sign in. Before
you send this guide:

1. **Register the app** once, as [Connecting](connecting.md#jira-cloud) describes. It needs an
   Atlassian account, not an administrator. Its **Settings** page holds the **Client ID** (the
   app id in this guide) and the **Secret**.
2. **Switch on sharing for the app:** at
   [developer.atlassian.com/console/myapps](https://developer.atlassian.com/console/myapps), your
   app, **Distribution**, **Edit**, set it to **Sharing** and answer what Atlassian asks (a
   vendor name, a privacy policy link, and its questions about personal data: hearthwood keeps
   what it reads on each user's own laptop and sends it nowhere else). Until then only you can
   sign in with the app.
3. **Send the app id and secret privately**, for example in a password manager's shared item or
   a message that disappears. Not in a ticket, an email thread or a group chat.
4. **Tell them which Jira project** to choose in step 6, if they have more than one.
