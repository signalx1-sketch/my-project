import json
import subprocess
from pathlib import Path

import pytest

from shorts_editor.captions import build_ass, build_parts, chunk_words, speech_islands
from shorts_editor.config import Options
from shorts_editor.pipeline import make_shorts
from shorts_editor.planner import ShortPlan, heuristic_plan, sanitize

SENTENCES = [
    "처음에는 정말 아무것도 몰랐어요",
    "그런데 딱 한 가지 습관을 바꾸고 수익률이 열 배가 됐습니다",
    "그 습관이 뭐냐면요",
    "매일 아침 십 분씩 기록하는 겁니다",
    "이걸 안 하는 사람은 절대 돈을 못 법니다",
    "저도 처음에 천만 원을 잃었거든요",
    "근데 그 경험이 제 인생을 바꿨습니다",
    "돈은 버는 것보다 지키는 게 어렵습니다",
]


def fake_transcript(duration: float) -> list[dict]:
    """3초 간격 문장, 단어 0.4초씩, 문장 사이 1초 공백."""
    segs, t = [], 1.0
    while t < duration - 4:
        text = SENTENCES[len(segs) % len(SENTENCES)]
        words, wt = [], t
        for w in text.split():
            words.append({"start": round(wt, 2), "end": round(wt + 0.35, 2), "text": w})
            wt += 0.4
        segs.append({"start": words[0]["start"], "end": words[-1]["end"], "text": text, "words": words})
        t = wt + 1.0
    return segs


def make_analysis(duration=90.0) -> dict:
    env = [-20.0 + (15 if 100 <= i < 120 else 0) for i in range(int(duration / 0.5))]
    return {"probe": {"duration": duration, "width": 1280, "height": 720, "has_audio": True},
            "envelope": env, "silences": [], "scenes": [10.0, 50.0], "transcript": fake_transcript(duration)}


def test_chunk_words_short_chunks():
    words = fake_transcript(10)[0]["words"]
    chunks = chunk_words(words)
    assert all(1 <= len(c) <= 3 for c in chunks)
    assert sum(len(c) for c in chunks) == len(words)


def test_speech_islands_cuts_long_gaps():
    words = [{"start": 0.0, "end": 0.5, "text": "a"}, {"start": 0.6, "end": 1.0, "text": "b"},
             {"start": 3.0, "end": 3.5, "text": "c"}]
    islands = speech_islands(words, 0.0, 4.0)
    assert len(islands) == 2
    assert islands[1][0] > 2.5


def test_heuristic_plan_respects_rules():
    a = make_analysis()
    opts = Options(count=2, min_len=15, max_len=30)
    plans = heuristic_plan(a, opts)
    assert len(plans) == 2
    for p in plans:
        assert 15 <= p.end - p.start <= 30
        assert p.hook_text and p.title
    assert plans[0].end <= plans[1].start or plans[1].end <= plans[0].start
    # 가장 시끄러운 구간(50~60초)을 포함해야 함
    assert any(p.start <= 55 <= p.end for p in plans)


def test_sanitize_snaps_and_drops_bad_teaser():
    a = make_analysis()
    opts = Options(count=3, min_len=15, max_len=30)
    raw = [ShortPlan(start=10.3, end=200, title="t", hook_text="첫줄\\n둘째줄", teaser_start=5, teaser_end=6),
           ShortPlan(start=12, end=30, title="겹침", hook_text="x")]
    out = sanitize(raw, a, opts)
    assert len(out) == 1
    p = out[0]
    starts = {s["start"] for s in a["transcript"]}
    assert p.start in starts and p.end - p.start <= 30
    assert p.teaser_start == p.teaser_end == 0
    assert p.hook_text == "첫줄\n둘째줄"


def test_build_parts_and_ass():
    a = make_analysis()
    words = [w for s in a["transcript"] for w in s["words"]]
    plan = ShortPlan(start=20, end=45, title="t", hook_text="한 가지 습관\n수익률 10배",
                     teaser_start=40, teaser_end=42, highlight_words=["습관", "천만"])
    parts = build_parts(plan, words, [], cut_silence=True, zoom_punch=True)
    assert parts[0].teaser and len(parts) > 2
    assert sum(p.dur for p in parts) < 25 + 2  # 공백이 잘려서 원래보다 짧음 (+티저)
    ass = build_ass(plan, parts, words, layout="blur", total=sum(p.dur for p in parts),
                    font="Black Han Sans", src_w=1280, src_h=720)
    assert "Style: Hook" in ass and "수익률 10배" in ass
    assert "잠시 후 공개" in ass
    assert "&H0000E4FF&}습관" in ass  # 강조 단어 노란색


def test_brand_style_and_header_fit():
    from shorts_editor.styles import TextStyle
    a = make_analysis()
    words = [w for s in a["transcript"] for w in s["words"]]
    plan = ShortPlan(start=20, end=45, title="t", hook_text="팔 안쪽·무릎 뒤 가려움\n[아토피인지 확인법]")
    parts = build_parts(plan, words, [], cut_silence=True, zoom_punch=True)
    ass = build_ass(plan, parts, words, layout="blur", total=sum(p.dur for p in parts), font="",
                    src_w=1920, src_h=940, style=TextStyle())
    hook = next(l for l in ass.splitlines() if l.startswith("Style: Hook"))
    size = float(hook.split(",")[2])
    assert size <= 116 * 1.17 + 1  # 350pt × 0.33 (libass 보정), 화면 폭에 맞게 축소
    assert ",&H0000C6FB&," in hook  # 상단 문구 노란색 #FBC600
    assert "[" not in ass.split("[Events]")[1]  # 대괄호는 지워짐
    assert "\\fax-0.18" in ass  # 자막 기울임


def test_before_after_pairs_and_card(tmp_path):
    from PIL import Image
    from shorts_editor.inserts import find_pairs, make_card
    d = tmp_path / "아토피"
    d.mkdir()
    for name in ["01_before.jpg", "01_after.jpg", "02_전.png", "03_before.jpg"]:
        Image.new("RGB", (300, 400), (200, 100, 100)).save(d / name)
    (d / "01.txt").write_text("치료 6개월", encoding="utf-8")
    pairs = find_pairs("아토피", base=tmp_path)
    assert [p["id"] for p in pairs] == ["01"] and pairs[0]["note"] == "치료 6개월"
    card = make_card(pairs[0]["before"], pairs[0]["after"], tmp_path / "c.png", note="치료 6개월")
    assert Image.open(card).size == (1080, 860)
    assert make_card(None, None, tmp_path / "ph.png").exists()  # 사진 없으면 자리 표시


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("src") / "in.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=60",
                    "-f", "lavfi", "-i", "sine=f=300:d=60", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(p)], check=True)
    return p


@pytest.mark.parametrize("layout", ["black", "blur", "crop"])
def test_end_to_end_render(sample_video, tmp_path, layout, monkeypatch):
    work = tmp_path / layout
    work.mkdir()
    a = make_analysis(60.0)
    (work / "analysis.json").write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    opts = Options(count=1, min_len=15, max_len=25, layout=layout, use_ai=False)
    if layout == "black":  # 비포앤애프터 자리 표시 카드도 함께 렌더
        import shorts_editor.pipeline as pipeline
        plans = heuristic_plan(a, opts)
        plans[0].inserts = [{"category": "없는폴더", "at": plans[0].start + 3, "duration": 2}]
        monkeypatch.setattr(pipeline, "plan_shorts", lambda *_: (plans, "heuristic"))
    summary = make_shorts(str(sample_video), work, opts)
    assert summary["method"] == "heuristic"
    s = summary["shorts"][0]
    out = work / s["file"]
    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(out)],
        capture_output=True, text=True, check=True).stdout)
    v = next(x for x in info["streams"] if x["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert any(x["codec_type"] == "audio" for x in info["streams"])
    assert abs(float(info["format"]["duration"]) - s["duration"]) < 0.5
    assert (work / s["cover"]).exists()


def test_combined_photo(tmp_path):
    from PIL import Image
    from shorts_editor.inserts import find_pairs, make_photo
    d = tmp_path / "아토피"
    d.mkdir()
    Image.new("RGB", (2400, 900), (200, 100, 100)).save(d / "60.jpg")
    pairs = find_pairs("아토피", base=tmp_path)
    assert pairs[0]["id"] == "60" and "image" in pairs[0]
    out = make_photo(pairs[0]["image"], tmp_path / "p.png")
    assert Image.open(out).size == (1080, 620)  # 영상 높이만큼 검은 바탕
