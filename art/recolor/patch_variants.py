"""앱에 종류별 그림(머리 모양 8종·무늬 5종) 넣기. 다시 실행해도 같은 결과 (기존 종류 항목은 지우고 새로 넣음)."""
import json, re, sys, os
app = sys.argv[1]
E = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "entries.json")))
s = open(app).read()
s = re.sub(r'^  "(human|humanWork|cat|catWork)\.\w+": \{.*\n', "", s, flags=re.M)        # 이전에 넣은 종류 항목 제거
lines = "".join(f'  "{k}": {{units:{e["units"]}, ax:{e["ax"]}, ay:{e["ay"]}, hx:{e["hx"]}, turn:null, O:"{e["O"]}", map:"{e["map"]}", src:"{e["src"]}"}},\n'
                for k, e in E.items())
m = re.search(r'^  catWork: \{.*\n', s, re.M); assert m
s = s[:m.end()] + "  // 종류별 그림 (생성 시트에서 자름: 사람 머리 모양 8종, 고양이 무늬 5종 × 서기/작업). 색은 영역 지도로 캐릭터마다 바꿈\n" * (("종류별 그림 (생성 시트" not in s)) + lines + s[m.end():]

def rep(a, b):
    global s
    if b in s: return
    assert a in s, a[:70]; s = s.replace(a, b, 1)

rep('const REGION = {human: {hair: 1, skin: 2, shirt: 3, pants: 4}, cat: {fur: 1, patch: 2}};',
    'const REGION = {human: {hair: 1, skin: 2, shirt: 3, pants: 4, hat: 5}, cat: {fur: 1, patch: 2}};')
rep('if (a.human){ const L = a.look; return L ? {hair: L.hair, skin: L.skin, shirt: L.shirt, pants: L.pants} : null; }',
    'if (a.human){ const L = a.look; return L ? {hair: L.hair, skin: L.skin, shirt: L.shirt, pants: L.pants, hat: L.hat || L.shirt} : null; }')
rep('const artVariants = new Map();',
'''const artVariants = new Map();
/* 종류 고르기: 사람은 머리 모양(look.style, 안경), 고양이는 털 무늬(coat)로. 그 종류 그림이 없으면 기본 그림. */
function humanArt(a){
  const L = a.look || {}, h = hashStr(String(a.id || a.name || ""));
  switch (L.style){
    case "short": return h & 1 ? "short" : "bob";
    case "long": return L.glasses ? "glasses" : "long";
    case "ponytail": case "bun": case "curly": case "beanie": return L.style;
    default: return "bob";
  }
}
function catArt(C){
  if (!C) return "patch";
  if (C.tux) return "tux";
  if (C.patch) return "patch";
  if (C.stripe) return "tabby";
  return lumHex(C.base) > 0.8 ? "socks" : "solid";
}
function artKind(base, a){
  const k = base + "." + (a.human ? humanArt(a) : catArt(a.coat));
  return CHAR_ART[k] && charArt.levels[k] && charArt.levels[k].length ? k : base;
}''')
rep('const kind = artWork ? (a.human ? "humanWork" : "catWork") : (a.human ? "human" : "cat");',
    'const kind = artKind(artWork ? (a.human ? "humanWork" : "catWork") : (a.human ? "human" : "cat"), a);')
rep('const kind = c.human ? "human" : "cat", img = artLevelsFor(kind, c)[0], [fx, fy, fs] = ART_FACE[kind];',
    'const kind = artKind(c.human ? "human" : "cat", c), img = artLevelsFor(kind, c)[0], [fx, fy, fs] = ART_FACE[kind] || [0, 0, 1];')
open(app, "w").write(s)
print("ok", len(E))
