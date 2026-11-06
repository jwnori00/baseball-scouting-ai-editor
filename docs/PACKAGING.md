# Windows 개발판 패키징

상태: **NOT_TESTED**. Linux에서 Windows EXE가 성공했다고 주장하지 않습니다.
현재 필요한 검증된 야구 모델과 재배포 자산은 **BLOCKED**입니다.
빌드 스크립트와 spec을 제공한 것이 실제 ZIP 생성·실행 성공을 뜻하지 않습니다.

제작자는 Windows 10/11 x64, Python 3.12 x64, Git을 준비합니다.
일반 사용자에게 이 설치를 요구하는 최종 배포 흐름은 아직 완성되지 않았습니다.

## 빌드 자산 계약

저장소 외부 `C:\BSAE-build-assets`에 다음을 준비합니다.

```
assets.json
models/model.json
models/temporal.npz
tools/ffmpeg.exe
tools/ffprobe.exe
tools/tesseract.exe
tools/tessdata/eng.traineddata
tools/(Tesseract 실행에 필요한 DLL들)
licenses/(모델·Tesseract·언어 데이터·FFmpeg·x264 등의 실제 라이선스)
corresponding-source/(사용한 Qt/PySide/FFmpeg/x264 등의 완전한 대응 소스·빌드 명령)
```

모든 배포 자산의 SHA-256을 `assets.json`에 등록합니다.
`{"files":[{"path":"tools/ffmpeg.exe","sha256":"실제 64자리 체크섬"}]}` 형식이며 모든 파일을 나열해야 합니다.
모델 manifest도 자체 체크섬·라이선스·학습 출처를 갖춰야 합니다.
체크섬은 신뢰할 수 있는 배포자의 공식 체크섬 또는 직접 재현한 빌드 산출물과 대조하세요.
다운로드한 파일에서 해시를 계산해 목록에 넣는 행위만으로 배포자의 진위를 검증할 수는 없습니다.
도구는 공식 프로젝트의 검증된 소스·릴리스를 사용하고 인증서/체크섬 검사를 끄지 마세요.
빌드 도구는 자산의 변경 여부와 형식을 검사하지만 법적 재배포 권한을 대신 판단하지 않습니다.

출처:

- FFmpeg: https://ffmpeg.org/download.html , https://github.com/FFmpeg/FFmpeg
- x264: https://www.videolan.org/developers/x264.html
- Tesseract: https://github.com/tesseract-ocr/tesseract (Apache-2.0)
- 영어 OCR 자료: https://github.com/tesseract-ocr/tessdata (사용한 실제 revision과 LICENSE 유지)
- PySide6/Qt 6.8.3: https://code.qt.io/pyside/pyside-setup.git/ , https://download.qt.io/archive/qt/6.8/6.8.3/

실제 재배포 모델 출처·버전·체크섬·상업 이용 가능 여부는 현재 **없음/미확인**입니다.
임의로 공용 객체 탐지 모델을 야구 투구 모델로 표시하지 않습니다.

## 실행

```powershell
.\scripts\build_windows.ps1 -Assets C:\BSAE-build-assets
```

스크립트는 자산 검사 → 합성 통합 테스트 → PyInstaller onedir → 라이선스 수집 →
PATH에서 외부 도구를 뺀 실제 EXE 자체검사 → ZIP과 SHA-256 순서로 실행하며 실패 시 중단합니다.
실행 파일은 `dist\BaseballScoutingAIEditor\BaseballScoutingAIEditor.exe`입니다.
배포 결과는 `BaseballScoutingAIEditor-Windows-x64-dev.zip`과 `.sha256`입니다.
전체 폴더를 함께 배포해야 하며 `_internal`의 DLL·도구·모델·고지·대응 소스를 유지합니다.
현재 모델 UI 경로는 압축을 푼 폴더의 `_internal\models\model.json`을 선택하세요.
중계별 OCR 프로필은 사용자의 로컬 설정으로 제공해야 합니다.

자체검사는 Qt 창 생성, 내장 모델 무결성/추론 호출, 내장 OCR 실행,
합성 영상 렌더링·디코딩, 프로젝트 왕복 저장 및 원본 보호를 확인합니다.
실제 중계 분석 정확도, Windows 사용자 PC 재생, 읽기 전용 설치 폴더, SmartScreen,
코드 서명 및 일반 사용자 사용성 검증은 별도이며 아직 수행하지 않았습니다.
GitHub Actions는 Windows/Linux 합성 테스트만 실행합니다. EXE 빌드 성공이나 릴리스를 생성하지 않습니다.

## 라이선스 검토

기존 v0.2.0 참고 저장소에는 프로젝트 코드의 재사용 허가 라이선스가 발견되지 않았으므로
코드를 복사하지 않았습니다. 본 저장소의 배포 라이선스 선택도 별도 결정 사항입니다.
Python은 PSF, NumPy는 BSD, OpenCV는 Apache-2.0 및 번들 구성요소 고지를 확인합니다.
PySide6/Qt의 실제 모듈별 LGPLv3/GPL/상용 조건을 확인하고 교체 가능한 DLL을 유지해야 합니다.
FFmpeg의 libx264 활성 빌드는 GPL 조건 및 정확한 대응 소스·빌드 구성을 함께 확인해야 합니다.
PyInstaller 부트로더의 GPL 예외는 실제 버전의 LICENSE를 유지합니다.
`collect_notices.py`는 설치된 Python 배포판의 실제 라이선스 파일을 수집합니다.
대응 소스·권리 고지 완비 여부는 배포 담당자가 실제 자산으로 검토해야 합니다.

## 깨끗한 Windows PC 최종 인수 시험 — 아직 미실행

이 테스트는 배포 사용자에게 설치를 요구하지 않습니다. 테스트 담당자는 Python·pip·FFmpeg·
Tesseract가 없는 새 Windows 10/11 x64 VM/PC에 ZIP 전체를 옮깁니다.
인터넷 연결을 끊고 NVIDIA GPU가 없는 환경에서 검사합니다.
인터넷 차단과 깨끗한 OS 상태는 테스트 담당자가 실제로 확인해야 하며 PATH 검사만으로 증명되지 않습니다.

1. ZIP을 한글·공백 경로에 풀고 EXE를 더블클릭합니다.
2. 내장 모델이 자동 선택되는지, 추가 다운로드·설치·환경변수 요구가 없는지 확인합니다.
3. 로컬 원본 1개/3개를 불러오고 대상 투수·타자를 각각 분석합니다.
4. 후보·근거·불확실성을 확인하고 실제 장면 재생·구간 수정·승인/제외를 수행합니다.
5. 승인 영상 전체·투구별·타석별 MP4를 출력하고 소리·후속 플레이·원본 보존을 확인합니다.
6. 중단·재개, 프로젝트 저장/열기, 기존 출력 보호, 설치 폴더 쓰기 불가 상황을 검사합니다.

자동 로컬 인수 시험도 **동일 EXE**로 실행할 수 있습니다. 실제 사람이 전체 영상에 대해
검수한 정답 프로젝트와 아래 plan JSON을 사용자 PC의 비공개 위치에 준비합니다.

```json
{
  "reference_project": "D:/private/reviewed-game.json",
  "ground_truth_complete": true,
  "followup_reviewed": true,
  "model": "C:/BSAE/_internal/models/model.json",
  "profile": {"language":"eng", "regions":{}},
  "cache": "D:/private/acceptance.sqlite",
  "candidate_project": "D:/private/fresh-candidates.json",
  "output": "D:/private/new-acceptance-export",
  "manual_seconds": 7200,
  "assisted_seconds": 1800
}
```

경로·프로필·시간은 형식 예시입니다. 실제 방송 ROI와 직접 측정한 시간을 사용합니다.
정답이 전수 확인되지 않았으면 두 선언을 true로 설정하지 마세요.
정답 프로젝트는 대상 선수의 실제 플레이 전수·후속 종료를 사람이 확인하고 승인 기록을 저장해야 합니다.
미측정 시간은 생략하면 NOT_EVALUATED이며 인수 시험은 통과하지 않습니다.

```powershell
# 일반 실행은 EXE 더블클릭. 아래 명령은 테스트 담당자용입니다.
.\scripts\test_clean_windows.ps1 -Exe 'C:\BSAE\BaseballScoutingAIEditor.exe' -Plan 'D:\private\acceptance.json' -Report 'D:\private\acceptance-report.json'
```

인수 시험은 새 자동 탐색 결과를 정답과 비교하고, 이미 사람이 승인한 정답 이벤트만 렌더링합니다.
새 AI 후보를 자동 승인해 테스트를 통과시키지 않습니다.
모든 측정 목표를 만족하지 못하면 종료 코드가 실패이며 미평가 지표도 통과로 간주하지 않습니다.
GUI 전체 상호작용 검증은 위 수동 체크리스트로 별도 완료해야 합니다.
원본·프레임·정답·인수 보고서는 GitHub Actions에 올리지 않습니다.
