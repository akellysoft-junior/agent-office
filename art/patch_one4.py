"""one(한 사무실) 4차: 바깥 풍경 정리.
- 다른 건물은 모두 숨기고, 본사 한 채가 앉은 마당 + 남쪽·동쪽 도로만
- 문 앞 돌길과 횡단보도, 벤치·우체통·자전거·화단, 도로변 가로등, 마당 둘레 나무
- 카메라 기본 위치·배율을 본사에 맞춤"""
import sys
app = sys.argv[1]
s = open(app).read()
def rep(a, b, cnt=1):
    global s
    assert a in s, a[:90]; s = s.replace(a, b, cnt)

# 1) 다른 건물 모두 숨김
rep("  for (const i of [1, 3, 4]) SLOTS[i].hidden = true;   // 앞을 가리지 않게 옆·아래 건물은 숨김",
    "  for (let i = 1; i < SLOTS.length; i++) SLOTS[i].hidden = true;   // 본사 한 채만")

# 2) 카메라: 본사 중심, 조금 더 가깝게
rep("const CENTER = [430, 280];            // 장면 내용의 중심 (카메라 기본 위치)",
    "const CENTER = ONE ? [250 + (150 - 96) * 0.78, 75 + (150 + 96) * 0.39 - 10] : [430, 280];   // 장면 내용의 중심 (one: 캠퍼스 원점(250,75) 기준 본사 가운데)")
rep("const overviewZ = () => scene !== \"campus\" ? 1 : EMBED ? embedZ : narrow ? 1.5 : 1;",
    "const overviewZ = () => scene !== \"campus\" ? 1 : (EMBED ? embedZ : narrow ? 1.5 : 1) * (ONE ? 1.55 : 1);")

# 3) 땅: one 전용 판·도로
rep("function drawCampusGround(){\n  const P = TOD;",
'''const ONE_YARD = [-40, -40, 380, 270];          // one: 본사 마당 (x -40~340, y -40~230)
const ONE_PLATES = [[-900, -900, 1240, 860], [-900, -40, 860, 270], [400, -900, 1500, 1130], [-900, 300, 2800, 900], ONE_YARD];
const ONE_LAMPS = [[30, 244], [176, 244], [318, 244], [354, 40], [354, 170]];
function drawOneGround(){
  const P = TOD;
  ctx.save(); ctx.setLineDash([7, 7]); ctx.globalAlpha = .45;
  line([gpt(-900, 265, -12), gpt(1600, 265, -12)]);           // 남쪽 도로 중앙선
  line([gpt(370, -900, -12), gpt(370, 230, -12)]);             // 동쪽 도로 중앙선
  ctx.restore();
  for (let i = 0; i < 4; i++) floorPoly(208, 238 + i * 15, 32, 6, P.plate, -12, true);   // 문 앞 횡단보도
  for (const [x, y, w, d] of ONE_PLATES){
    wallQuad(x, y+d, x+w, y+d, -12, GZ, P.side);
    wallQuad(x+w, y+d, x+w, y, -12, GZ, P.side);
    floorPoly(x, y, w, d, P.plate, GZ);
  }
  ctx.save(); ctx.globalAlpha = .55;                             // 문 앞 돌길
  for (let i = 0; i < 4; i++) floorPoly(216 + (i % 2) * 2, 180 + i * 12, 14, 8, P.paper, GZ);
  ctx.restore();
  if (P.lamp > 0.02){
    for (const [lx, ly] of ONE_LAMPS){
      const g = ctx.createRadialGradient(isoX(lx,ly), isoY(lx,ly,GZ), 2, isoX(lx,ly), isoY(lx,ly,GZ), 46);
      g.addColorStop(0, `rgba(255,205,120,${(.42*P.lamp).toFixed(3)})`); g.addColorStop(1, "rgba(255,205,120,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(isoX(lx,ly), isoY(lx,ly,GZ), 50, 22, 0, 0, 7); ctx.fill();
    }
  }
}
function oneDecor(){
  const out = [
    {z:-260, fn:() => apartment(60, -250, 100, 56, 90, 1)},
    {z:-250, fn:() => apartment(300, -260, 100, 60, 100, 3)},
  ];
  for (const [x, y, h, r] of [[10,-26,58,15],[95,-30,64,17],[180,-24,56,15],[265,-30,62,16],[330,-20,54,14],
                              [-26,30,60,16],[-30,110,56,15],[-24,190,62,16],
                              [-120,90,58,16],[460,60,60,16],[470,190,56,15],[60,330,58,16],[300,336,62,17]])
    out.push({z: x + y, fn:() => tree(x, y, h, r)});
  for (const [x, y] of ONE_LAMPS) out.push({z: x + y, fn:() => streetLamp(x, y)});
  out.push({z: 270 + 212, fn:() => bench(262, 206)});
  out.push({z: 140 + 212, fn:() => bench(130, 206)});
  out.push({z: 196 + 214, fn:() => mailbox(194, 210)});
  out.push({z: 300 + 214, fn:() => bike(292, 212)});
  out.push({z: 205 + 190, fn:() => planter(196, 186, ["#e9897a","#ffd36b","#e9897a"])});
  out.push({z: 250 + 190, fn:() => planter(244, 186, ["#7cc59a","#f08a8a","#7cc59a"])});
  return out;
}
function drawCampusGround(){
  if (ONE) return drawOneGround();
  const P = TOD;''')
rep("function campusDecor(now){\n  const out = [", "function campusDecor(now){\n  if (ONE) return oneDecor();\n  const out = [")
open(app, "w").write(s)
print("ok")
s = open(app).read()
for a, b in [
  ("for (let i = 0; i < 4; i++) floorPoly(216 + (i % 2) * 2, 180 + i * 12, 14, 8, P.paper, GZ);",
   "for (let i = 0; i < 4; i++) floorPoly(216 + (i % 2) * 2, 180 + i * 12, 14, 8, P.paper, GZ, true);"),
  ("for (const [px, py, h] of [[ax - 14, y0 + 140, 20], [x0 + 150, y0 + 150, 16], [x0 + 2, y0 + 2, 22]])",
   "for (const [px, py, h] of [[ax - 16, y0 + 152, 14], [x0 + 128, y0 + 156, 12], [x0 + 2, y0 + 2, 22]])   // 벽 쪽에 낮게"),
]:
    assert a in s, a[:60]; s = s.replace(a, b)
open(app, "w").write(s)
print("ok2")
