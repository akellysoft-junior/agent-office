"""생성 시트(사람 8종·고양이 5종 × 서기/작업)를 낱장으로 자르기.
각 캐릭터는 하나로 이어진 덩어리라서, 덩어리 번호로 자기 픽셀만 골라 자른다 (옆 캐릭터와 겹쳐도 안전)."""
import sys, os, json
import numpy as np
from PIL import Image
from scipy import ndimage
HERE = os.path.dirname(os.path.abspath(__file__))
src = sys.argv[1]
im = np.array(Image.open(src).convert("RGBA"))
m = im[..., 3] > 40
lab, n = ndimage.label(m)
sz = ndimage.sum(m, lab, range(1, n + 1)); objs = ndimage.find_objects(lab)
parts = [(i + 1, o) for i, (o, s) in enumerate(zip(objs, sz)) if s > 5000]
assert len(parts) == 26, len(parts)
HUM = ["bob", "long", "ponytail", "bun", "glasses", "short", "curly", "beanie"]
CAT = ["patch", "tabby", "tux", "solid", "socks"]
mid = im.shape[0] / 2
rows = {0: [], 1: []}
for lid, o in parts: rows[int((o[0].start + o[0].stop) / 2 > mid)].append((o[1].start, lid, o))
out = {}
os.makedirs(os.path.join(HERE, "sprites"), exist_ok=True)
for r, pose in ((0, "stand"), (1, "work")):
    items = sorted(rows[r])
    assert len(items) == 13
    for j, (_, lid, o) in enumerate(items):
        name = ("human_" + HUM[j]) if j < 8 else ("cat_" + CAT[j - 8])
        own = ndimage.binary_dilation(lab == lid, iterations=4)
        other = (lab > 0) & (lab != lid)
        keep = own & ~other
        a = im.copy(); a[..., 3] = np.where(keep, a[..., 3], 0)
        ys, xs = np.where(a[..., 3] > 8); pad = 6
        crop = a[ys.min() - pad: ys.max() + pad + 1, max(0, xs.min() - pad): xs.max() + pad + 1]
        Image.fromarray(crop).save(os.path.join(HERE, "sprites", f"{name}_{pose}.png"))
        out[f"{name}_{pose}"] = crop.shape[:2]
print(json.dumps(out))
