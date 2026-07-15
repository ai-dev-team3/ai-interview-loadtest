"""아이디어 A 검증: asr 내부 VAD 구간을 가로챈 값이 기존 별도 VAD와 같은가.

같으면 -> 앱 코드를 고쳐도 말속도 점수가 그대로 보존된다 (안전).
다르면 -> merge_vad 등 차이가 있다는 뜻. 그때 원인을 봐야 한다.

앱 코드는 건드리지 않는다. 여기서 asr 객체에만 임시로 wrapper 를 건다.
"""
import sys
import threading
import time
from pathlib import Path

BACK = Path(r"C:\Users\main\Desktop\ai-team3\ai_interview-main\back_tooktac")
sys.path.insert(0, str(BACK))

from dotenv import load_dotenv

load_dotenv(BACK / ".env")

import librosa

from app.services.stt.sensevoice import _run_asr, _speech_spans, get_models, warm_up

WEBM = Path(__file__).resolve().parents[1] / "fixtures" / "answer.webm"

_captured = threading.local()


def install_capture(asr):
    """asr 내부 VAD 호출을 감싸 구간을 스레드-로컬에 기록한다."""
    original = asr.vad_model.inference

    def wrapper(*args, **kwargs):
        results, meta = original(*args, **kwargs)
        try:
            _captured.spans = [(int(s), int(e)) for s, e in results[0]["value"]]
        except (IndexError, KeyError, TypeError, ValueError):
            _captured.spans = []
        return results, meta

    asr.vad_model.inference = wrapper


def main() -> None:
    import subprocess
    import tempfile

    wav = Path(tempfile.gettempdir()) / "loadtest_cap.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(WEBM), "-ar", "16000", "-ac", "1", str(wav)],
        check=True,
    )

    warm_up()
    vad, asr = get_models()
    audio, _ = librosa.load(str(wav), sr=16000)

    # (1) 기존 방식: 별도 VAD 패스
    standalone = _speech_spans(vad, audio)

    # (2) 제안 방식: asr 내부 VAD 를 가로챈다
    install_capture(asr)
    _captured.spans = []
    text = _run_asr(asr, audio)
    captured = getattr(_captured, "spans", [])

    print("=== 구간 개수 ===")
    print(f"기존(별도 VAD):   {len(standalone)}개")
    print(f"제안(가로챈 값):  {len(captured)}개")

    s_sum = sum(e - s for s, e in standalone)
    c_sum = sum(e - s for s, e in captured)
    print("\n=== 발화 길이 합 (말속도의 분모) ===")
    print(f"기존:  {s_sum/1000:.3f}s")
    print(f"제안:  {c_sum/1000:.3f}s")
    print(f"차이:  {abs(s_sum - c_sum)/1000:.3f}s  ({abs(s_sum - c_sum) / max(s_sum,1) * 100:.2f}%)")

    print("\n=== 구간 값 (앞 5개) ===")
    print(f"기존:  {standalone[:5]}")
    print(f"제안:  {captured[:5]}")
    print(f"\n완전 일치: {standalone == captured}")

    # 비용 재확인: 제안 방식은 별도 VAD 호출이 없다
    n = 5
    t = time.perf_counter()
    for _ in range(n):
        _run_asr(asr, audio)  # wrapper 가 걸린 상태 = 내부에서 VAD 도 돈다
    asr_only = (time.perf_counter() - t) / n
    t = time.perf_counter()
    for _ in range(n):
        _speech_spans(vad, audio)
    vad_only = (time.perf_counter() - t) / n
    print(f"\n=== 비용 (5회 평균) ===")
    print(f"제안(asr만, VAD 내장):   {asr_only:.3f}s")
    print(f"기존 추가분(별도 VAD):   {vad_only:.3f}s  <- 이만큼 사라진다")
    print(f"절감:  {vad_only/(asr_only+vad_only)*100:.1f}%")


if __name__ == "__main__":
    main()
