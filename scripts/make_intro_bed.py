"""영상 맨 앞 10초에 까는 소리 (2026-11-15, vidIQ 피드백: '처음 10초가 말소리뿐이면 첫 주 조회수가 덜 나온다').

- 0초: 낮게 깔리는 부드러운 '훔' 임팩트 (낮은 음이 내려가며 사라지고 공기 소리가 살짝)
- 0~10초: 따뜻한 패드 화음이 아주 작게 깔렸다가 9초부터 사라진다 (목소리보다 한참 아래)
배경음악은 넣지 않는다는 원칙은 그대로: 이건 처음 10초만 쓰는 사운드 디자인이다.

사용법: python scripts/make_intro_bed.py [출력.wav]  (기본 assets/sfx/intro_bed.wav)
"""
import sys
import wave
from pathlib import Path

import numpy as np

SR = 48000
LEN = 11.5


def lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):  # 한 극 저역 필터 (길이가 짧아 이 정도면 충분)
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def reverb(x, secs=2.2, mix=0.35, seed=1):
    rng = np.random.default_rng(seed)
    n = int(secs * SR)
    ir = rng.standard_normal(n) * np.exp(-np.linspace(0, 7, n))
    ir = lowpass(ir, 4000)
    ir /= np.sqrt((ir ** 2).sum())
    wet = np.convolve(x, ir)[: len(x)]
    return (1 - mix) * x + mix * wet


def pad(t):
    # A단조 add9 (A2 E3 C4 B4) — 부드럽고 차분한 화음, 좌우로 살짝 다르게 흔들린다
    freqs = [110.0, 164.81, 261.63, 493.88]
    out = []
    for ch, det in ((0, 0.997), (1, 1.003)):
        s = np.zeros_like(t)
        for k, f in enumerate(freqs):
            for h, amp in ((1, 1.0), (2, 0.35), (3, 0.12)):  # 배음 조금 (사인보다 따뜻하게)
                s += amp / (k + 1) ** 0.5 * np.sin(2 * np.pi * f * h * det * t + k + ch)
        s *= 1 + 0.15 * np.sin(2 * np.pi * 0.23 * t + ch)   # 천천히 숨 쉬듯
        s = lowpass(s, 1800)
        out.append(s)
    env = np.clip(t / 1.2, 0, 1) * np.clip((LEN - 1.0 - t) / 2.5, 0, 1)  # 1.2초 동안 들어와 9초부터 빠진다
    return np.stack(out, 1) * env[:, None]


def impact(t):
    f = 45 + 75 * np.exp(-t * 6)                        # 120Hz에서 45Hz로 내려간다
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.2)
    rng = np.random.default_rng(7)
    air = lowpass(rng.standard_normal(len(t)), 2500) * np.exp(-t * 5) * 0.6
    s = boom + air
    s = reverb(s, 2.5, 0.4)
    return np.stack([s, s * 0.96], 1) * np.clip(t / 0.01, 0, 1)[:, None]


def main(out: Path):
    t = np.arange(int(LEN * SR)) / SR
    p, im = pad(t), impact(t)
    p = np.stack([reverb(p[:, 0], 2.0, 0.3, 2), reverb(p[:, 1], 2.0, 0.3, 3)], 1)
    p *= 10 ** (-30 / 20) / np.sqrt((p[int(2 * SR):int(8 * SR)] ** 2).mean())   # 패드: RMS -30 dBFS
    im *= 10 ** (-9 / 20) / np.abs(im).max()                                      # 임팩트: 정점 -9 dBFS
    mix = np.clip(p + im, -1, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((mix * 32767).astype(np.int16).tobytes())
    print(f"{out} ({LEN}초)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "assets/sfx/intro_bed.wav")
