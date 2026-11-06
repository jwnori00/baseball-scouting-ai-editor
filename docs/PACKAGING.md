# 포터블 배포 — 제작 환경 전용

사용자는 개발 명령을 실행하지 않습니다. Codex/GitHub Actions에서 빌드하고
사용자는 ZIP 전체를 풀어 EXE를 실행합니다. [다운로드 안내](WINDOWS_DOWNLOAD.md).

## 개발판과 정식 AI판

| 조건 | development | release |
|---|---|---|
| Python/Qt/OpenCV/NumPy 내장 | 필수 | 필수 |
| FFmpeg/FFprobe, OCR DLL/언어 자료 내장 | 필수 | 필수 |
| GUI 영상 입력·검수·MP4 출력 | 가능 | 가능 |
| 야구 모델·중계 프로필 | 동봉하지 않음 | 검증된 자산 필수 |
| AI 자동 탐색 | 비활성화 | 검증 조건 충족 시에만 활성화 |
| 실제 자동 스카우팅 납품에 사용 가능하다는 주장 | 금지 | 실제 경기/납품 검수 필요 |

`packaging/validate_assets.py`는 파일 SHA-256과 필수 구성요소를 검사합니다.
release는 `models/model.json`, 가중치, `models/broadcast.json`, `models/validation.json`을 요구합니다.
독립 실제 경기 평가·상업 이용 검토·모델 해시 연결이 없거나 미평가 값이면 차단합니다.
현재 이 모델 자산은 준비되지 않았습니다. 합성 테스트 모델을 배포 모델로 대체하지 않습니다.

## GitHub Actions 제작 순서

워크플로: `.github/workflows/windows-portable.yml` / 표시명 **Windows portable EXE**.

1. Python 3.12 x64 및 고정 빌드 의존성을 Actions에 설치합니다.
2. FFmpeg와 x264의 고정 공식 Git 커밋을 소스 빌드합니다.
3. MSYS2의 네이티브 MINGW64 Tesseract와 종속 DLL·라이선스를 수집합니다.
4. 공식 OCR 영어 자료, Qt/PySide 및 Qt Multimedia FFmpeg의 대응 소스를 수집합니다.
   Qt 소스는 공식 SHA-256과 대조하고 모든 자산의 해시를 기록합니다.
5. 합성 통합 테스트 → PyInstaller onedir → 실제 EXE 자체검사를 순서대로 실행합니다.
6. 성공해야만 ZIP과 SHA-256을 Application Artifact로 게시합니다.
   정확한 대응 소스는 **ThirdPartyCorrespondingSources**로 같은 실행에 게시합니다.
7. 실패 로그/테스트/EXE 보고서는 **Windows-build-evidence**로 남깁니다.
   비공개 경기영상은 CI에서 받거나 올리지 않습니다.

로컬 제작 PC용 보조 스크립트는 `scripts/build_windows.ps1`입니다.
**이 스크립트를 최종 사용자에게 실행하도록 요구하지 않습니다.**

## 실제 검증의 범위

EXE 자체검사는 외부 Python/FFmpeg를 PATH에서 제거한 상태에서
내장 도구·OCR 실행, Qt 창 생성, 합성 영상 로드, GUI의 시험 구간/검수,
프로젝트 왕복 저장, MP4 출력/디코딩, 원본 해시 보존을 확인합니다.
개발판의 AI 버튼이 비활성화되는지도 검사합니다.

이 검사는 실제 야구 자동 탐색·깨끗한 Windows 사용자 PC의 전체 동작을 증명하지 않습니다.
별도 Windows 10/11 x64 PC/VM에서 인터넷 없이 ZIP 해제·더블클릭·영상 재생·출력을 확인해야 합니다.
정식 AI판에서는 대상 선수 전수 탐색·준비동작/반환 송구·수비/주루 종료 보존까지 확인해야 합니다.
`scripts/test_clean_windows.ps1` 및 EXE의 `--acceptance-test`는 제작/검증 담당자용으로 보존합니다.
미평가 성능을 인수 통과로 처리하지 않습니다.

## 라이선스와 출처

- FFmpeg n7.1.3: `f46e514491172d15bd74b4abb1814cd2f05a763e`
- x264: `c24e06c2e184345ceb33eb20a15d1024d9fd3497`
- Qt/PySide 6.8.3: 공식 소스 아카이브와 실제 설치 배포판의 라이선스 수집
- Tesseract: MSYS2 native package, 종속 DLL·실제 package versions와 라이선스 수집
- OCR 영어 자료: 공식 tessdata_fast의 전체 Git revision을 기록한 파일

GCC/MSYS2·패키지 버전·빌드 명령·FFmpeg 설정·공식 다운로드 URL·체크섬을 보존합니다.
Qt DLL은 교체 가능한 개별 라이브러리로 배포합니다. 대응 소스 Artifact는 재배포 시에도
프로그램과 같은 다운로드 위치에 제공해야 합니다. 모델·원본의 이용 권한은 별도 확인 사항입니다.
코드 서명·SmartScreen·실제 사용자 PC 검증은 아직 완료하지 않았습니다.

## 가벼운 영상 도구 구성

입력은 일반 중계 코덱 H.264/HEVC/VP8/VP9/MPEG-2/MPEG-4/MJPEG 및 MP4/MOV/MKV/TS/AVI를
중심으로 구성하며, FFV1/RAW는 합성 검증에 사용합니다. 모든 특수 코덱을 지원하는 범용 FFmpeg 배포가 아닙니다.
출력은 H.264/AAC MP4입니다. 준비된 자산은 파일 해시 검사를 유지하면서 빌드 캐시로 재사용합니다.
