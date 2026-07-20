# 실전 면접(/real-interview) 부하 테스트

`ai_interview-main` 백엔드의 **실전 면접 기능만** 부하 테스트한다. 앱 레포는 건드리지 않는다.

대상: `http://localhost:8000` (uvicorn 단일 워커) + MySQL 8
도구: k6 (`bin/k6.exe` — 아래 "준비"에서 내려받는다)
LLM/STT: **실제 API를 호출한다.** 토큰 비용이 실제로 발생한다.

> **문서**
> - [docs/METHODOLOGY.md](docs/METHODOLOGY.md) — 이 레포가 성능을 재는 방식 (서버 켬/끔 세 계층, 스크립트 목록, 실험 원칙)
> - [docs/FINDINGS.md](docs/FINDINGS.md) — 조사 결론 (병목 = STT, VAD 중복 제거 결과, 동시성/배치 실험, 최종 진단)

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

---

## 측정 결과 / 결론

측정 결과와 병목 조사 결론은 **[docs/FINDINGS.md](docs/FINDINGS.md)** 에 정리돼 있다
(동시 사용자 한계, STT VAD 중복 제거 before/after, 동시성·배치 실험, 최종 진단).
재는 방식은 [docs/METHODOLOGY.md](docs/METHODOLOGY.md) 참고.
