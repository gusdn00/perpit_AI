from pathlib import Path
import numpy as np
import librosa


def extract_chords(wav_path: Path) -> tuple:
    """
    Extract chords and BPM from a given audio file path.
    madmom CNN 기반 코드 인식 사용 (마디 단위로 스냅).

    Args:
        wav_path (Path): Path to the WAV file.
    Returns:
        tuple: (chords, tempo)
            - chords: list of dicts [{'chord': 'C', 'start': 0.0, 'end': 1.0, 'start_beat': 0.0, 'end_beat': 4.0}, ...]
            - tempo: float, BPM
    """
    if not isinstance(wav_path, Path):
        wav_path = Path(wav_path)

    if not wav_path.exists():
        print(f"❌ File not found: {wav_path}")
        return [], 120.0

    print(f"🎸 Chord Extraction Start: {wav_path.name}")

    try:
        return _extract_with_madmom(wav_path)
    except Exception as e:
        print(f"⚠️  madmom 실패 ({e}), librosa fallback 사용")
        return _extract_with_librosa(wav_path)


def _extract_with_madmom(wav_path: Path) -> tuple:
    """madmom CNN 코드 인식 + librosa BPM/beat 추적 후 마디 단위로 스냅."""
    import madmom
    from madmom.features.chords import CNNChordFeatureProcessor, CRFChordRecognitionProcessor
    from madmom.processors import SequentialProcessor

    # 1. madmom 코드 인식 (초 단위 타임스탬프 + 코드명)
    proc = SequentialProcessor([
        CNNChordFeatureProcessor(),
        CRFChordRecognitionProcessor(),
    ])
    raw = proc(str(wav_path))  # [(start, end, chord_label), ...]

    # 2. BPM + beat 추적 (librosa)
    y, sr = librosa.load(str(wav_path), sr=None, mono=True)
    tempo_arr, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    tempo = float(np.atleast_1d(tempo_arr)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    if len(beat_times) == 0:
        return _raw_madmom_to_chords(raw, len(y) / sr), tempo

    # 3. 마디 경계 계산 (4비트 단위)
    BEATS_PER_MEASURE = 4
    measure_times = beat_times[::BEATS_PER_MEASURE]
    duration = len(y) / sr
    measure_boundaries = np.append(measure_times, duration)

    # 4. 각 마디에서 가장 많이 등장한 코드 선택
    result_chords = []
    for i in range(len(measure_boundaries) - 1):
        m_start = measure_boundaries[i]
        m_end = measure_boundaries[i + 1]

        # 이 마디와 겹치는 madmom 코드 세그먼트 수집
        scores: dict[str, float] = {}
        for seg in raw:
            seg_start, seg_end, label = float(seg[0]), float(seg[1]), str(seg[2])
            label = _normalize_chord_label(label)
            if label is None:
                continue
            overlap = min(seg_end, m_end) - max(seg_start, m_start)
            if overlap > 0:
                scores[label] = scores.get(label, 0.0) + overlap

        if not scores:
            continue

        best_label = max(scores, key=lambda k: scores[k])
        chord_info = {
            "chord": best_label,
            "start": round(float(m_start), 2),
            "end": round(float(m_end), 2),
            "start_beat": float(i * BEATS_PER_MEASURE),
            "end_beat": float((i + 1) * BEATS_PER_MEASURE),
        }

        # 연속 동일 코드 병합
        if result_chords and result_chords[-1]["chord"] == chord_info["chord"]:
            result_chords[-1]["end"] = chord_info["end"]
            result_chords[-1]["end_beat"] = chord_info["end_beat"]
        else:
            result_chords.append(chord_info)

    return result_chords, tempo


def _normalize_chord_label(label: str):
    """
    madmom 코드 레이블을 우리 시스템 표기로 변환.
    예) 'D:min' → 'Dm', 'A#:maj' → 'A#', 'N' → None
    """
    if label in ("N", "X", ""):
        return None

    # madmom 형식: "근음:quality" 또는 "근음"
    if ":" in label:
        root, quality = label.split(":", 1)
    else:
        root, quality = label, "maj"

    # 근음 표기 통일 (Db→C#, Eb→D# 등)
    enharmonic = {
        "Db": "C#", "Eb": "D#", "Fb": "E", "Gb": "F#",
        "Ab": "G#", "Bb": "A#", "Cb": "B",
    }
    root = enharmonic.get(root, root)

    if quality in ("maj", "maj7", "7", "maj6", "6", "sus2", "sus4", "aug", ""):
        return root
    elif quality in ("min", "min7", "m7", "dim", "dim7", "hdim7", "min6"):
        return root + "m"
    else:
        return root  # 기타 화음은 메이저로 처리


def _raw_madmom_to_chords(raw, duration: float) -> list:
    """beat 정보 없을 때 madmom 원본 세그먼트를 그대로 변환."""
    result = []
    for seg in raw:
        label = _normalize_chord_label(str(seg[2]))
        if label is None:
            continue
        chord_info = {
            "chord": label,
            "start": round(float(seg[0]), 2),
            "end": round(float(seg[1]), 2),
            "start_beat": 0.0,
            "end_beat": 0.0,
        }
        if result and result[-1]["chord"] == chord_info["chord"]:
            result[-1]["end"] = chord_info["end"]
        else:
            result.append(chord_info)
    return result


def _extract_with_librosa(wav_path: Path) -> tuple:
    """madmom 실패 시 librosa 기반 fallback (마디 단위)."""
    import soundfile as sf

    y, sr = sf.read(str(wav_path))
    if len(y.shape) > 1:
        y = np.mean(y, axis=1)

    y_harmonic = librosa.effects.harmonic(y)
    tempo_arr, beat_frames = librosa.beat.beat_track(y=y_harmonic, sr=sr)
    tempo = float(np.atleast_1d(tempo_arr)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    chroma = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr)

    BEATS_PER_MEASURE = 4
    if len(beat_frames) == 0:
        return [], tempo

    measure_frames = beat_frames[::BEATS_PER_MEASURE]
    measure_times = librosa.frames_to_time(measure_frames, sr=sr)
    chroma_synced = librosa.util.sync(chroma, measure_frames)

    chord_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    major_tmpl = np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0])
    minor_tmpl = np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0])
    templates = np.array(
        [np.roll(major_tmpl, i) for i in range(12)] +
        [np.roll(minor_tmpl, i) for i in range(12)]
    )
    labels = chord_names + [n + "m" for n in chord_names]

    duration = len(y) / sr
    time_points = np.append(measure_times, duration)
    result_chords = []

    for i in range(min(chroma_synced.shape[1], len(time_points) - 1)):
        best_idx = int(np.argmax(np.dot(templates, chroma_synced[:, i])))
        chord_info = {
            "chord": labels[best_idx],
            "start": round(float(time_points[i]), 2),
            "end": round(float(time_points[i + 1]), 2),
            "start_beat": float(i * BEATS_PER_MEASURE),
            "end_beat": float((i + 1) * BEATS_PER_MEASURE),
        }
        if result_chords and result_chords[-1]["chord"] == chord_info["chord"]:
            result_chords[-1]["end"] = chord_info["end"]
            result_chords[-1]["end_beat"] = chord_info["end_beat"]
        else:
            result_chords.append(chord_info)

    return result_chords, tempo
