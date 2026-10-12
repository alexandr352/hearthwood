# Criteria

Hearthwood starts with the common sense of someone who looks after a board: flow before tidiness, in review is not
finished, what cannot be known is not fine. Your board is not every board. Criteria are how you
say what is true on yours.

## Where they live

`~/.hearthwood/criteria.md` is a plain file. Each reading reads it first, and the reading's
instructions say it outranks everything else. Write rules as sentences, one per line, under
`## My rules`:

```markdown
## My rules

- A ticket in progress for more than five working days needs a comment saying what it waits on.
- Bugs that block a release outrank everything else, whatever the board's order says.
- Search work may wait; offline mode comes first this quarter.
```

## How they grow

Every point the reading raises, and every finding, can be answered:

| verdict | meaning |
| --- | --- |
| `agree` | right, and it matters |
| `disagree` | wrong, or does not matter here |
| `wrong-reason` | the right finding for the wrong reason |
| `not-now` | right, but not a priority |

with one line of why. `manager review` asks for each in turn. When you give a reason, it asks
whether to keep it as a rule. The rule is kept in your words, not polished into something you
did not say.

```sh
manager review
manager verdict stale-180ca4 disagree --why "search is parked on purpose until offline ships"
manager verdict Q1 --answer "Only merged work counts as done for planning."
manager criteria add "In review for one day is normal; flag it after three."
manager criteria edit
```

Three things carry your judgement forward:

- **The finding's id.** It stays the same while the same items are involved. The next
  `facts.md` shows your last verdict under the finding, and the reading sees it.
- **Your rules.** They are in every mission.
- **The questions.** The reading asks you ("for": "you") whenever your answer would teach it how
  you judge.

Approving or rejecting a proposal is a verdict too: `manager approve P2 --why "..."`.

## Sharing them

`manager share` writes your criteria, how often you agreed with each kind of finding, and your
reasons to `~/.hearthwood/share/criteria-<date>.md`. Item keys and quoted titles are taken out.
Nothing is sent: read it, edit it, and pass it on only if you want to.

This is how hearthwood itself gets better. The facts' rules and the reading's defaults change
when people's criteria show they are wrong.
