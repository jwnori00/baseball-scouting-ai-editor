> 현재 통합 시험판: 자동 신원·수동 확인·검수를 분리하고 자막 근거와 경기 인덱스를 기록합니다.
> 유니폼 번호 인식·선수 추적·새 전체 경기의 타자 식별은 미완료입니다.
> preview8 타자 자막 보완과 실제 실패: [타자 식별 검사](docs/BATTER_SCOREBUG_V4.md).
> 실제 시험과 실패 범위: [통합 인덱스·신원 검증](docs/UNIFIED_IDENTITY_INDEX.md).

# Baseball Scouting AI Editor — 자동 플레이 탐색 검증판

기존 Windows 영상 입력·검수·MP4 출력을 유지하며,
**영상 선택 → 투수/타자 지정 → 자동 플레이 탐색 → 검수 → MP4 저장**으로 작업합니다.
사용자 PC에 Python·pip·FFmpeg를 설치하지 않습니다.

## 실행

GitHub **Actions → Windows portable EXE → 성공한 통합 브랜치 실행 → Artifacts →
BaseballScoutingAIEditor-Windows-x64-rules-preview**를 받습니다.
Artifact ZIP 안의 프로그램 ZIP도 새 폴더에 전부 풀고 `BaseballScoutingAIEditor.exe`를 실행합니다.
**실제 성공한 실행과 Artifact가 있을 때만 다운로드할 수 있습니다.**
[다운로드 안내](docs/WINDOWS_DOWNLOAD.md).

## 자동 탐색 구현 범위

기본 엔진은 중계 구도·카메라 보정 국소 움직임·OCR·시간 문맥을 결합한 규칙 방식입니다.
일반 동작 모델의 야구 판정을 필수 조건으로 사용하지 않습니다.
후보는 자동 승인하지 않고, 이름+팀 등의 근거가 부족하면 신원 미확정으로 남깁니다.
타자는 개별 투구와 타석 그룹을 구분하며, 카운트가 그대로인 파울도 움직임 후보를 유지합니다.

기본 프로필은 제공된 LMB 샘플의 여백/자막 배치를 대상으로 합니다.
다른 방송 배치·다양한 교체/견제/리플레이·의미적 플레이 종료는 추가 검증이 필요합니다.
정식 1.0 또는 모든 경기에서의 전수 검출 성능을 주장하지 않습니다.
이전 **development** ZIP은 자동 탐색이 차단된 수동 검증판이므로 새 **rules-preview**와 구분하세요.

- [투수·타자 사용 매뉴얼](docs/AUTOMATIC_DISCOVERY.md)
- [실제 샘플 검증 결과와 한계](docs/RULES_VALIDATION.md)
- [실무 절차·재사용 프롬프트](docs/SCOUTING_WORKFLOW.md)
- [Windows 제작/검사](docs/PACKAGING.md) — 제작자용이며 사용자 설치 절차가 아닙니다.

실제 원본과 추출 프레임은 GitHub/CI에 올리지 않습니다.
제공된 91초 샘플은 분석했지만 사용자 PC의 1.2GB 이상 전체 원본을 읽은 것은 아닙니다.
기존 main, 성공한 fix/windows-portable-build 및 기존 v0.2.0 저장소는 보존합니다.
