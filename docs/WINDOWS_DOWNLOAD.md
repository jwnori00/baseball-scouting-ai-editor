# Windows 개발판 EXE 다운로드

개발판은 **검증된 야구 모델이 없으므로 AI 자동 분석이 비활성화**되어 있습니다.
영상 등록·미리보기·검수·수동 시험 구간·MP4 출력과 포터블 실행을 시험하는 용도입니다.
투구 전수 자동 탐색을 완성한 정식 1.0이 아닙니다.

1. GitHub 저장소 **Actions**를 클릭합니다.
2. 왼쪽에서 **Windows portable EXE**를 선택합니다.
3. **초록색 체크(성공)**가 표시된 실행을 클릭합니다.
4. 페이지 아래 **Artifacts**에서 **BaseballScoutingAIEditor-Windows-x64-development**를 클릭합니다.
5. 받은 Artifact ZIP을 풀면 실제 프로그램 ZIP과 `.sha256` 파일이 나옵니다.
6. `BaseballScoutingAIEditor-Windows-x64-development.zip`도 새 폴더에 **전부 압축 해제**합니다.
7. `BaseballScoutingAIEditor\BaseballScoutingAIEditor.exe`를 더블클릭합니다.

Python·pip·FFmpeg 설치나 환경변수 설정은 필요하지 않습니다.
EXE 파일 하나만 꺼내지 말고 `_internal` 폴더를 포함한 전체 폴더를 유지하세요.
코드 서명은 아직 하지 않았으며 깨끗한 사용자 PC 검증은 별도입니다.

Artifact 이름이 없거나 실행이 빨간색 실패라면 ZIP이 생성된 것으로 보지 마세요.
**Windows-build-evidence** Artifact의 `portable-build.log`, `media-build.log`,
`windows-tests.xml`, `portable-smoke.json`을 확인합니다.
재배포자는 옆에 게시되는 **ThirdPartyCorrespondingSources**도 함께 제공해야 합니다.

## 개발판 사용

영상 선택 → 선수 이름 입력 → **개발판 시험 메뉴의 경기 등록** → 시작·종료 초 입력 →
미리보기 → **누락 후보 보조 추가** → 목록 선택 → **대상 선수 확인** →
**수정·검수 승인** → **MP4 저장** 순서로 편집 경로를 시험할 수 있습니다.
이 시험용 수동 경로를 최종 AI 제품의 완성으로 간주하지 않습니다.

## 빌드 직접 시작

워크플로가 기본 브랜치에 반영된 후 **Windows portable EXE → Run workflow → kind: development → Run workflow**.
`release`는 검증된 야구 모델·독립 평가·상업 이용 검토가 없으면 의도적으로 차단합니다.
다운로드 가능 여부는 실제 실행 결과와 Artifact 게시 성공으로 확인해야 합니다.
