"""앱에 색 바꾸기 넣기: CHAR_ART 에 O·map 추가, 지도 로드, 캐릭터별 색 변형 캐시."""
import json, re, sys, os
app = sys.argv[1]
M = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "maps.json")))
s = open(app).read()
for key, m in M.items():
    pat = re.compile(r'^(  ' + key + r':\s*\{)(.*?)(src:")', re.M)
    mm = pat.search(s); assert mm, key
    head = mm.group(2)
    head = re.sub(r'O:"#[0-9a-f]{6}", map:"[^"]*", ', '', head)
    s = s[:mm.start()] + mm.group(1) + head + f'O:"{m["O"]}", map:"{m["map"]}", ' + mm.group(3) + s[mm.end():]

def rep(a, b):
    global s
    assert a in s, a[:60]; s = s.replace(a, b, 1)

rep('const charArt = {ready:false, failed:false, levels:{human:[], cat:[], humanWork:[], catWork:[]}};',
    'const charArt = {ready:false, failed:false, levels:{human:[], cat:[], humanWork:[], catWork:[]}, base:{}, maps:{}};')
rep('''    img.onload = () => resolve([kind, A.svg ? rasterize(img, A) : img]);
    img.onerror = () => reject(new Error(kind));
    img.src = A.svg ? svgSource(A) : A.src;
  }))).then(list => {
    for (const [kind, img] of list) charArt.levels[kind] = artLevels(img);''',
'''    img.onload = () => resolve([kind, A.svg ? rasterize(img, A) : img]);
    img.onerror = () => reject(new Error(kind));
    img.src = A.svg ? svgSource(A) : A.src;
  }).then(r => !CHAR_ART[r[0]].map ? r : new Promise(res => {          // 색 바꾸기 지도 (없거나 실패하면 원래 색으로)
    const mi = new Image();
    mi.onload = () => {
      const c = document.createElement("canvas"); c.width = mi.width; c.height = mi.height;
      const x = c.getContext("2d"); x.drawImage(mi, 0, 0);
      charArt.maps[r[0]] = x.getImageData(0, 0, c.width, c.height).data; res(r);
    };
    mi.onerror = () => res(r);
    mi.src = CHAR_ART[r[0]].map;
  })))).then(list => {
    for (const [kind, img] of list){ charArt.levels[kind] = artLevels(img); charArt.base[kind] = img; }''')

rep('function drawArt(kind, x, y, h, flip, turn, mot){\n  const lv = charArt.levels[kind];',
'''/* 색 바꾸기: 영역 지도(R = 영역 번호, G = 외곽선→칠 위치 t×200)로 칠을 새 색으로 바꾼다.
   새 픽셀 = 외곽선 색 + t·(새 색 − 외곽선 색) → 질감·명암·외곽 안티에일리어싱이 그대로 남음.
   사람: 머리·피부·상의·바지 (a.look), 고양이: 밝은 털·무늬 (a.coat). 같은 색 조합은 한 번만 만들어 둠. */
const REGION = {human: {hair: 1, skin: 2, shirt: 3, pants: 4}, cat: {fur: 1, patch: 2}};
const hexRGB = h => { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; };
const mixHex = (a, b, t) => "#" + hexRGB(a).map((v, i) => Math.round(v + (hexRGB(b)[i] - v) * t).toString(16).padStart(2, "0")).join("");
const lumHex = h => { const [r, g, b] = hexRGB(h); return (0.299 * r + 0.587 * g + 0.114 * b) / 255; };
function coatColors(C){                       // 고양이 털 → 그림의 (밝은 털, 무늬) 두 영역
  if (!C || !C.base) return null;
  const light = lumHex(C.base) > 0.8;
  return light ? {fur: C.base, patch: C.patch || C.stripe || mixHex(C.base, "#6b6f7a", 0.45)}
               : {fur: C.paw || mixHex(C.base, "#ffffff", lumHex(C.base) < 0.3 ? 0.3 : 0.8), patch: C.base};
}
function artLook(a){
  if (a.human){ const L = a.look; return L ? {hair: L.hair, skin: L.skin, shirt: L.shirt, pants: L.pants} : null; }
  return coatColors(a.coat);
}
const artVariants = new Map();
function recolorArt(kind, cols){
  const base = charArt.base[kind], m = charArt.maps[kind];
  const c = document.createElement("canvas"); c.width = base.width; c.height = base.height;
  const x = c.getContext("2d"); x.drawImage(base, 0, 0);
  const d = x.getImageData(0, 0, c.width, c.height), p = d.data;
  if (m.length !== p.length) return base;                     // 지도와 그림 크기가 다르면 원래 색
  const O = hexRGB(CHAR_ART[kind].O), T = [];
  for (const [name, id] of Object.entries(REGION[kind.startsWith("human") ? "human" : "cat"])) if (cols[name]) T[id] = hexRGB(cols[name]);
  for (let i = 0; i < p.length; i += 4){
    const t = T[m[i]]; if (!t) continue;
    const f = m[i + 1] / 200;
    p[i] = O[0] + (t[0] - O[0]) * f; p[i + 1] = O[1] + (t[1] - O[1]) * f; p[i + 2] = O[2] + (t[2] - O[2]) * f;
  }
  x.putImageData(d, 0, 0);
  return c;
}
function artLevelsFor(kind, a){
  const cols = a && artLook(a);
  if (!cols || !charArt.maps[kind]) return charArt.levels[kind];
  const key = kind + "|" + Object.values(cols).join(",");
  let lv = artVariants.get(key);
  if (!lv){ lv = artLevels(recolorArt(kind, cols)); artVariants.set(key, lv); }
  return lv;
}
function drawArt(kind, x, y, h, flip, turn, mot, levels){
  const lv = levels || charArt.levels[kind];''')
rep('drawArt(kind, sx, sy - lift - (mot ? mot.bob : 0), CHAR_ART[kind].units * k, ff < 0, artWork ? ("turn" in CHAR_ART[kind] ? CHAR_ART[kind].turn : WORK_TURN) : null, mot);',
    'drawArt(kind, sx, sy - lift - (mot ? mot.bob : 0), CHAR_ART[kind].units * k, ff < 0, artWork ? ("turn" in CHAR_ART[kind] ? CHAR_ART[kind].turn : WORK_TURN) : null, mot, artLevelsFor(kind, a));')
rep('const kind = c.human ? "human" : "cat", img = charArt.levels[kind][0],',
    'const kind = c.human ? "human" : "cat", img = artLevelsFor(kind, c)[0],')
open(app, "w").write(s)
print("patched", app)
