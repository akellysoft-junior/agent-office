"""낱장 → 앱 그림 항목 (WebP + 색 바꾸기 지도 + 기준점·크기).
크기: 지금 앱의 기본 자세 그림과 머리 폭이 같도록 (고양이 작업 자세는 키보드에 맞게 1/1.2, 1단위 내려앉힘 — 이전과 같은 규칙)."""
import os, io, json, base64, glob
import numpy as np
from PIL import Image
from scipy import ndimage
HERE = os.path.dirname(os.path.abspath(__file__)); SP = os.path.join(HERE, "sprites")
REF = os.path.join(HERE, "..", "recolor")
hx = lambda s: np.array([int(s[i:i + 2], 16) for i in (1, 3, 5)], float)

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

# 기준: 앱의 지금 기본 자세 (사람 28단위, 고양이 20단위)
ra = alpha(os.path.join(REF, "human.png")); r_ppu = ra.shape[0] / 28
HW_UNITS = head_w(ra, 0.15, 0.30) / r_ppu
ca = alpha(os.path.join(REF, "cat.png")); c_ppu = ca.shape[0] / 20
CW_UNITS = head_w(ca, 0.18, 0.36) / c_ppu
PPU = {
  "human": head_w(alpha(os.path.join(SP, "human_bob_stand.png")), 0.15, 0.30) / HW_UNITS,
  "humanWork": head_w(alpha(os.path.join(SP, "human_bob_work.png")), 0.12, 0.27) / HW_UNITS,
  "cat": head_w(alpha(os.path.join(SP, "cat_patch_stand.png")), 0.18, 0.36) / CW_UNITS,
  "catWork": head_w(alpha(os.path.join(SP, "cat_patch_work.png")), 0.14, 0.32) / CW_UNITS * 1.2,
}
print("ppu", {k: round(v, 2) for k, v in PPU.items()})

H_FILL = {"hair": "#7c4e42", "skin": "#f9d0b5", "shirt": "#ef7b5e", "pants": "#684b47"}
H_O, H_KEEP = "#3b1f0e", ["#bcaf8a", "#fbe9d7"]
C_FILL = {"fur": "#fbe3cb", "patch": "#f59e57"}
C_O, C_KEEP = "#3c200e", ["#edbd94"]
IDS = {"hair": 1, "skin": 2, "shirt": 3, "pants": 4, "hat": 5, "fur": 1, "patch": 2}

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
    best_id[(best_res > 45) | (best_t < 0.18) | (al < 8)] = 0
    if human:
        ys = np.where(al > 40)[0]; top, bot = ys.min(), ys.max(); hh = bot - top
        # 갈색 덩어리: 위쪽(가운데가 몸 위 55% 안)이면 머리, 아래면 바지
        brown = (best_id == 1) | (best_id == 4)
        lab, n = ndimage.label(brown)
        for i in range(1, n + 1):
            yy = np.where(lab == i)[0]
            legs = (yy.mean() - top) / hh >= 0.5 and (yy.max() - top) / hh >= 0.75   # 바지는 다리 아래까지 내려감
            best_id[lab == i] = 4 if legs else 1
        # 상의 색 덩어리가 머리 위쪽에 있으면 모자
        sh = best_id == 3; lab, n = ndimage.label(sh)
        for i in range(1, n + 1):
            yy = np.where(lab == i)[0]
            if (yy.mean() - top) / hh < 0.22: best_id[lab == i] = 5
    m = np.zeros((H, W, 4), np.uint8); m[..., 0] = best_id; m[..., 1] = np.clip(best_t * 200, 0, 255); m[..., 3] = 255
    return m, best_id

entries, vis = {}, []
for path in sorted(glob.glob(os.path.join(SP, "*.png"))):
    name = os.path.basename(path)[:-4]                 # human_bob_stand
    who, var, pose = name.split("_")
    kind = (who if pose == "stand" else who + "Work")
    im = np.array(Image.open(path).convert("RGBA")); a = im[..., 3] > 40; H, W = a.shape
    ys, xs = np.where(a); top, bot = ys.min(), ys.max(); x0, x1 = xs.min(), xs.max(); bw = x1 - x0
    ppu = PPU[kind]
    if pose == "stand":
        fy = np.where(a[bot - max(2, (bot - top) // 30):bot + 1].any(0))[0]
        sx, sy = (fy[0] + fy[-1]) / 2, bot
    elif who == "human":
        sx = sy = None                                  # 아래에서 바지 영역으로 정함 (긴 머리가 엉덩이 쪽 열을 가려서)
    else:
        cols = range(int(x0 + 0.45 * bw), int(x0 + 0.65 * bw))
        sx = (cols.start + cols.stop) / 2; sy = max(np.where(a[:, c])[0].max() for c in cols) - 1 * ppu
    f0, f1 = (0.15, 0.30) if who == "human" else (0.18, 0.36)
    hcx = head_cx(a, f0, f1)
    m, ids = region_map(im, H_O if who == "human" else C_O, H_FILL if who == "human" else C_FILL,
                        H_KEEP if who == "human" else C_KEEP, who == "human")
    if sx is None:                                      # 사람 작업: 바지 왼쪽(엉덩이) 열들의 맨 아래
        pys, pxs = np.where(ids == 4); p0, p1 = pxs.min(), pxs.max(); pw = p1 - p0
        cols = range(int(p0 + 0.08 * pw), int(p0 + 0.30 * pw))
        sx = (cols.start + cols.stop) / 2; sy = float(np.median([np.where(a[:, c])[0].max() for c in cols]))
    b1 = io.BytesIO(); Image.fromarray(im).save(b1, "WEBP", quality=92, method=6)
    b2 = io.BytesIO(); Image.fromarray(m).save(b2, "PNG", optimize=True)
    key = f"{kind}.{var}"
    entries[key] = dict(units=round(H / ppu, 3), ax=round(sx / W, 4), ay=round(sy / H, 4), hx=round(hcx / W, 3),
                        O=H_O if who == "human" else C_O,
                        map="data:image/png;base64," + base64.b64encode(b2.getvalue()).decode(),
                        src="data:image/webp;base64," + base64.b64encode(b1.getvalue()).decode())
    v = np.zeros((H, W, 3), np.uint8) + 255
    for rid, c in {1: (220, 60, 60), 2: (60, 160, 60), 3: (60, 90, 220), 4: (200, 160, 30), 5: (150, 60, 200)}.items(): v[ids == rid] = c
    v[(ids == 0) & a] = (40, 40, 40); vis.append(Image.fromarray(v))
json.dump(entries, open(os.path.join(HERE, "entries.json"), "w"))
print(len(entries), "entries; total KB", sum(len(e["src"]) + len(e["map"]) for e in entries.values()) // 1024)
for k, e in entries.items(): print(k, e["units"], e["ax"], e["ay"], e["hx"])
Hs = 260; vis = [i.resize((int(i.width * Hs / i.height), Hs)) for i in vis]
s = Image.new("RGB", (sum(i.width + 6 for i in vis), Hs), "white"); x = 0
for i in vis: s.paste(i, (x, 0)); x += i.width + 6
s.save(os.path.join(HERE, "regions.png"))
