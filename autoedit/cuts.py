"""단어 타임스탬프로 문장을 나누고, 무음/군말을 빼고 남길 구간을 계산한다."""
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# 단독으로 나오면 지우는 군말
FILLERS = {"어", "음", "으", "흠", "어어", "음음", "어음", "그니까"}

GAP_SPLIT = 0.25   # 단어 사이 공백이 이보다 길면 잘라낸다 (초). 컷은 바짝
PAD_START = 0.06   # 잘린 구간 앞쪽 여유
PAD_END = 0.14     # 잘린 구간 뒤쪽 여유 (말끝 잘림 방지)
MIN_CLIP = 0.35    # 이보다 짧은 조각은 버린다
SILENCE_DB = -42   # 이보다 작은 소리는 무음으로 본다
SILENCE_MIN = 0.25  # 이보다 긴 무음만 잘라낸다
SILENCE_KEEP = 0.07  # 무음을 자를 때 앞뒤로 남기는 여유
NONSPEECH_MIN = 0.16  # 음성 검출(VAD)로 말소리가 아니라고 나온 구간(숨소리, 쩝 소리, 잡음)이 이보다 길면 잘라낸다
NONSPEECH_KEEP = 0.05


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


def _norm(w: str) -> str:
    return re.sub(r"[^가-힣A-Za-z0-9]", "", w)


def mark_restarts(words: list[dict], max_n: int = 3) -> int:
    """말을 하다 끊고 다시 시작한 곳("스테로 스테로이드를", "그래서 이 그래서 이게")에서 앞의 조각을 지운다.

    앞 n어절이 뒤 n어절과 같은데 마지막 어절만 뒤 것의 앞부분일 때 (말이 끊긴 조각) 앞 n어절에 drop=True.
    """
    n_drop, i = 0, 0
    while i < len(words):
        for n in range(max_n, 0, -1):
            a = [_norm(w["w"]) for w in words[i:i + n]]
            b = [_norm(w["w"]) for w in words[i + n:i + 2 * n]]
            if len(b) < n or not all(a) or any(w.get("drop") for w in words[i:i + n]):
                continue
            if a[:-1] != b[:-1] or a[-1] == b[-1] or not b[-1].startswith(a[-1]):
                continue
            if words[i + n]["s"] - words[i + n - 1]["e"] > 1.5:
                continue
            for w in words[i:i + n]:
                w["drop"] = True
            n_drop += n
            i += n - 1
            break
        i += 1
    return n_drop


def find_retakes(sentences: list["Sentence"], words: list[dict]) -> list[int]:
    """같은 문장을 다시 찍은 곳: 바로 뒤(두 문장 안) 문장이 이 문장 내용을 거의 다 담고 있으면 앞 문장을 뺀다."""
    def grams(s):
        t = re.sub(r"[^가-힣A-Za-z0-9]", "", " ".join(words[i]["w"] for i in s.word_ids if not words[i].get("drop")))
        return {t[k:k + 2] for k in range(len(t) - 1)}

    out = []
    for i, s in enumerate(sentences):
        g = grams(s)
        if len(g) < 6:
            continue
        for j in (i + 1, i + 2):
            if j < len(sentences):
                h = grams(sentences[j])
                if len(g & h) / len(g) >= 0.7 and len(h) >= len(g) * 0.8:
                    out.append(s.idx)
                    break
    return out


def detect_nonspeech(video: Path, out_json: Path) -> list[tuple[float, float]]:
    """음성 검출(Silero VAD)로 말소리가 아닌 구간(숨소리, 입맛 다시는 소리, 잡음)을 찾는다.
    음량 기준 무음 검출은 쩝 소리나 숨소리를 소리로 보고 남기기 때문에 같이 쓴다."""
    if out_json.exists():
        return [tuple(x) for x in json.loads(out_json.read_text())]
    import numpy as np
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         check=True, capture_output=True).stdout
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    segs = get_speech_timestamps(audio, VadOptions(threshold=0.5, min_speech_duration_ms=80,
                                                   min_silence_duration_ms=100, speech_pad_ms=60))
    sp = [(x["start"] / 16000, x["end"] / 16000) for x in segs]
    holes = []
    for (a0, a1), (b0, b1) in zip(sp, sp[1:]):
        if b0 - a1 >= NONSPEECH_MIN:
            holes.append((round(a1 + NONSPEECH_KEEP, 3), round(b0 - NONSPEECH_KEEP, 3)))
    out_json.write_text(json.dumps(holes))
    return holes


DRAWL_RUN = 0.3      # 같은 모음이 이만큼 이상 이어지면(스펙트럼이 거의 안 바뀌는 유성음) "어~/음~" 군말이나 말끝 끌기로 본다
DRAWL_WORDS = {"그", "저", "뭐"}
SYL_SEC = 0.2        # 한 음절 보통 길이. 단어가 음절 수 × 이것 + 0.15초보다 0.25초 넘게 길 때만 자른다


def detect_drawls(video: Path, words: list[dict], out_json: Path) -> list[tuple[float, float]]:
    """음성 인식이 단어에 붙여 버린 군말("어~ 오늘", "진단과는~ 음")과 길게 끈 모음을 찾아 잘라낼 구간을 돌려준다.
    인식기는 "어", "음"을 거의 받아 적지 않아서 소리로 찾는다: 단어 안에서 같은 모음이 DRAWL_RUN초 넘게 이어지고,
    단어가 음절 수에 비해 눈에 띄게 길 때만. 잘라도 모음 가운데라 이음매가 매끄럽다 (앞뒤로 조금씩 남긴다)."""
    if out_json.exists():
        return [tuple(x) for x in json.loads(out_json.read_text())]
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         check=True, capture_output=True).stdout
    x = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    sr, n, hop = 16000, 640, 320
    holes = []
    for w in words:
        syl = max(1, len(re.sub(r"[^가-힣0-9]", "", w["w"])))
        dur = w["e"] - w["s"]
        # "그~", "저~", "뭐~"를 길게 끌면 군말이다 (짧게 말한 '저 병원'의 '저'는 남는다)
        if _bare(w["w"]) in DRAWL_WORDS and dur > 0.5:
            holes.append((round(w["s"] + 0.02, 3), round(w["e"] - 0.04, 3)))
            continue
        excess = dur - (syl * SYL_SEC + 0.15)
        if excess < 0.25:
            continue
        seg = x[int(w["s"] * sr):int(w["e"] * sr)]
        frames = [seg[i:i + n] for i in range(0, len(seg) - n, hop)]
        if len(frames) < 4:
            continue
        sp = [np.abs(np.fft.rfft(f * np.hanning(n)))[:160] for f in frames]
        sp = [v / (np.linalg.norm(v) + 1e-9) for v in sp]
        steady = [np.linalg.norm(sp[i] - sp[i - 1]) < 0.25 and (frames[i] ** 2).mean() > 1e-4 for i in range(1, len(sp))]
        c0 = None
        for i, v in enumerate(steady + [False]):
            if v and c0 is None:
                c0 = i
            if not v and c0 is not None:
                a, b = w["s"] + (c0 + 1) * hop / sr, w["s"] + (i + 1) * hop / sr
                c0 = None
                if b - a < DRAWL_RUN:
                    continue
                # 단어 맨 앞이면 "어~" 같은 군말이 붙은 것: 거의 다 자른다. 가운데/끝이면 끈 모음: 앞쪽을 조금 남긴다
                lead = 0.03 if a - w["s"] < 0.12 else 0.12
                cut = min(b - 0.06 - (a + lead), excess)
                if cut >= 0.15:
                    holes.append((round(a + lead, 3), round(a + lead + cut, 3)))
                    excess -= cut
    out_json.write_text(json.dumps(holes))
    return holes


def detect_fillers_asr(video: Path, scan_json: Path, model_name: str = "large-v3-turbo") -> list[tuple[float, float]]:
    """군말을 받아 적도록 유도한 두 번째 음성 인식("음, 어..."로 시작하는 프롬프트)에서 "어/음"이 나온 자리를 잘라낼 구간으로.
    첫 인식은 군말을 옆 단어에 붙여 버리므로, 이 인식에서 군말 다음 단어가 시작하기 직전까지 자른다."""
    if scan_json.exists():
        ws = json.loads(scan_json.read_text(encoding="utf-8"))
    else:
        import numpy as np
        from faster_whisper import WhisperModel
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                             check=True, capture_output=True).stdout
        audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
        segs, _ = WhisperModel(model_name, device="cpu", compute_type="int8").transcribe(
            audio, language="ko", word_timestamps=True, vad_filter=False, temperature=0.0,
            initial_prompt="음, 어... 그러니까 어, 음 그 저, 어어 이제 음...", condition_on_previous_text=False)
        ws = [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3)} for sg in segs for w in (sg.words or [])]
        scan_json.write_text(json.dumps(ws, ensure_ascii=False), encoding="utf-8")
    holes = []
    for i, w in enumerate(ws):
        if not is_filler(w["w"]):
            continue
        end = ws[i + 1]["s"] - 0.06 if i + 1 < len(ws) else w["e"]
        if end - (w["s"] + 0.02) >= 0.15:
            holes.append((round(w["s"] + 0.02, 3), round(end, 3)))
    return holes


def mark_repeats(words: list[dict], max_n: int = 5) -> int:
    """같은 말을 바로 이어서 다시 한 경우("지금 당장은 지금 당장은") 앞의 것을 지우고 마지막 것만 남긴다.

    지울 단어에 drop=True를 표시하고 지운 단어 수를 돌려준다. 짧은 말(1어절)은 2글자 이상일 때만 본다.
    """
    n_drop = 0
    i = 0
    while i < len(words):
        for n in range(max_n, 0, -1):
            a = [_norm(w["w"]) for w in words[i:i + n]]
            b = [_norm(w["w"]) for w in words[i + n:i + 2 * n]]
            if len(b) < n or a != b or not all(a) or (n == 1 and len(a[0]) < 2):
                continue
            # 두 번째 말이 한참 뒤에 나오면 반복이 아니라 다른 문장이다
            if words[i + n]["s"] - words[i + n - 1]["e"] > 1.5:
                continue
            for w in words[i:i + n]:
                w["drop"] = True
            n_drop += n
            i += n - 1
            break
        i += 1
    return n_drop


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
    spoken = [w for w in words if w["s"] >= start - 0.01 and w["e"] <= end + 0.01
              and not is_filler(w["w"]) and not w.get("drop")]
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
