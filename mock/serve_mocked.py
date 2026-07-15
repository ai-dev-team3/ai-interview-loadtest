"""LLM 호출을 '고정 지연'으로 대체하고 서버를 띄운다. STT만 보기 위한 것이다.

왜 이렇게 하나.
    부하 테스트로 확인한 사실: 다음 질문 생성 LLM은 동시 1명에서 평균 2.0초,
    동시 5명에서도 평균 2.0초였다. 동시성과 무관하다 — 외부 API는 병목이 아니다.
    그러니 실제로 부를 이유가 없다. 그만큼 자는 것으로 대신하면 토큰 비용도 0이고,
    외부 API의 편차가 측정에 섞이지도 않는다. 그러면 남는 변수는 STT 하나다.

무엇을 가짜로 바꾸나 (LLM 호출만이다).
    NextQuestionAgent.generate      다음 질문 생성 (사용자를 기다리게 하는 경로)
    ModelAnswerGenerator.generate   모범답변 생성 (백그라운드)
    AnswerEvaluator.evaluate        답변 평가   (백그라운드)

무엇을 진짜로 두나 (STT 부하를 재려면 그대로여야 한다).
    ffmpeg 변환, SenseVoice STT, VAD, librosa 피치 분석, 임베딩 유사도, DB, 영상 소켓

    python mock\serve_mocked.py                  # LLM = 2.0초 (실측값)
    $env:LLM_DELAY_SECONDS=0; python mock\serve_mocked.py   # LLM 시간을 빼고 STT만
"""
import asyncio
import os
import sys
import time
from pathlib import Path

BACK = Path(r"C:\Users\main\Desktop\ai-team3\ai_interview-main\back_tooktac")
sys.path.insert(0, str(BACK))
os.chdir(BACK)

from dotenv import load_dotenv

load_dotenv(BACK / ".env")

# 실측값. 동시 1명 1.6~2.8초, 동시 5명 평균 2.0초 (동시성과 무관했다).
DELAY = float(os.getenv("LLM_DELAY_SECONDS", "2.0"))

from app.services.interview.next_question import NextQuestion, NextQuestionAgent
from app.services.text.answer_generator import ModelAnswerGenerator
from app.services.text.evaluator import AnswerEvaluator

# 백그라운드 임베딩(유사도)을 어느 장치에 올릴지. 기본은 앱 그대로(=GPU 자동 선택).
#
# 앱은 SentenceTransformer 에 device 를 주지 않아 모델이 알아서 cuda:0 를 잡는다
# (기동 로그: "No device provided, using cuda:0"). 그래서 사용자를 기다리게 하는
# SenseVoice STT 와 백그라운드 임베딩이 GPU 한 장을 두고 다툰다.
# EMBED_DEVICE=cpu 로 띄우면 그 경합을 없앤 상태를 잴 수 있다.
EMBED_DEVICE = os.getenv("EMBED_DEVICE", "").strip()

if EMBED_DEVICE:
    from sentence_transformers import SentenceTransformer as _RealST

    import app.services.text.scorer as scorer

    def _st_on_device(name, **kwargs):
        kwargs["device"] = EMBED_DEVICE
        return _RealST(name, **kwargs)

    scorer.SentenceTransformer = _st_on_device

FAKE_QUESTION = "방금 말씀하신 스레드풀 조정에서, 왜 하필 그 크기를 골랐는지 근거를 설명해주시겠어요?"
FAKE_MODEL_ANSWER = (
    "병목 구간을 먼저 측정해 어디에서 시간이 쓰이는지 확인하고, "
    "동시 처리량과 지연의 균형점을 찾아 스레드풀 크기를 정했습니다."
)
FAKE_EVALUATION = {
    "intent_score": 7.0,
    "knowledge_score": 6.5,
    "strengths": ["문제를 측정으로 좁혀 나간 점이 좋습니다."],
    "improvements": ["선택의 근거를 수치로 제시하면 더 설득력이 있습니다."],
    "final_feedback": "구체적인 경험을 논리적으로 설명했습니다.",
}


def _next_question(self, resume, history, remaining_seconds):
    time.sleep(DELAY)  # 이 경로는 to_thread 로 불린다 — 동기 sleep 이 맞다
    return NextQuestion(FAKE_QUESTION, "기술형", is_follow_up=True)


def _model_answer(self, question, user_answer, evaluation_type):
    time.sleep(DELAY)
    return FAKE_MODEL_ANSWER


async def _amodel_answer(self, question, user_answer, evaluation_type):
    await asyncio.sleep(DELAY)
    return FAKE_MODEL_ANSWER


def _evaluate(self, question, user_answer, evaluation_type):
    time.sleep(DELAY)
    return dict(FAKE_EVALUATION)


async def _aevaluate(self, question, user_answer, evaluation_type):
    await asyncio.sleep(DELAY)
    return dict(FAKE_EVALUATION)


NextQuestionAgent.generate = _next_question
ModelAnswerGenerator.generate = _model_answer
ModelAnswerGenerator.agenerate = _amodel_answer
AnswerEvaluator.evaluate = _evaluate
AnswerEvaluator.aevaluate = _aevaluate

# STT 를 즉시 반환으로 스텁한다 (STUB_STT=1). "STT 병목을 뺀 다음 벽이 어디냐"를 잴 때 쓴다.
# ffmpeg 변환은 그대로 두고(파일이 있어야 백그라운드 pitch 가 wav 를 읽는다), GPU STT 만 없앤다.
STUB_STT = os.getenv("STUB_STT", "") == "1"
if STUB_STT:
    from app.services.stt.sensevoice import SenseVoiceClient

    _FIXED_TEXT = (
        "네 제가 맡았던 프로젝트에 대해 말씀드리겠습니다. 저는 음성 처리 파이프라인을 담당했고, "
        "동시 요청이 몰릴 때 느려지는 문제를 측정으로 좁혀 스레드풀을 조정해 개선했습니다."
    )

    def _fake_transcribe(self, wav_path):
        # 실제 발화 구간과 비슷하게 채운다 (말속도 계산이 0으로 죽지 않게).
        return _FIXED_TEXT, {"segments": [{"text": _FIXED_TEXT, "start": 0, "end": 70000}]}

    SenseVoiceClient.transcribe = _fake_transcribe

if __name__ == "__main__":
    import uvicorn

    from app.main import app

    stt = "스텁(즉시 반환)" if STUB_STT else "실제 GPU"
    print(
        f"[mock] LLM={DELAY}초 고정 | STT={stt} | 임베딩 장치={EMBED_DEVICE or '앱 기본값(GPU)'} "
        f"| ffmpeg/영상/DB 는 그대로"
    )
    uvicorn.run(app, host="0.0.0.0", port=8000)
