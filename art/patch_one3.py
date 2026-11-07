"""one(한 사무실) 3차: 덜 휑하게.
- 버그: 자리 4칸 앞에서 멈춰 '걷는 중'으로 굳음 → 커피 들고 서 있던 사람의 원인. 남은 경로를 끝까지 걷게 함
- 사무실 크기를 줄임 (책상 12개), 아래쪽 건물은 다시 보이게
- 쉬는 세션 고양이는 휴게실로 (다른 세션과 자리 안 겹치게), 명령 대기는 책상에서 '냥?' 팻말
- 소품: 책장, 정수기, 프린터, 화분, 시계, 포스터, 회의 테이블과 러그, 책상 위 소품"""
import sys
app = sys.argv[1]
s = open(app).read()
def rep(a, b, cnt=1):
    global s
    assert a in s, a[:90]; s = s.replace(a, b, cnt)

# 1) 걷기 버그 (두 모드 공통)
rep('''  } else if (Math.hypot(a.seat.x - a.pos.x, a.seat.y - a.pos.y) > 4){
    if (!a.path.length) goTo(a, a.seat.x, a.seat.y);''',
'''  } else if (a.path.length || Math.hypot(a.seat.x - a.pos.x, a.seat.y - a.pos.y) > 4){   // 남은 경로는 끝까지 (4칸 앞에서 멈추던 문제)
    if (!a.path.length) goTo(a, a.seat.x, a.seat.y);''')

# 2) 크기
rep("Object.assign(SLOTS[0], {w:380, d:232, cols:4, gx:66, gy:50, ox:26, oy:24, maxDesks:16});\n  for (const i of [1, 3, 4]) SLOTS[i].hidden = true;",
    "Object.assign(SLOTS[0], {w:300, d:172, cols:4, gx:50, gy:44, ox:18, oy:16, maxDesks:12, big:true});\n  for (const i of [1, 3, 4]) SLOTS[i].hidden = true;   // 앞을 가리지 않게 옆·아래 건물은 숨김")
rep("for (const [x, y] of CAMPUS_LAMPS) if (!(ONE && x < 505 && y < 318))", "for (const [x, y] of CAMPUS_LAMPS) if (!(ONE && x < 310 && y < 180))")

# 3) 쉬는 고양이: 휴게실 자리를 세션끼리 나눠 씀 / 명령 대기는 책상에서
rep('''      const taken = new Set(cats.filter(x => x.inLounge).map(x => x.loungeIdx));
      const free = spots.map((_, i) => i).filter(i => !taken.has(i));''',
'''      const sharing = ONE ? visibleCats().filter(x => x.lot === s.slot) : cats;   // one: 다른 세션 고양이·사람과 자리 나눔
      const taken = new Set(sharing.filter(x => x.inLounge).map(x => x.loungeIdx));
      const free = spots.map((_, i) => i).filter(i => !taken.has(i) && !(ONE && charArt.ready && [3, 4].includes(i) && sharing.some(x => x.human && x.inLounge)));''')
rep('''  if (ONE){ const i = s.bossIdx || 0; b.seat = {x: b.seat.x - 26 + (i % 3) * 13, y: b.seat.y - 8 - Math.floor(i / 3) * 12}; }''',
    '''  if (ONE){ b.seat = {...b.home}; b.seatLift = 7; }      // one: 명령 대기는 자기 책상에서 '냥?' 팻말''')
# 사람 휴식도 다른 고양이가 쓰는 자리는 피함
rep('''      const taken = new Set(team.members.filter(x => x.present && x.cat.inLounge).map(x => x.cat.loungeIdx));''',
'''      const taken = new Set((ONE ? visibleCats().filter(x => x.lot === team.slot) : team.members.filter(x => x.present).map(x => x.cat))
                              .filter(x => x.inLounge).map(x => x.loungeIdx));''')

# 4) 소품
rep('''  items.push({z: L.x + 8 + L.y + L.d - 8, fn:() => drawPlant(L.x + 2, L.y + L.d - 15, 18)});''',
'''  items.push({z: L.x + 8 + L.y + L.d - 8, fn:() => drawPlant(L.x + 2, L.y + L.d - 15, 18)});
  if (L.big) items.push(...bigOfficeProps(L, now));''')
rep('function drawCampus(now){',
'''/* one: 넓은 사무실 소품 (깊이 정렬에 섞임) */
function bigOfficeProps(L, now){
  const P = TOD, x0 = L.x, y0 = L.y, out = [];
  const ax = lotAisle(L);
  // 서쪽 벽: 책장 (책등 색색)
  out.push({z: x0 + 6 + y0 + 130, fn:() => {
    const bx = x0 + 1, by = y0 + 108, bd = 30;
    isoBox(bx, by, 8, bd, 0, 26, P.paper, P.paper, P.side);
    const cols = ["#e5534b", "#7fb2ea", "#f0c96b", "#8fbf9a", "#c79bff", "#f2a54e"];
    for (const z of [3, 12, 20]) for (let k = 0; k < 6; k++){
      const yy = by + 2 + k * 4.4, hgt = 5 + ((k * 7 + z) % 3);
      wallQuad(bx + 8, yy, bx + 8, yy + 3.2, z, z + hgt, cols[(k + z) % cols.length]);
    }
  }});
  // 서쪽 벽: 시계와 포스터
  out.push({z: -1e6, fn:() => {
    const [cx, cy] = gpt(x0, y0 + 100, 20);
    ell(cx, cy, 3.6, 4.4, P.paper);
    const t = new Date(), hr = (t.getHours() % 12 + t.getMinutes() / 60) / 12 * 6.283, mn = t.getMinutes() / 60 * 6.283;
    line([[cx, cy], [cx + Math.sin(hr) * 1.8, cy - Math.cos(hr) * 2.2]]);
    line([[cx, cy], [cx + Math.sin(mn) * 2.6, cy - Math.cos(mn) * 3.2]]);
    wallQuad(x0, y0 + 140, x0, y0 + 150, 9, 22, "#f6d6c8");
    wallQuad(x0, y0 + 142, x0, y0 + 148, 15, 20, "#7fb2ea");
  }});
  // 통로 옆: 정수기
  out.push({z: ax - 8 + y0 + 12, fn:() => {
    const wx = ax - 12, wy = y0 + 6;
    isoBox(wx, wy, 8, 8, 0, 14, P.paper, P.paper, P.side);
    isoBox(wx + 1.5, wy + 1.5, 5, 5, 14, 7, "#bfe6ff", "#bfe6ff", "#a6dcff");
    wallQuad(wx + 2, wy + 8, wx + 6, wy + 8, 9, 11, P.side);
  }});
  // 통로 옆: 프린터
  out.push({z: ax - 8 + y0 + 72, fn:() => {
    const px = ax - 16, py = y0 + 64;
    isoBox(px, py, 14, 10, 0, 8, P.paper, P.paper, P.side);
    isoBox(px + 1, py + 1, 12, 8, 8, 4, P.paper, P.paper, P.side);
    isoBox(px + 3, py + 3, 8, 4, 12, 0.6, "#ffffff", "#ffffff", "#ffffff");
  }});
  // 남쪽: 회의 러그 + 둥근 테이블 + 의자
  const mx = x0 + 70, my = y0 + 146;
  out.push({z: -1e5, fn:() => {
    ctx.save(); ctx.globalAlpha = .22; floorPoly(mx - 34, my - 14, 68, 26, L.trim, 0, true); ctx.restore();
    ctx.setLineDash([2, 2.5]); floorPoly(mx - 31, my - 11, 62, 20, null); ctx.setLineDash([]);
  }});
  for (const [dx, dy] of [[-15, -2], [15, -2], [0, 8]]) out.push({z: mx + dx + my + dy, fn:() => drawStool({x: mx + dx, y: my + dy}, 0)});
  out.push({z: mx + my + 1, fn:() => {
    line([gpt(mx, my, 0), gpt(mx, my, 9)]);
    const [cx, cy] = gpt(mx, my, 9.5); ell(cx, cy, 10, 4.4, P.paper);
    isoBox(mx - 2, my - 1, 3, 3, 9.5, 2.5, "#ffffff", "#ffffff", P.side);            // 머그
    isoBox(mx + 3, my - 3, 5, 4, 9.5, 0.6, "#f6f1e6", "#f6f1e6", "#f6f1e6");        // 종이
  }});
  // 화분 몇 개
  for (const [px, py, h] of [[ax - 14, y0 + 140, 20], [x0 + 150, y0 + 150, 16], [x0 + 2, y0 + 2, 22]])
    out.push({z: px + 6 + py + 6, fn:() => drawPlant(px, py, h)});
  return out;
}
function drawCampus(now){''')
# 책상 위 소품 (one 넓은 사무실): 책상 번호마다 화분/머그/서류
rep('''  isoBox(d.x + DESK_W/2 - 5, d.y + DESK_D - 5, 10, 3, 11, 0.8, P.paper, P.paper, P.side);
  ctx.globalAlpha = 1;
}''', '''  isoBox(d.x + DESK_W/2 - 5, d.y + DESK_D - 5, 10, 3, 11, 0.8, P.paper, P.paper, P.side);
  if (L.big) deskTrinket(d, i);
  ctx.globalAlpha = 1;
}''')
rep('function drawCampus(now){', '''function deskTrinket(d, i){                       // 모니터 뒤쪽 왼편에 작은 소품
  const P = TOD, x = d.x + 2.5, y = d.y + 2;
  const kind = (i * 5 + 1) % 4;
  if (kind === 0){ isoBox(x, y, 3.5, 3.5, 11, 3, "#c98d6b", "#c98d6b", "#a8714f"); const [cx, cy] = gpt(x + 1.7, y + 1.7, 15.5); bush(cx, cy, 3); }
  else if (kind === 1) isoBox(x, y + 1, 3, 3, 11, 3, "#ffffff", "#ffffff", P.side);
  else if (kind === 2){ isoBox(x, y, 5, 4, 11, 0.8, "#f6f1e6", "#f6f1e6", P.side); isoBox(x + 0.5, y + 0.3, 5, 4, 11.8, 0.8, "#ffffff", "#ffffff", P.side); }
}
function drawCampus(now){''')
open(app, "w").write(s)
print("ok")
# 사람은 휴게실에서 커피 들고 서서 쉼 (서서 조는 zzz 없음)
s = open(app).read()
old = 'napAfter:spots[i].nap, stateText:"휴게실에서 쉬는 중"});'
assert old in s
s = s.replace(old, 'napAfter:999, stateText:"휴게실에서 커피 마시는 중"});')
open(app, "w").write(s)
print("ok2")
