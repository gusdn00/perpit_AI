from pathlib import Path
from music21 import stream, note, metadata, converter, harmony

def write_dummy_musicxml(
    title: str, 
    out_path: Path, 
    midi_path: Path = None,  # [추가] 분석된 MIDI 파일 경로
    chords: list = None      # [추가] 분석된 코드 정보
) -> Path:
    """
    MusicXML 파일을 생성합니다.
    - midi_path가 있으면: 해당 MIDI 파일을 불러와서 악보로 변환합니다.
    - midi_path가 없으면: 기본 '도-미-솔' 악보를 만듭니다.
    """
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 1. MIDI 파일이 존재하는지 확인하고 불러오기
    if midi_path and midi_path.exists():
        print(f"   📝 Loading MIDI from: {midi_path.name}")
        try:
            # music21을 이용해 MIDI 파일을 파싱(변환)합니다.
            score = converter.parse(str(midi_path))
        except Exception as e:
            print(f"   ⚠️ Failed to load MIDI: {e}. Falling back to dummy.")
            score = stream.Score()
            part = stream.Part()
            part.append(note.Note("C4")) # 실패 시 안전장치
            score.append(part)
    else:
        # 2. MIDI가 없으면 기존처럼 '도-미-솔' (Dummy) 생성
        print("   📝 No MIDI found. Creating dummy score.")
        score = stream.Score()
        part = stream.Part()
        part.append(note.Note("C4", quarterLength=1))
        part.append(note.Note("E4", quarterLength=1))
        part.append(note.Note("G4", quarterLength=2))
        score.append(part)

    # 3. 메타데이터(제목) 설정
    if not score.metadata:
        score.insert(0, metadata.Metadata())
    score.metadata.title = title

    # 4. (옵션) 코드 정보가 있다면 콘솔에 출력 (나중에 악보에 삽입 가능)
    if chords:
        print(f"   ℹ️ {len(chords)} chords provided (Integration pending...)")
        # TODO: 여기에 코드 심볼을 악보 타임라인에 맞춰 넣는 로직이 들어가야 함
        # 현재는 오디오 시간(초)과 악보 박자(Beat)를 맞추는 작업이 필요해서 생략

    # 5. 최종 XML 저장
    score.write("musicxml", str(out_path))
    
    return out_path