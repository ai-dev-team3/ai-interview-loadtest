"""2프로세스 실험용 워커. 프로세스마다 모델 1개를 올린다.

조건:
  - 동일 오디오(미리 만든 wav), 미리 librosa.load 해서 같은 배열 재사용
  - 워밍업 후 측정, 타이밍 구간엔 generate 만
  - 세마포어 우회 (_run_asr 는 _INFERENCE_SLOTS 를 안 탄다)
  - 두 워커가 rendezvous 로 동시에 시작
  - 개별 latency(perf_counter) + 프로세스 loop 시작/끝(time.time, 프로세스 간 비교용)
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

BACK = Path(r"C:\Users\main\Desktop\ai-team3\ai_interview-main\back_tooktac")
sys.path.insert(0, str(BACK))
os.environ.setdefault("SENSEVOICE_MAX_CONCURRENCY", "8")

from dotenv import load_dotenv

load_dotenv(BACK / ".env")

import librosa
import torch

from app.services.stt.sensevoice import SAMPLE_RATE, _run_asr, get_models, warm_up


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--wav", required=True)
    ap.add_argument("--ready-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--nprocs", type=int, default=2)
    a = ap.parse_args()

    audio, _ = librosa.load(a.wav, sr=SAMPLE_RATE)
    warm_up()
    asr = get_models()

    for _ in range(a.warmup):
        _run_asr(asr, audio)
    torch.cuda.synchronize()
    vram_mb = torch.cuda.memory_allocated() / 1e6

    # rendezvous: 둘 다 준비됐을 때 동시에 시작
    rd = Path(a.ready_dir)
    (rd / f"ready_{a.id}").write_text("1")
    while len(list(rd.glob("ready_*"))) < a.nprocs:
        time.sleep(0.005)

    t_start = time.time()
    lat = []
    for _ in range(a.n):
        t = time.perf_counter()
        _run_asr(asr, audio)
        lat.append((time.perf_counter() - t) * 1000)
    t_end = time.time()

    json.dump(
        {"id": a.id, "t_start": t_start, "t_end": t_end, "lat": lat, "vram_mb": vram_mb},
        open(a.out, "w"),
    )


if __name__ == "__main__":
    main()
