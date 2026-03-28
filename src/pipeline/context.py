#config에서 온 값들을 표준화하여 보관하는 객체
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PipelineContext:
    # === input config ===
    file: Path                 # audio file path (mp3/wav)
    title: str
    instrument: str            # "1"=피아노, "2"=기타
    purpose: str               # "1"=반주용, "2"=연주용
    style: str                 # "1"=팝, "2"=발라드, "3"=오리지널
    difficulty: str            # "1"=Easy, "2"=Normal

    # === derived flags ===
    has_lyrics: bool

    # === intermediate outputs ===
    standard_wav: Path | None = None
    separated_tracks: dict | None = None   # demucs 분리 결과 {"vocals": Path, "piano": Path, ...}
    pitch_midi: Path | None = None
    chords: list | None = None             # 코드 추출 결과 [{"chord": "C", "start": 0.0, "end": 2.5}, ...]
    tempo: float | None = None             # BPM

    # === final output ===
    output_xml: Optional[Path] = None