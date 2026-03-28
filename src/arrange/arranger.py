"""
arranger.py - PerPit AI 편곡 핵심 로직

melody MIDI + 코드 진행 + BPM + 옵션 → music21 Score 생성

지원 케이스:
  - 피아노 + 연주용(purpose=2): 오른손=멜로디 / 왼손=코드 반주 패턴
  - 피아노 + 반주용(purpose=1): 오른손=코드 보이싱 / 왼손=베이스라인
  - 기타(instrument=2):        단일 보표, 코드 반주 패턴 (purpose 무관)
"""

from pathlib import Path
from typing import Optional
from music21 import (
    stream, note, chord as m21chord, clef,
    metadata, meter, tempo as m21tempo, converter
)


# ── 상수 ──────────────────────────────────────────────────────────────────

# 피치 클래스 (반음 번호) - chords_extract.py가 출력하는 코드 이름 대응
_PC = {
    'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5,
    'F#': 6, 'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11
}

# MIDI 번호 → 노트 이름 변환용
_NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# style 숫자 → 이름 (로그용)
_STYLE_NAME = {"1": "팝", "2": "발라드", "3": "오리지널"}


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────

def _midi_pitch_name(midi: int) -> str:
    """MIDI 번호 → music21 피치 이름 (예: 60 → 'C4', 48 → 'C3')"""
    octave = (midi // 12) - 1
    return f"{_NOTE_NAMES[midi % 12]}{octave}"


def _chord_midi_notes(chord_name: str, base_octave: int = 3, difficulty: str = "2") -> list:
    """
    코드명 → MIDI 번호 리스트

    Args:
        chord_name: 'C', 'Am', 'C#m' 등 (chords_extract.py 출력 형식)
        base_octave: 근음 옥타브 (3 → C3=48, 4 → C4=60)
        difficulty: "1"=Easy(근음+3음만), "2"=Normal(근음+3음+5음)

    Returns:
        [근음_midi, 3음_midi, 5음_midi] 또는 [근음_midi, 3음_midi]
    """
    is_minor = chord_name.endswith('m')
    root_str = chord_name[:-1] if is_minor else chord_name
    root_pc = _PC.get(root_str, 0)

    # C3=48, C4=60 → root_midi = (octave+1)*12 + pitch_class
    root_midi = (base_octave + 1) * 12 + root_pc

    # 인터벌: 장음계=[0,4,7], 단음계=[0,3,7]
    intervals = [0, 3, 7] if is_minor else [0, 4, 7]

    # Easy 난이도: 근음+3음만 (7음·9음 제거 효과)
    if difficulty == "1":
        intervals = intervals[:2]

    return [root_midi + i for i in intervals]


def _to_beats(seconds: float, bpm: float) -> float:
    """초(seconds) → 박(beat) 변환: beat = seconds * (bpm / 60)"""
    return seconds * (bpm / 60.0)


def _quantize(value: float, grid: float) -> float:
    """값을 grid 단위로 반올림 (예: grid=0.5이면 8분음표 단위)"""
    if grid <= 0:
        return value
    return round(value / grid) * grid


def _get_grid(difficulty: str) -> float:
    """난이도별 양자화 단위: Easy=0.5(8분음표), Normal=0.25(16분음표)"""
    return 0.5 if difficulty == "1" else 0.25


# ── 파트 빌더: 왼손 반주 ──────────────────────────────────────────────────

def _build_accompaniment_part(
    chords: list, bpm: float, style: str, difficulty: str, octave: int = 3
) -> stream.Part:
    """
    피아노 연주용 왼손: 코드 기반 반주 패턴 생성

    스타일별 패턴:
      발라드(2): 아르페지오 [근음→5음→3음→5음] 1박 단위 velocity=60
      팝(1):    파워코드 [근음+5음] 2박 단위 velocity=110
      오리지널(3): 블록코드 (동시에 치기) velocity=80
    """
    part = stream.Part()
    part.partName = "Left Hand"
    part.append(clef.BassClef())
    part.append(meter.TimeSignature('4/4'))

    grid = _get_grid(difficulty)

    for c in chords:
        start_beat = _quantize(_to_beats(c["start"], bpm), grid)
        end_beat   = _quantize(_to_beats(c["end"],   bpm), grid)
        duration   = max(end_beat - start_beat, grid)

        midi_notes = _chord_midi_notes(c["chord"], base_octave=octave, difficulty=difficulty)
        if not midi_notes:
            continue

        root_p  = _midi_pitch_name(midi_notes[0])
        third_p = _midi_pitch_name(midi_notes[1]) if len(midi_notes) > 1 else root_p
        fifth_p = _midi_pitch_name(midi_notes[2]) if len(midi_notes) > 2 else third_p

        if style == "2":
            # 발라드: 아르페지오 [근음→5음→3음→5음] 1박씩
            pattern = [root_p, fifth_p, third_p, fifth_p]
            beat, idx = start_beat, 0
            while beat < end_beat:
                n = note.Note(pattern[idx % 4], quarterLength=min(1.0, end_beat - beat))
                n.volume.velocity = 60
                part.insert(beat, n)
                beat = _quantize(beat + 1.0, grid)
                idx += 1

        elif style == "1":
            # 팝: 파워코드 [근음+5음] 2박씩
            beat = start_beat
            while beat < end_beat:
                dur = min(2.0, end_beat - beat)
                ch = m21chord.Chord([root_p, fifth_p], quarterLength=dur)
                ch.volume.velocity = 110
                part.insert(beat, ch)
                beat = _quantize(beat + 2.0, grid)

        else:
            # 오리지널: 블록코드 (전체 지속)
            pitches = [_midi_pitch_name(m) for m in midi_notes]
            ch = m21chord.Chord(pitches, quarterLength=duration)
            ch.volume.velocity = 80
            part.insert(start_beat, ch)

    return part


def _build_bassline_part(chords: list, bpm: float, style: str, difficulty: str) -> stream.Part:
    """
    피아노 반주용 왼손: 베이스라인 (근음 위주, 옥타브 2)

    스타일별:
      발라드: 2분음표 근음
      팝:    8분음표 근음 반복
      오리지널: 4분음표 근음
    """
    part = stream.Part()
    part.partName = "Left Hand"
    part.append(clef.BassClef())
    part.append(meter.TimeSignature('4/4'))

    grid = _get_grid(difficulty)

    for c in chords:
        start_beat = _quantize(_to_beats(c["start"], bpm), grid)
        end_beat   = _quantize(_to_beats(c["end"],   bpm), grid)
        duration   = max(end_beat - start_beat, grid)

        # 베이스는 옥타브 2 (C2=36 영역, 더 낮은 음)
        midi_notes = _chord_midi_notes(c["chord"], base_octave=2, difficulty=difficulty)
        root_p = _midi_pitch_name(midi_notes[0])

        if style == "2":
            # 발라드: 2분음표 근음
            n = note.Note(root_p, quarterLength=min(2.0, duration))
            n.volume.velocity = 65
            part.insert(start_beat, n)

        elif style == "1":
            # 팝: 8분음표 근음 반복
            beat = start_beat
            while beat < end_beat:
                n = note.Note(root_p, quarterLength=min(0.5, end_beat - beat))
                n.volume.velocity = 80
                part.insert(beat, n)
                beat = _quantize(beat + 0.5, grid)

        else:
            # 오리지널: 4분음표 근음
            n = note.Note(root_p, quarterLength=min(1.0, duration))
            n.volume.velocity = 70
            part.insert(start_beat, n)

    return part


# ── 파트 빌더: 오른손 ─────────────────────────────────────────────────────

def _build_melody_part(melody_midi_path: Optional[Path], difficulty: str) -> stream.Part:
    """
    피아노 연주용 오른손: MIDI에서 멜로디 로드 후 난이도별 양자화

    difficulty=1(Easy):   0.5박 단위 양자화
    difficulty=2(Normal): 0.25박 단위 양자화
    """
    part = stream.Part()
    part.partName = "Right Hand"
    part.append(clef.TrebleClef())
    part.append(meter.TimeSignature('4/4'))

    grid = _get_grid(difficulty)

    if not melody_midi_path or not melody_midi_path.exists():
        print("   ⚠️  멜로디 MIDI 없음 → 빈 오른손 파트 생성")
        part.append(note.Rest(quarterLength=4.0))
        return part

    try:
        midi_score = converter.parse(str(melody_midi_path))
        note_count = 0
        for n in midi_score.flat.notes:
            if isinstance(n, note.Note):
                onset = _quantize(float(n.offset), grid)
                dur   = max(_quantize(float(n.duration.quarterLength), grid), grid)
                new_note = note.Note(n.pitch, quarterLength=dur)
                new_note.volume.velocity = getattr(n.volume, 'velocity', 80) or 80
                part.insert(onset, new_note)
                note_count += 1
        print(f"   ✅ 멜로디 {note_count}개 음표 로드")
    except Exception as e:
        print(f"   ⚠️  멜로디 MIDI 로드 실패: {e}")
        part.append(note.Rest(quarterLength=4.0))

    return part


def _build_voicing_part(chords: list, bpm: float, style: str, difficulty: str) -> stream.Part:
    """
    피아노 반주용 오른손: 코드 보이싱 (옥타브 4 영역)

    스타일별:
      발라드: 아르페지오 위로 1박씩
      팝:    블록코드 2박씩
      오리지널: 블록코드 전체 지속
    """
    part = stream.Part()
    part.partName = "Right Hand"
    part.append(clef.TrebleClef())
    part.append(meter.TimeSignature('4/4'))

    grid = _get_grid(difficulty)

    for c in chords:
        start_beat = _quantize(_to_beats(c["start"], bpm), grid)
        end_beat   = _quantize(_to_beats(c["end"],   bpm), grid)
        duration   = max(end_beat - start_beat, grid)

        # 오른손: 옥타브 4 (C4=60 영역)
        midi_notes = _chord_midi_notes(c["chord"], base_octave=4, difficulty=difficulty)
        pitches = [_midi_pitch_name(m) for m in midi_notes]

        if style == "2":
            # 발라드: 아르페지오 위로 1박씩
            beat, idx = start_beat, 0
            while beat < end_beat:
                n = note.Note(pitches[idx % len(pitches)], quarterLength=min(1.0, end_beat - beat))
                n.volume.velocity = 65
                part.insert(beat, n)
                beat = _quantize(beat + 1.0, grid)
                idx += 1

        elif style == "1":
            # 팝: 블록코드 2박씩
            beat = start_beat
            while beat < end_beat:
                dur = min(2.0, end_beat - beat)
                ch = m21chord.Chord(pitches, quarterLength=dur)
                ch.volume.velocity = 100
                part.insert(beat, ch)
                beat = _quantize(beat + 2.0, grid)

        else:
            # 오리지널: 블록코드 전체 지속
            ch = m21chord.Chord(pitches, quarterLength=duration)
            ch.volume.velocity = 80
            part.insert(start_beat, ch)

    return part


# ── 파트 빌더: 기타 ───────────────────────────────────────────────────────

def _build_guitar_part(chords: list, bpm: float, style: str, difficulty: str) -> stream.Part:
    """
    기타: 단일 높은음자리표, 코드 반주 패턴 (옥타브 3 영역)

    스타일별:
      발라드: 아르페지오 피킹 0.5박씩
      팝:    파워코드 [근음+5음] 다운스트로크 2박씩
      오리지널: 블록코드 스트로크 1박씩
    """
    part = stream.Part()
    part.partName = "Guitar"
    part.append(clef.TrebleClef())
    part.append(meter.TimeSignature('4/4'))

    grid = _get_grid(difficulty)

    for c in chords:
        start_beat = _quantize(_to_beats(c["start"], bpm), grid)
        end_beat   = _quantize(_to_beats(c["end"],   bpm), grid)

        midi_notes = _chord_midi_notes(c["chord"], base_octave=3, difficulty=difficulty)
        pitches = [_midi_pitch_name(m) for m in midi_notes]
        root_p  = pitches[0]
        fifth_p = pitches[2] if len(pitches) > 2 else pitches[-1]

        if style == "2":
            # 발라드: 아르페지오 피킹 (0.5박씩)
            beat, idx = start_beat, 0
            while beat < end_beat:
                n = note.Note(pitches[idx % len(pitches)], quarterLength=min(0.5, end_beat - beat))
                n.volume.velocity = 65
                part.insert(beat, n)
                beat = _quantize(beat + 0.5, grid)
                idx += 1

        elif style == "1":
            # 팝: 파워코드 다운스트로크 (2박씩)
            beat = start_beat
            while beat < end_beat:
                dur = min(2.0, end_beat - beat)
                ch = m21chord.Chord([root_p, fifth_p], quarterLength=dur)
                ch.volume.velocity = 110
                part.insert(beat, ch)
                beat = _quantize(beat + 2.0, grid)

        else:
            # 오리지널: 블록코드 스트로크 (1박씩)
            beat = start_beat
            while beat < end_beat:
                dur = min(1.0, end_beat - beat)
                ch = m21chord.Chord(pitches, quarterLength=dur)
                ch.volume.velocity = 80
                part.insert(beat, ch)
                beat = _quantize(beat + 1.0, grid)

    return part


# ── 메인 함수 ─────────────────────────────────────────────────────────────

def arrange(
    melody_midi_path: Optional[Path],
    chords: list,
    bpm: float,
    instrument: str,
    purpose: str,
    style: str,
    difficulty: str,
    title: str,
) -> stream.Score:
    """
    편곡 메인 함수. music21 Score 반환.

    Args:
        melody_midi_path: 정제된 멜로디 MIDI 경로 (기타 or 반주용이면 None 가능)
        chords: [{"chord": "C", "start": 0.0, "end": 2.5}, ...] (초 단위)
        bpm:    BPM (chords_extract에서 추출)
        instrument: "1"=피아노, "2"=기타
        purpose:    "1"=반주용, "2"=연주용
        style:      "1"=팝, "2"=발라드, "3"=오리지널
        difficulty: "1"=Easy, "2"=Normal
        title:      악보 제목

    Returns:
        music21.stream.Score
    """
    style_name = _STYLE_NAME.get(style, "?")
    print(f"🎼 편곡 시작: [{title}]  instrument={instrument}  purpose={purpose}  style={style_name}  difficulty={difficulty}  BPM={bpm:.1f}")

    score = stream.Score()

    # 메타데이터 (제목)
    md = metadata.Metadata()
    md.title = title
    score.insert(0, md)

    # 빠르기 표시
    mm = m21tempo.MetronomeMark(number=int(bpm))

    if instrument == "2":
        # ── 기타: 단일 파트 ──────────────────────────────────────
        guitar_part = _build_guitar_part(chords, bpm, style, difficulty)
        guitar_part.insert(0, mm)
        score.append(guitar_part)
        print(f"   → 기타 파트 완성 (style={style_name})")

    else:
        # ── 피아노 ───────────────────────────────────────────────
        if purpose == "2":
            # 연주용: 오른손=멜로디, 왼손=코드 반주
            right = _build_melody_part(melody_midi_path, difficulty)
            left  = _build_accompaniment_part(chords, bpm, style, difficulty, octave=3)
            print(f"   → 피아노 연주용: 오른손=멜로디, 왼손={style_name} 반주")
        else:
            # 반주용: 오른손=코드 보이싱, 왼손=베이스라인
            right = _build_voicing_part(chords, bpm, style, difficulty)
            left  = _build_bassline_part(chords, bpm, style, difficulty)
            print(f"   → 피아노 반주용: 오른손=코드보이싱, 왼손=베이스라인")

        right.insert(0, mm)
        score.append(right)
        score.append(left)

    print(f"✅ 편곡 완료: {len(score.parts)}개 파트, 코드 {len(chords)}개 처리")
    return score
