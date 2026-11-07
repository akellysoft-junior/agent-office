"""v3: 높은 해상도 종류 그림(사람 9종+단발, 고양이 4종+줄무늬)과 안쪽 옷 색."""
import json, re, sys, os
app = sys.argv[1]
E = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "all_entries.json")))
s = open(app).read()
s = re.sub(r'^  "(human|humanWork|cat|catWork)\.\w+": \{.*\n', "", s, flags=re.M)
lines = "".join(f'  "{k}": {{units:{e["units"]}, ax:{e["ax"]}, ay:{e["ay"]}, hx:{e["hx"]}, turn:null, O:"{e["O"]}", map:"{e["map"]}", src:"{e["src"]}"}},\n' for k, e in E.items())
m = re.search(r'^  // 종류별 그림 \(생성 시트.*\n', s, re.M); assert m
s = s[:m.start()] + "  // 종류별 그림: 사람 = 머리 모양·옷 10종, 고양이 = 무늬 5종 (서기/작업). 색은 영역 지도로 캐릭터마다 바꿈 (art/recolor, v3/process_v3.py)\n" + lines + s[m.end():]
def rep(a, b):
    global s
    if b in s: return
    assert a in s, a[:70]; s = s.replace(a, b, 1)
rep('const REGION = {human: {hair: 1, skin: 2, shirt: 3, pants: 4, hat: 5}, cat: {fur: 1, patch: 2}};',
    'const REGION = {human: {hair: 1, skin: 2, shirt: 3, pants: 4, hat: 5, inner: 6}, cat: {fur: 1, patch: 2}};\nconst INNER_COLORS = ["#ffffff", "#f4ecdc", "#d8dde6", "#3a3f4b", "#f3dfa0", "#cfe3d2"];   // 가디건·후드티 안에 입은 옷')
rep('if (a.human){ const L = a.look; return L ? {hair: L.hair, skin: L.skin, shirt: L.shirt, pants: L.pants, hat: L.hat || L.shirt} : null; }',
    'if (a.human){ const L = a.look; return L ? {hair: L.hair, skin: L.skin, shirt: L.shirt, pants: L.pants, hat: L.hat || L.shirt,\n    inner: INNER_COLORS[(hashStr(String(a.id || a.name || "")) >>> 3) % INNER_COLORS.length]} : null; }')
rep('''    case "short": return h & 1 ? "short" : "bob";
    case "long": return L.glasses ? "glasses" : "long";
    case "ponytail": case "bun": case "curly": case "beanie": return L.style;''',
'''    case "short": return ["bob", "short", "fringe"][h % 3];
    case "long": return L.glasses ? "longglasses" : "wavy";
    case "ponytail": return L.glasses ? "ponyglasses" : "ponytail";
    case "bun": return "bunhood";
    case "curly": case "beanie": return L.style;''')
open(app, "w").write(s); print("ok", len(E))
