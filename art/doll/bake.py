"""조합 도구용 데이터 굽기: 레이어마다 (그림 WebP, 영역 지도 PNG[R=영역, G=t×200]), 지울 영역(zone), 캐릭터 영역으로 자르고 절반 크기."""
import os, io, json, base64
import numpy as np
from PIL import Image
from scipy import ndimage
HERE = os.path.dirname(os.path.abspath(__file__)); L = os.path.join(HERE, "layers")
hx = lambda s: np.array([int(s[i:i + 2], 16) for i in (1, 3, 5)], float)
O = hx("#3b1d0b")
REG = {"hair": ("#6f4637", 1), "skin": ("#fbd8bd", 2), "shirt": ("#f1775f", 3), "inner": ("#9bbfe0", 4),
       "pants": ("#57423f", 5), "tee": ("#d8d4cc", 6), "grey": ("#8a8580", 5), "mug": ("#b7b789", 0), "shoe": ("#fbeee0", 0)}
KEYS = {"mannequin": ["skin", "tee", "grey", "mug", "shoe"], "bottom": ["pants", "skin", "tee", "mug", "shoe"],
        "top": ["shirt", "inner", "skin", "tee", "grey", "mug", "shoe"], "hair": ["hair", "skin"]}

def region_map(arr, keys, tol=88):
    a = arr.astype(float); p = a[..., :3]; on = a[..., 3] > 0
    S = np.array([hx(REG[k][0]) for k in keys])
    blur = np.stack([ndimage.uniform_filter(p[..., i], 5) for i in range(3)], -1)
    d = ((blur[:, :, None, :] - S[None, None]) ** 2).sum(-1)
    cls = d.argmin(-1); dist = np.sqrt(d.min(-1))
    inkish = np.abs(p - O).sum(-1) < 110
    fillpx = on & ~inkish & (dist < tol)
    idx = ndimage.distance_transform_edt(~fillpx, return_distances=False, return_indices=True)
    cls = cls[idx[0], idx[1]]
    near = ndimage.distance_transform_edt(~fillpx) < 8
    R = np.zeros(p.shape[:2], np.uint8); G = np.zeros(p.shape[:2], np.uint8)
    for i, k in enumerate(keys):
        dv = S[i] - O; t = np.clip(((p - O) * dv).sum(-1) / (dv * dv).sum(), 0, 1.15)
        m = on & (cls == i) & (fillpx | (near & inkish & (t > 0.15)))
        R[m] = REG[k][1]; G[m] = np.where(fillpx[m], 200, np.clip(t[m] * 200, 0, 255)).astype(np.uint8)
    return np.dstack([R, G, np.zeros_like(R), np.full_like(R, 255)])

def b64(img, fmt):
    buf = io.BytesIO(); img.save(buf, fmt, **({"quality": 92, "method": 6} if fmt == "WEBP" else {"optimize": True}))
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()

out = {}
for pose in ("stand", "work"):
    man = np.array(Image.open(os.path.join(L, f"mannequin_{pose}.png")).convert("RGBA"))
    allA = man[..., 3] > 0                                    # 모든 레이어를 합친 범위로 자름 (긴 머리가 잘리지 않게)
    for n in ["hair_short", "hair_long", "hair_ponytail", "top_sweater", "top_hoodie", "top_cardigan", "bottom_pants", "bottom_skirt"]:
        allA |= np.array(Image.open(os.path.join(L, f"{n}_{pose}.png")).convert("RGBA"))[..., 3] > 0
    ys, xs = np.where(allA)
    box = (max(0, int(xs.min()) - 12), max(0, int(ys.min()) - 12), min(man.shape[1], int(xs.max()) + 12), min(man.shape[0], int(ys.max()) + 12))
    def prep(arr, keys):
        im = Image.fromarray(arr).crop(box); mp = Image.fromarray(region_map(arr, keys)).crop(box)
        w, h = im.size; im = im.resize((w // 2, h // 2), Image.LANCZOS); mp = mp.resize((w // 2, h // 2), Image.NEAREST)
        return {"src": b64(im, "WEBP"), "map": b64(mp, "PNG")}
    P = {"mannequin": prep(man, KEYS["mannequin"]), "w": int(box[2] - box[0]) // 2, "h": int(box[3] - box[1]) // 2}
    for kind in ("bottom", "top"):
        z = Image.open(os.path.join(L, f"zone_{kind}_{pose}.png")).crop(box)
        P["zone_" + kind] = b64(z.resize((z.width // 2, z.height // 2), Image.NEAREST), "PNG")
    for n in ["hair_short", "hair_long", "hair_ponytail", "top_sweater", "top_hoodie", "top_cardigan", "bottom_pants", "bottom_skirt"]:
        arr = np.array(Image.open(os.path.join(L, f"{n}_{pose}.png")).convert("RGBA"))
        P[n] = prep(arr, KEYS[n.split("_")[0]])
    out[pose] = P
json.dump(out, open(os.path.join(HERE, "doll_data.json"), "w"))
print("KB", os.path.getsize(os.path.join(HERE, "doll_data.json")) // 1024)
