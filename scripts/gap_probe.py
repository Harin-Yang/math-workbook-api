# -*- coding: utf-8 -*-
"""놓친 영역 감지 시제품 — 원본 쪽 잉크와 Mathpix 줄 영역을 대조한다."""
import json, sys
import fitz
from PIL import Image, ImageDraw

PDF = "/tmp/gsrc.pdf"
LINES = "/data/mathpix-cache/runs/[신사고 고등 기하] 05_공간도형/result.lines.json"
data = json.load(open(LINES))
doc = fitz.open(PDF)

def detect(page_no):
    pg = next(p for p in data["pages"] if p["page"] == page_no)
    W, H = pg["page_width"], pg["page_height"]
    page = doc[page_no - 1]
    zoom = W / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY)
    im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    # 줄 영역 가리기 (여유 8px)
    mask = Image.new("L", im.size, 0)
    dr = ImageDraw.Draw(mask)
    for ln in pg["lines"]:
        # 빈 껍데기(column·빈 list_item)는 실제 인식이 아니다 — 넓게 걸쳐 있어서
        # 그대로 가리면 그 안에서 놓친 것까지 가려진다 (p20 기본문제 1 실측).
        has_content = bool((ln.get("text") or "").strip()) \
            or ln.get("type") in ("diagram", "chart", "figure", "table")
        if not has_content:
            continue
        r = ln.get("region") or {}
        x, y = r.get("top_left_x"), r.get("top_left_y")
        w, h = r.get("width"), r.get("height")
        if None in (x, y, w, h):
            continue
        dr.rectangle([x - 8, y - 8, x + w + 8, y + h + 8], fill=255)
    # 거친 격자(16px)로 '가려지지 않은 잉크' 셀 찾기
    cell = 16
    dark = im.point(lambda v: 255 if v < 160 else 0)
    hits = []
    for cy in range(0, im.height // cell):
        for cx in range(0, im.width // cell):
            box = (cx * cell, cy * cell, cx * cell + cell, cy * cell + cell)
            if mask.crop(box).getbbox() is not None:
                continue                       # 이미 아는 영역
            region = dark.crop(box)
            n = sum(1 for v in region.getdata() if v)
            if n > cell * cell * 0.06:
                hits.append((cx, cy))
    # 이웃 셀 뭉치기 (간단 BFS)
    hits_set = set(hits)
    groups = []
    while hits_set:
        seed = hits_set.pop()
        blob = [seed]
        queue = [seed]
        while queue:
            x0, y0 = queue.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    p2 = (x0 + dx, y0 + dy)
                    if p2 in hits_set:
                        hits_set.remove(p2)
                        blob.append(p2)
                        queue.append(p2)
        xs = [b[0] for b in blob]; ys = [b[1] for b in blob]
        bx = (min(xs) * cell, min(ys) * cell, (max(xs) + 1) * cell, (max(ys) + 1) * cell)
        area = (bx[2] - bx[0]) * (bx[3] - bx[1])
        if area >= 120 * 120 and len(blob) >= 12:      # 자잘한 얼룩 제외
            groups.append(bx)
    print(f"p{page_no}: 놓친 의심 영역 {len(groups)}곳")
    for gi, bx in enumerate(groups):
        pad = 14
        crop = im.crop((max(0, bx[0] - pad), max(0, bx[1] - pad),
                        min(im.width, bx[2] + pad), min(im.height, bx[3] + pad)))
        out = f"/tmp/gap_p{page_no}_{gi}.png"
        crop.save(out)
        print(f"   {bx} -> {out}")
    return groups

detect(12)
detect(20)
