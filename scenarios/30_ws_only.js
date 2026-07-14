// H1 검증: 영상 소켓만으로 서버가 무너지는가 (특히 DB 커넥션 풀 고갈).
//
//   bin\k6.exe run -e VUS=20 scenarios/30_ws_only.js
//
// video.py:100 은 소켓이 열릴 때 get_db() 로 Session 을 만들고 연결이 끊길 때(:174)
// 닫는다. 다만 SQLAlchemy Session 은 '첫 쿼리'에서야 풀에서 커넥션을 꺼내므로,
// 프레임만 흘리는 동안에는 커넥션을 안 쥐고 있을 수도 있다. 코드만 봐서는 단정할 수
// 없어서 실측한다.
//
// 방법: 소켓을 N개 열어둔 채, 그와 무관한 API(analysis-status)를 1초에 한 번씩 찔러
// 응답이 느려지거나 죽기 시작하는 지점을 본다. 커넥션 풀(기본 5+10=15)이 마르면
// 소켓과 상관없는 이 요청이 먼저 티를 낸다.

import ws from 'k6/ws';
import http from 'k6/http';
import { check, sleep } from 'k6';
import {
    BASE, USERS, WS_BASE, headers, recordFailure, user, wsFrameRtt,
} from '../lib/config.js';
import { FRAME_INTERVAL_MS, frame } from '../lib/landmarks.js';
import { startInterview } from '../lib/interview.js';

const VUS = Number(__ENV.VUS || 10);
const HOLD_SECONDS = Number(__ENV.HOLD_SECONDS || 120);

export const options = {
    scenarios: {
        sockets: {
            executor: 'per-vu-iterations',
            vus: VUS,
            iterations: 1,
            maxDuration: '10m',
            exec: 'socket',
        },
        probe: {
            executor: 'constant-arrival-rate',
            rate: 1,
            timeUnit: '1s',
            duration: `${HOLD_SECONDS}s`,
            preAllocatedVUs: 2,
            exec: 'probe',
        },
    },
    thresholds: {
        'http_req_duration{name:GET /real-interview/analysis-status}': ['p(95)<300'],
        ws_frame_rtt: ['p(95)<200'],
        server_5xx: ['count==0'],
        db_pool_errors: ['count==0'],
        checks: ['rate>0.99'],
    },
};

// 소켓 VU 와 겹치지 않도록 마지막 유저로 프로브용 세션을 하나 만든다.
export function setup() {
    const probeUser = USERS[USERS.length - 1];
    const started = startInterview(probeUser);
    return { probeUser, sessionId: started ? started.sessionId : null };
}

export function socket() {
    const u = user(__VU);
    const url = `${WS_BASE}/ws/expression?question_id=1`;

    const res = ws.connect(url, { headers: headers(u) }, (socket) => {
        let sentAt = 0;
        socket.on('open', () => {
            socket.setInterval(() => {
                sentAt = Date.now();
                socket.sendBinary(frame());
            }, FRAME_INTERVAL_MS);
            socket.setTimeout(() => socket.close(), HOLD_SECONDS * 1000);
        });
        socket.on('message', (msg) => {
            if (sentAt) wsFrameRtt.add(Date.now() - sentAt);
            check(msg, { '영상 프레임 분석 성공': (m) => !String(m).includes('분석 실패') });
        });
    });

    check(res, { '영상 소켓 연결(101)': (r) => r && r.status === 101 });
}

export function probe(data) {
    if (!data.sessionId) return;

    const res = http.get(`${BASE}/real-interview/analysis-status?session_id=${data.sessionId}`, {
        headers: headers(data.probeUser),
        tags: { name: 'GET /real-interview/analysis-status' },
    });
    recordFailure(res);
    check(res, { '소켓이 열려 있는 동안에도 API 정상': (r) => r.status === 200 });
    sleep(0);
}
