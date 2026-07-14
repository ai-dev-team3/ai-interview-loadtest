// 실전 면접 한 판(start -> 질문마다 [영상 소켓 + 답변 업로드] -> closing -> 분석 대기).
// 00_smoke.js 와 10_interview.js 가 공유한다.

import http from 'k6/http';
import ws from 'k6/ws';
import { check, sleep } from 'k6';
import {
    AUDIO, ANSWER_SECONDS, BASE, MAX_ANSWERS, PREPARE_SECONDS, WS_BASE,
    analysisConvergence, analysisTimeouts, headers, recordFailure, wsFrameRtt,
} from './config.js';
import { FRAME_INTERVAL_MS, frame } from './landmarks.js';

/** 답변하는 동안 열려 있는 영상 소켓. 프론트와 같이 5fps 로 랜드마크를 흘린다.
 *  이 소켓은 서버에서 DB 커넥션 하나를 통째로 붙들고 있다 (video.py:100). */
function streamExpression(u, sessionId, questionOrder, seconds) {
    const url = `${WS_BASE}/ws/expression?question_id=${questionOrder}&session_id=${sessionId}`;
    const res = ws.connect(url, { headers: headers(u) }, (socket) => {
        let sentAt = 0;

        socket.on('open', () => {
            socket.setInterval(() => {
                sentAt = Date.now();
                socket.sendBinary(frame());
            }, FRAME_INTERVAL_MS);
            socket.setTimeout(() => socket.close(), seconds * 1000);
        });

        socket.on('message', (msg) => {
            if (sentAt) wsFrameRtt.add(Date.now() - sentAt);
            check(msg, {
                '영상 프레임 분석 성공': (m) => !String(m).includes('분석 실패'),
            });
        });

        socket.on('error', (e) => {
            if (e.error() !== 'websocket: close sent') {
                check(null, { '영상 소켓 정상': () => false });
            }
        });
    });

    check(res, { '영상 소켓 연결(101)': (r) => r && r.status === 101 });
}

export function submitAnswer(u, sessionId, questionOrder) {
    const res = http.post(
        `${BASE}/real-interview/answer?session_id=${sessionId}&question_order=${questionOrder}`,
        { audio: http.file(AUDIO, 'answer.webm', 'audio/webm') },
        { headers: headers(u), tags: { name: 'POST /real-interview/answer' }, timeout: '120s' },
    );
    recordFailure(res);
    check(res, { '답변 제출 200': (r) => r.status === 200 });
    return res.status === 200 ? res.json() : null;
}

/** 백그라운드 분석(pitch + 임베딩 + LLM 평가)이 전부 끝날 때까지 폴링한다.
 *  /answer 는 이 작업을 asyncio.create_task 로 던지고 바로 응답하므로,
 *  여기서 기다리지 않으면 뒤에 쌓이는 큐가 측정에서 통째로 빠진다. */
function waitForAnalysis(u, sessionId, lastAnswerAt, answers) {
    const deadline = Date.now() + 300 * 1000;

    while (Date.now() < deadline) {
        const res = http.get(`${BASE}/real-interview/analysis-status?session_id=${sessionId}`, {
            headers: headers(u),
            tags: { name: 'GET /real-interview/analysis-status' },
        });
        recordFailure(res);
        // finished(=done>=total) 를 쓰지 않는다. 면접을 중간에 끊으면(MAX_ANSWERS) 서버가 이미
        // 만들어 둔 '아직 답 안 한 질문'이 total 에 잡혀 영원히 finished 가 되지 않는다.
        // 우리가 기다릴 것은 '제출한 답변만큼 분석이 끝났는가' 다.
        if (res.status === 200 && res.json('done') >= answers) {
            analysisConvergence.add(Date.now() - lastAnswerAt);
            return true;
        }
        sleep(2);
    }

    analysisTimeouts.add(1);
    check(null, { '분석 5분 내 수렴': () => false });
    return false;
}

export function startInterview(u) {
    const res = http.post(`${BASE}/real-interview/start`, null, {
        headers: headers(u),
        tags: { name: 'POST /real-interview/start' },
        timeout: '60s',
    });
    recordFailure(res);
    if (!check(res, { '면접 시작 200': (r) => r.status === 200 })) return null;

    return { sessionId: res.json('session_id'), order: res.json('question.question_order') };
}

export function runInterview(u) {
    const started = startInterview(u);
    if (!started) return;

    const sessionId = started.sessionId;
    let order = started.order;
    let answers = 0;
    let lastAnswerAt = 0;

    // 종료 조건은 서버가 정한다: 시간 예산 10분 또는 질문 15개 (plan.py).
    // 응답의 closing=true 를 보고 빠져나온다.
    for (;;) {
        sleep(PREPARE_SECONDS); // 준비 시간. 이 동안 사용자는 생각만 한다.

        streamExpression(u, sessionId, order, ANSWER_SECONDS); // 답변하는 동안 영상 소켓이 열려 있다

        const answered = submitAnswer(u, sessionId, order);
        if (!answered) return;

        answers += 1;
        lastAnswerAt = Date.now();

        if (answered.closing) break;
        if (MAX_ANSWERS && answers >= MAX_ANSWERS) break;
        order = answered.question.question_order;
    }

    sleep(PREPARE_SECONDS);
    const closing = http.post(
        `${BASE}/real-interview/closing?session_id=${sessionId}`,
        { audio: http.file(AUDIO, 'answer.webm', 'audio/webm') },
        { headers: headers(u), tags: { name: 'POST /real-interview/closing' }, timeout: '120s' },
    );
    recordFailure(closing);
    check(closing, { '마지막 한마디 200': (r) => r.status === 200 });

    waitForAnalysis(u, sessionId, lastAnswerAt, answers);
}
