"""5차: 작업 고양이 크기를 서 있는 고양이와 같게 + 사람 휴식 자주 (one).
- 종류별 그림 항목을 다시 넣음 (v3/all_entries.json: 작업 고양이 1/1.2 축소 없앰)
- one: 사람은 30~90초 뒤 첫 휴식, 그 뒤 1~2.5분마다. 휴식 자리: 휴게실 러그 2곳 + 정수기 앞 + 회의 테이블 옆"""
import json, re, sys, os
app = sys.argv[1]
E = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "v3", "all_entries.json")))
s = open(app).read()
s = re.sub(r'^  "(human|humanWork|cat|catWork)\.\w+": \{.*\n', "", s, flags=re.M)
m = re.search(r'^  // 종류별 그림: .*\n', s, re.M); assert m
lines = "".join(f'  "{k}": {{units:{e["units"]}, ax:{e["ax"]}, ay:{e["ay"]}, hx:{e["hx"]}, turn:null, O:"{e["O"]}", map:"{e["map"]}", src:"{e["src"]}"}},\n' for k, e in E.items())
s = s[:m.end()] + lines + s[m.end():]
def rep(a, b):
    global s
    if b in s: return
    assert a in s, a[:90]; s = s.replace(a, b, 1)
rep('''                    leaveAt: Date.now() + tierTime(m, "stay"), breakAt: Date.now() + rand(1.5*MIN, 4*MIN)});''',
    '''                    leaveAt: Date.now() + tierTime(m, "stay"), breakAt: Date.now() + (ONE ? rand(30000, 90000) : rand(1.5*MIN, 4*MIN))});''')
rep('''      const spots = lotLounge(L);
      const taken = new Set((ONE ? visibleCats().filter(x => x.lot === team.slot) : team.members.filter(x => x.present).map(x => x.cat))
                              .filter(x => x.inLounge).map(x => x.loungeIdx));
      const free = (charArt.ready ? [3, 4] : [0, 1, 3, 4]).filter(i => !taken.has(i));''',
'''      const spots = lotLounge(L);
      if (L.big) spots.push({x: lotAisle(L) - 6, y: L.y + 22, lift:0, nap:999},      // 6: 정수기 앞
                            {x: L.x + 98, y: L.y + 150, lift:0, nap:999});            // 7: 회의 테이블 옆
      const taken = new Set((ONE ? visibleCats().filter(x => x.lot === team.slot) : team.members.filter(x => x.present).map(x => x.cat))
                              .filter(x => x.inLounge).map(x => x.loungeIdx));
      const free = (charArt.ready ? (L.big ? [3, 4, 6, 7] : [3, 4]) : [0, 1, 3, 4]).filter(i => !taken.has(i));''')
rep('''      m.breakAt = nowMs + rand(3*MIN, 6*MIN);''', '''      m.breakAt = nowMs + (ONE ? rand(60000, 150000) : rand(3*MIN, 6*MIN));''')
open(app, "w").write(s)
print("ok")
