from pathlib import Path
from basic_pitch.inference import predict_and_save
from basic_pitch import ICASSP_2022_MODEL_PATH


def extract_basic_pitch(
    wav_path: Path,
    out_dir: Path,
) -> Path:
    """
    Run Basic Pitch (old API, confirmed by inspect).
    Output: polyphonic MIDI (raw notes)
    """

    if not wav_path.exists():
        raise FileNotFoundError(f"WAV not found: {wav_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    predict_and_save(
        [str(wav_path)],          # audio_path_list
        str(out_dir),             # output_directory
        True,                     # save_midi
        False,                    # sonify_midi
        False,                    # save_model_outputs
        False,                    # save_notes
        ICASSP_2022_MODEL_PATH,   # model_or_model_path
    )

    midi_path = out_dir / f"{wav_path.stem}_basic_pitch.mid"

    if not midi_path.exists():
        raise RuntimeError("Basic Pitch MIDI was not created.")

    return midi_path
