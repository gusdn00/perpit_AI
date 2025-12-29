from pathlib import Path
from src.pipeline.run import run_pipeline

if __name__ == "__main__":
    # Configuration
    config = {
        "file": "src/audio/butterfly.mp3",  # Change this to your actual file path
        "title": "Test Project",
        "purpose": "1",
        "style": "3",
        "difficulty": "1",
    }

    # Execute Pipeline
    try:
        xml_path = run_pipeline(config, out_dir=Path("outputs"))
        print(f"\nPipeline Completed Successfully.")
        print(f"Generated MusicXML: {xml_path}")
    except Exception as e:
        print(f"\nPipeline Failed: {e}")