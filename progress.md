# PerPit AI - 개발 진행 기록

> 핸드오버 문서 기반으로 실제 파이프라인 구현 작업 기록

---

## 전체 작업 계획

| Part | 내용 | 상태 |
|------|------|------|
| Part 1 | 기반 수정 (context / validate / chords / server) | ✅ 완료 |
| Part 2 | demucs_separator.py 신규 생성 | 🔲 대기 |
| Part 3 | arranger.py 신규 생성 (핵심 편곡 로직) | 🔲 대기 |
| Part 4 | xml_writer.py 재작성 | 🔲 대기 |
| Part 5 | pipeline/run.py 교체 (전체 파이프라인 연결) | 🔲 대기 |

---

## Part 1 - 기반 수정

**목표:** 나머지 파트 구현 전에 데이터 구조, 검증 로직, API 파라미터를 맞춰두기

### 작업 항목

#### ① src/pipeline/context.py
- **문제:** `instrument`, `chords`, `tempo` 필드가 없음
- **영향:** `run1.py`에서 `ctx.chords = ...` 대입 시 에러 발생
- **변경 내용:**
  ```
  # 추가된 필드
  instrument: str        # "1"=피아노, "2"=기타 (input config)
  chords: list | None    # 코드 추출 결과 (intermediate output)
  tempo: float | None    # BPM (intermediate output)
  separated_tracks: dict | None  # demucs 분리 결과 (intermediate output)
  ```
- **상태:** ✅ 완료

#### ② src/pipeline/validate.py
- **문제:** `instrument` 필드가 required set에 없고 값 검증도 없음
- **변경 내용:**
  ```
  required에 "instrument" 추가
  instrument 값이 "1" 또는 "2"인지 검증 → 아니면 ConfigError 발생
  ```
- **상태:** ✅ 완료

#### ③ src/chord/chords_extract.py
- **문제:** `_analyze_signal()` 내부에서 `tempo`(BPM)를 계산하지만 반환하지 않고 버림
- **변경 내용:**
  ```
  반환 타입: list → tuple[list, float]
  extract_chords()도 (chords, tempo) 튜플로 반환
  파일 없거나 beat 없을 때 fallback: ([], 120.0)
  ```
- **참고:** beat→초 변환 공식 `beat = seconds * (bpm / 60.0)` 은 arranger에서 사용
- **상태:** ✅ 완료

#### ④ src/api/server.py
- **문제:** `instrument` 파라미터가 Form에 없고 백그라운드 작업에도 전달 안 됨
- **변경 내용:**
  ```
  receive_from_backend()에 instrument: int = Form(...) 추가
  process_sheet_generation() 시그니처에 instrument 추가
  run_pipeline() 호출 딕셔너리에 "instrument": str(instrument) 추가
  background_tasks.add_task() 호출에 instrument 인자 추가
  ```
- **상태:** ✅ 완료

### 완료 기준
- [x] context.py에 4개 필드 추가 확인
- [x] validate.py에서 instrument 누락/잘못된 값 시 ConfigError 발생 확인
- [x] chords_extract.py가 `(list, float)` 튜플 반환 확인
- [x] server.py POST /create_sheets/ai 에 instrument 파라미터 포함 확인

### Git
- 브랜치: main
- 커밋: `[feat] Part 1 - 기반 수정 (instrument 파라미터, BPM 반환, 컨텍스트 필드 추가)` ✅ push 완료

---

## Part 2 - demucs_separator.py 신규 생성

**목표:** HT-Demucs로 오디오를 악기별 트랙으로 분리

### 작업 항목

#### src/separation/demucs_separator.py (신규)
- **역할:** `htdemucs_6s` 모델로 vocals/piano/guitar/drums/bass/other 분리
- **입력:** `input_standard.wav` (전처리된 오디오)
- **출력:** `{out_dir}/vocals.wav`, `piano.wav`, `guitar.wav` 등 dict 반환
- **파이프라인에서의 역할:**
  ```
  피아노 + 연주용 → vocals.wav를 Basic Pitch에 입력 (멜로디 추출)
  피아노 + 반주용 → piano.wav를 Basic Pitch에 입력 (반주 추출)
  기타            → 피치 추출 불필요 (코드만 사용하므로 스킵)
  ```
- **상태:** 🔲

### Git
- 커밋 메시지 예정: `[feat] Part 2 - demucs 음원 분리 모듈 추가`

---

## Part 3 - arranger.py 신규 생성

**목표:** melody MIDI + chords + BPM + 옵션 → music21 Score 생성

### 작업 항목

#### src/arrange/arranger.py (신규)
- **입력:** `melody_midi_path`, `chords`, `bpm`, `instrument`, `purpose`, `style`, `difficulty`, `title`
- **출력:** `music21.stream.Score`

- **케이스별 로직:**

  | instrument | purpose | 오른손(높은음자리표) | 왼손(낮은음자리표) |
  |---|---|---|---|
  | 피아노(1) | 연주용(2) | 멜로디 (MIDI → music21) | 코드 반주 패턴 |
  | 피아노(1) | 반주용(1) | 코드 보이싱 (3음+5음+장7화음 등) | 베이스라인 (근음 위주) |
  | 기타(2) | 무관 | 코드 반주 패턴 (단보) | 없음 |

- **스타일별 반주 패턴:**
  ```
  발라드: 아르페지오 [근음→5음→3음→5음], 1박 단위, velocity=60
  팝:    덩기 화음 [근음+5음], 2박 단위, velocity=110
  오리지널: 블록코드 (동시에 치기), velocity=80
  ```

- **난이도별 처리:**
  ```
  Easy:   8분음표 단위 양자화, 화음 = 근음+3음만 (7음·9음 제거)
  Normal: 16분음표 단위 양자화, 원래 화음 그대로 유지
  ```

- **핵심 시간 변환:**
  ```python
  beat_position = time_in_seconds * (bpm / 60.0)
  ```

- **상태:** 🔲

### Git
- 커밋 메시지 예정: `[feat] Part 3 - 편곡 로직(arranger) 구현`

---

## Part 4 - xml_writer.py 재작성

**목표:** arranger가 만든 Score 객체를 MusicXML 파일로 저장

### 작업 항목

#### src/io/xml_writer.py (재작성)
- **현재 상태:** MIDI를 music21으로 단순 파싱해서 저장하는 수준, 코드 정보 미사용
- **변경 내용:**
  - 입력을 `midi_path` → `score: stream.Score`로 교체
  - 제목, 박자표(4/4), 빠르기(BPM) 메타데이터 삽입
  - 음자리표 설정 (오른손=Treble, 왼손=Bass)
  - `score.write('musicxml', fp=out_path)` 로 저장
- **상태:** 🔲

### Git
- 커밋 메시지 예정: `[feat] Part 4 - xml_writer 재작성 (Score → MusicXML)`

---

## Part 5 - pipeline/run.py 교체

**목표:** 파일 복사 임시 코드를 실제 전체 파이프라인으로 교체

### 작업 항목

#### src/pipeline/run.py (교체)
- **현재 상태:** purpose에 따라 미리 만들어둔 XML을 복사하는 임시 코드
- **변경 내용:** run1.py 기반으로 demucs + arranger 연결한 완전한 파이프라인으로 교체
  ```
  Step 1: preprocess_audio()
  Step 2: separate_sources()          ← demucs
  Step 3: extract_basic_pitch()       ← instrument/purpose에 따라 입력 트랙 결정
  Step 4: clean_midi_notes()
  Step 5: extract_chords() → (chords, tempo)
  Step 6: arrange()                   ← arranger
  Step 7: write_musicxml()            ← xml_writer
  Step 8: callback (server.py에서 처리)
  ```
- **상태:** 🔲

### Git
- 커밋 메시지 예정: `[feat] Part 5 - 전체 파이프라인 연결 완료`

---

## 변경 이력

| 날짜 | Part | 내용 |
|------|------|------|
| 2026-03-28 | Part 1 | context.py instrument/chords/tempo/separated_tracks 필드 추가 |
| 2026-03-28 | Part 1 | validate.py instrument 검증 추가 |
| 2026-03-28 | Part 1 | chords_extract.py (chords, tempo) 튜플 반환으로 변경 |
| 2026-03-28 | Part 1 | server.py instrument Form 파라미터 추가 및 파이프라인 전달 |
