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

FULL_SEC = 3.0       # 전체 화면 길이 (짧게 자주 바꿔야 지루하지 않다)
SIDE_SEC = 3.5       # 팝업 길이
FULL_GAP = 5.0       # 전체 화면 시작 사이 최소 간격
SIDE_GAP = 10.0      # 팝업 사이 최소 간격
FULL_RATIO = 0.5     # 본편 중 전체 화면 비율 상한
FACE_MIN = 1.8       # 자료 화면 사이에 얼굴이 최소 이만큼은 보이게
FAMILY_RECENT = 5    # 최근 이만큼의 자료와 같은 종류(예: 욕조 홍조 여성 사진들)는 다시 쓰지 않는다
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


# 파일명에 흔히 붙지만 대본 내용과는 상관없는 단어
STOP = {"영상", "사진", "도표", "캡처", "확인필요", "여성", "남성", "클로즈업", "정면", "측면", "미소", "표정",
        "얼굴", "피부", "제품", "설명", "비교", "모습", "장면", "하는", "있는", "바르는", "보는", "든", "들고",
        "3D", "일러스트", "vs", "논문", "기사", "유튜브", "썸네일", "목록",
        "구독", "좋아요", "피켓", "흔들기", "알림"}  # 끝인사 문장에 엉뚱한 자료가 붙지 않게
FILL_EVERY = 6.0  # 긴 문장은 이 간격마다 채움용 전체 화면 후보를 더 낸다
# 화면 전체보다 얼굴 옆 팝업이 어울리는 자료 (글씨가 있거나 가리키는 대상)
SIDE_HINTS = ("도표", "캡처", "전후", "치료전", "치료후", "제품", "논문", "현미경")


def _content_tokens(a: Asset) -> list[str]:
    return [t for t in re.findall(r"[가-힣A-Za-z0-9]{2,}", a.desc) if t not in STOP and not t.isdigit()]


def family(a: Asset) -> str:
    """비슷한 자료끼리 묶는 이름. '사진_욕조_홍조_여성_정면_3' → '사진 욕조 홍조'."""
    kind = a.id.split("/")[-1].split("_")[0]
    return " ".join([kind] + _content_tokens(a)[:2])


def default_mode(a: Asset) -> str:
    return "side" if a.kind == "image" and any(h in a.id for h in SIDE_HINTS) else "full"


def suggest_with_rules(sentences: list[Sentence], assets: list[Asset]) -> list[dict]:
    """API 없이: 파일명/태그의 단어가 문장에 나오면 그 문장에 배치할 후보로 낸다.

    드문 단어가 맞을수록 점수가 높다. 문장마다 점수 순으로 여러 후보를 내고,
    맞는 자료가 없는 문장에는 영상 전체 주제와 가까운 자료를 낮은 순위로 낸다 (전체 화면이 자주 바뀌도록).
    실제로 쓸지는 place()가 간격/다양성 규칙으로 고른다.
    """
    import math

    toks = {a.id: set(_content_tokens(a)) for a in assets}
    df: dict[str, int] = {}
    for ts in toks.values():
        for t in ts:
            df[t] = df.get(t, 0) + 1
    n = len(assets) or 1

    def score(a: Asset, text: str) -> float:
        return sum(math.log(1 + n / df[t]) for t in toks[a.id] if t in text)

    whole = " ".join(s.text for s in sentences)
    topic = sorted(assets, key=lambda a: -score(a, whole))
    topic = [a for a in topic if score(a, whole) > 0][:150]

    out = []
    for i, s in enumerate(sentences):
        ctx = s.text
        ranked = sorted(((score(a, ctx), a) for a in assets), key=lambda x: -x[0])
        # 팝업(도표/캡처)은 정확히 맞을 때만, 전체 화면은 조금 느슨하게
        local = [a for sc, a in ranked if sc >= (4.0 if default_mode(a) == "side" else 2.0)][:4]
        for a in local:
            out.append({"at": s.idx, "asset": a.id, "mode": default_mode(a)})
        # 주제 자료는 전체 화면용으로만, 문장마다 다른 것부터 돌려가며 낸다. 긴 문장은 중간에도 낸다
        fill = [a for a in topic if default_mode(a) == "full" and a not in local]
        offsets = [k * FILL_EVERY for k in range(max(1, int((s.end - s.start) // FILL_EVERY) + 1))]
        for j, off in enumerate(offsets):
            for k in range(min(3, len(fill))):
                a = fill[(i * 7 + j * 3 + k) % len(fill)]
                out.append({"at": s.idx, "offset": off, "asset": a.id, "mode": "full", "filler": True})
    return out


def _out_time(src_t: float, tl: Timeline) -> float | None:
    """원본 시간을 출력 시간으로. 잘려 나간 무음 구간이면 바로 다음 클립 시작으로 당긴다."""
    for c in tl.clips:
        if c.kind == "body" and c.src_start - 0.05 <= src_t < c.src_end:
            return c.out_start + max(0.0, src_t - c.src_start)
    nxt = [c for c in tl.clips if c.kind == "body" and src_t < c.src_start < src_t + 1.5]
    return min(nxt, key=lambda c: c.src_start).out_start if nxt else None


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
    # 같은 문장 안에서는 계획에 적힌 순서(점수 순)를 지키고, 내용이 맞는 자료를 채움용보다 먼저 본다
    order = sorted(range(len(plan_broll)), key=lambda k: (plan_broll[k]["at"], float(plan_broll[k].get("offset", 0)),
                                                          bool(plan_broll[k].get("filler")), k))
    for item in (plan_broll[k] for k in order):
        a = by_id.get(item.get("asset", ""))
        if not a or a.id in used or not 0 <= item["at"] < len(sentences):
            continue
        if family(a) in {family(p.asset) for p in placed[-FAMILY_RECENT:]}:
            continue
        mode = item.get("mode", "full")
        t = _out_time(sentences[item["at"]].start + float(item.get("offset", 0)), tl)
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
        if any(p.start < t + dur + FACE_MIN and t < p.start + p.dur + FACE_MIN for p in placed):
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


def _dims(path: Path) -> tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0:s=x", str(path)], capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split("\n")[0].split("x")
        return int(w), int(h)
    except ValueError:
        return 1920, 1080


def ffmpeg_inputs(placements: list[Placement]) -> list[str]:
    args = []
    for p in placements:
        a = p.asset
        if a.kind == "image" and p.mode == "full":
            args += ["-i", str(a.path)]  # 한 장만 읽고 zoompan이 필요한 프레임 수만큼 만든다
        elif a.kind == "image":
            args += ["-loop", "1", "-framerate", "30", "-t", f"{p.dur}", "-i", str(a.path)]
        else:
            ss = max(0.0, min(a.duration - p.dur, a.duration * 0.25))
            args += ["-ss", f"{ss:.2f}", "-t", f"{p.dur}", "-i", str(a.path)]
    return args


def _full_image(path: Path, d: float) -> str:
    """사진을 화면 전체에 천천히 확대하며 보여준다. 16:9와 많이 다르면(도표, 전후 사진, 제품) 잘리지 않게
    흐린 배경 위에 원본 비율로 얹는다."""
    frames = int(d * 30)
    w, h = _dims(path)
    zoom = (f"zoompan=z='1+0.0010*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}"
            f":s=1920x1080:fps=30")
    if 1.5 <= w / max(h, 1) <= 2.0:
        return f"scale=3840:2160:force_original_aspect_ratio=increase,crop=3840:2160,{zoom}"
    return ("split=2[fa][fb];"
            "[fa]scale=960:540:force_original_aspect_ratio=increase,crop=960:540,boxblur=20:2,"
            "eq=brightness=-0.15,scale=3840:2160[fbg];"
            "[fb]scale=3600:2000:force_original_aspect_ratio=decrease[ffg];"
            f"[fbg][ffg]overlay=(W-w)/2:(H-h)/2,{zoom}")


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
                # 분기(split)가 들어가는 필터는 라벨을 이 자료 번호로 고유하게 바꾼다
                prep = _full_image(p.asset.path, d).replace("[f", f"[f{n}_")
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
