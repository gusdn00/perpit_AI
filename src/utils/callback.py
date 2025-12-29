import requests
from pathlib import Path

BACKEND_CALLBACK_URL = "http://127.0.0.1:8000/create_sheets/callback/ai-result"

def send_callback_completed(job_id: str, xml_path: Path):
    """
    성공 시 호출: XML 파일과 status='completed'를 백엔드로 발사(POST)
    """
    if not xml_path.exists():
        raise FileNotFoundError(f"XML not found: {xml_path}")

    print(f"[CALLBACK] Sending COMPLETED for {job_id}...")

    # 파일을 'rb'(바이너리 읽기) 모드로 열어서 전송
    with open(xml_path, "rb") as f:
        files = {
            "xml_file": (xml_path.name, f, "application/xml")
        }
        data = {
            "status": "completed",
            "job_id": job_id
        }

        try:
            # 타임아웃 30초: 백엔드가 받을 때까지 충분히 기다림
            response = requests.post(
                BACKEND_CALLBACK_URL,
                data=data,
                files=files,
                timeout=30
            )
            response.raise_for_status() # 4xx, 5xx 에러 체크
            print(f"[CALLBACK] Success! Backend replied: {response.text}")

        except Exception as e:
            print(f"[CALLBACK] Error sending completed: {e}")


def send_callback_failed(job_id: str):
    """
    실패 시 호출: 파일 없이 status='failed'만 전송
    """
    print(f"[CALLBACK] Sending FAILED for {job_id}...")

    data = {
        "status": "failed",
        "job_id": job_id
    }

    try:
        response = requests.post(
            BACKEND_CALLBACK_URL,
            data=data, 
            timeout=10
        )
        print(f"[CALLBACK] Fail report delivered: {response.text}")

    except Exception as e:
        print(f"[CALLBACK] Error sending failed: {e}")