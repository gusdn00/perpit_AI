from pathlib import Path

from src.pipeline.context import PipelineContext
from src.pipeline.validate import validate_config
from src.io.xml_writer import write_dummy_musicxml
from src.audio.preprocess import preprocess_audio
from src.pitch.basic_pitch_extractor import extract_basic_pitch
from src.chord.chords_extract import extract_chords

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

    # Step 1: Audio Preprocessing
    print("Step 1: Audio Preprocessing...")
    audio_dir = out_dir / "audio"
    ctx.standard_wav = preprocess_audio(ctx.file, audio_dir)

    # Step 2: Pitch Extraction (Basic Pitch)
    print("Step 2: Pitch Extraction...")
    pitch_dir = out_dir / "pitch"
    ctx.pitch_midi = extract_basic_pitch(
        ctx.standard_wav,
        pitch_dir,
    )

    # Step 3: Chord Extraction
    print(f"Step 3: Chord Extraction...")
    try:
        ctx.chords = extract_chords(ctx.standard_wav)
        
        if ctx.chords:
            print(f"   Success! Extracted {len(ctx.chords)} chords.")
            print(f"   Preview: {ctx.chords[:3]}...")
        else:
            print("   Warning: No chords extracted.")
            
    except Exception as e:
        print(f"   Error during chord extraction: {e}")
        ctx.chords = []

    print("Step 4: Generating XML...")
    out_path = out_dir / "score.xml"
    ctx.output_xml = write_dummy_musicxml(
        title=ctx.title,
        out_path=out_path,
        midi_path=ctx.pitch_midi,
        chords=ctx.chords
    )



    return ctx.output_xml

