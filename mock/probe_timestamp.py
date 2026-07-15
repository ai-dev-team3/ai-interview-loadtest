"""output_timestamp=True 가 (1) 실제로 타임스탬프를 내는가, (2) 두 번째 VAD보다 싼가,
(3) 말속도(발화 길이)가 기존과 얼마나 다른가를 잰다.

기존:   asr.generate(...)  +  vad.generate(...)   -> 발화 길이 = VAD 구간 합
제안:   asr.generate(..., output_timestamp=True)  -> 발화 길이 = 단어 타임스탬프 기반
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

from app.services.stt.sensevoice import _speech_spans, get_models, warm_up

WEBM = Path(__file__).resolve().parents[1] / "fixtures" / "answer.webm"


def to_wav() -> str:
    wav = Path(tempfile.gettempdir()) / "loadtest_probe.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(WEBM), "-ar", "16000", "-ac", "1", str(wav)],
        check=True,
    )
    return str(wav)


def main() -> None:
    warm_up()
    vad, asr = get_models()
    audio, _ = librosa.load(to_wav(), sr=16000)

    # 워밍업 (커널 컴파일 비용 제거)
    asr.generate(input=audio, fs=16000, language="ko", use_itn=True)
    asr.generate(input=audio, fs=16000, language="ko", use_itn=True, output_timestamp=True)

    # --- 반환 형식 확인 ---
    r = asr.generate(input=audio, fs=16000, language="ko", use_itn=True, output_timestamp=True)[0]
    ts = r.get("timestamp")
    print("=== output_timestamp 반환 ===")
    print("키:", list(r.keys()))
    print("timestamp 개수:", len(ts) if ts else ts)
    if ts:
        print("timestamp 예시(앞 3개, ms):", ts[:3])

    # --- 비용 비교 (각 5회) ---
    base, tstamp, vadonly = [], [], []
    for _ in range(5):
        t = time.perf_counter(); asr.generate(input=audio, fs=16000, language="ko", use_itn=True); base.append(time.perf_counter() - t)
        t = time.perf_counter(); asr.generate(input=audio, fs=16000, language="ko", use_itn=True, output_timestamp=True); tstamp.append(time.perf_counter() - t)
        t = time.perf_counter(); _speech_spans(vad, audio); vadonly.append(time.perf_counter() - t)

    b, ts_, v = statistics.mean(base), statistics.mean(tstamp), statistics.mean(vadonly)
    print("\n=== 비용 (5회 평균) ===")
    print(f"asr.generate (기본)                 {b:.3f}s")
    print(f"asr.generate + output_timestamp     {ts_:.3f}s   (+{ts_ - b:.3f}s)")
    print(f"vad.generate (두 번째 패스, 지금)   {v:.3f}s")
    print(f"\n지금 총합:  asr {b:.3f} + vad {v:.3f} = {b + v:.3f}s")
    print(f"제안 총합:  asr+ts {ts_:.3f}s")
    print(f"절감:       {(b + v) - ts_:.3f}s  ({((b + v) - ts_) / (b + v) * 100:.1f}%)")

    # --- 말속도(발화 길이) 비교 ---
    spans = _speech_spans(vad, audio)
    vad_speech_ms = sum(e - s for s, e in spans)

    ts_span_ms = ts[-1][1] - ts[0][0] if ts else 0          # 첫 단어~끝 단어 전체 구간
    ts_sum_ms = sum(e - s for s, e in ts) if ts else 0       # 단어 구간의 합

    print("\n=== 발화 길이 (말속도의 분모) ===")
    print(f"기존  VAD 구간 합:            {vad_speech_ms/1000:.2f}s")
    print(f"제안  타임스탬프 전체 구간:   {ts_span_ms/1000:.2f}s")
    print(f"제안  타임스탬프 구간 합:     {ts_sum_ms/1000:.2f}s")

    syl = len(r["text"].replace(" ", ""))
    def spm(ms): return syl / (ms/1000) * 60 if ms else 0
    print(f"\n음절 수: {syl}")
    print(f"syllables_per_min  기존(VAD합)={spm(vad_speech_ms):.0f}  전체구간={spm(ts_span_ms):.0f}  구간합={spm(ts_sum_ms):.0f}")


if __name__ == "__main__":
    main()
