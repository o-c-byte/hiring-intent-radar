# Labelling guide (in-session classification)

Input: `data/batches/batch_NNN.in.txt`. Output: `data/batches/batch_NNN.out.jsonl`. `python -m radar.classify --import`
then keeps only signals whose quote is found word for word in the full posting.

## Input format

```
# COMPANY <company_id> = <name> | HQ <city>, <ISO2> | <sector> | <N> open roles | by country: GB:21, US:14
  BOILERPLATE (in 35 postings; ref job <job_id>): <a sentence repeated across the company's postings>
  ## <job_id> | <title> | <location> | <department> | hints: <rule flags>
     TEXT: <sentences from the posting that triggered a rule, separated by " / ">
```

`hints` are what the keyword rules matched. They are often wrong. BOILERPLATE lines are company-level text that
appears in many postings (company description, "about us"); label them once, using the ref job id.

## Output format

One JSON object per line, only for postings (or boilerplate) that carry at least one signal:

```
{"company_id": "9fin", "job_id": "f19f80c7-...", "signals": [{"type": "market_expansion", "strength": "medium", "country": "US", "evidence_quote": "rapid expansion in the US", "interpretation": "9fin is building its US business, with sales and client roles in New York."}]}
```

Always create the `.out.jsonl` file, even if empty: its existence marks the batch as done.

## Be strict

An investor reads the output. Most postings reveal nothing beyond normal hiring; output nothing for them.

## Signal types (exact keys)

- `market_expansion`: entering or building a market outside the HQ country. A market-facing role (country or general
  manager, sales, partnerships, operations, marketing, customer success, launch) in a country where the company has
  few or no other roles, or text about launching in or expanding to a named country. Engineers or back-office staff
  hired remotely abroad are NOT expansion. `country` = ISO-2 of the target market (one per signal; "EU" only if no
  single country is named).
- `upmarket`: selling to larger customers: first enterprise or strategic account roles, solutions engineers,
  customer-required SOC 2 / ISO 27001, procurement-heavy deals, very large books of business.
- `raise_prep`: building the finance function an investor process needs: CFO, head of finance, FP&A, investor
  relations, board reporting, audit readiness, fundraising as part of the job.
- `ai_buildout`: a company whose product is not AI is building AI/ML capability (applied AI team, LLM features, ML
  platform). Not for companies that already sell an AI product.
- `monetisation`: a change in how the company makes money: pricing roles, billing or revenue operations, a move
  between self-serve and sales-led, partnerships or channel as a new revenue line, marketplace take rate.
- `new_product_line`: a product, business line or team the posting presents as new ("greenfield", "0 to 1", "our
  new X"). Generic "new features" does not count.
- `regulatory_step`: obtaining or operating under a licence (EMI, payment institution, MiCA, insurance, medical
  device, banking), with compliance roles tied to it.

`strength`: strong = stated explicitly ("Country Manager Italy to launch our Italian market", "our first enterprise
AE"); medium = clear implication from role plus location or scope; weak = plausible but generic. Prefer no signal to
a weak one.

A code rule already adds a market_expansion signal for any sales / partnerships / country-lead title located in a
country where the company has 3 or fewer roles (quoting the title). Do not repeat those; label expansion only when
the text adds something (a launch, a "first hire", a named new market), and quote that text.

## Evidence quote rules (checked by code)

- 6 to 30 words copied character for character from ONE sentence of the TEXT, from a BOILERPLATE line, or from the
  title. The " / " separator is not part of the posting: never quote across it.
- No paraphrasing, translating, fixing typos, or changing quote marks and dashes. Keep the original language.

## Interpretation rules

One plain sentence, max 18 words, saying what the company is doing, written for an investor. No dashes used as
connectors, no hype words, no "not X but Y".
