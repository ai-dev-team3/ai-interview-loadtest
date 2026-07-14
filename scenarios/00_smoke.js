// 스크립트가 실제로 면접을 완주하는지 확인한다. 부하는 걸지 않는다.
//
//   bin\k6.exe run -e MAX_ANSWERS=2 -e PREPARE_SECONDS=2 -e ANSWER_SECONDS=10 scenarios/00_smoke.js
//
// 서버 워밍업(임베딩 + SenseVoice 모델 로딩)이 끝난 뒤에 돌릴 것. 로그에
// "워밍업 완료" 가 뜨기 전에 때리면 첫 요청이 비정상적으로 느리다 (main.py:71-72).

import { user } from '../lib/config.js';
import { runInterview } from '../lib/interview.js';

export const options = {
    vus: 1,
    iterations: 1,
    thresholds: { checks: ['rate==1.0'] },
};

export default function () {
    runInterview(user(__VU));
}
