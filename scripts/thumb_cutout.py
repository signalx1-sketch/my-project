"""원장님 프레임에서 사람만 오려 내는 마스크 (OpenCV GrabCut, 외부 모델 없음).

사용법: python scripts/thumb_cutout.py 원장님프레임.png 마스크.png  (1920x1080, 원장님이 화면 가운데 오른쪽에 앉은 구도 기준)
"""
import sys
import cv2
import numpy as np
src, out = sys.argv[1:3]
im = cv2.imread(src); h, w = im.shape[:2]
mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
cv2.ellipse(mask, (1080, 560), (170, 230), 0, 0, 360, cv2.GC_PR_FGD, -1)
cv2.rectangle(mask, (640, 760), (1420, 1080), cv2.GC_PR_FGD, -1)
cv2.ellipse(mask, (1080, 620), (110, 150), 0, 0, 360, cv2.GC_FGD, -1)
cv2.rectangle(mask, (820, 900), (1330, 1080), cv2.GC_FGD, -1)
mask[:760, :880] = cv2.GC_BGD; mask[:820, 1290:] = cv2.GC_BGD; mask[:330, :] = cv2.GC_BGD
mask[:, :600] = cv2.GC_BGD; mask[:, 1480:] = cv2.GC_BGD
mask[600:800, 840:935] = cv2.GC_BGD
bg = np.zeros((1, 65)); fg = np.zeros((1, 65))
cv2.grabCut(im, mask, None, bg, fg, 6, cv2.GC_INIT_WITH_MASK)
b = np.where((mask == 1) | (mask == 3), 255, 0).astype(np.uint8)
b = cv2.morphologyEx(b, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
b = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((13, 13), np.uint8))
# 머리 위쪽은 실제 머리카락(어두운 픽셀)만 남긴다: 마스크가 머리보다 조금 크면 뒤 가구 틈이 딸려 온다
gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
hair = cv2.morphologyEx((gray < 110).astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
hair = cv2.morphologyEx(hair, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))  # 가는 선(가구 틈)은 지운다
b[:470] = cv2.bitwise_and(b[:470], hair[:470])
n, lab, st, _ = cv2.connectedComponentsWithStats(b)
k = 1 + np.argmax(st[1:, cv2.CC_STAT_AREA]); b = np.where(lab == k, 255, 0).astype(np.uint8)
# 윤곽 안쪽 구멍(가르마 등 밝은 두피)은 채운다
cs, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
b = np.zeros_like(b); cv2.drawContours(b, cs, -1, 255, -1)
cv2.imwrite(out, cv2.GaussianBlur(b, (0, 0), 1.8))
