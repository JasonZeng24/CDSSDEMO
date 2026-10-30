"""Build the missing_assets table and classify each path.

Classes:
  A = chart     -> DeLong's own figures/charts (likely recoverable on Wayback)
  B = chrome    -> third-party site chrome (logos, spacers, nav icons) — skip
  C = desktop   -> files from DeLong's local Desktop folder (Wayback unlikely)
  D = other     -> unknown; try Wayback as best-effort
"""

import re
import sqlite3
from urllib.parse import quote, unquote

DB = "weblog_corpus.db"

CHROME_PATTERNS = [
    r"/images/blocks/",
    r"/images/standard/",
    r"/external/images/",
    r"/external/gifs/",
    r"^/images/dingbat\.gif$",
    r"^/images/ecdc_",
    r"^/images/empty\.gif$",
    r"/edition/resources/media/",
    r"^lg_gifs/",
    r"^/images/GA/",
    r"^/media/",
]

CHART_PATTERNS = [
    r"^/movable_type/",
    r"^/Econ_Articles/",
    r"^/Palm/",
    r"^/Totw/",
    r"^/Graphics/",
    r"j-bradford-delong\.net",
]

DESKTOP_PATTERNS = [
    r"Desktop[%\s_]*Folder",
    r"^\.\./\.\.",
]

CHROME_RE = re.compile("|".join(CHROME_PATTERNS), re.IGNORECASE)
CHART_RE = re.compile("|".join(CHART_PATTERNS), re.IGNORECASE)
DESKTOP_RE = re.compile("|".join(DESKTOP_PATTERNS), re.IGNORECASE)


def classify(path: str) -> str:
    p = path.strip()
    if not p:
        return "other"
    if DESKTOP_RE.search(p):
        return "desktop"
    if CHROME_RE.search(p):
        return "chrome"
    if CHART_RE.search(p):
        return "chart"
    if p.lower().startswith(("http://", "https://")):
        return "chart" if "delong" in p.lower() else "other"
    return "other"


def to_delong_url(path: str) -> str | None:
    """Build a candidate original URL on j-bradford-delong.net for a missing path."""
    p = path.strip()
    if p.lower().startswith(("http://", "https://")):
        return p
    if p.startswith("/"):
        return "http://www.j-bradford-delong.net" + quote(unquote(p), safe="/%")
    if p.startswith("../"):
        return None  # relative — no reliable anchor
    return "http://www.j-bradford-delong.net/" + quote(unquote(p), safe="/%")


SCHEMA = """
CREATE TABLE IF NOT EXISTS missing_assets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id       INTEGER NOT NULL,
    orig_path     TEXT    NOT NULL,
    kind          TEXT    NOT NULL,          -- chart | chrome | desktop | other
    orig_url      TEXT,                      -- derived candidate URL on delong site
    wayback_url   TEXT,                      -- filled by wayback_recover.py
    wayback_ts    TEXT,
    status        TEXT    NOT NULL DEFAULT 'pending',  -- pending|hit|miss|skip|error
    checked_at    TEXT,
    UNIQUE(post_id, orig_path)
);
CREATE INDEX IF NOT EXISTS idx_ma_kind_status ON missing_assets(kind, status);
CREATE INDEX IF NOT EXISTS idx_ma_url ON missing_assets(orig_url);
"""


def main():
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    conn.commit()

    rows = conn.execute(
        "SELECT id, missing_samples FROM posts WHERE missing_imgs > 0 AND missing_samples IS NOT NULL"
    ).fetchall()

    tally = {"chart": 0, "chrome": 0, "desktop": 0, "other": 0}
    inserted = 0
    for post_id, samples in rows:
        seen = set()
        for raw in samples.split(";"):
            path = raw.strip()
            if not path or path in seen:
                continue
            seen.add(path)
            kind = classify(path)
            orig_url = to_delong_url(path) if kind != "chrome" else None
            status = "skip" if kind in ("chrome", "desktop") else "pending"
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO missing_assets "
                    "(post_id, orig_path, kind, orig_url, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (post_id, path, kind, orig_url, status),
                )
                if conn.total_changes:
                    inserted += 1
            except sqlite3.Error as e:
                print(f"skip post {post_id} {path!r}: {e}")
            tally[kind] += 1

    conn.commit()

    print("=== classification ===")
    for k, v in tally.items():
        print(f"  {k:8s} {v}")
    print(f"inserted (post,path) rows: {inserted}")

    cur = conn.execute(
        "SELECT kind, status, COUNT(*) FROM missing_assets GROUP BY kind, status ORDER BY kind, status"
    )
    print("\n=== missing_assets table ===")
    for kind, status, n in cur:
        print(f"  {kind:8s} {status:8s} {n}")

    conn.execute(
        "SELECT COUNT(DISTINCT orig_url) FROM missing_assets WHERE status='pending'"
    )
    uniq_pending = conn.execute(
        "SELECT COUNT(DISTINCT orig_url) FROM missing_assets WHERE status='pending'"
    ).fetchone()[0]
    print(f"\nunique pending URLs to query on Wayback: {uniq_pending}")

    conn.close()


if __name__ == "__main__":
    main()
