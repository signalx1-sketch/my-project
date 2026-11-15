"""같은 사진 한 장으로 썸네일용 비포(붉은기 조금 더)·애프터(붉은기만 걷기)를 만든다 (2026-11-15).

작업 원칙: 비포·애프터는 반드시 같은 사진·같은 각도. 애프터는 볼의 붉은기만 이마 피부색 쪽으로 걷고(LAB a*),
밝기는 살짝, 흐림·강한 샤프닝 없이. 입술·눈·눈썹은 건드리지 않는다 (MediaPipe 얼굴 랜드마크로 가린다).

사용법: python scripts/make_redness_pair.py 사진.png 비포.png 애프터.png [--before 1.2] [--after 0.25]
"""
import argparse
from pathlib import Path

import cv2
import numpy as np

MODEL = Path.home() / "tools/mediapipe/face_landmarker.task"
# FaceMesh 윤곽 번호
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176,
             149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
L_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
R_EYE = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
L_BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
R_BROW = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
FOREHEAD = [10, 109, 67, 103, 54, 21, 71, 68, 104, 69, 108, 151, 337, 299, 333, 298, 301, 251, 284, 332, 297, 338]


def landmarks(img):
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)), num_faces=1)
    with vision.FaceLandmarker.create_from_options(opts) as lmk:
        r = lmk.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    if not r.face_landmarks:
        raise SystemExit("얼굴을 찾지 못했습니다")
    h, w = img.shape[:2]
    return np.array([(p.x * w, p.y * h) for p in r.face_landmarks[0]], np.int32)


def poly_mask(shape, pts, idx, grow=0):
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [cv2.convexHull(pts[idx])], 255)
    if grow:
        m = cv2.dilate(m, np.ones((grow, grow), np.uint8))
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--before", dest="kb", type=float, default=1.2, help="비포 붉은기 배율 (1이면 원본)")
    ap.add_argument("--after", dest="ka", type=float, default=0.25, help="애프터에 남길 붉은기 비율")
    a = ap.parse_args()
    img = cv2.imread(a.src)
    pts = landmarks(img)
    face = poly_mask(img.shape, pts, FACE_OVAL)
    keep = cv2.bitwise_or(poly_mask(img.shape, pts, LIPS, 15), poly_mask(img.shape, pts, L_EYE, 21))
    for idx in (R_EYE, L_BROW, R_BROW):
        keep = cv2.bitwise_or(keep, poly_mask(img.shape, pts, idx, 15))
    m = cv2.bitwise_and(face, cv2.bitwise_not(keep))
    soft = cv2.GaussianBlur(m, (0, 0), 14).astype(np.float32) / 255.0

    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    fh = poly_mask(img.shape, pts, FOREHEAD)
    ref = float(np.median(lab[..., 1][fh > 0]))           # 이마 피부의 a* (붉은기 기준)
    excess = np.clip(lab[..., 1] - ref, 0, None)         # 이마보다 붉은 만큼

    def make(k, lift):
        out = lab.copy()
        out[..., 1] = lab[..., 1] - excess * (1 - k) * soft
        out[..., 2] = lab[..., 2] - excess * (1 - k) * 0.15 * soft   # 붉은기와 함께 오는 노란기도 조금
        out[..., 0] = lab[..., 0] + lift * soft
        return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)

    cv2.imwrite(a.before, make(a.kb, 0))
    cv2.imwrite(a.after, make(a.ka, 3))
    print(f"이마 a* {ref:.1f}, 붉은기 평균 {excess[m > 0].mean():.1f} → {a.before}, {a.after}")


if __name__ == "__main__":
    main()
