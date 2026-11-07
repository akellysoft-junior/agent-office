"""생성 이미지(사람·고양이 작업 자세)를 앱 그림으로 준비.
- 타자 효과선(작은 조각) 제거, 여백 자르기, 600px 높이 WebP
- 앵커: 엉덩이 접점(seat), 손/앞발, 머리 가운데 x
- 크기: 기본 자세 그림과 머리 폭이 같도록 (px/단위)"""
import sys, json, base64, io, os
import numpy as np
from PIL import Image
from scipy import ndimage
HERE = os.path.dirname(os.path.abspath(__file__))
P = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

def clean(path):
    im = np.array(Image.open(path).convert("RGBA"))
    m = im[..., 3] > 40
    lab, n = ndimage.label(m); sz = ndimage.sum(m, lab, range(1, n + 1))
    main = lab == (int(np.argmax(sz)) + 1)
    keep = ndimage.binary_dilation(main, iterations=4)
    im[..., 3] = np.where(keep, im[..., 3], 0)
    return im

def head_width(a, top, frac0, frac1, H):
    ws = []
    for y in range(int(top + frac0 * H), int(top + frac1 * H)):
        xs = np.where(a[y])[0]
        if len(xs): ws.append(xs[-1] - xs[0])
    return max(ws)

# 기본 자세 기준 (px/단위 와 머리 폭)
IDLE = {"human": ("../charpkg/img0.png", 28), "cat": ("../charpkg/img1.png", 20)}
CFG = {
  # name: (src, head rows (비율 범위), seat 찾기 x 범위, 손 목록)
  "human": dict(src="human_src.png", head=(0.15, 0.30), seat_x=(300, 420), hands=[(712, 590), (848, 636)], head_cx=470),
  "cat":   dict(src="cat_src.png",   head=(0.18, 0.36), seat_x=(520, 700), hands=[(850, 700), (948, 770)], head_cx=560),
}
out = {}
for name, c in CFG.items():
    ip, units = IDLE[name]
    ia = np.array(Image.open(os.path.join(HERE, ip)).convert("RGBA"))[..., 3] > 40
    iy = np.where(ia.any(1))[0]; iH = iy[-1] - iy[0]; ippu = iH / units
    ihw = head_width(ia, iy[0], *c["head"], iH) if name == "cat" else head_width(ia, iy[0], 0.15, 0.30, iH)
    im = clean(os.path.join(HERE, c["src"])); a = im[..., 3] > 40
    ys, xs = np.where(a); top, bot = ys.min(), ys.max(); H = bot - top
    hw = head_width(a, top, *c["head"], H)
    ppu = hw / (ihw / ippu) * P.get(name + "_scale", 1.0)
    # 엉덩이 접점: seat_x 범위 열들의 가장 아래 불투명 픽셀 중 가장 낮은 곳 (사람은 허벅지 아래 = 엉덩이 바닥)
    x0, x1 = c["seat_x"]
    if name == "human":
        # 엉덩이 열에서 바지가 끝나는 곳(아래로 쭉 투명해지는 첫 지점)
        bottoms = [np.where(a[:, x])[0].max() for x in range(x0, x1)]
        sy = int(np.median(bottoms)); sx = (x0 + x1) // 2
    else:
        bottoms = [np.where(a[:, x])[0].max() for x in range(x0, x1)]
        sy = int(max(bottoms)) - 6; sx = (x0 + x1) // 2
    sx += P.get(name + "_sx", 0); sy += P.get(name + "_sy", 0)
    # 자르기
    pad = 6
    bx0, by0, bx1, by1 = xs.min() - pad, top - pad, xs.max() + pad, bot + pad
    crop = Image.fromarray(im).crop((bx0, by0, bx1, by1))
    cw, ch = crop.size
    scale = 600 / ch
    small = crop.resize((round(cw * scale), 600), Image.LANCZOS)
    buf = io.BytesIO(); small.save(buf, "WEBP", quality=90, method=6)
    small.save(os.path.join(HERE, f"{name}_work.webp"), "WEBP", quality=90, method=6)
    hands = [((hx - sx) / ppu, (hy - sy) / ppu) for hx, hy in c["hands"]]
    out[name] = dict(units=round(ch / ppu, 3), ax=round((sx - bx0) / cw, 4), ay=round((sy - by0) / ch, 4),
                     hx=round((c["head_cx"] - bx0) / cw, 3), src="data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode())
    print(name, "ppu", round(ppu, 2), "idle ppu", round(ippu, 2), "head", hw, "idle head", ihw, "seat", (sx, sy),
          "units", out[name]["units"], "hands(k=1)", [(round(u, 2), round(v, 2)) for u, v in hands], "webp KB", len(buf.getvalue()) // 1024)
json.dump(out, open(os.path.join(HERE, "work_art.json"), "w"))
