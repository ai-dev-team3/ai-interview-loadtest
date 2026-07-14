"""부하 테스트용 유저 + 이력서 시딩, JWT 발급.

앱의 ORM/토큰 발급을 그대로 가져다 쓴다(back_tooktac 를 import 한다).

이력서는 반드시 '구조화까지 끝난 상태'로 넣는다. /real-interview/start 가
resume_service.ensure_structured 를 부르는데, structured 가 비어 있으면 첫 요청마다
Gemini 로 이력서를 분석한다. 그러면 측정하려던 면접 진행 지연에 이력서 분석 시간이
섞인다.

로그인도 타지 않는다. JWT 를 여기서 직접 만들어 k6 에 넘긴다 — bcrypt 검증(수십 ms,
CPU 바운드)이 서버 CPU 프로파일을 오염시키지 않게 하기 위해서다.

    python seed/seed.py            # 기본 30명
    python seed/seed.py -n 50
    python seed/seed.py --clean    # 시딩한 것 전부 삭제
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import bcrypt
from dotenv import load_dotenv

BACK = Path(r"C:\Users\main\Desktop\ai-team3\ai_interview-main\back_tooktac")
sys.path.insert(0, str(BACK))
load_dotenv(BACK / ".env")

import app.repository.model_registry  # noqa: F401  (모든 모델을 Base 에 등록)
from app.core.security import create_access_token
from app.repository.analysis import EvaluationResult, VideoEvaluationResult
from app.repository.database import SessionLocal
from app.repository.interview import InterviewAnswer, InterviewQuestion, InterviewSession
from app.repository.report import (
    FinalReportSummary,
    ReportAreaScore,
    ReportImprovement,
    ReportQuestionScore,
    ReportStrength,
)
from app.repository.resume import Resume, ResumeQuestion
from app.repository.user import User
from app.services.interview.plan import DEFAULT_QUESTION_TEXT, DEFAULT_QUESTION_TYPE

PREFIX = "loadtest_"
TOKENS_PATH = Path(__file__).with_name("tokens.json")

RESUME_TEXT = """백엔드 개발자 지원자입니다.
Python, FastAPI, SQLAlchemy 로 REST API 를 개발했고 MySQL 을 주로 사용했습니다.
사내 면접 연습 서비스의 음성 처리 파이프라인을 맡아 ffmpeg 변환과 STT 연동을 구현했고,
동시 요청이 몰릴 때 응답이 느려지는 문제를 스레드풀 조정으로 개선했습니다.
Docker 와 GitHub Actions 로 CI 를 구성한 경험이 있습니다.
신입으로 지원하며, 백엔드 개발자로 성장하고 싶습니다."""

# structurer.py 의 출력 스키마와 같은 모양이어야 한다 (_DEFAULT_STRUCTURE 참고).
# NextQuestionAgent 가 이 dict 를 통째로 프롬프트에 넣으므로 내용도 그럴듯해야
# 질문 생성 LLM 호출이 실사용과 비슷한 크기의 프롬프트를 받는다.
RESUME_STRUCTURED = {
    "skills": ["Python", "FastAPI", "SQLAlchemy", "MySQL", "Docker", "GitHub Actions"],
    "education": {
        "school": "한국대학교",
        "major": "컴퓨터공학",
        "degree": "학사",
        "status": "졸업",
    },
    "career": {"status": "신입", "years": "0년"},
    "projects": [
        {
            "name": "면접 연습 서비스 음성 파이프라인",
            "description": "ffmpeg 변환과 STT 연동을 구현하고, 동시 요청 시 지연을 스레드풀 조정으로 개선",
            "tech_stack": ["Python", "FastAPI", "ffmpeg"],
        },
        {
            "name": "사내 API 서버",
            "description": "FastAPI 와 SQLAlchemy 로 REST API 를 설계하고 MySQL 스키마를 관리",
            "tech_stack": ["FastAPI", "SQLAlchemy", "MySQL"],
        },
    ],
    "self_introduction": {
        "motivation": "사용자가 겪는 지연을 직접 측정하고 줄이는 일에 흥미가 있습니다.",
        "strengths": "문제를 재현 가능한 형태로 좁히는 것을 잘합니다.",
        "key_experiences": "음성 처리 파이프라인의 병목을 찾아 개선한 경험",
        "career_goals": "안정적인 백엔드 시스템을 설계하는 개발자",
    },
    "desired_position": {"job_type": "백엔드 개발자"},
}


def clean(db) -> None:
    users = db.query(User).filter(User.username.like(f"{PREFIX}%")).all()
    if not users:
        print("삭제할 부하 테스트 유저가 없다.")
        return

    user_ids = [u.id for u in users]
    session_ids = [
        s.id for s in db.query(InterviewSession).filter(InterviewSession.user_id.in_(user_ids)).all()
    ]

    # interview_* / analysis / report 테이블에는 ondelete=CASCADE 가 없다. 순서대로 지운다.
    if session_ids:
        report_ids = [
            r.id
            for r in db.query(FinalReportSummary)
            .filter(FinalReportSummary.session_id.in_(session_ids))
            .all()
        ]
        for model in (ReportStrength, ReportImprovement, ReportAreaScore, ReportQuestionScore):
            if report_ids:
                db.query(model).filter(model.report_id.in_(report_ids)).delete(synchronize_session=False)
        db.query(FinalReportSummary).filter(
            FinalReportSummary.session_id.in_(session_ids)
        ).delete(synchronize_session=False)

        for model in (EvaluationResult, VideoEvaluationResult, InterviewAnswer, InterviewQuestion):
            db.query(model).filter(model.session_id.in_(session_ids)).delete(synchronize_session=False)
        db.query(InterviewSession).filter(InterviewSession.id.in_(session_ids)).delete(
            synchronize_session=False
        )

    for user in users:
        db.delete(user)  # resume 은 ondelete=CASCADE
    db.commit()

    print(f"유저 {len(user_ids)}명, 세션 {len(session_ids)}개 삭제 완료.")
    TOKENS_PATH.unlink(missing_ok=True)


def seed(db, count: int) -> None:
    password_hash = bcrypt.hashpw(b"loadtest1234", bcrypt.gensalt()).decode()
    entries = []

    for i in range(1, count + 1):
        username = f"{PREFIX}{i:03d}"
        user = db.query(User).filter_by(username=username).first()
        if user is None:
            user = User(
                username=username,
                password=password_hash,
                name=f"부하{i:03d}",
                nickname=f"부하테스터{i:03d}",
                email=f"{username}@loadtest.local",
                birthdate=date(1998, 1, 1),
                desired_job="백엔드 개발자",
            )
            db.add(user)
            db.flush()

        resume = db.query(Resume).filter_by(user_id=user.id).first()
        if resume is None:
            resume = Resume(user_id=user.id, filename="loadtest_resume.txt")
            db.add(resume)

        resume.content = RESUME_TEXT
        resume.structured = RESUME_STRUCTURED
        resume.questions_generated = True  # 질문 풀 지연 생성(LLM)을 막는다
        if not resume.questions:
            resume.questions.append(
                ResumeQuestion(
                    question_text=DEFAULT_QUESTION_TEXT,
                    question_type=DEFAULT_QUESTION_TYPE,
                    is_default=True,
                    sort_order=0,
                )
            )

        entries.append({"user_id": user.id, "username": username})

    db.commit()

    for e in entries:
        e["token"] = create_access_token(e["user_id"])

    TOKENS_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"유저 {len(entries)}명 시딩 완료. 토큰 -> {TOKENS_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--count", type=int, default=30)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.clean:
            clean(db)
        else:
            seed(db, args.count)
    finally:
        db.close()


if __name__ == "__main__":
    main()
