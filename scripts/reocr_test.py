# -*- coding: utf-8 -*-
"""놓친 영역 부분 재OCR 실전 테스트 — Mathpix v3/text (그림 한 장 단위 과금)."""
import base64, json, os, urllib.request
import fitz
from PIL import Image

PDF = "/tmp/gsrc.pdf"
doc = fitz.open(PDF)
page = doc[19]                      # 원본 20쪽
W = 1965
zoom = W / page.rect.width
pix = page.get_pixmap(matrix=fitz.Matrix(zoom * 2, zoom * 2))   # 재OCR용은 2배 해상도
im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

# 감지된 조각(1200,400-1456,496)을 문제 블록 전체로 넉넉히 확장 (오른쪽 열 위쪽)
box = (1000 * 2, 370 * 2, 1620 * 2, 660 * 2)
crop = im.crop(box)
crop.save("/tmp/reocr_in.png")
data = base64.b64encode(open("/tmp/reocr_in.png", "rb").read()).decode()

body = json.dumps({
    "src": "data:image/png;base64," + data,
    "formats": ["text"],
    "rm_spaces": False,
}).encode()
req = urllib.request.Request(
    "https://api.mathpix.com/v3/text", data=body, method="POST",
    headers={"app_id": os.environ["MATHPIX_APP_ID"],
             "app_key": os.environ["MATHPIX_APP_KEY"],
             "Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=60) as r:
    out = json.loads(r.read())
print("=== 재OCR 결과 ===")
print(out.get("text"))
print("신뢰도:", out.get("confidence"))
