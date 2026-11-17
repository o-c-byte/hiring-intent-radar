"""ATS census: for candidates where no public job feed was found, which hiring tool (if any) do their sites point to?

Answers "why are so few Spanish startups visible?" with data instead of a guess.

    python -m radar.census        # prints a table by HQ country; writes data/census.json
"""
from __future__ import annotations

import collections
import json
import re
from concurrent.futures import ThreadPoolExecutor

from .common import DATA, get
from .universe import CAREER_LINK, load_candidates

# Markers seen in careers pages / links. Order matters: first match wins.
MARKERS = [
    ("Factorial", r"factorialhr\.|factorial\.co/|\.factorial\.|careers\.factorialhr"),
    ("Teamtailor (custom domain)", r"teamtailor"),
    ("Workable", r"workable\.com"),
    ("Personio", r"personio\."),
    ("BambooHR", r"bamboohr\.com"),
    ("Welcome to the Jungle", r"welcometothejungle\.com|wttj"),
    ("Join.com", r"join\.com/companies"),
    ("Recruitee", r"recruitee\.com"),
    ("Greenhouse/Lever/Ashby", r"greenhouse\.io|lever\.co|ashbyhq\.com"),
    ("SmartRecruiters", r"smartrecruiters\.com"),
    ("InfoJobs", r"infojobs\.net"),
    ("Notion page", r"notion\.site|notion\.so"),
    ("Other ATS", r"hiringroom|talentclue|jobvite|recruitcrm|breezy\.hr|zohorecruit|jobylon|homerun\.co|"
                  r"pinpointhq|rippling|deel\.com/jobs|jobs\.gem\.com|dover\.com|hirehive|softgarden|"
                  r"successfactors|myworkdayjobs|icims|taleo"),
    ("LinkedIn only", r"linkedin\.com/(company/[^\"'/]+/jobs|jobs)"),
    ("Email only", r"mailto:[^\"']*(jobs|careers|talent|hr|rrhh|empleo|work)@"),
]


def classify_site(c: dict) -> str:
    dom = c["domain"]
    status, home = get(f"https://{dom}", timeout=8, accept="text/html")
    if status != 200:
        status, home = get(f"https://www.{dom}", timeout=8, accept="text/html")
    if status != 200:
        return "Site unreachable / bot wall"
    pages = [home]
    links = []
    for href in CAREER_LINK.findall(home):
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = f"https://{dom}{href}"
        if href.startswith("http"):
            links.append(href)
    for url in list(dict.fromkeys(links))[:2]:
        s, body = get(url, timeout=8, accept="text/html")
        if s == 200:
            pages.append(body)
    blob = "\n".join(pages)
    for name, rx in MARKERS:
        if re.search(rx, blob, re.I):
            return name
    return "Careers page, no tool detected" if links else "No careers link found"


def main() -> None:
    cache = json.loads((DATA / "resolve_cache.json").read_text(encoding="utf-8"))
    todo = [c for c in load_candidates() if cache.get(c["id"], {}).get("status") != "ok"]
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = list(ex.map(lambda c: (c, classify_site(c)), todo))
    out = [{"id": c["id"], "name": c["name"], "country": c["country"], "tool": tool} for c, tool in results]
    (DATA / "census.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    groups = {"ES": ["ES"], "PT+IT": ["PT", "IT"], "FR+DE+GB+NL": ["FR", "DE", "GB", "NL"]}
    cands = collections.Counter(c["country"] for c in load_candidates())
    for label, ccs in groups.items():
        n_all = sum(cands[cc] for cc in ccs)
        rows = [r for r in out if r["country"] in ccs]
        print(f"\n{label}: {n_all} candidates, {n_all - len(rows)} with a readable public feed "
              f"({(n_all - len(rows)) / n_all:.0%}); the rest, as share of all candidates:")
        for tool, n in collections.Counter(r["tool"] for r in rows).most_common():
            print(f"  {tool:<32} {n:>3}  ({n / n_all:.0%})")


if __name__ == "__main__":
    main()
