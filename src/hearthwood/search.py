"""Items that read alike: SQLite FTS5, BM25 over title and description.

Every item on the board, open and closed, goes into one in-memory full-text index. Each item
is then searched for with its own words: every title word, and the description's rarest words,
up to `max_terms`. A hit's strength is its BM25 score divided by the item's score against
itself, so 1.0 means "as close as the item is to itself" and the number reads the same on
every item.

A search returns CANDIDATES, never a verdict. On a real board most close matches are related
work (the same screen, the same file), not the same work twice; the reading decides which is
which. Why full-text search and not embeddings: docs/experiments/duplicate-search.md.

FTS5 is part of the SQLite most Pythons ship. Where a build lacks it, `available()` is False
and the facts fall back to comparing title words.
"""

import re
import sqlite3

STOP = set("""the and for with that this from into not are was were has have its it's but
which when what where whose than then them they their there these those only also each
does done item items board same would could should must will been being about over under
more most other another because while after before between both either neither nor""".split())


def available():
    try:
        db = sqlite3.connect(":memory:")
        db.execute("create virtual table t using fts5(x)")
        db.close()
        return True
    except sqlite3.OperationalError:
        return False


def terms(text):
    """The searchable words of a text, in order, each once: four letters or more, no stop words."""
    out = []
    for w in re.findall(r"[A-Za-z_][A-Za-z0-9_.\-/]{2,}", text or ""):
        for part in w.split("/"):
            part = part.strip(".-_").lower()
            if len(part) >= 4 and part not in STOP and part not in out:
                out.append(part)
    return out


def _quote(term):
    return '"' + term.replace('"', "") + '"'


class Index:
    def __init__(self, items, max_terms=48):
        self.items = list(items)
        self.row = {it.key: n for n, it in enumerate(self.items)}
        self.max_terms = max_terms
        self.db = sqlite3.connect(":memory:")
        self.db.execute("create virtual table t using fts5(title, body, tokenize='porter unicode61')")
        self.db.executemany("insert into t(rowid, title, body) values (?, ?, ?)",
                            [(n, it.title, it.body or "") for n, it in enumerate(self.items)])
        self._df = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.db.close()

    def __len__(self):
        return len(self.items)

    def df(self, term):
        """How many items hold the term."""
        if term not in self._df:
            self._df[term] = self.db.execute("select count(*) from t where t match ?", (_quote(term),)).fetchone()[0]
        return self._df[term]

    def query_terms(self, it):
        """The title's words, then the description's rarest. On a board of ten items or more, a word in
        more than half of them says nothing and is left out."""
        cap = len(self.items) / 2 if len(self.items) >= 10 else len(self.items)
        title = [w for w in terms(it.title) if 0 < self.df(w) <= cap]
        body = [w for w in terms(it.body) if w not in title and 0 < self.df(w) <= cap]
        return (title + sorted(body, key=self.df))[:self.max_terms]

    def similar(self, it, k=5):
        """[(key, match)] for the k items that read most like `it`, best first; match is 0..1 against itself."""
        q = self.query_terms(it)
        if not q:
            return []
        own = self.row[it.key]
        match = " OR ".join(_quote(w) for w in q)
        rows = self.db.execute("select rowid, -bm25(t) from t where t match ? order by bm25(t) limit ?",
                               (match, k + 1)).fetchall()
        mine = dict(rows).get(own)
        if mine is None:
            got = self.db.execute("select -bm25(t) from t where t match ? and rowid = ?", (match, own)).fetchone()
            mine = got[0] if got else None
        if not mine or mine <= 0:
            return []
        return [(self.items[n].key, round(min(1.0, s / mine), 2)) for n, s in rows if n != own][:k]
