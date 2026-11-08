"""서버: 내 캐릭터 꾸미기 — 본인 것만.
- 각자 설정은 '자기 GitHub 계정의 공개 gist(nyang-office.json)'에 둔다 → 그 계정 주인만 고칠 수 있음 (GitHub가 보장)
- 읽기: 팀 정보를 받을 때 상위 기여자들의 gist 에서 설정을 읽어 member.look 으로
- 쓰기: POST /api/me/look — 이 PC 의 gh 로그인 토큰 주인 계정에만 저장 (다른 사람 것은 구조적으로 못 씀)"""
import sys
p = sys.argv[1]
s = open(p).read()
def rep(a, b):
    global s
    assert a in s, a[:80]; s = s.replace(a, b, 1)

rep('''def fetch_team(repo):''', '''LOOK_FILE = "nyang-office.json"
LOOK_ARTS = {"wavy", "longglasses", "ponytail", "ponyglasses", "bunhood", "bob", "short", "fringe", "curly", "beanie"}
LOOK_COLORS = ("hair", "skin", "shirt", "pants", "inner", "hat")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def clean_look(d):
    """허용된 값만 남김 (종류 이름 + 색 #rrggbb)."""
    if not isinstance(d, dict):
        return None
    out = {}
    if d.get("art") in LOOK_ARTS:
        out["art"] = d["art"]
    for k in LOOK_COLORS:
        v = d.get(k)
        if isinstance(v, str) and HEX_RE.match(v):
            out[k] = v.lower()
    return out or None


def gh_send(method, path, body):
    req = urllib.request.Request("https://api.github.com" + path, method=method, data=json.dumps(body).encode(), headers={
        "Accept": "application/vnd.github+json", "User-Agent": "agent-office", "Content-Type": "application/json",
        "Authorization": "Bearer " + gh_token()})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"{}")


def find_look_gist(login):
    """그 사람 공개 gist 중 nyang-office.json 이 든 것 (없으면 None)."""
    for g in gh_get(f"/users/{login}/gists?per_page=50") or []:
        f = (g.get("files") or {}).get(LOOK_FILE)
        if f:
            return g, f
    return None


def fetch_look(login):
    hit = find_look_gist(login)
    if not hit:
        return None
    _, f = hit
    raw = f.get("raw_url") or ""
    if not raw.startswith("https://gist.githubusercontent.com/"):
        return None
    with urllib.request.urlopen(urllib.request.Request(raw, headers={"User-Agent": "agent-office"}), timeout=10) as r:
        text = r.read(4096)
    try:
        return clean_look(json.loads(text))
    except ValueError:
        return None


_me = {"at": 0, "login": None}
def gh_me():
    """이 PC 의 gh 로그인 계정 (10분 캐시). 토큰이 없으면 None."""
    if not gh_token():
        return None
    if time.time() - _me["at"] > 600:
        try:
            _me["login"] = (gh_get("/user") or {}).get("login")
        except Exception:
            _me["login"] = None
        _me["at"] = time.time()
    return _me["login"]


def save_my_look(look):
    me = gh_me()
    if not me:
        return False, "GitHub 로그인이 필요해요. 터미널에서 gh auth login 을 먼저 해 주세요.", None
    content = json.dumps(dict(look, by="냥오피스"), ensure_ascii=False, indent=1)
    try:
        hit = find_look_gist(me)
        if hit:
            g = gh_send("PATCH", f"/gists/{hit[0]['id']}", {"files": {LOOK_FILE: {"content": content}}})
        else:
            g = gh_send("POST", "/gists", {"public": True, "description": "냥오피스 내 캐릭터 설정",
                                           "files": {LOOK_FILE: {"content": content}}})
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return False, "gist 를 쓸 권한이 없어요. 터미널에서 gh auth refresh -s gist 를 실행한 뒤 다시 저장해 주세요.", None
        return False, f"저장하지 못했어요 (GitHub {e.code}).", None
    except Exception as e:
        return False, f"저장하지 못했어요: {e}", None
    for c in team_cache.values():               # 받아 둔 팀 정보에도 바로 반영
        for m in (c.get("data") or {}).get("members", []):
            if m.get("login") == me:
                m["look"] = look
    return True, "저장했어요. 이 저장소를 보는 다른 사람 화면에도 다음 갱신 때 반영돼요.", g.get("html_url")


def fetch_team(repo):''')
rep('''    for m in members[:12]:                      # 자기소개용 프로필 (상위 12명만, 한도 아끼기)
        try:
            u = gh_get(f"/users/{m['login']}")
        except Exception:
            break
        for k in ("name", "bio", "company", "location"):
            m[k] = (u.get(k) or "").strip()[:160]''',
'''    for m in members[:12]:                      # 자기소개용 프로필 (상위 12명만, 한도 아끼기)
        try:
            u = gh_get(f"/users/{m['login']}")
        except Exception:
            break
        for k in ("name", "bio", "company", "location"):
            m[k] = (u.get(k) or "").strip()[:160]
        try:                                    # 본인이 자기 gist 에 정한 캐릭터 (있으면)
            lk = fetch_look(m["login"])
            if lk:
                m["look"] = lk
        except Exception:
            pass''')
rep('''        elif u.path == "/api/ping":''', '''        elif u.path == "/api/me":
            self._json({"login": gh_me()})
        elif u.path == "/api/ping":''')
rep('''    def do_POST(self):
        if urlparse(self.path).path != "/api/open":''', '''    def do_POST(self):
        if urlparse(self.path).path == "/api/me/look":
            if not self._trusted():
                self._json({"ok": False, "msg": "허용되지 않은 요청이에요."}, 403)
                return
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 4096)
                look = clean_look(json.loads(self.rfile.read(n) or b"{}").get("look"))
            except (ValueError, AttributeError):
                look = None
            if not look:
                self._json({"ok": False, "msg": "저장할 내용이 비었어요."}, 400)
                return
            ok, msg, url = save_my_look(look)
            self._json({"ok": ok, "msg": msg, "url": url, "look": look})
            return
        if urlparse(self.path).path != "/api/open":''')
open(p, "w").write(s)
print("ok")
