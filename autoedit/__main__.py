"""사용법: python -m autoedit 원본.mp4 [-o 결과.mp4] [--plan 계획.json] [--bgm 음악.mp3]"""
import argparse
import json
import os
import time
from pathlib import Path

from . import broll, cuts, progress, fonts, motion, motion_hf, plan as plan_mod, render, slides as slides_mod, subtitles, timeline, transcribe


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


SFX_CARDS = {"bubble", "checklist", "timer", "merge", "compare2", "graph", "warning"}


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
    p.add_argument("--slide-font", choices=["readable", "original"], default="readable",
                   help="슬라이드 글꼴: readable(Pretendard, 작은 글씨 키움) 또는 original(파일에 지정된 글꼴)")
    p.add_argument("--cards", type=Path,
                   help="슬라이드별 카드 템플릿 설정 JSON (아이콘 줄, 휴대폰 메모, 비교, 타임라인 등. motion_templates 참고)")
    p.add_argument("--no-transitions", action="store_true",
                   help="화면 전환 효과(원형, 와이프, 밀기, 디졸브)를 쓰지 않고 예전처럼 컷/짧은 페이드만")
    p.add_argument("--no-motion", action="store_true",
                   help="슬라이드를 모션 그래픽 카드로 만들지 않고 정지 이미지로 쓴다")
    p.add_argument("--popups", action="store_true",
                   help="얼굴 옆 팝업 자료를 넣는다 (기본은 넣지 않음: 내용이 정확히 맞는 자료가 드물다)")
    p.add_argument("--face", type=float, default=broll.FACE_TARGET,
                   help="본편에서 얼굴이 그대로 보이는 시간 비율 목표 (기본 0.2)")
    p.add_argument("--caption-style", choices=list(subtitles.CAPTION_STYLES), default=subtitles.DEFAULT_CAPTION_STYLE,
                   help="자막 모양: reference(더마허브 레퍼런스: Pretendard, 반투명 박스) 또는 aggro(어그로체 큰 글씨)")
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
    n_rep = cuts.mark_repeats(words)  # 같은 말을 바로 다시 한 곳은 마지막 것만 남긴다
    n_rep += cuts.mark_restarts(words)  # 말을 하다 끊고 다시 시작한 조각도 지운다
    sentences = cuts.split_sentences(words)
    (work / "sentences.txt").write_text(
        "\n".join(f"[{s.idx}] ({s.start:.1f}s) {s.text}" for s in sentences), encoding="utf-8")
    print(f"  단어 {len(words)}개, 문장 {len(sentences)}개 (반복한 말 {n_rep}단어 제거) → {work / 'sentences.txt'}")

    print("2/4 편집 계획")
    plan = plan_mod.make_plan(sentences, args.plan, work / "plan.json", use_ai=not args.no_ai)

    print("3/4 타임라인과 자막")
    silences = cuts.detect_silences(src, work / "silences.json")
    # 숨소리, 쩝 소리, 잡음처럼 소리는 있지만 말이 아닌 구간도 잘라낸다
    nonspeech = cuts.detect_nonspeech(src, work / "nonspeech.json")
    # 음성 검출이 '말이 아님'이라고 해도 인식된 단어와 겹치면 자르지 않는다 (단어 가운데가 잘려 말이 씹힌다)
    n0 = len(nonspeech)
    nonspeech = [h for h in nonspeech if not any(w["s"] + 0.03 < h[1] and h[0] < w["e"] - 0.03 for w in words)]
    if n0 != len(nonspeech):
        print(f"  단어와 겹치는 숨소리 구간 {n0 - len(nonspeech)}개는 자르지 않음")
    # "어~", "음~" 같은 군말과 길게 끈 모음 (인식기가 받아 적지 않고 옆 단어에 붙여 버린 것)
    drawls = cuts.detect_drawls(src, words, work / "drawls.json") + cuts.detect_fillers_asr(src, work / "words_fillers.json")
    if drawls:
        print(f"  군말/끈 모음 {len(drawls)}곳 {sum(b - a for a, b in drawls):.1f}초 잘라냄")
    # 계획에 직접 적은 잘라낼 구간 (말이 씹혀서 다시 한 곳 등). 원본 기준 [시작, 끝] 초
    manual = [tuple(x) for x in plan.get("cut", [])]
    if manual:
        print(f"  계획에 적은 컷 {len(manual)}곳")
        drawls = drawls + manual
    for w in words:  # 통째로 잘린 군말 단어는 자막에도 안 나오게
        if any(a <= w["s"] + 0.05 and w["e"] - 0.06 <= b for a, b in drawls):
            w["drop"] = True
    silences = sorted(set(silences) | set(nonspeech) | set(drawls))
    retakes = cuts.find_retakes(sentences, words)
    if retakes:
        plan["skip"] = plan.get("skip", []) + [{"from": i, "to": i} for i in retakes]
        print(f"  다시 찍은 문장 {len(retakes)}개는 앞의 것을 뺍니다: {retakes}")
    tl = timeline.build(words, sentences, plan, silences)
    placements, slide_items, items, assets = [], [], [], []
    if args.slides:
        sl = slides_mod.load(args.slides.resolve(), work, readable=args.slide_font == "readable")
        matched = slides_mod.match(sl, sentences, words, plan.get("chapters", []))
        # 계획의 slide_at으로 슬라이드 시각을 직접 고정한다: {"슬라이드 번호": 문장 번호 또는 [문장 번호, 몇 초 뒤]}
        by_idx = {s.idx: s for s in sentences}
        for no, at in (plan.get("slide_at") or {}).items():
            si, off = (at, 0.0) if isinstance(at, int) else (at[0], at[1])
            for m in matched:
                if m["slide"].no == int(no) and si in by_idx:
                    m["t"], m["matched"] = round(by_idx[si].start + off, 2), "plan"
        matched.sort(key=lambda m: (m["t"], m["slide"].no))
        # 슬라이드를 움직이는 카드로 (숫자 카운트업, 줄마다 등장, 막대 비교). 못 만들면 정지 이미지
        # HyperFrames로 만들고, 쓸 수 없으면 자체 렌더러(Playwright)로 대신한다
        cards = None
        specs = json.loads(args.cards.read_text(encoding="utf-8")) if args.cards else {}
        card_kind = motion_hf.card_kinds(args.slides.resolve(), specs)
        if not args.no_motion:
            cards = motion_hf.render(args.slides.resolve(), work, specs) or motion.render(args.slides.resolve(), work)
        slide_items = [{"asset": broll.Asset(f"슬라이드/{m['slide'].no:02d}",
                                             cards[m["slide"].no][0] if cards and m["slide"].no in cards else m["slide"].path,
                                             "slide", 0.0, m["slide"].text), "t": m["t"]} for m in matched]
        # 슬라이드에 적힌 용어로 자막 오타를 고친다 (직접 적은 fix가 우선)
        auto_fix = slides_mod.term_fixes(sl, words)
        plan["fix"] = {**auto_fix, **plan.get("fix", {})}
        if auto_fix:
            print("  슬라이드 용어로 자막 교정: " + ", ".join(f"{a}→{b}" for a, b in auto_fix.items()))
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
        # 배치 계획을 직접 준 경우(문장마다 내용을 보고 고른 것)에는 파일명 규칙 후보를 섞지 않는다:
        # 규칙 후보는 내용이 느슨하게 맞아서 엉뚱한 장면이 끼어든다. 맞는 자료가 없으면 얼굴로 둔다
        if not args.broll:
            items += [dict(x, auto=True) for x in broll.suggest_with_rules(sentences, assets)
                      if x.get("filler") or (x["mode"] == "side" and args.popups)]
        if not args.popups:
            items = [x for x in items if x.get("mode", "full") != "side"]
    if slide_items or items:
        placements = broll.place(items, sentences, assets, tl, slide_items, args.face)
        for pl in placements:
            if pl.mode == "slide":
                pl.card = card_kind.get(int(pl.asset.id.split("/")[-1]), "")
        if not args.no_transitions:
            broll.assign_transitions(placements)
            tr = [x for pl in placements for x in (pl.tin, pl.tout) if x]
            print("  화면 전환: " + ", ".join(f"{k} {tr.count(k)}" for k in sorted(set(tr))))
        cnt = {m: [p for p in placements if p.mode == m] for m in ("slide", "full", "side")}
        body = [c for c in tl.clips if c.kind == "body"]
        body_len = (tl.duration - 6.5) - body[0].out_start if body else 1
        cover = sum(p.dur for p in placements if p.mode != "side")
        print(f"  화면 배치: 슬라이드 {len(cnt['slide'])}장 {sum(p.dur for p in cnt['slide']):.0f}초, "
              f"전체 화면 자료 {len(cnt['full'])}개 {sum(p.dur for p in cnt['full']):.0f}초, 팝업 {len(cnt['side'])}개 "
              f"/ 본편 중 얼굴 {100 * (1 - cover / body_len):.0f}%")
    (work / "placements.json").write_text(json.dumps(
        [{"start": p.start, "dur": p.dur, "mode": p.mode, "asset": p.asset.id, "tin": p.tin, "tout": p.tout,
          "extend": p.extend, "card": p.card} for p in placements],
        ensure_ascii=False, indent=0), encoding="utf-8")
    hide = [(p.start, p.start + p.dur) for p in placements if p.mode == "slide"]
    ass, sfx = subtitles.build_ass(words, tl, plan, args.channel, fonts.caption_fonts(), hide,
                                   args.caption_style)
    # 전체 화면 자료는 화면 전환 자체가 효과라서 소리를 넣지 않고, 얼굴 옆 팝업에만 작게 넣는다
    # 파트 표지(초록 패널이 쓸고 지나감)에만 작은 휙 소리
    sfx = render.thin_sfx(sfx + [(p.start, "pop") for p in placements if p.mode == "side"]
                          + [(p.start + 0.25, "whoosh") for p in placements if p.card == "part"]
                          # 강조 카드(✕/✓ 말풍선, 체크리스트, 타이머, 합치기, 비교)에 작은 뽁 소리. 30초 간격으로 솎아진다
                          + [(p.start + 0.45, "pop") for p in placements if p.card in SFX_CARDS], tl.duration)
    tabs = None
    if (plan.get("progress") or {}).get("labels"):
        wins = progress.windows(tl, plan, tl.duration)
        tabs = (progress.make_tabs(plan["progress"]["labels"], work / "tabs"), wins)
        print(f"  위쪽 진행 표시: {len(wins)}개 파트")
    src_len = sentences[-1].end if sentences else 0
    print(f"  {src_len / 60:.1f}분 → {tl.duration / 60:.1f}분 (클립 {len(tl.clips)}개, 효과음 {len(sfx)}개)")
    (work / "timeline.json").write_text(
        json.dumps([c.__dict__ for c in tl.clips], ensure_ascii=False, indent=0), encoding="utf-8")

    print("4/4 렌더링")
    render.render(src, tl, ass, sfx, out, work, bgm=args.bgm, jobs=args.jobs, placements=placements, tabs=tabs)
    print(f"완료: {out}  ({(time.time() - t0) / 60:.1f}분 걸림)")


if __name__ == "__main__":
    main()
