// H2 검증: 답변 처리 fast-path 가 스레드풀 4개(FAST_PATH_WORKERS)로 막혀 있는가.
//
//   bin\k6.exe run -e VUS=4 scenarios/20_answer_burst.js
//   bin\k6.exe run -e VUS=8 scenarios/20_answer_burst.js
//
// 영상 소켓도, 준비/답변 대기도 없다. /answer 만 N개가 동시에 서버를 때린다.
// ffmpeg + SenseVoice STT 가 _FAST_EXECUTOR(기본 4 워커)에서 도므로,
// VUS 를 4 -> 8 -> 16 으로 올릴 때 p95 가 계단처럼 늘면 이 스레드풀이 병목이다.

import { user } from '../lib/config.js';
import { MAX_ANSWERS } from '../lib/config.js';
import { startInterview, submitAnswer } from '../lib/interview.js';

const VUS = Number(__ENV.VUS || 4);
const ANSWERS = MAX_ANSWERS || 3;

export const options = {
    scenarios: {
        burst: {
            executor: 'per-vu-iterations',
            vus: VUS,
            iterations: 1,
            maxDuration: '20m',
        },
    },
    thresholds: {
        'http_req_duration{name:POST /real-interview/answer}': ['p(95)<10000'],
        server_5xx: ['count==0'],
        db_pool_errors: ['count==0'],
    },
};

export default function () {
    const u = user(__VU);
    const started = startInterview(u);
    if (!started) return;

    let order = started.order;
    for (let i = 0; i < ANSWERS; i++) {
        const answered = submitAnswer(u, started.sessionId, order);
        if (!answered || answered.closing) return;
        order = answered.question.question_order;
    }
}
