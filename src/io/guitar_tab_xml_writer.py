from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from src.arrange.arranger import _build_guitar_pattern_events, _get_guitar_tab_notes


_DIVISIONS = 480
_BEATS_PER_MEASURE = 4.0
_BEAT_TYPE = 4
_TUNING = [
    ("E", None, 2),
    ("A", None, 2),
    ("D", None, 3),
    ("G", None, 3),
    ("B", None, 3),
    ("E", None, 4),
]


def _pitch_components(midi_number: int) -> tuple[str, int | None, int]:
    names = [
        ("C", None), ("C", 1), ("D", None), ("D", 1), ("E", None), ("F", None),
        ("F", 1), ("G", None), ("G", 1), ("A", None), ("A", 1), ("B", None),
    ]
    step, alter = names[midi_number % 12]
    octave = (midi_number // 12) - 1
    return step, alter, octave


def _duration_spec(duration_beats: float) -> tuple[str, int]:
    mapping = {
        4.0: ("whole", 0),
        3.0: ("half", 1),
        2.0: ("half", 0),
        1.5: ("quarter", 1),
        1.0: ("quarter", 0),
        0.75: ("eighth", 1),
        0.5: ("eighth", 0),
        0.25: ("16th", 0),
    }
    rounded = round(duration_beats, 2)
    if rounded not in mapping:
        raise ValueError(f"Unsupported duration for MusicXML writer: {duration_beats}")
    return mapping[rounded]


def _duration_divisions(duration_beats: float) -> int:
    return int(round(duration_beats * _DIVISIONS))


def _build_note_element(
    *,
    midi_number: int | None,
    duration_beats: float,
    staff_number: int,
    voice: int,
    string: int | None = None,
    fret: int | None = None,
    is_rest: bool = False,
) -> ET.Element:
    note_elem = ET.Element("note")

    if is_rest:
        rest_elem = ET.SubElement(note_elem, "rest")
        if duration_beats >= _BEATS_PER_MEASURE:
            rest_elem.set("measure", "yes")
    else:
        step, alter, octave = _pitch_components(midi_number)
        pitch_elem = ET.SubElement(note_elem, "pitch")
        ET.SubElement(pitch_elem, "step").text = step
        if alter is not None:
            ET.SubElement(pitch_elem, "alter").text = str(alter)
        ET.SubElement(pitch_elem, "octave").text = str(octave)

    ET.SubElement(note_elem, "duration").text = str(_duration_divisions(duration_beats))
    ET.SubElement(note_elem, "voice").text = str(voice)

    if duration_beats < _BEATS_PER_MEASURE or not is_rest:
        note_type, dots = _duration_spec(duration_beats)
        ET.SubElement(note_elem, "type").text = note_type
        for _ in range(dots):
            ET.SubElement(note_elem, "dot")

    ET.SubElement(note_elem, "staff").text = str(staff_number)

    if string is not None and fret is not None:
        notations = ET.SubElement(note_elem, "notations")
        technical = ET.SubElement(notations, "technical")
        ET.SubElement(technical, "string").text = str(string)
        ET.SubElement(technical, "fret").text = str(fret)

    return note_elem


def _append_chord_mark(note_elem: ET.Element) -> None:
    note_elem.insert(0, ET.Element("chord"))


def _append_note_group(
    *,
    measure: ET.Element,
    tab_notes: list[dict],
    duration_beats: float,
    staff_number: int,
    voice: int,
) -> None:
    for idx, tab_note in enumerate(tab_notes):
        note_elem = _build_note_element(
            midi_number=tab_note["midi"],
            duration_beats=duration_beats,
            staff_number=staff_number,
            voice=voice,
            string=tab_note["string"] if staff_number == 2 else None,
            fret=tab_note["fret"] if staff_number == 2 else None,
        )
        if idx > 0:
            _append_chord_mark(note_elem)
        measure.append(note_elem)


def _split_events_by_measure(events: list[dict]) -> dict[int, list[dict]]:
    measures: dict[int, list[dict]] = defaultdict(list)

    for event in events:
        start = event["beat"]
        remaining = event["duration"]
        tab_notes = event["tab_notes"]
        while remaining > 1e-6:
            measure_idx = int(start // _BEATS_PER_MEASURE)
            measure_start = measure_idx * _BEATS_PER_MEASURE
            within_measure = start - measure_start
            available = _BEATS_PER_MEASURE - within_measure
            chunk = min(remaining, available)

            measures[measure_idx].append({
                "offset": round(within_measure, 4),
                "duration": round(chunk, 4),
                "tab_notes": tab_notes,
            })

            start += chunk
            remaining -= chunk

    return measures


def _fill_measure_timeline(events: list[dict]) -> list[dict]:
    if not events:
        return [{"kind": "rest", "duration": _BEATS_PER_MEASURE}]

    ordered = sorted(events, key=lambda item: item["offset"])
    timeline: list[dict] = []
    cursor = 0.0

    for event in ordered:
        if event["offset"] > cursor + 1e-6:
            timeline.append({
                "kind": "rest",
                "duration": round(event["offset"] - cursor, 4),
            })

        timeline.append({
            "kind": "note",
            "duration": event["duration"],
            "tab_notes": event["tab_notes"],
        })
        cursor = event["offset"] + event["duration"]

    if cursor < _BEATS_PER_MEASURE - 1e-6:
        timeline.append({
            "kind": "rest",
            "duration": round(_BEATS_PER_MEASURE - cursor, 4),
        })

    return timeline


def _build_staff_details() -> ET.Element:
    staff_details = ET.Element("staff-details")
    staff_details.set("number", "2")
    ET.SubElement(staff_details, "staff-lines").text = "6"

    # line=1 is the highest string in MusicXML staff-tuning order.
    for idx, (step, alter, octave) in enumerate(reversed(_TUNING), start=1):
        tuning = ET.SubElement(staff_details, "staff-tuning")
        tuning.set("line", str(idx))
        ET.SubElement(tuning, "tuning-step").text = step
        if alter is not None:
            ET.SubElement(tuning, "tuning-alter").text = str(alter)
        ET.SubElement(tuning, "tuning-octave").text = str(octave)

    return staff_details


def write_guitar_dual_staff_musicxml(
    *,
    out_path: Path,
    title: str,
    chords: list,
    bpm: float,
    style: str,
    difficulty: str,
) -> Path:
    """
    기타용 2단 스태프 MusicXML을 직접 생성한다.

    위 스태프는 standard notation, 아래 스태프는 TAB(string/fret)로 출력한다.
    """
    grid = 0.5 if difficulty == "1" else 0.25
    all_events: list[dict] = []

    for chord_info in chords:
        start_beat = chord_info["start"] * (bpm / 60.0)
        end_beat = chord_info["end"] * (bpm / 60.0)
        tab_notes = _get_guitar_tab_notes(chord_info["chord"], difficulty)
        chord_events = _build_guitar_pattern_events(
            tab_notes=tab_notes,
            start_beat=start_beat,
            end_beat=end_beat,
            style=style,
            difficulty=difficulty,
            grid=grid,
        )
        all_events.extend(chord_events)

    split_events = _split_events_by_measure(all_events)
    measure_count = max(split_events.keys(), default=0) + 1

    root = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = title
    ET.SubElement(root, "movement-title").text = title

    identification = ET.SubElement(root, "identification")
    creator = ET.SubElement(identification, "creator")
    creator.set("type", "composer")
    creator.text = "PerPit AI"

    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = "Guitar"

    part = ET.SubElement(root, "part", id="P1")

    for measure_no in range(1, measure_count + 1):
        measure = ET.SubElement(part, "measure", number=str(measure_no))

        if measure_no == 1:
            attributes = ET.SubElement(measure, "attributes")
            ET.SubElement(attributes, "divisions").text = str(_DIVISIONS)
            time = ET.SubElement(attributes, "time")
            ET.SubElement(time, "beats").text = str(int(_BEATS_PER_MEASURE))
            ET.SubElement(time, "beat-type").text = str(_BEAT_TYPE)
            ET.SubElement(attributes, "staves").text = "2"

            clef1 = ET.SubElement(attributes, "clef", number="1")
            ET.SubElement(clef1, "sign").text = "G"
            ET.SubElement(clef1, "line").text = "2"

            clef2 = ET.SubElement(attributes, "clef", number="2")
            ET.SubElement(clef2, "sign").text = "TAB"
            ET.SubElement(clef2, "line").text = "5"

            attributes.append(_build_staff_details())

            direction = ET.SubElement(measure, "direction")
            direction_type = ET.SubElement(direction, "direction-type")
            metronome = ET.SubElement(direction_type, "metronome")
            metronome.set("parentheses", "no")
            ET.SubElement(metronome, "beat-unit").text = "quarter"
            ET.SubElement(metronome, "per-minute").text = str(int(round(bpm)))
            ET.SubElement(direction, "staff").text = "1"
            sound = ET.SubElement(direction, "sound")
            sound.set("tempo", str(int(round(bpm))))

        measure_events = split_events.get(measure_no - 1, [])
        upper_timeline = _fill_measure_timeline(measure_events)
        lower_timeline = _fill_measure_timeline(measure_events)

        for item in upper_timeline:
            if item["kind"] == "rest":
                measure.append(
                    _build_note_element(
                        midi_number=None,
                        duration_beats=item["duration"],
                        staff_number=1,
                        voice=1,
                        is_rest=True,
                    )
                )
            else:
                _append_note_group(
                    measure=measure,
                    tab_notes=item["tab_notes"],
                    duration_beats=item["duration"],
                    staff_number=1,
                    voice=1,
                )

        backup = ET.SubElement(measure, "backup")
        ET.SubElement(backup, "duration").text = str(_duration_divisions(_BEATS_PER_MEASURE))

        for item in lower_timeline:
            if item["kind"] == "rest":
                measure.append(
                    _build_note_element(
                        midi_number=None,
                        duration_beats=item["duration"],
                        staff_number=2,
                        voice=2,
                        is_rest=True,
                    )
                )
            else:
                _append_note_group(
                    measure=measure,
                    tab_notes=item["tab_notes"],
                    duration_beats=item["duration"],
                    staff_number=2,
                    voice=2,
                )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path
