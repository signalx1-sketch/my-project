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

FULL_VIDEO_ONLY = True  # 전체 화면 배경은 영상만 (사진은 같은 장면 영상으로 바꾸고, 없으면 빼기)
TWIN_MIN = 0.6          # 사진과 영상 파일명 단어가 이만큼 겹치면 같은 장면으로 본다
FACE_TARGET = 0.15   # 본편에서 얼굴이 그대로 보이는 시간 비율 목표 (나머지는 슬라이드/자료 화면)
FULL_SEC = 4.5       # 전체 화면 자료 길이 (자청 채널처럼 3.5~5.5초마다 화면이 바뀌게)
FULL_MIN = 2.0
LOOKAHEAD = 3.5     # 그 문장 자리가 이미 덮여 있으면 이만큼 뒤까지 빈 곳을 찾는다
FULL_MAX = 6.0
SLIDE_MAX = 6.0      # 슬라이드는 다음 슬라이드가 나올 때까지, 최대 이만큼 (화면이 3.5~5.5초마다 바뀌게)
SLIDE_MIN = 1.5
SIDE_SEC = 3.0       # 팝업 길이
SIDE_MIN = 2.2
SIDE_GAP = 12.0      # 팝업 사이 최소 간격
FACE_KEEP = 3.0      # 자료 화면 사이에 얼굴을 보여 줄 때는 최소 이만큼
FACE_LONG = 5.5      # 얼굴만 이보다 오래 이어지면 비율과 상관없이 자료를 끼운다
FACE_SHORT = 3.0     # 자료 사이 얼굴이 이보다 짧게 비치면 메운다 (깜빡임처럼 보인다)
MAX_NO_FACE = 30.0
FACE_BREAK = 3.0     # 그때 끼우는 얼굴 길이   # 얼굴 없이 자료/카드만 이보다 오래 이어지면 중간 자료 하나를 빼서 얼굴을 보여 준다 (토크 영상)
FACE_MIN = 1.0       # 이보다 짧은 얼굴 조각은 남기지 않는다 (앞뒤 자료를 늘려서 붙인다)
FAMILY_RECENT = 5    # 최근 이만큼의 자료와 같은 종류(예: 욕조 홍조 여성 사진들)는 다시 쓰지 않는다
MIN_SHOW = 3.0       # 얼굴·자료·카드 모두 한 화면은 최소 이만큼 (2026-10-30: 너무 짧게 지나가는 화면 없게)
INTRO_FACE = 3.5     # 영상 맨 앞은 얼굴로 최소 이만큼 시작한다
HOLD_MAX = 9.0       # 짧은 화면을 메우려고 카드를 늘릴 때 최대 길이
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
    tin: str = ""    # 들어올 때 전환: cut | fade | dissolve | iris | wipe | push (빈 값이면 예전 방식)
    tout: str = ""   # 나갈 때(얼굴로 돌아갈 때) 전환: cut | fade | wipe | pushout
    extend: float = 0.0  # 다음 자료가 전환하며 덮는 동안 이만큼 더 보여 준다
    card: str = ""   # 슬라이드 카드 종류 (part 등)
    keep: bool = False  # 얼굴 비중을 맞추려고 자료를 뺄 때도 남길 자료 (계획의 keep)


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
OUTRO_WORDS = ("구독", "좋아요", "알림", "하이프", "댓글", "영상은 여기까지", "고맙습니다", "감사합니다")
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
            return c.to_out(max(src_t, c.src_start))
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


def video_twin(a: Asset, videos: list[Asset]) -> Asset | None:
    """사진과 같은 장면으로 만든 영상("사진_세안_후_미소_홍조_여성" → "영상_세안_후_미소_홍조_여성")을 찾는다."""
    toks = set(_content_tokens(a))
    if not toks:
        return None
    best, score = None, 0.0
    for v in videos:
        vt = set(_content_tokens(v))
        sc = len(toks & vt) / len(toks | vt) if vt else 0
        if sc > score:
            best, score = v, sc
    return best if score >= TWIN_MIN else None


def place(plan_broll: list[dict], sentences: list[Sentence], assets: list[Asset], tl: Timeline,
          slides: list[dict] = (), face_target: float = FACE_TARGET) -> list[Placement]:
    """자료 화면을 출력 시간에 배치한다.

    1. 슬라이드: 그 내용을 말하는 순간부터 다음 슬라이드 전까지 (최대 SLIDE_MAX초)
    2. 얼굴 옆 팝업: 얼굴이 보이는 곳에 (그 자리는 얼굴로 남긴다)
    3. 계획에서 내용이 맞는 전체 화면 자료: 빈 곳에 FULL_SEC초씩 (앞 자료와 바로 붙어도 된다)
    4. 얼굴이 보이는 시간이 본편의 face_target을 넘으면, 긴 얼굴 구간부터 채움용 자료로 덮는다
    plan_broll 항목: {at, offset, asset, mode, filler?}. slides 항목: {asset: Asset, t: 원본 초}
    """
    # 전체 화면은 사진을 확대하는 것보다 영상이 낫다: 같은 장면의 영상이 있으면 그걸로, 없으면 사진은 전체 화면에 쓰지 않는다
    videos = [a for a in assets if a.kind == "video"]
    by_id = {a.id: a for a in assets}
    if FULL_VIDEO_ONLY:
        swapped = []
        for x in plan_broll:
            a = by_id.get(x.get("asset", ""))
            if a and a.kind == "image" and x.get("mode", "full") == "full":
                twin = video_twin(a, videos)
                if twin is None:
                    continue
                x = dict(x, asset=twin.id)
            swapped.append(x)
        plan_broll = swapped
    bd = _Board(tl, assets)
    if bd.start >= bd.end:
        return []

    def out_t(item) -> float | None:
        if not 0 <= item["at"] < len(sentences):
            return None
        return _out_time(sentences[item["at"]].start + float(item.get("offset", 0)), tl)

    # 1. 슬라이드
    st = sorted(((_out_time(x["t"], tl), x["asset"], x.get("card", ""), x.get("stop", False)) for x in slides),
                key=lambda x: (x[0] is None, x[0] or 0))
    st = [x for x in st if x[0] is not None and bd.start <= x[0] < bd.end - SLIDE_MIN]
    for k, (t, a, cd, stop) in enumerate(st):
        nxt = st[k + 1][0] if k + 1 < len(st) else bd.end
        dur = min(SLIDE_MAX, nxt - t, bd.end - t)
        if dur >= SLIDE_MIN and not stop:
            bd.add(a, "slide", t, dur)
            bd.placed[-1].card = cd

    # 챕터 시작은 얼굴로 (큰 챕터 제목이 뜬다). 슬라이드가 이미 덮은 챕터는 제외
    keep_face = [(c, c + AVOID_AFTER_CHAPTER) for c in bd.chapters if bd.free_at(c)]
    keep_face.append((bd.start, bd.start + 1.5))
    # 구독/좋아요/하이프 같은 끝인사는 얼굴로 (엉뚱한 자료가 붙지 않게)
    for snt in sentences:
        if any(w in snt.text for w in OUTRO_WORDS):
            a, b = _out_time(snt.start, tl), _out_time(max(snt.start, snt.end - 0.05), tl)
            if a is not None and b is not None and b > a:
                keep_face.append((a, b + 0.3))

    def fit_full(a: Asset, t: float, want: float) -> tuple[float, float] | None:
        """t 근처에서 덮을 수 있는 곳(얼굴 구간 중 챕터 시작/팝업 자리 제외)에 들어갈 (시작, 길이).
        이미 덮인 곳이면 2.5초 안쪽으로 뒤에 빈 곳을 찾는다."""
        spots = [x for s0, e0 in bd.face_windows() for x in _subtract(s0, e0, keep_face)]
        w = next((x for x in spots if x[0] - 1e-6 <= t < x[1]), None)
        if w is None:
            w = next((x for x in spots if t < x[0] < t + LOOKAHEAD), None)
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
            if item.get("keep"):  # 계획에서 꼭 넣으라고 한 자료는 얼굴을 보여 주려고 뺄 때도 남긴다
                bd.placed[-1].keep = True

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

    # 5. 자료 사이에 잠깐(2초 미만) 얼굴이 비치는 곳은 화면이 깜빡이는 것처럼 어색하다.
    #    챕터 시작/팝업 자리가 아니면 앞 자료를 늘려서(안 되면 뒤 자료를 당겨서) 메운다
    for s0, e0 in bd.face_windows():
        if e0 - s0 >= FACE_SHORT or any(ks < e0 - 0.05 and s0 + 0.05 < ke for ks, ke in keep_face):
            continue
        full = [p for p in bd.placed if p.mode != "side"]
        prev = next((p for p in full if abs(p.start + p.dur - s0) < 0.05), None)
        nxt = next((p for p in full if abs(p.start - e0) < 0.05), None)
        if prev and (prev.asset.kind != "video" or prev.dur + (e0 - s0) <= prev.asset.duration - 0.2):
            prev.dur = round(snap(e0) - prev.start, 4)
        elif nxt and nxt.asset.kind != "video":
            nxt.dur = round(nxt.start + nxt.dur - snap(s0), 4)
            nxt.start = snap(s0)
        elif prev and nxt:  # 둘 다 길이가 정해진 영상이면 앞 영상을 끝까지 쓰고, 그래도 모자라면 뒤 자료를 뺀다
            room = prev.asset.duration - 0.2 - prev.dur
            if room >= e0 - s0:
                prev.dur = round(snap(e0) - prev.start, 4)
            elif nxt.mode == "full":
                bd.placed.remove(nxt)
    # 6. 얼굴이 너무 오래 안 나오면 (카드와 자료가 MAX_NO_FACE초 넘게 이어지면) 가운데쯤의 자료 화면 하나를 뺀다
    for _ in range(100):
        full = sorted((p for p in bd.placed if p.mode != "side"), key=lambda p: p.start)
        runs, cur = [], []
        for p in full:
            if cur and p.start - (cur[-1].start + cur[-1].dur) > 0.05:
                runs.append(cur)
                cur = []
            cur.append(p)
        if cur:
            runs.append(cur)
        fixed = False
        for r in runs:
            r0, r1 = r[0].start, r[-1].start + r[-1].dur
            if r1 - r0 <= MAX_NO_FACE:
                continue
            mid = (r0 + r1) / 2
            cands = [p for p in r if p.mode == "full" and not p.keep and p.start - r0 >= 4 and r1 - (p.start + p.dur) >= 4]
            if cands:
                bd.placed.remove(min(cands, key=lambda p: abs(p.start + p.dur / 2 - mid)))
                fixed = True
                continue
            # 카드만 이어지면 가운데쯤 카드 하나를 FACE_BREAK초 줄여 그 뒤에 얼굴이 나오게 한다
            cards = [p for p in r[:-1] if p.mode == "slide" and p.card != "paper" and p.dur >= SLIDE_MIN + FACE_BREAK and p.start - r0 >= 3]
            if cards:
                c = min(cards, key=lambda p: abs(p.start + p.dur - mid))
                c.dur = round(c.dur - FACE_BREAK, 4)
                fixed = True
        if not fixed:
            break
    placed = [p for p in bd.placed if p.mode == "side"] + enforce_min_show(
        [p for p in bd.placed if p.mode != "side"], bd.start, bd.end)
    return sorted(placed, key=lambda p: p.start)


def _can_hold(p: Placement, dur: float) -> bool:
    if p.mode == "slide" or p.asset.kind == "image":
        return dur <= HOLD_MAX
    return dur <= p.asset.duration - 0.2


def enforce_min_show(placed: list[Placement], start: float, end: float) -> list[Placement]:
    """화면 하나하나(얼굴 구간 포함)가 MIN_SHOW초보다 짧지 않게 고친다. 맨 앞은 얼굴로 INTRO_FACE초 시작한다."""
    placed = sorted(placed, key=lambda p: p.start)
    # 맨 앞: 얼굴 먼저. 그 안에서 끝나는 화면은 빼고, 걸치는 화면은 뒤로 민다
    head = start + INTRO_FACE
    for p in list(placed):
        if p.start < head:
            if p.start + p.dur < head + MIN_SHOW:
                placed.remove(p)
            else:
                p.dur, p.start = round(p.start + p.dur - head, 4), head
    for _ in range(500):
        segs, t = [], start
        for p in placed:
            if p.start > t + 0.05:
                segs.append((None, t, p.start))
            segs.append((p, p.start, p.start + p.dur))
            t = p.start + p.dur
        if end > t + 0.05:
            segs.append((None, t, end))
        bad = next((k for k, (p, a, b) in enumerate(segs) if b - a < MIN_SHOW - 1e-3 and not (p is None and k == len(segs) - 1)), None)
        if bad is None:
            break
        p, a, b = segs[bad]
        prev = segs[bad - 1][0] if bad > 0 else None
        nxt_seg = segs[bad + 1] if bad + 1 < len(segs) else None
        if p is None:  # 짧은 얼굴: 앞 화면을 늘려 덮거나, 뒤 화면을 당긴다
            if prev and _can_hold(prev, prev.dur + (b - a)):
                prev.dur = round(b - prev.start, 4)
            elif nxt_seg and nxt_seg[0] and _can_hold(nxt_seg[0], nxt_seg[0].dur + (b - a)):
                q = nxt_seg[0]
                q.dur, q.start = round(q.start + q.dur - a, 4), a
            elif prev:
                prev.dur = round(b - prev.start, 4)  # 길이를 넘더라도 마지막 프레임을 잠깐 잡아 둔다
            else:
                break
            continue
        need = MIN_SHOW - (b - a)
        if nxt_seg and nxt_seg[0] is None:  # 뒤가 얼굴: 그만큼 늘리고, 남는 얼굴이 짧으면 통째로 덮는다
            f = nxt_seg[2] - nxt_seg[1]
            grow = f if f - need < MIN_SHOW else need
            if _can_hold(p, p.dur + grow):
                p.dur = round(p.dur + grow, 4)
                continue
        if p.mode == "slide" and p.card not in ("part", "paper") and nxt_seg and nxt_seg[0] is not None \
                and nxt_seg[0].mode == "slide":
            placed.remove(p)  # 카드가 줄줄이 붙으면 뒤 카드를 늦추지 않고 짧은 카드를 뺀다 (말과 카드가 어긋나지 않게, 2026-10-30)
            continue
        if nxt_seg and nxt_seg[0] is not None and nxt_seg[0].dur - need >= MIN_SHOW:  # 뒤가 화면: 뒤를 조금 늦춘다
            q = nxt_seg[0]
            q.start, q.dur = round(q.start + need, 4), round(q.dur - need, 4)
            p.dur = round(p.dur + need, 4)
            continue
        if prev is not None and prev.mode == p.mode == "slide" and _can_hold(prev, prev.dur + p.dur):
            prev.dur = round(prev.dur + p.dur, 4)  # 짧은 카드는 앞 카드에 붙인다 (빼는 대신)
            placed.remove(p)
            continue
        placed.remove(p)  # 늘릴 수 없는 짧은 화면은 뺀다
    return placed


FILLER_NEAR = 25.0  # 채움용 자료는 계획한 문장에서 이 시간 안쪽에만 쓴다


def _pick_filler(fillers: list[dict], by_id: dict, bd: _Board, sentences: list[Sentence], tl: Timeline,
                 t: float) -> Asset | None:
    """출력 시각 t에 쓸 채움용 자료. 계획한 문장이 FILLER_NEAR초 안에 있는 후보만 (안 쓴 것, 최근과 다른 종류)."""
    def near(item) -> float:
        if not 0 <= item["at"] < len(sentences):
            return 1e9
        ot = _out_time(sentences[item["at"]].start + float(item.get("offset", 0)), tl)
        return abs(ot - t) if ot is not None else 1e9

    for item in sorted(fillers, key=near):
        a = by_id.get(item.get("asset", ""))
        # 계획한 문장에서 먼 곳에는 쓰지 않는다 (엉뚱한 말 위에 자료가 붙는다, 2026-10-29)
        if near(item) > FILLER_NEAR:
            break
        if a and a.id not in bd.used and not bd.recent_family(a) and (a.kind == "image" or a.duration >= FULL_MIN + 0.3):
            return a
    return None


# --- 렌더링용 ffmpeg 필터 ---

SIDE_BOX = (720, 520)  # 팝업 최대 크기
SIDE_X = 70            # 얼굴 왼쪽
FADE = 0.2
UPSCALE_SHARPEN = "unsharp=5:5:0.6:5:5:0.0"  # 720p → 1080p로 늘린 자료의 흐릿함을 덜어 준다 (밝기 채널만)


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
        elif a.kind == "slide" and a.path.suffix == ".mp4":
            args += ["-i", str(a.path)]  # 모션 그래픽 카드: 앞부분만 움직이고 나머지는 마지막 장면을 늘린다
        elif a.kind in ("image", "slide"):
            args += ["-loop", "1", "-framerate", "30", "-t", f"{p.dur + p.extend}", "-i", str(a.path)]
        else:
            d = p.dur + p.extend
            ss = max(0.0, min(a.duration - d - 0.3, a.duration * 0.25))
            args += ["-ss", f"{ss:.2f}", "-t", f"{d + 0.3:.3f}", "-i", str(a.path)]
    return args


def _full_image(path: Path, d: float) -> str:
    """사진을 화면 전체에 천천히 확대하며 보여준다. 16:9와 많이 다르면(도표, 전후 사진, 제품) 잘리지 않게
    흐린 배경 위에 원본 비율로 얹는다."""
    frames = round(d * 30) + 2  # 버림으로 한 프레임 모자라면 끝에서 얼굴이 비친다 (남는 건 trim이 자른다)
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


TRANS = 0.4  # 전환 길이 (초)
# 얼굴 위로 자료가 옆에서 밀려 들어오거나(push) 밀려 나가면(pushout) 어색하다 (2026-10-26 지적, 2:43)
IN_FROM_FACE = {"slide": ["wipe", "fade"], "full": ["fade", "iris", "wipe"]}
OUT_TO_FACE = {"slide": ["fade", "wipe"], "full": ["fade", "wipe"]}
# 카드끼리 디졸브하면 앞 카드 글자가 뒤 카드 글자와 겹쳐 지저분하다 (2026-10-26 지적): 카드끼리는 컷(새 카드가
# 스스로 움직이며 등장한다)과 밀어 넣기를 번갈아 쓰고, 카드와 영상 사이도 글자가 겹치지 않는 와이프/밀기/컷
BETWEEN = {"slide-slide": ["cut", "push"], "full-full": ["cut", "dissolve"], "mixed": ["wipe", "push", "cut"]}
CUT_MAX = 1 / 3  # 그냥 컷으로 넘기는 전환은 전체의 1/3까지


def assign_transitions(placements: list[Placement]):
    """화면 전환 종류를 정한다. 같은 전환이 연달아 나오지 않게 돌려 쓰고, 컷은 1/3을 넘지 않게 한다.
    파트 표지 카드는 초록 패널이 쓸고 지나가는 것 자체가 전환이라 컷으로 들어간다."""
    full = sorted((p for p in placements if p.mode != "side"), key=lambda p: p.start)
    last, rot = "", {}

    def pick(key: str, opts: list[str]) -> str:
        nonlocal last
        k = rot.get(key, 0)
        for j in range(len(opts)):
            o = opts[(k + j) % len(opts)]
            if o != last or len(opts) == 1:
                rot[key] = k + j + 1
                last = o
                return o
        return opts[0]

    for i, p in enumerate(full):
        prev = full[i - 1] if i and abs(full[i - 1].start + full[i - 1].dur - p.start) < 0.05 else None
        nxt = full[i + 1] if i + 1 < len(full) and abs(p.start + p.dur - full[i + 1].start) < 0.05 else None
        kind = "slide" if p.mode == "slide" else "full"
        if p.card == "part":
            p.tin = "cut"
        elif prev is None:
            p.tin = pick("in-" + kind, IN_FROM_FACE[kind])
        else:
            pk = "slide" if prev.mode == "slide" else "full"
            key = f"{pk}-{kind}" if pk == kind else "mixed"
            p.tin = pick(key, BETWEEN[key])
        if prev is not None and p.tin != "cut":
            prev.extend = TRANS
        p.tout = pick("out-" + kind, OUT_TO_FACE[kind]) if nxt is None else ""
    # 컷이 너무 많으면 디졸브로 바꾼다
    ts = [p for p in full if p.tin] + [p for p in full if p.tout]
    def card_to_card(p):
        prv = next((q for q in full if abs(q.start + q.dur - p.start) < 0.05), None)
        return p.mode == "slide" and prv is not None and prv.mode == "slide"
    # 카드끼리의 컷은 새 카드의 등장 애니메이션이 전환 역할을 하므로 세지 않는다
    cuts = [p for p in full if p.tin == "cut" and p.card != "part" and not card_to_card(p)]
    ts = [p for p in ts if not (p.tin == "cut" and card_to_card(p))]
    over = len(cuts) - int(len(ts) * CUT_MAX)
    for p in cuts[:max(0, over)]:
        prv = next((q for q in full if abs(q.start + q.dur - p.start) < 0.05), None)
        p.tin = "push" if p.mode == "slide" or (prv and prv.mode == "slide") else "dissolve"
        if prv:
            prv.extend = TRANS


def _ease_out(x):
    return 1 - (1 - x) ** 3


def transition_masks(folder: Path) -> dict[str, Path]:
    """원형으로 열리는(iris) 마스크와 비스듬히 닦아내는(wipe) 마스크를 한 번 만들어 둔다 (흑백 12프레임)."""
    import numpy as np
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    n, W, H, fe = round(TRANS * 30), 1920, 1080, 60.0
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dist = np.hypot(xx - W / 2, yy - H / 2)
    diag = float(dist.max())
    slant = xx + 0.35 * yy
    out = {}
    for name in ("iris_in", "iris_out", "wipe_in", "wipe_out"):
        mp = folder / f"{name}.mkv"
        out[name] = mp
        if mp.exists():
            continue
        frames = []
        for k in range(n):
            e = _ease_out((k + 1) / n)
            if name.startswith("iris"):
                r = e * (diag + fe)
                a = np.clip((r - dist) / fe, 0, 1)
            else:
                x0 = e * (W + 0.35 * H + 2 * fe) - fe
                a = np.clip((x0 - slant) / fe, 0, 1)
            frames.append(a)
        if name == "iris_out":
            frames = frames[::-1]
        elif name == "wipe_out":
            frames = [1 - f for f in frames]
        tmp = folder / f"_{name}"
        tmp.mkdir(exist_ok=True)
        for k, a in enumerate(frames):
            Image.fromarray((a * 255).astype(np.uint8), "L").save(tmp / f"{k:03d}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "30", "-i", str(tmp / "%03d.png"),
                        "-c:v", "ffv1", "-pix_fmt", "gray", str(mp)], check=True)
    return out


def _mask_chain(n: int, p: Placement, d: float, masks: dict[str, Path]) -> str | None:
    """마스크 전환이 있으면 이 자료의 길이에 맞는 흑백 마스크 스트림 필터를 만든다."""
    mi = p.tin if p.tin in ("iris", "wipe") else None
    mo = p.tout if p.tout == "wipe" else None
    if not (mi or mo):
        return None
    segs, lab = [], []
    if mi:
        segs.append(f"movie={masks[mi + '_in']},format=gray,setpts=PTS-STARTPTS[m{n}a]")
        lab.append(f"[m{n}a]")
    mid = d - (TRANS if mi else 0) - (TRANS if mo else 0)
    # color=white를 흑백으로 바꾸면 235(방송 규격 흰색)가 되어 자료가 92%만 불투명해진다 → 255로 채운다
    segs.append(f"color=c=white:s=1920x1080:r=30:d={max(mid, 1 / 30):.4f},format=gray,lut=c0=255[m{n}b]")
    lab.append(f"[m{n}b]")
    if mo:
        segs.append(f"movie={masks[mo + '_out']},format=gray,setpts=PTS-STARTPTS[m{n}c]")
        lab.append(f"[m{n}c]")
    if len(lab) > 1:
        segs.append(f"{''.join(lab)}concat=n={len(lab)}:v=1:a=0,settb=1/30[m{n}]")
    else:
        segs[-1] = segs[-1].replace(f"[m{n}b]", f"[m{n}]")
    return ";".join(segs)


def overlay_filters(placements: list[Placement], first_input: int, base: str,
                    masks: dict[str, Path] | None = None) -> tuple[str, str]:
    """기존 영상 [base] 위에 자료 화면을 얹는 filter_complex 조각과 결과 라벨을 돌려준다."""
    parts, cur = [], base
    covers = [(p.start, p.start + p.dur) for p in placements if p.mode != "side"]
    for n, p in enumerate(placements):
        i = first_input + n
        d = round(p.dur + p.extend, 4)
        fades = "format=yuva420p"
        if p.tin or p.tout:
            if p.tin in ("fade", "dissolve"):
                fades += f",fade=t=in:st=0:d={0.25 if p.tin == 'fade' else 0.3}:alpha=1"
            if p.tout == "fade":
                fades += f",fade=t=out:st={max(0, d - 0.3):.3f}:d=0.3:alpha=1"
        else:
            # 전체 화면끼리 바로 이어지면 컷으로 넘기고, 얼굴에서 넘어올 때만 짧게 페이드한다
            fin = p.mode == "side" or not any(abs(e - p.start) < 0.05 for s, e in covers)
            fout = p.mode == "side" or not any(abs(s - (p.start + p.dur)) < 0.05 for s, e in covers)
            if fin:
                fades += f",fade=t=in:st=0:d={FADE}:alpha=1"
            if fout:
                fades += f",fade=t=out:st={max(0, d - FADE)}:d={FADE}:alpha=1"
        if p.mode == "slide":
            prep = "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
            if p.asset.path.suffix == ".mp4":
                prep += f",tpad=stop_mode=clone:stop_duration={d + 1:.2f}"
            pos = "0:0"
        elif p.mode == "full":
            if p.asset.kind == "image":
                # 분기(split)가 들어가는 필터는 라벨을 이 자료 번호로 고유하게 바꾼다
                prep = _full_image(p.asset.path, d).replace("[f", f"[f{n}_")
            else:
                # 원본 프레임 수가 모자라 끝에서 한 프레임 얼굴이 비치지 않게 마지막 장면을 조금 늘려 둔다
                # 720p 자료는 lanczos로 늘리고 가볍게 선명도를 올린다 (1080p 이상이면 줄이기만 하므로 그대로 둔다)
                prep = ("fps=30,scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080,"
                        + (UPSCALE_SHARPEN + "," if _dims(p.asset.path)[1] < 1000 else "")
                        + f"tpad=stop_mode=clone:stop_duration={0.5 + p.extend:.2f}")
            pos = "0:0"
        else:
            bw, bh = SIDE_BOX
            prep = (f"fps=30,scale={bw - 16}:{bh - 16}:force_original_aspect_ratio=decrease,"
                    f"pad=iw+16:ih+16:8:8:white,tpad=stop_mode=clone:stop_duration=0.5")
            pos = f"{SIDE_X}:(H-h)/2-40"
        # 시작 시각은 프레임 번호(정수)로 준다. 초를 그대로 쓰면 34.1333×30=1023.999가 1023으로 내려가서
        # 자료가 한 프레임 일찍 끝나고 그 틈에 얼굴이 한 프레임 비친다
        frame0 = round(p.start * 30)
        mk = _mask_chain(n, p, d, masks) if masks and p.mode != "side" else None
        if mk:
            parts.append(mk)
            parts.append(f"[{i}:v]{prep},setsar=1,trim=duration={d},setpts=PTS-STARTPTS,format=yuva420p[it{n}]")
            parts.append(f"[it{n}][m{n}]alphamerge,{fades},settb=1/30,setpts=PTS-STARTPTS+{frame0}[br{n}]")
        else:
            parts.append(f"[{i}:v]{prep},setsar=1,trim=duration={d},{fades},settb=1/30,"
                         f"setpts=PTS-STARTPTS+{frame0}[br{n}]")
        if p.tin == "push" or p.tout == "pushout":
            t0, t1 = frame0 / 30, frame0 / 30 + d - TRANS
            xin = f"W*pow(1-(t-{t0:.4f})/{TRANS},3)" if p.tin == "push" else "0"
            xout = f"-W*pow((t-{t1:.4f})/{TRANS},3)" if p.tout == "pushout" else "0"
            pos = f"x='if(lt(t,{t0 + TRANS:.4f}),{xin},if(gt(t,{t1:.4f}),{xout},0))':y=0:eval=frame"
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
