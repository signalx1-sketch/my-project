"""환자 인터뷰 클립 확인표 (HTML, 2026-11-21).

data/interview_clips.json의 클립마다 가운데 프레임을 잘라낼 높이(keep_h)로 잘라 붙이고,
환자·주제·말·길이·구워진 글자 검사 결과를 주제별로 묶어 한 장짜리 HTML로 만든다.

사용법: python scripts/interview_review.py 인터뷰_영상_폴더 결과.html
"""
import base64
import html
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GROUPS = [  # 태그로 큰 묶음을 정한다 (앞에 있는 것 우선)
    ("스테로이드·연고", {"스테로이드", "스테로이드부작용", "리바운드", "탈스테로이드", "연고", "의존"}),
    ("레이저·시술", {"레이저", "브이빔", "프락셀", "필링", "박피", "PDT", "시술", "제모", "혈관"}),
    ("병원 유목·포기", {"병원유목", "병원", "포기", "오진", "한의원", "약침", "절망"}),
    ("증상·고통", {"증상", "고통", "가려움", "진물", "통증", "열감", "수면", "우울", "대인기피", "스트레스", "일상", "심리", "눈물"}),
    ("비용", {"비용"}),
    ("치료 경과·효과", {"경과", "효과", "자연수액", "계단식", "가족"}),
    ("격려·조언", {"격려", "희망", "추천", "인터뷰"}),
]


def group_of(c):
    tags = set(c.get("tags", []))
    for name, keys in GROUPS:
        if tags & keys:
            return name
    return "기타"


def thumb(lib: Path, c: dict) -> str:
    kh = int(c.get("keep_h") or 1080)
    w = round(kh * 16 / 9) // 2 * 2
    t = (c["start"] + c["end"]) / 2
    jpg = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", str(lib / c["video"]), "-frames:v", "1",
                          "-vf", f"scale=-2:1080,crop={w}:{kh}:(iw-{w})/2:0,scale=320:180", "-q:v", "5", "-f", "mjpeg", "-"],
                         capture_output=True).stdout
    return base64.b64encode(jpg).decode()


def main():
    lib, out = Path(sys.argv[1]), Path(sys.argv[2])
    clips = json.loads((ROOT / "data" / "interview_clips.json").read_text(encoding="utf-8"))
    groups = defaultdict(list)
    for c in clips:
        groups[group_of(c)].append(c)
    rows = []
    order = [g for g, _ in GROUPS] + ["기타"]
    for g in order:
        if not groups[g]:
            continue
        rows.append(f"<h2>{g} <small>{len(groups[g])}개</small></h2><div class=grid>")
        for c in groups[g]:
            sc = c.get("screen", {})
            warn = []
            if sc.get("center_text", 0) >= 0.3:
                warn.append("가운데 글자")
            if sc.get("top_text", 0) >= 0.2:
                warn.append("위쪽 글자")
            if sc.get("too_low"):
                warn.append("자막이 높이 떠 있음")
            src = "유튜브본" if c["video"].startswith("yt_") else "가편집본"
            img = thumb(lib, c) if (lib / c["video"]).exists() else ""
            rows.append(
                f"<div class='card{' warn' if warn else ''}'>"
                + (f"<img src='data:image/jpeg;base64,{img}'>" if img else "")
                + f"<div class=id>{c['id']} · {c['end'] - c['start']:.0f}초 · {src}</div>"
                f"<div class=txt>“{html.escape(c['text'])}”</div>"
                f"<div class=lab>{html.escape(c['label'])}</div>"
                f"<div class=tag>{html.escape(c.get('topic', ''))} · {html.escape(', '.join(c.get('tags', [])))}</div>"
                + (f"<div class=w>확인 필요: {', '.join(warn)}</div>" if warn else "")
                + "</div>")
        rows.append("</div>")
    n_yt = sum(c["video"].startswith("yt_") for c in clips)
    page = f"""<!DOCTYPE html><html lang=ko><meta charset=utf-8><title>환자 인터뷰 클립 확인표</title>
<style>body{{font-family:Pretendard,'Apple SD Gothic Neo',sans-serif;background:#111;color:#eee;margin:24px}}
h1{{font-size:22px}}h2{{font-size:18px;margin-top:28px;border-bottom:1px solid #333;padding-bottom:6px}}small{{color:#888;font-weight:400}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}}
.card{{background:#1c1c1c;border-radius:8px;padding:8px;font-size:13px}}.card.warn{{outline:2px solid #c80}}
.card img{{width:100%;border-radius:4px;display:block}}.id{{color:#8c8;margin-top:6px}}.txt{{font-size:15px;margin:4px 0;font-weight:600}}
.lab{{color:#bbb}}.tag{{color:#888;font-size:12px}}.w{{color:#fb4;font-size:12px;margin-top:4px}}p{{color:#aaa;line-height:1.6}}</style>
<h1>환자 인터뷰 클립 {len(clips)}개 <small>(유튜브본 {n_yt}개)</small></h1>
<p>사진은 실제로 들어갈 화면입니다. 아래 구워진 자막 띠는 잘라낸 상태이고, 그 위에 우리 자막과 '실제 환자 인터뷰' 이름표가 얹힙니다.
주황 테두리는 화면 가운데·위쪽에 글자가 떠 있어서 쓰기 전에 한 번 더 볼 클립입니다.</p>
{''.join(rows)}</html>"""
    out.write_text(page, encoding="utf-8")
    print("ok", out, len(clips))


if __name__ == "__main__":
    main()
