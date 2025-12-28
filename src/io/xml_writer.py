#최소 기능으로 더미 악보 출력
from pathlib import Path
from music21 import stream, note, metadata


def write_dummy_musicxml(title: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    score = stream.Score()
    score.insert(0, metadata.Metadata())
    score.metadata.title = title

    part = stream.Part()
    part.append(note.Note("C4", quarterLength=1))
    part.append(note.Note("E4", quarterLength=1))
    part.append(note.Note("G4", quarterLength=2))
    score.append(part)

    score.write("musicxml", str(out_path))
    return out_path
