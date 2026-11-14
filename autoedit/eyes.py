"""얼굴 영상에서 눈을 얼마나 뜨고 있는지 잰다 (2026-11-14).

밤에 강한 조명 아래서 찍으면 눈이 부셔 실눈을 뜬 장면이 많다. 얼굴이 그대로 보이는 구간은
눈을 크게 뜬 곳으로 남기고, 실눈 구간은 카드나 자료로 덮는다 (broll.place의 squint).

MediaPipe FaceLandmarker로 프레임마다 눈 높이/폭 비율(EAR)을 재고, 영상 전체 분포에 견주어
점수(0 = 이 영상에서 가장 작게 뜬 눈, 1 = 가장 크게 뜬 눈)로 바꾼다. 깜빡임은 0.4초 창의
최대값으로 걸러 낸다. 결과는 작업 폴더 eyes.json에 남겨 다시 쓴다.
"""
import json
import os
from pathlib import Path

MODEL = Path(os.environ.get("FACE_LANDMARKER", Path.home() / "tools/mediapipe/face_landmarker.task"))
FPS = 5.0
SQUINT_Q = 0.55   # 이 영상에서 아래 55%로 작게 뜬 눈을 '실눈'으로 본다

# FaceMesh 눈 랜드마크: (바깥 끝, 안쪽 끝, 위 두 점, 아래 두 점)
_L = (33, 133, (160, 158), (144, 153))
_R = (362, 263, (385, 387), (380, 373))


def _ear(lm, eye) -> float:
    import math
    a, b, ups, downs = eye
    d = lambda i, j: math.dist((lm[i].x, lm[i].y), (lm[j].x, lm[j].y))
    return (d(ups[0], downs[0]) + d(ups[1], downs[1])) / (2 * d(a, b) + 1e-6)


def measure(video: Path, work: Path) -> list[tuple[float, float]] | None:
    """[(원본 시각, 눈 뜬 정도 EAR)] — 얼굴을 못 찾은 프레임은 빠진다. 모델이 없으면 None."""
    cache = work / "eyes.json"
    if cache.exists() and cache.stat().st_mtime > video.stat().st_mtime:
        return [tuple(x) for x in json.loads(cache.read_text())]
    if not MODEL.exists():
        print("  눈 크기 측정 건너뜀: FaceLandmarker 모델 없음 (setup_tools.sh)")
        return None
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
    except ImportError:
        print("  눈 크기 측정 건너뜀: mediapipe 없음 (setup_tools.sh)")
        return None
    print("  눈 크기 측정 중...")
    opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)),
                                        running_mode=vision.RunningMode.VIDEO, num_faces=1)
    out = []
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, round(fps / FPS))
    with vision.FaceLandmarker.create_from_options(opts) as lmk:
        i = 0
        while True:
            ok = cap.grab()
            if not ok:
                break
            if i % step == 0:
                ok, fr = cap.retrieve()
                if ok:
                    small = cv2.resize(fr, (960, 540))
                    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
                    r = lmk.detect_for_video(img, int(i * 1000 / fps))
                    if r.face_landmarks:
                        lm = r.face_landmarks[0]
                        out.append((round(i / fps, 3), round((_ear(lm, _L) + _ear(lm, _R)) / 2, 4)))
            i += 1
    cap.release()
    cache.write_text(json.dumps(out))
    return out


def squint_ranges(samples: list[tuple[float, float]], q: float = SQUINT_Q,
                  min_len: float = 1.0) -> list[tuple[float, float]]:
    """원본 시각 기준 실눈 구간들. 0.4초 창의 최대값(깜빡임 제외)이 영상 분포의 q 분위수보다 낮은 곳."""
    if not samples:
        return []
    ts = [t for t, _ in samples]
    vs = [v for _, v in samples]
    half = 0.2
    mx, j0 = [], 0
    for i, t in enumerate(ts):
        while ts[j0] < t - half:
            j0 += 1
        j1 = i
        while j1 + 1 < len(ts) and ts[j1 + 1] <= t + half:
            j1 += 1
        mx.append(max(vs[j0:j1 + 1]))
    cut = sorted(mx)[int(len(mx) * q)]
    out, s = [], None
    gap = 1.5 / FPS
    for i, (t, v) in enumerate(zip(ts, mx)):
        low = v < cut
        if low and s is None:
            s = t
        cont = i + 1 < len(ts) and ts[i + 1] - t <= gap and mx[i + 1] < cut
        if s is not None and not cont:
            if t - s + 1 / FPS >= min_len:
                out.append((s, t + 1 / FPS))
            s = None
    # 0.6초 안으로 붙은 구간은 하나로
    merged = []
    for a, b in out:
        if merged and a - merged[-1][1] < 0.6:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged


def openness(samples: list[tuple[float, float]]):
    """원본 시각 → 0~1 점수 (영상 분포의 백분위). 얼굴이 없는 곳은 None."""
    if not samples:
        return lambda t: None
    vs = sorted(v for _, v in samples)
    import bisect
    ts = [t for t, _ in samples]

    def f(t: float):
        i = bisect.bisect_left(ts, t)
        near = [k for k in (i - 1, i) if 0 <= k < len(ts) and abs(ts[k] - t) <= 0.4]
        if not near:
            return None
        v = max(samples[k][1] for k in near)
        return bisect.bisect_left(vs, v) / len(vs)
    return f
