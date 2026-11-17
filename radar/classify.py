"""Classify postings into strategic signals.

Two stages:
  1. Rules (deterministic, free): flag postings whose title, location or text could carry a signal.
     Everything else is ignored. This keeps model calls to the postings that matter.
  2. Claude reads each flagged posting and decides which signals it really supports, with a verbatim quote.
     A quote that is not found word-for-word in the full posting is discarded by code (no invented evidence).
     Default: done in a Claude Code session (no API cost). Rules write compact excerpts to data/batches/,
     Claude labels each batch into data/batches/*.out.jsonl, then --import verifies and assembles.

    python -m radar.classify --rules-only     # stage 1 only: print how many postings are flagged
    python -m radar.classify --export         # write excerpt batches for in-session labelling
    python -m radar.classify --import         # verify quotes, write data/signals.jsonl
    python -m radar.classify --api            # optional: label via the Anthropic API instead (paid)
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from .common import DATA, ROOT, read_jsonl, write_jsonl
from .geo import COUNTRIES

SIGNAL_TYPES = ["market_expansion", "upmarket", "raise_prep", "ai_buildout", "monetisation", "new_product_line",
                "regulatory_step"]

# ------------------------------------------------------------------ stage 1: rules
R = lambda p: re.compile(p, re.I)
TITLE_RULES = {
    "market_expansion": R(r"country manager|general manager|managing director|launch|market (lead|manager|expansion)|"
                          r"expansion|head of (?:[a-z]+ )?(spain|france|germany|italy|uk|dach|benelux|nordics|iberia|"
                          r"portugal|netherlands|poland|us|usa|north america|latam|mena)|city (launcher|manager)|"
                          r"\b(dach|benelux|nordics|iberia|latam|mena|north america|us market)\b"),
    "upmarket": R(r"enterprise|strategic account|key account|solutions? (engineer|architect|consultant)|"
                  r"sales engineer|pre-?sales|large account|global account|public sector|government"),
    "raise_prep": R(r"\bcfo\b|chief financial|head of finance|finance director|vp,? finance|fp&a|"
                    r"investor relations|corporate development|corp ?dev|financial controller|head of (strategy|bizops)"),
    "ai_buildout": R(r"\b(ai|ml|llm|genai|gen ai|nlp)\b|machine learning|artificial intelligence|applied scientist|"
                     r"research scientist|data scientist|prompt|agentic|agents?\b"),
    "monetisation": R(r"pricing|monetis|monetiz|revenue operations|revops|billing|partnerships?|channel|alliances|"
                      r"partner (manager|sales)|reseller|affiliate|payments? (product|lead)|growth (pm|product)"),
    "regulatory_step": R(r"compliance|mlro|aml\b|regulatory|risk officer|licen[cs]e|quality assurance.*(medical|mdr)|"
                         r"regulatory affairs|dpo\b|data protection officer"),
}
TEXT_RULES = {
    "market_expansion": R(r"(launch|expand|expansion|entering|enter) (in|into|to)? ?(the )?(new )?(market|country|"
                          r"spain|france|germany|italy|uk|united kingdom|portugal|netherlands|us\b|united states|"
                          r"dach|nordics|benelux|poland|latam|mexico|brazil)|first (hire|employee|team member) in|"
                          r"new market|international expansion|go-to-market in|local team in"),
    "upmarket": R(r"soc ?2|iso ?27001|enterprise (customers|clients|segment|deals|accounts)|fortune 500|"
                  r"move upmarket|upmarket|six[- ]figure|7-figure|procurement process"),
    "raise_prep": R(r"fundrais|investor (relations|updates|reporting)|board (reporting|meetings|pack)|"
                    r"due diligence|audit[- ]ready|\bipo\b|cap table"),
    "ai_buildout": R(r"\bllms?\b|large language model|generative ai|genai|ai-first|ai first|ai-native|"
                     r"rag\b|retrieval-augmented|fine-tun|agentic|ai agents?"),
    "monetisation": R(r"pricing (strategy|model|page)|monetis|monetiz|take rate|self-serve|product-led|plg\b|"
                      r"new revenue stream|usage-based|paywall|subscription tiers?"),
    "new_product_line": R(r"new product|0 ?(to|->|→) ?1|zero to one|greenfield|new business (line|unit)|"
                          r"launch(ing)? (a|our) new|brand[- ]new (product|team)|first (product|engineer) (on|in|for) (the|our) new"),
    "regulatory_step": R(r"\bemi\b|e-money|electronic money|mica\b|psd2|payment institution|banking licen|"
                         r"medical device|mdr\b|ce mark|fca\b|bafin|cnmv|banco de espa|insurance licen|"
                         r"regulated (entity|activity)"),
}


BUILDER = R(r"engineer|developer|product|data|research|architect|cto|head of (engineering|technology|product)")


SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")


def sentences(text: str) -> list[str]:
    return [x.strip() for x in SENT_SPLIT.split(text) if x.strip()]


def own_text(post: dict, ctx: dict) -> str:
    """Posting text minus the company's boilerplate (sentences repeated across many of its postings)."""
    return "\n".join(x for x in sentences(post["text"]) if x not in ctx["boilerplate"])


def rule_flags(post: dict, ctx: dict) -> list[str]:
    title, text = post["title"], own_text(post, ctx)
    flags = {k for k, rx in TITLE_RULES.items() if rx.search(title)}
    flags |= {k for k, rx in TEXT_RULES.items() if rx.search(text)}
    # Text-only AI mentions ("we use AI tools") count only for roles that would build it.
    if "ai_buildout" in flags and not TITLE_RULES["ai_buildout"].search(title) and not BUILDER.search(title):
        flags.discard("ai_buildout")
    # Location rule: role sits in a non-HQ country where the company has only a handful of roles.
    for cc in post["countries"]:
        if cc != ctx["hq"] and ctx["country_roles"].get(cc, 0) <= 3 and not post["remote_only"]:
            flags.add("market_expansion")
    # AI roles at AI-native companies are business as usual, not a build-out signal.
    if ctx["sector"] == "vertical-ai" or ctx["sector"] == "devtools-data":
        flags.discard("ai_buildout")
    return sorted(flags)


def company_contexts(universe: list[dict], posts: list[dict]) -> dict:
    ctx = {}
    by_co = collections.defaultdict(list)
    for p in posts:
        by_co[p["company_id"]].append(p)
    for c in universe:
        cps = by_co[c["id"]]
        counts = collections.Counter(cc for p in cps for cc in p["countries"])
        # Boilerplate = a sentence that appears in at least 3 postings and 30% of the company's board.
        seen = collections.Counter(x for p in cps for x in set(sentences(p["text"])))
        floor = max(3, 0.3 * len(cps))
        boiler = {x for x, n in seen.items() if n >= floor}
        # Boilerplate that itself carries a signal is labelled once per company, against one reference posting.
        boiler_hits = []
        for x in sorted(boiler):
            if any(rx.search(x) for rx in TEXT_RULES.values()):
                ref = next(p for p in cps if x in p["text"])
                boiler_hits.append((x[:400], ref["job_id"], seen[x]))
        ctx[c["id"]] = {"name": c["name"], "hq": c["country"], "hq_city": c["hq_city"], "sector": c["sector"],
                        "open_roles": len(cps), "country_roles": dict(counts), "boilerplate": boiler,
                        "boiler_hits": boiler_hits}
    return ctx


# ------------------------------------------------------------------ stage 2: Claude
SYSTEM = """You read one job posting from a European startup and decide which strategic moves it reveals.
An investor will read your output, so be strict: most postings reveal nothing beyond normal hiring.

Signal types (use exactly these keys):
- market_expansion: the company is entering or building a market outside its HQ country. Evidence: a market-facing
  role (country/general manager, sales, partnerships, operations, marketing, customer success, launch) located in a
  country where it has few or no other roles, or text about launching in / expanding to a named country or region.
  Engineers or back-office staff hired remotely abroad are NOT market expansion. Set "country" to the ISO-3166 alpha-2
  code of the target market (one per signal; use "EU" only if the text names no single country).
- upmarket: selling to larger customers: first enterprise/strategic AEs, solutions engineers, enterprise security or
  compliance certifications (SOC 2, ISO 27001) required by customers, procurement-heavy deals.
- raise_prep: building the finance function an investor process needs: CFO, head of finance, FP&A, investor
  relations, board reporting, audit readiness, fundraising mentioned as part of the job.
- ai_buildout: a company whose core product is not AI is building AI/ML capability (applied AI team, LLM features,
  ML platform). Do not use this for companies that already sell an AI product.
- monetisation: a change in how the company makes money: pricing roles, billing/revenue operations, moving from
  self-serve to sales-led or the reverse, partnerships/channel as a new revenue line, marketplace take rate.
- new_product_line: a new product, business line or team the posting presents as new (0 to 1, "our new X").
- regulatory_step: obtaining or operating under a licence or regulated status (EMI, payment institution, MiCA,
  insurance, medical device, banking), with compliance roles tied to it.

Strength: strong = the posting states the move explicitly (e.g. "Country Manager Italy to launch our Italian
market", "our first enterprise AE"). medium = clear implication from the role and its location or scope. weak =
plausible but generic. Do not output weak signals unless nothing better exists in the posting; prefer none.

For each signal give:
- evidence_quote: a short verbatim excerpt (6 to 30 words) copied character-for-character from the posting title or
  text. Do not paraphrase, translate, fix typos or join separate sentences. If you cannot quote it, drop the signal.
- interpretation: one plain sentence (max 18 words) saying what the company is doing, written for an investor.
  No dashes as connectors, no hype words.

Return {"signals": []} when the posting shows only ordinary hiring."""

SCHEMA = {
    "type": "object",
    "properties": {"signals": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": SIGNAL_TYPES},
            "strength": {"type": "string", "enum": ["strong", "medium", "weak"]},
            "country": {"type": "string"},
            "evidence_quote": {"type": "string"},
            "interpretation": {"type": "string"},
        },
        "required": ["type", "strength", "country", "evidence_quote", "interpretation"],
        "additionalProperties": False}}},
    "required": ["signals"],
    "additionalProperties": False,
}


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


def quote_found(quote: str, post: dict) -> bool:
    q = _norm(quote).strip(" .\"'…")
    if len(q) < 8:
        return False
    hay = _norm(post["title"] + "\n" + post["text"])
    if q in hay:
        return True
    # tolerate an ellipsis joining two verbatim fragments
    parts = [x.strip(" .") for x in re.split(r"\.\.\.|…", q) if len(x.strip()) >= 8]
    return len(parts) > 1 and all(x in hay for x in parts)


def user_message(post: dict, ctx: dict) -> str:
    roles = ", ".join(f"{COUNTRIES.get(k, (k,))[0]}: {v}" for k, v in
                      sorted(ctx["country_roles"].items(), key=lambda kv: -kv[1])) or "unknown"
    return (f"Company: {ctx['name']} (HQ {ctx['hq_city']}, {COUNTRIES.get(ctx['hq'], (ctx['hq'],))[0]}; "
            f"sector {ctx['sector']}; {ctx['open_roles']} open roles; roles by country: {roles})\n"
            f"Rule hints (may be wrong): {', '.join(post['flags'])}\n\n"
            f"Title: {post['title']}\nLocation: {post['location']}\nDepartment: {post['department']}\n"
            f"Posted: {post['posted_at']}\n\nPosting text:\n{post['text']}")


def excerpt(post: dict, ctx: dict, max_chars: int = 900) -> str:
    """Non-boilerplate sentences that triggered a text rule, in posting order, capped."""
    keep = [x for x in sentences(own_text(post, ctx)) if any(rx.search(x) for rx in TEXT_RULES.values())]
    out, n = [], 0
    for x in keep:
        x = x[:400]
        if n + len(x) > max_chars:
            break
        out.append(x)
        n += len(x)
    return " / ".join(out)


def export_batches(flagged: list[dict], ctxs: dict, size: int = 60) -> None:
    """Write data/batches/batch_NNN.in.txt grouped by company, plus .keys.json listing what each batch covers.
    A batch counts as done once batch_NNN.out.jsonl exists; re-export only writes what is left."""
    bdir = DATA / "batches"
    bdir.mkdir(exist_ok=True)
    done = set()
    for kf in bdir.glob("batch_*.keys.json"):
        if kf.with_name(kf.name.replace(".keys.json", ".out.jsonl")).exists():
            done |= {tuple(k) for k in json.loads(kf.read_text(encoding="utf-8"))}
        else:
            kf.unlink()
            kf.with_name(kf.name.replace(".keys.json", ".in.txt")).unlink(missing_ok=True)
    by_co = collections.defaultdict(list)
    for p in flagged:
        if (p["company_id"], p["job_id"]) not in done:
            by_co[p["company_id"]].append(p)
    for cid, c in ctxs.items():
        if c["boiler_hits"] and (cid, "*boilerplate*") not in done:
            by_co.setdefault(cid, [])
    n_next = max([int(f.name[6:9]) for f in bdir.glob("batch_*.keys.json")] + [-1]) + 1
    blocks, keys, count, written = [], [], 0, 0

    def flush():
        nonlocal blocks, keys, count, n_next, written
        if blocks:
            (bdir / f"batch_{n_next:03d}.in.txt").write_text("\n".join(blocks), encoding="utf-8")
            (bdir / f"batch_{n_next:03d}.keys.json").write_text(json.dumps(keys), encoding="utf-8")
            n_next, written = n_next + 1, written + 1
        blocks, keys, count = [], [], 0

    for cid in sorted(by_co):
        c, ps = ctxs[cid], sorted(by_co[cid], key=lambda p: p["job_id"])
        roles = ", ".join(f"{k}:{v}" for k, v in sorted(c["country_roles"].items(), key=lambda kv: -kv[1])[:8])
        lines = [f"# COMPANY {cid} = {c['name']} | HQ {c['hq_city']}, {c['hq']} | {c['sector']} | "
                 f"{c['open_roles']} open roles | by country: {roles or 'n/a'}"]
        if c["boiler_hits"] and (cid, "*boilerplate*") not in done:
            for x, ref, n in c["boiler_hits"]:
                lines.append(f"  BOILERPLATE (in {n} postings; ref job {ref}): {x}")
            keys.append([cid, "*boilerplate*"])
        for p in ps:
            ex = excerpt(p, c)
            lines.append(f"  ## {p['job_id']} | {p['title']} | {p['location'] or 'no location'} | "
                         f"{p['department'] or '-'} | hints: {', '.join(p['flags'])}"
                         + (f"\n     TEXT: {ex}" if ex else ""))
            keys.append([cid, p["job_id"]])
        blocks.append("\n".join(lines) + "\n")
        count += max(1, len(ps))
        if count >= size:
            flush()
    flush()
    total = sum(len(v) for v in by_co.values())
    print(f"{total} postings + {sum(1 for c in by_co if ctxs[c]['boiler_hits'])} company boilerplate blocks "
          f"in {written} new batches under data/batches/ ({len(done)} items already labelled)")


MARKET_FACING = R(r"account (executive|manager|director)|\b(ae|sdr|bdr)\b|sales|business development|country manager|"
                  r"general manager|managing director|partnerships?|customer success|marketing|growth|launch|"
                  r"city (manager|launcher)|market (lead|manager)|key account|commercial|expansion|operations manager")
NAMED_MARKET = R(r"country manager|general manager|managing director|launch|\b(dach|benelux|nordics|iberia|latam|"
                 r"apac|mena|north america|spain|france|germany|italy|portugal|netherlands|poland|uk|us|usa|mexico|"
                 r"brazil|colombia|peru|chile|japan|singapore|australia|canada|nordic|deutschland|españa|italia)\b")


def title_expansion_signals(posts: list[dict], ctxs: dict) -> list[dict]:
    """Deterministic expansion signal: a market-facing role located in a country other than HQ where the company has
    at most 3 roles. Evidence = the job title (verbatim). Strength medium when the title names a market or a
    country-lead role, weak otherwise. Labelled signals for the same company and country take precedence in scoring."""
    out = []
    for p in posts:
        c = ctxs[p["company_id"]]
        if p["remote_only"] or not MARKET_FACING.search(p["title"]):
            continue
        for cc in p["countries"]:
            n = c["country_roles"].get(cc, 0)
            if cc == c["hq"] or n > 3 or cc not in COUNTRIES:
                continue
            out.append({"company_id": p["company_id"], "job_id": p["job_id"], "title": p["title"],
                        "location": p["location"], "url": p["url"], "posted_at": p["posted_at"],
                        "date_field": p["date_field"], "age_days": p["age_days"], "type": "market_expansion",
                        "strength": "medium" if NAMED_MARKET.search(p["title"]) else "weak", "country": cc,
                        "evidence_quote": p["title"], "rule": True,
                        "interpretation": f"{c['name']} is hiring a market-facing role in {COUNTRIES[cc][0]}, "
                                          f"where it has {n} open role{'s' if n != 1 else ''}."})
    return out


def import_batches(posts: list[dict], ctxs: dict) -> None:
    """Read every batch_*.out.jsonl ({"company_id", "job_id", "signals": [...]}) and keep signals that pass checks."""
    by_key = {(p["company_id"], p["job_id"]): p for p in posts}
    signals, dropped, bad = [], collections.Counter(), 0
    for f in sorted((DATA / "batches").glob("*.out.jsonl")):
        for rec in read_jsonl(f):
            p = by_key.get((rec["company_id"], str(rec["job_id"])))
            if not p:
                bad += 1
                continue
            for sig in rec.get("signals", []):
                if sig.get("type") not in SIGNAL_TYPES:
                    dropped["bad type"] += 1
                elif sig.get("strength") not in ("strong", "medium", "weak"):
                    dropped["bad strength"] += 1
                elif not quote_found(sig.get("evidence_quote", ""), p):
                    dropped["quote not verbatim"] += 1
                else:
                    signals.append({"company_id": p["company_id"], "job_id": p["job_id"], "title": p["title"],
                                    "location": p["location"], "url": p["url"], "posted_at": p["posted_at"],
                                    "date_field": p["date_field"], "age_days": p["age_days"], **sig,
                                    "country": (sig.get("country") or "").upper()})
    rule_sigs = title_expansion_signals(posts, ctxs)
    write_jsonl(DATA / "signals.jsonl", signals + rule_sigs)
    print(f"+ {len(rule_sigs)} rule-based expansion signals (market-facing title in a thin non-HQ country)")
    print(f"{len(signals)} verified signals -> data/signals.jsonl (dropped: {dict(dropped)}; unknown ids: {bad})")


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))


def classify_one(client, model: str, post: dict, ctx: dict) -> dict:
    import anthropic
    try:
        resp = client.beta.messages.create(
            model=model,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_message(post, ctx)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
    except anthropic.BadRequestError as e:
        return {"error": f"bad_request: {e.message}"}
    except anthropic.APIStatusError as e:
        return {"error": f"api_{e.status_code}"}
    except anthropic.APIConnectionError:
        return {"error": "connection"}
    if resp.stop_reason == "refusal":
        return {"error": "refusal"}
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        signals = json.loads(text)["signals"]
    except (json.JSONDecodeError, KeyError):
        return {"error": f"unparsable ({resp.stop_reason})"}
    u = resp.usage
    return {"signals": signals, "usage": [u.input_tokens, u.output_tokens,
                                          getattr(u, "cache_read_input_tokens", 0) or 0]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules-only", action="store_true")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--import", dest="do_import", action="store_true")
    ap.add_argument("--api", action="store_true", help="paid: label via the Anthropic API")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    universe = json.loads((DATA / "universe.json").read_text(encoding="utf-8"))
    posts = read_jsonl(DATA / "postings.jsonl")
    ctxs = company_contexts(universe, posts)
    for p in posts:
        p["flags"] = rule_flags(p, ctxs[p["company_id"]])
    flagged = [p for p in posts if p["flags"]]
    print(f"{len(posts)} postings, {len(flagged)} flagged by rules "
          f"({collections.Counter(f for p in flagged for f in p['flags']).most_common()})")
    approx_in = sum(len(user_message(p, ctxs[p['company_id']])) for p in flagged) / 3.6
    print(f"~{approx_in / 1e6:.2f}M input tokens for the model stage")
    if args.export:
        return export_batches(flagged, ctxs)
    if args.do_import:
        return import_batches(posts, ctxs)
    if not args.api:  # rules-only, or no mode chosen
        return

    load_env()
    import anthropic
    client = anthropic.Anthropic(max_retries=4)
    cache_path = DATA / "llm_cache.jsonl"
    cache = {(r["company_id"], r["job_id"], r["model"]): r for r in read_jsonl(cache_path) if "signals" in r}
    todo = [p for p in flagged if (p["company_id"], p["job_id"], args.model) not in cache]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} postings to send to {args.model} ({len(flagged) - len(todo)} cached)", flush=True)

    lock = threading.Lock()
    totals = collections.Counter()
    with cache_path.open("a", encoding="utf-8") as out, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(classify_one, client, args.model, p, ctxs[p["company_id"]]): p for p in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            p = futs[fut]
            res = fut.result()
            rec = {"company_id": p["company_id"], "job_id": p["job_id"], "model": args.model, **res}
            with lock:
                if "signals" in res:
                    cache[(p["company_id"], p["job_id"], args.model)] = rec
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()
                    totals.update({"in": res["usage"][0], "out": res["usage"][1], "cached": res["usage"][2]})
                else:
                    totals[res["error"]] += 1
            if i % 50 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} done; tokens {dict(totals)}", flush=True)

    # Assemble verified signals
    by_key = {(p["company_id"], p["job_id"]): p for p in flagged}
    signals, dropped = [], 0
    for (cid, jid, model), rec in cache.items():
        if model != args.model or (cid, jid) not in by_key:
            continue
        p = by_key[(cid, jid)]
        for s in rec["signals"]:
            if not quote_found(s["evidence_quote"], p):
                dropped += 1
                continue
            signals.append({"company_id": cid, "job_id": jid, "title": p["title"], "location": p["location"],
                            "url": p["url"], "posted_at": p["posted_at"], "date_field": p["date_field"],
                            "age_days": p["age_days"], **s, "country": s["country"].upper()})
    write_jsonl(DATA / "signals.jsonl", signals)
    print(f"{len(signals)} verified signals -> data/signals.jsonl ({dropped} dropped: quote not found verbatim)")


if __name__ == "__main__":
    main()
