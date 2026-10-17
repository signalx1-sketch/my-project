"""명령줄 사용: python -m shorts_editor 원본.mp4 --count 3"""
import argparse
import json
import logging
from pathlib import Path

from .config import DATA_DIR, Options
from .pipeline import make_shorts


def main() -> None:
    ap = argparse.ArgumentParser(description="원본 영상을 쇼츠로 자동 편집")
    ap.add_argument("video")
    ap.add_argument("--out", type=Path, default=None, help="결과 폴더 (기본: data/cli/<파일명>)")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--min-len", type=float, default=20)
    ap.add_argument("--max-len", type=float, default=45)
    ap.add_argument("--layout", choices=["blur", "crop"], default="blur")
    ap.add_argument("--no-ai", action="store_true", help="Claude 없이 자동 분석만 사용")
    ap.add_argument("--no-transcribe", action="store_true", help="음성 인식(자막) 끄기")
    ap.add_argument("--no-teaser", action="store_true")
    ap.add_argument("--no-silence-cut", action="store_true")
    ap.add_argument("--language", default="ko")
    ap.add_argument("--crop-bottom", type=int, default=0, help="원본 하단에 박힌 자막을 가릴 때 잘라낼 픽셀 수")
    ap.add_argument("--cta", default="", help="마지막 3초 하단 문구 (예: '풀영상은 고정 댓글에')")
    ap.add_argument("--header", choices=["bar", "float"], default="bar", help="상단 문구 스타일")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    opts = Options(count=args.count, min_len=args.min_len, max_len=args.max_len, layout=args.layout,
                   use_ai=not args.no_ai, transcribe=not args.no_transcribe, teaser=not args.no_teaser,
                   cut_silence=not args.no_silence_cut, language=args.language or None,
                   crop_bottom=args.crop_bottom, cta_text=args.cta, header_style=args.header)
    out = args.out or DATA_DIR / "cli" / Path(args.video).stem
    summary = make_shorts(args.video, out, opts)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n결과 폴더: {out}")


if __name__ == "__main__":
    main()
