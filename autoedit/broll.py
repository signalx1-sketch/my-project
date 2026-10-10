"""자료 화면(스톡 영상/이미지) 라이브러리를 읽고, 편집 계획에 따라 출력 타임라인에 배치한다.

두 가지 방식:
- slide: 발표 슬라이드를 화면 전체에 (그 동안 아래 자막은 숨긴다. 슬라이드 글자가 자막 역할)
- full: 화면 전체를 2~4초 덮는다 (말소리와 자막은 계속)
- side: 얼굴 왼쪽에 작은 팝업으로 3~4초 띄운다
"""
import base64
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .cuts import Sentence
from .timeline import Timeline, snap

IMAGE_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}

FACE_TARGET = 0.2    # 본편에서 얼굴이 그대로 보이는 시간 비율 목표 (나머지는 슬라이드/자료 화면)
FULL_SEC = 3.2       # 전체 화면 자료 길이 (짧게 자주 바꿔야 지루하지 않다)
FULL_MIN = 2.0
FULL_MAX = 4.5
SLIDE_MAX = 6.0      # 슬라이드는 다음 슬라이드가 나올 때까지, 최대 이만큼
SLIDE_MIN = 1.5
SIDE_SEC = 3.5       # 팝업 길이
SIDE_MIN = 2.2
SIDE_GAP = 8.0       # 팝업 사이 최소 간격
FACE_KEEP = 1.5      # 자료 화면 사이에 얼굴을 보여 줄 때는 최소 이만큼
FACE_LONG = 7.0      # 얼굴만 이보다 오래 이어지면 비율과 상관없이 자료를 끼운다
FACE_MIN = 1.0       # 이보다 짧은 얼굴 조각은 남기지 않는다 (앞뒤 자료를 늘려서 붙인다)
FAMILY_RECENT = 5    # 최근 이만큼의 자료와 같은 종류(예: 욕조 홍조 여성 사진들)는 다시 쓰지 않는다
AVOID_AFTER_CHAPTER = 1.8  # 챕터 제목이 크게 뜨는 동안은 얼굴로 둔다


@dataclass
class Asset:
    id: str          # 라이브러리 폴더 기준 상대 경로
    path: Path
    kind: str        # "image" | "video" | "slide"
    duration: float  # 이미지는 0
    desc: str        # 내용 설명 (파일명 + 태그)


@dataclass
class Placement:
    asset: Asset
    mode: str        # "full" | "side" | "slide"
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


def _subtract(a: float, b: float, cover: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """[a, b]에서 cover 구간들을 뺀 나머지 구간들."""
    out, cur = [], a
    for s, e in sorted(cover):
        if e <= cur or s >= b:
            continue
        if s > cur:
            out.append((cur, s))
        cur = max(cur, e)
    if cur < b:
        out.append((cur, b))
    return out


class _Board:
    """출력 타임라인 위에 자료 화면을 놓아 가며 빈 곳(얼굴이 보이는 곳)을 계산한다."""

    def __init__(self, tl: Timeline, assets: list[Asset]):
        body = [c for c in tl.clips if c.kind == "body"]
        self.start = body[0].out_start if body else tl.duration
        self.end = tl.duration - 6.5  # 마지막 구독 안내 전까지
        self.chapters = [c.out_start for c in tl.clips if c.chapter is not None]
        self.placed: list[Placement] = []
        self.used: set[str] = set()

    def full_cover(self) -> list[tuple[float, float]]:
        return [(p.start, p.start + p.dur) for p in self.placed if p.mode in ("full", "slide")]

    def face_windows(self) -> list[tuple[float, float]]:
        return _subtract(self.start, self.end, self.full_cover())

    def free_at(self, t: float) -> tuple[float, float] | None:
        for w in self.face_windows():
            if w[0] - 1e-6 <= t < w[1]:
                return w
        return None

    def recent_family(self, a: Asset) -> bool:
        stock = [p for p in sorted(self.placed, key=lambda p: p.start) if p.asset.kind != "slide"]
        return family(a) in {family(p.asset) for p in stock[-FAMILY_RECENT:]}

    def add(self, a: Asset, mode: str, t: float, dur: float):
        # 프레임에 맞춰서 이어 붙인 자료 사이에 얼굴이 한 프레임 비치지 않게 한다
        t0, t1 = snap(t), snap(t + dur)
        self.placed.append(Placement(a, mode, t0, round(t1 - t0, 4)))
        self.used.add(a.id)


def place(plan_broll: list[dict], sentences: list[Sentence], assets: list[Asset], tl: Timeline,
          slides: list[dict] = (), face_target: float = FACE_TARGET) -> list[Placement]:
    """자료 화면을 출력 시간에 배치한다.

    1. 슬라이드: 그 내용을 말하는 순간부터 다음 슬라이드 전까지 (최대 SLIDE_MAX초)
    2. 얼굴 옆 팝업: 얼굴이 보이는 곳에 (그 자리는 얼굴로 남긴다)
    3. 계획에서 내용이 맞는 전체 화면 자료: 빈 곳에 FULL_SEC초씩 (앞 자료와 바로 붙어도 된다)
    4. 얼굴이 보이는 시간이 본편의 face_target을 넘으면, 긴 얼굴 구간부터 채움용 자료로 덮는다
    plan_broll 항목: {at, offset, asset, mode, filler?}. slides 항목: {asset: Asset, t: 원본 초}
    """
    by_id = {a.id: a for a in assets}
    bd = _Board(tl, assets)
    if bd.start >= bd.end:
        return []

    def out_t(item) -> float | None:
        if not 0 <= item["at"] < len(sentences):
            return None
        return _out_time(sentences[item["at"]].start + float(item.get("offset", 0)), tl)

    # 1. 슬라이드
    st = sorted(((_out_time(x["t"], tl), x["asset"]) for x in slides), key=lambda x: (x[0] is None, x[0] or 0))
    st = [(t, a) for t, a in st if t is not None and bd.start <= t < bd.end - SLIDE_MIN]
    for k, (t, a) in enumerate(st):
        nxt = st[k + 1][0] if k + 1 < len(st) else bd.end
        dur = min(SLIDE_MAX, nxt - t, bd.end - t)
        if dur >= SLIDE_MIN:
            bd.add(a, "slide", t, dur)

    # 챕터 시작은 얼굴로 (큰 챕터 제목이 뜬다). 슬라이드가 이미 덮은 챕터는 제외
    keep_face = [(c, c + AVOID_AFTER_CHAPTER) for c in bd.chapters if bd.free_at(c)]
    keep_face.append((bd.start, bd.start + 1.5))

    def fit_full(a: Asset, t: float, want: float) -> tuple[float, float] | None:
        """t 근처에서 덮을 수 있는 곳(얼굴 구간 중 챕터 시작/팝업 자리 제외)에 들어갈 (시작, 길이).
        이미 덮인 곳이면 2.5초 안쪽으로 뒤에 빈 곳을 찾는다."""
        spots = [x for s0, e0 in bd.face_windows() for x in _subtract(s0, e0, keep_face)]
        w = next((x for x in spots if x[0] - 1e-6 <= t < x[1]), None)
        if w is None:
            w = next((x for x in spots if t < x[0] < t + 2.5), None)
            if w is None:
                return None
            t = w[0]
        cap = a.duration - 0.2 if a.kind == "video" else FULL_MAX
        dur = min(want, w[1] - t, cap)
        # 남는 얼굴 조각이 너무 짧으면 자료를 늘려서 붙인다 (0.5초 얼굴은 깜빡임처럼 보인다)
        if 0 < w[1] - (t + dur) < FACE_MIN and w[1] - t <= cap:
            dur = w[1] - t
        if 0 < t - w[0] < FACE_MIN and t + dur - w[0] <= cap:
            dur, t = t + dur - w[0], w[0]
        return (t, dur) if dur >= FULL_MIN else None

    # 계획에 적힌 자료를 먼저, 규칙으로 보탠 후보(auto)는 나중에 본다
    order = sorted(range(len(plan_broll)), key=lambda k: (bool(plan_broll[k].get("filler")),
                                                          bool(plan_broll[k].get("auto")), plan_broll[k]["at"],
                                                          float(plan_broll[k].get("offset", 0)), k))
    items = [plan_broll[k] for k in order]

    # 2. 얼굴 옆 팝업 (얼굴이 보이는 곳에, 서로 SIDE_GAP 이상 떨어지게)
    for item in items:
        a = by_id.get(item.get("asset", ""))
        if item.get("mode") != "side" or not a or a.id in bd.used or a.kind == "video" and a.duration < SIDE_MIN:
            continue
        t = out_t(item)
        w = bd.free_at(t) if t is not None else None
        if not w or any(p.mode == "side" and abs(p.start - t) < SIDE_GAP for p in bd.placed):
            continue
        t = max(t, w[0] + 0.3)
        dur = min(SIDE_SEC, w[1] - t - 0.2)
        if dur >= SIDE_MIN:
            bd.add(a, "side", t, dur)
            keep_face.append((t - 0.3, t + dur + 0.2))

    # 3. 내용이 맞는 전체 화면 자료
    for item in items:
        a = by_id.get(item.get("asset", ""))
        if item.get("filler") or item.get("mode", "full") != "full" or not a or a.id in bd.used:
            continue
        t = out_t(item)
        if t is None or bd.recent_family(a):
            continue
        fit = fit_full(a, t, FULL_SEC)
        if fit:
            bd.add(a, "full", *fit)

    # 4. 얼굴 비율 맞추기: 긴 얼굴 구간 가운데를 채움용 전체 화면으로 덮는다
    body_len = bd.end - bd.start
    fillers = [x for x in items if x.get("mode", "full") == "full"]
    for _ in range(400):
        windows = bd.face_windows()
        face = sum(e - s for s, e in windows)
        # 덮을 수 있는 부분 = 얼굴 구간에서 꼭 얼굴로 남길 곳(챕터 시작, 팝업)을 뺀 곳
        # 팝업/챕터 시작 바로 뒤라면 얼굴은 이미 보였으니 바로 덮어도 된다
        spots = [x for s, e in windows for x in _subtract(s, e, keep_face)]
        after_keep = lambda s: any(abs(ke - s) < 0.05 for _, ke in keep_face)
        spots = [(s, e) for s, e in spots if e - s >= FULL_MIN + (0 if after_keep(s) else FACE_KEEP)]
        # 목표 비율에 닿아도 얼굴만 오래 나오는 구간은 끊어 준다
        if not spots or (face <= body_len * face_target and max(e - s for s, e in spots) <= FACE_LONG):
            break
        s, e = max(spots, key=lambda w: w[1] - w[0])
        t = s if s <= bd.start + 0.01 or after_keep(s) else s + FACE_KEEP
        dur = min(FULL_SEC, e - t)
        if 0 < e - (t + dur) < FACE_MIN:
            dur = min(FULL_MAX, e - t)
        pick = _pick_filler(fillers, by_id, bd, sentences, tl, t)
        if not pick:
            keep_face.append((s, e))  # 쓸 자료가 없으면 이 구간은 얼굴로 둔다
            continue
        if pick.kind == "video":
            dur = min(dur, pick.duration - 0.2)
        if dur < FULL_MIN:
            keep_face.append((s, e))
            continue
        bd.add(pick, "full", t, dur)

    # 5. 자료 사이에 남은 아주 짧은 얼굴 조각(깜빡임)은 앞 자료를 늘려서 메운다
    for s0, e0 in bd.face_windows():
        if e0 - s0 >= FACE_MIN or any(ks < e0 and s0 < ke for ks, ke in keep_face):
            continue
        prev = next((p for p in bd.placed if p.mode != "side" and abs(p.start + p.dur - s0) < 0.05), None)
        if prev and (prev.asset.kind != "video" or prev.dur + (e0 - s0) <= prev.asset.duration - 0.2):
            prev.dur = round(snap(e0) - prev.start, 4)
    return sorted(bd.placed, key=lambda p: p.start)


def _pick_filler(fillers: list[dict], by_id: dict, bd: _Board, sentences: list[Sentence], tl: Timeline,
                 t: float) -> Asset | None:
    """출력 시각 t에 쓸 채움용 자료. 그 근처 문장에 붙은 후보를 먼저, 없으면 아무 후보나 (안 쓴 것, 최근과 다른 종류)."""
    def near(item) -> float:
        if not 0 <= item["at"] < len(sentences):
            return 1e9
        ot = _out_time(sentences[item["at"]].start + float(item.get("offset", 0)), tl)
        return abs(ot - t) if ot is not None else 1e9

    for item in sorted(fillers, key=near):
        a = by_id.get(item.get("asset", ""))
        if a and a.id not in bd.used and not bd.recent_family(a) and (a.kind == "image" or a.duration >= FULL_MIN + 0.3):
            return a
    return None


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
        elif a.kind in ("image", "slide"):
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
    covers = [(p.start, p.start + p.dur) for p in placements if p.mode != "side"]
    for n, p in enumerate(placements):
        i = first_input + n
        d = p.dur
        # 전체 화면끼리 바로 이어지면 컷으로 넘기고, 얼굴에서 넘어올 때만 짧게 페이드한다
        fin = p.mode == "side" or not any(abs(e - p.start) < 0.05 for s, e in covers)
        fout = p.mode == "side" or not any(abs(s - (p.start + d)) < 0.05 for s, e in covers)
        fades = "format=yuva420p"
        if fin:
            fades += f",fade=t=in:st=0:d={FADE}:alpha=1"
        if fout:
            fades += f",fade=t=out:st={max(0, d - FADE)}:d={FADE}:alpha=1"
        if p.mode == "slide":
            prep = "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
            pos = "0:0"
        elif p.mode == "full":
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
