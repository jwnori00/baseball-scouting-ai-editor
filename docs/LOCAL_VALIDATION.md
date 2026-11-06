# Windows PC에서만 실제 경기 분석

원본 3개 및 추출 프레임·정답·모델은 `private/` 또는 저장소 밖에 보관합니다.
원본을 원격 저장소·CI에 업로드하지 마세요. 원본은 읽기만 하며 출력과 캐시를 다른 위치에 둡니다.
파일 순서는 실제 경기 순서로 지정하세요. 전체 SHA-256 계산에는 큰 파일을 읽는 시간이 필요합니다.

## 1. 도구 확인

README의 개발 환경을 준비하고 `python -m bsae.cli doctor`로 확인합니다.
FFmpeg/FFprobe와 Tesseract는 별도 개발 설치가 필요합니다. 완성 EXE를 제공하는 단계가 아닙니다.
기본 실행은 CPU이며 네트워크 API·GPU가 필요하지 않습니다. GPU 가속은 미구현입니다.

## 2. 야구 모델 학습

검증된 사전학습 야구 모델을 동봉하지 않았습니다. 다음 클래스의 로컬 라벨 영상이 필요합니다:
`other`, `setup`, `delivery`, `receive`, `live`, `dead`, `replay`, `pickoff`.
`dead`는 반환 송구/필요한 후속 수비·주루·판정이 끝난 상태를 뜻하도록 일관되게 라벨링합니다.
광고·관중·인터뷰는 현재 별도 분류가 아니라 `other`로 처리합니다.
홈런/폭투/볼넷 등 세부 결과의 자동 분류·종료 판단은 아직 제공하지 않습니다.

사용권이 있는 여러 경기·투수·타자·조명·중계사 영상에서 다양한 예제를 수집합니다.
학습과 평가는 경기 단위로 분리하여 유사 프레임의 누출을 방지해야 합니다.
예제 JSON의 시간은 학습 정답이며 추론 결과에 복사되지 않습니다.
다음은 **형식 예시**로, 사용자 영상의 실제 정답을 의미하지 않습니다.

```json
[
  {"video": "training-game.mp4", "intervals": [
    {"start": 0.0, "end": 3.0, "label": "other"},
    {"start": 3.0, "end": 5.0, "label": "setup"}
  ]}
]
```

모든 클래스의 학습 예제가 필요합니다. 최소 예제 수 검사는 수학적 입력 요건이며 충분한 성능의 보장이 아닙니다.
현재 학습 방식은 공간 RGB/에지·전후 프레임 차이 특징에 대한 정규화 선형 분류입니다.
긴 동작 문맥을 학습하는 3D CNN/Transformer 또는 ONNX 야구 모델은 미구현입니다.
이 기초 분류기로 실제 방송에서 충분한 성능을 달성하지 못하면 별도의 영상 동작 모델 개발·학습이 필요합니다.

```powershell
.\.venv\Scripts\python.exe -m bsae.cli train private\labels.json private\model --license "실제 사용 가능한 모델 라이선스" --provenance "사용권 확인한 로컬 학습 데이터 설명"
```

산출물: `model.json`, `temporal.npz`. SHA-256·특징 버전·클래스·학습 개수·출처·라이선스가 기록됩니다.
체크섬이 맞지 않으면 로드하지 않습니다. 로컬 학습은 학습 영상의 상업적 사용 권한을 부여하지 않습니다.
입력 예제 수는 최대 100,000개이며 그 이상이면 학습셋을 분할하거나 모델 학습 코드를 확장해야 합니다.

## 3. 중계 OCR 프로필

중계 화면을 로컬에서 보고 영역을 지정해 `private/broadcast.json`을 작성합니다.
각 ROI는 `[왼쪽, 위, 오른쪽, 아래]`, 0~1 정규화 좌표입니다.
**아래 좌표는 실제 LMB 방송 레이아웃을 측정한 값이 아니며 그대로 사용하면 안 됩니다.**

```json
{
  "language": "eng",
  "minimum_word_confidence": 60,
  "regions": {
    "pitcher_name": [0.05, 0.80, 0.50, 0.88],
    "pitcher_team": [0.05, 0.88, 0.30, 0.94],
    "pitcher_jersey": [0.50, 0.80, 0.60, 0.88],
    "batter_name": [0.05, 0.70, 0.50, 0.78],
    "batter_jersey": [0.50, 0.70, 0.60, 0.78],
    "inning": [0.75, 0.05, 0.85, 0.12],
    "count": [0.85, 0.05, 0.95, 0.12]
  }
}
```

`outs`, `runners`, `score`, `pitch_count`, `plate_id` 등의 키도 OCR 원문으로 저장할 수 있습니다.
이 문자열을 구조화된 야구 상태로 해석하는 파서는 미구현입니다.
다른 OCR 언어를 사용하려면 해당 Tesseract traineddata를 로컬에 준비하세요.
이름은 악센트·공백·구두점을 정규화해 이름/별칭과 일치시킵니다.
이름 이외 팀 또는 등번호 근거를 요구하고, 근거 부족 후보를 숨기지 않습니다.
12초 이내 OCR 문맥을 결합하는 실험 규칙으로 교체 선수 식별 정확도는 별도 검증 대상입니다.
OCR 단독으로 이벤트를 생성하지 않으며 분류 모델의 delivery 전이가 필요합니다.

## 4. 분석·중단·검수·출력

README의 `new`, `analyze` 명령 또는 GUI를 사용합니다.
분석 도중 Ctrl+C / GUI 중단으로 멈춘 뒤 같은 명령과 같은 캐시 경로로 재개합니다.
CPU 디코딩·추론과 해당 프레임 DB 트랜잭션 이후에 중단됩니다.
캐시는 원본 전체 해시, 모델 해시/메타데이터, OCR 프로필, 샘플링 설정으로 구분되며 선수 변경과 무관하게 재사용됩니다.
다른 선수의 프로젝트는 `new`로 만들고 같은 캐시를 지정하세요.

후보 JSON의 `warnings`, `evidence`, `segments`를 확인합니다.
모든 후보는 `REVIEW_REQUIRED`, 보정 신뢰도는 `null`입니다.
일반 방송 컷 전환은 이벤트를 종료하지 않으며 dead 상태 또는 다음 setup까지 유지합니다.
실제 끝 장면이 없거나 영상 종료에 도달하면 불확실성을 기록합니다.
4 fps 샘플링으로 시작 시각은 최대 약 한 샘플 간격의 관측 제한을 가집니다.
프레임 단위 동작 경계 정밀화는 미구현입니다. 출력 재인코딩은 지정한 소수초 경계를 사용합니다.

리플레이는 모델의 replay 분류로만 구별합니다. 분할 파일의 경계 60초 안에서
8개 이상(4 fps)의 연속 SHA-256 프레임 일치와 4개 이상의 서로 다른 프레임이 있으면
중복 구간 근거를 기록합니다. 재인코딩된 중복이나 다른 앵글 리플레이는 놓칠 수 있습니다.
중복 후보를 임의 삭제하지 않으므로 반드시 검수에서 제외하세요. 중복 미검출은 중복 없음의 증명이 아닙니다.

```powershell
# 실제 프로젝트 이벤트 ID로 치환. 원본·시작·끝·대상 선수를 확인한 뒤에만 승인
.\.venv\Scripts\python.exe -m bsae.cli review private\game.json EVENT_ID --status APPROVED --confirm-identity --note "원본 대조 검수"
.\.venv\Scripts\python.exe -m bsae.cli export private\game.json "D:\스카우팅\Daniel_Martínez_20260818_Pitcher_Scouting" --mode all
.\.venv\Scripts\python.exe -m bsae.cli export private\game.json "D:\스카우팅\투구별" --mode pitch
# 타석별 출력 전 GUI 또는 confirm-plate 명령으로 각 그룹 확정 필요
.\.venv\Scripts\python.exe -m bsae.cli confirm-plate private\game.json PLATE_ID
.\.venv\Scripts\python.exe -m bsae.cli export private\game.json "D:\스카우팅\타석별" --mode plate
```

출력 경로는 새 폴더입니다. 기존 폴더·파일에 덮어쓰지 않습니다.
폴더 안에 MP4, manifest.json(스트림·길이·디코딩·출력 해시), events.json/CSV를 만듭니다.
전체 출력은 all_0001.mp4이며 폴더 이름으로 선수·날짜를 구분합니다.
오디오가 없으면 무음 AAC를 생성합니다. 소스에 있는 오디오는 AAC로 변환해 유지합니다.
타석 그룹은 동일 타자·이닝·선택적 plate_id/count 문맥에 따른 제안으로 종료 판정이 불완전합니다.
검수로 투구 경계를 바꾸면 미리보기에서 원본 연결부까지 확인하세요.

## 5. 독립 정답과 비교

`truth.json` 배열은 **경기 통합 타임라인 초**를 사용합니다.
`player_id`는 프로젝트의 선수 ID를 쓰고 실제 타석 ID와 후속 플레이 종료를 포함합니다.
정답 작성자는 전체 영상을 확인해 누락 이벤트도 기록해야 합니다.

```json
[{"start": 10.0, "end": 25.0, "player_id": "프로젝트 선수 ID", "plate_id": "실제 타석1", "followup_end": 24.5}]
```

```powershell
.\.venv\Scripts\python.exe -m bsae.cli evaluate private\game.json private\truth.json private\evaluation --manual-seconds 7200 --assisted-seconds 1800
```

위 시간은 명령 형식 예시이며 측정값이 아닙니다. 실제 측정하지 않았으면 시간 옵션을 생략합니다.
JSON/CSV 보고서는 IoU >= 0.5, 중복 금지 일대일 greedy 매칭으로 계산합니다.
선수 미확정 후보는 선수 식별 정답이 있는 매칭에서 오답으로 계산됩니다.
정답 이벤트가 없으면 성능을 주장하지 않으며 `NOT_EVALUATED`를 기록합니다.
타석 재현율은 정답 타석별 적어도 한 투구가 매칭된 비율이고, 모든 투구 보존을 보장하지 않습니다.
미포함 장면 비율은 이벤트 단위 누락률로 계산하며 실제 경기 정답 없이 측정할 수 없습니다.
