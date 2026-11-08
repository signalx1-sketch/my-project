"""편집기가 만든 자막(subs.ass)을 유튜브에 올릴 SRT로 바꾼다.
사용법: python scripts/ass2srt.py work/subs.ass 결과.srt
"""
import re
import sys


def ts(t: str) -> str:
    h, m, s = t.split(":")
    sec = int(h) * 3600 + int(m) * 60 + float(s)
    ms = round(sec * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main():
    src, out = sys.argv[1:3]
    rows = []
    for line in open(src, encoding="utf-8"):
        if not line.startswith("Dialogue:"):
            continue
        parts = line.rstrip("\n").split(",", 9)
        start, end, style, text = parts[1], parts[2], parts[3], parts[9]
        if style != "Cap":  # 말 자막만 (로고·챕터 라벨·구독 안내 그림은 빼고)
            continue
        text = re.sub(r"\{[^}]*\}", "", text).replace("\\N", "\n").replace("\\h", " ").strip()
        if text:
            rows.append((start, end, text))
    rows.sort(key=lambda r: r[0])
    with open(out, "w", encoding="utf-8") as f:
        for i, (a, b, t) in enumerate(rows, 1):
            f.write(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n\n")
    print(len(rows))


if __name__ == "__main__":
    main()
