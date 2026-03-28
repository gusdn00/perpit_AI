"""
pipeline/run.py - PerPit AI 메인 파이프라인

Before (8단계): 음원 → 전처리 → demucs 분리 → Basic Pitch → MIDI 후처리 → 코드추출 → 편곡 → XML
After  (6단계): 음원 → 전처리 → YourMT3 → 코드추출 → 편곡 → XML

관련 이슈:
    #17 - YourMT3로 피치 추출 교체
    #16 - pipeline/run.py 교체
"""

from pathlib import Path

from src.audio.preprocess import preprocess_audio
from src.transcription.yourmt3_extractor import transcribe_audio
from src.chord.chords_extract import extract_chords
from src.arrange.arranger import arrange
from src.pipeline.context import PipelineContext


def run_pipeline(args: dict, out_dir: Path) -> str:
    """
    PerPit AI 파이프라인 실행.

    Args:
        args:    API 요청 파라미터
                 {
                   "file":       str,  # 업로드된 오디오 경로
                   "title":      str,
                   "instrument": str,  # "1"=피아노, "2"=기타
                   "purpose":    str,  # "1"=반주용, "2"=연주용
                   "style":      str,  # "1"=팝, "2"=발라드, "3"=오리지널
                   "difficulty": str,  # "1"=Easy, "2"=Normal
                 }
        out_dir: 결과물 저장 디렉토리 (job_id 기반, server.py가 생성)

    Returns:
        score.xml 절대 경로 (str)
    """

    # ── Context 생성 ──────────────────────────────────────────────────────────
    ctx = PipelineContext(
        file=Path(args["file"]),
        title=args.get("title", "Untitled"),
        instrument=str(args.get("instrument", "1")),
        purpose=str(args.get("purpose", "1")),
        style=str(args.get("style", "1")),
        difficulty=str(args.get("difficulty", "2")),
        has_lyrics=False,  # 현재 미사용 (보컬 감지 미구현)
    )

    print(f"\n{'='*60}")
    print(f"[Pipeline] 시작: {ctx.title}")
    print(f"  instrument={ctx.instrument}  purpose={ctx.purpose}  style={ctx.style}  difficulty={ctx.difficulty}")
    print(f"{'='*60}\n")

    # ── Step 1: 오디오 전처리 (mp3/wav → 표준 wav) ────────────────────────────
    print("[Step 1] 오디오 전처리")
    ctx.standard_wav = preprocess_audio(
        input_path=ctx.file,
        out_dir=out_dir / "audio",
    )

    # ── Step 2: YourMT3 음 추출 (demucs + basic_pitch 대체) ──────────────────
    print("\n[Step 2] YourMT3 음 추출")
    ctx.transcribed_tracks = transcribe_audio(
        wav_path=ctx.standard_wav,
        out_dir=out_dir / "midi",
        instrument=ctx.instrument,
    )
    ctx.selected_midi = ctx.transcribed_tracks["selected"]

    # ── Step 3: 코드 추출 ────────────────────────────────────────────────────
    print("\n[Step 3] 코드 추출")
    ctx.chords, ctx.tempo = extract_chords(ctx.standard_wav)
    print(f"   BPM={ctx.tempo:.1f}  코드 수={len(ctx.chords)}")

    # ── Step 4: 편곡 (arranger → music21 Score) ───────────────────────────────
    print("\n[Step 4] 편곡")
    # 기타(instrument=2) or 반주용(purpose=1): 멜로디 MIDI 불필요
    melody_midi = None
    if ctx.instrument == "1" and ctx.purpose == "2":
        melody_midi = ctx.selected_midi

    score = arrange(
        melody_midi_path=melody_midi,
        chords=ctx.chords,
        bpm=ctx.tempo,
        instrument=ctx.instrument,
        purpose=ctx.purpose,
        style=ctx.style,
        difficulty=ctx.difficulty,
        title=ctx.title,
    )

    # ── Step 5: MusicXML 저장 ─────────────────────────────────────────────────
    print("\n[Step 5] MusicXML 저장")
    xml_path = out_dir / "score.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    score.write("musicxml", str(xml_path))
    ctx.output_xml = xml_path
    print(f"   저장 완료: {xml_path}")

    print(f"\n{'='*60}")
    print(f"[Pipeline] 완료: {ctx.title} → {xml_path.name}")
    print(f"{'='*60}\n")

    return str(xml_path)
