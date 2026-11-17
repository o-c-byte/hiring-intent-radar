"""Public ATS job-board readers. One function per platform, all returning normalised postings.

Normalised posting keys: job_id, title, location, locations[], country_codes[] (ISO-2 when the ATS gives it),
department, posted_at (YYYY-MM-DD), date_field (which ATS field the date came from), url, text.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import xml.etree.ElementTree as ET

from .common import get, get_json, html_to_text

MAX_TEXT = 12000


def _day(value) -> str | None:
    """ISO string or epoch-ms -> YYYY-MM-DD."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).date().isoformat()
    s = str(value)
    return s[:10] if len(s) >= 10 and s[4] == "-" else None


def _post(job_id, title, locations, department, posted_at, date_field, url, text, country_codes=()):
    locs = [l.strip() for l in locations if l and l.strip()]
    locs = list(dict.fromkeys(locs))
    return {
        "job_id": str(job_id), "title": (title or "").strip(), "location": " | ".join(locs),
        "locations": locs, "country_codes": sorted({c.upper() for c in country_codes if c}),
        "department": (department or "").strip(), "posted_at": posted_at, "date_field": date_field,
        "url": url, "text": (text or "")[:MAX_TEXT],
    }


# ---------------------------------------------------------------- Greenhouse
def greenhouse(slug: str):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if d is None or "jobs" not in d:
        return None
    out = []
    for j in d["jobs"]:
        locs = [(j.get("location") or {}).get("name", "")]
        locs += [o.get("location") or o.get("name") or "" for o in j.get("offices") or []]
        dept = ", ".join(x.get("name", "") for x in j.get("departments") or [])
        date_field = "first_published" if j.get("first_published") else "updated_at"
        out.append(_post(j["id"], j.get("title"), locs, dept, _day(j.get(date_field)), date_field,
                         j.get("absolute_url"), html_to_text(j.get("content"))))
    return out


# ---------------------------------------------------------------- Lever
def _lever(base: str, slug: str):
    d = get_json(f"{base}/v0/postings/{slug}?mode=json")
    if not isinstance(d, list):
        return None
    out = []
    for j in d:
        cat = j.get("categories") or {}
        locs = [cat.get("location", "")] + list(cat.get("allLocations") or [])
        parts = [j.get("descriptionPlain") or ""]
        for lst in j.get("lists") or []:
            parts.append(lst.get("text", "") + "\n" + html_to_text(lst.get("content")))
        parts.append(j.get("additionalPlain") or "")
        dept = " / ".join(x for x in (cat.get("department"), cat.get("team")) if x)
        cc = [j.get("country")] if j.get("country") else []
        out.append(_post(j["id"], j.get("text"), locs, dept, _day(j.get("createdAt")), "createdAt",
                         j.get("hostedUrl"), "\n".join(parts), cc))
    return out


def lever(slug: str):
    res = _lever("https://api.lever.co", slug)
    if not res:
        eu = _lever("https://api.eu.lever.co", slug)
        if eu:
            return eu
    return res


# ---------------------------------------------------------------- Ashby
def ashby(slug: str):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    if d is None or "jobs" not in d:
        return None
    out = []
    for j in d["jobs"]:
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        cc = []
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        if addr.get("addressCountry"):
            locs.append(addr["addressCountry"])
        dept = " / ".join(x for x in (j.get("department"), j.get("team")) if x)
        out.append(_post(j.get("id") or j.get("jobUrl"), j.get("title"), locs, dept, _day(j.get("publishedAt")),
                         "publishedAt", j.get("jobUrl"), j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")), cc))
    return out


# ---------------------------------------------------------------- Workable
def workable(slug: str):
    d = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    if d is None or "jobs" not in d:
        return None
    out = []
    for j in d["jobs"]:
        locs = [", ".join(x for x in (j.get("city"), j.get("country")) if x)]
        for l in j.get("locations") or []:
            locs.append(", ".join(x for x in (l.get("city"), l.get("country")) if x))
        cc = [l.get("countryCode") for l in j.get("locations") or []]
        date_field = "published_on" if j.get("published_on") else "created_at"
        out.append(_post(j.get("shortcode"), j.get("title"), locs, j.get("department"), _day(j.get(date_field)),
                         date_field, j.get("url") or j.get("shortlink"), html_to_text(j.get("description")), cc))
    return out


# ---------------------------------------------------------------- Personio
def personio(slug: str):
    for tld in ("com", "de"):
        status, body = get(f"https://{slug}.jobs.personio.{tld}/xml", accept="application/xml")
        if status == 200 and "<workzag-jobs" in body:
            break
    else:
        return None
    root = ET.fromstring(body.encode("utf-8"))
    out = []
    for p in root.findall("position"):
        txt = lambda tag: (p.findtext(tag) or "").strip()
        locs = [txt("office")] + [o.text or "" for o in p.findall("additionalOffices/office")]
        desc = "\n".join(html_to_text(d.findtext("value")) for d in p.findall("jobDescriptions/jobDescription"))
        out.append(_post(txt("id"), txt("name"), locs, txt("department"), _day(txt("createdAt")), "createdAt",
                         f"https://{slug}.jobs.personio.{tld}/job/{txt('id')}", desc))
    return out


# ---------------------------------------------------------------- Recruitee
def recruitee(slug: str):
    d = get_json(f"https://{slug}.recruitee.com/api/offers/")
    if d is None or "offers" not in d:
        return None
    out = []
    for j in d["offers"]:
        locs = [j.get("location", "")] + [", ".join(x for x in (l.get("city"), l.get("country")) if x)
                                          for l in j.get("locations") or []]
        cc = [j.get("country_code")] + [l.get("country_code") for l in j.get("locations") or []]
        date_field = "published_at" if j.get("published_at") else "created_at"
        text = html_to_text(j.get("description")) + "\n" + html_to_text(j.get("requirements"))
        out.append(_post(j.get("id"), j.get("title"), locs, j.get("department"), _day(j.get(date_field)),
                         date_field, j.get("careers_url"), text, cc))
    return out


# ---------------------------------------------------------------- SmartRecruiters
def smartrecruiters(slug: str, max_details: int = 60):
    d = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100")
    if d is None or not d.get("content"):
        return None
    out = []
    for i, j in enumerate(d["content"]):
        loc = j.get("location") or {}
        locs = [", ".join(x for x in (loc.get("city"), loc.get("country")) if x)]
        text = ""
        if i < max_details:
            det = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{j['id']}") or {}
            secs = ((det.get("jobAd") or {}).get("sections") or {})
            text = "\n".join(html_to_text((secs.get(k) or {}).get("text")) for k in
                             ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))
        out.append(_post(j["id"], j.get("name"), locs, (j.get("department") or {}).get("label"),
                         _day(j.get("releasedDate")), "releasedDate",
                         f"https://jobs.smartrecruiters.com/{slug}/{j['id']}", text, [loc.get("country")]))
    return out


# ---------------------------------------------------------------- Teamtailor (public RSS feed with tt: namespace)
def teamtailor(slug: str):
    status, body = get(f"https://{slug}.teamtailor.com/jobs.rss", accept="application/rss+xml")
    if status != 200 or "<rss" not in body:
        return None
    ns = {"tt": "https://teamtailor.com/locations"}
    root = ET.fromstring(body.encode("utf-8"))
    out = []
    for it in root.iter("item"):
        locs = []
        for l in it.findall("tt:locations/tt:location", ns):
            city, country = l.findtext("tt:city", "", ns), l.findtext("tt:country", "", ns)
            locs.append(", ".join(x for x in (city or l.findtext("tt:name", "", ns), country) if x))
        if (it.findtext("remoteStatus") or "none") != "none":
            locs.append("Remote")
        try:
            posted = email.utils.parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
        except Exception:
            posted = None
        out.append(_post(it.findtext("guid"), it.findtext("title"), locs, it.findtext("tt:department", "", ns),
                         posted, "pubDate", it.findtext("link"), html_to_text(it.findtext("description"))))
    return out


FETCHERS = {
    "teamtailor": teamtailor,
    "greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workable": workable,
    "personio": personio, "recruitee": recruitee, "smartrecruiters": smartrecruiters,
}
