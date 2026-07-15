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


def split(wav: str, repeat: int) -> None:
    """한 건의 내부를 쪼개 잰다.

    sensevoice.py 는 같은 오디오에 VAD 를 두 번 돌린다.
      asr.generate  — 내부에서 VAD 로 끊고 조각별 ASR 을 돌린 뒤 합친다
      vad.generate  — 말속도용 발화 구간(합)을 얻으려고 같은 오디오에 VAD 를 또 돌린다
    두 번째가 한 건에서 몇 %인지 알아야 없앨 가치가 있는지 판단할 수 있다.
    """
    import librosa

    from app.services.stt.sensevoice import _run_asr, _speech_spans, get_models

    vad, asr = get_models()
    load_t, asr_t, vad_t = [], [], []

    for _ in range(repeat):
        t0 = time.perf_counter()
        audio, _sr = librosa.load(wav, sr=16000)
        t1 = time.perf_counter()
        _run_asr(asr, audio)
        t2 = time.perf_counter()
        _speech_spans(vad, audio)
        t3 = time.perf_counter()

        load_t.append(t1 - t0)
        asr_t.append(t2 - t1)
        vad_t.append(t3 - t2)

    total = statistics.mean(load_t) + statistics.mean(asr_t) + statistics.mean(vad_t)
    print(f"\n한 건의 내부 ({repeat}회 평균) | 오디오 약 75초\n")
    print(f"{'구간':<26} {'시간':>8}  {'비중':>6}")
    print("-" * 44)
    for name, times in (
        ("librosa.load (CPU)", load_t),
        ("asr.generate (GPU, VAD 포함)", asr_t),
        ("vad.generate (GPU, 두 번째)", vad_t),
    ):
        avg = statistics.mean(times)
        print(f"{name:<26} {avg:>7.3f}s  {avg / total * 100:>5.1f}%")
    print("-" * 44)
    print(f"{'합계':<26} {total:>7.3f}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--levels", default="1,2,3,4,8")
    parser.add_argument("--split", type=int, default=0, help="한 건의 내부를 N회 반복해 쪼개 잰다")
    args = parser.parse_args()

    wav = to_wav(WEBM)
    client = SenseVoiceClient()

    print("모델 로딩...")
    warm_up()
    client.transcribe(wav)  # 첫 호출의 커널 컴파일 비용을 여기서 털어낸다

    if args.split:
        split(wav, args.split)
        return

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
