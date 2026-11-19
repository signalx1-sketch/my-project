"""가편 원본의 잡음(쉬~ 하는 화이트 노이즈, 방 울림, 웅 소리)을 AI(DeepFilterNet3)로 걷어 낸다 (2026-11-19).

편집기의 가벼운 잡음 제거(afftdn nr 6)로는 잡음 바닥이 -53 dB쯤인 녹음을 못 다룬다: 말 사이 빈 곳이 무음으로 잡히지 않아
빈 공간 컷도 안 된다. 이 스크립트로 오디오만 먼저 정리한 영상을 만든 뒤 편집기에 넣는다.

사용법: ~/tools/earshot/.venv/bin/python scripts/denoise.py 원본.mp4 결과.mp4 [--limit 20]
  --limit: 잡음을 최대 몇 dB까지 줄일지 (12 약, 20 중간(기본), 0이면 끝까지). 너무 세면 목소리가 로봇처럼 될 수 있다.
준비: earshot venv(torch) + `pip install deepfilternet torchaudio` + 모델(~/.cache/DeepFilterNet/DeepFilterNet3).
  GitHub에서 모델을 못 받으면 Hugging Face fal/DeepFilterNet3의 config.ini, model.safetensors를 받아
  checkpoints/model_120.ckpt.best로 저장한다 (setup_tools.sh의 DENOISE=1).
"""
import argparse
import subprocess
import sys
import tempfile
import types
from dataclasses import dataclass
from pathlib import Path

MODEL = Path.home() / ".cache/DeepFilterNet/DeepFilterNet3"


def _shim_torchaudio():
    """DeepFilterNet이 찾는 옛 torchaudio.backend.common.AudioMetaData 자리를 채운다 (새 torchaudio에는 없다)."""
    try:
        import torchaudio.backend.common  # noqa: F401
        return
    except Exception:
        pass
    import torchaudio

    @dataclass
    class AudioMetaData:
        sample_rate: int = 0
        num_frames: int = 0
        num_channels: int = 0
        bits_per_sample: int = 0
        encoding: str = ""
    backend = types.ModuleType("torchaudio.backend")
    common = types.ModuleType("torchaudio.backend.common")
    common.AudioMetaData = AudioMetaData
    backend.common = common
    sys.modules["torchaudio.backend"] = backend
    sys.modules["torchaudio.backend.common"] = common
    torchaudio.backend = backend


def denoise_wav(src: Path, dst: Path, limit: float | None):
    _shim_torchaudio()
    import soundfile as sf
    import torch
    from df.enhance import enhance, init_df
    model, st, _ = init_df(str(MODEL))
    x, sr = sf.read(str(src), dtype="float32")
    assert sr == st.sr(), sr
    out = []
    step = sr * 60  # 1분씩 나눠 처리 (메모리)
    for i in range(0, len(x), step):
        a = torch.from_numpy(x[i:i + step]).unsqueeze(0)
        out.append(enhance(model, st, a, atten_lim_db=limit).squeeze(0).numpy())
    import numpy as np
    sf.write(str(dst), np.concatenate(out), sr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--limit", type=float, default=20)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as d:
        wav, clean = Path(d) / "a.wav", Path(d) / "b.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.src, "-vn", "-ac", "1", "-ar", "48000", str(wav)], check=True)
        denoise_wav(wav, clean, a.limit or None)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.src, "-i", str(clean), "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ac", "2", a.out], check=True)
    print("ok", a.out)


if __name__ == "__main__":
    main()
