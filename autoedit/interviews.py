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
# 인터뷰 음성 인식에 자주 나오는 오인식 (단어 단위로 바꾼다). 클립별 "fix"가 뒤에 덮어쓴다 (2026-11-21)
INTERVIEW_FIX = {
    "자연수액": "자윤수액", "자연수육": "자윤수액", "자연수색": "자윤수액", "자연수행": "자윤수액", "자연책": "자윤수액", "자연색": "자윤수액",
    "자연수에": "자윤수액", "자연수의": "자윤수액",
    "스킨눅스": "스킨룩스", "스킨록스": "스킨룩스", "스킨룹스": "스킨룩스", "스킨롭스": "스킨룩스", "스킨옥스": "스킨룩스",
    "스킨럭스": "스킨룩스", "스킨업스": "스킨룩스", "스킨로스": "스킨룩스", "스킨십스": "스킨룩스",
    "스티로이드": "스테로이드", "스테레이드": "스테로이드", "스테롤드": "스테로이드", "세로이드": "스테로이드",
    "히로이드": "스테로이드",
    "사이포렌": "사이폴엔", "폐혈증": "패혈증", "독시사이클링": "독시사이클린", "술안트라": "수란트라",
    "VBM": "브이빔", "VBIM": "브이빔", "V빔": "브이빔", "LED": "엘리델", "레이더": "레이저", "연골": "연고", "\ufffd": "",  # 음성 인식이 깨진 글자를 낼 때가 있다
}


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
    ws = [OutWord(subtitles.fix_text(w["w"], {**INTERVIEW_FIX, **clip.get("fix", {})}), w["s"] - clip["start"], w["e"] - clip["start"], "body")
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
    for i, ln in enumerate(lines):
        text = " ".join(w.text for w in ln).strip()
        nxt = lines[i + 1][0].s if i + 1 < len(lines) else dur
        end = min(dur, nxt, ln[-1].e + 0.25)  # 다음 줄과 겹쳐 두 줄이 뜨지 않게
        ev.append(f"Dialogue: 1,{subtitles.ts(max(0, ln[0].s))},{subtitles.ts(end)},Cap,,0,0,0,,"
                  f"{subtitles.esc(text.rstrip('.,'))}")
    ass_path.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


def _render_clip(clip: dict, lib: Path, words_dir: Path, gain_db: float, out: Path, tmp: Path, bg_lib: Path | None = None):
    """mode "audio"(기본): 유튜브본은 자막·스톡이 구워져 있고 얼굴도 안 나와서 목소리만 쓴다.
    화면은 문장에 맞는 자료 영상(bg)을 흐리고 어둡게 깔고 초록 파형 + 이름표 + 우리 자막.
    mode "video": 인터뷰 화면을 쓴다. 유튜브본처럼 아래에 자막이 구워져 있으면 keep_h(예 890)로 그 띠를 잘라낸다."""
    if clip.get("mode", "audio") == "audio":
        return _render_audio_clip(clip, lib, words_dir, gain_db, out, tmp, bg_lib)
    src = lib / clip["video"]
    wj = words_dir / f"{Path(clip['video']).stem}.words.json"
    words = json.loads(wj.read_text(encoding="utf-8")) if wj.exists() else []
    ass = tmp / f"{clip['id']}.ass"
    _clip_ass(clip, words, ass)
    dur = clip["end"] - clip["start"]
    # 유튜브본은 아래쪽 띠(높이 83~94%)에 자막이 구워져 있다: 위쪽 keep_h만 남기고 16:9로 키워 자막을 잘라낸다 (2026-11-21)
    kh = int(clip.get("keep_h", 0))
    crop = (f"scale=-2:1080,crop={round(kh * 16 / 9) // 2 * 2}:{kh}:(iw-{round(kh * 16 / 9) // 2 * 2})/2:0,"
            if kh else "")
    vf = (f"{crop}scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080,setsar=1,fps=30,"
          f"ass={ass}:fontsdir={Path(__file__).resolve().parent.parent / 'assets' / 'fonts'},"
          f"fade=t=in:st=0:d={FADE},fade=t=out:st={dur - FADE:.3f}:d={FADE}")
    af = (f"aresample=48000,aformat=channel_layouts=stereo,volume={gain_db:.2f}dB,"
          f"afade=t=in:st=0:d={FADE},afade=t=out:st={dur - FADE:.3f}:d={FADE}")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{clip['start']:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                    "-vf", vf, "-af", af, "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)], check=True)


def _render_audio_clip(clip, lib, words_dir, gain_db, out, tmp, bg_lib):
    src = lib / clip["video"]
    wj = words_dir / f"{Path(clip['video']).stem}.words.json"
    words = json.loads(wj.read_text(encoding="utf-8")) if wj.exists() else []
    ass = tmp / f"{clip['id']}.ass"
    _clip_ass(clip, words, ass)
    dur = clip["end"] - clip["start"]
    fonts = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    bg = (bg_lib / clip["bg"]) if bg_lib and clip.get("bg") and (bg_lib / clip["bg"]).exists() else None
    inputs = ["-ss", f"{clip['start']:.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
    if bg:
        inputs += ["-stream_loop", "-1", "-i", str(bg)]
        base = (f"[1:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=30,"
                f"trim=duration={dur:.3f},gblur=sigma=18,eq=brightness=-0.22:saturation=0.8[bg]")
    else:
        base = f"color=c=0x101412:s=1920x1080:r=30:d={dur:.3f}[bg]"
    fc = [base,
          # 목소리 파형: 가운데 가로 띠, 초록
          f"[0:a]aresample=48000,showwaves=s=1200x220:mode=cline:rate=30:colors=0x52B788|0x52B788:scale=sqrt,"
          f"format=yuva420p,colorchannelmixer=aa=0.85[wv]",
          f"[bg][wv]overlay=(W-w)/2:(H-h)/2-40:shortest=1,ass={ass}:fontsdir={fonts},"
          f"fade=t=in:st=0:d={FADE},fade=t=out:st={dur - FADE:.3f}:d={FADE},format=yuv420p[v]",
          f"[0:a]aresample=48000,aformat=channel_layouts=stereo,volume={gain_db:.2f}dB,"
          f"afade=t=in:st=0:d={FADE},afade=t=out:st={dur - FADE:.3f}:d={FADE}[a]"]
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
                    "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)], check=True)


def insert(video: Path, work: Path, plan: dict, lib: Path, catalog: Path, out: Path, words_dir: Path,
           bg_lib: Path | None = None) -> list[tuple]:
    """본편 video에 plan["interviews"]의 클립을 끼워 out으로 저장. 넣은 (출력 시각, 클립 id, 길이) 목록을 돌려준다."""
    items = plan.get("interviews") or []
    if not items:
        return []
    cat = {c["id"]: c for c in json.loads(catalog.read_text(encoding="utf-8"))}
    clips_tl = json.loads((work / "timeline.json").read_text(encoding="utf-8"))
    starts = _sentence_starts(work)
    target = _loudness(video)
    cuts_at = []
    it_bg = {it["clip"]: it.get("bg") for it in items}  # 계획에서 클립마다 깔 자료 영상을 바꿀 수 있다
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
            _render_clip({**c, **({"bg": it_bg[c["id"]]} if it_bg.get(c["id"]) else {})}, lib, words_dir, max(-12, min(12, gain)), cp, tmp, bg_lib)
            segs.append(("main", prev, t))
            segs.append(("clip", cp))
            prev = t
        segs.append(("main", prev, None))
        # 본편 조각과 인터뷰 클립을 한 번에 이어 붙인다 (본편은 다시 인코딩)
        # 본편 조각마다 입력을 따로 연다 (한 입력을 여러 번 trim하면 영상이 통째로 메모리에 쌓여 죽는다)
        inputs, fc, labels, k = [], [], [], 0
        for s in segs:
            n = inputs.count("-i")
            if s[0] == "main":
                a, b = s[1], s[2]
                inputs += ["-ss", f"{a:.3f}"] + (["-to", f"{b:.3f}"] if b else []) + ["-i", str(video)]
                fc.append(f"[{n}:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p[v{k}]")
                fc.append(f"[{n}:a]asetpts=PTS-STARTPTS,aresample=48000[a{k}]")
            else:
                inputs += ["-i", str(s[1])]
                fc.append(f"[{n}:v]setpts=PTS-STARTPTS,format=yuv420p[v{k}]")
                fc.append(f"[{n}:a]asetpts=PTS-STARTPTS[a{k}]")
            labels.append(f"[v{k}][a{k}]")
            k += 1
        fc.append("".join(labels) + f"concat=n={k}:v=1:a=1[v][a]")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)
    placed, shift = [], 0.0
    for t, c in cuts_at:
        placed.append((round(t + shift, 2), c["id"], round(c["end"] - c["start"], 2)))
        shift += c["end"] - c["start"]
    return placed


def scan_overlays(src: Path, start: float, end: float, fps: float = 2.0) -> dict:
    """유튜브본 클립에 구워진 글자 위치를 잰다 (2026-11-21).

    유튜브본은 아래 자막 말고도 강조 글씨·질문 상자가 높이 72~85%에 뜨거나, 가운데에 질문 상자가 뜬다.
    0.5초마다 프레임을 뽑아 글자 상자를 찾고(RapidOCR 검출만), 아래쪽 글자를 다 잘라낼 keep_h와
    가운데·위쪽 글자가 뜬 프레임 비율을 돌려준다. keep_h가 KEEP_MIN보다 작아야 하면 too_low."""
    import numpy as np
    from rapidocr import RapidOCR   # pip install rapidocr (검출 모델만 쓴다)
    eng = RapidOCR()
    W, H = 960, 540
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(src),
                          "-vf", f"fps={fps},scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    top_cut, center, upper = 1.0, 0, 0
    for f in frames:
        boxes = eng(np.ascontiguousarray(f), use_det=True, use_cls=False, use_rec=False).boxes
        boxes = [] if boxes is None else boxes
        c_hit = u_hit = False
        for b in boxes:
            ys = [p[1] / H for p in b]
            y0, y1 = min(ys), max(ys)
            if y1 - y0 < 0.02:
                continue
            cy = (y0 + y1) / 2
            if cy > 0.6:
                top_cut = min(top_cut, y0)
            elif cy < 0.09:
                u_hit = True
            else:
                c_hit = True
        center += c_hit
        upper += u_hit
    n = max(1, len(frames))
    kh = min(KEEP_MAX, int(top_cut * 1080) - 14) // 2 * 2
    return {"keep_h": max(kh, KEEP_MIN), "too_low": kh < KEEP_MIN,
            "center_text": round(center / n, 2), "top_text": round(upper / n, 2)}


KEEP_MAX, KEEP_MIN = 890, 760   # 890 = 자막 띠 위, 760보다 더 자르면 화면이 너무 커져 흐려진다


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
    b.add_argument("--bg-lib", help="배경으로 깔 자료 영상 폴더 (클립의 bg)")
    c = sub.add_parser("scan", help="클립 목록의 유튜브본 클립마다 구워진 글자를 재서 keep_h·screen 표시를 적는다")
    c.add_argument("--assets", required=True, help="인터뷰 영상 폴더")
    c.add_argument("--catalog", default="data/interview_clips.json")
    c.add_argument("--all", action="store_true", help="이미 잰 클립도 다시 잰다")
    x = ap.parse_args()
    if x.cmd == "index":
        for v in x.videos:
            print("ok", index(Path(v), Path(x.out)))
    elif x.cmd == "scan":
        cat = Path(x.catalog)
        clips = json.loads(cat.read_text(encoding="utf-8"))
        for cl in clips:
            if cl.get("mode") != "video" or not cl["video"].startswith("yt_") or ("screen" in cl and not x.all):
                continue
            r = scan_overlays(Path(x.assets) / cl["video"], cl["start"], cl["end"])
            cl["keep_h"] = r["keep_h"]
            cl["screen"] = r
            print(cl["id"], r, flush=True)
            cat.write_text(json.dumps(clips, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        plan = json.loads(Path(x.plan).read_text(encoding="utf-8"))
        placed = insert(Path(x.video), Path(x.work), plan, Path(x.assets), Path(x.catalog), Path(x.out), Path(x.words),
                        Path(x.bg_lib) if x.bg_lib else None)
        for p in placed:
            print("  인터뷰", p)
        print("ok", x.out)


if __name__ == "__main__":
    sys.exit(main())
