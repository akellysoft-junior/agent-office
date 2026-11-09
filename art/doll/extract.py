"""마네킹 기준 차이 추출 → 부위 레이어.
1) 배경 정리: 가짜 체크무늬(불투명) 배경은 가장자리에서 밝은 무채색만 채워 지움, 빛 번짐(옅은 알파)은 제거
2) 정렬: 서기/작업 반쪽마다, 바뀌지 않는 부위(머리 그림은 다리, 옷 그림은 머리)의 외곽선이 마네킹과 겹치도록 ±20px 이동
3) 추출: 마네킹과 색이 달라진 픽셀(+ 외곽선 두께만큼 넓힘) = 그 부위 레이어
결과: layers/<name>_<stand|work>.png (마네킹과 같은 좌표), mannequin_<pose>.png"""
import os, json
import numpy as np
from PIL import Image
from scipy import ndimage
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(HERE, "src"); OUT = os.path.join(HERE, "layers")
os.makedirs(OUT, exist_ok=True)
NAMES = ["hair_short", "hair_long", "hair_ponytail", "top_sweater", "top_hoodie", "top_cardigan", "bottom_pants", "bottom_skirt"]

def load(n):
    a = np.array(Image.open(os.path.join(SRC, n + ".png")).convert("RGBA")).astype(np.int16)
    if (a[..., 3] < 10).mean() < 0.05:                       # 불투명 배경 → 가장자리에서 채우기
        rgb = a[..., :3]; light = (rgb.min(-1) > 225) & (rgb.max(-1) - rgb.min(-1) < 14)
        lab, _ = ndimage.label(light)
        edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
        bg = np.isin(lab, list(edge))
        bg = ndimage.binary_dilation(bg, iterations=1) & (rgb.min(-1) > 200)
        a[..., 3] = np.where(bg, 0, 255)
    a[..., 3] = np.where(a[..., 3] < 60, 0, a[..., 3])          # 빛 번짐 제거
    return a

OUTLINE = np.array([59, 29, 11])
def ink(a): return (a[..., 3] > 128) & (np.abs(a[..., :3] - OUTLINE).sum(-1) < 70)   # 외곽선(진한 갈색 #3b1d0b 근처)

M = load("mannequin"); H, W = M.shape[:2]; HALF = W // 2
mink = ink(M)
def body_rows(a, half):
    ys = np.where((a[:, half * HALF:(half + 1) * HALF, 3] > 128).any(1))[0]; return ys.min(), ys.max()

def best_shift(img, half, region):
    t0, t1 = body_rows(M, half); hgt = t1 - t0
    r0, r1 = (t0, int(t0 + 0.32 * hgt)) if region == "head" else (int(t0 + 0.62 * hgt), t1)
    x0, x1 = half * HALF, (half + 1) * HALF
    ref = mink[r0:r1, x0:x1]; cur = ink(img)
    best = (-1, 0, 0)
    for dy in range(-20, 21):
        for dx in range(-20, 21):
            ys0, ys1 = r0 + dy, r1 + dy
            if ys0 < 0 or ys1 > H: continue
            c = cur[ys0:ys1, max(0, x0 + dx):x1 + dx]
            if c.shape != ref.shape: continue
            sc = (c & ref).sum()
            if sc > best[0]: best = (sc, dx, dy)
    return best[1], best[2], best[0] / max(1, ref.sum())

report = {}
for half, pose in ((0, "stand"), (1, "work")):
    x0, x1 = half * HALF, (half + 1) * HALF
    Image.fromarray(M[:, x0:x1].astype(np.uint8)).save(os.path.join(OUT, f"mannequin_{pose}.png"))
for n in NAMES:
    A = load(n)
    for half, pose in ((0, "stand"), (1, "work")):
        x0, x1 = half * HALF, (half + 1) * HALF
        dx, dy, fit = best_shift(A, half, "legs" if n.startswith("hair") else "head")
        S = np.zeros_like(A); S[:] = 0
        sy0, sy1 = max(0, dy), min(H, H + dy); ty0 = sy0 - dy
        sx0, sx1 = max(0, dx), min(W, W + dx); tx0 = sx0 - dx
        S[ty0:ty0 + (sy1 - sy0), tx0:tx0 + (sx1 - sx0)] = A[sy0:sy1, sx0:sx1]
        S = S[:, x0:x1]; m = M[:, x0:x1]
        a_on, m_on = S[..., 3] > 128, m[..., 3] > 128
        diff = np.abs(S[..., :3] - m[..., :3]).sum(-1)
        changed = a_on & ((~m_on) | (diff > 60)) & ~ink(S)      # 바뀐 '칠' 만 (외곽선만 조금 달라진 건 무시)
        changed = ndimage.binary_opening(changed, iterations=4)          # 정렬 오차로 생긴 가는 띠 제거
        lab, k = ndimage.label(changed); sz = ndimage.sum(changed, lab, range(1, k + 1))
        changed = np.isin(lab, [i + 1 for i, s in enumerate(sz) if s > 900])
        layer_mask = ndimage.binary_dilation(changed, iterations=11) & a_on   # 외곽선까지
        # 옷은 마네킹의 그 부위(티/바지 영역)를 통째로 갈아 끼움: 영역 안은 편집 그림 그대로 가져오고, 조합할 때 마네킹 쪽은 지움
        fill = lambda img, c: (img[..., 3] > 128) & (np.abs(img[..., :3] - np.array(c)).sum(-1) < 40)
        if n.startswith("bottom"):
            zone = ndimage.binary_dilation(fill(m, (138, 133, 128)), iterations=15)
            layer_mask = (layer_mask | zone) & a_on
            Image.fromarray((zone * 255).astype(np.uint8)).save(os.path.join(OUT, f"zone_bottom_{pose}.png"))
        if n.startswith("top"):
            zone = ndimage.binary_dilation(fill(m, (216, 212, 204)), iterations=8)
            layer_mask = (layer_mask | (zone & ~fill(S, (138, 133, 128)))) & a_on
            Image.fromarray((zone * 255).astype(np.uint8)).save(os.path.join(OUT, f"zone_top_{pose}.png"))
        if n.startswith("hair"):                                            # 머리 레이어에 섞인 티 색 조각 제거
            layer_mask &= ~fill(S, (216, 212, 204))
        L = S.copy(); L[..., 3] = np.where(layer_mask, S[..., 3], 0)
        Image.fromarray(L.astype(np.uint8)).save(os.path.join(OUT, f"{n}_{pose}.png"))
        report[f"{n}_{pose}"] = {"shift": [dx, dy], "fit": round(fit, 3), "px": int(layer_mask.sum())}
json.dump(report, open(os.path.join(OUT, "report.json"), "w"), indent=1)
for k, v in report.items(): print(k, v)
