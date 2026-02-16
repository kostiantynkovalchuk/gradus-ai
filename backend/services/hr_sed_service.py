import httpx
import os
from typing import Dict, Optional
from datetime import datetime, timedelta
import logging
from utils.phone_normalizer import normalize_phone, generate_format_variations

logger = logging.getLogger(__name__)


class SEDService:
    def __init__(self):
        self.api_url = os.getenv("SED_API_URL", "https://api-sed.tdav.net.ua")
        self.api_key = os.getenv("SED_API_KEY")
        self.headers = {
            "X-API-Key": self.api_key or "",
            "Content-Type": "application/json"
        }

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _try_single_format(self, client: httpx.AsyncClient, phone_format: str) -> Dict:
        try:
            response = await client.post(
                f"{self.api_url}/api/employees",
                headers=self.headers,
                json={"phone": phone_format},
                timeout=5.0
            )

            if response.status_code == 401:
                logger.error("SED API 401 Unauthorized (API key invalid or expired)")
                return {"verified": False, "employee": None, "error": "http_401", "stop": True}

            if response.status_code != 200:
                logger.debug(f"SED API HTTP {response.status_code} for format '{phone_format}'")
                return {"verified": False, "employee": None, "error": f"http_{response.status_code}"}

            try:
                data = response.json()
            except Exception:
                return {"verified": False, "employee": None, "error": "invalid_response"}

            if data.get("status") == "success" and data.get("data"):
                emp = data["data"]
                logger.info(f"SED employee found with format '{phone_format}': {emp.get('full_name')}")
                return {
                    "verified": True,
                    "employee": {
                        "employee_id": emp.get("employee_id"),
                        "phone": emp.get("phone"),
                        "full_name": emp.get("full_name"),
                        "first_name": emp.get("first_name"),
                        "last_name": emp.get("last_name"),
                        "department": emp.get("department"),
                        "position": emp.get("position"),
                        "start_date": emp.get("start_date"),
                        "email": emp.get("email")
                    },
                    "error": None,
                    "phone_format_used": phone_format
                }
            else:
                return {"verified": False, "employee": None, "error": "not_found"}

        except httpx.TimeoutException:
            logger.warning(f"SED API timeout for format '{phone_format}'")
            return {"verified": False, "employee": None, "error": "timeout"}

    async def verify_employee(self, phone: str) -> Dict:
        if not self.api_key:
            logger.error("SED_API_KEY not configured")
            return {"verified": False, "employee": None, "error": "not_configured"}

        try:
            phone_normalized = normalize_phone(phone)
        except ValueError:
            phone_normalized = phone

        formats_to_try = generate_format_variations(phone_normalized) if len(phone_normalized) == 12 else [phone]

        logger.info(f"Verifying employee: {phone} -> {phone_normalized} ({len(formats_to_try)} formats)")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for i, fmt in enumerate(formats_to_try, 1):
                    logger.debug(f"SED attempt {i}/{len(formats_to_try)}: '{fmt}'")
                    result = await self._try_single_format(client, fmt)

                    if result.get("stop"):
                        return result

                    if result["verified"]:
                        return result

            logger.warning(f"Employee not found in SED with any format: {phone_normalized}")
            return {"verified": False, "employee": None, "error": "not_found"}

        except Exception as e:
            logger.error(f"SED API error for {phone}: {e}")
            return {"verified": False, "employee": None, "error": f"api_error: {str(e)}"}

    def should_sync_user(self, last_sed_sync: Optional[datetime]) -> bool:
        if not last_sed_sync:
            return True
        return last_sed_sync < datetime.utcnow() - timedelta(days=7)


sed_service = SEDService()
