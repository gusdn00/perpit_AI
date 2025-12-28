#config에서 온 값들을 표준화하여 보관하는 객체
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PipelineContext:
    # === input config ===
    file: Path                 # audio file path (mp3/wav)
    title: str
    purpose: str               # "1" or "2"
    style: str                 # "1" or "2" or "3"
    difficulty: str            # "1" or "2"

    # === derived flags ===
    has_lyrics: bool

    # === outputs ===
    output_xml: Optional[Path] = None
    
    standard_wav: Path | None = None
    pitch_midi: Path | None = None