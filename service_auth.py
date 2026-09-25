import os


def service_headers(service):
    key = os.getenv(f"{service.upper()}_API_KEY", "") or os.getenv("IARA_API_KEY", "")
    return {"Authorization": f"Bearer {key}"} if key else {}
