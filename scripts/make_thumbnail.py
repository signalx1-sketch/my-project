"""썸네일 (레퍼런스 dybUda36l7A 톤): 흰 배경, 왼쪽 흐린 관련 장면, 오른쪽 원장님, 왼쪽 위 빨간 질환 키워드,
오른쪽 위 손글씨 괄호, 아래 노란/흰 큰 글자 두 줄(검은 테두리). 문구는 아래 text(...) 줄을 바꿔 쓴다.
사용법: python scripts/make_thumbnail.py 폴더(doc.png, 배경 이미지, fonts/) 결과.jpg 배경파일 [흐림] [배경 x오프셋]
글꼴: Black Han Sans, Nanum Pen Script (Google Fonts, OFL) → assets/fonts/thumb"""
import sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
T = sys.argv[1]; F = T + "/fonts/"; out = sys.argv[2]
W, H = 1280, 720
canvas = Image.new("RGB", (W, H), "white")
# 왼쪽 배경: 휴대폰 메모 장면을 흐리고 밝게 (레퍼런스의 흐린 연고 사진처럼)
bg = Image.open(T + "/" + sys.argv[3]).convert("RGB")
bg = bg.resize((int(bg.width * H / bg.height), H))
ox = int(sys.argv[5]) if len(sys.argv) > 5 else 0
bg = bg.crop((ox, 0, ox + 760, H)).filter(ImageFilter.GaussianBlur(int(sys.argv[4]) if len(sys.argv) > 4 else 14))
bg = ImageEnhance.Brightness(bg).enhance(1.45)
bg = Image.blend(bg, Image.new("RGB", bg.size, "white"), 0.45)
canvas.paste(bg, (0, 0))
# 오른쪽: 원장님 (가장자리를 부드럽게 흰색으로)
doc = Image.open(T + "/doc.png").convert("RGB")
crop = doc.crop((660, 260, 1370, 1060)).resize((640, 720))
crop = ImageEnhance.Brightness(crop).enhance(1.08)
mask = Image.new("L", crop.size, 255)
md = ImageDraw.Draw(mask)
for x in range(130):
    md.line([(x, 0), (x, H)], fill=int(255 * x / 130))
canvas.paste(crop, (W - 640, 0), mask)
d = ImageDraw.Draw(canvas)

def text(xy, s, font, fill, stroke, sw, anchor="la"):
    d.text(xy, s, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor)

bh = lambda n: ImageFont.truetype(F + "BlackHanSans-Regular.ttf", n)
pen = ImageFont.truetype(F + "NanumPenScript-Regular.ttf", 58)
# 왼쪽 위 빨간 키워드
pk = ImageFont.truetype("/home/user/my-project/assets/fonts/Pretendard-ExtraBold.otf", 70)
text((330, 165), "지루성피부염 ·", pk, "#F0384A", "white", 10, "ma")
text((330, 250), "접촉성 · 주사피부", pk, "#F0384A", "white", 10, "ma")
# 오른쪽 위 손글씨
text((1105, 40), "(난치 피부", pen, "#111111", "white", 3, "ma")
text((1105, 95), "18년 본 원장)", pen, "#111111", "white", 3, "ma")
# 아래 큰 두 줄
text((52, 432), "피부과 가기 전에", bh(118), "#FFF200", "black", 12)
text((52, 568), "‘이것’만 외우세요", bh(118), "white", "black", 12)
canvas.save(out, quality=95)
