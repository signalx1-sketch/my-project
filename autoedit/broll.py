"""자료 화면(스톡 영상/이미지) 라이브러리를 읽고, 편집 계획에 따라 출력 타임라인에 배치한다.

두 가지 방식:
- full: 화면 전체를 3~5초 덮는다 (말소리와 자막은 계속)
- side: 얼굴 왼쪽에 작은 팝업으로 3~4초 띄운다
"""
import base64
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .cuts import Sentence
from .timeline import Timeline

IMAGE_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}

FULL_SEC = 4.0       # 전체 화면 길이
SIDE_SEC = 3.5       # 팝업 길이
FULL_GAP = 14.0      # 전체 화면 사이 최소 간격
SIDE_GAP = 8.0       # 팝업 사이 최소 간격
FULL_RATIO = 0.15    # 본편 중 전체 화면 비율 상한
AVOID_AFTER_CHAPTER = 1.8  # 챕터 제목이 크게 뜨는 동안은 피한다


@dataclass
class Asset:
    id: str          # 라이브러리 폴더 기준 상대 경로
    path: Path
    kind: str        # "image" | "video"
    duration: float  # 이미지는 0
    desc: str        # 내용 설명 (파일명 + 태그)


@dataclass
class Placement:
    asset: Asset
    mode: str        # "full" | "side"
    start: float     # 출력 타임라인 기준
    dur: float


def _probe_duration(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _name_words(rel: str) -> str:
    stem = re.sub(r"\.[^.]+$", "", rel)
    return re.sub(r"[_\-/\\.]+", " ", stem).strip()


def scan_library(folder: Path) -> list[Asset]:
    """폴더 안의 이미지/영상을 읽는다. tags.json({상대경로: 설명})이 있으면 설명에 더한다."""
    tags_file = folder / "tags.json"
    tags = json.loads(tags_file.read_text(encoding="utf-8")) if tags_file.exists() else {}
    assets = []
    for p in sorted(folder.rglob("*")):
        ext = p.suffix.lower()
        if not p.is_file() or ext not in IMAGE_EXT | VIDEO_EXT:
            continue
        rel = p.relative_to(folder).as_posix()
        kind = "image" if ext in IMAGE_EXT else "video"
        dur = _probe_duration(p) if kind == "video" else 0.0
        if kind == "video" and dur < 1.5:
            continue
        desc = " / ".join(x for x in (_name_words(rel), tags.get(rel, "")) if x)
        assets.append(Asset(rel, p, kind, dur, desc))
    return assets


def thumbnails_b64(a: Asset) -> list[str]:
    """Claude에게 보여줄 작은 JPEG 목록. 영상은 장면이 바뀔 수 있어서 앞/중간/뒤 3장을 뽑는다."""
    times = [a.duration * f for f in (0.15, 0.5, 0.85)] if a.kind == "video" else [None]
    out = []
    for t in times:
        cmd = ["ffmpeg", "-v", "error"] + (["-ss", f"{t:.2f}"] if t is not None else [])
        cmd += ["-i", str(a.path), "-frames:v", "1", "-vf", "scale=512:-2", "-f", "image2", "-c:v", "mjpeg", "-"]
        out.append(base64.standard_b64encode(subprocess.run(cmd, check=True, capture_output=True).stdout).decode())
    return out


def tag_with_claude(folder: Path, assets: list[Asset], model: str) -> list[Asset]:
    """tags.json에 설명이 없는 파일을 Claude가 보고 한 줄 설명을 붙인다. 키가 없으면 건너뛴다."""
    import anthropic

    tags_file = folder / "tags.json"
    tags = json.loads(tags_file.read_text(encoding="utf-8")) if tags_file.exists() else {}
    todo = [a for a in assets if a.id not in tags]
    if not todo:
        return assets
    client = anthropic.Anthropic()
    print(f"  자료 {len(todo)}개 내용 파악 중 (Claude)...")
    for a in todo:
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=2000,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": [
                    *[{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}
                      for b in thumbnails_b64(a)],
                    {"type": "text", "text": ("피부과 유튜브 영상의 자료 화면으로 쓸 "
                                              + ("영상의 앞/중간/뒤 장면이다. " if a.kind == "video" else "이미지다. "))
                                             + "무엇이 보이는지 "
                                             "검색용 한국어 키워드 위주로 한 줄(40자 이내)로만 답해라. "
                                             "제품이면 제품명, 신체 부위, 증상, 장면을 포함해라."},
                ]}],
            )
        except anthropic.APIError as e:
            print(f"  {a.id}: 설명 실패 ({e})")
            continue
        if resp.stop_reason == "refusal":
            continue
        text = next((b.text for b in resp.content if b.type == "text"), "").strip()
        if text:
            tags[a.id] = text
    tags_file.write_text(json.dumps(tags, ensure_ascii=False, indent=1), encoding="utf-8")
    return scan_library(folder)


def catalog_prompt(assets: list[Asset]) -> str:
    lines = [f"- {a.id} ({'영상 %.0f초' % a.duration if a.kind == 'video' else '이미지'}): {a.desc}" for a in assets]
    return "\n".join(lines)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[가-힣A-Za-z0-9]{2,}", text)}


def suggest_with_rules(sentences: list[Sentence], assets: list[Asset]) -> list[dict]:
    """API 없이: 파일명/태그의 단어가 문장에 나오면 그 문장에 배치한다."""
    out = []
    for a in assets:
        toks = _tokens(a.desc)
        for s in sentences:
            if any(t in s.text for t in toks):
                out.append({"at": s.idx, "asset": a.id, "mode": "full" if a.kind == "video" else "side"})
                break
    return out


def _out_time(src_t: float, tl: Timeline) -> float | None:
    for c in tl.clips:
        if c.kind == "body" and c.src_start - 0.05 <= src_t < c.src_end:
            return c.out_start + max(0.0, src_t - c.src_start)
    return None


def place(plan_broll: list[dict], sentences: list[Sentence], assets: list[Asset], tl: Timeline) -> list[Placement]:
    """계획의 (문장 번호, 자료) 목록을 출력 시간으로 바꾸고, 간격/비율 규칙에 맞지 않는 것은 버린다."""
    by_id = {a.id: a for a in assets}
    body = [c for c in tl.clips if c.kind == "body"]
    if not body:
        return []
    body_start = body[0].out_start
    end_limit = tl.duration - 6.5  # 마지막 구독 안내 전까지
    chapter_starts = [c.out_start for c in tl.clips if c.chapter is not None]
    full_budget = (tl.duration - body_start) * FULL_RATIO

    placed: list[Placement] = []
    used: set[str] = set()
    for item in sorted(plan_broll, key=lambda x: x["at"]):
        a = by_id.get(item.get("asset", ""))
        if not a or a.id in used or not 0 <= item["at"] < len(sentences):
            continue
        mode = item.get("mode", "full")
        t = _out_time(sentences[item["at"]].start, tl)
        if t is None:
            continue
        # 챕터 제목이 크게 뜨는 구간은 건너뛴다
        for cs in chapter_starts:
            if cs <= t < cs + AVOID_AFTER_CHAPTER:
                t = cs + AVOID_AFTER_CHAPTER
        dur = SIDE_SEC if mode == "side" else FULL_SEC
        if a.kind == "video":
            dur = min(dur, a.duration - 0.2)
        if t < body_start + 2 or t + dur > end_limit or dur < 1.5:
            continue
        gap = SIDE_GAP if mode == "side" else FULL_GAP
        if any(p.mode == mode and abs(p.start - t) < gap for p in placed):
            continue
        if any(p.start < t + dur + 0.5 and t < p.start + p.dur + 0.5 for p in placed):
            continue
        if mode == "full":
            if sum(p.dur for p in placed if p.mode == "full") + dur > full_budget:
                continue
            # 다음 챕터 제목과 겹치지 않게
            if any(t < cs < t + dur for cs in chapter_starts):
                continue
        placed.append(Placement(a, mode, round(t, 3), round(dur, 3)))
        used.add(a.id)
    return sorted(placed, key=lambda p: p.start)


# --- 렌더링용 ffmpeg 필터 ---

SIDE_BOX = (720, 520)  # 팝업 최대 크기
SIDE_X = 70            # 얼굴 왼쪽
FADE = 0.2


def ffmpeg_inputs(placements: list[Placement]) -> list[str]:
    args = []
    for p in placements:
        a = p.asset
        if a.kind == "image":
            args += ["-loop", "1", "-framerate", "30", "-t", f"{p.dur}", "-i", str(a.path)]
        else:
            ss = max(0.0, min(a.duration - p.dur, a.duration * 0.25))
            args += ["-ss", f"{ss:.2f}", "-t", f"{p.dur}", "-i", str(a.path)]
    return args


def overlay_filters(placements: list[Placement], first_input: int, base: str) -> tuple[str, str]:
    """기존 영상 [base] 위에 자료 화면을 얹는 filter_complex 조각과 결과 라벨을 돌려준다."""
    parts, cur = [], base
    for n, p in enumerate(placements):
        i = first_input + n
        d = p.dur
        fades = (f"format=yuva420p,fade=t=in:st=0:d={FADE}:alpha=1,"
                 f"fade=t=out:st={max(0, d - FADE)}:d={FADE}:alpha=1")
        if p.mode == "full":
            if p.asset.kind == "image":
                frames = int(d * 30)
                # 사진은 천천히 확대해서 정지 화면처럼 보이지 않게 한다
                prep = (f"scale=3840:2160:force_original_aspect_ratio=increase,crop=3840:2160,"
                        f"zoompan=z='1+0.0012*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080:fps=30")
            else:
                prep = "fps=30,scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"
            pos = "0:0"
        else:
            bw, bh = SIDE_BOX
            prep = (f"fps=30,scale={bw - 16}:{bh - 16}:force_original_aspect_ratio=decrease,"
                    f"pad=iw+16:ih+16:8:8:white")
            pos = f"{SIDE_X}:(H-h)/2-40"
        parts.append(f"[{i}:v]{prep},setsar=1,trim=duration={d},{fades},"
                     f"setpts=PTS-STARTPTS+{p.start}/TB[br{n}]")
        nxt = f"vb{n}"
        parts.append(f"[{cur}][br{n}]overlay={pos}:eof_action=pass[{nxt}]")
        cur = nxt
    return ";".join(parts), cur


def _safe_name(desc: str, max_len: int = 40) -> str:
    words = re.findall(r"[가-힣A-Za-z0-9]+", desc)
    name = ""
    for w in words:
        if len(name) + len(w) + 1 > max_len:
            break
        name = f"{name}_{w}" if name else w
    return name or "자료"


def rename_by_tags(folder: Path) -> int:
    """tags.json의 설명으로 파일 이름을 바꾼다. 되돌릴 수 있게 rename_log.json에 원래 이름을 남긴다."""
    tags_file = folder / "tags.json"
    if not tags_file.exists():
        return 0
    tags = json.loads(tags_file.read_text(encoding="utf-8"))
    log_file = folder / "rename_log.json"
    log = json.loads(log_file.read_text(encoding="utf-8")) if log_file.exists() else {}
    new_tags, n = {}, 0
    for rel, desc in tags.items():
        old = folder / rel
        if not old.exists():
            continue
        target = old.with_name(_safe_name(desc) + old.suffix.lower())
        k = 2
        while target.exists() and target != old:
            target = old.with_name(f"{_safe_name(desc)}_{k}{old.suffix.lower()}")
            k += 1
        new_rel = target.relative_to(folder).as_posix()
        if target != old:
            old.rename(target)
            log[new_rel] = log.pop(rel, rel)
            n += 1
        new_tags[new_rel] = desc
    tags_file.write_text(json.dumps(new_tags, ensure_ascii=False, indent=1), encoding="utf-8")
    log_file.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    return n
