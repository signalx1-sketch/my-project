"""유튜브 댓글 캡처를 휴대폰 화면처럼 좁게 다시 쌓는다 (2026-11-25).

데스크톱에서 찍은 댓글 캡처는 한 줄이 화면 끝까지 길어서 영상에 그대로 넣으면 글자가 아주 작다.
글자를 다시 쓰지 않고 캡처 픽셀 그대로, 낱말 사이 빈칸에서 잘라 좁은 폭으로 줄을 다시 쌓고 키운다.
(사용자: 디자인한 댓글 카드는 주작 느낌이 난다, 원본 스샷 그대로)

사용법:
  python scripts/comment_reflow.py 캡처.png --words            # 낱말 번호표(캡처.words.png)를 만들어 고를 범위를 본다
  python scripts/comment_reflow.py 캡처.png -o 출력.png --rows 0:90 --pick 0:8,20:35 --width 760 --scale 2
--pick 범위 사이와 (--more면) 끝에 '…'를 넣는다. 오른쪽 끝에서 잘린 낱말은 뺀다.
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DARK = 90       # 본문 글자(#0f0f0f 근처). '자세히 알아보기' 같은 회색 글자는 빼려고 어두운 것만 센다
LIGHT = 200     # 글자 가장자리까지 자르려고 옅은 획도 센다
WORD_GAP = 7    # 낱말 사이 빈칸(px)은 7~9px, 글자 사이는 1~6px (캡처에서 잼)
FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Pretendard-Bold.otf"


def bands(dark):
    out, s = [], None
    for y, v in enumerate(dark.sum(1)):
        if v and s is None:
            s = y
        elif not v and s is not None:
            out.append((s, y)); s = None
    if s is not None:
        out.append((s, len(dark)))
    return out


def words_of(img, rows):
    rgb = np.asarray(img).astype(int)
    g = rgb.mean(2)
    gray = (rgb.max(2) - rgb.min(2)) < 40          # 색 있는 프로필 동그라미는 글자로 치지 않는다
    ink = (g < LIGHT) & gray                         # 글자 획 끝(옅은 가장자리)까지: ㅔ의 둘째 세로획이 옅다
    r0, r1 = rows
    dark = (g[r0:r1] < DARK) & gray[r0:r1]
    bl = [(s + r0, e + r0) for s, e in bands(dark) if e - s >= 8]
    if not bl:
        raise SystemExit("본문 줄을 못 찾음")
    x0 = min(int(np.where(((g[s:e] < DARK) & gray[s:e]).any(0))[0].min()) for s, e in bl)
    lh = max(e - s for s, e in bl)
    out = []
    for s, e in bl:
        top, bot = s - 4, s + lh + 5
        cols = ((g[s:e, x0:] < DARK) & gray[s:e, x0:]).any(0)   # 빈칸은 진한 획으로 찾고
        soft = ink[s:e, x0:].any(0)                               # 낱말 끝은 옅은 획까지 늘린다
        xs = np.where(cols)[0]
        segs, a, last = [], xs[0], xs[0]
        for x in xs[1:]:
            if x - last > WORD_GAP:
                segs.append((a, last)); a = x
            last = x
        segs.append((a, last))
        if x0 + segs[-1][1] >= img.width - 3:      # 오른쪽 끝에서 잘린 낱말
            segs = segs[:-1]
        grown = []
        for i, (a, b) in enumerate(segs):
            nxt = segs[i + 1][0] if i + 1 < len(segs) else len(soft)
            for x in range(b + 1, min(b + 6, nxt - 3)):       # 옅은 획이 5px 안에 있으면 낱말 끝을 거기까지
                if soft[x]:
                    b = x
            grown.append((a, b))
        segs = grown
        out += [img.crop((x0 + a - 1, top, x0 + b + 2, bot)) for a, b in segs]
    return out, x0, bl[0][0], lh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--rows", default="0:9999", help="댓글 하나가 있는 세로 범위 (캡처에 댓글이 여럿일 때)")
    ap.add_argument("--pick", default="", help="쓸 낱말 번호 범위들 a:b,c:d (빈 값이면 전부)")
    ap.add_argument("--more", action="store_true", help="끝에 … 붙이기")
    ap.add_argument("--width", type=int, default=760, help="다시 쌓을 본문 폭 (원본 px)")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--words", action="store_true", help="낱말 번호표만 만든다")
    a = ap.parse_args()
    img = Image.open(a.src).convert("RGB")
    r = [int(x) for x in a.rows.split(":")]
    r[1] = min(r[1], img.height)
    ws, x0, y0, lh = words_of(img, r)
    if a.words:
        W = 1400; sheet = Image.new("RGB", (W, 2000), "white"); d = ImageDraw.Draw(sheet)
        f = ImageFont.truetype(str(FONT), 14); x = y = 10
        for i, w in enumerate(ws):
            if x + w.width > W - 10:
                x, y = 10, y + lh + 30
            sheet.paste(w, (x, y + 16)); d.text((x, y), str(i), fill="red", font=f); x += w.width + 14
        sheet.crop((0, 0, W, y + lh + 30)).save(a.src.with_suffix(".words.png"))
        print(len(ws), "words →", a.src.with_suffix(".words.png"))
        return
    picks = [tuple(int(v) for v in p.split(":")) for p in a.pick.split(",")] if a.pick else [(0, len(ws))]
    font = ImageFont.truetype(str(FONT), int(lh * 1.05))
    dot = Image.new("RGB", (int(lh * 1.1), ws[0].height), "white")
    ImageDraw.Draw(dot).text((1, 3), "…", fill=(15, 15, 15), font=font)
    seq = []
    for i, (p, q) in enumerate(picks):
        seq += ws[p:q]
        if i < len(picks) - 1 or a.more:
            seq.append(dot)
    space, lstep = 6, lh + 10
    lines, cur, cw = [], [], 0
    for w in seq:
        if cur and cw + space + w.width > a.width:
            lines.append(cur); cur, cw = [], 0
        cw += (space if cur else 0) + w.width; cur.append(w)
    lines.append(cur)
    head = img.crop((0, 0, min(img.width, x0 + a.width), y0 - 3))        # 흐린 프로필·닉네임 줄 그대로
    H = head.height + len(lines) * lstep + 14
    canvas = Image.new("RGB", (x0 + a.width + 30, H), "white")
    canvas.paste(head, (0, 0))
    av = img.crop((0, y0 - 3, x0 - 4, min(img.height, y0 + 2 * lstep)))   # 프로필 동그라미 아래쪽
    canvas.paste(av, (0, head.height))
    y = head.height - 1
    for ln in lines:
        x = x0
        for w in ln:
            canvas.paste(w, (x, y)); x += w.width + space
        y += lstep
    out = canvas.resize((int(canvas.width * a.scale), int(canvas.height * a.scale)), Image.LANCZOS)
    out.save(a.out)
    print(a.out, out.size, len(lines), "줄")


if __name__ == "__main__":
    main()
