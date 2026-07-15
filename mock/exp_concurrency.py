"""2스레드 vs 2프로세스 — 동시 STT 처리량을 같은 조건에서 비교한다.

GIL/세마포어는 프로세스 단위다. 프로세스로 쪼갰을 때 처리량이 뛰면 범인은 CPU/GIL,
그대로면 GPU/드라이버가 진짜 직렬 자원이다.

    python mock/exp_concurrency.py            # 2 워커, 각 10회
    python mock/exp_concurrency.py --n 15

공통 조건: 동일 wav, 워밍업 후, 각 방식 (2 워커 × n)회, 세마포어 우회,
프로세스마다 모델 1개, 같은 GPU(cuda:0). throughput = 완료 수 / 전체 wall.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from statistics import mean, median

HERE = Path(__file__).resolve().parent
BACK = Path(r"C:\Users\main\Desktop\ai-team3\ai_interview-main\back_tooktac")
PY = str(BACK / ".venv" / "Scripts" / "python.exe")
WEBM = HERE.parent / "fixtures" / "answer.webm"


def make_wav() -> str:
    wav = Path(tempfile.gettempdir()) / "loadtest_exp.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(WEBM), "-ar", "16000", "-ac", "1", str(wav)],
        check=True,
    )
    return str(wav)


class VramPoller:
    """nvidia-smi 로 GPU 총 사용 메모리(MB) 최대치를 0.2초마다 기록한다."""

    def __init__(self):
        self.peak = 0
        self._stop = False
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop:
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                )
                self.peak = max(self.peak, int(out.stdout.strip().splitlines()[0]))
            except Exception:
                pass
            time.sleep(0.2)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop = True
        self._t.join(timeout=1)


def run_threads(wav: str, warmup: int, n: int) -> dict:
    """한 프로세스, 모델 하나 공유, 스레드 2개가 동시에 generate."""
    import librosa
    import torch

    sys.path.insert(0, str(BACK))
    from app.services.stt.sensevoice import SAMPLE_RATE, _run_asr, get_models, warm_up

    audio, _ = librosa.load(wav, sr=SAMPLE_RATE)
    warm_up()
    asr = get_models()
    for _ in range(warmup):
        _run_asr(asr, audio)
    torch.cuda.synchronize()
    vram_mb = torch.cuda.memory_allocated() / 1e6

    barrier = threading.Barrier(2)
    results = {}

    def work(i):
        barrier.wait()
        t_start = time.time()
        lat = []
        for _ in range(n):
            t = time.perf_counter()
            _run_asr(asr, audio)
            lat.append((time.perf_counter() - t) * 1000)
        results[i] = {"t_start": t_start, "t_end": time.time(), "lat": lat, "vram_mb": vram_mb}

    with VramPoller() as vp:
        threads = [threading.Thread(target=work, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    return _summarize("2스레드 (모델 1개 공유)", list(results.values()), n, vp.peak)


def run_procs(wav: str, warmup: int, n: int) -> dict:
    """프로세스 2개, 각자 모델 1개, 같은 GPU."""
    ready = Path(tempfile.mkdtemp(prefix="stt_ready_"))
    outs = [ready / f"out_{i}.json" for i in range(2)]

    with VramPoller() as vp:
        procs = [
            subprocess.Popen([
                PY, str(HERE / "stt_worker.py"),
                "--id", str(i), "--wav", wav, "--ready-dir", str(ready),
                "--out", str(outs[i]), "--warmup", str(warmup), "--n", str(n), "--nprocs", "2",
            ])
            for i in range(2)
        ]
        for p in procs:
            p.wait()

    data = [json.load(open(o)) for o in outs]
    return _summarize("2프로세스 (모델 각 1개)", data, n, vp.peak)


def _summarize(name: str, workers: list, n: int, vram_peak: int) -> dict:
    wall = max(w["t_end"] for w in workers) - min(w["t_start"] for w in workers)
    total = sum(len(w["lat"]) for w in workers)
    all_lat = [x for w in workers for x in w["lat"]]
    return {
        "name": name,
        "wall": wall,
        "throughput": total / wall,
        "total": total,
        "lat_mean": mean(all_lat),
        "lat_median": median(all_lat),
        "per_worker": [(mean(w["lat"]), median(w["lat"])) for w in workers],
        "vram_alloc_mb": [round(w["vram_mb"]) for w in workers],
        "vram_peak_mb": vram_peak,
    }


def show(r: dict) -> None:
    print(f"\n=== {r['name']} ===")
    print(f"완료 추론: {r['total']}건 | 전체 wall: {r['wall']:.2f}s | 처리량: {r['throughput']:.2f} 건/초")
    print(f"개별 latency  평균 {r['lat_mean']:.0f}ms  중앙 {r['lat_median']:.0f}ms")
    for i, (m, md) in enumerate(r["per_worker"]):
        print(f"  워커 {i}: 평균 {m:.0f}ms  중앙 {md:.0f}ms")
    print(f"VRAM  torch alloc {r['vram_alloc_mb']} MB  | GPU 총 사용 peak {r['vram_peak_mb']} MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--only", choices=["threads", "procs"])
    a = ap.parse_args()

    wav = make_wav()
    import os
    print(f"CPU 코어: {os.cpu_count()} | 워커 2개 × {a.n}회 | 워밍업 {a.warmup}회")

    results = []
    if a.only in (None, "threads"):
        results.append(run_threads(wav, a.warmup, a.n))
    if a.only in (None, "procs"):
        results.append(run_procs(wav, a.warmup, a.n))

    for r in results:
        show(r)

    if len(results) == 2:
        t, p = results
        print("\n=== 비교 ===")
        print(f"처리량: 스레드 {t['throughput']:.2f} -> 프로세스 {p['throughput']:.2f} 건/초 "
              f"({(p['throughput']/t['throughput']-1)*100:+.0f}%)")
        print(f"VRAM peak: 스레드 {t['vram_peak_mb']} MB -> 프로세스 {p['vram_peak_mb']} MB "
              f"({p['vram_peak_mb']-t['vram_peak_mb']:+d} MB)")


if __name__ == "__main__":
    main()
