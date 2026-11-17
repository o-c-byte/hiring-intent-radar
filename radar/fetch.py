"""Fetch every open posting for the universe and write data/postings.jsonl.

    python -m radar.fetch            # re-download every board (polite pacing, ~1 req/s per ATS host)
    python -m radar.fetch --cached   # rebuild postings.jsonl from data/raw/ without network
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from .ats import FETCHERS
from .common import DATA, RAW, write_jsonl
from .geo import countries_in, is_remote_only

# Date fields that mark when a posting was created/published (Greenhouse `updated_at` is not one of them).
CREATION_FIELDS = {"first_published", "createdAt", "publishedAt", "published_on", "created_at", "published_at",
                   "releasedDate", "pubDate"}


def main(argv: list[str]) -> None:
    cached = "--cached" in argv
    universe = json.loads((DATA / "universe.json").read_text(encoding="utf-8"))
    today = dt.date.today()

    def load(c):
        path = RAW / f"{c['id']}.json"
        if not cached:
            posts = FETCHERS[c["platform"]](c["slug"])
            if posts is not None:
                path.write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
                return c, posts
        return c, json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    rows = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for c, posts in ex.map(load, universe):
            c["open_roles"] = len(posts)
            for p in posts:
                posted = p.get("posted_at")
                age = (today - dt.date.fromisoformat(posted)).days if posted else None
                rows.append({
                    "company_id": c["id"], **{k: p[k] for k in ("job_id", "title", "location", "department", "url")},
                    "countries": countries_in(p["locations"], p.get("country_codes", [])),
                    "remote_only": is_remote_only(p["locations"]),
                    "posted_at": posted, "date_field": p.get("date_field"),
                    "date_is_creation": p.get("date_field") in CREATION_FIELDS, "age_days": age,
                    "text": p["text"],
                })
    write_jsonl(DATA / "postings.jsonl", rows)
    (DATA / "universe.json").write_text(json.dumps(universe, indent=1, ensure_ascii=False), encoding="utf-8")
    (DATA / "snapshot.json").write_text(json.dumps({"date": today.isoformat(), "companies": len(universe),
                                                    "postings": len(rows)}), encoding="utf-8")
    print(f"{len(rows)} postings from {len(universe)} companies -> data/postings.jsonl")


if __name__ == "__main__":
    main(sys.argv[1:])
