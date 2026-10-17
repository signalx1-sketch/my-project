"""분석 → 구간 선정 → 렌더링 전체 흐름."""
import json
import logging
from pathlib import Path
from typing import Callable

from . import media
from .captions import build_ass, build_parts, to_output_time
from .inserts import find_pairs, make_card, make_photo
from .config import Options
from .planner import ShortPlan, plan_shorts
from .render import cover_image, render
from .transcribe import transcribe

log = logging.getLogger(__name__)

Progress = Callable[[str, float], None]


def _noop(stage: str, pct: float) -> None:
    log.info("%s (%.0f%%)", stage, pct * 100)


def analyze(src: str, workdir: Path, opts: Options, progress: Progress = _noop) -> dict:
    cache = workdir / "analysis.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    progress("영상 정보 확인 중", 0.02)
    info = media.probe(src)
    analysis = {"probe": info, "envelope": [], "silences": [], "scenes": [], "transcript": []}
    if info["has_audio"]:
        progress("음량 분석 중", 0.05)
        analysis["envelope"] = media.audio_envelope(src)
        analysis["silences"] = media.silences(src)
    progress("장면 전환 분석 중", 0.1)
    analysis["scenes"] = media.scene_changes(src)
    if opts.transcribe and info["has_audio"]:
        progress("음성 인식 중 (영상 길이에 따라 몇 분 걸릴 수 있어요)", 0.15)
        analysis["transcript"] = transcribe(src, opts.whisper_model, opts.language)
    cache.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    return analysis


def all_words(analysis: dict) -> list[dict]:
    return [w for s in analysis.get("transcript", []) for w in s["words"]]


def render_short(src: str, workdir: Path, analysis: dict, plan: ShortPlan, opts: Options,
                 index: int) -> dict:
    info = analysis["probe"]
    words = all_words(analysis)
    parts = build_parts(plan, words, analysis.get("silences", []),
                        cut_silence=opts.cut_silence, zoom_punch=opts.zoom_punch)
    total = sum(p.dur for p in parts)
    ass = build_ass(plan, parts, words, layout=opts.layout, total=total, font="",
                    src_w=info["width"], src_h=info["height"] - opts.crop_bottom,
                    cta_text=opts.cta_text, style=opts.text_style())
    out = workdir / f"short_{index + 1:02d}.mp4"
    images, used = [], []
    for k, ins in enumerate(plan.inserts):
        t = to_output_time(parts, float(ins["at"]))
        if t is None:
            continue
        dur = min(float(ins.get("duration", 3.0)), max(0.5, total - t))
        pairs = find_pairs(ins.get("category", ""))
        pick = ins.get("pick", 0)
        pair = next((p for p in pairs if p["id"] == str(pick)), None) or \
            (pairs[pick % len(pairs)] if pairs and isinstance(pick, int) else None)
        card_path = workdir / f"{out.stem}_ba{k + 1}.png"
        if pair and "image" in pair:
            card = make_photo(pair["image"], card_path)
        else:
            card = make_card(pair and pair["before"], pair and pair["after"], card_path,
                             title=ins.get("title", "실제 치료 전·후"),
                             note=ins.get("note") or (pair or {}).get("note", "") or ins.get("category", ""))
        images.append((card, t, dur))
        used.append({"category": ins.get("category"), "photo": pair["id"] if pair else None,
                     "at": round(t, 2), "duration": dur})
    render(src, out, parts, ass, layout=opts.layout, src_w=info["width"], src_h=info["height"],
           has_audio=info["has_audio"], progress_bar=opts.progress_bar, crop_bottom=opts.crop_bottom,
           images=images)
    cover = out.with_suffix(".jpg")
    cover_image(out, cover, at=min(0.6, total / 2))
    return {
        "index": index,
        "file": out.name,
        "cover": cover.name,
        "duration": round(total, 2),
        "cuts": len(parts),
        "before_after": used,
        "plan": plan.to_dict(),
    }


def make_shorts(src: str, workdir: Path, opts: Options, progress: Progress = _noop) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    analysis = analyze(src, workdir, opts, progress)
    progress("쇼츠 구간·문구 고르는 중", 0.6)
    plans, method = plan_shorts(analysis, opts)
    results = []
    for i, plan in enumerate(plans):
        progress(f"쇼츠 {i + 1}/{len(plans)} 렌더링 중", 0.65 + 0.33 * i / max(1, len(plans)))
        results.append(render_short(src, workdir, analysis, plan, opts, i))
    summary = {"method": method, "source_duration": analysis["probe"]["duration"],
               "has_transcript": bool(analysis["transcript"]), "shorts": results}
    (workdir / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    progress("완료", 1.0)
    return summary
