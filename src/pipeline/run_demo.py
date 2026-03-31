"""
run_demo.py - 시연용 파이프라인

실제 AI 처리 없이 미리 준비된 악보를 반환한다.
- 기타(instrument=2): 외톨이야.xml
- 피아노 연주용 Normal(instrument=1, purpose=2, difficulty=2): Blueming_normal.xml
- 피아노 연주용 Easy(instrument=1, purpose=2, difficulty=1): Blueming_easy.xml
"""

from pathlib import Path
import shutil

_DEMO_DIR = Path(__file__).parent.parent.parent / "outputs" / "demo"

_DEMO_MAP = {
    "guitar":        _DEMO_DIR / "외톨이야.xml",
    "piano_normal":  _DEMO_DIR / "Blueming_normal.xml",
    "piano_easy":    _DEMO_DIR / "Blueming_easy.xml",
}


def run_pipeline(args: dict, out_dir: Path) -> str:
    instrument = str(args.get("instrument", "1"))
    difficulty = str(args.get("difficulty", "2"))

    if instrument == "2":
        src = _DEMO_MAP["guitar"]
    elif difficulty == "1":
        src = _DEMO_MAP["piano_easy"]
    else:
        src = _DEMO_MAP["piano_normal"]

    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "score.xml"
    shutil.copy2(src, dst)

    print(f"[Demo] {src.name} → {dst}")
    return str(dst)
