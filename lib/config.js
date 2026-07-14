import { SharedArray } from 'k6/data';
import { Counter, Trend } from 'k6/metrics';

export const BASE = __ENV.BASE_URL || 'http://localhost:8000';
export const WS_BASE = __ENV.WS_URL || 'ws://localhost:8000';

// seed/seed.py 가 만든 유저. VU 하나가 유저 하나를 쓴다 (세션이 유저에 묶이므로 섞으면 안 된다).
export const USERS = new SharedArray('users', () => JSON.parse(open('../seed/tokens.json')));

// 실제 발화가 담긴 webm. 무음이면 서버가 LLM 평가 경로를 타지 않아 부하가 과소평가된다.
export const AUDIO = open('../fixtures/answer.webm', 'b');

// plan.py 와 같은 값. 실사용 페이스를 재현할 때 쓴다.
export const PREPARE_SECONDS = Number(__ENV.PREPARE_SECONDS || 10);
// fixtures/answer.webm 의 실제 길이(약 75초). 답변 상한은 90초지만 오디오만큼만 말한 셈이다.
export const ANSWER_SECONDS = Number(__ENV.ANSWER_SECONDS || 75);

// 0 이면 서버가 끝낼 때까지(시간 예산 10분 또는 질문 15개). 스모크에서만 줄여 쓴다.
export const MAX_ANSWERS = Number(__ENV.MAX_ANSWERS || 0);

export const poolErrors = new Counter('db_pool_errors');
export const serverErrors = new Counter('server_5xx');
export const wsFrameRtt = new Trend('ws_frame_rtt', true);
// 마지막 답변 제출 -> 백그라운드 분석이 전부 끝나기까지. H3(분석 큐 적체) 검증용.
export const analysisConvergence = new Trend('analysis_convergence', true);
export const analysisTimeouts = new Counter('analysis_timeouts');

export function user(vu) {
    return USERS[(vu - 1) % USERS.length];
}

export function headers(u) {
    // 앱은 HTTP 라우트에서 Authorization 을 보지 않는다 — 쿠키만 읽는다 (dependencies.py).
    return { Cookie: `access_token=${u.token}` };
}

/** 500 / 커넥션 풀 고갈을 집계한다. 풀이 마르면 SQLAlchemy 가 TimeoutError 를 던진다. */
export function recordFailure(res) {
    if (res.status >= 500 || res.status === 0) {
        serverErrors.add(1);
        const body = String(res.body || '');
        if (body.includes('QueuePool') || body.includes('TimeoutError')) {
            poolErrors.add(1);
        }
    }
}
