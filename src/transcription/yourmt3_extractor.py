"""
yourmt3_extractor.py - YourMT3 기반 멀티트랙 MIDI 추출

YourMT3 (https://github.com/mimbres/YourMT3) 를 사용하여
오디오 파일 하나에서 악기별 MIDI를 한 번에 추출.

멀티트랙 모델(YPTF+Multi)을 사용해 Singing Voice / Piano 등 트랙을 분리한 뒤,
구간별로 병합해 단일 멜로디 MIDI를 생성:
  - 보컬이 있는 구간 → Singing Voice 트랙 우선
  - 보컬이 없는 구간 (인트로/간주) → 가장 두드러진 악기 트랙으로 채움

설치 방법:
    git clone https://huggingface.co/spaces/mimbres/YourMT3 ~/YourMT3
    pip install -r ~/YourMT3/requirements.txt  (torch/torchaudio 제외)

    # 체크포인트 다운로드
    python -c "
    from huggingface_hub import hf_hub_download
    hf_hub_download(
        repo_id='mimbres/YourMT3', repo_type='space',
        filename='amt/logs/2024/mc13_256_all_cross_v6_xk5_amp0811_edr005_attend_c_full_plus_2psn_nl26_sb_b26r_800k/checkpoints/model.ckpt',
        local_dir='/home/jisu/YourMT3',
    )"

환경 변수:
    YOURMT3_DIR: YourMT3 클론 경로 (기본: ~/YourMT3)
    YOURMT3_MODEL: 사용할 모델 이름 (기본: YPTF+Multi (PS))

사용 가능한 모델:
    "YPTF+Multi (PS)"       - 멀티트랙 추출 (악기별 분리) ← 기본값
    "YPTF+Single (noPS)"    - 단일 악기 추출 (피아노/기타 독주 전용)
    "YPTF.MoE+Multi (noPS)" - 멀티트랙 + MoE 모델 (고정밀)
    "YMT3+"                 - 기본 YMT3 모델
"""

import os
import sys
import shutil
from pathlib import Path

import pretty_midi
import torchaudio
import soundfile as sf


_DEFAULT_YOURMT3_DIR = os.environ.get(
    "YOURMT3_DIR",
    str(Path.home() / "YourMT3"),
)

_DEFAULT_MODEL = os.environ.get("YOURMT3_MODEL", "YPTF+Multi (PS)")

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
        "ptf_mc13_256_all_cross_v6_xk5_amp0811_edr005_attend_c_full_plus_2psn_nl26_sb_b26r_800k@model.ckpt",
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

# Singing Voice 트랙 판별 키워드 (YourMT3 output_inverse_vocab 기준)
_SINGING_KEYWORDS = ("singing", "vocal", "voice")

# 멜로디 트랙 우선순위 (앞쪽일수록 멜로디 가능성 높음)
# Bass/Drums는 멜로디에 부적합 → 완전 제외
_MELODY_PRIORITY = [
    "synth lead",          # 신스 리드: 인트로/간주 멜로디 담당 多
    "piano",               # 피아노: 멜로디 + 반주 모두 가능, 빈도 높음
    "guitar",              # 기타: 인트로 리프 등
    "reed",                # 색소폰, 클라리넷: 관악 멜로디
    "pipe",                # 플루트: 관악 멜로디
    "brass",               # 트럼펫, 트롬본: 화성/멜로디
    "chromatic percussion",# 마림바, 비브라폰 등
    "strings",             # 스트링: 멜로디보다 화성 역할 多지만 포함
    "organ",
    "synth pad",           # 패드: 화음용, 우선순위 낮음
]
_EXCLUDED_KEYWORDS = ("bass",)  # 베이스는 음역대가 낮아 멜로디 악보에 부적합 → 제외


class YourMT3Error(RuntimeError):
    pass


def _prepare_audio_info(audio_filepath: str) -> dict:
    """
    app.py의 prepare_media()와 동일한 audio_info 딕셔너리 생성.
    spaces 의존성 없이 로컬에서 직접 사용 가능.
    """
    try:
        info = torchaudio.info(audio_filepath)
        sample_rate = int(info.sample_rate)
        bits_per_sample = int(info.bits_per_sample)
        num_channels = int(info.num_channels)
        num_frames = int(info.num_frames)
        encoding = str.lower(info.encoding)
    except AttributeError:
        audio_info = sf.info(audio_filepath)
        sample_rate = int(audio_info.samplerate)
        subtype = audio_info.subtype_info or ""
        bits_per_sample = 16 if "16" in subtype else 24 if "24" in subtype else 0
        num_channels = int(audio_info.channels)
        num_frames = int(audio_info.frames)
        encoding = str.lower(audio_info.format)

    return {
        "filepath": audio_filepath,
        "track_name": os.path.basename(audio_filepath).split(".")[0],
        "sample_rate": sample_rate,
        "bits_per_sample": bits_per_sample,
        "num_channels": num_channels,
        "num_frames": num_frames,
        "duration": int(num_frames / sample_rate),
        "encoding": encoding,
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


def _merge_melody_tracks(midi_path: Path, out_path: Path) -> Path:
    """
    Multi 모델 출력 MIDI에서 멜로디 트랙을 병합해 단일 MIDI로 반환.

    병합 전략:
      1. Drums, Bass는 항상 제외
      2. Singing Voice 구간 → Singing Voice 노트 사용
      3. Singing Voice 없는 구간 (인트로/간주) →
         _MELODY_PRIORITY 순서대로 가장 우선순위 높은 트랙의 노트를 사용.
         같은 시간대에 여러 트랙이 겹치면 우선순위 높은 트랙만 남김 (50ms 단위 판정).
      4. Singing Voice 트랙 자체가 없으면 → 우선순위 가장 높은 트랙 단독 사용

    Args:
        midi_path: Multi 모델이 출력한 원본 MIDI 경로
        out_path:  병합된 멜로디 MIDI를 저장할 경로

    Returns:
        out_path (병합된 MIDI 경로)
    """
    pm = pretty_midi.PrettyMIDI(str(midi_path))

    singing_notes = []
    melody_tracks = []  # (priority_idx, name, notes)

    for inst in pm.instruments:
        if inst.is_drum:
            continue
        name_lower = inst.name.lower()

        if any(kw in name_lower for kw in _SINGING_KEYWORDS):
            singing_notes.extend(inst.notes)
            print(f"   [트랙] Singing Voice: '{inst.name}' ({len(inst.notes)}개)")
        elif any(kw in name_lower for kw in _EXCLUDED_KEYWORDS):
            print(f"   [트랙] 제외 (Bass): '{inst.name}'")
        else:
            pri = next(
                (i for i, kw in enumerate(_MELODY_PRIORITY) if kw in name_lower),
                len(_MELODY_PRIORITY),  # 목록에 없으면 최저 우선순위
            )
            melody_tracks.append((pri, inst.name, list(inst.notes)))
            print(f"   [트랙] 멜로디 후보: '{inst.name}' (우선순위 {pri}, {len(inst.notes)}개)")

    melody_tracks.sort(key=lambda x: x[0])  # 우선순위 낮은 숫자 = 높은 우선순위

    if not singing_notes:
        # 순수 연주곡: 우선순위 가장 높은 트랙 하나만 사용
        if melody_tracks:
            _, best_name, best_notes = melody_tracks[0]
            print(f"   [병합] 보컬 없음 → '{best_name}' 단독 사용")
            all_notes = list(best_notes)
        else:
            print("   [병합] 사용 가능한 멜로디 트랙 없음")
            all_notes = []
    else:
        # 보컬 활성 구간 계산 (겹치는 구간 병합)
        raw = sorted((n.start, n.end) for n in singing_notes)
        merged_intervals = []
        for s, e in raw:
            if merged_intervals and s <= merged_intervals[-1][1]:
                merged_intervals[-1][1] = max(merged_intervals[-1][1], e)
            else:
                merged_intervals.append([s, e])

        def _in_singing(t: float) -> bool:
            for s, e in merged_intervals:
                if s <= t < e:
                    return True
            return False

        # 인트로/간주 구간: 우선순위 높은 트랙이 이미 커버한 시간대는
        # 낮은 우선순위 트랙 노트를 건너뜀 (50ms 버킷 단위 판정)
        BUCKET = 0.05  # 50ms
        claimed: dict[int, int] = {}  # bucket → 해당 구간을 차지한 우선순위

        gap_notes: list = []
        for pri, name, notes in melody_tracks:
            added = 0
            for note in notes:
                mid = (note.start + note.end) / 2
                if _in_singing(mid):
                    continue  # 보컬 구간은 건너뜀

                bucket = int(mid / BUCKET)
                if bucket in claimed and claimed[bucket] < pri:
                    continue  # 더 높은 우선순위 트랙이 이미 이 구간 차지

                gap_notes.append(note)
                claimed[bucket] = pri
                added += 1

            if added:
                print(f"   [병합] '{name}': 인트로/간주 {added}개 노트 채움")

        all_notes = list(singing_notes) + gap_notes
        print(f"   [병합] 보컬 {len(singing_notes)}개 + 간주 채움 {len(gap_notes)}개 = {len(all_notes)}개")

    all_notes.sort(key=lambda n: n.start)

    # 단일 멜로디 트랙으로 새 MIDI 생성
    out_pm = pretty_midi.PrettyMIDI()
    melody_inst = pretty_midi.Instrument(program=0, name="Melody")
    melody_inst.notes = all_notes
    out_pm.instruments.append(melody_inst)
    out_pm.write(str(out_path))

    return out_path


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

    Multi 모델 사용 시 악기별 트랙이 분리된 MIDI가 출력되며,
    Singing Voice + 악기 트랙을 병합해 단일 멜로디 MIDI(selected)를 생성.

    Args:
        wav_path:     전처리된 wav 파일 경로
        out_dir:      MIDI 파일을 저장할 디렉토리
        instrument:   "1"=피아노, "2"=기타 (현재 미사용, 향후 트랙 선택에 활용 가능)
        yourmt3_dir:  YourMT3 클론 경로
        model_name:   사용할 모델 이름
        device:       'cpu' 또는 'cuda'
        model:        사전 로드된 모델 (없으면 자동 로드)

    Returns:
        {
            "selected": Path,  # 파이프라인에서 사용할 멜로디 MIDI (Singing+악기 병합)
            "all":      Path,  # YourMT3 원본 출력 MIDI (멀티트랙)
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

    # audio_info 준비
    audio_info = _prepare_audio_info(str(wav_path))
    track_name = audio_info["track_name"]

    # YourMT3 transcribe()는 현재 디렉토리에 ./model_output/{track_name}.mid 를 생성
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

    # 원본 멀티트랙 MIDI를 out_dir 최상단으로 복사
    dest_all = out_dir / f"{track_name}.mid"
    if midi_path != dest_all:
        shutil.copy2(str(midi_path), str(dest_all))

    # 멜로디 트랙 병합 (Singing Voice 우선 + 인트로/간주 악기 채움)
    dest_melody = out_dir / f"{track_name}_melody.mid"
    print(f"🎼 멜로디 트랙 병합 중...")
    _merge_melody_tracks(dest_all, dest_melody)

    print(f"✅ YourMT3 추출 완료: {dest_melody.name}")

    return {
        "all": dest_all,        # 원본 멀티트랙 MIDI
        "selected": dest_melody, # 병합된 단일 멜로디 MIDI (파이프라인 사용)
    }
