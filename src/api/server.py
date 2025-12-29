import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

# 님 프로젝트 경로에 맞춰 import
from src.pipeline.run import run_pipeline
from src.utils.callback import send_callback_completed, send_callback_failed

app = FastAPI()

# 디렉토리 설정
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

# ======================================================
#  1. 백그라운드 작업 (AI 로직 + 보내기)
# 이 함수는 202 응답(return)이 나간 뒤에 혼자 실행됩니다.
# ======================================================
def process_sheet_generation(job_id: str, input_path: Path, title: str, purpose: int, style: int, difficulty: int):
    try:
        print(f"[{job_id}]  백그라운드 AI 작업 시작...")
        
        # 1) 결과 저장 폴더 지정
        target_output_dir = OUTPUT_DIR / job_id
        
        # 2) AI 파이프라인 실행 (시간 오래 걸림)
        # 여기서 시간이 걸려도 백엔드 연결은 이미 끊겨서 타임아웃 안 남!
        xml_path_result = run_pipeline(
            {
                "file": str(input_path),
                "title": title,
                "purpose": str(purpose),
                "style": str(style),
                "difficulty": str(difficulty),
            },
            out_dir=target_output_dir
        )
        
        # 3) 결과 검증 (run_pipeline 리턴값 혹은 파일 존재 여부 확인)
        if xml_path_result:
            xml_path = Path(xml_path_result)
        else:
            xml_path = target_output_dir / "score.xml" # 예상 경로

        if not xml_path.exists():
            raise FileNotFoundError(f"AI finished but XML not found at {xml_path}")

        # 4) 성공 콜백 (여기서 callback.py가 실행되어 백엔드로 파일을 쏩니다)
        send_callback_completed(job_id, xml_path)

    except Exception as e:
        print(f"[{job_id}] 작업 중 에러 발생: {e}")
        # 5) 실패 콜백
        send_callback_failed(job_id)


# ======================================================
# 2. 백엔드로부터 요청 받는 곳 (진입점)
# ======================================================
@app.post("/create_sheets/ai", status_code=202)
async def receive_from_backend(
    background_tasks: BackgroundTasks, #비동기 도구 추가
    job_id: str = Form(...),
    title: str = Form(...),
    purpose: int = Form(...),
    style: int = Form(...),
    difficulty: int = Form(...),
    file: UploadFile = File(...)
):
    print(f"[{job_id}] 요청 받음 (from Backend).")

    try:
        # 1) 파일 저장
        suffix = Path(file.filename).suffix if file.filename else ".mp3"
        input_path = UPLOAD_DIR / f"{job_id}{suffix}"
        
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2) 백그라운드 작업 예약 
        # run_pipeline을 직접 실행하지 않고, 등록만 함
        background_tasks.add_task(
            process_sheet_generation, 
            job_id, 
            input_path, 
            title, 
            purpose, 
            style, 
            difficulty
        )

        # 3) 즉시 응답 (타임아웃 방지)
        # 백엔드는 0.1초 만에 이 응답을 받고 연결을 끊음
        print(f"[{job_id}] 202 응답 보냄. 작업 예약 완료.")
        return JSONResponse(
            status_code=202,
            content={"jobId": job_id, "message": "Background task started."}
        )

    except Exception as e:
        print(f"[{job_id}] 요청 접수 단계 에러: {e}")
        raise HTTPException(status_code=500, detail=str(e))
