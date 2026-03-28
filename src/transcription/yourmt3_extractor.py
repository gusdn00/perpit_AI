"""
yourmt3_extractor.py - YourMT3 기반 멀티트랙 MIDI 추출

YourMT3 (https://github.com/mimbres/YourMT3) 를 사용하여
오디오 파일 하나에서 악기별 MIDI를 한 번에 추출.

기존 demucs + basic_pitch 2단계를 YourMT3 단일 모델로 대체.

설치 방법:
    git clone https://huggingface.co/spaces/mimbres/YourMT3 ~/YourMT3
    pip install -r ~/YourMT3/requirements.txt  (torch/torchaudio 제외)

환경 변수:
    YOURMT3_DIR: YourMT3 클론 경로 (기본: ~/YourMT3)
    YOURMT3_MODEL: 사용할 모델 이름 (기본: YPTF+Single (noPS))

사용 가능한 모델:
    "YPTF+Single (noPS)"   - 단일 악기 추출 (피아노/기타 독주)
    "YPTF+Multi (PS)"      - 멀티트랙 추출 (악기별 분리)
    "YPTF.MoE+Multi (noPS)"- 멀티트랙 + MoE 모델 (고정밀)
    "YMT3+"                - 기본 YMT3 모델
"""

import os
import sys
import shutil
from pathlib import Path

import torchaudio


_DEFAULT_YOURMT3_DIR = os.environ.get(
    "YOURMT3_DIR",
    str(Path.home() / "YourMT3"),  # ~/YourMT3 (기본 클론 위치)
)

_DEFAULT_MODEL = os.environ.get("YOURMT3_MODEL", "YPTF+Single (noPS)")

# 모델 이름 → load_model_checkpoint args 매핑 (app.py 기준)
_MODEL_ARGS = {
    "YMT3+": lambda pr: [
        "notask_all_cross_v6_xk2_amp0811_gm_ext_plus_nops_b72@model.ckpt",
        "-p", "2024", "-pr", pr,
    ],
    "YPTF+Single (noPS)": lambda pr: [
        "ptf_all_cross_rebal5_mirst_xk2_edr005_attend_c_full_plus_b100@model.ckpt",
        "-p", "2024", "-enc", "perceiver-tf", "-ac", "spec",
        "-hop", "300", "-atc", "1", "-pr", pr,
    ],
    "YPTF+Multi (PS)": lambda pr: [
        "mc13_256_all_cross_v6_xk5_amp0811_edr005_attend_c_full_plus_2psn_nl26_sb_b26r_800k@model.ckpt",
        "-p", "2024", "-tk", "mc13_full_plus_256",
        "-dec", "multi-t5", "-nl", "26", "-enc", "perceiver-tf",
        "-ac", "spec", "-hop", "300", "-atc", "1", "-pr", pr,
    ],
    "YPTF.MoE+Multi (noPS)": lambda pr: [
        "mc13_256_g4_all_v7_mt3f_sqr_rms_moe_wf4_n8k2_silu_rope_rp_b36_nops@last.ckpt",
        "-p", "2024", "-tk", "mc13_full_plus_256", "-dec", "multi-t5",
        "-nl", "26", "-enc", "perceiver-tf", "-sqr", "1", "-ff", "moe",
        "-wf", "4", "-nmoe", "8", "-kmoe", "2", "-act", "silu", "-epe", "rope",
        "-rp", "1", "-ac", "spec", "-hop", "300", "-atc", "1", "-pr", pr,
    ],
}


class YourMT3Error(RuntimeError):
    pass


def _prepare_audio_info(audio_filepath: str) -> dict:
    """
    app.py의 prepare_media()와 동일한 audio_info 딕셔너리 생성.
    spaces 의존성 없이 로컬에서 직접 사용 가능.
    """
    info = torchaudio.info(audio_filepath)
    return {
        "filepath": audio_filepath,
        "track_name": os.path.basename(audio_filepath).split(".")[0],
        "sample_rate": int(info.sample_rate),
        "bits_per_sample": int(info.bits_per_sample),
        "num_channels": int(info.num_channels),
        "num_frames": int(info.num_frames),
        "duration": int(info.num_frames / info.sample_rate),
        "encoding": str.lower(info.encoding),
    }


def _setup_sys_path(yourmt3_dir: str) -> Path:
    """YourMT3 Space 루트와 amt/src를 sys.path에 추가."""
    mt3_path = Path(yourmt3_dir)
    if not mt3_path.exists():
        raise YourMT3Error(
            f"YourMT3 설치 디렉토리가 없습니다: {yourmt3_dir}\n"
            f"설치: git clone https://huggingface.co/spaces/mimbres/YourMT3 {yourmt3_dir}"
        )

    amt_src = mt3_path / "amt" / "src"
    for p in [str(mt3_path), str(amt_src)]:
        if p not in sys.path:
            sys.path.insert(0, p)

    return mt3_path


def load_model(
    yourmt3_dir: str = _DEFAULT_YOURMT3_DIR,
    model_name: str = _DEFAULT_MODEL,
    device: str = "cpu",
):
    """
    YourMT3 모델 로드.

    Args:
        yourmt3_dir: YourMT3 클론 경로
        model_name:  사용할 모델 이름 (_MODEL_ARGS 키 중 하나)
        device:      'cpu' 또는 'cuda'

    Returns:
        로드된 YourMT3 모델 (eval 모드)
    """
    _setup_sys_path(yourmt3_dir)

    try:
        from model_helper import load_model_checkpoint
    except ImportError as e:
        raise YourMT3Error(f"YourMT3 임포트 실패: {e}") from e

    if model_name not in _MODEL_ARGS:
        raise YourMT3Error(
            f"지원하지 않는 모델: '{model_name}'\n"
            f"사용 가능: {list(_MODEL_ARGS.keys())}"
        )

    # CPU는 bf16 미지원 → 32비트 사용
    precision = "32" if device == "cpu" else "16"
    args = _MODEL_ARGS[model_name](precision)

    print(f"   모델 로드: {model_name} (device={device})")

    # 체크포인트 경로가 cwd 기준 상대경로 → YourMT3 디렉토리에서 실행
    original_cwd = os.getcwd()
    try:
        os.chdir(yourmt3_dir)
        model = load_model_checkpoint(args=args, device=device)
    finally:
        os.chdir(original_cwd)

    return model


def transcribe_audio(
    wav_path: Path,
    out_dir: Path,
    instrument: str = "1",
    yourmt3_dir: str = _DEFAULT_YOURMT3_DIR,
    model_name: str = _DEFAULT_MODEL,
    device: str = "cpu",
    model=None,
) -> dict:
    """
    YourMT3로 오디오를 MIDI로 변환.

    Args:
        wav_path:     전처리된 wav 파일 경로
        out_dir:      MIDI 파일을 저장할 디렉토리
        instrument:   "1"=피아노, "2"=기타 (메인 트랙 선택에 사용)
        yourmt3_dir:  YourMT3 클론 경로
        model_name:   사용할 모델 이름
        device:       'cpu' 또는 'cuda'
        model:        사전 로드된 모델 (없으면 자동 로드)

    Returns:
        {
            "selected": Path,  # 파이프라인에서 사용할 메인 MIDI
            "all":      Path,  # YourMT3 원본 출력 MIDI
        }
    """
    if not isinstance(wav_path, Path):
        wav_path = Path(wav_path)

    if not wav_path.exists():
        raise YourMT3Error(f"입력 WAV 파일이 없습니다: {wav_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    mt3_path = _setup_sys_path(yourmt3_dir)

    print(f"🎵 YourMT3 음 추출 시작: {wav_path.name} (모델: {model_name})")

    try:
        from model_helper import load_model_checkpoint, transcribe
    except ImportError as e:
        raise YourMT3Error(f"YourMT3 임포트 실패: {e}") from e

    # 모델 로드 (외부에서 사전 로드된 모델 재사용 가능)
    if model is None:
        model = load_model(yourmt3_dir, model_name, device)

    # audio_info 준비 (app.py의 prepare_media와 동일 구조, spaces 의존성 없이 직접 구현)
    audio_info = _prepare_audio_info(str(wav_path))
    track_name = audio_info["track_name"]

    # YourMT3 transcribe()는 현재 디렉토리에 ./model_output/{track_name}.mid 를 생성
    # 실행 디렉토리를 out_dir로 변경해 결과를 out_dir/model_output/ 에 받음
    original_cwd = os.getcwd()
    try:
        os.chdir(str(out_dir))
        midi_path_str = transcribe(model, audio_info)
    finally:
        os.chdir(original_cwd)

    # transcribe()가 반환한 경로 (out_dir 기준 상대경로일 수 있음)
    midi_path = Path(midi_path_str)
    if not midi_path.is_absolute():
        midi_path = out_dir / midi_path

    if not midi_path.exists():
        raise YourMT3Error(f"YourMT3 MIDI 출력이 없습니다: {midi_path}")

    # 결과를 out_dir 최상단으로 복사 (model_output/ 서브디렉토리에서 꺼냄)
    dest = out_dir / f"{track_name}.mid"
    if midi_path != dest:
        shutil.copy2(str(midi_path), str(dest))

    print(f"✅ YourMT3 추출 완료: {dest.name}")

    return {
        "all": dest,
        "selected": dest,  # Single 모델은 단일 MIDI → 항상 selected
    }
