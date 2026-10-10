"""사용법: python -m autoedit 원본.mp4 [-o 결과.mp4] [--plan 계획.json] [--bgm 음악.mp3]"""
import argparse
import json
import os
import time
from pathlib import Path

from . import broll, cuts, fonts, plan as plan_mod, render, slides as slides_mod, subtitles, timeline, transcribe


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
    p.add_argument("--rename-assets", action="store_true",
                   help="자료 파일 이름을 내용 설명으로 바꾼다 (원래 이름은 rename_log.json에 남음)")
    p.add_argument("--broll", type=Path, help="자료 화면 배치 계획 JSON [{at, asset, mode}]")
    p.add_argument("--slides", type=Path, help="발표 슬라이드(pptx). 말하는 순간에 맞춰 화면 전체에 띄운다")
    p.add_argument("--face", type=float, default=broll.FACE_TARGET,
                   help="본편에서 얼굴이 그대로 보이는 시간 비율 목표 (기본 0.2)")
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
    placements, slide_items, items, assets = [], [], [], []
    if args.slides:
        sl = slides_mod.load(args.slides.resolve(), work)
        matched = slides_mod.match(sl, sentences, words, plan.get("chapters", []))
        slide_items = [{"asset": broll.Asset(f"슬라이드/{m['slide'].no:02d}", m["slide"].path, "slide", 0.0,
                                             m["slide"].text), "t": m["t"]} for m in matched]
        (work / "slides.json").write_text(json.dumps(
            [{"slide": m["slide"].no, "t": m["t"], "matched": m["matched"], "text": m["slide"].text} for m in matched],
            ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"  슬라이드 {len(sl)}장 → 대본에 맞춤 (글자로 {sum(m['matched'] == 'text' for m in matched)}장, "
              f"챕터 표지 {sum(m['matched'] == 'chapter' for m in matched)}장, 사이에 끼움 "
              f"{sum(m['matched'] == 'between' for m in matched)}장) → {work / 'slides.json'}")
    if args.assets:
        assets = broll.scan_library(args.assets.resolve())
        if not args.no_ai and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            assets = broll.tag_with_claude(args.assets.resolve(), assets, plan_mod.CLAUDE_MODEL)
        if args.rename_assets:
            n = broll.rename_by_tags(args.assets.resolve())
            print(f"  자료 파일 {n}개 이름 변경")
            assets = broll.scan_library(args.assets.resolve())
        print(f"  자료 {len(assets)}개 (영상 {sum(a.kind == 'video' for a in assets)}, 이미지 {sum(a.kind == 'image' for a in assets)})")
        if args.broll:
            items = json.loads(args.broll.read_text(encoding="utf-8"))
        else:
            items = plan_mod.plan_broll(sentences, assets, work / "broll.json", use_ai=not args.no_ai)
        # 파일명 규칙 후보도 보탠다: 얼굴 옆 팝업(제품/논문/도표가 문장과 정확히 맞을 때)과
        # 얼굴 비율을 맞출 때 쓸 채움용 자료. 계획에 적힌 자료가 항상 먼저 쓰인다.
        items += [dict(x, auto=True) for x in broll.suggest_with_rules(sentences, assets)
                  if x.get("filler") or x["mode"] == "side"]
    if slide_items or items:
        placements = broll.place(items, sentences, assets, tl, slide_items, args.face)
        cnt = {m: [p for p in placements if p.mode == m] for m in ("slide", "full", "side")}
        body = [c for c in tl.clips if c.kind == "body"]
        body_len = (tl.duration - 6.5) - body[0].out_start if body else 1
        cover = sum(p.dur for p in placements if p.mode != "side")
        print(f"  화면 배치: 슬라이드 {len(cnt['slide'])}장 {sum(p.dur for p in cnt['slide']):.0f}초, "
              f"전체 화면 자료 {len(cnt['full'])}개 {sum(p.dur for p in cnt['full']):.0f}초, 팝업 {len(cnt['side'])}개 "
              f"/ 본편 중 얼굴 {100 * (1 - cover / body_len):.0f}%")
    hide = [(p.start, p.start + p.dur) for p in placements if p.mode == "slide"]
    ass, sfx = subtitles.build_ass(words, tl, plan, args.channel, fonts.caption_fonts(), hide)
    # 전체 화면 자료는 화면 전환 자체가 효과라서 소리를 넣지 않고, 얼굴 옆 팝업에만 작게 넣는다
    sfx = sorted(sfx + [(p.start, "pop") for p in placements if p.mode == "side"])
    src_len = sentences[-1].end if sentences else 0
    print(f"  {src_len / 60:.1f}분 → {tl.duration / 60:.1f}분 (클립 {len(tl.clips)}개, 효과음 {len(sfx)}개)")
    (work / "timeline.json").write_text(
        json.dumps([c.__dict__ for c in tl.clips], ensure_ascii=False, indent=0), encoding="utf-8")

    print("4/4 렌더링")
    render.render(src, tl, ass, sfx, out, work, bgm=args.bgm, jobs=args.jobs, placements=placements)
    print(f"완료: {out}  ({(time.time() - t0) / 60:.1f}분 걸림)")


if __name__ == "__main__":
    main()
