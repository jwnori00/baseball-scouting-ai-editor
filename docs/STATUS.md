# 개발·검증 보고서

2026-11-06, 버전 `1.0.0.dev1`. 완성형 1.0 출시가 아닙니다.
신규 저장소 `jwnori00/baseball-scouting-ai-editor`, 기능 브랜치 `feat/scouting-ai-foundation`.
기존 저장소와 main을 초기화·덮어쓰기·강제 푸시하지 않았습니다.

| 항목 | 실제 상태 |
|---|---|
| 다중 원본·통합 타임라인·구간 분할·PTS 범위 | IMPLEMENTED / 합성 TESTED |
| 원본 전체 SHA-256·변경 차단·기존 출력 보호 | IMPLEMENTED / TESTED |
| RGB/움직임/에지 특징 기반 CPU 로컬 모델 학습·추론 | IMPLEMENTED / 합성 TESTED |
| 실제 방송용 야구 동작 모델·가중치 | BLOCKED: 학습자료·검증된 모델 없음 |
| 동작 모델+상태 조립에 의한 후보 자동 발견 | IMPLEMENTED / 합성 TESTED / 실제 경기 NOT_TESTED |
| Tesseract ROI OCR·악센트 이름·팀/등번호 근거 결합 | IMPLEMENTED / 합성 TESTED |
| 투수·타자 역할과 미확정 선수 후보 보존 | IMPLEMENTED / 규칙 TESTED / 실제 교체 장면 NOT_TESTED |
| 타석 자동 그룹 제안·검수 확정 | IMPLEMENTED / 규칙 TESTED / 실제 전수 타석 NOT_TESTED |
| 중계 화면 전환 중 활성 이벤트 유지 | IMPLEMENTED / 상태 규칙 TESTED |
| replay 상태 제외·정확한 원본 경계 해시 중복 근거 | IMPLEMENTED / 합성 TESTED |
| 다른 앵글·재압축 리플레이의 확실한 중복 제거 | NOT_IMPLEMENTED / 실제 성능 NOT_EVALUATED |
| 모든 결과 유형별 후속 수비·주루·판정 종료 | BLOCKED: 검증된 동작/결과 모델 필요; 검수 경고만 구현 |
| 장기 동작 인식·스윙·공/선수 추적 | NOT_IMPLEMENTED |
| OCR의 볼/스트라이크/아웃/주자 구조화 상태 해석 | NOT_IMPLEMENTED: 현재는 임의 ROI 원문 저장 |
| 캐시·분석 중단/재개·선수와 무관한 캐시 키 | IMPLEMENTED / TESTED |
| 한국어 GUI·작업 스레드·후보 검수·영상 미리보기 | IMPLEMENTED / 창 생성·모델 게이트 TESTED; 실제 재생/전체 조작 NOT_TESTED |
| 승인 이벤트 전체/투구/확정 타석 MP4·오디오·디코딩 검증 | IMPLEMENTED / 합성 TESTED |
| 로컬 정답 JSON/CSV 평가·미평가 처리 | IMPLEMENTED / TESTED |
| EXE 내장 도구·내장 모델 자동 탐색·onedir spec | IMPLEMENTED / 경로 선택만 Linux TESTED |
| Windows x64 포터블 ZIP·SHA-256 실제 생성 | BLOCKED / NOT_TESTED |
| 인터넷 없는 깨끗한 Windows PC에서 전체 흐름 | BLOCKED / NOT_TESTED |
| 실제 Daniel Martínez 경기 성능·95% 재현율 등 목표 | NOT_EVALUATED |

## 기존 v0.2.0 검토

읽기 전용 참고 복제의 HEAD: `4fe89346c47785819f384097775976fc3f873b13`.
`engine/render.py`, `video.py`, `runtime.py`, `project.py`, `quality.py`, `gui/app.py`,
테스트 목록, Windows spec, 빌드·고지·소스 수집·CI를 검토했습니다.
원본 보호, 검수 승인, 도구 절대경로, 출력 디코딩, onedir 및 대응 소스 보존 방식을 참고했습니다.
기존 프로젝트의 코드 재사용 허가를 명시한 LICENSE를 발견하지 못해 **복사한 코드는 없습니다**.
기존 단일 원본 모델 대신 경기 세션·원본별 구간·통합 시각 구조를 새로 작성했습니다.

## 실제 실행 결과

Linux, Python 3.12.14, FFmpeg 7.1.5, PySide6 6.8.3, NumPy 2.2.6, OpenCV 4.12.0.88.
최종 전체 검사: **17 passed, 0 failed, 0 skipped** (`9.99s`).
기록: 로컬 `build-evidence/linux-tests.xml` (저장소에는 올리지 않음).
`pip check` 통과, 고정 의존성 재설치 및 editable 설치 반복 통과, 소스 컴파일 검사 통과.

합성 학습 데이터로 직접 모델 가중치를 학습한 후 FFmpeg 영상 스트림에서 후보를 찾고,
미승인 출력 차단 → 사람 검수 기록 → 전체/투구/타석 렌더링 → 디코딩·원본 해시 검사를 연결했습니다.
타임스탬프 정답은 비교에만 사용하며 모델의 이벤트 출력으로 주입하지 않았습니다.
프레임·색/패턴을 상태별로 구분한 합성 영상이므로 실제 야구 의미 인식·일반화의 증거는 아닙니다.
OCR 실제 실행, 중단/캐시 재개, 가변 PTS, 다중 원본 경계 컷, 선수 근거 결합,
리플레이 상태, 중복 근거, 번들 모델 자동 선택과 미평가 인수 시험 실패 처리도 검사했습니다.

발견/수정: Qt `event()` 이름 충돌, 제한 실행 환경의 Qt 오디오 초기화 지연,
시작 PTS가 0이 아닌 Matroska의 format.duration 오해, 빈 타석 출력 그룹 처리.
Qt 검사는 오디오 초기화가 허용된 실행 경로에서 수행했습니다.
GitHub Actions의 Windows/Linux 테스트 정의는 작성했지만 원격 실행 결과는 아직 확인하지 않았습니다.

## 포터블 추가 요구사항

최종 배포 사용자는 Python·FFmpeg·pip·설치 마법사·환경변수를 사용하지 않아야 합니다.
현재 빌드 계약은 Python/Qt/OpenCV/NumPy와 도구·OCR 언어자료·모델·라이선스·대응 소스를
Onedir ZIP에 포함하며 frozen 모드에서는 외부 PATH 도구로 대체하지 않습니다.
모델은 번들 경로에서 자동 선택되고 기본 추론은 CPU입니다. 클라우드 AI API 호출은 없습니다.

하지만 **이 환경에서 EXE나 ZIP을 만들지 않았습니다**.
검증된 야구 가중치/재배포 자산이 없고 현재 실행 환경이 Linux이므로
깨끗한 Windows 10/11 x64 PC의 더블클릭→AI 탐색→검수→출력을 확인할 수 없습니다.
개발판 합성 가중치를 제품 모델로 동봉하거나 빌드 성공으로 표시하지 않습니다.

## 다음 작업의 전제

1. 권한 있는 로컬 야구 데이터로 클래스/선수/후속 플레이를 라벨링하고 독립 경기로 검증합니다.
   현재 기초 선형 분류기의 성능이 부족하면 실제 동작 모델을 추가 학습해야 합니다.
2. 세부 결과별 종료 규칙, 스윙/수비/주루 인식, 리플레이 일반화, 정밀 경계와 타석 종료를 구현·검증합니다.
3. 재배포 권리가 확인된 모델·FFmpeg/OCR·Qt 소스/고지 자산을 준비합니다.
4. Windows에서 빌드 스크립트와 EXE 자체검사를 실행하고, 별도 깨끗한 오프라인 PC에서 인수 시험을 수행합니다.

실제 원본은 사용자의 Windows PC에 유지합니다. 업로드를 요청하지 않습니다.
실행 명령은 README와 docs/LOCAL_VALIDATION.md, 제작/깨끗한 PC 검사는 docs/PACKAGING.md에 있습니다.
현재 GitHub API 읽기는 `Forbidden`으로 거부되어 PR 자동 생성은 불가능했습니다.

## Windows 포터블 수정 작업

- `editor.spec` 누락 원인: 기존 `.gitignore`의 `*.spec` 규칙 때문에 로컬 파일이 커밋에서 제외됨.
  `/packaging/editor.spec` 예외를 추가해 추적함.
- 개발판에도 모델을 필수로 요구하던 자산 게이트를 development/release로 분리.
  development는 모델을 동봉하지 않고 AI를 비활성화함.
- 정식 release는 실제 야구 독립 평가 보고서, 모델 해시 결합, 목표 성능과 상업 이용 검토를 요구함.
- FFmpeg 버전마다 달라지는 선택된 마지막 VFR 프레임의 0.1/0.3초 길이를 구분하고
  테스트는 5초의 PTS 원점을 제외한 실제 재생 범위를 검사함.
- Linux Qt 의존성 `libegl1` 등 시스템 패키지 추가.
- Windows 전용 워크플로: 네이티브 FFmpeg 소스 빌드, 네이티브 OCR DLL/자료,
  Qt 대응 소스/라이선스/체크섬 수집, 테스트, 실제 frozen EXE 자체검사, ZIP/SHA-256 Artifact.
- 최근 main 실행 42173406878의 Windows/Linux 실패 상태와 작업 ID를 확인함.
  상세 로그는 GitHub 웹의 로그인 제한과 API Forbidden 때문에 직접 열람하지 못함.
  공개 페이지의 실패 상태, 사용자 제공 오류, 로컬 재현을 구분하여 진단함.
- 사용자 다운로드 절차: docs/WINDOWS_DOWNLOAD.md.

## 실무형 범위 조정

- 사용자 화면을 영상 선택·선수 지정·AI 탐색·검수·MP4 저장으로 축소.
  모델 경로/OCR 설정과 상세 근거는 기본 화면에서 숨김.
- 학습·평가·분석 대시보드의 추가 개발 중단. 기존 코드는 삭제하지 않고 보존.
- 로컬 회귀 테스트: 20 passed. GitHub 실행 42174601699에서 Windows/Linux 테스트 성공 확인.
- 실제 AI는 합성 학습/추론 연결만 검증. 실제 야구 전수 탐색·선수 식별·후속 플레이 보존은 미검증이며
  검증된 모델이 없는 포터블 개발판에서는 분석을 비활성화.
- Windows 실행 42174601841은 실제 네이티브 미디어 빌드를 진행 중인 상태에서 확인함.
  최종 성공/ZIP 여부는 이후 실행 결과로 판단해야 함.
- 실제 납품 작업 및 ChatGPT 보조 프롬프트는 docs/SCOUTING_WORKFLOW.md에 정리.
  원본 접근 없이 AI가 영상을 분석한 것으로 보고하지 않으며, 수동 전 경기 검색으로 자동 탐색을 대체하지 않음.
