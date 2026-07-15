"""한 건의 STT 1초 중 실제로 GPU가 몇 초인가.

"GPU가 직렬이라 동시 처리가 안 된다"는 가설을 확정하려면, 애초에 그 1초가 GPU 일인지부터
봐야 한다. FunASR 파이프라인은 CPU·파이썬(librosa, fbank, VAD 청킹, 토크나이즈, 후처리)
비중이 크다. 그게 크면 GIL 때문에 동시 처리가 안 되는 것이고, GPU는 죄가 없다.

세 가지를 잰다:
  1) librosa.load        순수 CPU (오디오 디코드/리샘플)
  2) CUDA 이벤트 구간     generate 동안 GPU 스트림의 첫~끝 구간 (유휴 포함, 참고용)
  3) 프로파일러 분해      CUDA 커널 활성 시간 vs CPU 시간  <- 결정적 숫자
"""
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BACK = Path(r"C:\Users\main\Desktop\ai-team3\ai_interview-main\back_tooktac")
sys.path.insert(0, str(BACK))

from dotenv import load_dotenv

load_dotenv(BACK / ".env")

import librosa
import torch
from torch.profiler import ProfilerActivity, profile

from app.services.stt.sensevoice import SAMPLE_RATE, _run_asr, get_models, warm_up

WEBM = Path(__file__).resolve().parents[1] / "fixtures" / "answer.webm"
N = 5


def main() -> None:
    wav = Path(tempfile.gettempdir()) / "loadtest_gpu.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(WEBM), "-ar", "16000", "-ac", "1", str(wav)],
        check=True,
    )

    warm_up()
    asr = get_models()

    # 1) librosa 로드 (순수 CPU)
    load_ms = []
    for _ in range(N):
        t = time.perf_counter()
        audio, _sr = librosa.load(str(wav), sr=SAMPLE_RATE)
        load_ms.append((time.perf_counter() - t) * 1000)

    # 워밍업 (커널 컴파일)
    _run_asr(asr, audio)
    _run_asr(asr, audio)

    # 2) CUDA 이벤트: generate 동안 GPU 스트림 구간 + wall
    wall_ms, gpu_span_ms = [], []
    for _ in range(N):
        torch.cuda.synchronize()
        s = torch.cuda.Event(enable_timing=True)
        e = torch.cuda.Event(enable_timing=True)
        t = time.perf_counter()
        s.record()
        _run_asr(asr, audio)
        e.record()
        torch.cuda.synchronize()
        wall_ms.append((time.perf_counter() - t) * 1000)
        gpu_span_ms.append(s.elapsed_time(e))

    # 3) 프로파일러: CUDA 커널 활성 시간 vs CPU 시간 (결정적)
    torch.cuda.synchronize()
    with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
        _run_asr(asr, audio)
        torch.cuda.synchronize()

    ka = prof.key_averages()

    def field(x, *names):
        for n in names:
            v = getattr(x, n, None)
            if v:
                return v
        return 0

    cuda_us = sum(field(x, "self_device_time_total", "self_cuda_time_total") for x in ka)
    cpu_us = sum(x.self_cpu_time_total for x in ka)

    print("\n=== 한 건 STT 분해 (75초 오디오, %d회 평균) ===" % N)
    print(f"librosa.load (CPU)        {statistics.mean(load_ms):7.1f} ms")
    print(f"generate wall             {statistics.mean(wall_ms):7.1f} ms")
    print(f"  CUDA 이벤트 스트림 구간  {statistics.mean(gpu_span_ms):7.1f} ms  (유휴 포함, 참고용)")
    print()
    print("=== 프로파일러 (generate 1회) ===")
    print(f"CUDA 커널 활성 시간        {cuda_us/1000:7.1f} ms  <- 실제 GPU 일")
    print(f"CPU 시간(self 합)          {cpu_us/1000:7.1f} ms")
    wall = statistics.mean(wall_ms)
    print()
    print(f"해석: generate {wall:.0f}ms 중 GPU 커널이 실제로 도는 시간 ≈ {cuda_us/1000:.0f}ms "
          f"({cuda_us/1000/wall*100:.0f}%)")

    print("\n=== 상위 연산 (CUDA 시간 순) ===")
    print(prof.key_averages().table(sort_by="self_cuda_time_total", row_limit=8))


if __name__ == "__main__":
    main()
