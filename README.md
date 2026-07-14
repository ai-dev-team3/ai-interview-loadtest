# 실전 면접(/real-interview) 부하 테스트

`ai_interview-main` 백엔드의 **실전 면접 기능만** 부하 테스트한다. 앱 레포는 건드리지 않는다.

대상: `http://localhost:8000` (uvicorn 단일 워커) + MySQL 8
도구: k6 (`bin/k6.exe` — 아래 "준비"에서 내려받는다)
LLM/STT: **실제 API를 호출한다.** 토큰 비용이 실제로 발생한다.

---

## 무엇을 재는가

한 명의 실전 면접은 이렇게 흘러간다. 이 흐름을 그대로 재현한다.

```
POST /real-interview/start                 첫 질문(고정, LLM 없음)
  질문마다 반복:
    준비 10초
    WS /ws/expression                      답변 내내 열려 있음, 5fps 랜드마크
    POST /real-interview/answer            webm 업로드 → ffmpeg → SenseVoice STT → LLM(다음 질문)
                                           ...무거운 분석은 백그라운드로 던져짐
POST /real-interview/closing               마지막 한마디 (STT만)
GET  /real-interview/analysis-status        백그라운드 분석이 다 끝날 때까지 폴링
```

종료 조건은 문항 수가 아니라 **시간**이다 (`plan.py`: 10분 예산, 안전 상한 15문항).

## 검증할 병목 가설

| | 가설 | 근거 | 검증 |
|---|---|---|---|
| **H1** | 영상 소켓이 DB 커넥션을 붙들어 동시 15명에서 풀이 마른다 | `video.py:100`이 소켓 열 때 `get_db()`로 Session을 잡고 끊길 때(:174)까지 안 놓는다. 풀은 기본값 5+10=15 (`database.py:10`) | `30_ws_only.js` |
| **H2** | 답변 fast-path가 스레드풀 4개로 막힌다 | `answer_pipeline.py`의 `_FAST_EXECUTOR` = `FAST_PATH_WORKERS`(기본 4). ffmpeg + STT가 여기서 돈다 | `20_answer_burst.js` |
| **H3** | 백그라운드 분석이 조용히 쌓인다 | `real_interview.py:146`이 무거운 분석(약 17초)을 `asyncio.create_task`로 던지고 바로 응답한다. `/answer`의 p95만 보면 서버가 멀쩡해 보인다 | `10_interview.js`의 `analysis_convergence` |

> **H1 주의**: SQLAlchemy `Session`은 **첫 쿼리에서야** 풀에서 커넥션을 꺼낸다(lazy). 프레임만 흘리는 동안에는 쿼리가 없으므로 커넥션을 안 쥐고 있을 수도 있다. 코드만 봐서는 단정할 수 없어 실측으로 판정한다.

## SLO (판정 기준)

`lib/thresholds.js`에 코드로 박혀 있다. k6가 통과/실패를 종료 코드로 알려준다.

| 대상 | 임계값 | 근거 |
|---|---|---|
| `POST /answer` | **p95 < 10s**, p99 < 15s | 우리가 정한 값이 아니다. `real_interview.py`의 첫 주석이 *"빠른 길 — 준비 시간 10초 예산"*이라고 못박고 있다. 넘으면 사용자는 준비 시간 없이 답변해야 한다 |
| `POST /start` | p95 < 2s | 이력서 구조화가 캐시돼 있으면 DB만 |
| `POST /closing` | p95 < 8s | ffmpeg + STT만 |
| `GET /analysis-status` | p95 < 300ms | 단순 count 쿼리 |
| WS 프레임 왕복 | p95 < 200ms | 실시간 피드백 |
| 분석 수렴 | 마지막 답변 후 60초 이내 | H3 |
| 전역 | 5xx = 0, 풀 고갈 = 0, checks > 99% | |

**동시 사용자 한계** = 위 임계값을 처음 깨는 동시 면접자 수.

---

## 실행 순서

### 1. 준비 (한 번만)

```powershell
# k6 (winget/choco 없이 릴리스 바이너리만 받는다)
New-Item -ItemType Directory -Force bin | Out-Null
Invoke-WebRequest "https://github.com/grafana/k6/releases/download/v1.3.0/k6-v1.3.0-windows-amd64.zip" -OutFile "$env:TEMP\k6.zip"
Expand-Archive "$env:TEMP\k6.zip" "$env:TEMP\k6x" -Force
Copy-Item (Get-ChildItem -Recurse -Filter k6.exe "$env:TEMP\k6x").FullName bin\k6.exe

# 테스트 유저 30명 + '구조화까지 끝난' 이력서 시딩, JWT 발급 -> seed/tokens.json
..\ai_interview-main\back_tooktac\.venv\Scripts\python.exe seed\seed.py -n 30

# 답변 오디오 픽스처 생성 (한국어 TTS -> webm, 약 75초)
.\fixtures\make_audio.ps1
```

이력서를 **구조화된 상태로** 넣는 이유: `/real-interview/start`가 `ensure_structured`를 부르는데, 비어 있으면 첫 요청마다 Gemini로 이력서를 분석한다. 그러면 면접 진행 지연에 이력서 분석 시간이 섞인다.

로그인을 타지 않고 JWT를 직접 발급하는 이유: bcrypt 검증(수십 ms, CPU 바운드)이 서버 CPU 프로파일을 오염시킨다.

### 2. 백엔드 기동

```powershell
cd ..\ai_interview-main\back_tooktac
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**워밍업이 끝난 뒤에 부하를 걸 것.** `main.py:71-72`가 임베딩 모델(약 6초)과 SenseVoice STT를 백그라운드 스레드로 올린다. 그 전에 때리면 첫 요청이 비정상적으로 느리게 찍힌다.

### 3. 스모크 (스크립트가 면접을 완주하는지)

```powershell
bin\k6.exe run -e MAX_ANSWERS=2 -e PREPARE_SECONDS=2 -e ANSWER_SECONDS=10 scenarios\00_smoke.js
```

### 4. 본편 — 동시 사용자 한계 찾기

```powershell
.\run.ps1 -Scenario 10_interview.js -Levels 5,10,15,20,30
```

VU 하나 = 면접자 한 명 = 면접 한 판(약 11분). 준비 10초/답변 75초를 **실제로 쉰다**. 압축하지 않는 이유는 영상 소켓이 열려 있는 '시간'과 분석이 쌓이는 '시간'이 병목의 핵심이라, 시간을 줄이면 그 병목이 안 보이기 때문이다. 레벨 하나에 12분 안팎이 걸린다.

`run.ps1`은 SLO를 처음 깨는 레벨에서 멈춘다. **그 지점이 답이다.**

### 5. 가설 격리

```powershell
.\run.ps1 -Scenario 20_answer_burst.js -Levels 1,2,4,8,16   # H2: 4를 넘을 때 p95가 계단처럼 뛰는가
.\run.ps1 -Scenario 30_ws_only.js -Levels 10,20,30          # H1: 소켓만으로 무관한 API가 죽는가
```

### 6. 병목 확정 (설정만 바꿔 재측정)

앱 코드는 고치지 않는다. 되돌릴 수 있는 설정만 바꿔 before/after를 비교한다.

- H2가 확인되면: `FAST_PATH_WORKERS=8` 환경변수로 서버를 다시 띄우고 4번을 재실행
- H1이 확인되면: `database.py`에 `pool_size=30, max_overflow=20, pool_pre_ping=True`를 임시로 주고 재실행 후 원복

---

## 결과 읽는 법

- `out/<시나리오>-vus<N>-<시각>.json` — k6 요약 (레벨별)
- `out/server.log` — 서버 로그. 커넥션 풀이 마르면 `QueuePool limit of size 5 overflow 10 reached`가 여기 찍힌다
- 커스텀 메트릭
  - `analysis_convergence` — 마지막 답변 → 분석 완료까지 (H3)
  - `db_pool_errors` — 커넥션 풀 고갈 (H1)
  - `ws_frame_rtt` — 영상 프레임 왕복

### 비용 주의

`next_question.py:101`의 다음 질문 생성은 **OpenAI gpt-4o가 primary**다(Gemini 아님). 그리고 `llm/factory.py`가 `with_fallbacks`로 묶어 놔서, 한쪽이 429를 뱉으면 **조용히 다른 쪽으로 폴백**한다. 지연 그래프에는 안 나타나면서 요금만 이중으로 나가고 "안 느려졌다"는 잘못된 결론이 나올 수 있다. 실행 후 OpenAI/Google 콘솔의 실제 호출 수를 대조할 것.

## 측정 결과 (2026-07-14, 로컬: RTX GPU + MySQL 8, uvicorn 단일 워커)

### 결론: 동시 사용자 한계는 3명. 병목은 SenseVoice STT의 GPU 추론 하나다.

실사용 페이스(준비 10초 / 답변 75초)로 면접을 완주시켰을 때:

| 동시 면접자 | `/answer` p95 | 판정 |
|---|---|---|
| 3명 | **8.57s** | SLO 통과 |
| 4명 | **10.36s** | 실패 (10초 예산 초과) |
| 5명 | **14.47s** | 실패 |

`/answer` 말고는 **아무것도 안 무너졌다.** 5명에서도 `start` 0.48s, `closing` 5.78s,
`analysis-status` 20ms, 영상 프레임 왕복 15ms, 백그라운드 분석 수렴 15.8초(기준 60초),
**5xx 0건, 커넥션 풀 고갈 0건, checks 실패 0건.**

### 가설 검증 결과

| | 가설 | 결과 |
|---|---|---|
| H1 | 영상 소켓이 DB 커넥션을 붙들어 풀이 마른다 | **기각.** 풀 고갈 0건. SQLAlchemy Session은 첫 쿼리에서야 커넥션을 꺼내는데(lazy), 프레임 스트리밍 중엔 쿼리가 없다. 소켓은 공짜에 가깝다 (프레임 왕복 15ms) |
| H2 | fast-path 스레드풀 4개가 캡이다 | **부분 확인, 다만 진범이 아니다.** 진짜 캡은 `sensevoice.py:44`의 `SENSEVOICE_MAX_CONCURRENCY=2` 세마포어다 |
| H3 | 백그라운드 분석이 조용히 쌓인다 | **기각.** 5명에서도 마지막 답변 후 15.8초면 수렴한다 |

### /answer 3.4초의 내역 (동시 1명)

```
업로드 + ffmpeg   ~0.5s
SenseVoice STT    ~2.0s   <- 동시성이 늘면 여기만 늘어난다 (5명이면 평균 3.9s)
다음 질문 LLM     ~2.0s   <- 동시성과 무관 (5명에서도 평균 2.0s)
```

둘은 직렬일 수밖에 없다 — 꼬리질문을 만들려면 답변 텍스트가 먼저 있어야 한다.
줄일 수 있는 건 STT뿐이다.

`sensevoice.py`의 주석은 "70초 오디오 → 약 0.8초 (RTF 0.01)"라고 적고 있지만,
실측은 **1명일 때도 1.5~2.2초**다.

### GPU는 직렬화된다 (동시성이 늘면 지연이 선형 증가)

`/answer`만 동시에 때렸을 때 (`20_answer_burst.js`, 답변 3개씩):

| 동시 | p95 | 1명 대비 |
|---|---|---|
| 1 | 3.45s | 1× |
| 2 | 7.92s | 2.3× |
| 3 | 12.04s | 3.5× |
| 4 | 24.06s | 7× |
| 8 | 38.29s | 11× |

스레드풀이 4개 워커면 4명까지는 평평해야 하는데 그렇지 않다. 처리량 천장이
**약 0.3 답변/초**로 고정돼 있고, 지연은 그냥 대기열 길이다.

### 안 통한 것

- **세마포어 2 → 4** (`SENSEVOICE_MAX_CONCURRENCY=4`): 동시 4명 p95 24.06s → 16.24s로
  나아지지만 여전히 선형이다. GPU가 직렬이라 동시 실행 허용치를 늘려도 같은 GPU를
  나눠 쓸 뿐이다. (표본이 작아 편차가 크다 — VU당 답변 3개)
- **uvicorn 워커 늘리기**: 워커마다 모델을 하나씩 올려 VRAM이 터진다.
- **커넥션 풀 / 스레드풀 튜닝**: 애초에 병목이 아니었다.

---

## LLM은 이제 부르지 않는다 (고정 2.0초로 가정)

**측정값: 다음 질문 생성 LLM = 평균 2.0초.** 동시 1명에서 1.6~2.8초, 동시 5명에서도 평균 2.0초로
**동시성과 무관했다.** 외부 API는 병목이 아니다.

그러니 실제로 부를 이유가 없다. 부르면 토큰 비용만 들고, 외부 API의 편차가 측정에 섞인다.
`mock/serve_mocked.py`가 LLM 호출을 그 시간만큼 자는 것으로 대체한다.

```powershell
..\ai_interview-main\back_tooktac\.venv\Scripts\python.exe mock\serve_mocked.py   # LLM = 2.0초
$env:LLM_DELAY_SECONDS=0; ... mock\serve_mocked.py                                # LLM 시간을 아예 뺀다
```

가짜로 바꾸는 것은 **LLM 호출 세 군데뿐이다** (`NextQuestionAgent.generate`,
`ModelAnswerGenerator`, `AnswerEvaluator`). ffmpeg·SenseVoice STT·VAD·피치 분석·임베딩
유사도·DB·영상 소켓은 전부 진짜 그대로 돈다. 앱 코드는 건드리지 않는다 — 런처에서 패치한다.

## STT만 보면 (`mock/bench_stt.py`)

HTTP를 통해 재면 백그라운드 분석(임베딩 유사도, 피치)이 같은 프로세스에서 같이 돌아 STT
시간에 섞인다. 그래서 `SenseVoiceClient.transcribe`만 직접 동시 N개로 때렸다.
75초짜리 답변 오디오 기준:

| 동시 | 1건 평균 | 최대 | 전체 시간 | **처리량** |
|---|---|---|---|---|
| 1 | 1.38s | 1.38s | 1.38s | **0.72건/초** |
| 2 | 3.06s | 3.07s | 3.07s | **0.65건/초** |
| 3 | 3.44s | 4.33s | 4.33s | **0.69건/초** |
| 4 | 4.56s | 6.10s | 6.10s | **0.66건/초** |
| 8 | 7.61s | 12.23s | 12.24s | **0.65건/초** |

**처리량이 동시성과 무관하게 0.65~0.72건/초로 못 박혀 있다.** GPU가 완전히 직렬이라는 뜻이다.
동시에 몇 명이 오든 초당 0.7건만 처리하고 나머지는 줄을 선다. 세마포어가 2를 허용하든 4를
허용하든 처리량이 그대로였던 이유가 이것이다 — 허용치를 늘려도 같은 GPU를 나눠 쓸 뿐이다.

**한 건의 GPU 시간은 1.4초다.** 그런데 HTTP 경로에서 STT는 1.5~2.2초(1명), 3.9초(5명)로 찍혔다.

### 시도해보고 버린 가설: "백그라운드 임베딩이 같은 GPU를 뺏는다"

`scorer.py`의 유사도 모델 중 `paraphrase-multilingual-mpnet-base-v2`가 `SentenceTransformer`로
로드되면서 **같은 GPU(cuda:0)에 올라가는 것은 사실이다** (기동 로그: `No device provided,
using cuda:0`). 그래서 답변마다 백그라운드로 도는 임베딩이 STT의 GPU를 뺏는다고 의심했다.

**틀렸다. 재봤더니 차이가 없다.** `EMBED_DEVICE=cpu`로 임베딩만 CPU로 내리고 같은 조건
(LLM 2.0초 고정)에서 A/B로 쟀다:

| 동시 | BEFORE (임베딩 GPU) | AFTER (임베딩 CPU) |
|---|---|---|
| 1명 | p95 5.48s | p95 5.26s |
| 2명 | p95 7.11s | p95 7.82s |
| 3명 | p95 13.62s | p95 14.11s |
| 4명 | p95 16.24s | p95 15.72s |

노이즈 수준이다. 임베딩을 GPU에서 내려도 `/answer`는 빨라지지 않는다.
(`mock/serve_mocked.py`의 `EMBED_DEVICE`로 언제든 다시 확인할 수 있다.)

### LLM 시간은 실제로 /answer 에 더해진다 (앞선 오독 정정)

한때 "LLM 지연을 0으로 만들어도 `/answer`가 안 줄었다(3.37초 → 3.45초)"고 적었는데,
**서로 다른 서버 인스턴스의 값을 비교한 잘못된 대조였다.** 같은 mock 서버에서 조건만 바꾸면:

| | 동시 1명 | 동시 4명 |
|---|---|---|
| LLM 2.0초 | 4.48s | 13.59s |
| LLM 0초 | 3.45s | 12.70s |

LLM을 통째로 없애면 약 1초가 줄어든다(2초를 다 돌려받지는 못한다 — 동시성이 있으면 다른
요청의 STT와 겹쳐 일부가 상쇄된다). **`/answer` 시간의 대부분은 여전히 STT 대기다.**

### 그래서 예산은 이렇게 쓰인다 (10초 안에 끝나야 한다)

```
업로드 + ffmpeg    ~0.5s
STT (GPU 1.4초)    동시 N명이면 대기까지 N × 1.4초 (처리량 0.7건/초가 천장)
다음 질문 LLM      2.0s   <- 고정. 줄일 수 없고, 줄여도 의미 없다(위 참고)
```

즉 STT에 쓸 수 있는 예산은 약 **7.5초**뿐이고, GPU는 초당 0.7건만 뱉는다.

### 개선 방향 (미적용 — 팀 논의용)

1. **답변하는 동안 미리 전사한다.** 지금은 사용자가 90초 동안 말하는 내내 서버가 놀다가,
   끝난 순간 75초짜리 오디오를 통째로 GPU에 던진다. 그래서 10초 예산 안에 75초치 추론을
   해야 한다. 청크로 흘려보내며 미리 전사하면 종료 시점엔 마지막 몇 초만 남고, GPU 부하도
   90초에 걸쳐 분산돼 동시성 문제까지 같이 풀린다.
   (주의: `sensevoice.py` 주석대로 3초짜리 조각은 띄어쓰기를 깨뜨린다. 조각을 20~30초로
   크게 잡거나, 스트리밍은 예열용으로만 쓰고 최종 텍스트는 통짜로 다시 뽑아야 한다.)
2. **VAD를 두 번 돌리고 있다.** `asr`에 `vad_model="fsmn-vad"`가 붙어 있어 `asr.generate`
   내부에서 VAD가 돌고, `_speech_spans`에서 같은 오디오에 `vad.generate`를 또 돌린다
   (말속도용 구간을 얻으려고). 중복 제거 + fp16 추론으로 통짜 추론 시간을 줄일 여지가 있다.
3. 그래도 GPU 한 장의 처리량 천장은 남는다. 동시 접속 대기열을 두거나 STT를 별도 워커/장비로
   빼는 결정이 필요하다.

### 비용

이번 측정에서 다음 질문 생성 LLM(OpenAI gpt-4o)을 100회 남짓 호출했다. 지연은 동시성과
무관하게 평균 2.0초로 일정했다 — 외부 API는 병목이 아니다.
