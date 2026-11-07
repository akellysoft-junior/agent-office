"""색 바꾸기용 영역 지도 만들기.
각 픽셀을 '외곽선 색 O → 칠 색 F' 선 위의 한 점으로 보고 (t = 그 선 위 위치), 영역 번호와 t 를 PNG 에 저장한다.
  R = 영역 번호 (0 = 그대로 둠), G = t × 200 (0~255)
앱에서는 새 색 T 로 O + t·(T − O) 를 칠해서 질감·명암·외곽 안티에일리어싱을 그대로 살린다."""
import json, os, io, base64
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
hx = lambda s: np.array([int(s[i:i + 2], 16) for i in (1, 3, 5)], float)

# 그림별: 외곽선 색, 영역(이름 → 칠 색), 그대로 둘 색, 공간 규칙
SPEC = {
  "human":     dict(O="#321705", fills={"hair": "#6f4637", "skin": "#fbd8bd", "shirt": "#f1775f", "pants": "#57423f"},
                    keep=["#b7b789", "#fbeee0"], hair_below=0.45, shoe_from=0.90),
  "humanWork": dict(O="#401e08", fills={"hair": "#7e5044", "skin": "#fad4bb", "shirt": "#f58065", "pants": "#644b4c"},
                    keep=["#fbeee0"], hair_below=0.53, shoe_from=0.86),
  "cat":       dict(O="#4a2711", fills={"fur": "#fbe9d1", "patch": "#f09f49"}, keep=["#f6b880"]),
  "catWork":   dict(O="#48240e", fills={"fur": "#fbe8d4", "patch": "#f59f52"}, keep=["#f5c9a5"]),
}
IDS = {"hair": 1, "skin": 2, "shirt": 3, "pants": 4, "fur": 1, "patch": 2}

out = {}
for key, S in SPEC.items():
    im = np.array(Image.open(os.path.join(HERE, key + ".png")).convert("RGBA")).astype(float)
    H, W = im.shape[:2]; p = im[..., :3]; al = im[..., 3]
    O = hx(S["O"]); names = list(S["fills"]); F = np.array([hx(S["fills"][n]) for n in names])
    best_res = np.full((H, W), 1e9); best_id = np.zeros((H, W), int); best_t = np.zeros((H, W))
    for i, n in enumerate(names):
        d = F[i] - O; L2 = (d * d).sum()
        t = ((p - O) * d).sum(-1) / L2
        res = np.sqrt(((p - (O + t[..., None] * d)) ** 2).sum(-1)) + np.maximum(0, t - 1.15) * 200
        better = res < best_res
        best_res[better] = res[better]; best_id[better] = IDS[n]; best_t[better] = t[better]
    # 그대로 둘 색에 더 가까우면 0
    for k in S["keep"]:
        kd = hx(k) - O; L2 = (kd * kd).sum(); t = ((p - O) * kd).sum(-1) / L2
        res = np.sqrt(((p - (O + t[..., None] * kd)) ** 2).sum(-1))
        best_id[(res < best_res) & (t > 0.5)] = 0
    best_id[best_res > 45] = 0
    best_id[best_t < 0.18] = 0              # 거의 외곽선
    best_id[al < 8] = 0
    yy = np.arange(H)[:, None].repeat(W, 1) / H
    if key.startswith("human"):
        hairish = (best_id == 1) | (best_id == 4)
        best_id[hairish & (yy < S["hair_below"])] = 1     # 위쪽 갈색 = 머리
        best_id[hairish & (yy >= S["hair_below"])] = 4    # 아래쪽 갈색 = 바지
        best_id[(best_id == 2) & (yy >= S["shoe_from"])] = 0   # 발 쪽 밝은색 = 신발 (그대로)
    m = np.zeros((H, W, 4), np.uint8)
    m[..., 0] = best_id; m[..., 1] = np.clip(best_t * 200, 0, 255); m[..., 3] = 255
    buf = io.BytesIO(); Image.fromarray(m).save(buf, "PNG", optimize=True)
    out[key] = dict(O=S["O"], map="data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
                    regions={n: IDS[n] for n in names})
    Image.fromarray(m).save(os.path.join(HERE, key + "_map.png"))
    # 확인용 영역 색칠
    vis = np.zeros((H, W, 3), np.uint8)
    for rid, c in {1: (220, 60, 60), 2: (60, 160, 60), 3: (60, 90, 220), 4: (200, 160, 30)}.items(): vis[best_id == rid] = c
    vis[(best_id == 0) & (al > 8)] = (40, 40, 40)
    Image.fromarray(vis).save(os.path.join(HERE, key + "_regions.png"))
    print(key, {n: int((best_id == IDS[n]).sum()) for n in names}, "map KB", len(buf.getvalue()) // 1024)
json.dump(out, open(os.path.join(HERE, "maps.json"), "w"))
