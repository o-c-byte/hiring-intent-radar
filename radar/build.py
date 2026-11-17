"""Score companies and write site/data.js for the page.

Company score = sum over its distinct signals of  strength weight (strong 3, medium 2, weak 1)
                                                 x recency factor (posting <= 30 days 1.0, 31-90 days 0.6, older 0.3)
              + hiring-volume bonus (open roles / 25, capped at 2).
"Distinct" = one per (signal type, target country); extra postings for the same move count as support, not score.

    python -m radar.build                                  # site/data.js (with private overlay if present)
    python -m radar.build --public --out <path>/data.js   # public build, no portfolio overlay
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

from .common import DATA, SITE, read_jsonl
from .geo import COUNTRIES, city_coords
from .universe import load_candidates

WEIGHT = {"strong": 3, "medium": 2, "weak": 1}
LABEL = {"market_expansion": "Market expansion", "upmarket": "Moving upmarket", "raise_prep": "Gearing up to raise",
         "ai_buildout": "AI build-out", "monetisation": "Monetisation shift", "new_product_line": "New product line",
         "regulatory_step": "Regulatory step", "hiring_surge": "Hiring surge"}

FUNCTIONS = [
    ("Data & AI", r"\b(ai|ml|llm|data|machine learning|analytics|scientist|bi)\b"),
    ("Engineering", r"engineer|developer|devops|sre\b|architect|qa\b|tech lead|cto|software|frontend|backend|platform|security"),
    ("Product & Design", r"product|design|ux|ui\b|research"),
    ("Sales", r"sales|account (executive|manager)|\bae\b|\bsdr\b|\bbdr\b|business development|partnership|commercial|country manager"),
    ("Marketing", r"marketing|growth|brand|content|seo|community|communications|pr\b"),
    ("Customer", r"customer|support|success|onboarding|implementation|service"),
    ("Finance & Legal", r"financ|account(ant|ing)|controller|legal|counsel|compliance|risk|tax|treasury|payroll|fp&a"),
    ("People", r"people|talent|recruit|hr\b|human resources"),
    ("Operations", r"operations|ops\b|logistics|supply|procurement|office|operator|care|nurse|driver"),
]


def function_of(title: str, dept: str) -> str:
    t = f"{title} {dept}".lower()
    for name, rx in FUNCTIONS:
        if re.search(rx, t):
            return name
    return "Other"


def recency(age) -> float:
    if age is None:
        return 0.6
    return 1.0 if age <= 30 else 0.6 if age <= 90 else 0.3


def main(argv: list[str]) -> None:
    public = "--public" in argv  # build without the private portfolio overlay
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else SITE / "data.js"
    universe = json.loads((DATA / "universe.json").read_text(encoding="utf-8"))
    posts = read_jsonl(DATA / "postings.jsonl")
    signals = read_jsonl(DATA / "signals.jsonl")
    snap = json.loads((DATA / "snapshot.json").read_text(encoding="utf-8"))
    by_co_posts = collections.defaultdict(list)
    for p in posts:
        by_co_posts[p["company_id"]].append(p)
    by_co_sig = collections.defaultdict(list)
    for s in signals:
        by_co_sig[s["company_id"]].append(s)

    companies, feed, arcs = [], [], []
    for c in universe:
        cps = by_co_posts[c["id"]]
        lat, lon = city_coords(c["hq_city"], c["country"])
        # computed signal: hiring surge (only from creation-type dates)
        dated = [p for p in cps if p["date_is_creation"] and p["age_days"] is not None]
        new30 = sum(1 for p in dated if p["age_days"] <= 30)
        sigs = list(by_co_sig[c["id"]])
        if new30 >= 8 and dated and new30 / len(cps) >= 0.4:
            sigs.append({"type": "hiring_surge", "strength": "strong" if new30 >= 15 else "medium", "country": "",
                         "evidence_quote": f"{new30} of {len(cps)} open roles first published in the last 30 days",
                         "interpretation": f"{c['name']} opened {new30} of its {len(cps)} current roles in the last 30 days.",
                         "title": "", "location": "", "url": "", "posted_at": snap["date"], "age_days": 0,
                         "computed": True})
        # distinct moves
        groups = collections.defaultdict(list)
        for s in sigs:
            key = (s["type"], s["country"] if s["type"] == "market_expansion" else "")
            groups[key].append(s)
        moves = []
        for (typ, cc), ss in groups.items():
            ss.sort(key=lambda s: (-WEIGHT[s["strength"]], s["age_days"] if s["age_days"] is not None else 999))
            best = ss[0]
            pts = WEIGHT[best["strength"]] * recency(best["age_days"])
            moves.append({"type": typ, "label": LABEL[typ], "country": cc,
                          "country_name": COUNTRIES.get(cc, (cc,))[0] if cc else "", "strength": best["strength"],
                          "points": round(pts, 2), "support": len(ss), "quote": best["evidence_quote"],
                          "interpretation": best["interpretation"], "title": best["title"],
                          "location": best["location"], "url": best["url"], "posted_at": best["posted_at"], "date_field": best.get("date_field"),
                          "age_days": best["age_days"], "computed": best.get("computed", False)})
        moves.sort(key=lambda m: -m["points"])
        # Cap: market expansion scores for at most 3 countries, so a board with sales roles everywhere cannot win on
        # breadth alone. Further countries stay visible with 0 points.
        seen_exp = 0
        for m in moves:
            if m["type"] == "market_expansion":
                seen_exp += 1
                if seen_exp > 3:
                    m["points"], m["capped"] = 0.0, True
        bonus = min(2.0, len(cps) / 25)
        score = round(sum(m["points"] for m in moves) + bonus, 1)
        funcs = collections.Counter(function_of(p["title"], p["department"]) for p in cps)
        weeks = collections.Counter()
        for p in dated:
            if p["age_days"] <= 26 * 7:
                weeks[p["age_days"] // 7] += 1
        co = {"id": c["id"], "name": c["name"], "domain": c["domain"], "city": c["hq_city"], "country": c["country"],
              "country_name": COUNTRIES.get(c["country"], (c["country"],))[0], "lat": lat, "lon": lon,
              "sector": c["sector"], "stage": c["stage_approx"], "round": c.get("round"),
              "portfolio": c["portfolio"] and not public, "platform": c["platform"], "open_roles": len(cps), "new_30d": new30,
              "functions": funcs.most_common(), "weeks": [weeks.get(i, 0) for i in range(25, -1, -1)],
              "countries": collections.Counter(cc for p in cps for cc in p["countries"]).most_common(),
              "moves": moves, "score": score, "volume_bonus": round(bonus, 2)}
        companies.append(co)
        for m in moves:
            feed.append({"company": c["id"], **m})
            if m["type"] == "market_expansion" and m["country"] in COUNTRIES and m["country"] != c["country"]:
                _, tlat, tlon = COUNTRIES[m["country"]]
                arcs.append({"company": c["id"], "from": [lon, lat], "to": [tlon, tlat], "country": m["country"],
                             "country_name": m["country_name"], "strength": m["strength"]})

    companies.sort(key=lambda c: -c["score"])
    for i, c in enumerate(companies, 1):
        c["rank"] = i
    feed.sort(key=lambda f: (f["computed"], f["age_days"] if f["age_days"] is not None else 999, -f["points"]))
    month = [f for f in feed if f["age_days"] is not None and f["age_days"] <= 30]
    data = {
        "snapshot": snap["date"], "generated": dt.datetime.now().isoformat(timespec="minutes"),
        "stats": {"candidates": len(load_candidates()), "companies": len(companies), "roles": len(posts), "signals": len(feed),
                  "signals_30d": len(month), "countries_hq": len({c["country"] for c in companies}),
                  "expansion_arcs": len(arcs)},
        "labels": LABEL, "companies": companies, "feed": feed, "arcs": arcs,
    }
    # Coverage: share of candidates with a readable public job feed, Spain vs the four largest northern ecosystems.
    cache = json.loads((DATA / "resolve_cache.json").read_text(encoding="utf-8"))
    cands = load_candidates()
    for key, ccs in (("es", {"ES"}), ("north", {"FR", "DE", "GB", "NL"})):
        group = [c for c in cands if c["country"] in ccs]
        ok = sum(1 for c in group if cache.get(c["id"], {}).get("status") == "ok")
        data["stats"][f"coverage_{key}"] = {"candidates": len(group), "with_feed": ok}
    bets = DATA / "bets.json"
    if bets.exists():
        data["bets"] = json.loads(bets.read_text(encoding="utf-8"))
    out.parent.mkdir(exist_ok=True)
    out.write_text("window.RADAR = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"{out.name}: {len(companies)} companies, {len(feed)} moves, {len(arcs)} expansion arcs"
          + (" (public build, no portfolio overlay)" if public else ""))
    for c in companies[:15]:
        print(f"  {c['rank']:>2}. {c['name']:<24} {c['score']:>5}  {', '.join(m['label'] + (' ' + m['country'] if m['country'] else '') for m in c['moves'][:4])}")


if __name__ == "__main__":
    main(sys.argv[1:])
