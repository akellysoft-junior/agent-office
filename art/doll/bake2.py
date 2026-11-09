"""조합실 v2: 그림을 '영역 지도'로 바꿔서 굽는다. 외곽선은 조합한 뒤에 새로 그림.
- 레이어마다: R = 영역(0 투명, 1 머리, 2 피부, 3 겉옷, 4 안쪽 옷, 5 바지, 6 기본 티, 7 신발, 8 머그, 9 장식(끈·단추)),
             G = 255 이면 '안쪽 선'(눈·입·주름·단추 테두리처럼 같은 영역 안에 그려진 선)
- 영역 경계·실루엣의 외곽선은 굽지 않음 → 조합 후 한 번에 같은 굵기로 그려서 선이 겹치지 않음
- 생성 그림의 거친 가장자리는 다수결 필터로 다듬음"""
import os, io, json, base64
import numpy as np
from PIL import Image
from scipy import ndimage
HERE = os.path.dirname(os.path.abspath(__file__)); L = os.path.join(HERE, "layers")
hx = lambda s: np.array([int(s[i:i + 2], 16) for i in (1, 3, 5)], float)
O = hx("#3b1d0b")
COL = {"hair": ("#6f4637", 1), "skin": ("#fbd8bd", 2), "shirt": ("#f1775f", 3), "inner": ("#9bbfe0", 4), "pants": ("#57423f", 5),
       "tee": ("#d8d4cc", 6), "grey": ("#8a8580", 5), "shoe": ("#fbeee0", 7), "mug": ("#b7b789", 8)}
KEYS = {"mannequin": ["skin", "tee", "grey", "mug", "shoe"], "bottom": ["pants", "skin", "tee", "grey", "mug", "shoe"],
        "top": ["shirt", "inner", "skin", "tee", "grey", "mug", "shoe"], "hair": ["hair", "skin"]}
DISK = lambda r: (np.add.outer(np.arange(-r, r + 1) ** 2, np.arange(-r, r + 1) ** 2) <= r * r)

def labels(arr, keys, kind):
    a = arr.astype(float); p = a[..., :3]
    on = ndimage.binary_opening(ndimage.binary_closing(a[..., 3] > 0, DISK(2)), DISK(2))
    on = ndimage.gaussian_filter(on.astype(float), 2.5) > 0.5                        # 실루엣 다듬기
    S = np.array([hx(COL[k][0]) for k in keys]); ids = np.array([COL[k][1] for k in keys])
    d = ((p[:, :, None, :] - S[None, None]) ** 2).sum(-1)
    near = d.argmin(-1); dist = np.sqrt(d.min(-1))
    ink = (np.abs(p - O).sum(-1) < 80) & (a[..., 3] > 0)
    fill = on & ~ink
    lab, n = ndimage.label(fill)
    cls = np.full(p.shape[:2], -1)
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None: continue
        m = lab[sl] == i
        if m.sum() < 25: continue                                              # 잔 얼룩은 이웃을 따름
        votes = near[sl][m][dist[sl][m] < 110]
        if votes.size: cls[sl][m] = np.bincount(votes, minlength=len(keys)).argmax()
    # 작은 밝은 덩어리(끈·단추)는 장식(9) — 상의만
    if kind == "top":
        si = keys.index("shoe")
        for i, sl in enumerate(ndimage.find_objects(lab), 1):
            if sl is None: continue
            m = lab[sl] == i
            if 25 <= m.sum() < 1500 and (cls[sl][m] == si).all(): cls[sl][m] = 99
    known = cls >= 0
    idx = ndimage.distance_transform_edt(~known, return_distances=False, return_indices=True)
    cls = cls[idx[0], idx[1]]
    R = np.zeros(p.shape[:2], np.uint8)
    for j, i_ in enumerate(ids): R[cls == j] = i_
    R[cls == 99] = 9
    # 다수결 필터: 영역 경계의 지그재그를 부드럽게
    present = [v for v in np.unique(R) if v]
    cnt = np.stack([ndimage.uniform_filter((R == v).astype(float), 13) for v in present], -1)
    R = np.where(on, np.array(present)[cnt.argmax(-1)], 0).astype(np.uint8)
    # 작은 섬(얼룩) 없애기: 작은 조각은 둘러싼 영역을 따름 → 조각마다 외곽선이 생기던 문제
    bad = np.zeros_like(on)
    for v in present:
        lb, k = ndimage.label(R == v); sz = ndimage.sum(R == v, lb, range(1, k + 1))
        bad |= np.isin(lb, [i + 1 for i, s_ in enumerate(sz) if s_ < 700])
    good = on & ~bad
    idx = ndimage.distance_transform_edt(~good, return_distances=False, return_indices=True)
    R = np.where(on, R[idx[0], idx[1]], 0).astype(np.uint8)
    # 안쪽 선: 같은 영역 안에 있는 선 (영역 경계·실루엣 근처 선은 버림 → 나중에 새로 그림)
    edge = np.zeros_like(on)
    for v in present + [0]:
        m = R == v
        edge |= ndimage.binary_dilation(m, DISK(1)) & ~m
    nearedge = ndimage.binary_dilation(edge, DISK(9))
    det = ink & on & ~nearedge
    det = ndimage.binary_opening(det, DISK(1))
    lab2, n2 = ndimage.label(det); sz = ndimage.sum(det, lab2, range(1, n2 + 1))
    det = np.isin(lab2, [i + 1 for i, s in enumerate(sz) if s >= 60])
    det = ndimage.gaussian_filter(det.astype(float), 1.0) > 0.45                   # 선 가장자리 다듬기
    return np.dstack([R, np.where(det & on, 255, 0).astype(np.uint8), np.zeros_like(R), np.full_like(R, 255)])

def b64png(img):
    buf = io.BytesIO(); img.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

NAMES = ["hair_short", "hair_long", "hair_ponytail", "top_sweater", "top_hoodie", "top_cardigan", "bottom_pants", "bottom_skirt"]
out = {}
for pose in ("stand", "work"):
    man = np.array(Image.open(os.path.join(L, f"mannequin_{pose}.png")).convert("RGBA"))
    allA = man[..., 3] > 0
    for n in NAMES: allA |= np.array(Image.open(os.path.join(L, f"{n}_{pose}.png")).convert("RGBA"))[..., 3] > 0
    ys, xs = np.where(allA)
    box = (max(0, int(xs.min()) - 16), max(0, int(ys.min()) - 16), min(man.shape[1], int(xs.max()) + 16), min(man.shape[0], int(ys.max()) + 16))
    ML = labels(man, KEYS["mannequin"], "mannequin")
    P = {"w": box[2] - box[0], "h": box[3] - box[1], "mannequin": b64png(Image.fromarray(ML).crop(box))}
    # 갈아 끼울 영역은 마네킹 영역 지도에서 (바지 = 5, 기본 티 = 6) — 색으로 찾으면 그림자 낀 티까지 잡힘
    for kind, v, r in (("bottom", 5, 15), ("top", 6, 9)):
        z = ndimage.binary_dilation(ML[..., 0] == v, DISK(r)) & (ML[..., 0] != 0)
        P["zone_" + kind] = b64png(Image.fromarray((z * 255).astype(np.uint8)).crop(box))
    for n in NAMES:
        arr = np.array(Image.open(os.path.join(L, f"{n}_{pose}.png")).convert("RGBA"))
        P[n] = b64png(Image.fromarray(labels(arr, KEYS[n.split("_")[0]], n.split("_")[0])).crop(box))
    out[pose] = P
json.dump(out, open(os.path.join(HERE, "doll_labels.json"), "w"))
print("KB", os.path.getsize(os.path.join(HERE, "doll_labels.json")) // 1024)
