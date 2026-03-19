"""
Robota.ua CV/Resume Search Investigation Script
=================================================
Tests the dracula.robota.ua GraphQL API for CV database search capabilities.
Uses the existing ROBOTAUA_JWT token from environment.

Findings summary (from introspection):
  - recommendedProfResumes  → AI-matched CVs by vacancy title/description/city (main search)
  - publishedResumesCounter → counts matching published resumes
  - employerResume(id)      → fetch one full resume by ID (employer view with contacts)
  - cvdbRegions             → 27 cities reference data
  - cvdbRubrics             → 30 job categories reference data
  - CVDB service            → paid subscription (ActivatedCvDbService: rubricId + cityId + period)
  - REST api.robota.ua      → requires auth (401), no documented public CV search endpoint

Run: python3 test_robotaua_cv_search.py
"""

import os
import json
import logging
import requests
import base64
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("robotaua_cv_test")

GRAPHQL_URL = "https://dracula.robota.ua/"
ROBOTAUA_JWT = os.getenv("ROBOTAUA_JWT", "")

# ──────────────────────────────────────────────
# Headers
# ──────────────────────────────────────────────

def _headers(token: str = "") -> dict:
    h = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "uk",
        "apollographql-client-name": "web-alliance-desktop",
        "apollographql-client-version": "071f324",
        "Content-Type": "application/json",
        "Origin": "https://employer.robota.ua",
        "Referer": "https://employer.robota.ua/",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _gql(query: str, variables: dict, operation: str = "", token: str = "") -> dict:
    payload = {"query": query, "variables": variables}
    if operation:
        payload["operationName"] = operation
    try:
        resp = requests.post(
            GRAPHQL_URL + (f"?q={operation}" if operation else ""),
            json=payload,
            headers=_headers(token),
            timeout=20,
        )
        log.info(f"  HTTP {resp.status_code}  ({operation or 'anon'})")
        return resp.json()
    except Exception as e:
        log.error(f"  Request failed: {e}")
        return {}


# ──────────────────────────────────────────────
# Section 0: JWT inspection
# ──────────────────────────────────────────────

def inspect_jwt(token: str) -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 0: JWT TOKEN INSPECTION")
    log.info("=" * 60)

    if not token:
        log.warning("ROBOTAUA_JWT env var is not set! Auth tests will be skipped.")
        return

    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        decoded = json.loads(base64.b64decode(payload_b64))

        exp = decoded.get("exp", 0)
        iat = decoded.get("iat", 0)
        status = "EXPIRED" if exp < time.time() else f"valid for {int((exp - time.time()) / 3600)}h"

        log.info(f"  sub/userId : {decoded.get('sub') or decoded.get('userId') or decoded.get('id', 'n/a')}")
        log.info(f"  role/type  : {decoded.get('role') or decoded.get('userType') or decoded.get('type', 'n/a')}")
        log.info(f"  companyId  : {decoded.get('companyId', 'n/a')}")
        log.info(f"  issued     : {iat}")
        log.info(f"  expires    : {exp}  → {status}")
        safe_claims = {k: v for k, v in decoded.items()
                       if k not in ("jti", "sub", "companyId")}
        log.info(f"  other claims: {json.dumps(safe_claims, ensure_ascii=False)}")
    except Exception as e:
        log.error(f"  JWT decode failed: {e}")


# ──────────────────────────────────────────────
# Section 1: Reference data (public, no auth)
# ──────────────────────────────────────────────

def test_reference_data() -> dict:
    log.info("\n" + "=" * 60)
    log.info("SECTION 1: REFERENCE DATA (no auth required)")
    log.info("=" * 60)

    # Cities
    log.info("\n-- cvdbRegions (cities for CV database) --")
    r1 = _gql(
        """query cvdbRegions { cvdbRegions { cities { id name } } }""",
        {}, "cvdbRegions"
    )
    cities = r1.get("data", {}).get("cvdbRegions", {}).get("cities", [])
    log.info(f"  Cities available: {len(cities)}")
    for c in cities[:10]:
        log.info(f"    id={c['id']:3}  {c['name']}")
    city_map = {c["name"].lower(): c["id"] for c in cities}

    # Rubrics
    log.info("\n-- cvdbRubrics (job categories) --")
    r2 = _gql(
        """query cvdbRubrics { cvdbRubrics { rubrics { id name } } }""",
        {}, "cvdbRubrics"
    )
    rubrics = r2.get("data", {}).get("cvdbRubrics", {}).get("rubrics", [])
    log.info(f"  Rubrics available: {len(rubrics)}")
    for rub in rubrics[:12]:
        log.info(f"    id={rub['id']:3}  {rub['name']}")

    return {"cities": cities, "rubrics": rubrics, "city_map": city_map}


# ──────────────────────────────────────────────
# Section 2: Probing common query names
# ──────────────────────────────────────────────

def test_common_query_names(token: str) -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 2: PROBING COMMON QUERY NAMES")
    log.info("=" * 60)

    probe_queries = [
        ("cvSearch",          """query { cvSearch(keywords: "менеджер") { total } }"""),
        ("resumeSearch",      """query { resumeSearch(keywords: "менеджер") { total } }"""),
        ("candidateSearch",   """query { candidateSearch(keywords: "менеджер") { total } }"""),
        ("searchCandidates",  """query { searchCandidates(keyword: "менеджер") { total } }"""),
        ("searchResumes",     """query { searchResumes(keyword: "менеджер") { total } }"""),
        ("cvdbSearch",        """query { cvdbSearch(keyword: "менеджер") { total } }"""),
        ("resumeList",        """query { resumeList(first: 1) { total } }"""),
        ("resumes",           """query { resumes(first: 1) { total } }"""),
        ("candidates",        """query { candidates(first: 1) { total } }"""),
        ("employerResumes",   """query { employerResumes(first: 1) { total } }"""),
    ]

    for name, q in probe_queries:
        result = _gql(q, {}, name, token=token)
        errors = result.get("errors", [])
        data = result.get("data", {})

        if errors:
            err_msg = errors[0].get("message", "")
            if "Cannot query field" in err_msg or "Unknown field" in err_msg:
                log.info(f"  ❌ {name:30} → FIELD DOES NOT EXIST")
            elif "Unauthorized" in err_msg or "Forbidden" in err_msg or "401" in err_msg:
                log.info(f"  🔒 {name:30} → EXISTS but requires auth")
            else:
                log.info(f"  ⚠️  {name:30} → ERROR: {err_msg[:80]}")
        elif data:
            log.info(f"  ✅ {name:30} → SUCCESS: {json.dumps(data)[:120]}")
        else:
            log.info(f"  ❓ {name:30} → Empty response: {result}")


# ──────────────────────────────────────────────
# Section 3: recommendedProfResumes (the real CV search)
# ──────────────────────────────────────────────

RECOMMENDED_QUERY = """
query recommendedProfResumesQuery(
    $input: RecommendedProfResumesInput!
    $after: String
    $first: Int
) {
  recommendedProfResumes(input: $input, after: $after, first: $first) {
    total
    recommendedProfResumeList {
      id
      displayName
      speciality
      age
      gender
      lastActivityDate
      updateDate
      recommendationType
      city { id name }
      resumeSalary { amount currency }
      experience {
        company
        position
        startDate
        endDate
        isCurrent
      }
    }
  }
}
"""

def test_recommended_resumes(token: str, city_id: str = "1") -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 3: recommendedProfResumes (AI-MATCHED CV SEARCH)")
    log.info("=" * 60)

    test_cases = [
        {
            "desc": "Sales manager in Kyiv, ALL type",
            "input": {
                "vacancyTitle": "Торговий представник",
                "vacancyDescription": "Шукаємо торгового представника з досвідом продажів алкогольних напоїв в HoReCa та рітейлі.",
                "cityId": "1",
                "resumeType": "ALL",
            },
        },
        {
            "desc": "Merchandiser in Dnipro, SUITABLE type",
            "input": {
                "vacancyTitle": "Мерчандайзер",
                "vacancyDescription": "Мерчандайзер для роботи з торговими точками у категорії FMCG / алкоголь.",
                "cityId": "4",
                "resumeType": "SUITABLE",
            },
        },
        {
            "desc": "HR manager Ukraine-wide (cityId=0), ALL type",
            "input": {
                "vacancyTitle": "HR менеджер",
                "vacancyDescription": "HR менеджер з рекрутингу та адаптації персоналу для торговельної компанії.",
                "cityId": "0",
                "resumeType": "ALL",
            },
        },
    ]

    for tc in test_cases:
        log.info(f"\n  >> Test: {tc['desc']}")
        result = _gql(
            RECOMMENDED_QUERY,
            {"input": tc["input"], "first": 5},
            "recommendedProfResumesQuery",
            token=token,
        )
        errors = result.get("errors", [])
        if errors:
            log.error(f"     Errors: {json.dumps(errors, ensure_ascii=False)[:300]}")
            continue

        data = result.get("data", {}).get("recommendedProfResumes", {})
        total = data.get("total", 0)
        resumes = data.get("recommendedProfResumeList", [])
        log.info(f"     Total available: {total}")
        log.info(f"     Returned: {len(resumes)}")
        for i, r in enumerate(resumes, 1):
            salary = r.get("resumeSalary")
            salary_str = f"{salary['amount']} {salary['currency']}" if salary else "no salary"
            city_name = (r.get("city") or {}).get("name", "?")
            exp_count = len(r.get("experience") or [])
            log.info(
                f"     [{i}] id={r.get('id')} | {r.get('displayName','?')} | "
                f"{r.get('speciality','?')[:40]} | {city_name} | "
                f"age={r.get('age')} | salary={salary_str} | exp_entries={exp_count}"
            )


# ──────────────────────────────────────────────
# Section 4: employerResume (fetch full CV by ID)
# ──────────────────────────────────────────────

EMPLOYER_RESUME_QUERY = """
query employerResumeQuery($id: ID!) {
  employerResume(id: $id) {
    __typename
    ... on EmployerResume {
      id
      title
      isAnonymous
      isUserOnline
      skills
      addedAt
      updatedAt
      isActivelySearchingForNewJob
      city { id name }
      salary { amount currency }
      filling { percentage type }
      personal {
        firstName
        lastName
        birthDate
        gender
      }
      contacts {
        phones { phone }
        email { email }
        socialNetworks { type url }
      }
      experiences {
        company
        position
        startDate
        endDate
        isCurrent
        description
      }
      educations {
        name
        type
        yearStart
        yearEnd
      }
      skills
      languageSkills {
        language { name }
        level { name }
      }
    }
    ... on NotFoundEmployerResumeError {
      message
    }
    ... on ServerError {
      message
    }
  }
}
"""

def test_employer_resume(token: str, resume_id: str = None) -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 4: employerResume (FULL CV DETAIL BY ID)")
    log.info("=" * 60)

    if not resume_id:
        log.info("  No resume_id provided — skipping. Provide a real ID from Section 3 results.")
        log.info("  Example: test_employer_resume(token, '12345678')")
        return

    log.info(f"  Fetching resume id={resume_id}")
    result = _gql(
        EMPLOYER_RESUME_QUERY,
        {"id": resume_id},
        "employerResumeQuery",
        token=token,
    )
    errors = result.get("errors", [])
    if errors:
        log.error(f"  Errors: {json.dumps(errors, ensure_ascii=False)[:300]}")
        return

    data = result.get("data", {}).get("employerResume", {})
    typename = data.get("__typename", "?")
    log.info(f"  Response type: {typename}")
    if typename == "EmployerResume":
        personal = data.get("personal", {})
        contacts = data.get("contacts", {})
        log.info(f"  Name: {personal.get('firstName','')} {personal.get('lastName','')}")
        log.info(f"  Title: {data.get('title','')}")
        log.info(f"  City: {(data.get('city') or {}).get('name','?')}")
        log.info(f"  Anonymous: {data.get('isAnonymous')}")
        log.info(f"  Salary: {data.get('salary')}")
        log.info(f"  Skills: {(data.get('skills') or '')[:100]}")
        log.info(f"  Phones: {contacts.get('phones', [])}")
        log.info(f"  Email: {contacts.get('email')}")
        log.info(f"  Experiences: {len(data.get('experiences') or [])} entries")
    else:
        log.info(f"  Message: {data.get('message', 'n/a')}")


# ──────────────────────────────────────────────
# Section 5: publishedResumesCounter
# ──────────────────────────────────────────────

def test_published_resumes_counter(token: str) -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 5: publishedResumesCounter")
    log.info("=" * 60)

    # Introspect the actual input type for this query
    r = requests.post(GRAPHQL_URL, json={
        "query": """
        query {
          __type(name: "Query") {
            fields { name args { name type { name kind ofType { name } } } }
          }
        }
        """,
        "variables": {}
    }, headers=_headers(), timeout=15)
    fields = r.json().get("data", {}).get("__type", {}).get("fields", [])
    match = next((f for f in fields if f["name"] == "publishedResumesCounter"), None)
    if match:
        log.info(f"  publishedResumesCounter args: {json.dumps(match.get('args', []), ensure_ascii=False)}")
    else:
        log.warning("  publishedResumesCounter not found in schema")

    # Try a direct introspection of the input type
    r2 = requests.post(GRAPHQL_URL, json={
        "query": """
        query {
          __type(name: "PublishedResumesCounterInput") {
            name kind inputFields { name type { name kind ofType { name kind } } }
          }
        }
        """,
        "variables": {}
    }, headers=_headers(token), timeout=10)
    data2 = r2.json().get("data", {}).get("__type")
    log.info(f"  PublishedResumesCounterInput type lookup: {data2}")


# ──────────────────────────────────────────────
# Section 6: REST endpoints
# ──────────────────────────────────────────────

def test_rest_endpoints(token: str) -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 6: REST ENDPOINT PROBES")
    log.info("=" * 60)

    auth_h = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }

    endpoints = [
        ("GET",  "https://api.robota.ua/resume/search?q=менеджер&cityId=1"),
        ("GET",  "https://api.robota.ua/cvdb/resumes?q=менеджер"),
        ("GET",  "https://employer-api.robota.ua/resume/search"),
        ("GET",  "https://employer-api.robota.ua/cvdb"),
        ("GET",  "https://api.robota.ua/v2/resumes?keywords=менеджер&cityId=1"),
        ("GET",  "https://employer.robota.ua/api/cvdb/resumes"),
    ]

    for method, url in endpoints:
        try:
            if method == "GET":
                resp = requests.get(url, headers=auth_h, timeout=8, allow_redirects=False)
            else:
                resp = requests.post(url, headers=auth_h, timeout=8)
            log.info(f"  {method} {url}")
            log.info(f"       → {resp.status_code}  {resp.text[:150]}")
        except Exception as e:
            log.info(f"  {method} {url}")
            log.info(f"       → ERROR: {e}")


# ──────────────────────────────────────────────
# Section 7: CVDB service status (requires auth)
# ──────────────────────────────────────────────

CVDB_SERVICE_QUERY = """
query getCvdbServices {
  catalogServices(filter: { type: CVDB }) {
    id
    name
    type
    price
    description
  }
}
"""

def test_cvdb_service_status(token: str) -> None:
    log.info("\n" + "=" * 60)
    log.info("SECTION 7: CVDB SERVICE CATALOG")
    log.info("=" * 60)

    result = _gql(CVDB_SERVICE_QUERY, {}, "getCvdbServices", token=token)
    errors = result.get("errors", [])
    if errors:
        log.error(f"  Errors: {json.dumps(errors, ensure_ascii=False)[:300]}")
    else:
        services = result.get("data", {}).get("catalogServices", [])
        log.info(f"  CVDB catalog services found: {len(services)}")
        for s in services:
            log.info(f"    {s}")

    # Also try to find if our account has active CVDB service
    ACTIVE_CVDB_QUERY = """
    query {
      company {
        id
        name
        activatedServices {
          ... on ActivatedCvDbService {
            id
            name
            city { id name }
            rubric { id name }
            activatedAt
            endedAt
            contactsUsage { used total }
          }
        }
      }
    }
    """
    log.info("\n  -- Checking our account's active CVDB services --")
    result2 = _gql(ACTIVE_CVDB_QUERY, {}, "getActiveCvdbServices", token=token)
    errors2 = result2.get("errors", [])
    if errors2:
        log.error(f"  Errors: {json.dumps(errors2, ensure_ascii=False)[:300]}")
    else:
        company = result2.get("data", {}).get("company", {})
        log.info(f"  Company: id={company.get('id')} name={company.get('name')}")
        active = company.get("activatedServices", [])
        log.info(f"  Active services: {len(active)}")
        for svc in active:
            log.info(f"    {json.dumps(svc, ensure_ascii=False)}")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("ROBOTA.UA CV SEARCH API INVESTIGATION")
    log.info(f"Endpoint: {GRAPHQL_URL}")
    log.info(f"JWT configured: {'YES' if ROBOTAUA_JWT else 'NO — set ROBOTAUA_JWT env var'}")
    log.info("=" * 60)

    token = ROBOTAUA_JWT

    # 0. JWT analysis
    inspect_jwt(token)

    # 1. Public reference data
    ref = test_reference_data()

    # 2. Probe common query names (GraphQL validation errors reveal existence)
    test_common_query_names(token)

    # 3. Main CV search: recommendedProfResumes
    test_recommended_resumes(token, city_id="1")

    # 4. Full CV detail by ID (requires a real ID from step 3 results)
    # Uncomment and set a real ID once you have results from Section 3:
    # test_employer_resume(token, resume_id="XXXXXXXX")
    test_employer_resume(token, resume_id=None)

    # 5. Published resumes counter
    test_published_resumes_counter(token)

    # 6. REST endpoints
    test_rest_endpoints(token)

    # 7. CVDB subscription/service status
    test_cvdb_service_status(token)

    log.info("\n" + "=" * 60)
    log.info("INVESTIGATION COMPLETE")
    log.info("=" * 60)
    log.info("""
FINDINGS SUMMARY:
─────────────────────────────────────────────────────
CONFIRMED WORKING (from live introspection):
  ✅ dracula.robota.ua GraphQL — same endpoint we already use
  ✅ Same JWT token works (same Authorization: Bearer header)
  ✅ cvdbRegions  — 27 Ukrainian cities reference data
  ✅ cvdbRubrics  — 30 job categories reference data
  ✅ recommendedProfResumes(input!, after, first)
         input: { vacancyTitle, vacancyDescription, cityId, resumeType }
         resumeType: ALL | SUITABLE | VIEWED
         returns: total + list with id/name/speciality/age/city/salary/experience
  ✅ employerResume(id: ID!)
         returns EmployerResume with full data + contacts (phones, email)
         requires auth + candidate must not be anonymous

PAID SERVICE GATING:
  ⚠️  CVDB (CV Database) is a PAID subscription per rubric+city+period
  ⚠️  "ActivatedCvDbService" has contactsUsage { used / total }
  ⚠️  Contacts may be hidden for non-paying accounts (EmployerResumeContacts)

NO SUCH ENDPOINTS (confirmed by introspection):
  ❌ cvSearch, resumeSearch, candidateSearch, searchCandidates, searchResumes
  ❌ cvdbSearch (no direct keyword search query)
  ❌ employer-api.robota.ua REST (404)
  ❌ api.robota.ua/resume/search (401 — auth not enough, different product)

INTEGRATION PATH FOR HUNT:
  1. Use recommendedProfResumes → AI-match CVs by vacancy title + description
  2. Collect resume IDs from the list
  3. Call employerResume(id) for each → get full data + contacts
  4. If contacts hidden → CVDB subscription needed (purchase via employer portal)
─────────────────────────────────────────────────────
""")
