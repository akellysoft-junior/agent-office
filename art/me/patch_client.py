"""앱: 내 캐릭터 꾸미기 (본인 캐릭터에만 버튼).
- '나' = 이 PC 의 gh 로그인 계정 (/api/me). 데모에서는 첫 번째 사람을 나로 가정하고 저장은 안 함
- 대화창에서 내 캐릭터일 때만 '내 캐릭터 꾸미기' → 종류·색 고르기, 바로 미리 보기, 저장 = 내 gist
- 다른 사람 설정은 팀 정보(member.look)로 받아 그대로 반영"""
import sys
p = sys.argv[1]
s = open(p).read()
def rep(a, b):
    global s
    assert a in s, a[:80]; s = s.replace(a, b, 1)

# 1) 팀 정보의 look 반영
rep('''    if (prev) return Object.assign(prev, {info:d, rank, tier});''',
'''    if (prev){ if (d.look) Object.assign(prev.look, d.look); return Object.assign(prev, {info:d, rank, tier}); }''')
rep('''            coat:coats[h % coats.length], look:personLook(d.login)};''',
    '''            coat:coats[h % coats.length], look:{...personLook(d.login), ...(d.look || {})}};   // 본인이 gist 에 정한 모습이 있으면 그걸로''')
rep('''function humanArt(a){
  const L = a.look || {}, h = hashStr(String(a.id || a.name || ""));''',
'''function humanArt(a){
  const L = a.look || {}, h = hashStr(String(a.id || a.name || ""));
  if (L.art && CHAR_ART["human." + L.art]) return L.art;          // 본인이 고른 종류''')
rep('''    inner: INNER_COLORS[(hashStr(String(a.id || a.name || "")) >>> 3) % INNER_COLORS.length]} : null; }''',
    '''    inner: L.inner || INNER_COLORS[(hashStr(String(a.id || a.name || "")) >>> 3) % INNER_COLORS.length]} : null; }''')

# 2) 마크업·스타일
rep('''<div class="zoomctl" id="zoomCtl" hidden>''',
'''<div class="picker" id="picker" role="dialog" aria-label="내 캐릭터 꾸미기" hidden><div class="pk-head"><b>내 캐릭터 꾸미기</b><span id="pkWho"></span></div><div class="pk-main"><canvas id="pkCv" width="160" height="220"></canvas><div class="pk-opts" id="pkOpts"></div></div><p class="pk-note" id="pkNote"></p><div class="pk-actions"><button type="button" id="pkCancel" class="mini">취소</button><button type="button" id="pkSave" class="mini primary">저장</button></div></div><div class="zoomctl" id="zoomCtl" hidden>''')
rep('''.talk-close{''', '''.picker{position:absolute; right:14px; top:14px; z-index:4; width:min(380px, calc(100% - 28px)); max-height:calc(100% - 28px); overflow:auto;
  background:var(--paper); color:var(--ink); border:2px solid var(--ink); border-radius:14px; box-shadow:4px 4px 0 var(--ink); padding:12px 14px;
  display:flex; flex-direction:column; gap:8px; animation:pop .25s ease-out}
.pk-head{display:flex; align-items:baseline; gap:8px}
.pk-head b{font-family:var(--font-display); font-weight:400; font-size:17px}
.pk-head span{font-size:12px; color:var(--muted)}
.pk-main{display:flex; gap:10px; align-items:flex-start}
.pk-main canvas{flex:none; width:96px; height:132px; border:1.5px solid var(--ink); border-radius:10px; background:var(--paper-2)}
.pk-opts{flex:1 1 auto; min-width:0; display:flex; flex-direction:column; gap:6px}
.pk-row{display:flex; flex-direction:column; gap:3px}
.pk-row > span{font-size:11px; color:var(--muted)}
.pk-chips{display:flex; flex-wrap:wrap; gap:4px}
.pk-chips button{font-size:11px; padding:2px 7px; border-radius:999px; box-shadow:none}
.pk-chips button[aria-pressed="true"]{background:var(--ink); color:var(--paper)}
.pk-chips .sw{width:20px; height:20px; padding:0; border-radius:50%; border:1.5px solid var(--ink)}
.pk-chips .sw[aria-pressed="true"]{outline:2px solid var(--accent); outline-offset:1px}
.pk-note{margin:0; font-size:12px; color:var(--muted); line-height:1.5}
.pk-actions{display:flex; justify-content:flex-end; gap:6px}
@media (max-width:560px){ .picker{left:8px; right:8px; top:8px; width:auto} }
.talk-close{''')

# 3) '나' 와 꾸미기 창
rep('''/* ── 캐릭터 클릭 → 확대 + 자기소개 대화창 ── */''',
'''/* ── 내 캐릭터 꾸미기: 본인 캐릭터에만. 저장은 내 GitHub 계정의 gist (그 계정 주인만 고칠 수 있음) ── */
let me = null;                                  // {login, demo}
async function loadMe(){
  if (!live) return;
  if (live.source === "server"){
    try { const r = await fetch("api/me", {cache:"no-store"}); const d = await r.json(); me = d.login ? {login:d.login} : null; } catch { me = null; }
  } else if (live.source === "demo") me = team && team.members[0] ? {login:team.members[0].login, demo:true} : null;
}
const ART_LABEL = {wavy:"웨이브·가디건", longglasses:"긴머리·안경·후드", ponytail:"포니테일", ponyglasses:"포니테일·안경·니트",
  bunhood:"똥머리·후드", bob:"단발", short:"짧은 머리·니트", fringe:"앞머리·후드", curly:"곱슬·가디건", beanie:"비니"};
const picker = {box:$("#picker"), cv:$("#pkCv"), opts:$("#pkOpts"), note:$("#pkNote"), who:$("#pkWho"), m:null, before:null};
function openPicker(m){
  picker.m = m; picker.before = {...m.look};
  if (!m.look.art) m.look.art = humanArt(m.cat || {look:m.look, id:"gh-" + m.login});
  picker.who.textContent = "@" + m.login;
  picker.note.textContent = me && me.demo ? "데모에서는 첫 번째 사람을 '나'로 가정해요. 저장은 되지 않아요."
    : "저장하면 내 GitHub 계정에 공개 gist(nyang-office.json)로 남아요. 내 계정이라 나만 고칠 수 있어요.";
  const O = picker.opts; O.textContent = "";
  const row = (label, items, key, swatch) => {
    const r = document.createElement("div"); r.className = "pk-row";
    const t = document.createElement("span"); t.textContent = label; r.appendChild(t);
    const c = document.createElement("div"); c.className = "pk-chips"; r.appendChild(c);
    for (const [val, text] of items){
      const b = document.createElement("button"); b.type = "button";
      if (swatch){ b.className = "sw"; b.style.background = val; b.title = val; b.setAttribute("aria-label", `${label} ${val}`); }
      else b.textContent = text;
      b.setAttribute("aria-pressed", String(m.look[key] === val));
      b.addEventListener("click", () => {
        m.look[key] = val; [...c.children].forEach(x => x.setAttribute("aria-pressed", String(x === b)));
        drawPickerPreview();
      });
      c.appendChild(b);
    }
    O.appendChild(r);
  };
  row("모양", Object.keys(ART_LABEL).filter(k => CHAR_ART["human." + k]).map(k => [k, ART_LABEL[k]]), "art");
  row("머리색", HAIRS.map(c => [c]), "hair", true);
  row("피부", SKINS.map(c => [c]), "skin", true);
  row("상의", ACC_COLORS.map(c => [c]), "shirt", true);
  row("안에 입은 옷", INNER_COLORS.map(c => [c]), "inner", true);
  row("바지", PANTS.map(c => [c]), "pants", true);
  row("모자", ACC_COLORS.map(c => [c]), "hat", true);
  picker.box.hidden = false;
  drawPickerPreview();
}
function drawPickerPreview(){
  const m = picker.m; if (!m || !charArt.ready) return;
  const fake = {human:m, look:m.look, id:"gh-" + m.login};
  const kind = artKind("human", fake), img = artLevelsFor(kind, fake)[0];
  const p = picker.cv.getContext("2d"), W = picker.cv.width, H = picker.cv.height;
  p.setTransform(1, 0, 0, 1, 0, 0); p.clearRect(0, 0, W, H);
  const sc = Math.min((W - 16) / img.width, (H - 16) / img.height);
  p.imageSmoothingEnabled = true; p.imageSmoothingQuality = "high";
  p.drawImage(img, (W - img.width * sc) / 2, H - 8 - img.height * sc, img.width * sc, img.height * sc);
}
function closePicker(restore){
  if (!picker.m) return;
  if (restore) Object.keys(picker.m.look).forEach(k => delete picker.m.look[k]), Object.assign(picker.m.look, picker.before);
  picker.m = null; picker.box.hidden = true;
}
$("#pkCancel").addEventListener("click", () => closePicker(true));
$("#pkSave").addEventListener("click", async () => {
  const m = picker.m; if (!m) return;
  if (!me || me.demo){ picker.note.textContent = "데모라서 저장하지 않았어요. 이 화면에서만 바뀐 모습이 보여요."; return; }
  const look = {art:m.look.art, hair:m.look.hair, skin:m.look.skin, shirt:m.look.shirt, pants:m.look.pants, inner:m.look.inner, hat:m.look.hat};
  picker.note.textContent = "저장하는 중…";
  try {
    const r = await fetch("api/me/look", {method:"POST", headers:{"Content-Type":"application/json", "X-Agent-Office":"1"}, body:JSON.stringify({look})});
    const d = await r.json();
    picker.note.textContent = d.msg || (d.ok ? "저장했어요." : "저장하지 못했어요.");
    if (d.ok){ picker.before = {...m.look}; setTimeout(() => closePicker(false), 1600); }
  } catch { picker.note.textContent = "서버에 연결하지 못했어요."; }
});
picker.box.addEventListener("pointerdown", e => e.stopPropagation());

/* ── 캐릭터 클릭 → 확대 + 자기소개 대화창 ── */''')
rep('''  if (info.session) talkButton("이어하기 명령 복사", () => openAction(info.session, "copy", talk.msg));''',
'''  if (info.session) talkButton("이어하기 명령 복사", () => openAction(info.session, "copy", talk.msg));
  if (c.human && me && c.human.login === me.login) talkButton("내 캐릭터 꾸미기", () => openPicker(c.human));   // 본인 캐릭터에만''')
rep('''    else if (!refresh) log(`🐙 ${team.repo} 팀 ${team.members.length}명이 ${SLOTS[team.slot].name}에 등록됐어요`, "good");''',
'''    else if (!refresh) log(`🐙 ${team.repo} 팀 ${team.members.length}명이 ${SLOTS[team.slot].name}에 등록됐어요`, "good");
    if (team && !refresh) loadMe();''')
open(p, "w").write(s)
print("ok")
