"""Build the company universe: candidates -> live public ATS board (>= MIN_ROLES open roles).

Resolution order per company:
  1. read its own website (/, /careers, /jobs ...) and look for an ATS link (most reliable: the company points to it);
  2. look the slug up in data/seed_ats_slugs_raw.json;
  3. try slug variants against each ATS endpoint. A guessed board is only accepted if its postings mention the
     company name or domain (guards against a same-named stranger's board).
Writes data/universe.json and caches raw boards in data/raw/<id>.json. Re-runs skip companies already resolved.

    python -m radar.universe            # resolve new candidates
    python -m radar.universe --retry    # also retry ones that failed before
    python -m radar.universe --from-cache  # only rewrite data/universe.json from the cache
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from .ats import FETCHERS
from .common import DATA, RAW, get, slugify

MIN_ROLES = 3
KEEP_STAGES = {"pre-seed", "seed", "a", "b", ""}
CACHE = DATA / "resolve_cache.json"
OUT = DATA / "universe.json"

ATS_PATTERNS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)"),
    ("greenhouse", r"greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)"),
    ("lever", r"jobs(?:\.eu)?\.lever\.co/([A-Za-z0-9_.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("personio", r"([A-Za-z0-9-]+)\.jobs\.personio\.(?:com|de)"),
    ("recruitee", r"([A-Za-z0-9-]+)\.recruitee\.com"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("teamtailor", r"([A-Za-z0-9-]+)\.teamtailor\.com"),
    ("bamboohr", r"([A-Za-z0-9-]+)\.bamboohr\.com"),
]
BAD_SLUGS = {"embed", "api", "v0", "v1", "jobs", "www", "app", "careers", "job_board", "static", "assets", "js", "cdn"}
CAREER_LINK = re.compile(r'href="([^"#]*?(?:career|jobs|join|trabaja|empleo|vacantes|work-with-us|hiring)[^"#]*)"', re.I)
PROBE_ORDER = ["greenhouse", "ashby", "lever", "personio", "recruitee", "teamtailor"]  # workable rate-limits probes: site detection only


def portfolio_domains() -> set[str]:
    """Optional private overlay: a markdown table of portfolio companies (2nd column = domain) to mark on the page.
    Not part of the public repo; without it nothing is marked."""
    path = DATA / "portfolio_overlay.md"
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    return {m.lower() for m in re.findall(r"^\|[^|]+\|\s*([a-z0-9.-]+\.[a-z.]+)\s*\|", text, re.M)}


SECTOR_KEYWORDS = [  # free-text sector (press) -> radar sector slug; first match wins
    ("legal", r"legal|law"), ("hr-work", r"\bhr\b|hiring|recruit|talent|workforce|payroll|employee|staffing|frontline"),
    ("health", r"health|medic|clinic|care|pharma|patient|dental|veterin|mental|wellbeing"),
    ("insurtech", r"insur"), ("fintech", r"fintech|financ|payment|bank|lending|credit|invoice|accounting|treasury|tax|wealth|invest|cfo"),
    ("edtech", r"edtech|education|learning|school|student|tutor"),
    ("martech-adtech", r"marketing|adtech|advertis|martech|sales|crm|e-?commerce|retail|customer"),
    ("climate-energy", r"energy|climate|carbon|solar|battery|sustainab|esg|grid"),
    ("proptech-construction", r"proptech|real estate|construction|property|housing"),
    ("security", r"secur|cyber|fraud|identity"), ("travel-mobility", r"travel|mobility|logistic|fleet|transport|freight"),
    ("devtools-data", r"developer|devtool|infrastructure|data platform|database|observability|inference|api"),
    ("marketplace", r"marketplace"), ("vertical-ai", r"\bai\b|agent|llm|machine learning|automation"),
    ("consumer", r"consumer|app|gaming|social|food"),
]
KNOWN_SECTORS = {k for k, _ in SECTOR_KEYWORDS} | {"productivity-saas"}


def sector_slug(text: str) -> str:
    if text in KNOWN_SECTORS:
        return text
    for slug, rx in SECTOR_KEYWORDS:
        if re.search(rx, text or "", re.I):
            return slug
    return "productivity-saas"


def load_candidates() -> list[dict]:
    rows: dict[str, dict] = {}
    with (DATA / "candidates_base.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["round_src"] = ""
            rows[r["domain"].lower()] = r
    recent = DATA / "candidates_recent.csv"
    if recent.exists():
        with recent.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                dom = (r.get("domain") or "").lower().strip()
                if not dom:
                    continue
                rnd = (r.get("round") or "").lower()
                stage = "seed" if "seed" in rnd else "a" if "series a" in rnd or rnd == "a" else \
                        "b" if "series b" in rnd or rnd == "b" else rnd
                base = rows.get(dom, {})
                rows[dom] = {
                    "name": r["name"], "domain": dom, "hq_city": r.get("hq_city") or base.get("hq_city", ""),
                    "country": (r.get("country_iso2") or base.get("country", "")).upper(),
                    "stage_approx": stage, "sector": base.get("sector") or r.get("sector", ""),
                    "round_src": json.dumps({k: r.get(k) for k in ("round", "amount_eur_m", "announced", "source_url")}),
                }
    port = portfolio_domains()
    out = []
    for dom, r in rows.items():
        r["portfolio"] = dom in port
        if r["stage_approx"].lower() not in KEEP_STAGES:
            continue
        r["id"] = slugify(r["name"])
        r["sector_text"] = r["sector"]
        r["sector"] = sector_slug(r["sector"])
        out.append(r)
    return out


def seed_index() -> dict[str, tuple[str, str]]:
    """Optional lookup of known ATS slugs (a private file, not in the public repo). Without it, step 2 is skipped."""
    path = DATA / "seed_ats_slugs_raw.json"
    if not path.exists():
        return {}
    d = json.loads(path.read_text(encoding="utf-8"))
    return {b["slug"].lower(): (b["platform"], b["slug"]) for b in d["boards"]}


def variants(c: dict) -> list[str]:
    name = c["name"].lower()
    stem = c["domain"].split(".")[0].lower()
    v = [re.sub(r"[^a-z0-9]", "", name), slugify(name), stem, stem + "hq"]
    first = re.split(r"[^a-z0-9]", name)[0]
    if len(first) >= 4:
        v.append(first)
    return [x for x in dict.fromkeys(v) if x]


def mentions_company(posts: list[dict], c: dict) -> bool:
    keys = {c["name"].lower(), c["domain"].split(".")[0].lower(), c["domain"].lower()}
    keys = {k for k in keys if len(k) >= 3}
    blob = " ".join((p["title"] + " " + p["text"][:4000]).lower() for p in posts[:15])
    return any(k in blob for k in keys)


def _scan(body: str) -> list[tuple[str, str]]:
    found = []
    for platform, pat in ATS_PATTERNS:
        for m in re.finditer(pat, body):
            slug = m.group(1).strip(".")
            if slug.lower() not in BAD_SLUGS:
                found.append((platform, slug))
    return found


def detect_from_site(c: dict) -> list[tuple[str, str]]:
    """Homepage -> ATS link; else follow up to 3 career-looking links found on it; else careers./jobs. subdomains."""
    dom = c["domain"]
    status, home = get(f"https://{dom}", timeout=8, accept="text/html")
    if status != 200:
        status, home = get(f"https://www.{dom}", timeout=8, accept="text/html")
    found = _scan(home)
    if found:
        return list(dict.fromkeys(found))
    links = []
    for href in CAREER_LINK.findall(home or ""):
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = f"https://{dom}{href}"
        elif not href.startswith("http"):
            continue
        links.append(href)
    links = list(dict.fromkeys(links))[:3] + [f"https://{dom}/careers", f"https://careers.{dom}", f"https://jobs.{dom}"]
    for url in list(dict.fromkeys(links)):
        status, body = get(url, timeout=8, accept="text/html")
        if status == 200:
            found = _scan(body)
            if found:
                return list(dict.fromkeys(found))
    return []


def resolve(c: dict, seeds: dict) -> dict:
    tried = []
    # 1. company's own site
    for platform, slug in detect_from_site(c):
        tried.append(f"site:{platform}:{slug}")
        if platform not in FETCHERS:
            return {"status": "unsupported", "platform": platform, "slug": slug, "tried": tried}
        posts = FETCHERS[platform](slug)
        if posts:
            return {"status": "ok", "platform": platform, "slug": slug, "via": "site", "posts": posts}
    # 2 + 3. seed list, then guessed slugs (with a name check)
    for v in variants(c):
        if v in seeds and seeds[v][0] in FETCHERS:
            platform, slug = seeds[v]
            tried.append(f"seed:{platform}:{slug}")
            posts = FETCHERS[platform](slug)
            if posts and mentions_company(posts, c):
                return {"status": "ok", "platform": platform, "slug": slug, "via": "seed-list", "posts": posts}
    order = PROBE_ORDER[:]
    random.Random(c["id"]).shuffle(order)  # spread load across ATS hosts
    for platform in order:
        for v in variants(c)[:2]:
            tried.append(f"probe:{platform}:{v}")
            posts = FETCHERS[platform](v)
            if posts and mentions_company(posts, c):
                return {"status": "ok", "platform": platform, "slug": v, "via": "slug-probe", "posts": posts}
    return {"status": "not-found", "tried": tried}


def main(argv: list[str]) -> None:
    retry = "--retry" in argv
    RAW.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    cands = load_candidates()
    seeds = seed_index()
    todo = [c for c in cands if c["id"] not in cache or (retry and cache[c["id"]]["status"] != "ok")]
    if "--from-cache" in argv:  # rebuild universe.json from what is already resolved, no network
        todo = []
    print(f"{len(cands)} candidates in stage range, {len(todo)} to resolve", flush=True)

    with ThreadPoolExecutor(max_workers=48) as ex:
        futs = {ex.submit(resolve, c, seeds): c for c in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            c = futs[fut]
            try:
                res = fut.result()
            except Exception as e:  # keep going; record the failure
                res = {"status": "error", "error": repr(e)}
            posts = res.pop("posts", None)
            if posts is not None:
                res["open_roles"] = len(posts)
                (RAW / f"{c['id']}.json").write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
            cache[c["id"]] = res
            print(f"[{i}/{len(todo)}] {c['name']}: {res['status']} {res.get('platform', '')} "
                  f"{res.get('slug', '')} {res.get('open_roles', '')}", flush=True)
            if i % 5 == 0:
                CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    if todo:
        CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")

    overrides = json.loads((DATA / "board_overrides.json").read_text(encoding="utf-8"))
    universe, rejected = [], []
    for c in cands:
        r = cache.get(c["id"], {})
        if r.get("status") == "ok" and r.get("open_roles", 0) >= MIN_ROLES:
            ok, why = board_plausible(c, r, overrides)
            if not ok:
                rejected.append(f"{c['name']} ({r['platform']}:{r['slug']}): {why}")
                continue
            universe.append({k: c[k] for k in ("id", "name", "domain", "hq_city", "country", "stage_approx",
                                                "sector", "portfolio")}
                            | {"round": json.loads(c["round_src"]) if c["round_src"] else None,
                               "platform": r["platform"], "slug": r["slug"], "resolved_via": r["via"],
                               "open_roles": r["open_roles"]})
    OUT.write_text(json.dumps(universe, indent=1, ensure_ascii=False), encoding="utf-8")
    stats = {}
    for r in cache.values():
        stats[r["status"]] = stats.get(r["status"], 0) + 1
    print(f"universe: {len(universe)} companies with >= {MIN_ROLES} roles; resolution stats {stats}")
    if rejected:
        print(f"rejected {len(rejected)} implausible boards:\n  " + "\n  ".join(rejected))


def board_plausible(c: dict, r: dict, overrides: dict) -> tuple[bool, str]:
    """A board found on the company's own site is trusted. A guessed one (seed list or slug probe) must show it is the
    same company: its postings mention the company's domain, or at least 30% of located roles are in the HQ country.
    data/board_overrides.json records manual decisions (reject same-name strangers, allow verified exceptions)."""
    if c["id"] in overrides["reject"]:
        return False, "manual: " + overrides["reject"][c["id"]]
    if r.get("via") == "site" or c["id"] in overrides["allow"]:
        return True, ""
    from .geo import countries_in
    posts = json.loads((RAW / f"{c['id']}.json").read_text(encoding="utf-8"))
    if any(c["domain"].lower() in (p["text"] + " " + (p["url"] or "")).lower() for p in posts):
        return True, ""
    located = [cc for p in posts for cc in countries_in(p["locations"], p.get("country_codes", []))]
    share = located.count(c["country"]) / len(located) if located else 0
    return (share >= 0.3, f"domain never mentioned and only {share:.0%} of roles in HQ country {c['country']}")


if __name__ == "__main__":
    main(sys.argv[1:])
