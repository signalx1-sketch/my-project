# 원장님이 화면 가운데 앉은 구도(보습 영상, 2026-11-04) 오리기: python3 scripts/thumb_cutout_center.py 프레임.png 마스크.png [머리 가운데 x-1000]
import sys, cv2, numpy as np
src, out = sys.argv[1:3]
dx = int(sys.argv[3]) if len(sys.argv) > 3 else 0  # 머리 가운데가 x=1000에서 얼마나 옮겨 있는지
im = cv2.imread(src); h, w = im.shape[:2]; g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
mask = np.full((h, w), cv2.GC_BGD, np.uint8)
mask[340:1080, 480:1500] = cv2.GC_PR_BGD
cv2.ellipse(mask, (1000 + dx, 560), (150, 190), 0, 0, 360, cv2.GC_PR_FGD, -1)
cv2.ellipse(mask, (1000 + dx, 590), (95, 140), 0, 0, 360, cv2.GC_FGD, -1)
mask[820:1080, 620:1380] = cv2.GC_PR_FGD; mask[900:1080, 760:1240] = cv2.GC_FGD
bg = np.zeros((1, 65)); fg = np.zeros((1, 65))
cv2.grabCut(im, mask, None, bg, fg, 6, cv2.GC_INIT_WITH_MASK)
b = np.where((mask == 1) | (mask == 3), 255, 0).astype(np.uint8)
b[600:700, 780+dx:870+dx][g[600:700, 780+dx:870+dx] < 100] = 0
r = np.zeros_like(b); r[780:920, 600:1420] = 1; r[780:920, 780:1220] = 0; b[(r == 1) & (g < 120)] = 0
b[650:820, 1185+dx:1230+dx][g[650:820, 1185+dx:1230+dx] < 105] = 0
b[:700, 1215+dx:] = 0  # 머리 오른쪽 바깥(책장)
b[470:800, 1142+dx:] = 0  # 귀 아래 의자 등받이
b[:560, :780+dx] = 0; b[560:700, :815+dx] = 0  # 머리 왼쪽 바깥(선반)
b[800:880, :790+dx] = 0; b[800:880, 1280+dx:] = 0  # 어깨 옆 의자
b = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
b = cv2.morphologyEx(b, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
n, lab, st, _ = cv2.connectedComponentsWithStats(b); k = 1 + np.argmax(st[1:, cv2.CC_STAT_AREA]); b = (lab == k).astype(np.uint8) * 255

cs, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE); b2 = np.zeros_like(b); cv2.drawContours(b2, cs, -1, 255, -1)
cv2.imwrite(out, cv2.GaussianBlur(b2, (5, 5), 0))
