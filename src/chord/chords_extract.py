from pathlib import Path
import soundfile as sf
import numpy as np
import librosa

def extract_chords(wav_path: Path) -> list:
    """
    Extract chords from a given audio file path.
    Args:
        wav_path (Path): Path to the audio file.
    Returns:
        list: A list of dictionaries containing chord information.
              e.g., [{'chord': 'C', 'start': 0.0, 'end': 1.0}, ...]
    """
    
    # 1. Validate Path
    if not isinstance(wav_path, Path):
        wav_path = Path(wav_path)

    if not wav_path.exists():
        print(f"❌ File not found: {wav_path}")
        return []

    print(f"🎸 Chord Extraction Start: {wav_path.name}")

    # 2. Load Audio
    try:
        y, sr = sf.read(str(wav_path))
    except Exception as e:
        print(f"❌ Error loading audio: {e}")
        return []

    # 3. Convert to Mono (if stereo)
    if len(y.shape) > 1:
        y = np.mean(y, axis=1)

    # 4. Analyze
    return _analyze_signal(y, sr)


def _analyze_signal(y, sr):
    """
    Internal logic to analyze audio signal and extract chords.
    """
    # Harmonic Separation
    y_harmonic = librosa.effects.harmonic(y)

    # Beat Tracking
    tempo, beat_frames = librosa.beat.beat_track(y=y_harmonic, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    
    # Chroma Feature Extraction
    chroma = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr)
    
    if len(beat_frames) == 0:
        return []
        
    chroma_synced = librosa.util.sync(chroma, beat_frames)
    
    # Templates Definition
    chord_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    major_tmpl = np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0])
    minor_tmpl = np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0])
    
    templates = []
    labels = []
    for i in range(12):
        templates.append(np.roll(major_tmpl, i))
        labels.append(chord_names[i])
    for i in range(12):
        templates.append(np.roll(minor_tmpl, i))
        labels.append(chord_names[i] + "m")
    templates = np.array(templates)

    # Matching
    result_chords = []
    duration = len(y) / sr
    time_points = np.append(beat_times, duration)
    
    for i in range(chroma_synced.shape[1]):
        correlations = np.dot(templates, chroma_synced[:, i])
        best_idx = np.argmax(correlations)
        
        chord_info = {
            "chord": labels[best_idx],
            "start": round(time_points[i], 2),
            "end": round(time_points[i+1], 2)
        }
        
        # Merge consecutive identical chords
        if result_chords and result_chords[-1]['chord'] == chord_info['chord']:
            result_chords[-1]['end'] = chord_info['end']
        else:
            result_chords.append(chord_info)
            
    return result_chords
