# Hiring Intent Radar

**Live page:** https://otmarcarrion-byte.github.io/hiring-intent-radar/

Startups publish their plans in their job boards before they announce them. This project reads the public job boards
of European seed to Series B startups and turns open postings into dated, evidenced strategic signals: market
expansion, moving upmarket, preparing a funding round, AI build-out, monetisation changes, new product lines,
regulatory steps and hiring surges. Every signal cites its source posting with a verbatim quote.

Snapshot of 17 November 2026: 139 companies, 2,882 open roles, 267 detected moves.

## How it works

1. **Universe** (`radar/universe.py`). 435 candidate companies from funding announcements (July 2025 to November
   2026) and public startup lists. For each one the pipeline looks for an applicant-tracking-system (ATS) link on the
   company's own careers page, then tries likely board names. A guessed board is kept only if its postings mention the
   company's domain or at least 30% of its roles sit in the HQ country; `data/board_overrides.json` records the manual
   decisions (11 same-name boards rejected).
2. **Fetch** (`radar/fetch.py`, `radar/ats.py`). All open postings from the public JSON/RSS endpoints of Greenhouse,
   Lever, Ashby, Workable, Personio, Recruitee, SmartRecruiters and Teamtailor. No logins, no scraping of LinkedIn,
   at most one request per 1.1 seconds per host.
3. **Classify** (`radar/classify.py`). Keyword rules shortlist postings whose title, location or text may carry a
   signal and cut each one to the relevant sentences; company boilerplate repeated across postings is labelled once.
   Claude (in a Claude Code session) labels the excerpts against `docs/labelling_guide.md`, and the import step rejects
   any quote it cannot find word for word in the original posting. A rule adds weak or medium expansion signals for
   sales or country-lead roles in countries where a company has three or fewer roles, quoting the job title.
4. **Score and publish** (`radar/build.py`, `site/index.html`). Each distinct move scores strength (3/2/1) times
   recency (1.0 up to 30 days, 0.6 up to 90, 0.3 after), plus a hiring-volume bonus of open roles / 25 capped at 2.
   Market expansion scores in three countries at most.
5. **Coverage census** (`radar/census.py`). Checks which hiring tools the companies without a public feed use. Spain
   stands out: the pipeline found a public feed for 16% of 110 Spanish candidates, against 52% of 201 in France,
   Germany, the UK and the Netherlands.

## Run it

```
python -X utf8 -m radar.universe          # candidates -> live public ATS boards (data/universe.json)
python -X utf8 -m radar.fetch             # all open postings (data/postings.jsonl, not committed)
python -X utf8 -m radar.classify --export # rule shortlist -> excerpt batches (data/batches/*.in.txt)
#   label each batch in a Claude Code session -> data/batches/*.out.jsonl (docs/labelling_guide.md)
python -X utf8 -m radar.classify --import # verbatim-quote check -> data/signals.jsonl
python -X utf8 -m radar.build             # scores + site/data.js
python -X utf8 -m radar.census            # optional: which hiring tools invisible companies use
```

Python standard library only. The page is static HTML with D3 from a CDN; open `site/index.html` directly.

## Limits

- One snapshot. "Only role in Italy" describes today's board and does not prove a first hire.
- Companies cancel some roles before filling them and keep others open indefinitely.
- Companies without a public job feed do not appear, which under-represents Spain, Portugal and Italy.
- Posting dates come from each ATS's own field and can reset when a company reposts a role.

## Credits and rights

Built by Otmar Carrión (Valencia) with Claude Code, November 2026. Job-posting excerpts and quotes belong to the
companies that published them. Code: © 2026 Otmar Carrión, all rights reserved.
