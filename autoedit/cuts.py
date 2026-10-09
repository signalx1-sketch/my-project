"""단어 타임스탬프로 문장을 나누고, 무음/군말을 빼고 남길 구간을 계산한다."""
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# 단독으로 나오면 지우는 군말
FILLERS = {"어", "음", "으", "흠", "어어", "음음", "어음", "그니까"}

GAP_SPLIT = 0.40   # 단어 사이 공백이 이보다 길면 잘라낸다 (초)
PAD_START = 0.06   # 잘린 구간 앞쪽 여유
PAD_END = 0.14     # 잘린 구간 뒤쪽 여유 (말끝 잘림 방지)
MIN_CLIP = 0.35    # 이보다 짧은 조각은 버린다
SILENCE_DB = -42   # 이보다 작은 소리는 무음으로 본다
SILENCE_MIN = 0.4  # 이보다 긴 무음만 잘라낸다
SILENCE_KEEP = 0.1  # 무음을 자를 때 앞뒤로 남기는 여유


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


ENDINGS = ("다", "요", "죠", "까", "니다", "네")


def _ends_sentence(w: str) -> bool:
    # 한국어 음성 인식은 문장부호를 자주 빼먹어서 종결어미로도 문장을 끊는다
    return w.endswith((".", "?", "!")) or _bare(w).endswith(ENDINGS)


def split_sentences(words: list[dict], max_gap: float = 0.7) -> list[Sentence]:
    """문장부호, 종결어미, 긴 공백을 기준으로 문장을 나눈다."""
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
        if _ends_sentence(w["w"]) and len(cur) >= 3:
            flush()
    flush()
    return sentences


def detect_silences(video: Path, out_json: Path) -> list[tuple[float, float]]:
    """실제 오디오 음량으로 무음 구간을 찾는다. 음성 인식 타임스탬프는 쉬는 구간까지 단어에 붙여버려서 믿을 수 없다."""
    if out_json.exists():
        return [tuple(x) for x in json.loads(out_json.read_text())]
    log = subprocess.run(
        ["ffmpeg", "-i", str(video), "-vn", "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN}",
         "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    silences = [(a + SILENCE_KEEP, b - SILENCE_KEEP) for a, b in zip(starts, ends)]
    out_json.write_text(json.dumps(silences))
    return silences


def _subtract(ranges: list[list[float]], holes: list[tuple[float, float]]) -> list[list[float]]:
    out = []
    for s, e in ranges:
        cur = s
        for a, b in holes:
            if b <= cur or a >= e:
                continue
            if a > cur:
                out.append([cur, a])
            cur = max(cur, b)
        if cur < e:
            out.append([cur, e])
    return out


def keep_ranges(words: list[dict], start: float, end: float,
                silences: list[tuple[float, float]] = ()) -> list[tuple[float, float]]:
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
    ranges = _subtract(ranges, silences)
    return [(round(s, 3), round(e, 3)) for s, e in ranges if e - s >= MIN_CLIP]
