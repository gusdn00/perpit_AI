import pretty_midi
import numpy as np
from pathlib import Path

def clean_midi_notes(input_path: Path, output_path: Path, min_duration=0.08, pitch_z_score=2.5):
    try:

        midi_data = pretty_midi.PrettyMIDI(str(input_path))
        
        cleaned_notes = []
        
        for instrument in midi_data.instruments:
            all_pitches = [note.pitch for note in instrument.notes]
            if not all_pitches:
                continue
            
            mean_pitch = np.mean(all_pitches)
            std_pitch = np.std(all_pitches)
            
            cleaned_notes_inst = []
            
            for note in instrument.notes:
                duration = note.end - note.start
                
                # 1. 길이가 너무 짧으면 패스
                if duration < min_duration:
                    continue
                
                # 2. 피치가 너무 튀면 패스
                if std_pitch > 0:
                    z_score = abs(note.pitch - mean_pitch) / std_pitch
                    if z_score > pitch_z_score:
                        continue

                cleaned_notes_inst.append(note)
            
            instrument.notes = cleaned_notes_inst

        midi_data.write(str(output_path))
        print(f"   [Clean] Processed MIDI saved to: {output_path.name}")
        return output_path

    except Exception as e:
        print(f"   [Clean] Error during MIDI cleaning: {e}")
        return input_path 