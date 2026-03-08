import requests
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://dracula.robota.ua/"

_position_cache: Dict[str, float] = {}

SALARY_QUERY = """
query gettingStatisticsAverageSalary(
    $keyword: String!, 
    $input: StatisticDataCityRubricInput!
) {
  keyword(name: $keyword) {
    name
    statistic(input: $input) {
      vacancy {
        total {
          count
          salary
          salaryMax
          salaryMin
        }
        median {
          begin
          end
          value
        }
      }
      candidate {
        total {
          count
          salary
          salaryMax
          salaryMin
        }
        median {
          begin
          end
          value
        }
      }
    }
  }
}
"""


def fetch_salary_analytics(position: str) -> Optional[Dict]:
    from services.robotaua_auth import get_robotaua_token, get_graphql_headers
    from services.salary_normalizer import get_usd_uah_rate

    cache_key = position.lower().strip()
    now = time.time()
    if cache_key in _position_cache and (now - _position_cache[cache_key]) < 3600:
        logger.info(f"Salary analytics for '{position}' cached, skipping")
        return None
    _position_cache[cache_key] = now

    usd_rate = get_usd_uah_rate()

    token = get_robotaua_token()
    if not token:
        logger.warning("No Robota.ua token - skipping salary analytics")
        return None

    now_dt = datetime.utcnow()
    date_begin = (now_dt - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00.000Z")
    date_end = (now_dt + timedelta(days=30)).strftime("%Y-%m-%dT23:59:59.999Z")

    payload = {
        "operationName": "gettingStatisticsAverageSalary",
        "query": SALARY_QUERY,
        "variables": {
            "keyword": position,
            "input": {
                "keyword": position,
                "cityId": "1",
                "rubricId": "0",
                "range": {
                    "begin": date_begin,
                    "end": date_end,
                },
                "period": "WEEK",
            },
        },
    }

    try:
        resp = requests.post(
            GRAPHQL_URL + "?q=gettingStatisticsAverageSalary",
            json=payload,
            headers=get_graphql_headers(token),
            timeout=15,
        )
        resp.raise_for_status()

        data = resp.json()
        statistic = data.get("data", {}).get("keyword", {}).get("statistic", {})

        if not statistic:
            logger.warning(f"No salary data for position: {position}")
            return None

        vacancy = statistic.get("vacancy", {})
        candidate = statistic.get("candidate", {})

        vacancy_total = vacancy.get("total", {})
        candidate_total = candidate.get("total", {})

        employer_median_uah = vacancy_total.get("salary", 0)
        candidate_median_uah = candidate_total.get("salary", 0)

        employer_median_usd = int(employer_median_uah / usd_rate) if employer_median_uah else 0
        candidate_median_usd = int(candidate_median_uah / usd_rate) if candidate_median_uah else 0

        gap_uah = employer_median_uah - candidate_median_uah
        gap_usd = employer_median_usd - candidate_median_usd

        timeseries_vacancy = [
            {
                "date": item["begin"][:10],
                "value_uah": item["value"],
                "value_usd": int(item["value"] / usd_rate),
            }
            for item in vacancy.get("median", [])
        ]

        timeseries_candidate = [
            {
                "date": item["begin"][:10],
                "value_uah": item["value"],
                "value_usd": int(item["value"] / usd_rate),
            }
            for item in candidate.get("median", [])
        ]

        result = {
            "position": position,
            "source": "robota.ua",
            "employer_median_uah": employer_median_uah,
            "employer_median_usd": employer_median_usd,
            "candidate_median_uah": candidate_median_uah,
            "candidate_median_usd": candidate_median_usd,
            "gap_uah": gap_uah,
            "gap_usd": gap_usd,
            "salary_min_uah": vacancy_total.get("salaryMin", 0),
            "salary_max_uah": vacancy_total.get("salaryMax", 0),
            "employer_count": vacancy_total.get("count", 0),
            "candidate_count": candidate_total.get("count", 0),
            "timeseries_vacancy": timeseries_vacancy,
            "timeseries_candidate": timeseries_candidate,
            "usd_rate": usd_rate,
        }

        logger.info(
            f"Salary data for '{position}': "
            f"employer {employer_median_uah} грн / "
            f"candidate {candidate_median_uah} грн / "
            f"gap {gap_uah} грн"
        )

        return result

    except Exception as e:
        logger.error(f"Robota.ua salary fetch error: {e}")
        return None


def save_salary_data(salary_result: Dict, vacancy_id: int, db) -> None:
    if not salary_result:
        return

    from models.hunt_models import HuntSalaryData

    usd_rate = salary_result.get("usd_rate", 41.0)

    employer_row = HuntSalaryData(
        vacancy_id=vacancy_id,
        source="robota.ua",
        data_type="employer",
        position=salary_result["position"],
        city="Україна",
        salary_median=salary_result["employer_median_uah"],
        salary_median_uah=salary_result["employer_median_uah"],
        salary_median_usd=salary_result["employer_median_usd"],
        salary_min=salary_result.get("salary_min_uah", 0),
        salary_min_uah=salary_result.get("salary_min_uah", 0),
        salary_max=salary_result.get("salary_max_uah", 0),
        salary_max_uah=salary_result.get("salary_max_uah", 0),
        currency="UAH",
        currency_detected="UAH",
        usd_rate_at_collection=usd_rate,
        sample_count=salary_result.get("employer_count", 0),
        source_url="https://robota.ua/zapros/transparent-salary",
        collected_at=datetime.now(),
    )

    candidate_row = HuntSalaryData(
        vacancy_id=vacancy_id,
        source="robota.ua",
        data_type="candidate",
        position=salary_result["position"],
        city="Україна",
        salary_median=salary_result["candidate_median_uah"],
        salary_median_uah=salary_result["candidate_median_uah"],
        salary_median_usd=salary_result["candidate_median_usd"],
        salary_min_uah=salary_result.get("salary_min_uah", 0),
        salary_max_uah=salary_result.get("salary_max_uah", 0),
        currency="UAH",
        currency_detected="UAH",
        usd_rate_at_collection=usd_rate,
        sample_count=salary_result.get("candidate_count", 0),
        source_url="https://robota.ua/zapros/transparent-salary",
        collected_at=datetime.now(),
    )

    try:
        db.add(employer_row)
        db.add(candidate_row)
        db.commit()
        logger.info(f"Saved salary data for '{salary_result['position']}'")
    except Exception as e:
        logger.error(f"Failed to save salary data: {e}")
        db.rollback()
