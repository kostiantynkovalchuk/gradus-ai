"""
Robota.ua reference data: city and rubric caches.
Populated lazily on first call; thread-safe for asyncio usage.
"""
import logging
import httpx

from services.robotaua_auth import login_robotaua

logger = logging.getLogger(__name__)

_EMPLOYER_API = "https://employer-api.robota.ua"

_city_cache: dict = {}   # name_lower -> int id
_city_cache_loaded: bool = False

CITY_ALIASES = {
    "kyiv": "київ", "kiev": "київ", "киев": "київ",
    "dnipro": "дніпро", "dnipropetrovsk": "дніпро", "дніпропетровськ": "дніпро",
    "dnepropetrovsk": "дніпро", "днепр": "дніпро",
    "kharkiv": "харків", "kharkov": "харків", "харьков": "харків",
    "odesa": "одеса", "odessa": "одеса", "одесса": "одеса",
    "lviv": "львів", "lvov": "львів", "львов": "львів",
    "zaporizhzhia": "запоріжжя", "zaporizhja": "запоріжжя", "запорожье": "запоріжжя",
    "vinnytsia": "вінниця", "vinnitsa": "вінниця",
    "poltava": "полтава",
    "mykolaiv": "миколаїв", "nikolaev": "миколаїв",
    "kherson": "херсон",
    "cherkasy": "черкаси",
    "sumy": "суми",
    "zhytomyr": "житомир",
    "rivne": "рівне",
    "ternopil": "тернопіль",
    "khmelnytskyi": "хмельницький",
    "ivano-frankivsk": "івано-франківськ",
    "kropyvnytskyi": "кропивницький",
    "uzhhorod": "ужгород",
    "lutsk": "луцьк",
    "chernihiv": "чернігів",
    "chernivtsi": "чернівці",
}


async def ensure_city_cache() -> None:
    global _city_cache_loaded
    if _city_cache_loaded:
        return
    token = await login_robotaua()
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_EMPLOYER_API}/values/citylist",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                cities = resp.json()
                for city in cities:
                    city_id = city.get("id")
                    if city_id is None:
                        continue
                    city_id = int(city_id)
                    for field in ("name", "nameUkr", "nameEng", "urlSegment"):
                        val = (city.get(field) or "").strip().lower()
                        if val:
                            _city_cache[val] = city_id
                _city_cache_loaded = True
                logger.info(f"[RobotaUA] City cache loaded: {len(_city_cache)} entries")
            else:
                logger.warning(f"[RobotaUA] citylist {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"[RobotaUA] City cache load error: {e}")


async def get_city_id(city_name: str) -> int | None:
    """Resolve Ukrainian city name to Robota.ua integer city ID."""
    if not city_name:
        return None
    await ensure_city_cache()
    name = city_name.strip().lower()

    if name in _city_cache:
        return _city_cache[name]

    canonical = CITY_ALIASES.get(name)
    if canonical and canonical in _city_cache:
        return _city_cache[canonical]

    for cached_name, city_id in _city_cache.items():
        if name in cached_name or cached_name in name:
            return city_id

    return None
