import { SharedArray } from 'k6/data';
import { Counter, Trend } from 'k6/metrics';

export const BASE = __ENV.BASE_URL || 'http://localhost:8000';
export const WS_BASE = __ENV.WS_URL || 'ws://localhost:8000';

// seed/seed.py 가 만든 유저. VU 하나가 유저 하나를 쓴다 (세션이 유저에 묶이므로 섞으면 안 된다).
export const USERS = new SharedArray('users', () => JSON.parse(open('../seed/tokens.json')));

// 실제 발화가 담긴 webm. 무음이면 서버가 LLM 평가 경로를 타지 않아 부하가 과소평가된다.
// 단일 오디오를 쓰는 시나리오(버스트/영상소켓)용. 면접 시나리오는 아래 ANSWERS 를 쓴다.
export const AUDIO = open('../fixtures/answer.webm', 'b');

// 실제 사용자는 답변 길이가 제각각이다. 답변마다 아래에서 하나를 골라 STT 처리 시간이
// 실제처럼 달라지게 한다. seconds 는 영상 소켓 유지 시간·답변 대기에도 같이 쓴다.
//
// 30/60/90 3개 버킷은 너무 성기다 — 특히 30%가 90초 최악값에 고정돼 STT 부하의 꼬리를
// 과장한다. 실제 답변 길이는 연속적이므로 30~90초를 2초 간격(31개)으로 촘촘하게 두고,
// 아래 pickAnswer 가 삼각분포로 뽑는다. seconds 로 O(1) 조회하려고 오름차순(index=(sec-30)/2).
const ANSWER_MIN = 30;
const ANSWER_MAX = 90;
const ANSWER_STEP = 2;
export const ANSWERS = (() => {
    const arr = [];
    for (let s = ANSWER_MIN; s <= ANSWER_MAX; s += ANSWER_STEP) {
        arr.push({ seconds: s, audio: open(`../fixtures/answer_${s}s.webm`, 'b') });
    }
    return arr;
})();

// 최악 시나리오용: 답변 길이를 고정(초). 0 이면 아래 분포를 따른다.
const FORCE_ANSWER = Number(__ENV.FORCE_ANSWER || 0);

/** 30초 간격 2초로 촘촘하게 자른 답변 중 하나를, 삼각분포(최빈값 60초)로 뽑는다.
 *  평균은 (30+60+90)/3 = 60초로 기존 3버킷과 같지만, 밀도가 양끝으로 갈수록 0에
 *  수렴해 90초 최악값에 몰리지 않는다 — 실제 사용자 분포에 가깝다. FORCE_ANSWER 면 고정. */
export function pickAnswer() {
    if (FORCE_ANSWER) {
        return ANSWERS.find((a) => a.seconds === FORCE_ANSWER) || ANSWERS[ANSWERS.length - 1];
    }
    // 삼각분포 역변환 (a=30, mode=60, b=90). Fc = (c-a)/(b-a) = 0.5.
    const a = ANSWER_MIN, b = ANSWER_MAX, c = 60;
    const u = Math.random();
    const x = u < 0.5
        ? a + Math.sqrt(u * (b - a) * (c - a))
        : b - Math.sqrt((1 - u) * (b - a) * (b - c));
    // 가장 가까운 2초 격자로 스냅 후 인덱스로 변환.
    let idx = Math.round((x - ANSWER_MIN) / ANSWER_STEP);
    if (idx < 0) idx = 0;
    if (idx >= ANSWERS.length) idx = ANSWERS.length - 1;
    return ANSWERS[idx];
}

// plan.py 와 같은 값. 실사용 페이스를 재현할 때 쓴다.
export const PREPARE_SECONDS = Number(__ENV.PREPARE_SECONDS || 10);
// fixtures/answer.webm 의 실제 길이(약 75초). 답변 상한은 90초지만 오디오만큼만 말한 셈이다.
export const ANSWER_SECONDS = Number(__ENV.ANSWER_SECONDS || 75);

// 0 이면 서버가 끝낼 때까지(시간 예산 10분 또는 질문 15개). 스모크에서만 줄여 쓴다.
export const MAX_ANSWERS = Number(__ENV.MAX_ANSWERS || 0);

// 면접 시작을 VU마다 0~이 값(초) 사이로 랜덤하게 늦춘다. 실제 사용자는 동시에 시작하지
// 않는다 — 이게 0이면 모든 VU가 lockstep 으로 같은 시점에 답변을 제출해(동기화 버스트)
// "평균" 시나리오가 실은 최악이 된다. 평균 측정에선 answer 간격만큼 준다.
export const START_JITTER = Number(__ENV.START_JITTER_SECONDS || 0);

// 영상 소켓 페이로드: 'landmarks'(기본, 브라우저가 뽑은 값=서버 CPU 마이크로초) 또는
// 'jpeg'(저사양 폴백=서버가 접속마다 MediaPipe 그래프를 올려 프레임당 ~18ms CPU).
export const VIDEO_MODE = __ENV.VIDEO_MODE || 'landmarks';
export const JPEG = VIDEO_MODE === 'jpeg' ? open('../fixtures/frame.jpg', 'b') : null;

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
