"""사무실 구성 옵션: rooms(세션마다 건물 하나, 지금 방식) / one(한 사무실에 세션 고양이 + 기여자 사람).
one: 세션 = 대장 고양이 한 마리(책상 하나), 서브에이전트는 따로 그리지 않고 고양이 머리 위 표에 🐾 수로.
사람은 지금처럼 깃 기여 통계(티어)에 따라 출근·퇴근. 책상은 세션 고양이가 먼저 쓰고 남는 자리를 사람이 씀."""
import sys
app = sys.argv[1]
s = open(app).read()
def rep(a, b, cnt=1):
    global s
    assert s.count(a) >= 1, a[:80]
    s = s.replace(a, b, cnt)

# 1) 설정
rep('const EMBED = document.documentElement.classList.contains("embed");',
'''const EMBED = document.documentElement.classList.contains("embed");
/* 사무실 구성: rooms = 세션마다 건물 하나 / one = 한 사무실에 세션 고양이와 기여자 사람이 함께 (URL ?layout=one, 아니면 저장된 값) */
const LAYOUT = (() => { let v = QS.get("layout"); if (!v) try { v = localStorage.getItem("ao.layout"); } catch {} return v === "one" ? "one" : "rooms"; })();
const ONE = LAYOUT === "one";''')

# 2) 툴바 버튼
rep('<button id="btnFollow" aria-pressed="true" hidden>🎥 자동 따라가기: 켜짐</button>',
    '<button id="btnFollow" aria-pressed="true" hidden>🎥 자동 따라가기: 켜짐</button>\n    <button id="btnLayout" hidden>🏢 사무실: 세션별</button>')
rep('setTimeout(followText, 0);',
'''setTimeout(followText, 0);
const btnLayout = $("#btnLayout");
btnLayout.textContent = "🏢 사무실: " + (ONE ? "한 곳에 모두" : "세션별");
btnLayout.title = ONE ? "세션마다 건물 하나로 바꾸기" : "모든 세션과 기여자를 한 사무실에 모으기";
btnLayout.addEventListener("click", () => {          // 바꾸면 새로 불러옴 (라이브 상태는 서버에서 다시 받음)
  const next = ONE ? "rooms" : "one";
  try { localStorage.setItem("ao.layout", next); } catch {}
  const u = new URL(location.href);
  if (u.searchParams.has("layout")){ u.searchParams.set("layout", next); location.replace(u.toString()); } else location.reload();
});''')
rep("  if (btnFollow.hidden === showFollow) btnFollow.hidden = !showFollow;",
    "  if (btnFollow.hidden === showFollow) btnFollow.hidden = !showFollow;\n  if (btnLayout.hidden === showFollow) btnLayout.hidden = !showFollow;")

# 3) 세션이 건물을 차지하지 않음
rep('''function slotSession(i){
  if (mode !== "live" || !live) return null;''',
'''function slotSession(i){
  if (mode !== "live" || !live || ONE) return null;''')
rep('''  for (const s of live.sessions.values()){ out.push(s.boss); for (const kt of s.kittens.values()) out.push(kt); }''',
'''  for (const s of live.sessions.values()){ out.push(s.boss); if (!ONE) for (const kt of s.kittens.values()) out.push(kt); }''')

# 4) one: 세션 입주 = 본사 책상 하나
rep('''function liveSession(rec){
  let s = live.sessions.get(rec.s);
  if (s) return s;''',
'''const hqSlot = () => team ? team.slot : 0;
function oneDesks(except){                       // one: 지금 쓰는 책상 (세션 고양이 + 출근한 사람)
  const used = new Set();
  for (const v of live.sessions.values()) if (v.boss !== except && v.boss.deskIdx != null && v.boss.deskIdx >= 0) used.add(v.boss.deskIdx);
  if (team) for (const m of team.members) if (m.present && m.cat && !m.leaving) used.add(m.cat.deskIdx);
  return used;
}
function oneSeatBoss(boss){                       // one: 대장 고양이를 본사 빈 책상에 앉힘 (없으면 사람 한 명이 자리를 비켜 줌)
  const H = hqSlot(), L = SLOTS[H];
  let used = oneDesks(boss), idx = -1;
  for (let i=0; i<MAX_DESKS; i++) if (!used.has(i)){ idx = i; break; }
  if (idx < 0 && team){
    const m = team.members.filter(x => x.present && !x.leaving && x.cat && talkSel.cat !== x.cat).sort((a, b) => b.rank - a.rank)[0];
    if (m){ idx = m.cat.deskIdx; m.leaveAt = 0; }
  }
  const seat = idx >= 0 ? lotSeat(L, idx) : lotLounge(L)[3];
  Object.assign(boss, {lot:H, router:lotRouter(L), deskIdx:idx, home:{...seat}, seat:{...seat}});
}
function liveSession(rec){
  let s = live.sessions.get(rec.s);
  if (s) return s;
  if (ONE) return liveSessionOne(rec);''')
rep('''  const boss = BOSSES[slot];
  Object.assign(boss, {q:[], cur:null, path:[], pos:{...boss.home}, seat:{...boss.home}, seatLift:7,''',
'''  const boss = BOSSES[slot];
  return newSession(rec, slot, boss, `${SLOTS[slot].name}에 입주 — ${rec.p} · ${rec.s}`);
}
function liveSessionOne(rec){
  const used = new Set([...live.sessions.values()].map(v => v.bossIdx));
  let bi = BOSSES.findIndex((_, i) => !used.has(i));
  if (bi < 0){                                   // 고양이가 다 일하는 중이면 가장 오래 조용한 세션이 퇴근
    let old = null;
    for (const v of live.sessions.values()) if (!old || v.lastMs < old.lastMs) old = v;
    live.sessions.delete(old.sid);
    if (old.card) old.card.el.remove();
    bi = old.bossIdx;
    log(`${sessName(old)} 퇴근 (자리 비움)`, null);
  }
  const boss = BOSSES[bi];
  oneSeatBoss(boss);
  const s = newSession(rec, hqSlot(), boss, `${SLOTS[hqSlot()].name}에 출근 — ${rec.p} · ${rec.s}`, true);
  s.bossIdx = bi;
  boss.pos = lotDoor(SLOTS[hqSlot()]);            // 문으로 들어와서 자리로
  return s;
}
function newSession(rec, slot, boss, msg, oneMode){
  Object.assign(boss, {q:[], cur:null, path:[], pos:{...boss.home}, seat:{...boss.home}, seatLift:7,''')
rep('''  live.sessions.set(rec.s, s); live.ver++;
  log(`${SLOTS[slot].name}에 입주 — ${rec.p} · ${rec.s}`, "good");
  say(boss, "입주했어요!", 2.4);
  return s;''',
'''  live.sessions.set(rec.s, s); live.ver++;
  log(msg, "good");
  say(boss, oneMode ? "출근했어요!" : "입주했어요!", 2.4);
  return s;''')
rep("  s = {sid:rec.s, proj:rec.p, slot, boss,", "  const s = {sid:rec.s, proj:rec.p, slot, boss,")
rep('''  const act = s ? (s.phase === "working" ? 1 : 0.4) : hq ? (cats.length ? 0.8 : 0.15) : 0;''',
    '''  const act = s ? (s.phase === "working" ? 1 : 0.4) : hq ? (cats.length || (ONE && live.sessions.size) ? 0.8 : 0.15)
            : ONE && i === hqSlot() && live && live.sessions.size ? 0.8 : 0;''')

# 5) 서브에이전트: one 에서는 보이지 않는 새끼냥 (상태 계산만)
rep('''  kt.roleSet = !!role; kt.busy = true;
  sess.kittens.set(key, kt); live.ver++;
  log(`${L.name}에 새끼냥 ${name} 출근 — ${kt.role}`, "good");''',
'''  kt.roleSet = !!role; kt.busy = true;
  if (ONE){ kt.hidden = true; kt.pos = {...kt.seat}; }
  sess.kittens.set(key, kt); live.ver++;
  log(ONE ? `${sessName(sess)}: 서브에이전트 ${name} 합류 — ${kt.role}` : `${L.name}에 새끼냥 ${name} 출근 — ${kt.role}`, "good");''')

# 6) 기다리는 자리: one 에서는 고양이마다 조금씩 비켜서
rep('''  b.waiting = true; b.inLounge = false; b.seat = lotWait(SLOTS[s.slot]); b.seatLift = 0; b.napAfter = 90;''',
'''  b.waiting = true; b.inLounge = false; b.seat = lotWait(SLOTS[s.slot]); b.seatLift = 0; b.napAfter = 90;
  if (ONE){ const i = s.bossIdx || 0; b.seat = {x: b.seat.x - 26 + (i % 3) * 13, y: b.seat.y - 8 - Math.floor(i / 3) * 12}; }''')

# 7) 사람: 세션 고양이 책상은 피해서 출근 / 본사는 0번
rep('''  const used = new Set(team.members.filter(x => x.present && x !== m).map(x => x.cat.deskIdx));
  let idx = -1;''',
'''  const used = new Set(team.members.filter(x => x.present && x !== m).map(x => x.cat.deskIdx));
  if (ONE && live) for (const v of live.sessions.values()) used.add(v.boss.deskIdx);
  let idx = -1;''')
rep('''    slot = !used.has(0) ? 0 : SLOTS.findIndex((_, i) => !used.has(i));''',
'''    slot = ONE || !used.has(0) ? 0 : SLOTS.findIndex((_, i) => !used.has(i));''')

# 8) 이름표: one 에서는 건물 위 세션 표 대신 고양이 머리 위에 세션 표
rep('''  for (const s of live.sessions.values()){
    if (cam.focus !== null && cam.focus !== s.slot) continue;
    const L = SLOTS[s.slot], look = phaseLook(s);
    const tx = SX(isoX(L.x + 78, L.y)), ty = SY(isoY(L.x + 78, L.y, WALL + 14)) - 6*dpr;''',
'''  if (ONE && !team && (cam.focus === null || cam.focus === 0) && live.sessions.size){
    const L = SLOTS[0], txt = `🐾 세션 ${live.sessions.size}개`;
    const tx = SX(isoX(L.x + 78, L.y)), ty = SY(isoY(L.x + 78, L.y, WALL + 14)) - 6*dpr;
    const w = ctx.measureText(txt).width + 18*dpr, hh = 20*dpr, bx = Math.max(4, Math.min(cv.width - w - 4, tx - w/2));
    if (ty >= hh){
      ctx.strokeStyle = TOD.ink; ctx.fillStyle = TOD.paper;
      ctx.beginPath(); ctx.roundRect(bx, ty - hh, w, hh, hh/2); ctx.fill(); ctx.stroke();
      ctx.fillStyle = TOD.ink; ctx.fillText(txt, bx + 9*dpr, ty - hh/2 + 0.5);
    }
  }
  for (const s of live.sessions.values()){
    if (cam.focus !== null && cam.focus !== s.slot) continue;
    const L = SLOTS[s.slot], look = phaseLook(s);
    if (ONE){ drawSessionTag(s, look, now); continue; }
    const tx = SX(isoX(L.x + 78, L.y)), ty = SY(isoY(L.x + 78, L.y, WALL + 14)) - 6*dpr;''')
rep('''/* 멀티 세션 데모: 서버 없이''',
'''function drawSessionTag(s, look, now){            // one: 고양이 머리 위 세션 표 (+ 완료 도장)
  const b = s.boss;                              // 발밑에 (머리 위 말풍선과 겹치지 않게)
  const x = SX(isoX(b.pos.x, b.pos.y)), y0 = SY(isoY(b.pos.x, b.pos.y, b.zBase || 0)) + 5*dpr;
  const n = [...s.kittens.values()].filter(k => !k.leaving).length;
  ctx.save();
  const big = cam.z > 1.6;
  ctx.font = `${Math.max(9, (big ? 11 : 9.5)*dpr)}px 'Gowun Dodum', sans-serif`; ctx.textBaseline = "middle"; ctx.lineWidth = 1.1*dpr;
  const txt = big ? `${look.icon} ${clip(sessName(s), 14)} · ${b.name}${n ? "  🐾" + n : ""}` : `${look.icon} ${clip(sessName(s), 10)}${n ? " 🐾" + n : ""}`;
  const w = ctx.measureText(txt).width + 14*dpr, hh = (big ? 18 : 15)*dpr, y = y0 + hh;
  if (y > hh){
    ctx.strokeStyle = TOD.ink; ctx.fillStyle = look.bg || TOD.paper;
    ctx.beginPath(); ctx.roundRect(x - w/2, y - hh, w, hh, hh/2); ctx.fill(); ctx.stroke();
    ctx.fillStyle = look.bg ? "#1f1d1b" : TOD.ink; ctx.textAlign = "center"; ctx.fillText(txt, x, y - hh/2 + 0.5);
  }
  if (s.stampUntil > now){
    const age = 3 - (s.stampUntil - now), sc = Math.min(1, age / 0.25) * (1 + Math.max(0, 0.25 - age) * 2) * 0.7;
    ctx.globalAlpha = Math.min(1, (s.stampUntil - now) / 0.6);
    ctx.translate(x, SY(isoY(b.pos.x, b.pos.y, 40))); ctx.rotate(-0.18); ctx.scale(sc, sc);
    ctx.strokeStyle = "#d6463f"; ctx.fillStyle = "rgba(255,255,255,.85)"; ctx.lineWidth = 3*dpr;
    ctx.beginPath(); ctx.roundRect(-46*dpr, -20*dpr, 92*dpr, 40*dpr, 10*dpr); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#d6463f"; ctx.font = `${24*dpr}px 'Jua', sans-serif`; ctx.textAlign = "center";
    ctx.fillText("완료!", 0, 1*dpr);
  }
  ctx.restore();
  ctx.font = `${Math.max(10, 11*dpr)}px 'Gowun Dodum', sans-serif`; ctx.textBaseline = "middle"; ctx.lineWidth = 1.3*dpr; ctx.textAlign = "left";
}

/* 멀티 세션 데모: 서버 없이''')

# 9) 오른쪽 목록: one 본사 = 세션 고양이 + 출근한 사람
rep('''    $("#agentsTitle").textContent = hq ? `${L.name} · 출근한 사람들` : `${L.name} · 고양이들`;
    if (hq){''',
'''    $("#agentsTitle").textContent = ONE && cam.focus === hqSlot() ? `${L.name} · 세션 고양이와 사람들`
                                  : hq ? `${L.name} · 출근한 사람들` : `${L.name} · 고양이들`;
    if (ONE && cam.focus === hqSlot()){
      liveRows = [...live.sessions.values()].map(v => ({c:v.boss, ...hudRow(v.boss.coat.base, `${v.boss.name} · ${sessName(v)}`,
                   `${phaseLook(v).text}${v.kittens.size ? " · 서브에이전트 " + v.kittens.size : ""}`)}));
      if (team) for (const m of team.members.filter(m => m.present))
        liveRows.push({c:m.cat, ...hudRow("#e8735f", m.info.name || "@" + m.login, TIER_LABEL[m.tier])});
      if (!liveRows.length){
        const p = document.createElement("p"); p.className = "hint"; p.style.margin = "0";
        p.textContent = "아직 아무도 없어요. 세션이 시작되면 고양이가, 기여자는 기여 정도에 따라 사람이 출근해요.";
        agentList.appendChild(p);
      }
    } else if (hq){''')
rep('''  $("#summaryEmpty").textContent = cam.focus !== null && team && team.slot === cam.focus ? `${team.repo} 기여자들의 사무실이에요. AI 세션은 다른 건물에서 일해요.`''',
'''  $("#summaryEmpty").textContent = ONE && cam.focus !== null && cam.focus !== hqSlot() ? "빈 건물이에요. 모두 한 사무실에서 일해요."
    : cam.focus !== null && team && team.slot === cam.focus && !ONE ? `${team.repo} 기여자들의 사무실이에요. AI 세션은 다른 건물에서 일해요.`''')

rep("""  const cats = hq ? team.members.filter(m => m.present).map(m => m.cat) : s ? [s.boss, ...s.kittens.values()] : null;""",
"""  const oneCats = ONE && live && i === hqSlot() ? [...live.sessions.values()].map(v => v.boss) : [];   // one: 세션 고양이도 본사에
  const cats = hq ? [...oneCats, ...team.members.filter(m => m.present).map(m => m.cat)] : s ? [s.boss, ...s.kittens.values()] : oneCats.length ? oneCats : null;""")
rep("""      if (a.lot !== cam.focus || a === talkSel.cat) continue;""",
    """      if (a.lot !== cam.focus || a === talkSel.cat || (ONE && !a.human)) continue;   // one: 고양이는 세션 표가 이름표 역할""")

open(app, "w").write(s)
print("ok")
