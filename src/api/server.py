from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path

from src.pipeline.run import run_pipeline
from src.utils.callback import (
    send_callback_completed,
    send_callback_failed,
)

app = FastAPI()

# 업로드 / 출력 디렉토리
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


# ======================================================
# 1. Backend → AI : 악보 생성 요청
# ======================================================
@app.post("/create_sheets/ai", status_code=202)
async def receive_from_backend(
    job_id: str = Form(...),
    title: str = Form(...),
    purpose: int = Form(...),
    style: int = Form(...),
    difficulty: int = Form(...),
    file: UploadFile = File(...)
):
    # 파일 타입 검증
    if file.content_type not in ["audio/mpeg", "audio/wav"]:
        raise HTTPException(
            status_code=400,
            detail="지원하지 않는 파일 형식이거나 입력값이 누락되었습니다."
        )

    # 파일 저장
    suffix = Path(file.filename).suffix
    input_path = UPLOAD_DIR / f"{job_id}{suffix}"

    with open(input_path, "wb") as f:
        f.write(await file.read())

    # 파이프라인 실행 (여기서는 callback )
    try:
        xml_path = run_pipeline(
            {
                "file": str(input_path),
                "title": title,
                "purpose": str(purpose),
                "style": str(style),
                "difficulty": str(difficulty),
            },
            out_dir=OUTPUT_DIR / job_id
        )

        # 성공 시: xml 경로만 반환
        return JSONResponse(
            status_code=202,
            content={
                "jobId": job_id,
                "xml_path": str(xml_path),
                "message": "악보 생성이 완료되었습니다. callback은 별도 엔드포인트로 전송하세요."
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"악보 생성 중 오류 발생: {str(e)}"
        )


# ======================================================
# 2. AI → Backend : 콜백 전송 전용 엔드포인트
# ======================================================
@app.post("/internal/callback")
async def send_callback_endpoint(
    job_id: str = Form(...),
    status: str = Form(...),
    xml_path: str | None = Form(None),
):
    """
    내부/운영용 API
    - status = completed | failed
    - completed 인 경우 xml_path 필수
    """

    if status not in ["completed", "failed"]:
        raise HTTPException(status_code=400, detail="status must be completed or failed")

    try:
        if status == "completed":
            if not xml_path:
                raise HTTPException(status_code=400, detail="xml_path is required")

            path = Path(xml_path)
            if not path.exists():
                raise HTTPException(status_code=404, detail="xml file not found")

            send_callback_completed(job_id, path)

        else:
            send_callback_failed(job_id)

        return {
            "job_id": job_id,
            "status": status,
            "message": "callback sent to backend"
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"callback 전송 실패: {str(e)}"
        )
