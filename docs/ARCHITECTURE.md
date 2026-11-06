# 구조와 근거

- `core/models.py`: 경기·다중 원본·선수·투구·타석·검수·출력 데이터, 스키마와 구간 검증.
- `ingest/media.py`: 원본 전체 해시, FFprobe 메타데이터/패킷 PTS, FFmpeg 스트리밍 RGB.
- `vision/model.py`: 로컬 지도학습, 가중치 체크섬·라이선스/출처 검사, CPU 특징 분류.
- `vision/scoreboard.py`: 중계별 정규화 ROI, Tesseract TSV, 이름 정규화 및 복수 근거 결합.
- `vision/pipeline.py`: 4fps 저해상도 스캔, 선택 상태의 960x540 OCR 재검사,
  setup→delivery→receive/live→dead/next setup 상태 조립, 취소와 캐시 재개.
- `vision/replay.py`: 정적 화면을 제외한 원본 경계의 정확한 프레임 해시 중복 근거.
- `vision/cache.py`: 선수와 무관한 분석 결과, SQLite WAL의 프레임별 트랜잭션.
- `core/review.py`: 승인·제외·경계 변경·선수 확인의 감사 기록.
- `export/render.py`: 승인 이벤트만 정렬, 다중 원본 분할 컷, 표준화된 H.264/AAC,
  각 구간/최종 파일 길이·스트림·전체 디코딩·해시 검사, 실패 정리와 기존 출력 보호.
- `evaluation.py`: 정답과 일대일 IoU 매칭, 측정 가능한 지표 및 미평가 구분.
- `gui/window.py`: 한국어 AI 분석 중심 작업 흐름, QThread 작업, 후보 영상 검수.

시간은 초(float)와 원본 PTS origin을 보관합니다. 원본 패킷 PTS로 구간 길이를 확인하며
샘플 시각은 FFmpeg showinfo에서 읽습니다. 디코더의 전체 프레임을 메모리에 쌓지 않습니다.
FFmpeg fps 필터가 균등 샘플링한 PTS이며 원본의 모든 프레임 경계를 저장하는 구조는 아닙니다.
분할 원본의 순서는 사용자 지정 순서입니다. 중복 감지는 근거를 제시하며 자동으로 타임라인을 당기지 않습니다.
겹침/리플레이의 불확실한 자동 삭제로 진짜 투구를 잃지 않도록 후보는 검수 대상으로 유지합니다.

검출 점수는 보정하지 않은 선형 회귀 판별 점수입니다. 확률·정확도·신뢰도로 부르지 않습니다.
confidence는 null이며 전체 성능과 calibration은 NOT_EVALUATED입니다.
분류기는 현재 프레임 공간 특징과 직전 샘플과의 차이를 보며 장기 문맥은 상태 머신에서만 사용합니다.
선수 근거가 부족한 이벤트도 버리지 않으므로 전수 탐색 후 검수 비용은 아직 검증되지 않았습니다.
실제 영상·독립 정답이 없다는 이유로 더미 후보나 정답 타임스탬프를 분석 출력에 넣지 않습니다.
