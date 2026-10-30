"""Hit the Wayback Availability API for every pending missing asset.

- Rate-limited (default 1 req/sec, polite).
- Resumable: only queries rows still in status='pending'.
- Deduped by orig_url so the same chart on 20 posts costs 1 request.
- Writes wayback_url/wayback_ts/status/checked_at on every row with that URL.
"""

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DB = "weblog_corpus.db"
API = "https://archive.org/wayback/available"
UA = "DS-discovery-demo/1.0 (research; zengjason311@gmail.com)"

# Prefer a snapshot captured during DeLong's active years
PREFERRED_TS = "20030701"


def query_wayback(url: str, timeout: float = 20.0, max_retries: int = 4) -> tuple[str | None, str | None, str]:
    """Return (wayback_url, wayback_ts, status). status ∈ hit|miss|error:*.

    On HTTP 429 / 5xx / timeout, retries with exponential backoff.
    """
    qs = urllib.parse.urlencode({"url": url, "timestamp": PREFERRED_TS})
    req = urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": UA})
    backoff = 5.0
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                print(f"    HTTP {e.code}, backing off {backoff:.1f}s")
                time.sleep(backoff)
                backoff *= 2
                continue
            return None, None, f"error:http{e.code}"
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"    {type(e).__name__}, backing off {backoff:.1f}s")
                time.sleep(backoff)
                backoff *= 2
                continue
            return None, None, f"error:{type(e).__name__}"
    else:
        return None, None, "error:exhausted"

    snap = (data.get("archived_snapshots") or {}).get("closest") or {}
    if snap.get("available") and snap.get("url"):
        return snap["url"].replace("http://", "https://", 1), snap.get("timestamp"), "hit"
    return None, None, "miss"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max unique URLs this run (0=all)")
    ap.add_argument("--sleep", type=float, default=3.0, help="seconds between requests")
    ap.add_argument("--retry-errors", action="store_true", help="also retry rows in error:* status")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    status_filter = "status='pending'"
    if args.retry_errors:
        status_filter = "(status='pending' OR status LIKE 'error:%')"

    urls = [
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT orig_url FROM missing_assets "
            f"WHERE orig_url IS NOT NULL AND {status_filter} "
            f"ORDER BY orig_url"
        ).fetchall()
    ]
    if args.limit:
        urls = urls[: args.limit]

    print(f"querying {len(urls)} unique URLs (sleep={args.sleep}s)")
    hits = misses = errors = 0

    for i, url in enumerate(urls, 1):
        wb_url, wb_ts, status = query_wayback(url)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE missing_assets SET wayback_url=?, wayback_ts=?, status=?, checked_at=? "
            "WHERE orig_url=?",
            (wb_url, wb_ts, status, now, url),
        )
        conn.commit()

        if status == "hit":
            hits += 1
        elif status == "miss":
            misses += 1
        else:
            errors += 1

        if i % 10 == 0 or i == len(urls):
            print(f"  [{i}/{len(urls)}] hits={hits} miss={misses} err={errors}  last={url[:80]}")

        time.sleep(args.sleep)

    print(f"\ndone. hits={hits} miss={misses} err={errors}")

    # Final tally across all rows
    print("\n=== missing_assets final ===")
    for row in conn.execute(
        "SELECT kind, status, COUNT(*) FROM missing_assets GROUP BY kind, status ORDER BY kind, status"
    ):
        print(f"  {row[0]:8s} {row[1]:12s} {row[2]}")

    conn.close()


if __name__ == "__main__":
    main()
