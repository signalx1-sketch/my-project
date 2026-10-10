"""ffmpeg로 클립을 자르고 줌을 넣어 이어 붙인 뒤, 자막/효과음/배경음악을 입혀 최종 영상을 만든다."""
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import broll
from .timeline import FPS, Clip, Timeline

W, H = 1920, 1080
SR = 48000
FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# 효과음 (ffmpeg 필터로 직접 합성한다). 같은 소리가 반복되면 귀에 거슬려서 종류마다 변형을 여러 개 두고 돌려 쓴다.
SFX_SOURCES = {
    "whoosh": [
        "anoisesrc=color=pink:duration=0.5:amplitude=0.6:seed=1,highpass=f=500,lowpass=f=6000,"
        "afade=t=in:d=0.28:curve=exp,afade=t=out:st=0.28:d=0.22,volume=0.55",
        "anoisesrc=color=brown:duration=0.6:amplitude=0.7:seed=2,highpass=f=250,lowpass=f=3500,"
        "afade=t=in:d=0.36:curve=exp,afade=t=out:st=0.36:d=0.24,volume=0.7",
        "anoisesrc=color=white:duration=0.4:amplitude=0.4:seed=3,highpass=f=1200,lowpass=f=9000,"
        "afade=t=in:d=0.22:curve=exp,afade=t=out:st=0.22:d=0.18,volume=0.45",
    ],
    "pop": [
        "aevalsrc='0.5*sin(2*PI*(500+1100*exp(-35*t))*t)*exp(-28*t)':d=0.16",
        "aevalsrc='0.45*sin(2*PI*(380+700*exp(-30*t))*t)*exp(-24*t)':d=0.18",
        "aevalsrc='0.4*sin(2*PI*(900+900*exp(-45*t))*t)*exp(-34*t)':d=0.13",
    ],
    "ding": [
        "aevalsrc='0.35*(sin(2*PI*1318.5*t)+0.5*sin(2*PI*1975.5*t))*exp(-5*t)':d=0.9",
    ],
}
SFX_GAIN = {"whoosh": 0.6, "pop": 0.45, "ding": 0.5}


def run(cmd: list[str]):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {' '.join(cmd[:8])} ...\n{r.stderr[-2000:]}")


def _zoom_filter(z: float) -> str:
    if z == 1.0:
        return f"scale={W}:{H}"
    # 얼굴이 화면 위쪽에 있으므로 세로는 위에서 35% 지점 기준으로 자른다
    return (f"crop=iw/{z}:ih/{z}:(iw-iw/{z})/2:(ih-ih/{z})*0.35,"
            f"scale={W}:{H}:flags=lanczos")


def render_clip(src: Path, c: Clip, i: int, work: Path, next_joined: bool) -> tuple[Path, Path]:
    # 파일명에 구간과 줌을 넣어서, 계획을 바꿔 다시 돌리면 바뀐 클립만 새로 만든다
    key = (f"{i:04d}_{c.kind}_{round(c.src_start * 1000)}_{round(c.src_end * 1000)}_{round(c.zoom * 100)}"
           f"_{int(c.joined)}{int(next_joined)}")
    v, a = work / f"v{key}.mp4", work / f"a{key}.wav"
    if v.exists() and a.exists():
        return v, a
    frames = round(c.dur * FPS)
    venc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-frames:v", str(frames), "-an"]
    if c.kind == "bumper":
        # 원본 첫 장면을 흐리고 어둡게 한 정지 화면 위에 제목을 띄운다
        vf = f"scale={W}:{H},boxblur=24:2,eq=brightness=-0.22:saturation=0.7,loop=-1:1:0"
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c.src_start}", "-i", str(src),
             "-vf", vf, *venc, str(v)])
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo",
             "-t", f"{c.dur}", "-c:a", "pcm_s16le", str(a)])
        return v, a
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c.src_start}", "-i", str(src), "-t", f"{c.dur + 0.1}",
         "-vf", _zoom_filter(c.zoom), *venc, str(v)])
    # 실제로 잘린 경계에만 짧은 페이드를 넣어 '틱' 소리를 막는다 (줌만 바뀌는 경계는 소리가 이어져야 한다)
    af = [f"apad", f"atrim=0:{c.dur}"]
    if not c.joined:
        af.append("afade=t=in:d=0.012")
    if not next_joined:
        af.append(f"afade=t=out:st={max(0.0, c.dur - 0.03)}:d=0.03")
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c.src_start}", "-i", str(src), "-t", f"{c.dur}",
         "-vn", "-ac", "2", "-ar", str(SR), "-af", ",".join(af), "-c:a", "pcm_s16le", str(a)])
    return v, a


def _concat(files: list[Path], out: Path, extra: list[str]):
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{f}'\n" for f in files))
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), *extra, str(out)])


def _read_pcm(cmd_input: list[str]) -> np.ndarray:
    pcm = subprocess.run(["ffmpeg", "-v", "error", *cmd_input, "-ac", "2", "-ar", str(SR),
                          "-f", "s16le", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(pcm, np.int16).reshape(-1, 2).astype(np.float32) / 32768.0


def build_sfx_track(events: list[tuple[float, str]], duration: float, out: Path):
    """효과음 이벤트를 한 트랙(wav)에 배치한다."""
    sounds = {k: [_read_pcm(["-f", "lavfi", "-i", src]) * SFX_GAIN[k] for src in srcs]
              for k, srcs in SFX_SOURCES.items()}
    track = np.zeros((int(duration * SR) + SR, 2), np.float32)
    used = {k: 0 for k in sounds}
    for t, kind in events:
        snd = sounds[kind][used[kind] % len(sounds[kind])]
        used[kind] += 1
        # 휙 소리는 화면 전환 직전에 정점이 오도록 조금 당긴다
        start = max(0, int((t - (0.25 if kind == "whoosh" else 0)) * SR))
        end = min(len(track), start + len(snd))
        track[start:end] += snd[: end - start]
    with wave.open(str(out), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.clip(track, -1, 1) * 32767).astype(np.int16).tobytes())


def render(src: Path, tl: Timeline, ass: str, sfx_events: list[tuple[float, str]], out: Path,
           work: Path, bgm: Path | None = None, jobs: int = 4, placements: list | None = None):
    clips_dir = work / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    print(f"  클립 {len(tl.clips)}개 자르는 중...")
    with ThreadPoolExecutor(jobs) as ex:
        nxt = [tl.clips[i + 1].joined if i + 1 < len(tl.clips) else False for i in range(len(tl.clips))]
        parts = list(ex.map(lambda i: render_clip(src, tl.clips[i], i, clips_dir, nxt[i]), range(len(tl.clips))))

    video = work / "video.mp4"
    speech = work / "speech.wav"
    _concat([p[0] for p in parts], video, ["-c", "copy"])
    _concat([p[1] for p in parts], speech, ["-c", "copy"])

    sfx = work / "sfx.wav"
    build_sfx_track(sfx_events, tl.duration, sfx)
    ass_path = work / "subs.ass"
    ass_path.write_text(ass, encoding="utf-8")

    inputs = ["-i", str(video), "-i", str(speech), "-i", str(sfx)]
    if bgm:
        inputs += ["-stream_loop", "-1", "-i", str(bgm)]
        # 배경음악은 대사보다 훨씬 작게 깔고, 말할 때 더 줄인다 (사이드체인 덕킹)
        audio = ("[1:a]asplit=2[sp][key];"
                 "[3:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.12[bg];"
                 "[bg][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[duck];"
                 "[sp][2:a][duck]amix=inputs=3:normalize=0:duration=first[mix];")
    else:
        audio = "[1:a][2:a]amix=inputs=2:normalize=0:duration=first[mix];"
    audio += "[mix]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"

    # 자료 화면을 먼저 얹고 그 위에 자막을 입힌다 (자료 화면 위에서도 자막이 보이게)
    base = "0:v"
    if placements:
        first = 4 if bgm else 3  # 영상, 대사, 효과음, (배경음악) 다음 입력부터
        inputs += broll.ffmpeg_inputs(placements)
        overlays, base = broll.overlay_filters(placements, first, "0:v")
        audio = overlays + ";" + audio
    vf = f"[{base}]ass={ass_path}:fontsdir={FONTS_DIR}[vout]"

    print("  자막과 소리를 입혀서 최종 렌더링 중...")
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", f"{vf};{audio}",
         "-map", "[vout]", "-map", "[aout]", "-t", f"{tl.duration}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart", str(out)])
