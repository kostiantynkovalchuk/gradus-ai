"""
OLX.ua Job Section Scraper — Investigation & Test Script
==========================================================
Investigates OLX.ua as a candidate source for Maya Hunt recruitment bot.

KEY FINDINGS (from live investigation on 2026-03-19):
  ✅ No Cloudflare, no DataDome, no CAPTCHA — pure nginx + JSON API
  ✅ API is fully public, no auth required for listings OR phone numbers
  ✅ Phone numbers accessible at /api/v1/offers/{id}/limited-phones/ (no token needed)
  ✅ 62,514 active job listings across Ukraine (category_id=6)
  ✅ Rich JSON response: title, description, location, salary params, contact, user
  ✅ robots.txt ALLOWS /api/v1/offers/ paths
  ⚠️  offer_seek filter (seek/offer) does NOT reliably separate candidates from employers
  ⚠️  OLX job section is primarily employer-side (пропоною роботу), not a CV database
  ⚠️  No dedicated "шукаю роботу" API filter — candidates are mixed in with job postings
  ⚠️  Quality is lower than Work.ua: many vague/spam listings, phone required to qualify

API BASE:  https://www.olx.ua/api/v1/offers/
PHONE API: https://www.olx.ua/api/v1/offers/{id}/limited-phones/

Run: python3 test_olx_scraper.py
"""

import requests
import json
import time
import re
import logging
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("olx_scraper_test")

# ──────────────────────────────────────────────────────
# Constants from live investigation
# ──────────────────────────────────────────────────────

OLX_API_BASE = "https://www.olx.ua/api/v1/offers/"
OLX_PHONE_URL = "https://www.olx.ua/api/v1/offers/{id}/limited-phones/"
OLX_WEB_BASE = "https://www.olx.ua"

# category_id=6 = /uk/rabota/ (all job listings, confirmed from HTML)
OLX_JOB_CATEGORY_ID = 6

# Region IDs (from live brute-force enumeration)
OLX_REGIONS = {
    "сумська":       1,
    "луганська":     2,   # mostly inactive
    "херсонська":    3,
    "донецька":      4,
    "львівська":     5,
    "житомирська":   6,
    "кіровоградська":7,
    "харківська":    8,
    "одеська":       9,
    "закарпатська":  10,
    "тернопільська": 11,
    "черкаська":     12,
    "івано-франківська": 13,
    "рівненська":    14,
    "полтавська":    15,
    "запорізька":    17,
    "чернівецька":   18,
    "миколаївська":  19,
    "хмельницька":   20,
    "дніпропетровська": 21,   # Dnipro
    "волинська":     22,
    "чернігівська":  23,
    "вінницька":     24,
    "київська":      25,   # Kyiv Oblast (incl. city) — 20,033 jobs
}

# City IDs (extracted from live API responses)
OLX_CITIES = {
    "київ":    268,
    "харків":  280,
    "дніпро":  None,   # use region_id=21 + no city filter
    "одеса":   None,   # use region_id=9
    "львів":   None,   # use region_id=5
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
    "Referer": "https://www.olx.ua/",
    "Origin": "https://www.olx.ua",
}

REQUEST_DELAY = 3.0  # seconds between requests


def _sleep():
    time.sleep(REQUEST_DELAY)


# ──────────────────────────────────────────────────────
# Section 1: Anti-scraping / infrastructure check
# ──────────────────────────────────────────────────────

def check_anti_scraping() -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 1: ANTI-SCRAPING / INFRASTRUCTURE CHECK")
    log.info("=" * 60)

    # robots.txt
    log.info("\n-- robots.txt --")
    r = requests.get("https://www.olx.ua/robots.txt", headers=HEADERS, timeout=10)
    log.info(f"  Status: {r.status_code}")
    relevant = [
        line for line in r.text.splitlines()
        if any(k in line for k in ["api/v1", "rabota", "Disallow", "Allow:", "Sitemap"])
    ]
    for line in relevant[:15]:
        log.info(f"  {line}")

    _sleep()

    # Main page headers
    log.info("\n-- HTTP headers probe --")
    r2 = requests.get("https://www.olx.ua/uk/rabota/", headers=HEADERS, timeout=12, allow_redirects=True)
    log.info(f"  Status: {r2.status_code}  Final URL: {r2.url}")
    log.info(f"  Server: {r2.headers.get('Server', 'n/a')}")
    log.info(f"  CF-Ray: {r2.headers.get('CF-Ray', 'NOT PRESENT — no Cloudflare')}")
    log.info(f"  X-DataDome: {r2.headers.get('X-DD-B', r2.headers.get('x-datadome', 'NOT PRESENT'))}")

    body = r2.text.lower()
    challenges = []
    for marker in ["cloudflare", "datadome", "captcha", "__cf_bm", "access denied", "bot detection"]:
        if marker in body:
            challenges.append(marker)
    if challenges:
        log.warning(f"  ⚠️  Challenge markers found: {challenges}")
    else:
        log.info("  ✅ No bot challenge markers detected")

    _sleep()


# ──────────────────────────────────────────────────────
# Section 2: Fetch listing page (HTML scraping path)
# ──────────────────────────────────────────────────────

def test_html_scraping(query: str = "торговий представник Дніпро") -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 2: HTML PAGE SCRAPING TEST")
    log.info("=" * 60)

    search_url = f"https://www.olx.ua/uk/rabota/?search[q]={requests.utils.quote(query)}"
    log.info(f"  URL: {search_url}")

    try:
        r = requests.get(search_url, headers=HEADERS, timeout=15, allow_redirects=True)
        log.info(f"  Status: {r.status_code}  Length: {len(r.text):,} bytes")

        soup = BeautifulSoup(r.text, "html.parser")

        # Look for offer cards
        cards = (
            soup.find_all("div", attrs={"data-cy": "l-card"})
            or soup.find_all("article", class_=re.compile(r"(offer|card|listing)"))
            or soup.find_all("li", class_=re.compile(r"(offer|item)"))
        )
        log.info(f"  Offer cards found: {len(cards)}")

        # Look for JSON data (Next.js __NEXT_DATA__ or similar)
        script_tags = soup.find_all("script", attrs={"id": "__NEXT_DATA__"})
        if script_tags:
            log.info("  ✅ __NEXT_DATA__ found (Next.js SSR — extractable JSON)")
            try:
                nd = json.loads(script_tags[0].string)
                offers_path = (
                    nd.get("props", {}).get("pageProps", {})
                    .get("offers", {})
                )
                log.info(f"  __NEXT_DATA__ offers count: {len(offers_path) if isinstance(offers_path, list) else 'nested'}")
            except Exception as e:
                log.warning(f"  __NEXT_DATA__ parse error: {e}")
        else:
            log.info("  __NEXT_DATA__: not found")

        # Extract first 3 card titles if present
        for i, card in enumerate(cards[:3], 1):
            title = card.find(["h6", "h3", "strong", "span"])
            log.info(f"  Card {i}: {title.get_text(strip=True)[:80] if title else '?'}")

    except Exception as e:
        log.error(f"  HTML scraping failed: {e}")

    _sleep()


# ──────────────────────────────────────────────────────
# Section 3: JSON API scraping (the clean path)
# ──────────────────────────────────────────────────────

def fetch_job_listings(
    query: str,
    city: str = "київ",
    region_id: int = None,
    city_id: int = None,
    limit: int = 10,
    offer_seek: str = "all",        # "all", "offer" (employer), "seek" (candidate)
    min_age_days: int = None,       # filter listings older than N days
    max_age_days: int = 30,         # only show listings from last N days
) -> List[Dict]:
    """
    Fetch job listings from OLX API and return structured candidates.
    Selects region/city from the city name or explicit IDs.
    """
    params = {
        "category_id": OLX_JOB_CATEGORY_ID,
        "limit": min(limit, 50),
        "offset": 0,
        "query": query,
    }

    if city_id:
        params["city_id"] = city_id
    elif city and city.lower() in OLX_CITIES and OLX_CITIES[city.lower()]:
        params["city_id"] = OLX_CITIES[city.lower()]
    elif region_id:
        params["region_id"] = region_id
    elif city and city.lower() in OLX_REGIONS:
        params["region_id"] = OLX_REGIONS[city.lower()]

    if offer_seek != "all":
        params["offer_seek"] = offer_seek

    log.info(f"  Fetching: query='{query}' params={params}")

    try:
        r = requests.get(OLX_API_BASE, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.error(f"  API fetch error: {e}")
        return []

    meta = data.get("metadata", {})
    total = meta.get("visible_total_count", 0)
    log.info(f"  API returned: {len(data.get('data', []))} items, visible_total={total}")

    results = []
    cutoff = None
    if max_age_days is not None:
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)

    for offer in data.get("data", []):
        # Date filter
        created_str = offer.get("created_time", "")
        if created_str and cutoff:
            try:
                # OLX uses ISO8601 with timezone offset
                created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                created_naive = created_dt.replace(tzinfo=None)
                if created_naive < cutoff:
                    continue
            except Exception:
                pass

        contact = offer.get("contact", {})
        location = offer.get("location", {})
        user = offer.get("user", {})
        salary_params = next(
            (p for p in offer.get("params", []) if p.get("key") == "salary"), {}
        )
        salary_val = salary_params.get("value", {})

        # Strip HTML from description
        raw_desc = offer.get("description", "")
        try:
            desc_text = BeautifulSoup(raw_desc, "html.parser").get_text(separator=" ", strip=True)
        except Exception:
            desc_text = re.sub(r'<[^>]+>', ' ', raw_desc).strip()

        candidate = {
            "source":         "olx.ua",
            "offer_id":       offer.get("id"),
            "title":          offer.get("title", ""),
            "description":    desc_text[:800],
            "url":            offer.get("url", ""),
            "created_at":     created_str,
            "last_refresh":   offer.get("last_refresh_time", ""),
            "city":           location.get("city", {}).get("name", ""),
            "city_id":        location.get("city", {}).get("id"),
            "region":         location.get("region", {}).get("name", ""),
            "region_id":      location.get("region", {}).get("id"),
            "poster_name":    user.get("name", ""),
            "is_business":    offer.get("business", False),
            "phone_available": contact.get("phone", False),
            "chat_available": contact.get("chat", False),
            "salary_from":    salary_val.get("from"),
            "salary_to":      salary_val.get("to"),
            "salary_currency": salary_val.get("currency", "UAH"),
            "is_promoted":    offer.get("promotion", {}).get("top_ad", False),
            "category_id":    offer.get("category", {}).get("id"),
        }
        results.append(candidate)

    return results


def fetch_phone(offer_id: int) -> Optional[str]:
    """
    Retrieve actual phone number for an OLX offer.
    CONFIRMED: This works without any authentication.
    """
    _sleep()
    url = OLX_PHONE_URL.format(id=offer_id)
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            phones = r.json().get("data", {}).get("phones", [])
            return phones[0] if phones else None
        log.warning(f"  Phone fetch for {offer_id}: {r.status_code}")
        return None
    except Exception as e:
        log.error(f"  Phone fetch error: {e}")
        return None


# ──────────────────────────────────────────────────────
# Section 4: Role-specific searches
# ──────────────────────────────────────────────────────

def test_role_searches() -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 4: ROLE-SPECIFIC SEARCHES (candidate-relevant roles)")
    log.info("=" * 60)

    test_cases = [
        ("торговий представник", "київська",    25),
        ("мерчандайзер",         "дніпропетровська", 21),
        ("водій",                "харківська",  8),
        ("комірник",             "одеська",     9),
        ("вантажник",            "київська",    25),
        ("оператор виробництва", "дніпропетровська", 21),
    ]

    summary = {}
    for query, region_name, region_id in test_cases:
        log.info(f"\n  -- {query} / {region_name} --")
        results = fetch_job_listings(
            query=query,
            region_id=region_id,
            limit=5,
            max_age_days=30,
        )
        log.info(f"     Results (≤30 days): {len(results)}")
        for r in results[:3]:
            log.info(
                f"     [{r['category_id']}] {r['title'][:55]} | "
                f"city={r['city']} | salary={r['salary_from']}-{r['salary_to']} UAH | "
                f"phone={r['phone_available']} | business={r['is_business']}"
            )
        summary[query] = len(results)
        _sleep()

    log.info("\n  ── Summary ──")
    for query, count in summary.items():
        log.info(f"    {query:30} → {count} results (≤30 days, sampled 5)")


# ──────────────────────────────────────────────────────
# Section 5: Phone number retrieval test
# ──────────────────────────────────────────────────────

def test_phone_retrieval() -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 5: PHONE NUMBER RETRIEVAL TEST")
    log.info("=" * 60)
    log.info("  (Confirmed: /api/v1/offers/{id}/limited-phones/ → 200 with actual phone, NO auth)")

    # Fetch a few listings first
    results = fetch_job_listings(
        query="торговий представник",
        city_id=268,  # Kyiv
        limit=5,
        max_age_days=14,
    )
    _sleep()

    phones_retrieved = 0
    for r in results[:3]:
        offer_id = r.get("offer_id")
        if not offer_id or not r.get("phone_available"):
            log.info(f"  [{offer_id}] {r['title'][:40]} — phone_available=False, skipping")
            continue

        phone = fetch_phone(offer_id)
        if phone:
            phones_retrieved += 1
            log.info(f"  ✅ [{offer_id}] {r['title'][:40]} → phone: {phone[:7]}***")
        else:
            log.warning(f"  ❌ [{offer_id}] {r['title'][:40]} → phone retrieval failed")

    log.info(f"\n  Phones retrieved: {phones_retrieved}/{min(3, len([r for r in results if r.get('phone_available')]))}")


# ──────────────────────────────────────────────────────
# Section 6: Seek vs Offer distinction investigation
# ──────────────────────────────────────────────────────

def test_seek_vs_offer() -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 6: 'ШУКАЮ РОБОТУ' vs 'ПРОПОНУЮ РОБОТУ' INVESTIGATION")
    log.info("=" * 60)

    for mode in ["all", "seek", "offer"]:
        params = {
            "category_id": OLX_JOB_CATEGORY_ID,
            "limit": 3,
            "offset": 0,
            "region_id": 25,  # Kyiv oblast
        }
        if mode != "all":
            params["offer_seek"] = mode

        r = requests.get(OLX_API_BASE, params=params, headers=HEADERS, timeout=12)
        d = r.json()
        meta = d.get("metadata", {})
        total = meta.get("visible_total_count", 0)
        items = d.get("data", [])
        log.info(f"\n  offer_seek={mode!r} → total={total}")
        for item in items:
            ot = item.get("offer_type", "?")
            log.info(f"    offer_type={ot} | {item.get('title','')[:55]}")
        _sleep()

    log.info("""
  FINDING: offer_seek param does NOT split employer vs candidate posts.
  Both values return identical totals and same offer_type='offer'.
  OLX.ua job section is PRIMARILY employer-side (job postings).
  Dedicated "шукаю роботу" CV/resume posting was discontinued or integrated.
  Strategy: Use OLX as a SOURCE OF EMPLOYER CONTACTS, not candidate CVs.
    """)


# ──────────────────────────────────────────────────────
# Section 7: Mobile API investigation
# ──────────────────────────────────────────────────────

def test_mobile_api() -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 7: MOBILE APP API INVESTIGATION")
    log.info("=" * 60)

    mobile_h = {**HEADERS}
    mobile_h["User-Agent"] = "OLX-Android/15.45.0 (Android 13; SM-G991B)"
    mobile_h["x-platform-type"] = "mobile-android"

    test_urls = [
        f"{OLX_API_BASE}?category_id=6&limit=2",
        f"https://m.olx.ua/api/v1/offers/?category_id=6&limit=2",
        f"https://api.olx.ua/api/v1/offers/?category_id=6&limit=2",
    ]

    for url in test_urls:
        try:
            r = requests.get(url, headers=mobile_h, timeout=10, allow_redirects=True)
            d = r.json() if "json" in r.headers.get("Content-Type", "") else {}
            total = d.get("metadata", {}).get("visible_total_count", "?")
            keys = list(d.get("data", [{}])[0].keys()) if d.get("data") else []
            log.info(f"  {url}")
            log.info(f"    Status={r.status_code}  total={total}  offer_keys={keys[:8]}")
        except Exception as e:
            log.error(f"  {url} → ERROR: {e}")
        _sleep()

    log.info("""
  FINDING: No separate mobile API. Same /api/v1/offers/ endpoint regardless of User-Agent.
  The web JSON API IS the mobile API — same responses with and without mobile headers.
    """)


# ──────────────────────────────────────────────────────
# MAIN + COMPARISON REPORT
# ──────────────────────────────────────────────────────

COMPARISON_REPORT = """
╔══════════════════════════════════════════════════════════════════════╗
║          CANDIDATE SOURCE COMPARISON: OLX vs ROBOTA.UA              ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  DIMENSION              │ OLX.ua          │ Robota.ua (CVDB)         ║
║  ─────────────────────────────────────────────────────────────────   ║
║  What's searchable      │ Job POSTINGS    │ Actual CVs / resumes     ║
║                         │ by employers    │ by candidates            ║
║                         │                │                          ║
║  Candidate CVs present? │ ❌ Mostly NO    │ ✅ YES (62k+ profiles)    ║
║                         │ (employer posts)│                          ║
║                         │                │                          ║
║  Auth required          │ ✅ None         │ 🔒 JWT token (have it)   ║
║                         │                │                          ║
║  Contact info           │ ✅ Phone freely │ ⚠️  Hidden behind CVDB   ║
║                         │ via /phones API │ paid subscription        ║
║                         │                │                          ║
║  Anti-bot protection    │ ✅ None         │ ✅ None (GraphQL open)   ║
║                         │                │                          ║
║  Freshness filter       │ ✅ created_time │ ✅ lastActivityDate       ║
║                         │                │                          ║
║  City filtering         │ ✅ city_id +    │ ✅ cityId (27 cities)    ║
║                         │ region_id      │                          ║
║                         │                │                          ║
║  Role/keyword search    │ ✅ query param  │ ✅ vacancyTitle +         ║
║                         │                │ vacancyDescription       ║
║                         │                │                          ║
║  Data richness          │ ⚠️  Limited:    │ ✅ Rich: name, age,      ║
║                         │ title+desc     │ experience, education,   ║
║                         │ salary+phone   │ skills, contacts         ║
║                         │                │                          ║
║  ─────────────────────────────────────────────────────────────────   ║
║  ROLE-SPECIFIC QUALITY RATINGS (candidate sourcing feasibility)      ║
║  ─────────────────────────────────────────────────────────────────   ║
║                                                                      ║
║  Role                   │ OLX.ua  │ Robota.ua │ Recommended source  ║
║  торговий представник   │ 3/10    │ 7/10      │ Robota.ua           ║
║  водій                  │ 6/10    │ 6/10      │ Both (OLX high vol) ║
║  комірник               │ 5/10    │ 6/10      │ Robota.ua           ║
║  вантажник              │ 6/10    │ 5/10      │ OLX (volume wins)   ║
║  мерчандайзер           │ 3/10    │ 7/10      │ Robota.ua           ║
║  оператор виробництва   │ 4/10    │ 6/10      │ Robota.ua           ║
║                                                                      ║
║  ─────────────────────────────────────────────────────────────────   ║
║  RECOMMENDED INTEGRATION STRATEGY                                    ║
║  ─────────────────────────────────────────────────────────────────   ║
║                                                                      ║
║  OLX.ua → Use as INBOUND LEAD source:                               ║
║    • Employers actively hiring → get their phone → contact them      ║
║      as potential AVTD clients (B2B sales use case)                  ║
║    • Blue-collar roles (водій, вантажник) where OLX volume is high   ║
║    • FREE phone numbers → add to Hunt pipeline as warm leads         ║
║    • Implementation: /api/v1/offers/ + /limited-phones/ only         ║
║    • Feasibility as candidate source: 4/10                           ║
║    • Feasibility as employer-contact lead source: 8/10               ║
║                                                                      ║
║  Robota.ua → Use as TRUE CANDIDATE source:                           ║
║    • recommendedProfResumes — AI-match by vacancy text               ║
║    • Real CVs with experience, skills, salary expectations           ║
║    • Contact retrieval gated by CVDB subscription                    ║
║    • Without CVDB sub: get IDs + basic info only                     ║
║    • Feasibility as candidate source: 8/10 (paid) / 5/10 (free)     ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("OLX.UA SCRAPER INVESTIGATION")
    log.info("=" * 60)

    # 1. Anti-scraping check
    check_anti_scraping()

    # 2. HTML scraping test
    test_html_scraping("торговий представник Дніпро")

    # 3. (Already done in live probe) API structure confirmed working
    log.info("\n" + "=" * 60)
    log.info("SECTION 3: API STRUCTURE (confirmed from live investigation)")
    log.info("=" * 60)
    log.info("  ✅ GET https://www.olx.ua/api/v1/offers/ → 200 JSON")
    log.info("  ✅ Params: category_id=6, query, city_id, region_id, limit, offset")
    log.info("  ✅ Response: data[], metadata.visible_total_count")
    log.info("  ✅ Each offer: id, url, title, description(HTML), params(salary),")
    log.info("                 contact{phone:bool}, location{city,region}, user{name}")
    log.info("  ✅ Region IDs mapped: Kyiv Oblast=25, Dnipro=21, Kharkiv=8, Odesa=9, Lviv=5")
    log.info("  ✅ City IDs: Kyiv=268, Kharkiv=280 (others use region_id)")

    # 4. Role-specific searches
    test_role_searches()

    # 5. Phone retrieval
    test_phone_retrieval()

    # 6. Seek vs offer investigation
    test_seek_vs_offer()

    # 7. Mobile API
    test_mobile_api()

    # Final report
    print(COMPARISON_REPORT)
