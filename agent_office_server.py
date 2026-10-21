#!/usr/bin/env python3
"""에이전트 오피스 라이브 서버.

로컬에서 돌아가는 Claude Code 세션들(~/.claude/projects/*.jsonl)과
서브에이전트 로그(<세션>/subagents/*.jsonl)를 감시해서
에이전트 오피스 페이지에 실시간으로 흘려보낸다. 표준 라이브러리만 사용.

페이지에서 세션의 "터미널로 이동 / 새 터미널에서 이어하기 / 폴더 열기"를 누르면
이 서버가 대신 실행한다 (내 PC 안에서만, 정해진 동작만).

사용법 — agent_office.html 과 같은 폴더에 두고:
    python3 agent_office_server.py        (맥/리눅스)
    py agent_office_server.py             (윈도우)
브라우저가 자동으로 열린다 (http://localhost:8765)

옵션:
    --dir PATH    감시할 로그 폴더 (기본: ~/.claude/projects)
    --port N      포트 (기본: 8765)
    --no-browser  브라우저 자동 열기 끄기
"""
import argparse
import collections
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ACTIVE_WINDOW = 6 * 3600      # 최근 6시간 내에 움직인 세션만 감시
BACKLOG_BYTES = 16 * 1024     # 처음 발견한 파일은 마지막 16KB만 소급
SYSTEM = platform.system()    # "Darwin" | "Windows" | "Linux"

events = collections.deque(maxlen=6000)
offsets = {}    # path -> 읽은 바이트 수
partial = {}    # path -> 줄바꿈 전 미완성 조각
meta = {}       # 세션 앞 8글자 -> {"id", "cwd", "started", "file"}
seq = 0
lock = threading.Lock()


def proj_label(dirname):
    """'-Users-me-StudioProjects-myapp' → 'myapp' (cwd를 못 읽었을 때만 쓰는 예비 이름)"""
    parts = [p for p in dirname.split("-") if p]
    return parts[-1] if parts else dirname


def parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def learn_meta(path, sess):
    """세션 파일 첫 줄들에서 전체 ID, 작업 폴더(cwd), 시작 시각을 읽어 둔다."""
    m = meta.setdefault(sess, {"id": os.path.basename(path)[:-6], "cwd": None, "started": None, "file": path})
    if m["cwd"] and m["started"]:
        return
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for _ in range(40):
                line = fh.readline()
                if not line:
                    break
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not m["cwd"] and o.get("cwd"):
                    m["cwd"] = o["cwd"]
                if not m["started"] and o.get("timestamp"):
                    m["started"] = parse_ts(o["timestamp"])
                if m["cwd"] and m["started"]:
                    break
    except OSError:
        pass


def tail(path, sess, proj, agent=None):
    """파일에서 새로 추가된 줄만 읽어 events 에 넣는다."""
    global seq
    try:
        st = os.stat(path)
    except OSError:
        return
    if time.time() - st.st_mtime > ACTIVE_WINDOW and path not in offsets:
        return
    if agent is None:
        learn_meta(path, sess)
    first = path not in offsets
    pos = offsets.get(path, max(0, st.st_size - BACKLOG_BYTES))
    if st.st_size < pos:              # 파일이 교체/축소됨
        pos, first = 0, True
        partial.pop(path, None)
    if st.st_size == pos:
        offsets[path] = pos
        return
    try:
        with open(path, "rb") as fh:
            fh.seek(pos)
            chunk = fh.read(st.st_size - pos)
    except OSError:
        return
    offsets[path] = pos + len(chunk)
    text = partial.pop(path, "") + chunk.decode("utf-8", "replace")
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()                   # 마지막 빈 조각
    else:
        partial[path] = lines.pop()
    if first and pos > 0 and lines:
        lines = lines[1:]             # 파일 중간부터 읽었으니 첫 조각은 버림
    for line in lines:
        line = line.strip()
        if not line:
            continue
        seq += 1
        ev = {"q": seq, "s": sess, "p": proj, "l": line}
        if agent:
            ev["a"] = agent
        events.append(ev)


def scan(root):
    """~/.claude/projects/<프로젝트>/<세션>.jsonl 과
    <세션>/subagents/<에이전트>.jsonl (서브에이전트 로그)을 함께 감시."""
    try:
        entries = os.listdir(root)
    except OSError:
        return
    for d in entries:
        pdir = os.path.join(root, d)
        if not os.path.isdir(pdir):
            continue
        proj = proj_label(d)
        try:
            names = os.listdir(pdir)
        except OSError:
            continue
        for f in names:
            full = os.path.join(pdir, f)
            if f.endswith(".jsonl"):
                tail(full, f[:8], proj)
            elif os.path.isdir(full):
                sub = os.path.join(full, "subagents")
                if not os.path.isdir(sub):
                    continue
                try:
                    subs = os.listdir(sub)
                except OSError:
                    continue
                for sf in subs:
                    if sf.endswith(".jsonl"):
                        tail(os.path.join(sub, sf), f[:8], proj, sf[:-6])


# ───────── 터미널 열기 ─────────

def run(cmd, timeout=6, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def same_dir(a, b):
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except (OSError, TypeError):
        return False


CLAUDE_RE = re.compile(r"(^|[\\/\s])claude(\.exe|\.cmd)?(\s|$)|claude-code", re.I)


def claude_processes():
    """실행 중인 Claude Code 프로세스 목록: [{pid, ppid, tty, start, args, cwd}]"""
    out = []
    if SYSTEM == "Windows":
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'claude' -and "
              "$_.Name -match '^(node|claude|bun)' } | ForEach-Object { [pscustomobject]@{ "
              "pid=$_.ProcessId; ppid=$_.ParentProcessId; args=$_.CommandLine; "
              "start=$_.CreationDate.ToUniversalTime().ToString('o') } } | ConvertTo-Json -Compress")
        raw = run(["powershell", "-NoProfile", "-Command", ps], timeout=12)
        try:
            data = json.loads(raw) if raw else []
        except ValueError:
            data = []
        if isinstance(data, dict):
            data = [data]
        for p in data:
            out.append({"pid": int(p["pid"]), "ppid": int(p["ppid"]), "tty": None,
                        "start": parse_ts(p.get("start")), "args": p.get("args") or "", "cwd": None})
        return out
    fmt = "pid=,ppid=,tty=,lstart=,command=" if SYSTEM == "Darwin" else "pid=,ppid=,tty=,lstart=,args="
    raw = run(["ps", "-axo" if SYSTEM == "Darwin" else "-eo", fmt])
    for line in raw.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        pid, ppid, tty = parts[0], parts[1], parts[2]
        args = parts[8]
        if not CLAUDE_RE.search(args) or "agent_office_server" in args:
            continue
        try:
            start = time.mktime(time.strptime(" ".join(parts[3:8]), "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            start = None
        cwd = None
        if SYSTEM == "Linux":
            try:
                cwd = os.readlink(f"/proc/{pid}/cwd")
            except OSError:
                pass
        else:
            for ln in run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"]).splitlines():
                if ln.startswith("n"):
                    cwd = ln[1:]
        out.append({"pid": int(pid), "ppid": int(ppid), "tty": None if tty in ("?", "??") else tty,
                    "start": start, "args": args, "cwd": cwd})
    return out


def find_process(m):
    """세션에 해당하는 프로세스를 고른다: 세션 ID가 명령줄에 있으면 확정,
    아니면 같은 폴더(cwd)에서 돌고 있는 것 중 시작 시각이 가장 가까운 것."""
    procs = claude_processes()
    for p in procs:
        if m["id"] in p["args"]:
            return p
    cands = [p for p in procs if p["cwd"] and m["cwd"] and same_dir(p["cwd"], m["cwd"])]
    if not cands and SYSTEM == "Windows":
        cands = procs            # 윈도우는 cwd를 못 읽으니 시작 시각으로만 고름
    if not cands:
        return None
    if m["started"]:
        cands.sort(key=lambda p: abs((p["start"] or 0) - m["started"]))
    return cands[0]


def osa(script):
    return run(["osascript", "-e", script], timeout=8)


def focus_mac(p, m):
    if p["tty"]:
        tty = "/dev/" + p["tty"]
        if re.fullmatch(r"/dev/tty[a-z]*\d+", tty):
            r = osa(f'''if application id "com.apple.Terminal" is running then
  tell application id "com.apple.Terminal"
    repeat with w in windows
      repeat with t in tabs of w
        if tty of t is "{tty}" then
          set selected tab of w to t
          set index of w to 1
          activate
          return "ok"
        end if
      end repeat
    end repeat
  end tell
end if
return "no"''')
            if r == "ok":
                return True, "Terminal에서 그 탭을 앞으로 가져왔어요."
            r = osa(f'''if application id "com.googlecode.iterm2" is running then
  tell application id "com.googlecode.iterm2"
    repeat with w in windows
      repeat with t in tabs of w
        repeat with s in sessions of t
          if tty of s is "{tty}" then
            tell w to select
            tell t to select
            tell s to select
            activate
            return "ok"
          end if
        end repeat
      end repeat
    end repeat
  end tell
end if
return "no"''')
            if r == "ok":
                return True, "iTerm에서 그 탭을 앞으로 가져왔어요."
    # 다른 앱(VS Code, Cursor, Warp 등) 안의 터미널이면 그 앱을 앞으로
    pid = p["pid"]
    for _ in range(12):
        info = run(["ps", "-o", "ppid=,comm=", "-p", str(pid)])
        if not info:
            break
        ppid, _, comm = info.strip().partition(" ")
        hit = re.search(r"(/[^\n]*?\.app)/", comm.strip())
        if hit:
            app = hit.group(1)
            name = os.path.basename(app)[:-4]
            if m["cwd"] and re.search(r"Code|Cursor|Windsurf|IntelliJ|Android Studio|PyCharm|WebStorm", name):
                run(["open", "-a", app, m["cwd"]])
            else:
                run(["open", "-a", app])
            return True, f"{name} 창을 앞으로 가져왔어요. (탭까지는 고를 수 없어요)"
        try:
            pid = int(ppid)
        except ValueError:
            break
        if pid <= 1:
            break
    return False, "터미널 창을 찾지 못했어요."


def focus_windows(p):
    ps = f'''
Add-Type -Namespace W -Name U -MemberDefinition '[DllImport("user32.dll")] public static extern bool ShowWindowAsync(System.IntPtr h, int n);'
$id = {int(p["pid"])}
for ($i = 0; $i -lt 10; $i++) {{
  $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
  if ($proc -and $proc.MainWindowHandle -ne 0) {{
    [W.U]::ShowWindowAsync($proc.MainWindowHandle, 9) | Out-Null
    (New-Object -ComObject WScript.Shell).AppActivate($proc.Id) | Out-Null
    "ok:" + $proc.ProcessName
    exit
  }}
  $c = Get-CimInstance Win32_Process -Filter "ProcessId=$id"
  if (-not $c) {{ break }}
  $id = $c.ParentProcessId
}}
"no"'''
    r = run(["powershell", "-NoProfile", "-Command", ps], timeout=12)
    if r.startswith("ok:"):
        return True, f"{r[3:]} 창을 앞으로 가져왔어요. (탭까지는 고를 수 없어요)"
    return False, "터미널 창을 찾지 못했어요."


def focus_linux(p):
    if not shutil.which("wmctrl"):
        return False, "리눅스에서는 wmctrl이 있어야 창을 가져올 수 있어요."
    wins = run(["wmctrl", "-lp"]).splitlines()
    pid = p["pid"]
    for _ in range(10):
        for w in wins:
            cols = w.split(None, 4)
            if len(cols) >= 3 and cols[2] == str(pid):
                run(["wmctrl", "-ia", cols[0]])
                return True, "터미널 창을 앞으로 가져왔어요."
        info = run(["ps", "-o", "ppid=", "-p", str(pid)])
        try:
            pid = int(info)
        except ValueError:
            break
        if pid <= 1:
            break
    return False, "터미널 창을 찾지 못했어요."


def do_focus(m):
    p = find_process(m)
    if not p:
        return False, "실행 중인 Claude Code를 찾지 못했어요. 세션이 끝났다면 '이어하기'를 눌러 주세요."
    if SYSTEM == "Darwin":
        return focus_mac(p, m)
    if SYSTEM == "Windows":
        return focus_windows(p)
    return focus_linux(p)


def do_resume(m):
    cwd, sid = m["cwd"], m["id"]
    if not (cwd and os.path.isdir(cwd)):
        return False, "세션의 작업 폴더를 찾지 못했어요."
    if SYSTEM == "Darwin":
        cmd = f"cd {shlex.quote(cwd)} && claude --resume {sid}"
        esc = cmd.replace("\\", "\\\\").replace('"', '\\"')
        osa(f'tell application id "com.apple.Terminal"\n do script "{esc}"\n activate\nend tell')
        return True, "Terminal 새 창에서 이 세션을 이어서 열었어요."
    if SYSTEM == "Windows":
        if shutil.which("wt"):
            subprocess.Popen(["wt", "-d", cwd, "cmd", "/k", "claude", "--resume", sid])
        else:
            subprocess.Popen(f'start "" /D "{cwd}" cmd /k claude --resume {sid}', shell=True)
        return True, "새 터미널에서 이 세션을 이어서 열었어요."
    for term, args in (("gnome-terminal", ["--working-directory", cwd, "--", "claude", "--resume", sid]),
                       ("konsole", ["--workdir", cwd, "-e", "claude", "--resume", sid]),
                       ("x-terminal-emulator", ["-e", "bash", "-lc", f"cd {shlex.quote(cwd)} && claude --resume {sid}"]),
                       ("xterm", ["-e", "bash", "-lc", f"cd {shlex.quote(cwd)} && claude --resume {sid}"])):
        if shutil.which(term):
            subprocess.Popen([term] + args)
            return True, "새 터미널에서 이 세션을 이어서 열었어요."
    return False, "열 수 있는 터미널 프로그램을 찾지 못했어요."


def do_folder(m):
    cwd = m["cwd"]
    if not (cwd and os.path.isdir(cwd)):
        return False, "세션의 작업 폴더를 찾지 못했어요."
    if SYSTEM == "Darwin":
        run(["open", cwd])
    elif SYSTEM == "Windows":
        os.startfile(cwd)  # noqa: 윈도우 전용
    else:
        subprocess.Popen(["xdg-open", cwd])
    return True, "작업 폴더를 열었어요."


ACTIONS = {"focus": do_focus, "resume": do_resume, "folder": do_folder}


class Handler(BaseHTTPRequestHandler):
    root = os.path.expanduser("~/.claude/projects")
    port = 8765

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _trusted(self):
        """이 페이지에서 보낸 요청만 받는다 (다른 웹사이트가 몰래 부르는 것 차단)."""
        okhosts = {f"localhost:{self.port}", f"127.0.0.1:{self.port}"}
        if self.headers.get("Host") not in okhosts:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{h}" for h in okhosts}:
            return False
        return self.headers.get("X-Agent-Office") == "1"

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            try:
                with open(os.path.join(HERE, "agent_office.html"), "rb") as fh:
                    body = fh.read()
            except OSError:
                self.send_error(404, "agent_office.html not found next to this script")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/ping":
            self._json({"ok": True, "dir": self.root, "os": SYSTEM, "open": True})
        elif u.path == "/api/events":
            with lock:
                scan(self.root)
                try:
                    since = int(parse_qs(u.query).get("since", ["0"])[0])
                except ValueError:
                    since = 0
                out = [e for e in events if e["q"] > since][:400]
                cur = seq
            self._json({"seq": cur, "events": out})
        else:
            self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/open":
            self.send_error(404)
            return
        if not self._trusted():
            self._json({"ok": False, "msg": "허용되지 않은 요청이에요."}, 403)
            return
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 4096)
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            req = {}
        sid, action = str(req.get("sid", "")), str(req.get("action", ""))
        with lock:
            m = dict(meta.get(sid) or {})
        if not m or action not in ACTIONS:
            self._json({"ok": False, "msg": "모르는 세션이나 동작이에요."}, 400)
            return
        if not re.fullmatch(r"[0-9A-Za-z-]{8,64}", m["id"]):
            self._json({"ok": False, "msg": "세션 ID 형식이 이상해요."}, 400)
            return
        try:
            ok, msg = ACTIONS[action](m)
        except Exception as e:  # 실패해도 서버는 계속 돈다
            ok, msg = False, f"실행 중 문제가 생겼어요: {e}"
        self._json({"ok": ok, "msg": msg})

    def log_message(self, *args):   # 요청 로그는 조용히
        pass


def main():
    ap = argparse.ArgumentParser(description="에이전트 오피스 라이브 서버")
    ap.add_argument("--dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    Handler.root = args.dir
    Handler.port = args.port
    if not os.path.isdir(args.dir):
        print(f"[!] 로그 폴더가 없어요: {args.dir}")
        print("    Claude Code를 이 PC에서 한 번이라도 실행했는지 확인해 주세요.")

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"에이전트 오피스 라이브 서버: {url}")
    print(f"감시 중: {args.dir}   (Ctrl+C 로 종료)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")


if __name__ == "__main__":
    main()
