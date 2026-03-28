import subprocess
from pathlib import Path


class DemucsError(RuntimeError):
    pass


# htdemucs_6s: vocals / drums / bass / other / piano / guitar 6트랙 분리
MODEL_NAME = "htdemucs_6s"

# htdemucs_6s 모델이 분리하는 트랙 목록
EXPECTED_STEMS = ["vocals", "drums", "bass", "other", "piano", "guitar"]


def separate_sources(wav_path: Path, out_dir: Path) -> dict:
    """
    HT-Demucs(htdemucs_6s)로 오디오를 악기별 트랙으로 분리.

    Args:
        wav_path: 전처리된 wav 파일 경로 (input_standard.wav)
        out_dir:  분리된 트랙을 저장할 디렉토리

    Returns:
        {
            "vocals": Path,   # 보컬 (피아노+연주용 → 멜로디 추출에 사용)
            "piano":  Path,   # 피아노 트랙 (피아노+반주용 → 반주 추출에 사용)
            "guitar": Path,   # 기타 트랙
            "drums":  Path,
            "bass":   Path,
            "other":  Path,
        }

    파이프라인에서의 활용:
        - 피아노 + 연주용(purpose=2) → vocals.wav 를 Basic Pitch 입력으로 사용
        - 피아노 + 반주용(purpose=1) → piano.wav  를 Basic Pitch 입력으로 사용
        - 기타(instrument=2)         → 피치 추출 없이 코드만 사용 (이 함수 결과 불필요)
    """

    if not isinstance(wav_path, Path):
        wav_path = Path(wav_path)

    if not wav_path.exists():
        raise DemucsError(f"입력 파일이 없습니다: {wav_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"🎵 Demucs 분리 시작: {wav_path.name} (모델: {MODEL_NAME})")

    # demucs CLI 실행
    # 출력 구조: out_dir/htdemucs_6s/{파일명}/{stem}.wav
    cmd = [
        "python", "-m", "demucs",
        "-n", MODEL_NAME,
        "-o", str(out_dir),
        str(wav_path),
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise DemucsError(f"Demucs 실행 실패:\n{e.stderr}") from e

    # demucs 출력 경로: out_dir/htdemucs_6s/{파일명(확장자 제거)}/{stem}.wav
    stem_dir = out_dir / MODEL_NAME / wav_path.stem

    if not stem_dir.exists():
        raise DemucsError(f"Demucs 출력 디렉토리가 없습니다: {stem_dir}")

    # 분리된 트랙 경로 수집
    tracks = {}
    missing = []

    for stem in EXPECTED_STEMS:
        track_path = stem_dir / f"{stem}.wav"
        if track_path.exists():
            tracks[stem] = track_path
            print(f"   ✅ {stem}: {track_path.name}")
        else:
            missing.append(stem)
            print(f"   ⚠️  {stem}: 파일 없음")

    if missing:
        print(f"   경고: 다음 트랙이 생성되지 않았습니다 → {missing}")

    if not tracks:
        raise DemucsError("분리된 트랙이 하나도 없습니다.")

    print(f"✅ Demucs 분리 완료: {len(tracks)}개 트랙")
    return tracks
