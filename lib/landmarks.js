// /ws/expression 의 0x01(랜드마크) 페이로드를 만든다.
// 백엔드 app/services/vision/payload.py + 프론트 app/lib/postureProtocol.ts 와 같은 규격이다.
// 220바이트: 헤더 4 + float32 LE 54개 (얼굴 12점 + 포즈 6점) × (x, y, visibility)

const KIND_LANDMARKS = 0x01;
const KIND_JPEG = 0x02;
const HEADER_BYTES = 4;
export const FRAME_INTERVAL_MS = 200; // 프론트와 동일한 5fps (postureProtocol.ts)

/** 0x02 페이로드: [0]=0x02, 이후 JPEG 바이트. 서버가 접속마다 MediaPipe 로 처리한다. */
export function jpegFrame(jpeg) {
    const out = new Uint8Array(1 + jpeg.byteLength);
    out[0] = KIND_JPEG;
    out.set(new Uint8Array(jpeg), 1);
    return out.buffer;
}

// posture_rules.py 의 FACE_INDICES / POSE_INDICES 와 '순서까지' 같아야 한다.
// 값은 정면을 응시한 바른 자세 한 프레임이다 — score_landmarks 가 전 항목 CENTER 로 판정한다.
const FACE_POINTS = [
    [0.500, 0.500, 0.95], // 1   코끝
    [0.440, 0.450, 0.95], // 33  왼쪽 눈 바깥
    [0.470, 0.580, 0.95], // 78  왼쪽 입꼬리
    [0.500, 0.650, 0.95], // 152 턱
    [0.560, 0.450, 0.95], // 263 오른쪽 눈 바깥
    [0.530, 0.580, 0.95], // 308 오른쪽 입꼬리
    [0.4650, 0.450, 0.95], // 468 왼쪽 눈 중심
    [0.4725, 0.450, 0.95], // 469 왼쪽 홍채 오른쪽
    [0.4575, 0.450, 0.95], // 471 왼쪽 홍채 왼쪽
    [0.5350, 0.450, 0.95], // 473 오른쪽 눈 중심
    [0.5425, 0.450, 0.95], // 474 오른쪽 홍채 오른쪽
    [0.5275, 0.450, 0.95], // 476 오른쪽 홍채 왼쪽
];

const POSE_POINTS = [
    [0.420, 0.460, 0.95], // 7  왼쪽 귀
    [0.580, 0.460, 0.95], // 8  오른쪽 귀
    [0.350, 0.850, 0.95], // 11 왼쪽 어깨
    [0.650, 0.850, 0.95], // 12 오른쪽 어깨
    [0.200, 1.200, 0.10], // 19 왼손 (visibility 0.5 이하 = 손 안 보임)
    [0.800, 1.200, 0.10], // 20 오른손
];

/** 사람이 미세하게 움직이는 것처럼 프레임마다 좌표를 흔든다. */
export function frame() {
    const buffer = new ArrayBuffer(HEADER_BYTES + (FACE_POINTS.length + POSE_POINTS.length) * 3 * 4);
    const view = new DataView(buffer);

    view.setUint8(0, KIND_LANDMARKS);
    view.setUint8(1, 1); // face_present
    view.setUint8(2, 1); // pose_present
    view.setUint8(3, 0);

    let offset = HEADER_BYTES;
    for (const points of [FACE_POINTS, POSE_POINTS]) {
        for (const [x, y, visibility] of points) {
            const jitter = (Math.random() - 0.5) * 0.004;
            view.setFloat32(offset, x + jitter, true);
            view.setFloat32(offset + 4, y + jitter, true);
            view.setFloat32(offset + 8, visibility, true);
            offset += 12;
        }
    }
    return buffer;
}
