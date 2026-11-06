# Baseball Scouting AI Editor — 1.0 개발판

Windows용 전수 수집형 야구 스카우팅 편집기를 개발하는 저장소입니다.
**완성된 1.0 제품이 아닙니다. 현재 제공되는 검증된 야구 모델·Windows EXE는 없습니다.**
Daniel Martínez의 2026-08-18 경기영상에는 접근하지 않았으며 실제 경기 성능은 모두
`NOT_EVALUATED`입니다. 원본은 사용자 PC에만 두고 GitHub나 클라우드에 업로드하지 마세요.

구현: 다중 원본 통합 타임라인, FFmpeg 스트리밍 디코딩, 로컬 상태 분류기 학습/추론,
설정 가능한 Tesseract OCR, 선수 근거 결합, 후보·검수 기록·타석 그룹,
SQLite 분석 재개, 한국어 PySide6 검수 GUI, 승인 구간 MP4 출력과 전체 디코딩 검사,
JSON/CSV 성능 평가, Windows onedir 빌드 절차.

**모델이 없으면 자동 분석을 차단합니다.** 학습 코드는 실제로 가중치를 학습하고 영상에서 추론하지만,
작은 RGB·에지·움직임 특징 분류기가 실제 야구 중계를 충분히 이해한다는 검증은 없습니다.
합성 테스트 모델은 테스트 내부에서만 생성하며 사용자용 야구 모델로 배포하지 않습니다.
현재 상태와 남은 필수 작업은 [개발 보고서](docs/STATUS.md)를 확인하세요.

## 개발 실행

Python 3.12 x64, FFmpeg/FFprobe(libx264/AAC), Tesseract 5와 eng 언어 자료가 필요합니다.
다음 명령은 개발자를 위한 것입니다. 일반 사용자용 포터블 배포본은 아직 없습니다.

```powershell
cd C:\work\baseball-scouting-ai-editor
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m bsae.cli doctor
.\.venv\Scripts\python.exe -m bsae.app
```

Linux: `python3 -m venv .venv`, 위 명령의 Python을 `.venv/bin/python`으로 바꿉니다.
테스트: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.
Windows PowerShell에서는 `$env:QT_QPA_PLATFORM='offscreen'`을 먼저 지정합니다.
Qt 오디오 초기화는 제한 샌드박스에서 지연될 수 있으며 GUI 검사는 오디오 초기화가 허용되는 실행 경로가 필요합니다.

## 실제 경기 로컬 검증

[Windows 로컬 실행·학습·평가 안내](docs/LOCAL_VALIDATION.md)를 따라 진행하세요.
데이터가 없는 상태의 이름 입력만으로 Daniel Martínez를 자동으로 찾을 수 있다고 주장하지 않습니다.
아직 목표 재현율 95%, 정밀도 90%, 선수 정확도 98%, 경계 오차 1초를 달성했다고 볼 근거가 없습니다.

```powershell
.\.venv\Scripts\python.exe -m bsae.cli new private\game.json "D:\경기\1.mp4" "D:\경기\2.mp4" "D:\경기\3.mp4" --name "Daniel Martínez" --role pitcher --date 2026-08-18
# 실제 야구 라벨로 학습·독립 평가한 모델 및 중계 ROI 설정을 준비한 다음 실행
.\.venv\Scripts\python.exe -m bsae.cli analyze private\game.json --model private\model\model.json --profile private\broadcast.json --cache private\game.sqlite
```

후보는 모두 미승인 상태로 생성됩니다. 이름 OCR 외 팀/등번호 근거가 부족하면 선수 ID는 미확정으로 남습니다.
GUI에서 대상 선수·컷 경계·후속 플레이를 확인하고 승인한 이벤트만 출력합니다.
전체 후보를 보존하므로 다른 선수의 미확정 후보도 보일 수 있습니다.
검수 기록이 있는 프로젝트의 재분석은 거부하며 새 프로젝트와 기존 캐시로 진행합니다.

## Windows 빌드

[패키징 안내](docs/PACKAGING.md). 실제 Windows 빌드 성공은 **NOT_TESTED**입니다.
검증된 모델, OCR·FFmpeg 도구, 라이선스·대응 소스가 없으면 빌드를 중단합니다.
GitHub Actions는 합성 영상 테스트만 실행하며 실제 경기영상은 다운로드하지 않습니다.

```powershell
.\scripts\build_windows.ps1 -Assets C:\BSAE-build-assets
```

소스 버전은 `1.0.0.dev1`입니다. 기존 `baseball-scouting-auto-editor` 저장소는 수정하지 않았습니다.
