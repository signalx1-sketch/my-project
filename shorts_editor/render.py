"""ffmpeg로 9:16 쇼츠 렌더링."""
import subprocess
from pathlib import Path

from .captions import Part
from .config import FONTS_DIR, OUT_FPS, OUT_H, OUT_W


def _layout_chain(layout: str, zoom: float, src_w: int, src_h: int, tag: str) -> str:
    """입력 [{tag}in] → 출력 [{tag}] 세로 화면 필터."""
    if layout == "crop" or src_h >= src_w:  # 이미 세로 영상이면 꽉 채우기
        zw, zh = int(OUT_W * zoom) // 2 * 2, int(OUT_H * zoom) // 2 * 2
        return (f"[{tag}in]scale={zw}:{zh}:force_original_aspect_ratio=increase,"
                f"crop={OUT_W}:{OUT_H},setsar=1[{tag}]")
    zw = int(OUT_W * zoom) // 2 * 2
    return (f"[{tag}in]split[{tag}b][{tag}f];"
            f"[{tag}b]scale={OUT_W // 4}:{OUT_H // 4}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W // 4}:{OUT_H // 4},boxblur=8:2,eq=brightness=-0.12:saturation=1.2,"
            f"scale={OUT_W}:{OUT_H},setsar=1[{tag}bg];"
            f"[{tag}f]scale={zw}:-2,crop={OUT_W}:ih,setsar=1[{tag}fg];"
            f"[{tag}bg][{tag}fg]overlay=(W-w)/2:(H-h)/2[{tag}]")


def build_filter(parts: list[Part], *, layout: str, src_w: int, src_h: int, total: float,
                 ass_name: str, progress_bar: bool, audio_input: int) -> str:
    chains, concat_in = [], []
    for i, p in enumerate(parts):
        chains.append(f"[0:v]trim=start={p.start:.3f}:end={p.end:.3f},setpts=PTS-STARTPTS,"
                      f"fps={OUT_FPS}[v{i}in]")
        chains.append(_layout_chain(layout, p.zoom, src_w, src_h, f"v{i}"))
        fade = min(0.03, p.dur / 4)
        chains.append(f"[{audio_input}:a]atrim=start={p.start:.3f}:end={p.end:.3f},asetpts=PTS-STARTPTS,"
                      f"aformat=sample_rates=48000:channel_layouts=stereo,"
                      f"afade=t=in:d={fade:.3f},afade=t=out:st={max(0, p.dur - fade):.3f}:d={fade:.3f}[a{i}]")
        concat_in.append(f"[v{i}][a{i}]")
    chains.append(f"{''.join(concat_in)}concat=n={len(parts)}:v=1:a=1[vc][ac]")
    post = f"[vc]ass={ass_name}:fontsdir={FONTS_DIR}"
    if progress_bar:
        post += (f",drawbox=x=0:y=ih-14:w=iw:h=14:color=black@0.45:t=fill"
                 f",drawbox=x=0:y=ih-14:w='iw*t/{total:.3f}':h=14:color=0xFFD400@0.95:t=fill")
    post += ",format=yuv420p[vout]"
    chains.append(post)
    chains.append("[ac]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
    return ";\n".join(chains)


def render(src: str, out_path: Path, parts: list[Part], ass_text: str, *, layout: str,
           src_w: int, src_h: int, has_audio: bool, progress_bar: bool) -> None:
    workdir = out_path.parent
    stem = out_path.stem
    ass_name = f"{stem}.ass"
    (workdir / ass_name).write_text(ass_text, encoding="utf-8")
    total = sum(p.dur for p in parts)
    filt = build_filter(parts, layout=layout, src_w=src_w, src_h=src_h, total=total,
                        ass_name=ass_name, progress_bar=progress_bar,
                        audio_input=0 if has_audio else 1)
    script = workdir / f"{stem}.filter.txt"
    script.write_text(filt, encoding="utf-8")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(Path(src).resolve())]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += ["-filter_complex_script", script.name, "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(OUT_FPS),
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.3f}",
            out_path.name]
    proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 렌더링 실패:\n{proc.stderr[-2000:]}")


def cover_image(video: Path, out: Path, at: float = 0.6) -> None:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at}",
                    "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)], check=True)
