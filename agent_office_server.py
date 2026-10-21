#!/usr/bin/env python3
"""에이전트 오피스 라이브 서버.

로컬에서 돌아가는 Claude Code 세션들(~/.claude/projects/*.jsonl)과
서브에이전트 로그(<세션>/subagents/*.jsonl)를 감시해서
에이전트 오피스 페이지에 실시간으로 흘려보낸다. 표준 라이브러리만 사용.

페이지에서 세션의 "터미널로 이동 / 새 터미널에서 이어하기 / 폴더 열기"를 누르면
이 서버가 대신 실행한다 (내 PC 안에서만, 정해진 동작만).

Chrome·Edge에서 주소창의 "앱 설치"를 누르면 독립된 앱 창으로 쓸 수 있다 (웹앱).

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
import base64
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


# ── 리눅스: 환경마다 되는 방법이 달라서 차례로 시도한다 ──
#   1) tmux 안이면 그 창·패널로 전환   (설치 불필요, X11·Wayland 모두)
#   2) kitty / WezTerm 이면 터미널 자체 원격 기능으로   (Wayland도 가능)
#   3) GNOME + "Window Calls" 확장이면 D-Bus로 창 활성화   (Wayland도 가능)
#   4) X11 이면 xdotool 또는 wmctrl
#   5) 다 안 되면 이 환경에서 무엇이 필요한지 알려줌

def proc_env(pid):
    try:
        with open(f"/proc/{pid}/environ", "rb") as fh:
            data = fh.read().decode("utf-8", "replace")
        return dict(x.split("=", 1) for x in data.split("\0") if "=" in x)
    except OSError:
        return {}


def proc_ppid(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            s = fh.read()
        return int(s[s.rindex(")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def ancestors(pid, limit=15):
    chain = []
    while pid > 1 and len(chain) < limit:
        chain.append(pid)
        pid = proc_ppid(pid)
    return chain


def linux_session():
    """('x11'|'wayland'|'', 데스크톱 이름)"""
    st = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if not st:
        st = "wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11" if os.environ.get("DISPLAY") else ""
    return st, os.environ.get("XDG_CURRENT_DESKTOP", "")


def run_ok(cmd, timeout=6, env=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def gnome_window_calls():
    """GNOME 'Window Calls' 확장이 있으면 창 목록을 돌려준다. 없으면 None."""
    if not shutil.which("gdbus"):
        return None
    out = run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell",
               "--object-path", "/org/gnome/Shell/Extensions/Windows",
               "--method", "org.gnome.Shell.Extensions.Windows.List"])
    m = re.match(r"\('(.*)',\)\s*$", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace("\\'", "'"))
    except ValueError:
        return None


def linux_hint():
    st, de = linux_session()
    if st == "wayland" and "GNOME" in de.upper():
        return ("GNOME(Wayland)에서는 'Window Calls' 확장을 설치하면 터미널 창을 가져올 수 있어요 "
                "(extensions.gnome.org에서 Window Calls 검색). tmux 안에서 claude를 쓰면 설치 없이도 돼요.")
    if st == "wayland":
        return (f"{de or '이 데스크톱'}(Wayland)에서는 바깥 프로그램이 창을 앞으로 가져올 수 없어요. "
                "tmux·kitty·WezTerm 안에서 claude를 쓰면 돼요. 지금은 '이어하기'를 써 주세요.")
    if st == "x11":
        return "X11에서는 wmctrl이나 xdotool이 있으면 돼요: sudo apt install wmctrl  (서버를 켤 때 설치를 물어봐요)"
    return "화면 세션(DISPLAY)을 찾지 못했어요. 데스크톱에서 연 터미널로 서버를 켜 주세요."


def raise_window(chain):
    pids = list(chain)
    wins = gnome_window_calls()
    if wins:
        for pid in pids:
            for w in wins:
                if w.get("pid") == pid:
                    run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell",
                         "--object-path", "/org/gnome/Shell/Extensions/Windows",
                         "--method", "org.gnome.Shell.Extensions.Windows.Activate", str(w.get("id"))])
                    return True, "터미널 창을 앞으로 가져왔어요."
    st, _ = linux_session()
    if st != "wayland":
        if shutil.which("xdotool"):
            for pid in pids:
                ids = run(["xdotool", "search", "--pid", str(pid)]).split()
                if ids:
                    run(["xdotool", "windowactivate", ids[-1]])
                    return True, "터미널 창을 앞으로 가져왔어요."
        if shutil.which("wmctrl"):
            wl = run(["wmctrl", "-lp"]).splitlines()
            for pid in pids:
                for w in wl:
                    cols = w.split(None, 4)
                    if len(cols) >= 3 and cols[2] == str(pid):
                        run(["wmctrl", "-ia", cols[0]])
                        return True, "터미널 창을 앞으로 가져왔어요."
    return False, linux_hint()


def focus_linux(p):
    pid = p["pid"]
    env = proc_env(pid)
    chain = ancestors(pid)
    picked = ""
    # 1) tmux: 그 세션이 있는 창·패널로 전환 (터미널 창은 그다음에 앞으로)
    if env.get("TMUX_PANE") and shutil.which("tmux"):
        sock = env.get("TMUX", "").split(",")[0]
        base = ["tmux"] + (["-S", sock] if sock else [])
        if run_ok(base + ["select-window", "-t", env["TMUX_PANE"]]):
            run_ok(base + ["select-pane", "-t", env["TMUX_PANE"]])
            picked = "tmux에서 그 창을 골랐어요"
            clients = run(base + ["list-clients", "-F", "#{client_pid}"]).split()
            if clients and clients[0].isdigit():
                chain = ancestors(int(clients[0]))
    # 2) kitty (원격 제어가 켜져 있을 때)
    if env.get("KITTY_WINDOW_ID") and env.get("KITTY_LISTEN_ON") and shutil.which("kitty"):
        if run_ok(["kitty", "@", "--to", env["KITTY_LISTEN_ON"], "focus-window",
                   "--match", "id:" + env["KITTY_WINDOW_ID"]]):
            return True, "kitty에서 그 창을 앞으로 가져왔어요."
    # 3) WezTerm
    if env.get("WEZTERM_PANE") and shutil.which("wezterm"):
        e2 = dict(os.environ)
        if env.get("WEZTERM_UNIX_SOCKET"):
            e2["WEZTERM_UNIX_SOCKET"] = env["WEZTERM_UNIX_SOCKET"]
        if run_ok(["wezterm", "cli", "activate-pane", "--pane-id", env["WEZTERM_PANE"]], env=e2):
            return True, "WezTerm에서 그 패널을 앞으로 가져왔어요."
    # 4) 창 자체를 앞으로
    ok, msg = raise_window(chain)
    if ok:
        return True, (picked + "고, " + msg) if picked else msg
    if picked:
        return True, picked + ". 터미널 창은 직접 눌러 주세요. (" + msg + ")"
    return False, msg


def linux_setup_check():
    """서버를 켤 때 한 번: 이 리눅스에서 '터미널로 이동'이 되는지 알려주고, X11인데 도구가 없으면 설치를 제안."""
    st, de = linux_session()
    has_x = shutil.which("wmctrl") or shutil.which("xdotool")
    gnome_ok = gnome_window_calls() is not None
    label = f"{de or '알 수 없는 데스크톱'} · {st or '세션 없음'}"
    if gnome_ok or (st == "x11" and has_x):
        print(f"터미널로 이동: 준비됨 ({label})")
        return
    print(f"터미널로 이동: {linux_hint()}  [{label}]")
    print("    tmux · kitty · WezTerm 안에서 claude를 쓰는 경우는 따로 설치하지 않아도 돼요.")
    if st != "x11":
        return
    marker = os.path.join(HERE, ".agent_office_setup")
    if os.path.exists(marker) or not (os.isatty(0) and os.isatty(1)):
        return
    pm = next(((name, cmd) for name, cmd in (
        ("apt-get", ["sudo", "apt-get", "install", "-y", "wmctrl"]),
        ("dnf", ["sudo", "dnf", "install", "-y", "wmctrl"]),
        ("pacman", ["sudo", "pacman", "-S", "--noconfirm", "wmctrl"]),
        ("zypper", ["sudo", "zypper", "install", "-y", "wmctrl"]),
    ) if shutil.which(name)), None)
    if not pm:
        return
    try:
        ans = input(f"    wmctrl을 지금 설치할까요? ({' '.join(pm[1])}) [y/N] ").strip().lower()
    except EOFError:
        ans = ""
    if ans in ("y", "yes", "ㅛ"):
        r = subprocess.run(pm[1])
        print("    설치했어요." if r.returncode == 0 else "    설치하지 못했어요. 위 메시지를 확인해 주세요.")
    else:
        print("    건너뛸게요. 다음부터는 묻지 않아요. (다시 물어보려면 .agent_office_setup 파일을 지우세요)")
    try:
        with open(marker, "w") as fh:
            fh.write(ans or "n")
    except OSError:
        pass


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


# ───────── 웹앱(PWA): 앱 설치용 manifest · service worker · 아이콘 ─────────

MANIFEST = {
    "name": "Agent Office",
    "short_name": "냥오피스",
    "description": "Claude Code 세션을 고양이 동네 사무실로 보는 실시간 뷰",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#fcf7ee",
    "theme_color": "#fcf7ee",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

# 화면은 항상 최신(네트워크 우선)으로 받고, 서버가 꺼져 있을 때만 저장해 둔 화면을 띄운다.
SW_JS = """
const CACHE = "agent-office-v1";
const SHELL = ["/", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/")) return;
  e.respondWith(
    fetch(e.request)
      .then(r => { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); return r; })
      .catch(() => caches.match(e.request).then(r => r || caches.match("/")))
  );
});
"""

ICONS_B64 = {
    "/icon-192.png": (
    "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"
    ),
    "/icon-512.png": (
    "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"
    ),
    "/apple-touch-icon.png": (
    "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"
    "AAZJREFUAwDhnEHDx6fh6QAAAABJRU5ErkJggg=="
    ),
}
ICONS = {k: base64.b64decode(v) for k, v in ICONS_B64.items()}


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

    def _raw(self, body, ctype, extra=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {"Cache-Control": "no-cache"}).items():
            self.send_header(k, v)
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
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/manifest.webmanifest":
            self._raw(json.dumps(MANIFEST, ensure_ascii=False).encode(), "application/manifest+json")
        elif u.path == "/sw.js":
            self._raw(SW_JS.encode(), "text/javascript; charset=utf-8", {"Service-Worker-Allowed": "/"})
        elif u.path in ICONS or u.path == "/favicon.ico":
            self._raw(ICONS.get(u.path, ICONS["/icon-192.png"]), "image/png", {"Cache-Control": "max-age=86400"})
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

    if SYSTEM == "Linux":
        linux_setup_check()

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
