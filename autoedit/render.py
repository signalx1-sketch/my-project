"""ffmpeg로 클립을 자르고 줌을 넣어 이어 붙인 뒤, 자막/효과음/배경음악을 입혀 최종 영상을 만든다."""
import os
import subprocess
import sys
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


SFX_EVERY = 30.0      # 본편 효과음은 30초에 하나 꼴 (1분에 1~2개)
SFX_EDGE = 30.0       # 처음/끝 30초는 조금 더 자주 (인트로, 엔딩)
SFX_EDGE_EVERY = 6.0
SFX_PRIORITY = {"ding": 0, "whoosh": 1, "pop": 2}


def thin_sfx(events: list[tuple[float, str]], duration: float) -> list[tuple[float, str]]:
    """효과음이 너무 잦으면 거슬린다. 중요한 것(딩 > 휙 > 팝)부터 남기고 간격이 좁은 것은 뺀다."""
    kept: list[tuple[float, str]] = []
    for t, kind in sorted(events, key=lambda e: (SFX_PRIORITY.get(e[1], 9), e[0])):
        edge = t < SFX_EDGE or t > duration - SFX_EDGE
        gap = SFX_EDGE_EVERY if edge else SFX_EVERY
        if all(abs(t - k) >= gap for k, _ in kept):
            kept.append((t, kind))
    return sorted(kept)


OPENMONTAGE_DIRS = [os.environ.get("OPENMONTAGE_DIR", ""), str(Path.home() / "tools" / "OpenMontage"),
                    "/home/user/tools/OpenMontage"]


# 입 클릭(쩝, 짭 하는 짧은 충격음) 제거 + 배경 잡음 약하게 걷어내기. 말소리는 건드리지 않도록 약하게 건다
# 잡음 제거를 세게 걸거나(nr 10, 잡음 추적) 고음을 깎으면 목소리가 먹먹하고 물속처럼 들린다 (2026-10-26 지적)
MOUTH_NOISE_AF = "adeclick=w=55:o=75:t=2,afftdn=nr=6:nf=-45"


def clean_mouth_noise(speech: Path, out: Path) -> Path:
    run(["ffmpeg", "-v", "error", "-y", "-i", str(speech), "-af", MOUTH_NOISE_AF, "-ar", str(SR), "-ac", "2",
         "-c:a", "pcm_s16le", str(out)])
    print("  입 클릭, 잡음 정리")
    return out


# 목소리 다듬기: 저역 웅웅거림만 걷고 가볍게 압축한다. OpenMontage clean_speech 프리셋(게이트 + 13kHz 위 차단 +
# 압축 + 음량 보정)은 최종 음량 보정과 겹쳐 소리가 출렁이고 먹먹해서 쓰지 않는다
VOICE_AF = "highpass=f=70,acompressor=threshold=-22dB:ratio=2:attack=15:release=250:makeup=1.5"


def normalize_speech(speech: Path, out: Path, target: float = -14.0) -> Path:
    """음량을 두 번에 나눠 맞춘다 (측정 후 일정한 배율로). 한 번에 맞추면 구간마다 음량이 오르내린다."""
    import json as _json
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(speech), "-af",
                        f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = _json.loads(r.stderr[r.stderr.rfind("{"):r.stderr.rfind("}") + 1])
    run(["ffmpeg", "-v", "error", "-y", "-i", str(speech), "-af",
         f"loudnorm=I={target}:TP=-1.5:LRA=11:linear=true:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
         f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}",
         "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(out)])
    return out


def enhance_voice(speech: Path, out: Path) -> Path:
    """OpenMontage의 audio_enhance(VOICE_AF: 저역 정리, 가벼운 압축)로 목소리를 다듬는다.
    OpenMontage가 없으면 원본을 그대로 쓴다."""
    om = next((Path(d) for d in OPENMONTAGE_DIRS if d and (Path(d) / "tools" / "audio" / "audio_enhance.py").exists()), None)
    if om is None:
        return speech
    code = ("import sys,json;sys.path.insert(0,sys.argv[1]);from tools.audio.audio_enhance import AudioEnhance;"
            "r=AudioEnhance().execute({'input_path':sys.argv[2],'output_path':sys.argv[3],'custom_af':sys.argv[4],"
            "'audio_codec':'pcm_s16le'});print(json.dumps({'ok':r.success,'error':getattr(r,'error',None)}))")
    tmp = out.with_name(out.stem + "_om.wav")
    r = subprocess.run([sys.executable, "-c", code, str(om), str(speech), str(tmp), VOICE_AF],
                       capture_output=True, text=True, cwd=om)
    if r.returncode != 0 or not tmp.exists():
        print(f"  OpenMontage 음성 정리 실패, 원본 음성을 씁니다: {(r.stderr or r.stdout)[-300:]}")
        return speech
    # 편집기 기준(48kHz 스테레오)으로 맞춘다
    run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(out)])
    tmp.unlink(missing_ok=True)
    print("  OpenMontage로 목소리 정리 (저역 정리, 가벼운 압축)")
    return out


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
           f"_{int(c.joined)}{int(next_joined)}_{round(c.speed * 100)}")
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
    # 원본 끝을 넘는 클립(마지막 말의 여운)도 프레임 수가 모자라지 않게 마지막 장면을 늘려 둔다
    vf = _zoom_filter(c.zoom) + ",tpad=stop_mode=clone:stop_duration=2"
    if c.speed != 1.0:
        vf = f"setpts=(PTS-STARTPTS)/{c.speed},fps={FPS}," + vf
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c.src_start}", "-i", str(src), "-t", f"{c.src_dur + 0.1}",
         "-vf", vf, *venc, str(v)])
    # 실제로 잘린 경계에만 짧은 페이드를 넣어 '틱' 소리를 막는다 (줌만 바뀌는 경계는 소리가 이어져야 한다)
    af = ([f"atempo={c.speed}"] if c.speed != 1.0 else []) + [f"apad", f"atrim=0:{c.dur}"]
    if not c.joined:
        af.append("afade=t=in:d=0.012")
    if not next_joined:
        af.append(f"afade=t=out:st={max(0.0, c.dur - 0.03)}:d=0.03")
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c.src_start}", "-i", str(src), "-t", f"{c.src_dur}",
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
           work: Path, bgm: Path | None = None, jobs: int = 4, placements: list | None = None,
           tabs: tuple | None = None):
    """tabs: (탭 그림 목록, [(파트, 시작, 끝)]) — 위쪽 진행 표시 (progress 모듈)."""
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

    speech = clean_mouth_noise(speech, work / "speech_declick.wav")
    speech = enhance_voice(speech, work / "speech_clean.wav")
    speech = normalize_speech(speech, work / "speech_norm.wav")
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
    # 원본이 말끝에서 바로 끝나는 경우가 있어 영상 끝 0.3초는 소리를 부드럽게 줄인다
    # 대사는 이미 음량을 맞춰 두었다. 여기서 다시 loudnorm을 걸면 구간마다 음량이 출렁인다 (봉우리만 살짝 누른다)
    audio += f"[mix]alimiter=limit=0.84:attack=5:release=50,afade=t=out:st={max(0.0, tl.duration - 0.3):.3f}:d=0.3[aout]"

    # 자료 화면을 먼저 얹고 그 위에 자막을 입힌다 (자료 화면 위에서도 자막이 보이게)
    base = "0:v"
    if placements:
        first = 4 if bgm else 3  # 영상, 대사, 효과음, (배경음악) 다음 입력부터
        inputs += broll.ffmpeg_inputs(placements)
        masks = broll.transition_masks(work / "masks") if any(p.tin or p.tout for p in placements) else None
        overlays, base = broll.overlay_filters(placements, first, "0:v", masks)
        audio = overlays + ";" + audio
    if tabs and tabs[1]:
        from . import progress
        first = 3 + (1 if bgm else 0) + (len(placements) if placements else 0)
        args, filt, base = progress.overlay_filters(tabs[0], tabs[1], first, base)
        inputs += args
        audio = filt + ";" + audio
    vf = f"[{base}]ass={ass_path}:fontsdir={FONTS_DIR}[vout]"

    print("  자막과 소리를 입혀서 최종 렌더링 중...")
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", f"{vf};{audio}",
         "-map", "[vout]", "-map", "[aout]", "-t", f"{tl.duration}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart", str(out)])
