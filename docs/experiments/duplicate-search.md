# Finding duplicates: full-text search or embeddings?

*Run 2026-10-11 on one real product board. Hearthwood 0.2.0 is built on the result.*

A board accumulates the same work twice: two people file one bug from two test sessions, a
follow-up is written without naming what it follows, a feature that already shipped is asked
for again. Before 0.2.0, hearthwood compared the **words of open titles**. We wanted to know
whether a better search would find more, and which one: plain word matching, SQLite's
built-in full-text search, or embeddings from a vector database.

**The short answer:** use full-text search (SQLite FTS5, BM25) over the **title and the
description**. Reading descriptions was worth 12 to 17 points of recall. Choosing a better
search method was worth 4 at most. FTS5 needs no extra dependency, no model download and no
memory to speak of. Embeddings did better only on paraphrase, and there were too few of those
cases to rule on.

## The question

When a new piece of work turns up, can a search put the card that already covers it near the
top? We scored that as **recall@k**: of the cases where an existing card did cover the new
work, how often was that card among the first k results?

## The board and the ground truth

- **The board:** 746 cards from one software product, 527 open and 219 closed. They are
  written in English, mostly by developers, and dense with file names, routes and
  identifiers.
- **The cases:** an automated triage step (Claude, given the whole board) had already decided,
  for each piece of newly found work, whether an existing card covered it. Its decisions were
  saved, and those records are the ground truth:
  - **136 positive cases** over 40 cards. In 119 the work was already carded, in 10 it was
    covered by a broader goal, and in 7 it had already been done.
  - **414 negative cases**, where the work was judged new.
- **The query:** the text of the new finding. It ranks the board as that triage step saw it,
  minus the card the finding was raised on.

Recall against these records cannot see a duplicate the triage step itself missed. So we also
**read by hand** a random 30 of the best search hits that the triage step never named.

## The methods

| | method | what it needs |
| --- | --- | --- |
| A | grep: count of query words found in the card | nothing |
| B | SQLite FTS5, BM25 ranking, porter stemming | the `sqlite3` that ships with Python |
| C | embeddings, all-MiniLM-L6-v2 (Chroma's default) | chromadb, ~600 MB of memory |
| D | embeddings, bge-m3, inputs capped at 512 tokens | sentence-transformers, a 4.3 GB model, ~1.7 GB of memory |
| E | B and D combined by reciprocal rank fusion (k = 60) | both |

Each method ran twice: on titles alone, and on title plus description.

## Results

| method | R@5 | R@10 | MRR | goal R@10 (n=10) | done-before R@10 (n=7) | per query |
| --- | --- | --- | --- | --- | --- | --- |
| A grep, title + description | .257 | .301 | .224 | .1 | .14 | 25 ms |
| A grep, title | .507 | .559 | .367 | .3 | .29 | 3 ms |
| **B FTS5, title + description** | **.669** | **.735** | **.520** | .2 | .29 | 202 ms |
| B FTS5, title | .471 | .566 | .378 | .2 | .43 | 26 ms |
| C MiniLM, title + description | .662 | .735 | .508 | .4 | .57 | 175 ms |
| C MiniLM, title | .559 | .654 | .439 | .3 | .43 | 188 ms |
| D bge-m3, title + description | .640 | .772 | .544 | .6 | .43 | 785 ms |
| D bge-m3, title | .537 | .610 | .421 | .5 | .57 | 825 ms |
| E FTS5 + bge-m3, title + description | .757 | .838 | .588 | .5 | .71 | 977 ms |

Building the index took about 60 seconds for MiniLM and 29 minutes for bge-m3 on 3 CPU threads.
FTS5 indexes the whole board in well under a second.

**The hand read.** We drew 30 of the combined method's top-3 hits on findings the triage step
had judged new and never named. None was a true duplicate. 16 were related work (the same file
or screen, a different defect), and 14 were noise. So the triage step's verdicts held up under
every search, and there was no evidence of duplicates it had missed.

## What we read from it

1. **Descriptions matter more than the method.** Every method lost 12 to 17 points of recall@10
   on titles alone. A title says what someone wants. The description says where the work is,
   and that is where two cards about the same work agree.
2. **FTS5 is enough.** The best embedding model beat it by 3.7 points of recall@10, at four
   times the query time, plus a large download and gigabytes of memory. We had set the bar at
   10 points before running anything.
3. **Combining the two ranks better, but finds nothing new.** E clears the bar (+10.3 points,
   14 of 136 queries), but its gain is in ordering. The hand read found nothing it surfaced that
   the triage step had missed.
4. **Embeddings help with paraphrase.** They did better on goals and on work already done,
   where the words differ but the meaning matches. That is 17 cases, too few to decide on.
5. **A search returns candidates, not verdicts.** Most close matches are related work, not the
   same work twice. Deciding which is which needs someone (or a reading) to open both cards.

## Limits

- **One board.** One product, one language, developers' vocabulary. A board written in
  plainer prose, with fewer identifiers to share, may favour embeddings.
- **Finding to card, not card to card.** The queries were findings, not cards. Hearthwood
  searches card against card, which is the closest available measure, not the same one.
- **The ground truth is one triage step's records.** It was checked by a hand read of 30, not
  re-labelled.

## What hearthwood does with it (0.2.0)

- **The index.** Every item, open and closed, goes into an in-memory FTS5 index over title and
  description.
- **The query.** Each item is searched with every word of its title and the rarest words of its
  description, 48 words at most. Words found in more than half the items are dropped.
- **The match.** A hit's strength is its BM25 score divided by the item's score against itself,
  so `match` reads the same on every item.
- **Findings.** A pair is named only when each item is the other's closest match, the board does
  not already tie them (parent and sub-item, or a dependency), and both directions reach
  `duplicate_match` (0.5 by default):
  - **`duplicate`** when both are open;
  - **`done-before`** when one is open and the other was completed.
- **Titles too.** Two open items whose titles are nearly the same (the 0.1 rule, at least 70%
  of their title words shared) are still named. A thin card that twins a full one matches the
  full one's own long description only weakly, so the search alone would let it pass.
- **The shortlist.** `similar.md` gives the reading every open item's five closest matches,
  marked as candidates. The reading decides what is the same work and what is only related.

We checked the rule on the same board, by then 728 items in the snapshot. It searched the
board in about 2 seconds and named 18 pairs, 16 by the search and 2 by their titles. By hand:

| pairs | what they were |
| --- | --- |
| 2 | the same work twice (one bug filed from two test sessions; a card copied whole) |
| 3 | open work following finished work, one of which already named what it follows |
| 1 | one description pasted into two different cards |
| 4 | sibling cards: the same change on two or three screens |
| 6 | related work in the same area |
| 2 | noise |

The old title rule alone named 4 pairs on the same snapshot: the twin copied whole, and three
sibling cards written from one template. It missed the twin filed from two test sessions, which has
different words in its title. It also never looked at closed work, so it could not see a
follow-up.

A looser rule was tried first: accept a pair when each item is in the other's top five. At a
match of 0.5 it named 51 pairs, mostly clusters of related work. At 0.6 it named 19, but 12 of
those were pairs the shipped rule leaves out, mostly within clusters (one group of four related
cards alone gave six), and a follow-up the shipped rule finds fell below the bar.

A reading on Sonnet with the shortlist took one try, 34 seconds and $0.18. It ran before the
title path was added back, so it saw 16 pairs. It put the twin first among the duplicates,
raised it to high, and proposed links for the other likely pair and one follow-up. It also kept
one noise pair among its "reads like finished work" points.

If your Python's SQLite has no FTS5, hearthwood falls back to the title rule and says so in
`facts.md` and in `manager doctor`. Set `duplicate_search = "titles"` in `board.toml` to choose
the title rule yourself.
