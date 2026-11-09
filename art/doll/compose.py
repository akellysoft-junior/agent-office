"""레이어 조합 시험: 마네킹 → 하의 → 상의 → 머리, 부위마다 색 바꾸기 (외곽선→칠 선 위 위치 t 유지)."""
import os, itertools, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__)); L = os.path.join(HERE, "layers")
hx = lambda s: np.array([int(s[i:i + 2], 16) for i in (1, 3, 5)], float)
O = hx("#3b1d0b")
BASE = {"hair": "#6f4637", "skin": "#fbd8bd", "shirt": "#f1775f", "inner": "#9bbfe0", "pants": "#57423f",
        "tee": "#d8d4cc", "grey": "#8a8580"}

def recolor(arr, mapping, tol=55):
    """mapping: {기준색: 새색}.
    1) 칠 픽셀(외곽선에서 먼 것)은 가장 가까운 기준색으로 영역을 정함 (색 거리, 픽셀마다 흔들리지 않게 살짝 흐린 색으로)
    2) 외곽선과 섞인 경계 픽셀은 가장 가까운 칠 픽셀의 영역을 따름
    3) 새 색 = 외곽선 + t·(새색 − 외곽선), t = 외곽선→기준색 선 위 위치 (칠은 1로 평평하게)"""
    from scipy import ndimage
    a = arr.astype(float); p = a[..., :3]; on = a[..., 3] > 0
    keys = list(mapping); S = np.array([hx(k) for k in keys])
    blur = np.stack([ndimage.uniform_filter(p[..., i], 5) for i in range(3)], -1)
    d = ((blur[:, :, None, :] - S[None, None]) ** 2).sum(-1)
    cls = d.argmin(-1); dist = np.sqrt(d.min(-1))
    inkish = np.abs(p - O).sum(-1) < 110
    fillpx = on & ~inkish & (dist < tol * 1.6)
    idx = ndimage.distance_transform_edt(~fillpx, return_distances=False, return_indices=True)
    cls = cls[idx[0], idx[1]]
    near = ndimage.distance_transform_edt(~fillpx) < 8
    out = p.copy()
    for i, k in enumerate(keys):
        Sv, Dv = S[i], hx(mapping[k]); dv = Sv - O
        t = np.clip(((p - O) * dv).sum(-1) / (dv * dv).sum(), 0, 1.15)
        m = on & (cls == i) & (fillpx | (near & inkish & (t > 0.15)))
        tt = np.where(fillpx, 1.0, np.minimum(1.0, t))
        out[m] = np.clip(O + tt[m, None] * (Dv - O), 0, 255)
    a[..., :3] = out
    return a.astype(np.uint8)

KEEP = {"#b7b789": "#b7b789", "#fbeee0": "#fbeee0"}            # 머그·신발은 그대로 (가장 가까우면 안 바뀜)
def build(pose, hair, top, bottom, look):
    base = np.array(Image.open(os.path.join(L, f"mannequin_{pose}.png")).convert("RGBA"))
    for kind, part in (("bottom", bottom), ("top", top)):            # 갈아 끼울 부위는 마네킹에서 지움
        if part: base[..., 3] = np.where(np.array(Image.open(os.path.join(L, f"zone_{kind}_{pose}.png"))) > 0, 0, base[..., 3])
    img = Image.fromarray(recolor(base, {BASE["skin"]: look["skin"], BASE["tee"]: look["tee"], BASE["grey"]: look["pants"], **KEEP}))
    maps = {"bottom": {BASE["pants"]: look["pants"], BASE["skin"]: look["skin"], BASE["tee"]: look["tee"], **KEEP},
            "top": {BASE["shirt"]: look["shirt"], BASE["inner"]: look["inner"], BASE["skin"]: look["skin"], BASE["tee"]: look["tee"], BASE["grey"]: look["pants"], **KEEP},
            "hair": {BASE["hair"]: look["hair"], BASE["skin"]: look["skin"]}}
    for kind, part in (("bottom", bottom), ("top", top), ("hair", hair)):
        if not part: continue
        lay = np.array(Image.open(os.path.join(L, f"{part}_{pose}.png")).convert("RGBA"))
        img.alpha_composite(Image.fromarray(recolor(lay, maps[kind], 130)))   # 생성 그림의 잔 얼룩까지 한 색으로
    return img

if __name__ == "__main__":
    HAIRS = ["#2b2522", "#4a3426", "#7a5232", "#a8743e", "#c9a06a"]
    SKINS = ["#f8dcc4", "#f0c7a6", "#dda57f", "#bd8260", "#fbe6d4"]
    SHIRTS = ["#7fb2ea", "#e5534b", "#8fbf9a", "#f0c96b", "#c79bff", "#f08a8a"]
    PANTS = ["#4a5568", "#2f3e5c", "#5b4a3a", "#3d3b40"]
    INNER = ["#ffffff", "#f4ecdc", "#3a3f4b"]
    rnd = random.Random(3)
    combos = list(itertools.product(["hair_short", "hair_long", "hair_ponytail"], ["top_sweater", "top_hoodie", "top_cardigan", None],
                                    ["bottom_pants", "bottom_skirt"]))
    rnd.shuffle(combos); combos = combos[:12]
    tiles = []
    for hair, top, bottom in combos:
        look = dict(hair=rnd.choice(HAIRS), skin=rnd.choice(SKINS), shirt=rnd.choice(SHIRTS), pants=rnd.choice(PANTS),
                    inner=rnd.choice(INNER), tee=rnd.choice(["#ffffff", "#d8d4cc", "#f4ecdc"]))
        pair = [build(p, hair, top, bottom, look) for p in ("stand", "work")]
        t = Image.new("RGBA", (pair[0].width + pair[1].width, pair[0].height), (250, 246, 238, 255))
        t.alpha_composite(pair[0], (0, 0)); t.alpha_composite(pair[1], (pair[0].width - 80, 0))
        bb = t.getbbox(); tiles.append(t.crop((bb[0] + 150, 30, bb[2] - 60, bb[3])).resize((360, 300)))
    sheet = Image.new("RGB", (360 * 4, 300 * 3), (250, 246, 238))
    for i, t in enumerate(tiles): sheet.paste(t.convert("RGB"), ((i % 4) * 360, (i // 4) * 300))
    sheet.save(os.path.join(HERE, "combos.png"))
