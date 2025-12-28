from pathlib import Path

from src.pipeline.context import PipelineContext
from src.pipeline.validate import validate_config
from src.io.xml_writer import write_dummy_musicxml
from src.audio.preprocess import preprocess_audio
from src.pitch.basic_pitch_extractor import extract_basic_pitch

def build_context(config: dict) -> PipelineContext:
    validate_config(config)

    file_path = Path(config["file"])
    purpose = config["purpose"]

    return PipelineContext(
        file=file_path,
        title=config["title"],
        purpose=purpose,
        style=config["style"],
        difficulty=config["difficulty"],
        has_lyrics=(purpose == "2"),
    )


def run_pipeline(config: dict, out_dir: Path = Path("outputs")) -> Path:
    ctx = build_context(config)

    # 1. audio preprocess (mp3/wav → standard wav)
    audio_dir = out_dir / "audio"
    ctx.standard_wav = preprocess_audio(ctx.file, audio_dir)

    # 2. pitch extraction (Basic Pitch)
    pitch_dir = out_dir / "pitch"
    ctx.pitch_midi = extract_basic_pitch(
    ctx.standard_wav,
    pitch_dir,
)

    # 3. (아직은 pitch 없이) dummy XML
    out_path = out_dir / "score.xml"
    ctx.output_xml = write_dummy_musicxml(ctx.title, out_path)


    return ctx.output_xml

