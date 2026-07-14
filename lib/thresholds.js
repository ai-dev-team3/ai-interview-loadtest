// SLO. 한 곳에서 관리한다.
//
// /answer 의 10초는 우리가 지어낸 값이 아니다. real_interview.py 의 첫 주석이
// "빠른 길 (사용자를 기다리게 한다 — 준비 시간 10초 예산)" 이라고 못박고 있다.
// 이걸 넘으면 사용자는 준비 시간 없이 바로 답변해야 한다 — 기능이 깨진다.

export const SLO = {
    'http_req_duration{name:POST /real-interview/answer}': ['p(95)<10000', 'p(99)<15000'],
    'http_req_duration{name:POST /real-interview/start}': ['p(95)<2000'],
    'http_req_duration{name:POST /real-interview/closing}': ['p(95)<8000'],
    'http_req_duration{name:GET /real-interview/analysis-status}': ['p(95)<300'],
    ws_frame_rtt: ['p(95)<200'],
    analysis_convergence: ['p(95)<60000'], // 마지막 답변 후 60초 안에 분석이 끝나야 한다
    analysis_timeouts: ['count==0'],
    server_5xx: ['count==0'],
    db_pool_errors: ['count==0'],
    checks: ['rate>0.99'],
};
