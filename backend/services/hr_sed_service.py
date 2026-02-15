import httpx
import os
from typing import Dict, Optional
from datetime import datetime, timedelta
import logging

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

    async def verify_employee(self, phone: str) -> Dict:
        if not self.api_key:
            logger.error("SED_API_KEY not configured")
            return {"verified": False, "employee": None, "error": "not_configured"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.api_url}/api/employees",
                    headers=self.headers,
                    json={"phone": phone}
                )

                data = response.json()
                logger.info(f"SED API response for {phone}: {data.get('status')}")

                if data.get("status") == "success" and data.get("data"):
                    emp = data["data"]
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
                        "error": None
                    }
                else:
                    logger.warning(f"Employee not found in SED: {phone}")
                    return {"verified": False, "employee": None, "error": "not_found"}

        except httpx.TimeoutException:
            logger.error(f"SED API timeout for {phone}")
            return {"verified": False, "employee": None, "error": "timeout"}
        except Exception as e:
            logger.error(f"SED API error for {phone}: {e}")
            return {"verified": False, "employee": None, "error": f"api_error: {str(e)}"}

    def should_sync_user(self, last_sed_sync: Optional[datetime]) -> bool:
        if not last_sed_sync:
            return True
        return last_sed_sync < datetime.utcnow() - timedelta(days=7)


sed_service = SEDService()
