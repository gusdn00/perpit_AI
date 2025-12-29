import shutil
from pathlib import Path

def run_pipeline(args: dict, out_dir: Path) -> str:
    
    # 1. purpose 값 확인 (문자열로 들어올 수 있으니 안전하게 처리)
    # 백엔드에서 1, 2 등을 보내줌
    purpose = str(args.get("purpose", "1"))
    
    print(f"--- [TEST PIPELINE] 요청된 purpose: {purpose} ---")

    # 2. purpose에 따른 원본 파일 경로 설정 (절대 경로)
    if purpose == "1":
        source_file = Path("/home/jisu/PerPitModel/outputs/pps1/result.xml")
    elif purpose == "2":
        source_file = Path("/home/jisu/PerPitModel/outputs/pps2/result.xml")

    # 3. 결과 파일이 저장될 경로 (outputs/{job_id}/score.xml)
    # out_dir은 server.py에서 이미 생성해서 넘겨줍니다.
    target_path = out_dir / "score.xml"

    # 4. 파일 복사 수행
    if source_file.exists():
        shutil.copy(source_file, target_path)
        print(f"파일 복사 성공: {source_file} -> {target_path}")
    else:
        # 지정된 경로에 파일이 없으면 에러 발생
        raise FileNotFoundError(f"{source_file}")

    # 5. 복사된 파일의 경로를 문자열로 반환 (server.py로 전달)
    return str(target_path)