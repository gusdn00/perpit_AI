from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET


def _duration_value(elem: ET.Element) -> int:
    duration = elem.findtext("duration")
    return int(duration) if duration else 0


def _is_tab_part(part_elem: ET.Element) -> bool:
    return part_elem.find(".//clef/sign[.='TAB']") is not None


def _has_string_fret(note_elem: ET.Element) -> bool:
    technical = note_elem.find("./notations/technical")
    if technical is None:
        return False
    return technical.find("string") is not None and technical.find("fret") is not None


def _insert_chord_tag(note_elem: ET.Element) -> None:
    if note_elem.find("chord") is not None:
        return

    insert_at = 0
    first_tag = note_elem[0].tag if len(note_elem) else None
    if first_tag in {"cue", "grace"}:
        insert_at = 1
    note_elem.insert(insert_at, ET.Element("chord"))


def _normalize_voice(note_elem: ET.Element, voice_value: str = "1") -> None:
    voice = note_elem.find("voice")
    if voice is None:
        voice = ET.SubElement(note_elem, "voice")
    voice.text = voice_value


def _make_rest_like(note_elem: ET.Element) -> ET.Element:
    rest_note = deepcopy(note_elem)
    _normalize_voice(rest_note, "1")
    return rest_note


def _rewrite_tab_measure(measure_elem: ET.Element) -> None:
    current_time = 0
    timed_notes: list[tuple[int, ET.Element]] = []
    leading_elems: list[ET.Element] = []
    trailing_elems: list[ET.Element] = []

    for child in list(measure_elem):
        if child.tag == "note":
            note_copy = deepcopy(child)
            onset = current_time
            timed_notes.append((onset, note_copy))
            if note_copy.find("chord") is None:
                current_time += _duration_value(note_copy)
        elif child.tag == "backup":
            current_time -= _duration_value(child)
        elif child.tag == "forward":
            current_time += _duration_value(child)
        elif child.tag == "barline":
            trailing_elems.append(deepcopy(child))
        else:
            leading_elems.append(deepcopy(child))

    grouped_notes: dict[int, list[ET.Element]] = defaultdict(list)
    onset_order: list[int] = []
    for onset, note_elem in timed_notes:
        if onset not in grouped_notes:
            onset_order.append(onset)
        grouped_notes[onset].append(note_elem)

    first_tab_onset = None
    for onset in onset_order:
        if any(_has_string_fret(note) for note in grouped_notes[onset]):
            first_tab_onset = onset
            break

    measure_attrib = dict(measure_elem.attrib)
    measure_elem.clear()
    measure_elem.attrib.update(measure_attrib)

    for elem in leading_elems:
        measure_elem.append(elem)

    for onset in onset_order:
        chord_notes = grouped_notes[onset]
        tab_notes = [note for note in chord_notes if _has_string_fret(note)]
        rest_notes = [note for note in chord_notes if note.find("rest") is not None]

        if tab_notes:
            for idx, note_elem in enumerate(tab_notes):
                _normalize_voice(note_elem, "1")
                if idx > 0:
                    _insert_chord_tag(note_elem)
                measure_elem.append(note_elem)
            continue

        # TAB 파트에서 string/fret 없는 비-휴지 음표는 대개 voice/tie 잔재라 제거.
        if first_tab_onset is None:
            if rest_notes:
                measure_elem.append(_make_rest_like(rest_notes[0]))
            continue

        # 첫 실제 TAB 코드 전의 공백은 rest 하나로만 유지해 마디 위치를 보존.
        if onset < first_tab_onset and rest_notes:
            measure_elem.append(_make_rest_like(rest_notes[0]))

    for elem in trailing_elems:
        measure_elem.append(elem)


def postprocess_guitar_tab_musicxml(xml_path: Path | str) -> Path:
    """
    TAB 파트 MusicXML을 후처리해 같은 시점의 음들을 세로로 쌓인 코드로 정리한다.
    """
    xml_path = Path(xml_path)
    tree = ET.parse(xml_path)
    root = tree.getroot()

    for part_elem in root.findall("part"):
        if not _is_tab_part(part_elem):
            continue
        for measure_elem in part_elem.findall("measure"):
            _rewrite_tab_measure(measure_elem)

    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return xml_path


def _measure_has_sounded_note(measure_elem: ET.Element) -> bool:
    for note_elem in measure_elem.findall("note"):
        if note_elem.find("rest") is None and note_elem.find("pitch") is not None:
            return True
    return False


def trim_trailing_empty_measures(xml_path: Path | str) -> Path:
    """
    모든 파트를 기준으로 마지막 실제 음이 나온 마디 뒤의 빈 마디들을 잘라낸다.
    """
    xml_path = Path(xml_path)
    tree = ET.parse(xml_path)
    root = tree.getroot()

    parts = root.findall("part")
    if not parts:
        return xml_path

    global_last_sounded = 0
    for part_elem in parts:
        measures = part_elem.findall("measure")
        for idx, measure_elem in enumerate(measures, start=1):
            if _measure_has_sounded_note(measure_elem):
                global_last_sounded = max(global_last_sounded, idx)

    if global_last_sounded == 0:
        return xml_path

    for part_elem in parts:
        measures = part_elem.findall("measure")
        for measure_elem in measures[global_last_sounded:]:
            part_elem.remove(measure_elem)

    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return xml_path
