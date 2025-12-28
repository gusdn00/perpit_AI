import librosa
import numpy as np
import os

def extract_chords_from_signal(y, sr):
    print(f"--- Step 4: Chord Extraction Start (Direct Signal) ---")

    y_harmonic = librosa.effects.harmonic(y)

    tempo, beat_frames = librosa.beat.beat_track(y=y_harmonic, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    
    chroma = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr)
    chroma_synced = librosa.util.sync(chroma, beat_frames)
    
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
        
        if result_chords and result_chords[-1]['chord'] == chord_info['chord']:
            result_chords[-1]['end'] = chord_info['end']
        else:
            result_chords.append(chord_info)
            
    return result_chords
