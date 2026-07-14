// ★ 본편. 동시에 N명이 실사용 페이스로 면접을 본다.
//
//   bin\k6.exe run -e VUS=10 scenarios/10_interview.js
//
// VU 하나 = 면접자 한 명 = 면접 한 판(약 11분). 준비 10초 / 답변 75초를 실제로 쉰다.
// 압축해서 돌리지 않는 이유: 영상 소켓이 열려 있는 '시간'과 백그라운드 분석이 쌓이는
// '시간'이 병목의 핵심이라, 시간을 줄이면 그 병목이 보이지 않는다.
//
// 임계값(SLO)을 이 실행이 통과했는지가 곧 "이 동시 사용자 수를 버티는가"의 답이다.
// run.ps1 이 5, 10, 15, 20, 30 으로 올려가며 처음 깨지는 지점을 찾는다.

import { user } from '../lib/config.js';
import { runInterview } from '../lib/interview.js';
import { SLO } from '../lib/thresholds.js';

const VUS = Number(__ENV.VUS || 5);

export const options = {
    scenarios: {
        interviews: {
            executor: 'per-vu-iterations',
            vus: VUS,
            iterations: 1,      // 한 명이 면접을 한 판 완주한다
            maxDuration: '30m',
        },
    },
    thresholds: SLO,
};

export default function () {
    runInterview(user(__VU));
}
