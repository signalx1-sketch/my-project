"""사용법: python -m autoedit 원본.mp4 [-o 결과.mp4] [--plan 계획.json] [--bgm 음악.mp3]"""
import argparse
import json
import os
import time
from pathlib import Path

from . import broll, cuts, plan as plan_mod, render, subtitles, timeline, transcribe


def load_dotenv(path: Path):
    """.env 파일의 KEY=VALUE 줄을 환경 변수로 읽는다 (이미 설정된 값은 덮어쓰지 않는다)."""
    import os
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def main():
    p = argparse.ArgumentParser(prog="autoedit", description="토크 영상 자동 편집기")
    p.add_argument("video", type=Path, help="원본 영상")
    p.add_argument("-o", "--out", type=Path, help="결과 영상 (기본: 원본이름_편집.mp4)")
    p.add_argument("--work", type=Path, help="중간 파일 폴더 (기본: 원본이름_work)")
    p.add_argument("--plan", type=Path, help="편집 계획 JSON (콜드 오픈/챕터/키워드)")
    p.add_argument("--bgm", type=Path, help="배경음악 파일 (없으면 생략)")
    p.add_argument("--assets", type=Path, help="자료 화면 폴더 (스톡 영상/이미지)")
    p.add_argument("--broll", type=Path, help="자료 화면 배치 계획 JSON [{at, asset, mode}]")
    p.add_argument("--channel", default="더마허브", help="우상단 로고 글자")
    p.add_argument("--no-ai", action="store_true", help="Claude API를 쓰지 않는다")
    p.add_argument("--model", default="large-v3-turbo", help="음성 인식 모델")
    p.add_argument("--jobs", type=int, default=4, help="동시에 자를 클립 수")
    args = p.parse_args()

    load_dotenv(Path.cwd() / ".env")
    src = args.video.resolve()
    out = (args.out or src.with_name(src.stem + "_편집.mp4")).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    work = (args.work or src.with_name(src.stem + "_work")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("1/4 음성 인식")
    words = transcribe.transcribe(src, work / "words.json", args.model)
    sentences = cuts.split_sentences(words)
    (work / "sentences.txt").write_text(
        "\n".join(f"[{s.idx}] ({s.start:.1f}s) {s.text}" for s in sentences), encoding="utf-8")
    print(f"  단어 {len(words)}개, 문장 {len(sentences)}개 → {work / 'sentences.txt'}")

    print("2/4 편집 계획")
    plan = plan_mod.make_plan(sentences, args.plan, work / "plan.json", use_ai=not args.no_ai)

    print("3/4 타임라인과 자막")
    silences = cuts.detect_silences(src, work / "silences.json")
    tl = timeline.build(words, sentences, plan, silences)
    placements = []
    if args.assets:
        assets = broll.scan_library(args.assets.resolve())
        if not args.no_ai and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            assets = broll.tag_with_claude(args.assets.resolve(), assets, plan_mod.CLAUDE_MODEL)
        print(f"  자료 {len(assets)}개 (영상 {sum(a.kind == 'video' for a in assets)}, 이미지 {sum(a.kind == 'image' for a in assets)})")
        if args.broll:
            items = json.loads(args.broll.read_text(encoding="utf-8"))
        else:
            items = plan_mod.plan_broll(sentences, assets, work / "broll.json", use_ai=not args.no_ai)
        placements = broll.place(items, sentences, assets, tl)
        full = [p for p in placements if p.mode == "full"]
        print(f"  자료 화면 {len(placements)}개 배치 (전체 화면 {len(full)}개, {sum(p.dur for p in full):.0f}초 / 팝업 {len(placements) - len(full)}개)")
    ass, sfx = subtitles.build_ass(words, tl, plan, args.channel)
    sfx = sorted(sfx + [(p.start, "whoosh" if p.mode == "full" else "pop") for p in placements])
    src_len = sentences[-1].end if sentences else 0
    print(f"  {src_len / 60:.1f}분 → {tl.duration / 60:.1f}분 (클립 {len(tl.clips)}개, 효과음 {len(sfx)}개)")
    (work / "timeline.json").write_text(
        json.dumps([c.__dict__ for c in tl.clips], ensure_ascii=False, indent=0), encoding="utf-8")

    print("4/4 렌더링")
    render.render(src, tl, ass, sfx, out, work, bgm=args.bgm, jobs=args.jobs, placements=placements)
    print(f"완료: {out}  ({(time.time() - t0) / 60:.1f}분 걸림)")


if __name__ == "__main__":
    main()
