"""배치 크기 1 vs 2 vs 4 vs 8 — 묶으면 GPU 여유(놀던 37%)를 쓰는가.

같은 총량(8건)을 배치 크기만 바꿔 처리한다.
  배치 1: generate 8번, 각 1개
  배치 2: generate 4번, 각 [audio, audio]
  배치 4: generate 2번, 각 [audio]*4
  배치 8: generate 1번, [audio]*8

throughput = 8 / wall. 배치가 효과 있으면 클수록 처리량↑, GPU util↑.
GPU util(사용률)을 같이 재서 노는 코어를 정말 채우는지 본다.
"""
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

BACK = Path(r"C:\Users\main\Desktop\ai-team3\ai_interview-main\back_tooktac")
sys.path.insert(0, str(BACK))

from dotenv import load_dotenv

load_dotenv(BACK / ".env")

import librosa
import torch

from app.services.stt.sensevoice import SAMPLE_RATE, get_models, warm_up

WEBM = Path(__file__).resolve().parents[1] / "fixtures" / "answer.webm"
TOTAL = 8


class GpuPoller:
    """nvidia-smi 로 GPU 사용률(%)과 메모리(MB)를 0.1초마다 기록."""

    def __init__(self):
        self.util, self.mem = [], []
        self._stop = False
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop:
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                )
                u, m = out.stdout.strip().splitlines()[0].split(",")
                self.util.append(int(u))
                self.mem.append(int(m))
            except Exception:
                pass
            time.sleep(0.1)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop = True
        self._t.join(timeout=1)

    def stats(self):
        busy = [u for u in self.util if u > 0]
        return {
            "util_mean": statistics.mean(busy) if busy else 0,
            "util_peak": max(self.util) if self.util else 0,
            "mem_peak": max(self.mem) if self.mem else 0,
        }


def run_batch(asr, audio, batch: int) -> dict:
    calls = [[audio] * batch for _ in range(TOTAL // batch)]

    with GpuPoller() as gp:
        t0 = time.perf_counter()
        for chunk in calls:
            asr.generate(input=chunk, fs=SAMPLE_RATE, language="ko", use_itn=True)
        wall = time.perf_counter() - t0
    s = gp.stats()
    return {
        "batch": batch,
        "calls": len(calls),
        "wall": wall,
        "throughput": TOTAL / wall,
        **s,
    }


def main() -> None:
    wav = Path(tempfile.gettempdir()) / "loadtest_batch.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(WEBM), "-ar", "16000", "-ac", "1", str(wav)],
        check=True,
    )

    warm_up()
    asr = get_models()
    audio, _ = librosa.load(str(wav), sr=SAMPLE_RATE)

    # 워밍업
    asr.generate(input=[audio], fs=SAMPLE_RATE, language="ko", use_itn=True)
    asr.generate(input=[audio, audio], fs=SAMPLE_RATE, language="ko", use_itn=True)

    print(f"총 {TOTAL}건을 배치 크기만 바꿔 처리 | 오디오 75초 × {TOTAL}\n")
    print(f"{'배치':>4} {'호출수':>5} {'wall':>7} {'처리량':>9} {'GPU평균':>8} {'GPU피크':>7} {'VRAM피크':>8}")
    print("-" * 56)

    rows = []
    for b in (1, 2, 4, 8):
        r = run_batch(asr, audio, b)
        rows.append(r)
        print(f"{r['batch']:>4} {r['calls']:>5} {r['wall']:>6.2f}s "
              f"{r['throughput']:>6.2f}건/초 {r['util_mean']:>6.0f}% {r['util_peak']:>6.0f}% "
              f"{r['mem_peak']:>6d}MB")

    base = rows[0]["throughput"]
    print("\n=== 배치 1 대비 처리량 ===")
    for r in rows:
        print(f"배치 {r['batch']}: {r['throughput']:.2f} 건/초 ({(r['throughput']/base-1)*100:+.0f}%)")


if __name__ == "__main__":
    main()
