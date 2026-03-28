# PerPit AI - Handover 문서

> 새로운 환경(GPU 서버 등)에서 이 프로젝트를 이어받을 때 읽는 문서.
> 구현 현황, 코드 구조, 설치 방법, 미완료 작업을 모두 정리함.

---

## 1. 프로젝트 개요

**무엇을 하는 서비스인가:**
사용자가 음악 파일(mp3/wav)을 업로드하면 AI가 분석해서 악보(MusicXML)를 생성해주는 서비스.

**입력 파라미터:**

| 파라미터 | 값 | 설명 |
|---|---|---|
| `file` | mp3/wav | 오디오 파일 |
| `title` | str | 악보 제목 |
| `instrument` | 1 or 2 | 1=피아노, 2=기타 |
| `purpose` | 1 or 2 | 1=반주용, 2=연주용 |
| `style` | 1, 2, 3 | 1=팝, 2=발라드, 3=오리지널 |
| `difficulty` | 1 or 2 | 1=Easy, 2=Normal |

**출력:** `score.xml` (MusicXML 형식, 악보 프로그램에서 열 수 있음)

---

## 2. 전체 파이프라인

```
[백엔드] POST /create_sheets/ai
    │
    ▼
[server.py] 파일 저장 → 202 즉시 응답 → 백그라운드 작업 시작
    │
    ▼
[run.py] run_pipeline()
    │
    ├─ Step 1: preprocess_audio()
    │   mp3/wav → 표준 WAV (ffmpeg 사용)
    │   출력: outputs/{job_id}/audio/input_standard.wav
    │
    ├─ Step 2: transcribe_audio()   ← YourMT3 (핵심)
    │   WAV → 멀티트랙 MIDI → 멜로디 병합 MIDI
    │   출력: outputs/{job_id}/midi/{이름}.mid (원본)
    │          outputs/{job_id}/midi/{이름}_melody.mid (병합, 파이프라인 사용)
    │
    ├─ Step 3: extract_chords()
    │   WAV → 코드 진행 + BPM (librosa 사용)
    │   출력: [{"chord": "C", "start": 0.0, "end": 2.5}, ...], 120.0
    │
    ├─ Step 4: arrange()
    │   멜로디 MIDI + 코드 + BPM + 옵션 → music21 Score
    │
    └─ Step 5: score.write("musicxml")
        출력: outputs/{job_id}/score.xml
    │
    ▼
[callback.py] 백엔드로 score.xml 전송
    POST http://127.0.0.1:8000/create_sheets/callback/ai-result
```

---

## 3. 파일 구조

```
perpit_AI/
├── src/
│   ├── api/
│   │   └── server.py              # FastAPI 진입점. POST /create_sheets/ai
│   ├── audio/
│   │   └── preprocess.py          # ffmpeg로 표준 WAV 변환
│   ├── transcription/
│   │   └── yourmt3_extractor.py   # YourMT3 모델 로드/추론/트랙 병합 (핵심)
│   ├── chord/
│   │   └── chords_extract.py      # librosa로 코드 진행 + BPM 추출
│   ├── arrange/
│   │   └── arranger.py            # music21로 악보(Score) 생성 (핵심)
│   ├── pipeline/
│   │   ├── run.py                 # 파이프라인 전체 흐름 연결
│   │   ├── context.py             # 파이프라인 중간 결과 저장 dataclass
│   │   └── validate.py            # 입력 파라미터 검증
│   ├── utils/
│   │   └── callback.py            # 완료/실패 결과를 백엔드로 전송
│   ├── separation/
│   │   └── demucs_separator.py    # (미사용) demucs 음원 분리 - YourMT3로 대체됨
│   └── io/
│       └── xml_writer.py          # (미사용) 구 방식 XML 저장 - run.py에서 직접 처리
├── uploads/                       # 업로드된 오디오 임시 저장
├── outputs/                       # 결과물 저장 ({job_id}/ 단위)
├── progress.md                    # 개발 진행 기록 (gitignore)
└── handover.md                    # 이 파일
```

---

## 4. 핵심 모듈 상세

### 4-1. yourmt3_extractor.py

YourMT3 외부 라이브러리(`~/YourMT3`)를 감싸서 우리 파이프라인에 연결.

**기본 모델:** `YPTF+Multi (PS)` — 악기별 분리 멀티트랙 출력

**멜로디 병합 전략 (`_merge_melody_tracks`):**
- `Singing Voice` 트랙이 있는 구간 → 보컬 노트 사용
- 보컬 없는 구간(인트로/간주) → 우선순위 높은 악기 트랙으로 채움
  - 우선순위: `Synth Lead > Piano > Guitar > Reed > Pipe > Brass > Strings > Organ > Synth Pad`
  - `Bass`, `Drums` 는 완전 제외
- 보컬 자체가 없으면(순수 연주곡) → 우선순위 1위 트랙 단독 사용
- 같은 시간대 겹침 판정: 50ms 버킷 단위

**주요 함수:**
```python
load_model(yourmt3_dir, model_name, device) → model
transcribe_audio(wav_path, out_dir, instrument, model=None) → {"all": Path, "selected": Path}
```

**환경 변수:**
- `YOURMT3_DIR`: YourMT3 클론 경로 (기본 `~/YourMT3`)
- `YOURMT3_MODEL`: 모델 선택 (기본 `YPTF+Multi (PS)`)

---

### 4-2. arranger.py

코드 진행 + 멜로디 MIDI → music21 Score 변환.

**케이스별 악보 구성:**

| instrument | purpose | 오른손 | 왼손 |
|---|---|---|---|
| 피아노(1) | 연주용(2) | 멜로디 (YourMT3 MIDI) | 코드 반주 |
| 피아노(1) | 반주용(1) | 코드 보이싱 | 베이스라인 |
| 기타(2) | 무관 | 코드 스트로크 패턴 | 없음 (단일 보표) |

**스타일별 반주:**
- 팝(1): 파워코드, velocity=110, 2박 단위
- 발라드(2): 아르페지오, velocity=60, 0.5박 단위
- 오리지널(3): 블록코드, velocity=80, 1박 단위

**난이도별:**
- Easy(1): 8분음표 양자화, 근음+3음 (5음 제거)
- Normal(2): 16분음표 양자화, 근음+3음+5음

---

### 4-3. callback.py

파이프라인 완료 후 백엔드에 결과 전송.

```
성공: POST /create_sheets/callback/ai-result
      body: status="completed", job_id=...
      file: score.xml

실패: POST /create_sheets/callback/ai-result
      body: status="failed", job_id=...
```

> ⚠️ `BACKEND_CALLBACK_URL`이 `http://127.0.0.1:8000/...` 로 하드코딩돼 있음.
> 백엔드 서버 주소가 다르면 수정 필요.

---

## 5. GPU 서버 최초 설치

### 5-1. 프로젝트 클론

```bash
git clone https://github.com/gusdn00/perpit_AI.git
cd perpit_AI
```

### 5-2. Python 패키지 설치

```bash
# GPU 서버는 CUDA 버전 torch 사용 (CPU 버전 쓰면 안 됨)
pip install torch torchaudio  # CUDA 자동 감지

pip install fastapi uvicorn python-multipart
pip install soundfile librosa music21 pretty_midi
pip install requests mido
pip install huggingface_hub
```

### 5-3. ffmpeg 설치

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# 설치 확인
ffmpeg -version
```

### 5-4. YourMT3 설치

```bash
# 소스 클론
git clone https://huggingface.co/spaces/mimbres/YourMT3 ~/YourMT3

# 의존성 설치 (torch/torchaudio 제외)
pip install lightning>=2.2.1 transformers==4.45.1 numpy==1.26.4 \
  python-dotenv yt-dlp mido deprecated wandb gradio_log
```

### 5-5. 체크포인트 다운로드

```python
from huggingface_hub import hf_hub_download

# Multi 모델 (기본값, 권장)
hf_hub_download(
    repo_id='mimbres/YourMT3',
    repo_type='space',
    filename='amt/logs/2024/ptf_mc13_256_all_cross_v6_xk5_amp0811_edr005_attend_c_full_plus_2psn_nl26_sb_b26r_800k/checkpoints/model.ckpt',
    local_dir='/home/{user}/YourMT3',
)
```

다운로드 후 확인:
```
~/YourMT3/amt/logs/2024/ptf_mc13_256_.../checkpoints/model.ckpt  ✅
```

### 5-6. 서버 실행

```bash
cd perpit_AI
uvicorn src.api.server:app --host 0.0.0.0 --port 8080
```

---

## 6. 테스트 방법

### 파이프라인 단독 테스트 (빠른 확인용)

```python
# YourMT3 없이 코드추출 + 편곡 + XML만 테스트
from pathlib import Path
from src.chord.chords_extract import extract_chords
from src.arrange.arranger import arrange

chords, bpm = extract_chords(Path("샘플.wav"))
score = arrange(
    melody_midi_path=None,
    chords=chords,
    bpm=bpm,
    instrument="1",   # 피아노
    purpose="1",      # 반주용
    style="1",        # 팝
    difficulty="2",   # Normal
    title="테스트",
)
score.write("musicxml", "test_output.xml")
```

### 전체 파이프라인 테스트

```python
from pathlib import Path
from src.pipeline.run import run_pipeline

result = run_pipeline(
    args={
        "file": "샘플.mp3",
        "title": "테스트",
        "instrument": "1",
        "purpose": "2",
        "style": "2",
        "difficulty": "2",
    },
    out_dir=Path("outputs/test_job"),
)
print(result)  # score.xml 경로
```

### API 테스트

```bash
curl -X POST http://localhost:8080/create_sheets/ai \
  -F "job_id=test001" \
  -F "title=테스트곡" \
  -F "instrument=1" \
  -F "purpose=2" \
  -F "style=2" \
  -F "difficulty=2" \
  -F "file=@샘플.mp3"
```

---

## 7. 현재 상태 및 미완료 작업

### 완료된 것

| 항목 | 상태 |
|------|------|
| FastAPI 서버 (수신 + 백그라운드 처리 + 콜백) | ✅ |
| 오디오 전처리 (ffmpeg) | ✅ |
| YourMT3 연동 (모델 로드 + 추론) | ✅ |
| 멜로디 트랙 병합 (보컬 우선 + 인트로 채움) | ✅ |
| 코드 추출 + BPM (librosa) | ✅ |
| 편곡 로직 (피아노 연주용/반주용, 기타) | ✅ |
| MusicXML 저장 | ✅ |
| 백엔드 콜백 | ✅ |

### 확인이 필요한 것 (GPU 서버에서 처음 테스트)

| 항목 | 내용 |
|------|------|
| YourMT3 추론 결과 | CPU에서 메모리 부족으로 못 돌려봄. GPU에서 처음 확인 |
| 멜로디 트랙 병합 품질 | 보컬/악기 구간 분리가 잘 되는지 |
| 악보 출력 품질 | 음이 너무 빽빽하거나 이상한 위치에 배치되지 않는지 |
| 콜백 URL | `http://127.0.0.1:8000/...` 가 실제 백엔드 주소와 맞는지 확인 필요 |

---

## 8. 알려진 주의사항

1. **YourMT3 체크포인트 경로가 cwd 기준 상대경로**
   → `yourmt3_extractor.py`에서 `os.chdir(yourmt3_dir)` 로 처리함. 건드리지 말 것.

2. **`YOURMT3_DIR` 환경변수 기본값이 `~/YourMT3`**
   → 체크포인트를 다른 경로에 설치했으면 환경변수 설정 필요:
   ```bash
   export YOURMT3_DIR=/path/to/YourMT3
   ```

3. **GPU 사용 시 precision 자동 전환**
   → `device="cuda"` 로 넘기면 precision `"16"` (bf16) 자동 사용.
   → `device="cpu"` 면 `"32"` 강제. (bf16 미지원)

4. **콜백 URL 하드코딩**
   → `src/utils/callback.py` 4번째 줄 `BACKEND_CALLBACK_URL` 수정 필요할 수 있음.
