"""렌더 결과 검수: 화면 가운데(머리말과 자막 자리 제외)가 거의 비어 있는 장면이 1초 이상 이어지는 곳을 찾는다.
슬라이드 카드가 빈 화면이나 반쯤 가려진 채 멈춘 경우를 잡기 위한 것.

사용법: python scripts/qc_cards.py 결과.mp4
"""
import subprocess
import sys

import numpy as np

W, H, FPS = 192, 108, 4  # 작게 줄여 1초에 4장씩 본다


def main(path: str):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={FPS},scale={W}:{H},format=rgb24",
                          "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
    # 빨간 글씨도 글자로 보도록 색 채널 중 가장 밝은 값을 쓴다
    frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).max(axis=3)
    mid = frames[:, int(H * 0.14):int(H * 0.80), :]
    bright = (mid > 140).mean(axis=(1, 2))   # 글자(밝은 픽셀) 비율
    dark = mid.mean(axis=(1, 2)) < 40         # 어두운 카드 배경
    empty = dark & (bright < 0.004)
    runs, start = [], None
    for i, e in enumerate(list(empty) + [False]):
        if e and start is None:
            start = i
        elif not e and start is not None:
            if i - start >= FPS:  # 1초 이상
                runs.append((start / FPS, i / FPS))
            start = None
    for a, b in runs:
        print(f"빈 화면 의심 {int(a // 60)}:{a % 60:05.2f} ~ {int(b // 60)}:{b % 60:05.2f}")
    print(f"검사 {len(frames)}장, 의심 구간 {len(runs)}곳")
    return len(runs)


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1]) else 0)
