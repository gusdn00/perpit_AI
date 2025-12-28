from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status
from fastapi.responses import JSONResponse
from pathlib import Path

from src.pipeline.run import run_pipeline
from src.utils.callback import (
    send_callback_completed,
    send_callback_failed,
)

app = FastAPI()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


@app.post("/create_sheets/ai")
async def receive_from_backend(
    job_id: str = Form(...),
    title: str = Form(...),
    purpose: int = Form(...),
    style: int = Form(...),
    difficulty: int = Form(...),
    file: UploadFile = File(...)
):
    # 요청 자체가 잘못된 경우 400
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

    # pipeline 실행 → 결과는 callback으로만
    try:
        xml_path = run_pipeline(
            {
                "file": str(input_path),
                "title": title,
                "purpose": str(purpose),
                "style": str(style),
                "difficulty": str(difficulty),
            },
            out_dir=Path("outputs") / job_id
        )

        send_callback_completed(job_id, xml_path)

    except Exception:
        send_callback_failed(job_id)

    # 응답
    return JSONResponse(
        status_code=202,
        content={
            "jobId": job_id,
            "message": "악보 생성 작업이 시작되었습니다."
        }
    )
