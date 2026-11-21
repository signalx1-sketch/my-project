"""환자 인터뷰 클립 (2026-11-21).

1) 색인: 인터뷰 영상을 음성 인식해 문장 목록을 만든다 (`python -m autoedit.interviews index 영상.mp4 ...`).
   문장 목록을 읽고 쓸 만한 말을 골라 `data/interview_clips.json`에 적는다:
   {"id", "video": 자료 폴더 기준 경로, "start", "end", "text", "label": 화면 아래 이름표, "tags": [...], "topic"}
2) 끼워 넣기: 계획 JSON의 "interviews": [{"at": 문장 번호, "clip": 클립 id}]를 보고, 렌더한 본편의
   그 문장이 시작하기 직전에 환자 목소리 그대로의 클립을 끼워 넣는다 (본편은 멈추고 뒤로 밀린다).
   클립에는 같은 모양의 말 자막(Pretendard 반투명 박스)과 '실제 환자 인터뷰' 이름표를 굽고, 음량은 본편에 맞춘다.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import cuts, subtitles
from .subtitles import OutWord

FADE = 0.12          # 클립 앞뒤 화면·소리 페이드
LEAD = 0.15          # 문장 시작보다 이만큼 앞에서 자른다 (말 첫소리를 먹지 않게)
LABEL_PREFIX = "실제 환자 인터뷰"


# ---------- 1) 색인 ----------
def index(video: Path, out_dir: Path) -> Path:
    from .transcribe import transcribe
    out_dir.mkdir(parents=True, exist_ok=True)
    words = transcribe(video, out_dir / f"{video.stem}.words.json")
    sents = cuts.split_sentences(words, max_gap=0.9)
    txt = out_dir / f"{video.stem}.sentences.txt"
    txt.write_text("\n".join(f"[{s.idx}] ({s.start:.1f}-{s.end:.1f}) {s.text}" for s in sents), encoding="utf-8")
    return txt


# ---------- 2) 끼워 넣기 ----------
def _out_time(src_t: float, clips: list[dict]) -> float | None:
    for c in clips:
        if c["kind"] == "body" and c["src_start"] - 0.05 <= src_t < c["src_end"]:
            return c["out_start"] + (max(src_t, c["src_start"]) - c["src_start"]) / c.get("speed", 1.0)
    nxt = [c for c in clips if c["kind"] == "body" and src_t < c["src_start"] < src_t + 1.5]
    return min(nxt, key=lambda c: c["src_start"])["out_start"] if nxt else None


def _sentence_starts(work: Path) -> dict[int, float]:
    out = {}
    for line in (work / "sentences.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\[(\d+)\] \(([\d.]+)s\)", line)
        if m:
            out[int(m.group(1))] = float(m.group(2))
    return out


def _loudness(path: Path, start: float = 0, dur: float | None = None) -> float:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start}"] + (["-t", f"{dur}"] if dur else []) + \
          ["-i", str(path), "-vn", "-af", "ebur128", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    return float(m[-1]) if m else -16.0


def _clip_ass(clip: dict, words: list[dict], ass_path: Path):
    """클립 구간의 말 자막 + 왼쪽 아래 이름표. 시간은 클립 시작 기준."""
    st = subtitles.CAPTION_STYLES[subtitles.DEFAULT_CAPTION_STYLE]
    ws = [OutWord(subtitles.fix_text(w["w"], clip.get("fix", {})), w["s"] - clip["start"], w["e"] - clip["start"], "body")
          for w in words if w["s"] >= clip["start"] - 0.05 and w["e"] <= clip["end"] + 0.05]
    lines = subtitles.group_lines(ws, st["max_chars"], st["max_words"])
    head = subtitles.HEADER.format(cap=st["font"], capline=st["line"], big="Pretendard")
    head = head.replace("[Events]", "Style: IvTag,Pretendard,40,&H00FFFFFF,&H00FFFFFF,&H3060A040,&H3060A040,-1,0,0,0,"
                                    "100,100,0,0,3,16,0,7,64,64,60,1\n"
                                    "Style: IvSub,Pretendard,34,&H00FFFFFF,&H00FFFFFF,&H50101010,&H50101010,0,0,0,0,"
                                    "100,100,0,0,3,12,0,7,64,64,128,1\n\n[Events]")
    dur = clip["end"] - clip["start"]
    ev = [f"Dialogue: 2,{subtitles.ts(0)},{subtitles.ts(dur)},IvTag,,0,0,0,,{LABEL_PREFIX}",
          f"Dialogue: 2,{subtitles.ts(0)},{subtitles.ts(dur)},IvSub,,0,0,0,,{subtitles.esc(clip.get('label', ''))}"]
    for ln in lines:
        text = " ".join(w.text for w in ln).strip()
        ev.append(f"Dialogue: 1,{subtitles.ts(max(0, ln[0].s))},{subtitles.ts(min(dur, ln[-1].e + 0.25))},Cap,,0,0,0,,"
                  f"{subtitles.esc(text.rstrip('.,'))}")
    ass_path.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


def _render_clip(clip: dict, lib: Path, words_dir: Path, gain_db: float, out: Path, tmp: Path):
    src = lib / clip["video"]
    wj = words_dir / f"{Path(clip['video']).stem}.words.json"
    words = json.loads(wj.read_text(encoding="utf-8")) if wj.exists() else []
    ass = tmp / f"{clip['id']}.ass"
    _clip_ass(clip, words, ass)
    dur = clip["end"] - clip["start"]
    vf = (f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=30,"
          f"ass={ass}:fontsdir={Path(__file__).resolve().parent.parent / 'assets' / 'fonts'},"
          f"fade=t=in:st=0:d={FADE},fade=t=out:st={dur - FADE:.3f}:d={FADE}")
    af = (f"aresample=48000,aformat=channel_layouts=stereo,volume={gain_db:.2f}dB,"
          f"afade=t=in:st=0:d={FADE},afade=t=out:st={dur - FADE:.3f}:d={FADE}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{clip['start']:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                    "-vf", vf, "-af", af, "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)], check=True)


def insert(video: Path, work: Path, plan: dict, lib: Path, catalog: Path, out: Path, words_dir: Path) -> list[tuple]:
    """본편 video에 plan["interviews"]의 클립을 끼워 out으로 저장. 넣은 (출력 시각, 클립 id, 길이) 목록을 돌려준다."""
    items = plan.get("interviews") or []
    if not items:
        return []
    cat = {c["id"]: c for c in json.loads(catalog.read_text(encoding="utf-8"))}
    clips_tl = json.loads((work / "timeline.json").read_text(encoding="utf-8"))
    starts = _sentence_starts(work)
    target = _loudness(video)
    cuts_at = []
    for it in items:
        c = cat.get(it["clip"])
        if not c or it["at"] not in starts:
            print(f"  [인터뷰] 건너뜀: {it}")
            continue
        t = _out_time(starts[it["at"]], clips_tl)
        if t is None:
            continue
        cuts_at.append((max(0.0, t - LEAD), c))
    cuts_at.sort(key=lambda x: x[0])
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        segs, prev = [], 0.0
        for i, (t, c) in enumerate(cuts_at):
            gain = target - _loudness(lib / c["video"], c["start"], c["end"] - c["start"])
            cp = tmp / f"iv{i}.mp4"
            _render_clip(c, lib, words_dir, max(-12, min(12, gain)), cp, tmp)
            segs.append(("main", prev, t))
            segs.append(("clip", cp))
            prev = t
        segs.append(("main", prev, None))
        # 본편 조각과 인터뷰 클립을 한 번에 이어 붙인다 (본편은 다시 인코딩)
        inputs, fc, labels, k = ["-i", str(video)], [], [], 0
        for s in segs:
            if s[0] == "main":
                a, b = s[1], s[2]
                tr = f"trim=start={a:.3f}" + (f":end={b:.3f}" if b else "")
                atr = f"atrim=start={a:.3f}" + (f":end={b:.3f}" if b else "")
                fc.append(f"[0:v]{tr},setpts=PTS-STARTPTS,fps=30,format=yuv420p[v{k}]")
                fc.append(f"[0:a]{atr},asetpts=PTS-STARTPTS,aresample=48000[a{k}]")
            else:
                inputs += ["-i", str(s[1])]
                n = len(inputs) // 2 - 1
                fc.append(f"[{n}:v]setpts=PTS-STARTPTS,format=yuv420p[v{k}]")
                fc.append(f"[{n}:a]asetpts=PTS-STARTPTS[a{k}]")
            labels.append(f"[v{k}][a{k}]")
            k += 1
        fc.append("".join(labels) + f"concat=n={k}:v=1:a=1[v][a]")
        subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)
    placed, shift = [], 0.0
    for t, c in cuts_at:
        placed.append((round(t + shift, 2), c["id"], round(c["end"] - c["start"], 2)))
        shift += c["end"] - c["start"]
    return placed


def main():
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("index", help="인터뷰 영상을 음성 인식해 문장 목록을 만든다")
    a.add_argument("videos", nargs="+")
    a.add_argument("--out", default="data/interviews")
    b = sub.add_parser("insert", help="렌더한 본편에 인터뷰 클립을 끼워 넣는다")
    b.add_argument("video")
    b.add_argument("-o", "--out", required=True)
    b.add_argument("--work", required=True)
    b.add_argument("--plan", required=True)
    b.add_argument("--assets", required=True)
    b.add_argument("--catalog", default="data/interview_clips.json")
    b.add_argument("--words", default="data/interviews")
    x = ap.parse_args()
    if x.cmd == "index":
        for v in x.videos:
            print("ok", index(Path(v), Path(x.out)))
    else:
        plan = json.loads(Path(x.plan).read_text(encoding="utf-8"))
        placed = insert(Path(x.video), Path(x.work), plan, Path(x.assets), Path(x.catalog), Path(x.out), Path(x.words))
        for p in placed:
            print("  인터뷰", p)
        print("ok", x.out)


if __name__ == "__main__":
    sys.exit(main())
