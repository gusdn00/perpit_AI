from pathlib import Path
from src.pipeline.run import run_pipeline

if __name__ == "__main__":
    config = {
        "file": "/home/jisu/MusicSheet/dataset/butterfly.mp3",       # 여기 실제 wav/mp3 경로로 바꾸기
        "title": "Test",
        "purpose": "1",
        "style": "3",
        "difficulty": "1",
    }

    xml_path = run_pipeline(config, out_dir=Path("outputs"))
    print(" Generated MusicXML:", xml_path)
