"""ffmpeg/ffprobe 기반 미디어 분석."""
import json
import re
import subprocess

import numpy as np

SAMPLE_RATE = 16000


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=True, **kw)


def probe(path: str) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", path]).stdout
    info = json.loads(out)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("영상 스트림이 없는 파일입니다.")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    w, h = int(video["width"]), int(video["height"])
    # 세로로 촬영된 폰 영상은 rotate 메타데이터로 표시됨
    rotation = 0
    for sd in video.get("side_data_list", []):
        if "rotation" in sd:
            rotation = abs(int(sd["rotation"]))
    if rotation in (90, 270):
        w, h = h, w
    return {
        "duration": float(info["format"]["duration"]),
        "width": w,
        "height": h,
        "has_audio": has_audio,
    }


def load_audio(path: str) -> np.ndarray:
    """16kHz 모노 float32 PCM."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-f", "s16le", "-"], capture_output=True, check=True)
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def audio_envelope(path: str, hop: float = 0.5) -> list[float]:
    """hop 초 단위 음량(dB) 배열."""
    pcm = load_audio(path)
    n = int(SAMPLE_RATE * hop)
    if len(pcm) < n:
        return []
    frames = pcm[: len(pcm) // n * n].reshape(-1, n)
    rms = np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-6
    return (20 * np.log10(rms)).round(2).tolist()


def scene_changes(path: str, threshold: float = 0.3) -> list[float]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-an",
         "-vf", f"scale=160:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True)
    return [round(float(m), 2) for m in re.findall(r"pts_time:([\d.]+)", proc.stderr)]


def silences(path: str, noise_db: float = -35, min_dur: float = 0.45) -> list[tuple[float, float]]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-vn",
         "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    return list(zip(starts, ends))
