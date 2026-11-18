"""사진에서 사람만 정확하게 오려 내는 마스크 (2026-11-18: GrabCut 누끼가 글자를 먹고 가장자리가 지저분했다).

MediaPipe 사람 분할 모델(selfie_multiclass, 머리카락·얼굴·몸·옷 구분)로 사람 영역을 구하고,
가장자리는 원본 해상도에서 부드럽게 다듬는다. 의자·책상 같은 배경은 빠진다.

사용법: python scripts/person_mask.py 사진.png 마스크.png [--feather 2]
모델: ~/tools/mediapipe/selfie_multiclass.tflite (setup_tools.sh가 받는다)
"""
import argparse
from pathlib import Path

import cv2
import numpy as np

MODEL = Path.home() / "tools/mediapipe/selfie_multiclass.tflite"


def person_mask(img_bgr: np.ndarray, feather: float = 2.0) -> np.ndarray:
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    opts = vision.ImageSegmenterOptions(base_options=BaseOptions(model_asset_path=str(MODEL)),
                                        output_confidence_masks=True, output_category_mask=False)
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    with vision.ImageSegmenter.create_from_options(opts) as seg:
        r = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        # 0번은 배경 확률: 사람 = 1 - 배경. 분할기가 닫히면 메모리가 풀리니 안에서 복사해 둔다
        bg = r.confidence_masks[0].numpy_view().copy()[..., 0]
    m = np.clip(1.0 - bg, 0, 1)
    m = cv2.resize(m, (img_bgr.shape[1], img_bgr.shape[0]), interpolation=cv2.INTER_LINEAR)
    # 가장 큰 덩어리만 (옆에 걸린 다른 물체 제거)
    b = (m > 0.5).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b)
    if n > 1:
        k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        keep = (lab == k).astype(np.uint8)
        keep = cv2.dilate(keep, np.ones((9, 9), np.uint8))
        m = m * keep
    # 가장자리를 원본 색 경계에 맞춰 다듬는다 (guided filter가 있으면)
    try:
        # 0~1 실수로 넘겨야 한다 (uint8로 넘기면 eps 단위가 달라 마스크가 거의 지워진다, 2026-11-18)
        m = cv2.ximgproc.guidedFilter(img_bgr.astype(np.float32) / 255, m.astype(np.float32), 6, 1e-3)
    except AttributeError:
        pass
    if feather:
        m = cv2.GaussianBlur(m, (0, 0), feather)
    return (np.clip(m, 0, 1) * 255).astype(np.uint8)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--feather", type=float, default=2.0)
    a = ap.parse_args()
    img = cv2.imread(a.src)
    cv2.imwrite(a.out, person_mask(img, a.feather))
    print("ok", a.out)
