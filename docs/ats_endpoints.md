# Public ATS endpoints (no login, JSON/XML)

All verified in use during 2026 (from a separate project). `{slug}` = the company's board name, usually visible in
its careers-page URL. Pace requests (≥1 s per host). A 404 or empty list = no public board under that slug; try
variants (`acme`, `acmehq`, `acme-io`, `acmeinc`, `acme1`).

| Platform | List endpoint | Notes / useful fields |
|---|---|---|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | `jobs[]`: `id`, `title`, `location.name`, `offices[]`, `departments[]`, `updated_at`, `first_published`, `content` (HTML-escaped). Single job: `/v1/boards/{slug}/jobs/{id}?questions=true` |
| Lever | `https://api.lever.co/v0/postings/{slug}?mode=json` (EU-hosted: `https://api.eu.lever.co/v0/postings/{slug}?mode=json`) | list: `text` (title), `categories.location/team/department/commitment`, `createdAt` (ms), `descriptionPlain`, `lists[]`, `workplaceType`, `hostedUrl` |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true` | `jobs[]`: `title`, `location`, `secondaryLocations[]`, `department`, `team`, `isRemote`, `publishedAt`, `descriptionPlain`, `jobUrl`, `compensation` |
| Workable | `https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true` | `jobs[]`: `title`, `shortcode`, `city`, `country`, `published_on`, `created_at`, `description` (with details=true). 0 jobs = no live roles |
| Personio | `https://{slug}.jobs.personio.com/xml` | XML `<position>`: `id`, `name`, `office`, `additionalOffices`, `department`, `createdAt`, `jobDescriptions` |
| Recruitee | `https://{slug}.recruitee.com/api/offers/` | `offers[]`: `title`, `location`, `country`, `created_at`, `published_at`, `description`, `requirements`, `careers_url` |
| SmartRecruiters | `https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100` | `content[]`: `name`, `location`, `releasedDate`, `department`; full text via `/postings/{id}` |
| Teamtailor | `https://{slug}.teamtailor.com/jobs.rss` (public RSS; `jobs.json` is a JSON Feed without locations) | `<item>`: `title`, `link`, `guid`, `pubDate`, `remoteStatus`, `tt:locations/tt:location` (`tt:city`, `tt:country`), `tt:department`, `description` (HTML) |

Platform detection tip: open the company's careers page and look for `boards.greenhouse.io/`, `jobs.lever.co/`,
`jobs.ashbyhq.com/`, `apply.workable.com/`, `.jobs.personio.com`, `.recruitee.com`, `careers.smartrecruiters.com/`,
`.teamtailor.com` in links or iframes.

`data/seed_ats_slugs_raw.json` (923 boards: greenhouse 333, ashby 221, lever 137, bamboohr 82, teamtailor 54,
smartrecruiters 42, personio 29, recruitee 19, workable 6) is an unfiltered list of companies that hired in Spain in
2026. Some European startups are in it; most entries are not. Use it to skip slug-guessing for companies already
there, never as the universe.
