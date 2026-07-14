"""SenseVoice STT만 직접 재는 벤치. HTTP도 DB도 LLM도 끼지 않는다.

/answer 를 통해 재면 백그라운드 분석(임베딩 유사도 약 3 CPU-초, 피치)이 같은 프로세스에서
같이 돌아 STT 시간에 CPU 경합이 섞인다. 여기서는 앱의 SenseVoiceClient.transcribe 만
동시 N개로 때려 순수한 STT 처리량과 직렬화 정도를 본다.

    python mock\bench_stt.py                # 동시 1, 2, 3, 4, 8
    python mock\bench_stt.py --levels 1,2   # 원하는 동시성만
"""
import argparse
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACK = Path(r"C:\Users\main\Desktop\ai-team3\ai_interview-main\back_tooktac")
sys.path.insert(0, str(BACK))

from dotenv import load_dotenv

load_dotenv(BACK / ".env")

from app.services.stt.sensevoice import MAX_CONCURRENT_INFERENCE, SenseVoiceClient, warm_up

WEBM = Path(__file__).resolve().parents[1] / "fixtures" / "answer.webm"


def to_wav(webm: Path) -> str:
    wav = Path(tempfile.gettempdir()) / "loadtest_answer.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-ar", "16000", "-ac", "1", str(wav)],
        check=True,
    )
    return str(wav)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--levels", default="1,2,3,4,8")
    args = parser.parse_args()

    wav = to_wav(WEBM)
    client = SenseVoiceClient()

    print("모델 로딩...")
    warm_up()
    client.transcribe(wav)  # 첫 호출의 커널 컴파일 비용을 여기서 털어낸다

    print(f"\n오디오 {WEBM.name} (약 75초) | 세마포어 상한 = {MAX_CONCURRENT_INFERENCE}\n")
    print(f"{'동시':>4} | {'평균':>7} | {'최대':>7} | {'전체시간':>8} | {'처리량':>10}")
    print("-" * 52)

    for level in [int(x) for x in args.levels.split(",")]:
        def one(_):
            started = time.perf_counter()
            client.transcribe(wav)
            return time.perf_counter() - started

        wall_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=level) as pool:
            times = list(pool.map(one, range(level)))
        wall = time.perf_counter() - wall_start

        print(
            f"{level:>4} | {statistics.mean(times):>6.2f}s | {max(times):>6.2f}s | "
            f"{wall:>7.2f}s | {level / wall:>6.2f}건/초"
        )


if __name__ == "__main__":
    main()
