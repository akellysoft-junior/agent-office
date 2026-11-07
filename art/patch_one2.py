"""one(한 사무실) 다듬기: 넓은 사무실, 조용한 화면.
- 본사를 건물 4채 자리만큼 넓히고(책상 16개) 그 자리의 건물 3채는 숨김
- 사람: 한 번에 최대 4명, 출근은 간격을 두고 한 명씩. 퇴근하면 반짝이며 바로 사라짐
- 이름표·세션 표 없음 (누르면 대화창에 자세히)
- 말풍선: 세션 고양이는 말하지 않음(타자 배지만), 사람은 가끔 짧게. 화면 전체에 말풍선은 한 번에 하나
- 생각 구름·진행 막대·사람 작업 배지 없음"""
import re, sys
app = sys.argv[1]
s = open(app).read()
def rep(a, b, cnt=1):
    global s
    assert a in s, a[:90]; s = s.replace(a, b, cnt)

# ── 1) 사무실 크기·책상 배치를 사무실마다
rep('''const lotDesk  = (L, i) => ({x: L.x + 12 + (i % 3) * 46, y: L.y + 12 + Math.floor(i / 3) * 38});''',
'''if (ONE){                                       // one: 본사를 넓게 (옆·아래 건물 자리까지, 그 건물들은 숨김)
  Object.assign(SLOTS[0], {w:380, d:232, cols:4, gx:66, gy:50, ox:26, oy:24, maxDesks:16});
  for (const i of [1, 3, 4]) SLOTS[i].hidden = true;
}
for (const L of SLOTS) L.lx = L.x + L.w - LOT_W;     // 휴게공간은 늘 오른쪽 끝 (기본 크기면 L.x 와 같음)
const lotMax   = L => L.maxDesks || MAX_DESKS;
const lotDesk  = (L, i) => ({x: L.x + (L.ox ?? 12) + (i % (L.cols || 3)) * (L.gx || 46), y: L.y + (L.oy ?? 12) + Math.floor(i / (L.cols || 3)) * (L.gy || 38)});''')
rep('const lotAisle = L => L.x + 148;', 'const lotAisle = L => L.lx + 148;')
# 휴게공간 좌표 L.x+1xx/2xx → L.lx+…
def lounge_fix(block):
    return re.sub(r'L\.x ?\+ ?(1[5-9]\d|2[0-2]\d)\b', lambda m: f'L.lx + {m.group(1)}', block)
for start, end in [('const lotLounge = L => [', '];'), ('function loungeSofa(L){', 'function drawMonitorWall(L, list, now){')]:
    i = s.index(start); j = s.index(end, i) + len(end); s = s[:i] + lounge_fix(s[i:j]) + s[j:]
i = s.index('function drawLot(i, now){'); j = s.index('function drawCampus(now){', i)
blk = lounge_fix(s[i:j])
blk = blk.replace('floorPoly(L.lx + 156, L.y, L.w - 156, L.d, P.side, 0, true)', 'floorPoly(L.lx + 156, L.y, L.x + L.w - L.lx - 156, L.d, P.side, 0, true)')
blk = blk.replace('ctx.beginPath(); ctx.ellipse(isoX(L.x+78, L.y+L.d/2), isoY(L.x+78, L.y+L.d/2), 100, 42, 0, 0, 7); ctx.fill();',
                  'const lcx = (L.x + L.lx + 148) / 2, lsc = (L.lx - L.x + LOT_W) / LOT_W;\n    ctx.beginPath(); ctx.ellipse(isoX(lcx, L.y+L.d/2), isoY(lcx, L.y+L.d/2), 100*lsc, 42*lsc, 0, 0, 7); ctx.fill();')
blk = blk.replace('for (let k=n; k<MAX_DESKS; k++) L.appear[k] = undefined;', 'for (let k=n; k<lotMax(L); k++) L.appear[k] = undefined;')
s = s[:i] + blk + s[j:]
assert 'floorPoly(L.lx + 156, L.y, L.x + L.w - L.lx - 156' in s
rep('''  for (let i=0; i<MAX_DESKS; i++) if (!used.has(i)){ idx = i; break; }
  if (idx < 0) return false;                     // 책상이 꽉 차면 다음에''',
'''  for (let i=0; i<lotMax(L); i++) if (!used.has(i)){ idx = i; break; }
  if (idx < 0) return false;                     // 책상이 꽉 차면 다음에''')
rep('''  for (let i=0; i<MAX_DESKS; i++) if (!used.has(i)){ idx = i; break; }
  if (idx < 0 && team){''', '''  for (let i=0; i<lotMax(L); i++) if (!used.has(i)){ idx = i; break; }
  if (idx < 0 && team){''')
# 숨긴 건물은 그리지도, 누르지도 않음 / 그 자리 가로등도 치움
rep('const items = SLOTS.map((L, i) => ({z: L.x + L.w/2 + L.y + L.d/2, fn:() => drawLot(i, now)}));',
    'const items = SLOTS.map((L, i) => L.hidden ? null : {z: L.x + L.w/2 + L.y + L.d/2, fn:() => drawLot(i, now)}).filter(Boolean);')
rep('  for (let i=0; i<SLOTS.length; i++) if (inPoly(x, y, lotHull(i))) return i;',
    '  for (let i=0; i<SLOTS.length; i++) if (!SLOTS[i].hidden && inPoly(x, y, lotHull(i))) return i;')
rep('  for (const [x, y] of CAMPUS_LAMPS) out.push({z: x + y, fn:() => streetLamp(x, y)});',
    '  for (const [x, y] of CAMPUS_LAMPS) if (!(ONE && x < 505 && y < 318)) out.push({z: x + y, fn:() => streetLamp(x, y)});')

# ── 2) 사람: 적당히 (최대 4명, 한 명씩 간격), 퇴근하면 바로 사라짐, 말은 가끔
rep('''    if (!m.present){
      if (nowMs >= m.nextAt && !teamArrive(m)) m.nextAt = nowMs + 20000;
      continue;
    }''',
'''    if (!m.present){
      if (nowMs < m.nextAt) continue;
      if (ONE){                                   // one: 한 번에 최대 4명, 출근은 한 명씩 간격을 두고
        const here = team.members.filter(x => x.present).length;
        if (here >= 4 || nowMs < (team.nextArriveAt || 0)){ m.nextAt = nowMs + rand(8000, 20000); continue; }
      }
      if (!teamArrive(m)) m.nextAt = nowMs + 20000;
      else if (ONE) team.nextArriveAt = nowMs + rand(25000, 60000) * (team.source === "demo" ? 0.4 : 1);
      continue;
    }''')
rep('''    if (nowMs >= m.leaveAt && !talking){          // 이야기하는 중엔 퇴근을 미룬다''',
'''    if (ONE && nowMs >= m.leaveAt && !talking){   // one: 퇴근하면 반짝 하고 바로 사라짐
      sparkle(c.pos.x, c.pos.y);
      Object.assign(m, {present:false, leaving:false, cat:null, nextAt: nowMs + tierTime(m, "away")});
      live.ver++;
      continue;
    }
    if (nowMs >= m.leaveAt && !talking){          // 이야기하는 중엔 퇴근을 미룬다''')
rep('''  if (!instant) say(c, m.tier === "guest"''', '''  if (!instant && !ONE) say(c, m.tier === "guest"''')
rep('''        say(c, pick(["커피 한 잔", "잠깐 쉬자", "스트레칭~", "고양이들 귀엽다"]), 2);''',
    '''        if (!ONE) say(c, pick(["커피 한 잔", "잠깐 쉬자", "스트레칭~", "고양이들 귀엽다"]), 2);''')
rep('''        m.murmurAt = nowMs + rand(18000, 45000);''',
    '''        m.murmurAt = nowMs + (ONE ? rand(70000, 160000) : rand(18000, 45000));''')
# one: 처음 열 때도 한꺼번에 앉아 있지 않게 (상주 멤버 2명만 바로)
rep('''    if (m.tier === "core" || (m.tier === "regular" && Math.random() < 0.4)) m.nextAt = 1;''',
'''    if (ONE ? m.rank < 2 : (m.tier === "core" || (m.tier === "regular" && Math.random() < 0.4))) m.nextAt = 1;''')

# ── 3) 말풍선: 세션 고양이는 말 안 함, 전체 한 번에 하나
rep('function say(a, text, dur=2.6){ a.bubble = {text, t:dur}; }',
'''function say(a, text, dur=2.6){
  if (ONE && mode === "live" && live){            // one: 세션 고양이는 말하지 않고(누르면 자세히), 화면 전체에 말풍선은 하나만
    if (!a.human) return;
    if (visibleCats().some(o => o !== a && o.bubble)) return;
  }
  a.bubble = {text, t:dur};
}''')

# ── 4) 생각 구름·진행 막대 없음, 사람은 작업 배지 없음, 이름표·세션 표 없음
rep('  if (pose === "think" && !a.bubble){            // 💭 생각 구름',
    '  if (pose === "think" && !a.bubble && !ONE){            // 💭 생각 구름')
rep('  if (a.state === "working" && a.workDur > 0){\n    const p = Math.min(1, a.workT / a.workDur), bw = 20*k',
    '  if (a.state === "working" && a.workDur > 0 && !ONE){\n    const p = Math.min(1, a.workT / a.workDur), bw = 20*k')
rep('    if (pose === "work") drawWorkBadge(a, sx, sy - lift, k, now, kind);',
    '    if (pose === "work" && !(ONE && a.human)) drawWorkBadge(a, sx, sy - lift, k, now, kind);')
rep('    if (ONE){ drawSessionTag(s, look, now); continue; }',
    '    if (ONE){ if (s.stampUntil > now) drawSessionTag(s, look, now, true); continue; }   // one: 표 없이 완료 도장만')
rep('function drawSessionTag(s, look, now){', 'function drawSessionTag(s, look, now, stampOnly){')
rep('''  if (y > hh){
    ctx.strokeStyle = TOD.ink; ctx.fillStyle = look.bg || TOD.paper;
    ctx.beginPath(); ctx.roundRect(x - w/2, y - hh, w, hh, hh/2); ctx.fill(); ctx.stroke();''',
'''  if (y > hh && !stampOnly){
    ctx.strokeStyle = TOD.ink; ctx.fillStyle = look.bg || TOD.paper;
    ctx.beginPath(); ctx.roundRect(x - w/2, y - hh, w, hh, hh/2); ctx.fill(); ctx.stroke();''')
rep('      if (a.lot !== cam.focus || a === talkSel.cat || (ONE && !a.human)) continue;',
    '      if (ONE || a.lot !== cam.focus || a === talkSel.cat) continue;   // one: 이름표 없음 (누르면 대화창)')
open(app, "w").write(s)
print("ok")
