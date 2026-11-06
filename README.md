# Baseball Scouting AI Editor

목적은 대상 투수·타자의 **모든 플레이를 자동으로 찾아 스카우팅 MP4를 제작·납품**하는 것입니다.
기존 코드는 보존하고 사용자 흐름을 다음으로 줄였습니다.

**영상 선택 → 선수 지정 → AI 탐색 → 후보 검수 → MP4 저장**

## 사용자 실행

Windows 사용자는 Python·pip·FFmpeg를 설치하지 않습니다.
GitHub **Actions → Windows portable EXE → 성공한 실행 → Artifacts →
BaseballScoutingAIEditor-Windows-x64-development**에서 받은 프로그램 ZIP을 전부 풀고
`BaseballScoutingAIEditor.exe`를 실행하는 배포 구조입니다.
**실제 성공한 실행과 Artifact가 있어야 다운로드할 수 있습니다.**
[다운로드 안내](docs/WINDOWS_DOWNLOAD.md)

현재 개발판은 영상 입력·검수·출력 시험용이며 **검증된 야구 모델이 없어 AI 자동 탐색이 비활성화**됩니다.
이 개발판을 실제 전수 자동 탐색이 완성된 제품으로 표시하지 않습니다.
정식 AI판은 해당 방송에서 검증한 모델·중계 프로필·필수 자산이 없으면 빌드를 차단합니다.

## 실제 영상 제작

[실무 절차와 재사용 AI 프롬프트](docs/SCOUTING_WORKFLOW.md)를 사용합니다.
ChatGPT 프롬프트만으로 로컬 영상 경로를 읽거나 투구를 발견할 수는 없습니다.
실제 자동 탐색을 사람이 전 경기를 수동 검색하는 흐름으로 대체하지 않습니다.

실제 Daniel Martínez 경기영상은 사용자 PC에만 보관하며 업로드하지 않습니다.
해당 원본을 분석하거나 완성 스카우팅 MP4를 제작한 상태가 아닙니다.
모든 실제 경기 성능은 `NOT_EVALUATED`입니다.

## 구현과 검증

다중 원본·PTS 타임라인·원본 보호, 로컬 후보 엔진·OCR·캐시,
한국어 검수 UI, 승인 구간 MP4 출력·디코딩 검증을 재사용합니다.
모델 경로·OCR 설정은 기본 사용자 화면에서 숨기고 학습·평가 도구는 개발용으로만 보존합니다.
범용 학습 시스템이나 분석 대시보드의 추가 개발은 진행하지 않습니다.

- [구현 상태](docs/STATUS.md)
- [패키징/빌드](docs/PACKAGING.md) — 제작자용, 사용자 설치 절차가 아닙니다.
- [로컬 검증 도구](docs/LOCAL_VALIDATION.md) — 개발자용
- [구조](docs/ARCHITECTURE.md)

기존 `baseball-scouting-auto-editor` 저장소는 수정하지 않았습니다.
