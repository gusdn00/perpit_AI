import requests
from pathlib import Path

BACKEND_CALLBACK_URL = "http://127.0.0.1:8000/create_sheets/callback/ai-result"


def send_callback_completed(job_id: str, xml_path: Path):
    if not xml_path.exists():
        raise FileNotFoundError(f"XML not found: {xml_path}")

    with open(xml_path, "rb") as f:
        files = {
            "xml_file": (xml_path.name, f, "application/xml")
        }
        data = {
            "status": "completed",
            "job_id": job_id
        }

        requests.post(
            BACKEND_CALLBACK_URL,
            data=data,
            files=files,
            timeout=30
        )


def send_callback_failed(job_id: str):
    data = {
        "status": "failed",
        "job_id": job_id
    }

    requests.post(
        BACKEND_CALLBACK_URL,
        json=data,
        timeout=10
    )
