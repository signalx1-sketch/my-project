"""계획 파일(JSON)대로 쇼츠 렌더링.

  python -m shorts_editor.planfile 계획.json            # 전부
  python -m shorts_editor.planfile 계획.json --only 0 2 # 일부만 다시

계획 파일 형식은 examples/1015_아토피자가진단.plan.json 참고.
- segments: [[시작 초, "마지막 단어"], ...]  → 시작 시각부터 그 단어가 끝나는 곳까지
            [[시작 초, 끝 초], ...]          도 됨
- fixes: 음성 인식 오타 교정 {"틀린 단어": "맞는 단어"} (자막에 반영)
- options: Options 필드 덮어쓰기 (기본값이 더마허브 톤앤매너)
- title_options: 업로드 제목 후보 (title이 추천안). 렌더링 후 titles.md 로 정리됨
"""
import argparse
import json
import logging
from pathlib import Path

from .config import Options
from .pipeline import analyze, render_short
from .planner import ShortPlan


def _span(words: list[dict], start: float, end) -> list[float]:
    if isinstance(end, (int, float)):
        return [float(start), float(end)]
    try:
        last = next(w for w in words if w["start"] >= start - 0.05 and w["text"] == end)
    except StopIteration:
        raise ValueError(f"{start}초 이후에 '{end}' 단어가 없습니다") from None
    return [float(start), last["end"]]


def load_plans(plan: dict, analysis: dict) -> list[ShortPlan]:
    words = [w for s in analysis["transcript"] for w in s["words"]]
    plans = []
    for d in plan["shorts"]:
        segs = [_span(words, s, e) for s, e in d["segments"]]
        plans.append(ShortPlan(
            start=min(s for s, _ in segs), end=max(e for _, e in segs),
            title=d["title"], hook_text=d["hook_text"],
            highlight_words=d.get("highlight_words", []), segments=segs,
            inserts=d.get("inserts", []), reason=d.get("reason", "")))
    return plans


def apply_fixes(analysis: dict, fixes: dict) -> None:
    for seg in analysis["transcript"]:
        for w in seg["words"]:
            w["text"] = fixes.get(w["text"], w["text"])


def run(plan_path: Path, only: set[int] | None = None) -> list[dict]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    base = plan_path.parent
    src = str((base / plan["source"]).resolve())
    work = (base / plan.get("workdir", plan_path.stem)).resolve()
    work.mkdir(parents=True, exist_ok=True)
    opts = Options.from_dict({"teaser": False, **plan.get("options", {})})
    analysis = analyze(src, work, opts)
    apply_fixes(analysis, plan.get("fixes", {}))
    results = []
    for i, p in enumerate(load_plans(plan, analysis)):
        if only and i not in only:
            continue
        r = render_short(src, work, analysis, p, opts, i)
        results.append(r)
        print(f"{r['file']}  {r['duration']}초  사진 {len(r['before_after'])}장  — {p.title}")
    (work / "shorts.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    write_titles(plan, work / "titles.md")
    return results


def write_titles(plan: dict, path: Path) -> None:
    """쇼츠별 업로드 제목(추천안 + 후보)·상단 문구를 붙여넣기 쉽게 정리."""
    lines = ["# 업로드 제목", ""]
    for i, d in enumerate(plan["shorts"], 1):
        lines += [f"## 쇼츠 {i:02d} — 상단 문구: {d['hook_text'].replace(chr(10), ' / ')}", "",
                  f"- **추천** {d['title']}"]
        lines += [f"- {t}" for t in d.get("title_options", []) if t != d["title"]]
        if d.get("description"):
            lines += ["", "설명란:", "", d["description"]]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="계획 파일대로 쇼츠 렌더링")
    ap.add_argument("plan", type=Path)
    ap.add_argument("--only", type=int, nargs="*", help="이 번호(0부터)만 렌더링")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(args.plan, set(args.only or []))


if __name__ == "__main__":
    main()
