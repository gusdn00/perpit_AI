"""
yourmt3_extractor.py - YourMT3 기반 멀티트랙 MIDI 추출

YourMT3 (https://github.com/mimbres/YourMT3) 를 사용하여
오디오 파일 하나에서 악기별 MIDI를 한 번에 추출.

기존 demucs + basic_pitch 2단계를 YourMT3 단일 모델로 대체.

설치 방법:
    git clone https://huggingface.co/spaces/mimbres/YourMT3 /opt/YourMT3
    pip install -r /opt/YourMT3/requirements.txt

환경 변수:
    YOURMT3_DIR: YourMT3 클론 경로 (기본: /opt/YourMT3)
    YOURMT3_CHECKPOINT: 사용할 체크포인트 이름 (기본: YPTF+MixEnc/single_inst)
"""

import os
import sys
import shutil
from pathlib import Path


# YourMT3 HuggingFace Space 기본 설치 경로
_DEFAULT_YOURMT3_DIR = os.environ.get("YOURMT3_DIR", "/opt/YourMT3")

# 사용할 체크포인트 (YourMT3 Space에서 제공하는 모델 목록 중)
# 옵션: "YPTF+MixEnc/single_inst", "YMT3+/multi_inst" 등
_DEFAULT_CHECKPOINT = os.environ.get("YOURMT3_CHECKPOINT", "YPTF+MixEnc/single_inst")

# YourMT3가 분리해서 출력하는 악기 트랙명 (모델에 따라 다를 수 있음)
# single_inst 모드: 단일 피아노 트랙
# multi_inst 모드: piano, guitar, bass, drums, strings, ...
PIANO_TRACK_KEYWORDS = ["piano", "keyboard", "grand_piano"]
GUITAR_TRACK_KEYWORDS = ["guitar", "acoustic_guitar", "electric_guitar"]


class YourMT3Error(RuntimeError):
    pass


def _load_yourmt3(yourmt3_dir: str):
    """YourMT3 모듈을 동적으로 로드."""
    mt3_path = Path(yourmt3_dir)
    if not mt3_path.exists():
        raise YourMT3Error(
            f"YourMT3 설치 디렉토리가 없습니다: {yourmt3_dir}\n"
            "설치 방법: git clone https://huggingface.co/spaces/mimbres/YourMT3 "
            f"{yourmt3_dir}"
        )

    if str(mt3_path) not in sys.path:
        sys.path.insert(0, str(mt3_path))

    try:
        from model_helper import load_model_checkpoint, transcribe  # noqa: F401
        return load_model_checkpoint, transcribe
    except ImportError as e:
        raise YourMT3Error(
            f"YourMT3 모듈 임포트 실패: {e}\n"
            f"requirements.txt 설치 확인: pip install -r {yourmt3_dir}/requirements.txt"
        ) from e


def transcribe_audio(
    wav_path: Path,
    out_dir: Path,
    instrument: str = "1",
    yourmt3_dir: str = _DEFAULT_YOURMT3_DIR,
    checkpoint: str = _DEFAULT_CHECKPOINT,
) -> dict:
    """
    YourMT3로 오디오를 악기별 MIDI로 변환.

    Args:
        wav_path:     전처리된 wav 파일 경로 (input_standard.wav)
        out_dir:      MIDI 파일을 저장할 디렉토리
        instrument:   "1"=피아노, "2"=기타
        yourmt3_dir:  YourMT3 클론 경로
        checkpoint:   사용할 체크포인트 이름

    Returns:
        {
            "piano":  Path,   # 피아노 MIDI (instrument=1일 때)
            "guitar": Path,   # 기타 MIDI (instrument=2일 때)
            "all":    Path,   # 전체 합쳐진 MIDI (항상 포함)
            ...               # YourMT3가 출력한 다른 트랙들
        }
        - instrument에 해당하는 키가 반드시 포함됨
        - "selected" 키: 파이프라인에서 사용할 메인 MIDI 경로
    """

    if not isinstance(wav_path, Path):
        wav_path = Path(wav_path)

    if not wav_path.exists():
        raise YourMT3Error(f"입력 WAV 파일이 없습니다: {wav_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"🎵 YourMT3 음 추출 시작: {wav_path.name} (체크포인트: {checkpoint})")

    # YourMT3 모듈 로드
    load_model_checkpoint, transcribe = _load_yourmt3(yourmt3_dir)

    # 모델 로드 (첫 실행 시 체크포인트 다운로드)
    model = load_model_checkpoint(checkpoint)
    print(f"   모델 로드 완료: {checkpoint}")

    # YourMT3 추론 실행
    # transcribe() → 악기별 MIDI 파일 경로 목록 반환 (또는 딕셔너리)
    midi_results = transcribe(model, str(wav_path), str(out_dir))

    # 반환 타입 정규화: 리스트 또는 딕셔너리 모두 처리
    tracks = _normalize_results(midi_results, out_dir)
    print(f"   추출된 트랙: {list(tracks.keys())}")

    # instrument에 맞는 메인 트랙 선택
    selected = _select_track(tracks, instrument, wav_path.stem, out_dir)
    tracks["selected"] = selected

    print(f"✅ YourMT3 추출 완료: 선택된 트랙 = {selected.name}")
    return tracks


def _normalize_results(midi_results, out_dir: Path) -> dict:
    """
    YourMT3 transcribe() 반환값을 {트랙명: Path} 딕셔너리로 정규화.

    YourMT3 Space의 transcribe()는 버전에 따라:
    - dict: {"piano": "/path/to/piano.mid", ...}
    - list: ["/path/to/piano.mid", "/path/to/guitar.mid", ...]
    중 하나를 반환할 수 있음.
    """
    tracks = {}

    if isinstance(midi_results, dict):
        for key, val in midi_results.items():
            tracks[str(key).lower()] = Path(val)

    elif isinstance(midi_results, (list, tuple)):
        for midi_path in midi_results:
            p = Path(midi_path)
            # 파일명에서 트랙명 추론 (예: "piano.mid" → "piano")
            stem = p.stem.lower()
            # 접두사 정리 (예: "input_standard_piano" → "piano")
            for keyword in PIANO_TRACK_KEYWORDS + GUITAR_TRACK_KEYWORDS + ["bass", "drums", "strings", "other"]:
                if keyword in stem:
                    tracks[keyword] = p
                    break
            else:
                tracks[stem] = p

    else:
        raise YourMT3Error(
            f"YourMT3 transcribe() 반환 타입이 예상과 다릅니다: {type(midi_results)}\n"
            "YourMT3 버전 확인 후 yourmt3_extractor.py를 업데이트하세요."
        )

    if not tracks:
        raise YourMT3Error("YourMT3가 MIDI를 생성하지 않았습니다.")

    return tracks


def _select_track(tracks: dict, instrument: str, stem: str, out_dir: Path) -> Path:
    """
    instrument 파라미터에 따라 메인 MIDI 트랙을 선택.

    - instrument="1" (피아노): piano 키 우선, 없으면 "all" 또는 첫 번째 트랙
    - instrument="2" (기타): guitar 키 우선, 없으면 "all" 또는 첫 번째 트랙
    """
    if instrument == "1":
        keywords = PIANO_TRACK_KEYWORDS
    else:
        keywords = GUITAR_TRACK_KEYWORDS

    # 키워드 매칭 우선 탐색
    for keyword in keywords:
        if keyword in tracks:
            return tracks[keyword]

    # "all" 또는 단일 트랙 fallback
    if "all" in tracks:
        print(f"   ⚠️  instrument={instrument}에 맞는 트랙 없음 → 'all' 트랙 사용")
        return tracks["all"]

    # 첫 번째 트랙 fallback
    first_key = next(iter(tracks))
    print(f"   ⚠️  instrument={instrument}에 맞는 트랙 없음 → '{first_key}' 트랙 사용")
    return tracks[first_key]
