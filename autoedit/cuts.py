"""단어 타임스탬프로 문장을 나누고, 무음/군말을 빼고 남길 구간을 계산한다."""
from dataclasses import dataclass

# 단독으로 나오면 지우는 군말
FILLERS = {"어", "음", "으", "흠", "어어", "음음", "어음", "그니까"}

GAP_SPLIT = 0.40   # 단어 사이 공백이 이보다 길면 잘라낸다 (초)
PAD_START = 0.06   # 잘린 구간 앞쪽 여유
PAD_END = 0.14     # 잘린 구간 뒤쪽 여유 (말끝 잘림 방지)
MIN_CLIP = 0.35    # 이보다 짧은 조각은 버린다


@dataclass
class Sentence:
    idx: int
    start: float
    end: float
    text: str
    word_ids: list[int]


def _bare(w: str) -> str:
    return w.strip(".,?!…~ ")


def is_filler(w: str) -> bool:
    return _bare(w) in FILLERS


def split_sentences(words: list[dict], max_gap: float = 0.7) -> list[Sentence]:
    """문장부호나 긴 공백을 기준으로 문장을 나눈다."""
    sentences: list[Sentence] = []
    cur: list[int] = []

    def flush():
        if not cur:
            return
        text = " ".join(words[i]["w"] for i in cur)
        sentences.append(Sentence(len(sentences), words[cur[0]]["s"], words[cur[-1]]["e"], text, cur.copy()))
        cur.clear()

    for i, w in enumerate(words):
        if cur and w["s"] - words[cur[-1]]["e"] > max_gap:
            flush()
        cur.append(i)
        if w["w"].endswith((".", "?", "!")):
            flush()
    flush()
    return sentences


def keep_ranges(words: list[dict], start: float, end: float) -> list[tuple[float, float]]:
    """[start, end] 원본 구간 안에서 말하는 부분만 남긴 (시작, 끝) 목록."""
    spoken = [w for w in words if w["s"] >= start - 0.01 and w["e"] <= end + 0.01 and not is_filler(w["w"])]
    ranges: list[list[float]] = []
    for w in spoken:
        s, e = max(start, w["s"] - PAD_START), min(end, w["e"] + PAD_END)
        # 패딩을 뺀 실제 단어 간격이 GAP_SPLIT보다 짧으면 이어 붙인다
        if ranges and s - ranges[-1][1] < GAP_SPLIT - PAD_START - PAD_END:
            ranges[-1][1] = max(ranges[-1][1], e)
        else:
            ranges.append([s, e])
    return [(round(s, 3), round(e, 3)) for s, e in ranges if e - s >= MIN_CLIP]
