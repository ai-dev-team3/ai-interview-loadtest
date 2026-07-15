# 이 레포가 성능을 재는 방식

`ai_interview-main`(실전 면접 백엔드)의 성능을 **레포 바깥에서** 잰다. 앱 코드는 건드리지
않되, 파이썬 스크립트는 `back_tooktac`를 `sys.path`에 넣어 **앱 코드를 그대로 import** 한다.
그래서 서버를 안 띄워도 앱의 진짜 STT 코드를 돌릴 수 있다.

```
ai_interview-main/          ← 실제 앱 (서버 코드)
  back_tooktac/app/...
load_test/                  ← 이 레포. 앱을 바깥에서 측정
  bin/k6.exe                    부하 생성기 (gitignore, README에서 받는 법)
  scenarios/*.js                k6 시나리오
  seed/seed.py                  테스트 유저/이력서 시딩, JWT 발급
  mock/                         서버 런처 + 프로파일링/실험 스크립트
```

---

## 측정은 세 계층으로 한다

재려는 대상에 따라 **서버를 켜기도 하고 끄기도 한다.** 이게 핵심이다.

### 계층 1 — 서버 켬, 진짜 HTTP (k6)

end-to-end 지표(동시 사용자 한계 등)에 쓴다.

```
uvicorn(localhost:8000) 켠다
   ↓ 진짜 HTTP / WebSocket
k6 가 scenarios/*.js 실행 → POST /real-interview/answer 등
   → 서버가 ffmpeg + STT + LLM 다 태움 → 응답시간(p95) 집계
```

VU(가상 유저) 하나 = 면접자 한 명. `seed.py`로 만든 유저의 JWT를 쿠키로 붙여 진짜 요청을
보낸다. **앱이 실제로 도는 그대로를 잰다.** 가장 현실적이지만 잡음(네트워크·외부 API)이 많다.

### 계층 2 — 서버 켬, 단 LLM만 가짜 (`mock/serve_mocked.py`)

STT 변경의 `/answer` 효과를 깨끗하게 보려고 쓴다. 계층 1과 똑같이 uvicorn을 띄우되,
**런처가 시작할 때 LLM 호출 함수 세 개를 "N초 자기"로 런타임 패치**한다(앱 코드는 안 고침).
STT·ffmpeg·DB·영상 소켓은 전부 진짜 그대로 돈다.

```
python mock/serve_mocked.py                 # LLM = 2.0초 고정(실측값)
$env:LLM_DELAY_SECONDS=0; ... serve_mocked   # LLM 시간을 아예 뺀다
$env:EMBED_DEVICE=cpu; ... serve_mocked      # 백그라운드 임베딩을 CPU로 (A/B용)
```

이유: OpenAI/Gemini는 호출마다 지연이 들쭉날쭉하고 돈도 든다. 고정 지연으로 박아두면
**측정에서 외부 API 잡음이 빠져** STT 변경 전/후 차이가 선명해진다.

### 계층 3 — 서버 끔, 직접 호출 (`mock/bench_stt.py` 등)

순수 STT 지표(GPU가 몇 건/초를 뱉나)에 쓴다. uvicorn도 HTTP도 없다.

```
서버 안 띄운다
   ↓ 파이썬이 앱 코드를 직접 import
from app.services.stt.sensevoice import SenseVoiceClient
SenseVoiceClient().transcribe(wav) 를 스레드 N개로 동시 호출
   → GPU 추론 시간만 순수 측정
```

HTTP·DB·백그라운드 잡음이 하나도 안 섞여서 **병목의 정체**를 가장 깨끗하게 본다.

### 왜 세 개나 쓰나

| 재는 것 | 계층 | 서버 | 이유 |
|---|---|---|---|
| 동시 사용자 한계, end-to-end | 1: k6 | 켬 | 실제 사용자 경험 그대로 |
| STT 변경의 `/answer` 효과 | 2: k6 + mock LLM | 켬 | 외부 API 잡음 제거 |
| STT 자체 처리량 | 3: 직접 호출 | 끔 | GPU 순수 성능, 최소 잡음 |

바깥(계층 1)일수록 현실에 가깝지만 잡음이 많고, 안쪽(계층 3)일수록 잡음이 없지만 현실과 멀다.
그래서 **바깥에서 "몇 명에서 터지나"를 잡고, 안쪽에서 "왜 터지나"를 좁힌다.**

---

## 스크립트 목록

### 상시 도구 (재사용)

| 파일 | 계층 | 하는 일 |
|---|---|---|
| `seed/seed.py` | 공통 | 테스트 유저 N명 + 구조화된 이력서 시딩, JWT 오프라인 발급 |
| `fixtures/make_audio.ps1` | 공통 | 한국어 TTS 답변 오디오(webm) 생성 |
| `scenarios/*.js` + `run.ps1` | 1 | k6 부하 시나리오 (면접 완주 / 답변 버스트 / 영상 소켓) |
| `mock/serve_mocked.py` | 2 | LLM 가짜(고정 지연) 서버 런처 |
| `mock/bench_stt.py` | 3 | STT만 동시 N개로 직접 호출 → 순수 처리량 |

### 병목 규명용 프로파일링/실험

| 파일 | 하는 일 |
|---|---|
| `mock/probe_gpu.py` | 한 건의 STT를 CPU/GPU로 분해 (librosa / CUDA 이벤트 / PyTorch Profiler) |
| `mock/exp_concurrency.py` | 2스레드 vs 2프로세스 처리량 + VRAM 비교 (GIL이냐 GPU냐) |
| `mock/stt_worker.py` | 위 실험의 프로세스 워커 (프로세스마다 모델 1개) |
| `mock/exp_batch.py` | 배치 크기 1/2/4/8 처리량 + GPU 사용률 (배칭이 효과 있나) |

### 일회성 검증 프로브 (기록용, 재실행 불필요)

`mock/probe_capture.py`, `mock/probe_timestamp.py` 와 `bench_stt.py --split` 모드는
VAD 중복 제거를 **적용하기 전** 안전성을 확인하려고 쓴 프로브다. 앱에서 `_speech_spans`가
제거된 뒤로는 그 심볼을 참조하는 부분이 동작하지 않는다. 조사 기록으로만 남긴다
(결과는 [FINDINGS.md](FINDINGS.md)에 정리).

---

## 공통 실험 원칙

병목 규명 실험(계층 3)은 조건을 엄격히 맞춘다:

- **동일 오디오** (`fixtures/answer.webm`, 약 75초), 타이밍 구간 밖에서 미리 `librosa.load`
- **워밍업 후 측정** (첫 호출의 커널 컴파일 비용 제외)
- **각 방식 최소 10회**
- **세마포어 우회** (`_run_asr`는 `_INFERENCE_SLOTS`를 안 탄다) 또는 크게 설정
- **프로세스마다 모델 1개**, 두 프로세스 모두 동일 GPU(cuda:0)
- **개별 latency + 전체 wall time** 기록 → `throughput = 완료 수 / 전체 wall`
- **VRAM 확인** (프로세스-당-모델은 모델 메모리가 배로 든다 — 운영 구조 판단에 필요)

서버(계층 1·2)를 띄운 채 계층 3 실험을 돌리면 GPU를 나눠 쓰게 되므로, **실험 전 서버를 내려
GPU를 비운다.**
