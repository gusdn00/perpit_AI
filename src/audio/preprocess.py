from pathlib import Path
import subprocess


class AudioPreprocessError(RuntimeError):
    pass


def _run_ffmpeg(cmd: list[str]) -> None:
    """
    Run ffmpeg command and raise readable error on failure.
    """
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise AudioPreprocessError(
            f"ffmpeg failed:\n{e.stderr}"
        ) from e


def preprocess_audio(
    input_path: Path,
    out_dir: Path,
    sample_rate: int = 44100,
    channels: int = 2,
) -> Path:
    """
    Convert mp3/wav input into standardized wav.

    Output format:
    - wav
    - PCM 16-bit
    - sample_rate Hz
    - stereo
    """

    if not input_path.exists():
        raise AudioPreprocessError(f"Input audio not found: {input_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    output_wav = out_dir / "input_standard.wav"

    cmd = [
        "ffmpeg",
        "-y",                       # overwrite
        "-i", str(input_path),
        "-acodec", "pcm_s16le",     # 16-bit PCM
        "-ar", str(sample_rate),    # sample rate
        "-ac", str(channels),       # channels
        str(output_wav),
    ]

    _run_ffmpeg(cmd)

    if not output_wav.exists() or output_wav.stat().st_size == 0:
        raise AudioPreprocessError("Standard wav was not created.")

    return output_wav
