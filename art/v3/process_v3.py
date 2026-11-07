"""2자세 한 장(왼쪽 서기, 오른쪽 작업) 생성 그림 → 앱 그림 항목.
- 빛 번짐(아주 옅은 알파) 제거, 두 자세 분리, 같은 배율로 축소 (사람 서기 480px, 고양이 서기 360px 높이)
- 색 바꾸기 지도: 머리1 피부2 겉옷3 바지4 모자5 안쪽옷6 / 고양이 털1 무늬2
- 크기·기준점은 sheet/process.py 와 같은 규칙"""
import os, io, sys, json, base64
import numpy as np
from PIL import Image
from scipy import ndimage
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "sheet"))
REF = os.path.join(HERE, "..", "recolor")
hx = lambda s: np.array([int(s[i:i + 2], 16) for i in (1, 3, 5)], float)

FILES = {  # 번호: (종류, 이름)
  1: ("human", "beanie"), 2: ("human", "bunhood"), 3: ("human", "ponytail"), 4: ("human", "ponyglasses"),
  5: ("human", "longglasses"), 6: ("human", "wavy"), 7: ("human", "short"), 8: ("human", "fringe"), 9: ("human", "curly"),
  10: ("cat", "tux"), 11: ("cat", "patch"), 12: ("cat", "socks"), 14: ("cat", "solid"),
}
H_FILL = {"hair": "#75493c", "skin": "#fcd4b6", "shirt": "#ed775a", "pants": "#664844", "inner": "#93bbdb"}
H_O, H_KEEP = "#381706", ["#bab48b", "#fceade"]
C_FILL = {"fur": "#fce6ce", "patch": "#f09a4a"}
C_O, C_KEEP = "#461e08", ["#f6bb8b"]
IDS = {"hair": 1, "skin": 2, "shirt": 3, "pants": 4, "hat": 5, "inner": 6, "fur": 1, "patch": 2}

def alpha(path): return np.array(Image.open(path).convert("RGBA"))[..., 3] > 40
def head_w(a, f0, f1):
    ys = np.where(a.any(1))[0]; t, b = ys[0], ys[-1]; H = b - t; ws = []
    for y in range(int(t + f0 * H), int(t + f1 * H)):
        xs = np.where(a[y])[0]
        if len(xs): ws.append(xs[-1] - xs[0])
    return max(ws)
def head_cx(a, f0, f1):
    ys = np.where(a.any(1))[0]; t, b = ys[0], ys[-1]; H = b - t
    xs = np.where(a[int(t + f0 * H):int(t + f1 * H)].any(0))[0]; return (xs[0] + xs[-1]) / 2
ra = alpha(os.path.join(REF, "human.png")); HW_UNITS = head_w(ra, 0.15, 0.30) / (ra.shape[0] / 28)
ca = alpha(os.path.join(REF, "cat.png")); CW_UNITS = head_w(ca, 0.18, 0.36) / (ca.shape[0] / 20)

def split(path):
    im = np.array(Image.open(path).convert("RGBA"))
    im[..., 3] = np.where(im[..., 3] < 40, 0, im[..., 3])
    m = im[..., 3] > 128; lab, n = ndimage.label(m)
    sz = ndimage.sum(m, lab, range(1, n + 1)); top2 = np.argsort(-sz)[:2] + 1
    out = []
    for lid in top2:
        own = ndimage.binary_dilation(lab == lid, iterations=3) & ~((lab > 0) & (lab != lid))
        a = im.copy(); a[..., 3] = np.where(own, a[..., 3], 0)
        ys, xs = np.where(a[..., 3] > 0); pad = 8
        out.append((xs.min(), a[max(0, ys.min() - pad): ys.max() + pad + 1, max(0, xs.min() - pad): xs.max() + pad + 1]))
    out.sort(key=lambda t: t[0])
    return out[0][1], out[1][1]

def region_map(im, O, fills, keep, human):
    p = im[..., :3].astype(float); al = im[..., 3]; H, W = al.shape
    O = hx(O); names = list(fills)
    best_res = np.full((H, W), 1e9); best_id = np.zeros((H, W), int); best_t = np.zeros((H, W))
    for n in names:
        d = hx(fills[n]) - O; L2 = (d * d).sum(); t = ((p - O) * d).sum(-1) / L2
        res = np.sqrt(((p - (O + t[..., None] * d)) ** 2).sum(-1)) + np.maximum(0, t - 1.15) * 200
        b = res < best_res; best_res[b] = res[b]; best_id[b] = IDS[n]; best_t[b] = t[b]
    for k in keep:
        kd = hx(k) - O; L2 = (kd * kd).sum(); t = ((p - O) * kd).sum(-1) / L2
        res = np.sqrt(((p - (O + t[..., None] * kd)) ** 2).sum(-1))
        best_id[(res < best_res) & (t > 0.5)] = 0
    best_id[(best_res > 40) | (best_t < 0.18) | (al < 8)] = 0
    if human:
        ys = np.where(al > 40)[0]; top, bot = ys.min(), ys.max(); hh = bot - top
        brown = (best_id == 1) | (best_id == 4); lab, n = ndimage.label(brown)
        for i in range(1, n + 1):
            yy = np.where(lab == i)[0]
            legs = (yy.mean() - top) / hh >= 0.5 and (yy.max() - top) / hh >= 0.75
            best_id[lab == i] = 4 if legs else 1
        sh = best_id == 3; lab, n = ndimage.label(sh)
        for i in range(1, n + 1):
            yy = np.where(lab == i)[0]
            if (yy.mean() - top) / hh < 0.22: best_id[lab == i] = 5
    m = np.zeros((H, W, 4), np.uint8); m[..., 0] = best_id; m[..., 1] = np.clip(best_t * 200, 0, 255); m[..., 3] = 255
    return m, best_id

# 생성 그림은 모두 같은 캔버스·같은 크기로 그려졌으므로, 종류별로 기준 그림 하나에서 배율과 px/단위를 정해 모두에 똑같이 씀
# (머리 폭은 머리 모양마다 달라서 그림마다 재면 크기가 들쭉날쭉해짐)
REFNUM = {"human": 3, "cat": 11}
SCALE, PPU = {}, {}
for who, num in REFNUM.items():
    st, _ = split(os.path.join(HERE, "src", f"{num:02d}.png"))
    SCALE[who] = (480 if who == "human" else 360) / st.shape[0]
    img = Image.fromarray(st); img = img.resize((round(img.width * SCALE[who]), round(img.height * SCALE[who])), Image.LANCZOS)
    a = np.array(img)[..., 3] > 40
    PPU[who] = head_w(a, 0.15, 0.30) / HW_UNITS if who == "human" else head_w(a, 0.18, 0.36) / CW_UNITS
print("scale", SCALE, "ppu", PPU)
entries, vis = {}, []
for num, (who, var) in FILES.items():
    stand, work = split(os.path.join(HERE, "src", f"{num:02d}.png"))
    s = SCALE[who]
    for pose, arr in (("stand", stand), ("work", work)):
        img = Image.fromarray(arr); img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
        im = np.array(img); a = im[..., 3] > 40; H, W = a.shape
        kind = who if pose == "stand" else who + "Work"
        ppu = PPU[who]   # 서기·작업 같은 배율 (작업 고양이를 줄이면 서 있는 고양이보다 작아 보임)
        m, ids = region_map(im, H_O if who == "human" else C_O, H_FILL if who == "human" else C_FILL,
                            H_KEEP if who == "human" else C_KEEP, who == "human")
        ys, xs = np.where(a); top, bot = ys.min(), ys.max(); x0, x1 = xs.min(), xs.max(); bw = x1 - x0
        if pose == "stand":
            fy = np.where(a[bot - max(2, (bot - top) // 30):bot + 1].any(0))[0]; sx, sy = (fy[0] + fy[-1]) / 2, bot
        elif who == "human":
            pys, pxs = np.where(ids == 4); p0, p1 = pxs.min(), pxs.max(); pw = p1 - p0
            cols = range(int(p0 + 0.08 * pw), int(p0 + 0.30 * pw))
            sx = (cols.start + cols.stop) / 2; sy = float(np.median([np.where(a[:, c])[0].max() for c in cols]))
        else:
            cols = range(int(x0 + 0.45 * bw), int(x0 + 0.65 * bw))
            sx = (cols.start + cols.stop) / 2; sy = max(np.where(a[:, c])[0].max() for c in cols) - 1 * ppu
        hcx = head_cx(a, 0.15, 0.30) if who == "human" else head_cx(a, 0.18, 0.36)
        b1 = io.BytesIO(); Image.fromarray(im).save(b1, "WEBP", quality=90, method=6)
        b2 = io.BytesIO(); Image.fromarray(m).save(b2, "PNG", optimize=True)
        Image.fromarray(im).save(os.path.join(HERE, f"{who}_{var}_{pose}.png"))
        entries[f"{kind}.{var}"] = dict(units=round(H / ppu, 3), ax=round(sx / W, 4), ay=round(sy / H, 4), hx=round(hcx / W, 3),
            O=H_O if who == "human" else C_O, map="data:image/png;base64," + base64.b64encode(b2.getvalue()).decode(),
            src="data:image/webp;base64," + base64.b64encode(b1.getvalue()).decode())
        v = np.zeros((H, W, 3), np.uint8) + 255
        for rid, c in {1: (220, 60, 60), 2: (60, 160, 60), 3: (60, 90, 220), 4: (200, 160, 30), 5: (150, 60, 200), 6: (0, 200, 200)}.items(): v[ids == rid] = c
        v[(ids == 0) & a] = (40, 40, 40); vis.append(Image.fromarray(v))
json.dump(entries, open(os.path.join(HERE, "entries.json"), "w"))
print(len(entries), "entries, KB", sum(len(e["src"]) + len(e["map"]) for e in entries.values()) // 1024)
for k, e in entries.items(): print(k, e["units"], e["ax"], e["ay"], e["hx"])
Hs = 240; vis = [i.resize((int(i.width * Hs / i.height), Hs)) for i in vis]
s = Image.new("RGB", (sum(i.width + 6 for i in vis), Hs), "white"); x = 0
for i in vis: s.paste(i, (x, 0)); x += i.width + 6
s.save(os.path.join(HERE, "regions.png"))
