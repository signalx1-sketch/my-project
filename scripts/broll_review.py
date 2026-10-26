"""문장별 배경 확인표: 렌더 결과의 배치(placements.json)를 문장과 나란히 놓고, 자료 화면 대표 프레임을 붙인 HTML을 만든다.

사용법: python scripts/broll_review.py 작업폴더 자료폴더 결과.html [--catalog data/broll_catalog.json]
작업폴더에는 placements.json, timeline.json, sentences.txt가 있어야 한다.
"""
import argparse
import base64
import html
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def out_time(src_t: float, clips: list[dict]) -> float | None:
    for c in clips:
        if c["src_start"] - 1e-3 <= src_t <= c["src_end"] + 1e-3:
            return c["out_start"] + (src_t - c["src_start"]) / c.get("speed", 1.0)
    return None


def thumb(path: Path, at: float) -> str:
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=320:-2", "-f", "image2", "-c:v", "mjpeg", "-q:v", "5", "-"],
                       capture_output=True)
    return base64.b64encode(r.stdout).decode() if r.stdout else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work", type=Path)
    ap.add_argument("assets", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--catalog", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "broll_catalog.json")
    a = ap.parse_args()
    pl = json.loads((a.work / "placements.json").read_text(encoding="utf-8"))
    clips = json.loads((a.work / "timeline.json").read_text(encoding="utf-8"))
    cat = {x["file"]: x for x in json.loads(a.catalog.read_text(encoding="utf-8"))} if a.catalog.exists() else {}
    sents = []
    for line in (a.work / "sentences.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\[(\d+)\] \(([\d.]+)s\) (.*)", line)
        if m:
            t = out_time(float(m.group(2)), clips)
            if t is not None:
                sents.append((t, int(m.group(1)), m.group(3)))
    rows = []
    for p in pl:
        if p["mode"] == "side":
            continue
        said = " ".join(f"[{i}] {s}" for t, i, s in sents if p["start"] - 2.5 <= t < p["start"] + p["dur"])
        if p["mode"] == "slide":
            img, what = "", f"슬라이드 카드 {p['asset'].split('/')[-1]} ({p.get('card', '')})"
        else:
            f = a.assets / p["asset"]
            img = thumb(f, 1.5) if f.exists() else ""
            what = cat.get(Path(p["asset"]).name, {}).get("desc", Path(p["asset"]).stem)
        tr = f"{p.get('tin', '') or '-'} → {p.get('tout', '') or '(다음 화면)'}"
        m, s = divmod(p["start"], 60)
        rows.append(f"<tr class='{p['mode']}'><td>{int(m)}:{s:04.1f}<br><small>{p['dur']:.1f}초</small></td>"
                    f"<td>{'<img src=data:image/jpeg;base64,' + img + '>' if img else ''}</td>"
                    f"<td><b>{html.escape(what)}</b><br><small>{html.escape(tr)}</small></td>"
                    f"<td>{html.escape(said)}</td></tr>")
    a.out.write_text(PAGE.replace("{ROWS}", "\n".join(rows)), encoding="utf-8")
    print(f"{len(rows)}줄 → {a.out}")


PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>문장별 배경 확인표</title><style>
:root{--bg:#fff;--fg:#111;--mut:#666;--line:#ddd;--slide:#eef7f2}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#eee;--mut:#999;--line:#333;--slide:#1b2a22}}
body{background:var(--bg);color:var(--fg);font-family:Pretendard,system-ui,sans-serif;margin:16px}
table{border-collapse:collapse;width:100%}td{border-bottom:1px solid var(--line);padding:8px;vertical-align:top;font-size:14px}
td:first-child{white-space:nowrap;color:var(--mut)}img{width:200px;border-radius:6px;display:block}
tr.slide{background:var(--slide)}small{color:var(--mut)}
@media (max-width:640px){img{width:120px}td{font-size:13px}}
</style></head><body><h1>문장별 배경 확인표</h1>
<p>시간 · 화면 · 전환(들어올 때 → 나갈 때) · 그때 하는 말. 초록 줄은 슬라이드 카드.</p>
<table>{ROWS}</table></body></html>"""

if __name__ == "__main__":
    main()
