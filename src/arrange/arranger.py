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
    metadata, meter, tempo as m21tempo, converter,
    articulations, layout, instrument as m21instrument
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

# 표준 기타 튜닝 MIDI (6번줄 → 1번줄)
_GUITAR_STRING_MIDI = [40, 45, 50, 55, 59, 64]  # E2 A2 D3 G3 B3 E4

# 코드명 → 기타 보이싱 (6번줄 → 1번줄, x=뮤트)
# 현재 chord extractor는 메이저/마이너까지만 출력하므로 그 범위에 맞춰 정의.
_GUITAR_TAB_SHAPES = {
    "C":  ["x", 3, 2, 0, 1, 0],
    "C#": ["x", 4, 6, 6, 6, 4],
    "D":  ["x", "x", 0, 2, 3, 2],
    "D#": ["x", 6, 8, 8, 8, 6],
    "E":  [0, 2, 2, 1, 0, 0],
    "F":  [1, 3, 3, 2, 1, 1],
    "F#": [2, 4, 4, 3, 2, 2],
    "G":  [3, 2, 0, 0, 0, 3],
    "G#": [4, 6, 6, 5, 4, 4],
    "A":  ["x", 0, 2, 2, 2, 0],
    "A#": ["x", 1, 3, 3, 3, 1],
    "B":  ["x", 2, 4, 4, 4, 2],
    "Cm": ["x", 3, 5, 5, 4, 3],
    "C#m": ["x", 4, 6, 6, 5, 4],
    "Dm": ["x", "x", 0, 2, 3, 1],
    "D#m": ["x", 6, 8, 8, 7, 6],
    "Em": [0, 2, 2, 0, 0, 0],
    "Fm": [1, 3, 3, 1, 1, 1],
    "F#m": [2, 4, 4, 2, 2, 2],
    "Gm": [3, 5, 5, 3, 3, 3],
    "G#m": [4, 6, 6, 4, 4, 4],
    "Am": ["x", 0, 2, 2, 1, 0],
    "A#m": ["x", 1, 3, 3, 2, 1],
    "Bm": ["x", 2, 4, 4, 3, 2],
}


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


def _chord_start_end_beats(chord_info: dict, bpm: float) -> tuple[float, float]:
    """
    chord extractor가 제공한 beat 기준이 있으면 우선 사용하고, 없으면 초→박 변환을 사용한다.
    """
    if "start_beat" in chord_info and "end_beat" in chord_info:
        return float(chord_info["start_beat"]), float(chord_info["end_beat"])
    return _to_beats(chord_info["start"], bpm), _to_beats(chord_info["end"], bpm)


def _quantize(value: float, grid: float) -> float:
    """값을 grid 단위로 반올림 (예: grid=0.5이면 8분음표 단위)"""
    if grid <= 0:
        return value
    return round(value / grid) * grid


def _get_grid(difficulty: str) -> float:
    """난이도별 양자화 단위: Easy=0.5(8분음표), Normal=0.25(16분음표)"""
    return 0.5 if difficulty == "1" else 0.25


def _shape_to_tab_notes(shape: list) -> list[dict]:
    """
    기타 보이싱 shape를 실제 TAB 음 정보로 변환.

    Args:
        shape: 6번줄→1번줄 프렛 배열. 예) ["x", 3, 2, 0, 1, 0]

    Returns:
        [
            {"string": 5, "fret": 3, "midi": 48},
            ...
        ]
    """
    tab_notes = []
    for idx, fret in enumerate(shape):
        if fret == "x":
            continue

        string_number = 6 - idx  # MusicXML: 1=가장 높은 줄, 6=가장 낮은 줄
        midi_number = _GUITAR_STRING_MIDI[idx] + int(fret)
        tab_notes.append({
            "string": string_number,
            "fret": int(fret),
            "midi": midi_number,
        })

    return tab_notes


def _get_guitar_tab_notes(chord_name: str, difficulty: str) -> list[dict]:
    """
    코드명에 해당하는 기타 TAB 음 목록 반환.
    반주용 TAB이므로 동시 발음 수를 줄여 상위 현 중심으로 단순화한다.
    """
    shape = _GUITAR_TAB_SHAPES.get(chord_name, _GUITAR_TAB_SHAPES["C"])
    tab_notes = _shape_to_tab_notes(shape)

    keep_count = 2 if difficulty == "1" else 3
    if len(tab_notes) > keep_count:
        tab_notes = tab_notes[-keep_count:]

    return tab_notes


def _make_guitar_tab_note(tab_note: dict, duration: float) -> note.Note:
    """TAB용 단일 음표 생성 후 string/fret technical 정보 부착."""
    n = note.Note(_midi_pitch_name(tab_note["midi"]), quarterLength=duration)
    n.articulations.append(articulations.StringIndication(tab_note["string"]))
    n.articulations.append(articulations.FretIndication(tab_note["fret"]))
    return n


def _make_standard_guitar_note(tab_note: dict, duration: float) -> note.Note:
    """위 오선보용 기타 음표 생성."""
    return note.Note(_midi_pitch_name(tab_note["midi"]), quarterLength=duration)


def _build_guitar_pattern_events(
    tab_notes: list[dict],
    start_beat: float,
    end_beat: float,
    style: str,
    difficulty: str,
    grid: float,
) -> list[dict]:
    """
    기타 반주를 스트로크 중심 이벤트로 변환한다.
    """
    events = []
    if not tab_notes or end_beat <= start_beat:
        return events

    low_to_high = sorted(tab_notes, key=lambda x: x["string"], reverse=True)

    if style == "2":
        step = 2.0
    elif style == "1":
        step = 1.0
    else:
        step = 1.0

    start_beat = _quantize(start_beat, step)
    end_beat = _quantize(end_beat, step)
    if end_beat <= start_beat:
        end_beat = start_beat + step

    beat = start_beat

    while beat < end_beat:
        dur = min(step, end_beat - beat)
        if dur <= 0:
            break

        events.append({
            "beat": beat,
            "duration": dur,
            "tab_notes": low_to_high,
        })
        beat = round(beat + step, 4)

    return events


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
        raw_start_beat, raw_end_beat = _chord_start_end_beats(c, bpm)
        start_beat = _quantize(raw_start_beat, grid)
        end_beat   = _quantize(raw_end_beat, grid)
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
        raw_start_beat, raw_end_beat = _chord_start_end_beats(c, bpm)
        start_beat = _quantize(raw_start_beat, grid)
        end_beat   = _quantize(raw_end_beat, grid)
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


def _insert_pitches_into_part(
    part: stream.Part,
    midi_numbers: list[int],
    onset: float,
    duration: float,
    velocity: int,
) -> None:
    if not midi_numbers:
        return

    if len(midi_numbers) == 1:
        elem = note.Note(midi_numbers[0], quarterLength=duration)
    else:
        elem = m21chord.Chord(midi_numbers, quarterLength=duration)

    elem.volume.velocity = velocity
    part.insert(onset, elem)


def _trim_event_pitches(midi_numbers: list[int], hand: str) -> list[int]:
    unique_midis = sorted(set(midi_numbers))
    if hand == "right":
        return unique_midis[-4:]
    return unique_midis[:2]


def _build_rhythm_reduction_parts(
    rhythm_midi_path: Optional[Path],
    difficulty: str,
) -> tuple[stream.Part, stream.Part]:
    """
    멀티트랙 MIDI를 피아노 2단 리덕션으로 변환해 원곡 리듬을 최대한 유지한다.
    """
    right = stream.Part()
    right.partName = "Right Hand"
    right.append(clef.TrebleClef())
    right.append(meter.TimeSignature('4/4'))

    left = stream.Part()
    left.partName = "Left Hand"
    left.append(clef.BassClef())
    left.append(meter.TimeSignature('4/4'))

    if not rhythm_midi_path or not rhythm_midi_path.exists():
        print("   ⚠️  리듬 MIDI 없음 → 코드 기반 반주로 fallback")
        return right, left

    grid = _get_grid(difficulty)

    try:
        midi_score = converter.parse(str(rhythm_midi_path))
        right_events: dict[tuple[float, float], list[int]] = {}
        left_events: dict[tuple[float, float], list[int]] = {}
        inserted_count = 0

        for midi_part in midi_score.parts:
            part_name = (midi_part.partName or "").lower()
            instruments = midi_part.getInstruments(returnDefault=True)
            if any(isinstance(inst, m21instrument.UnpitchedPercussion) for inst in instruments):
                continue
            if "drum" in part_name:
                continue

            is_bass_track = "bass" in part_name

            for elem in midi_part.flatten().notes:
                onset = _quantize(float(elem.offset), grid)
                duration = max(_quantize(float(elem.duration.quarterLength), grid), grid)

                if isinstance(elem, note.Note):
                    midi_numbers = [int(elem.pitch.midi)]
                    velocity = getattr(elem.volume, "velocity", 80) or 80
                else:
                    midi_numbers = sorted(int(p.midi) for p in elem.pitches)
                    velocity = getattr(elem.volume, "velocity", 80) or 80

                if not midi_numbers:
                    continue

                if is_bass_track:
                    left_midis = midi_numbers
                    right_midis = []
                else:
                    right_midis = [m for m in midi_numbers if m >= 60]
                    left_midis = [m for m in midi_numbers if m < 60]

                    if not right_midis and midi_numbers:
                        highest = max(midi_numbers)
                        if highest >= 55:
                            right_midis = [highest]
                            left_midis = [m for m in midi_numbers if m != highest]

                if right_midis:
                    right_events.setdefault((onset, duration), []).extend(right_midis)
                if left_midis:
                    left_events.setdefault((onset, duration), []).extend(left_midis)
                inserted_count += len(right_midis) + len(left_midis)

        for (onset, duration), midi_numbers in sorted(right_events.items()):
            trimmed = _trim_event_pitches(midi_numbers, "right")
            _insert_pitches_into_part(right, trimmed, onset, duration, 80)

        for (onset, duration), midi_numbers in sorted(left_events.items()):
            trimmed = _trim_event_pitches(midi_numbers, "left")
            _insert_pitches_into_part(left, trimmed, onset, duration, 75)

        print(f"   ✅ 리듬 리덕션 MIDI 반영: {inserted_count}개 음표/코드")
    except Exception as e:
        print(f"   ⚠️  리듬 MIDI 리덕션 실패: {e}")

    return right, left


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
        raw_start_beat, raw_end_beat = _chord_start_end_beats(c, bpm)
        start_beat = _quantize(raw_start_beat, grid)
        end_beat   = _quantize(raw_end_beat, grid)
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


# ── 파트 빌더: 기타 2단 스태프 ──────────────────────────────────────────────

def _build_guitar_staff_parts(
    chords: list, bpm: float, style: str, difficulty: str
) -> tuple[stream.PartStaff, stream.PartStaff, layout.StaffGroup]:
    """
    기타: 위 standard notation + 아래 TAB의 2단 스태프 생성.

    스타일별:
      발라드: 8분음표 아르페지오
      팝:    8분음표 기반 단선율 패턴
      오리지널: 상/하행 교차 패턴
    """
    standard_part = stream.PartStaff()
    standard_part.partName = "Guitar"
    standard_part.append(clef.TrebleClef())
    standard_part.append(meter.TimeSignature('4/4'))

    tab_part = stream.PartStaff()
    tab_part.partName = "Guitar TAB"
    tab_part.append(clef.TabClef())
    tab_part.append(layout.StaffLayout(staffLines=6))
    tab_part.append(meter.TimeSignature('4/4'))
    grid = _get_grid(difficulty)

    for c in chords:
        start_beat, end_beat = _chord_start_end_beats(c, bpm)
        tab_notes = _get_guitar_tab_notes(c["chord"], difficulty)
        events = _build_guitar_pattern_events(
            tab_notes=tab_notes,
            start_beat=start_beat,
            end_beat=end_beat,
            style=style,
            difficulty=difficulty,
            grid=grid,
        )

        for event in events:
            onset = event["beat"]
            duration = event["duration"]
            selected_notes = event["tab_notes"]
            velocity = 65 if style == "2" else 90 if style == "1" else 80

            for tab_note in selected_notes:
                upper = _make_standard_guitar_note(tab_note, duration)
                lower = _make_guitar_tab_note(tab_note, duration)
                upper.volume.velocity = velocity
                lower.volume.velocity = velocity
                standard_part.insert(onset, upper)
                tab_part.insert(onset, lower)

    staff_group = layout.StaffGroup([standard_part, tab_part])
    staff_group.symbol = "brace"
    staff_group.barTogether = True

    return standard_part, tab_part, staff_group


# ── 메인 함수 ─────────────────────────────────────────────────────────────

def arrange(
    melody_midi_path: Optional[Path],
    rhythm_midi_path: Optional[Path],
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
        rhythm_midi_path: 원곡 리듬 보존용 멀티트랙 MIDI 경로
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
        # ── 기타: 위 standard notation + 아래 TAB ───────────────
        standard_part, tab_part, staff_group = _build_guitar_staff_parts(
            chords, bpm, style, difficulty
        )
        standard_part.insert(0, mm)
        score.insert(0, standard_part)
        score.insert(0, tab_part)
        score.insert(0, staff_group)
        print(f"   → 기타 2단 스태프 완성 (style={style_name})")

    else:
        # ── 피아노 ───────────────────────────────────────────────
        if purpose == "2":
            # 연주용: 오른손=멜로디, 왼손=코드 반주
            right = _build_melody_part(melody_midi_path, difficulty)
            left  = _build_accompaniment_part(chords, bpm, style, difficulty, octave=3)
            print(f"   → 피아노 연주용: 오른손=멜로디, 왼손={style_name} 반주")
        else:
            if rhythm_midi_path and rhythm_midi_path.exists():
                right, left = _build_rhythm_reduction_parts(rhythm_midi_path, difficulty)
                if len(right.flatten().notes) == 0 and len(left.flatten().notes) == 0:
                    right = _build_voicing_part(chords, bpm, style, difficulty)
                    left  = _build_bassline_part(chords, bpm, style, difficulty)
                    print("   → 리듬 MIDI 비어 있음 → 코드 기반 반주 fallback")
                else:
                    print("   → 피아노 반주용: 멀티트랙 MIDI 기반 리듬 리덕션")
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
