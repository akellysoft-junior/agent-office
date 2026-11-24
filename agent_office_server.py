#!/usr/bin/env python3
"""에이전트 오피스 라이브 서버.

로컬에서 돌아가는 Claude Code 세션들(~/.claude/projects/*.jsonl)과
서브에이전트 로그(<세션>/subagents/*.jsonl), Codex 세션(~/.codex/sessions)을 감시해서
에이전트 오피스 페이지에 실시간으로 흘려보낸다. 표준 라이브러리만 사용.

페이지에서 세션의 "터미널로 이동 / 새 터미널에서 이어하기 / 폴더 열기"를 누르면
이 서버가 대신 실행한다 (내 PC 안에서만, 정해진 동작만).

Chrome·Edge에서 주소창의 "앱 설치"를 누르면 독립된 앱 창으로 쓸 수 있다 (웹앱).

사용법 — agent_office.html 과 같은 폴더에 두고:
    python3 agent_office_server.py        (맥/리눅스)
    py agent_office_server.py             (윈도우)
이미 열린 창이 있으면 그 창이 다시 연결되고, 없으면 설치한 앱(없으면 브라우저)을 연다.

한 번만 하면 되는 설정:
    python3 agent_office_server.py --install     로그인할 때 서버 자동 시작 (지금도 켬)
    python3 agent_office_server.py --uninstall   자동 시작 해제
git 저장소에서 실행하면 시작할 때와 3시간마다 새 버전을 받아 온다 (고친 파일이 있으면 건너뜀).

옵션:
    --dir PATH    감시할 로그 폴더 (기본: ~/.claude/projects)
    --port N      포트 (기본: 8765)
    --no-browser  창 자동 열기 끄기
    --no-update   자동 업데이트 끄기
    --no-codex    Codex 세션(~/.codex/sessions)은 보여주지 않기 (기본: 함께 보여줌)
    --github-host HOST  회사 깃허브(GitHub Enterprise Server) 주소 (예: github.company.net)
"""
import argparse
import atexit
import base64
import calendar
import collections
import hashlib
import json
import os
import platform
import re
import signal
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ACTIVE_WINDOW = 24 * 3600     # 최근 하루 안에 움직인 세션만 감시 (화면도 하루 넘게 조용한 세션은 뺌)
BACKLOG_BYTES = 16 * 1024     # 처음 발견한 파일은 마지막 16KB만 소급
SYSTEM = platform.system()    # "Darwin" | "Windows" | "Linux"

events = collections.deque(maxlen=6000)
offsets = {}    # path -> 읽은 바이트 수
partial = {}    # path -> 줄바꿈 전 미완성 조각
meta = {}       # 세션 앞 8글자 -> {"id", "cwd", "started", "file"}
seq = 0
lock = threading.Lock()
last_client = 0.0              # 페이지가 마지막으로 서버에 연결한 시각
BOOT_ID = uuid.uuid4().hex[:8] # 서버가 다시 켜졌는지 페이지가 알아차리게
_code_watch = {"hash": None, "at": 0.0, "on": False}   # 서버 코드가 디스크에서 바뀌었는지 (git pull 등) 지켜봄


def html_version():
    try:
        return int(os.stat(os.path.join(HERE, "agent_office.html")).st_mtime)
    except OSError:
        return 0


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


def tail(path, sess, proj, agent=None, conv=None, src=None):
    """파일에서 새로 추가된 줄만 읽어 events 에 넣는다.
    conv: 다른 도구(Codex 등)의 로그 한 줄을 Claude 형식 줄 목록으로 바꾸는 함수, src: 그 도구 이름."""
    global seq
    try:
        st = os.stat(path)
    except OSError:
        return
    if time.time() - st.st_mtime > ACTIVE_WINDOW and path not in offsets and path not in force_paths:
        return                        # 하루 넘게 조용한 파일은 건너뜀 (프로세스가 살아 있는 세션은 예외)
    if agent is None and conv is None:
        learn_meta(path, sess)
    if agent is None:
        usage_track(path, sess, "codex" if src == "codex" else "main")
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
        outs = [line]
        if conv:
            try:
                outs = [json.dumps(o, ensure_ascii=False) for o in conv(json.loads(line), sess)]
            except ValueError:
                outs = []
        for out in outs:
            seq += 1
            ev = {"q": seq, "s": sess, "p": proj, "l": out}
            if agent:
                ev["a"] = agent
            if src:
                ev["src"] = src
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


# ───────── Codex 세션: ~/.codex/sessions/연/월/일/rollout-<시각>-<세션ID>.jsonl ─────────
# 줄마다 Claude Code 로그 형식으로 바꿔 같은 흐름에 넣는다 (페이지는 Claude 로그처럼 읽음).
CODEX_ROOT = os.path.expanduser("~/.codex/sessions")
CODEX_ON = True                # --no-codex 로 끔
CODEX_SHELL = {"shell", "exec_command", "local_shell", "container.exec", "shell_command"}
CODEX_STATUS = {"pending": "pending", "in_progress": "in_progress", "completed": "completed"}


def codex_sid(path):
    """rollout-...-<UUID>.jsonl → 'cx' + UUID 끝 6글자 (UUIDv7 앞부분은 시각이라 겹칠 수 있음)."""
    stem = os.path.basename(path)[:-6]
    return "cx" + re.sub(r"[^0-9a-f]", "", stem.lower())[-6:]


def codex_learn(path, sess):
    """첫 줄(session_meta)에서 세션 ID·작업 폴더·시작 시각을 읽어 둔다."""
    m = meta.get(sess)
    if m and m.get("cwd"):
        return m
    m = meta.setdefault(sess, {"id": os.path.basename(path)[-42:-6], "cwd": None, "started": None, "file": path, "src": "codex"})
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for _ in range(5):
                line = fh.readline()
                if not line:
                    break
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                p = o.get("payload") or {}
                if o.get("type") == "session_meta":
                    m["id"] = p.get("id") or m["id"]
                    m["app"] = str(p.get("originator") or "")       # codex_work_desktop: 데스크톱 앱 / codex_cli_rs: 터미널
                    m["cwd"] = p.get("cwd")
                    m["started"] = parse_ts(p.get("timestamp") or o.get("timestamp") or "")
                    break
    except OSError:
        pass
    return m


def codex_text(content):
    return "\n".join(c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("text")).strip()


def codex_tool(p):
    """Codex 도구 호출 → (Claude 도구 이름, 입력)."""
    name, ns = p.get("name") or "tool", p.get("namespace") or ""
    raw = p.get("arguments") if p.get("type") == "function_call" else p.get("input")
    try:
        args = json.loads(raw) if isinstance(raw, str) and raw[:1] in "{[" else raw
    except ValueError:
        args = raw
    if ns.startswith("mcp__"):
        return f"{ns}__{name}", args if isinstance(args, dict) else {"input": args}
    if name in CODEX_SHELL:
        cmd = args.get("command") or args.get("cmd") if isinstance(args, dict) else args
        if isinstance(cmd, list):
            cmd = " ".join(cmd[2:] if cmd[:1] in (["bash"], ["/bin/zsh"], ["zsh"], ["/bin/bash"]) and cmd[1:2] in (["-lc"], ["-c"]) else cmd)
        return "Bash", {"command": str(cmd or "")[:400]}
    if name == "apply_patch":
        files = re.findall(r"\*\*\* (?:Update|Add|Delete) File: (.+)", str(raw or ""))
        return "Edit", {"file_path": files[0].strip() if files else ""}
    if name == "update_plan" and isinstance(args, dict):   # 계획 → 할 일 목록 (진행률 표시)
        todos = [{"content": str(t.get("step", ""))[:80], "status": CODEX_STATUS.get(t.get("status"), "pending")}
                 for t in args.get("plan") or [] if isinstance(t, dict)]
        return "TodoWrite", {"todos": todos}
    if name.startswith("request_user_input"):
        return "AskUserQuestion", {"questions": []}
    return name, args if isinstance(args, dict) else {"input": str(args or "")[:400]}


def codex_conv(o, sess):
    """Codex 로그 한 줄 → Claude Code 형식 줄 목록 (없으면 빈 목록)."""
    t, p = o.get("type"), o.get("payload") or {}
    ts = o.get("timestamp")
    cwd = (meta.get(sess) or {}).get("cwd")
    base = {"timestamp": ts, "cwd": cwd, "sessionId": sess}
    pt = p.get("type") if isinstance(p, dict) else None
    if t == "session_meta":
        return []
    if t == "event_msg":
        if pt == "item_completed" and (p.get("item") or {}).get("type") == "UserMessage":
            text = codex_text(p["item"].get("content"))
        elif pt == "user_message":                           # 예전 CLI 형식
            text = str(p.get("message") or "").strip()
        elif pt == "task_complete":
            err = (p.get("error") or {}).get("message")
            msg = p.get("last_agent_message") or (f"오류: {err}" if err else "")
            return [{**base, "type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn",
                                                              "content": [{"type": "text", "text": msg[:2000]}]}}]
        elif pt == "turn_aborted":
            return [{**base, "type": "user", "message": {"role": "user", "content": "[Request interrupted by user]"}}]
        else:
            return []
        return [{**base, "type": "user", "message": {"role": "user", "content": text[:2000]}}] if text else []
    if t != "response_item":
        return []
    if pt == "message" and p.get("role") == "assistant":
        text = codex_text(p.get("content"))
        if not text:
            return []
        # 중간 설명(commentary)은 작업이 계속된다는 뜻 — 끝은 task_complete 로 알린다
        return [{**base, "type": "assistant", "message": {"role": "assistant", "stop_reason": "tool_use",
                                                          "content": [{"type": "text", "text": text[:2000]}]}}]
    if pt in ("function_call", "custom_tool_call"):
        name, inp = codex_tool(p)
        return [{**base, "type": "assistant", "message": {"role": "assistant", "stop_reason": "tool_use",
                 "content": [{"type": "tool_use", "id": p.get("call_id") or p.get("id"), "name": name, "input": inp}]}}]
    if pt in ("function_call_output", "custom_tool_call_output"):
        out = p.get("output")
        text = codex_text(out) if isinstance(out, list) else str(out or "")
        return [{**base, "type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": p.get("call_id"), "content": text[:1500]}]}}]
    return []


def scan_codex(root=CODEX_ROOT):
    """최근 사흘 치 날짜 폴더의 rollout 파일만 본다 (오래된 건 tail 이 하루 기준으로 거름)."""
    days = []
    try:
        for y in sorted(os.listdir(root))[-2:]:
            yp = os.path.join(root, y)
            for mo in sorted(os.listdir(yp))[-2:] if os.path.isdir(yp) else []:
                mp = os.path.join(yp, mo)
                days += [os.path.join(mp, d) for d in os.listdir(mp)] if os.path.isdir(mp) else []
    except OSError:
        return
    for d in sorted(days)[-3:]:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for f in names:
            if f.startswith("rollout-") and f.endswith(".jsonl"):
                path = os.path.join(d, f)
                if path not in offsets:
                    try:
                        if time.time() - os.stat(path).st_mtime > ACTIVE_WINDOW:
                            continue
                    except OSError:
                        continue
                sess = codex_sid(path)
                m = codex_learn(path, sess)
                proj = os.path.basename((m.get("cwd") or "").rstrip("/")) or "codex"
                tail(path, sess, proj, conv=codex_conv, src="codex")


# ───────── 세션별 토큰 사용량·요금: 대화창에서 팀장냥이 알려 줌 ─────────
# 로그의 응답 줄마다 붙은 usage 를 세션 파일 처음부터 끝까지 더한다 (서브에이전트 파일 포함).
# 파일이 수백 MB 일 수 있어서 화면 요청과는 따로, 뒤에서 조금씩 읽는다 (usage_loop).
# 요금은 공개 API 정가로 환산한 값이다 (2026-11-24 확인). 구독 요금제로 쓰면 실제로 내는 돈과 다르다.
#   Claude: https://platform.claude.com/docs/en/about-claude/pricing   OpenAI: https://developers.openai.com/api/docs/pricing
# (모델 이름 조각, 입력, 캐시 읽기, 출력) $/100만 토큰 — 위에서부터 먼저 맞는 것을 쓴다.
# 캐시 쓰기는 입력가의 1.25배(5분)·2배(1시간). 표에 없는 모델은 요금을 지어내지 않고 토큰 수만 알려 준다.
CLAUDE_PRICES = [
    ("fable-5-2", 8, 0.20, 40), ("mythos-5-2", 8, 0.20, 40),
    ("fable-5-1", 10, 0.25, 50), ("mythos-5-1", 10, 0.25, 50),
    ("fable-5", 10, 1.00, 50), ("mythos-5", 10, 1.00, 50),
    ("opus-5-5", 4, 0.20, 20),
    ("opus-5", 5, 0.50, 25), ("opus-4-8", 5, 0.50, 25), ("opus-4-7", 5, 0.50, 25),
    ("opus-4-6", 5, 0.50, 25), ("opus-4-5", 5, 0.50, 25),
    ("opus-4-1", 15, 1.50, 75), ("opus-4", 15, 1.50, 75),
    ("sonnet-5-5", 2, 0.10, 10), ("sonnet-5", 2, 0.20, 10),
    ("sonnet-4-6", 3, 0.30, 15), ("sonnet-4-5", 3, 0.30, 15), ("sonnet-4", 3, 0.30, 15),
    ("haiku-5-5", 0.10, 0.01, 0.50),          # 프롬프트가 10만 토큰을 넘는 요청은 5배 (claude_cost)
    ("haiku-4-5", 1, 0.10, 5),
]
CLAUDE_WIN_200K = {"haiku-4-5", "opus-4-5", "opus-4-1", "opus-4", "sonnet-4-5", "sonnet-4"}   # 나머지는 100만 토큰
# Codex: 모델 ID → (입력, 캐시된 입력, 출력) $/100만 토큰 (표준 요금)
CODEX_PRICES = {
    "gpt-6.2-astra": (8, 0.40, 40), "gpt-6.2-sol": (2, 0.10, 10), "gpt-6.1-sol": (2, 0.10, 10), "gpt-6.1-terra": (1, 0.05, 5),
    "gpt-6-astra": (10, 1.00, 50), "gpt-6-sol": (2, 0.20, 10), "gpt-6-luna": (0.10, 0.01, 0.50),
    "gpt-5.6-sol": (4, 0.40, 20), "gpt-5.6-terra": (2, 0.20, 12), "gpt-5.6-luna": (0.20, 0.02, 1.20),
    "gpt-5.5": (5, 0.50, 30), "gpt-5.4": (2.50, 0.25, 15), "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.3-codex": (1.75, 0.175, 14), "gpt-5.2": (1.75, 0.175, 14), "gpt-5.1": (1.25, 0.125, 10), "gpt-5": (1.25, 0.125, 10),
}
USAGE_CHUNK = 4 * 1024 * 1024   # 한 번에 읽는 양 (큰 파일도 화면 응답을 오래 막지 않게)
USAGE_AGENTS = 40               # 새끼냥(서브에이전트)별 사용량은 세션마다 최근 것 40개까지만 보냄
usage_files = {}                # 파일 경로 -> 그 파일의 누적 상태 (usage_track 이 등록, usage_loop 만 고침)
usage_ready = set()             # 파일을 처음부터 끝까지 한 번 다 읽은 세션 (그 전엔 반쪽 숫자를 내보내지 않음)
usage_out = {}                  # 세션 앞 8글자 -> 화면에 보낼 요약 (usage_loop 이 통째로 바꿔 끼움)
usage_lock = threading.Lock()
_price_memo = {}


def _n(v):
    return int(v) if isinstance(v, (int, float)) and v > 0 else 0


def claude_price(model):
    """모델 ID → (이름 조각, 입력, 캐시 읽기, 출력) 또는 None.
    'opus-5' 가 'opus-5-5' 나 아직 모르는 'opus-5-9' 에 맞지 않게, 뒤에 한 자리 숫자가 더 붙으면 다른 모델로 본다
    (날짜 꼬리 '-20251101' 은 괜찮음)."""
    if model not in _price_memo:
        _price_memo[model] = next((p for p in CLAUDE_PRICES if re.search(re.escape(p[0]) + r"(?!-\d(?!\d))", model)), None)
    return _price_memo[model]


def claude_cost(model, u):
    """응답 한 번의 usage → (달러 또는 None, 읽은 토큰, 쓴 토큰, 그 요청의 프롬프트 크기)."""
    # iterations(요청 한 번을 서버가 몇 차례에 걸쳐 처리했는지)가 있으면 그쪽이 기준: 재시도·압축이 끼면 맨 위 usage 는
    # 마지막 것만 담고, 중간에 끊긴 응답은 맨 위가 0 인 채로 남기도 한다
    its = [i for i in u.get("iterations") or [] if isinstance(i, dict)] if isinstance(u.get("iterations"), list) else []
    parts = [{**u, **i} for i in its] or [u]
    usd, read, out, prompt = 0.0, 0, 0, 0
    for d in parts:
        p = claude_price(d.get("model") if isinstance(d.get("model"), str) else model)
        tin, cr, cw = _n(d.get("input_tokens")), _n(d.get("cache_read_input_tokens")), _n(d.get("cache_creation_input_tokens"))
        o = _n(d.get("output_tokens"))
        prompt = tin + cr + cw
        read, out = read + prompt, out + o
        if not p or usd is None:
            usd = None
            continue
        cc = d.get("cache_creation") if isinstance(d.get("cache_creation"), dict) else {}
        cw1h = min(cw, _n(cc.get("ephemeral_1h_input_tokens")))
        c = (tin * p[1] + (cw - cw1h) * p[1] * 1.25 + cw1h * p[1] * 2 + cr * p[2] + o * p[3]) / 1e6
        if p[0] == "haiku-5-5" and prompt > 100_000:
            c *= 5
        if d.get("speed") == "fast":
            c *= 2
        if d.get("inference_geo") == "us":
            c *= 1.1
        usd += c
    if usd is not None:
        stu = u.get("server_tool_use") if isinstance(u.get("server_tool_use"), dict) else {}
        usd += _n(stu.get("web_search_requests")) * 0.01      # 웹 검색 1,000번에 $10
    return usd, read, out, prompt


def claude_window(model, ctx):
    p = claude_price(model)
    if not p:
        return 0
    return 200_000 if p[0] in CLAUDE_WIN_200K and ctx <= 200_000 else 1_000_000


def usage_track(path, sess, kind, agent=None):
    """사용량을 셀 파일로 등록 (kind: main | sub | codex)."""
    with usage_lock:
        if path not in usage_files:
            usage_files[path] = dict(_usage_blank(), sess=sess, kind=kind, agent=agent)


def _usage_blank():
    return {"pos": 0, "rest": b"", "ids": {}, "usd": 0.0, "unp": 0, "read": 0, "out": 0,
            "model": None, "ctx": 0, "win": 0, "cx": (0, 0, 0), "done": False, "mtime": 0.0,
            "base": 0.0, "cut": 0.0, "mts": 0.0, "memo": None, "title": ""}


def usage_since(f, cut):
    """서브에이전트 파일에서 cut(초) 뒤에 생긴 응답만: (달러, 요금표에 없는 응답 수). cut 이 없으면 전부."""
    if not cut:
        return f["usd"], f["unp"]
    key = (cut, len(f["ids"]), f["usd"], f["unp"])
    if not f["memo"] or f["memo"][0] != key:
        late = [v[0] for v in list(f["ids"].values()) if len(v) > 3 and v[3] > cut]
        f["memo"] = (key, sum(x or 0 for x in late), sum(x is None for x in late))
    return f["memo"][1], f["memo"][2]


def usage_cost_state(f, o):
    """Claude Code 가 끌 때 적어 두는 그때까지의 누적 요금 (다시 열면 터미널이 이 값에서 이어 셈).
    로그에 안 남는 호출(제목 짓기 등)까지 들어 있어서, 있으면 우리가 더한 값 대신 이걸 기준으로 하고 그 뒤 것만 더한다."""
    tot = o.get("totalCostUSD")
    if f["kind"] != "main" or not isinstance(tot, (int, float)) or tot < 0:
        return
    f["base"] = tot if tot >= f["base"] else f["base"] + tot      # 줄었으면 누적이 아니라 새로 센 값 → 앞의 것에 더함
    f["usd"], f["unp"] = 0.0, int(bool(o.get("hasUnknownModelCost")))
    f["ids"] = {k: (0.0, v[1], v[2], 0, True) for k, v in f["ids"].items()}   # 이미 기준값에 든 응답 (다시 적혀도 또 세지 않음)
    st, du = o.get("startTime"), o.get("totalDuration")
    if isinstance(st, (int, float)) and isinstance(du, (int, float)):
        f["cut"] = max(f["cut"], (st + du) / 1000)                 # 적은 시각: 서브에이전트 파일은 이 뒤 것만 더함
    else:
        f["cut"] = max(f["cut"], f["mts"])


def usage_claude_line(f, raw):
    if b'"custom-title"' in raw[:400]:
        o = json.loads(raw)
        if isinstance(o, dict) and o.get("type") == "custom-title" and isinstance(o.get("customTitle"), str):
            f["title"] = re.sub(r"[\x00-\x1f\x7f]+", " ", o["customTitle"]).strip()[:40]   # 세션에 붙인 이름 (/rename, 바깥 도구가 붙인 이름). 나중 것이 이김
        return
    if b'"cost-state"' in raw[:400]:
        o = json.loads(raw)
        if isinstance(o, dict) and o.get("type") == "cost-state":
            usage_cost_state(f, o)
        return
    if b'"usage"' not in raw or b'"assistant"' not in raw:
        return
    o = json.loads(raw)
    m = o.get("message") if isinstance(o, dict) and o.get("type") == "assistant" else None
    if not isinstance(m, dict):
        return
    u, model = m.get("usage"), m.get("model")
    if not isinstance(u, dict) or not isinstance(model, str) or model.startswith("<"):
        return                                # '<synthetic>': Claude Code 가 지어낸 줄 (API 호출 아님)
    usd, read, out, prompt = claude_cost(model, u)
    mid = m.get("id") or o.get("uuid")
    ts = parse_ts(o.get("timestamp")) or 0
    old = f["ids"].get(mid)                   # 응답 하나가 여러 줄로 나뉘어 적히므로(같은 id) 한 번만 셈
    if old and len(old) > 4:
        return
    if old:
        f["usd"] -= old[0] or 0
        f["unp"] -= old[0] is None
        f["read"] -= old[1]
        f["out"] -= old[2]
    f["ids"][mid] = (usd, read, out, ts)
    f["usd"] += usd or 0
    f["unp"] += usd is None
    f["read"] += read
    f["out"] += out
    if f["kind"] == "sub" or not o.get("isSidechain"):
        f["model"], f["ctx"] = model, prompt  # 지금 모델과 컨텍스트에 든 양 = 마지막 요청의 프롬프트 크기
        f["mts"] = max(f["mts"], ts)


def usage_codex_line(f, raw):
    if b'"turn_context"' in raw:
        o = json.loads(raw)
        p = o.get("payload") if isinstance(o, dict) and o.get("type") == "turn_context" else None
        if isinstance(p, dict) and isinstance(p.get("model"), str):
            f["model"] = p["model"]
    if b'"token_count"' not in raw:
        return
    o = json.loads(raw)
    p = o.get("payload") if isinstance(o, dict) else None
    info = p.get("info") if isinstance(p, dict) and p.get("type") == "token_count" else None
    if not isinstance(info, dict):
        return
    tot, last = info.get("total_token_usage"), info.get("last_token_usage")
    if isinstance(tot, dict):                 # 누적값이라 지난번과의 차이만 그때 모델 값으로 셈
        cur = (_n(tot.get("input_tokens")), _n(tot.get("cached_input_tokens")), _n(tot.get("output_tokens")))
        prev = f["cx"] if all(c >= q for c, q in zip(cur, f["cx"])) else (0, 0, 0)
        tin, cached, out = (c - q for c, q in zip(cur, prev))
        price = CODEX_PRICES.get(f["model"])
        if price:
            f["usd"] += (max(0, tin - cached) * price[0] + cached * price[1] + out * price[2]) / 1e6
        elif tin or out:
            f["unp"] += 1
        f["cx"], f["read"], f["out"] = cur, cur[0], cur[2]
    if isinstance(last, dict):
        f["ctx"] = _n(last.get("total_tokens")) or _n(last.get("input_tokens")) + _n(last.get("output_tokens"))
    f["win"] = _n(info.get("model_context_window")) or f["win"]


def usage_read(path, f):
    """아직 안 읽은 부분을 한 덩어리만 읽어 더한다. 더 남았으면 True."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    f["mtime"] = st.st_mtime
    if st.st_size < f["pos"]:                 # 파일이 교체/축소됨 → 처음부터 다시
        f.update(_usage_blank(), mtime=st.st_mtime)
    if st.st_size == f["pos"]:
        f["done"] = True
        return False
    try:
        with open(path, "rb") as fh:
            fh.seek(f["pos"])
            chunk = fh.read(USAGE_CHUNK)
    except OSError:
        return False
    f["pos"] += len(chunk)
    lines = (f["rest"] + chunk).split(b"\n")
    f["rest"] = lines.pop()                   # 줄바꿈 전 미완성 조각
    line_fn = usage_codex_line if f["kind"] == "codex" else usage_claude_line
    for raw in lines:
        try:
            line_fn(f, raw)
        except (ValueError, TypeError, AttributeError):
            pass
    f["done"] = f["pos"] >= st.st_size
    return not f["done"]


def usage_find_subs():
    """<세션>/subagents/*.jsonl 을 모두 등록 (오래된 것도: 세션이 지금까지 쓴 값을 다 더해야 하므로)."""
    with usage_lock:
        mains = [(p, f["sess"]) for p, f in usage_files.items() if f["kind"] == "main"]
    for path, sess in mains:
        sub = os.path.join(path[:-6], "subagents")
        try:
            names = os.listdir(sub)
        except OSError:
            continue
        for sf in names:
            if sf.endswith(".jsonl"):
                usage_track(os.path.join(sub, sf), sess, "sub", sf[:-6])


def usage_publish():
    global usage_out
    with usage_lock:
        items = list(usage_files.items())
    by = {}
    for path, f in items:
        by.setdefault(f["sess"], []).append((path, f))
    out, now = {}, time.time()
    for sess, fs in by.items():
        mp, mf = next(((p, f) for p, f in fs if f["kind"] != "sub"), (None, None))
        if not mf or (now - mf["mtime"] > ACTIVE_WINDOW and mp not in force_paths):
            continue
        if sess not in usage_ready:
            if not all(f["done"] for _, f in fs):
                continue
            usage_ready.add(sess)
        h = hook_pids.get(sess) or {}
        model = mf["model"]
        if mf["kind"] != "codex" and h.get("model") and float(h.get("mat") or 0) > mf["mts"]:
            model = h["model"]                # 켠(이어서 연) 뒤로 아직 응답이 없음 → 로그의 옛 모델 말고 지금 켜진 모델
        late = [usage_since(f, mf["cut"]) for _, f in fs if f["kind"] == "sub"]
        d = {"model": model, "ctx": mf["ctx"],
             "win": mf["win"] if mf["kind"] == "codex" else claude_window(model or "", mf["ctx"]),
             "in": sum(f["read"] for _, f in fs), "out": sum(f["out"] for _, f in fs),
             "usd": round(mf["base"] + mf["usd"] + sum(x[0] for x in late), 4),
             "sub": round(sum(f["usd"] for _, f in fs if f["kind"] == "sub"), 4)}
        if mf.get("title"):
            d["title"] = mf["title"]          # 세션에 붙인 이름 → 화면의 세션 이름
        if not d["model"] and not d["in"] and not d.get("title"):
            continue
        if mf["unp"] or any(x[1] for x in late):
            d["unp"] = 1                      # 요금표에 없는 모델이 섞임 → usd 는 아는 모델 몫만
        subs = sorted((f for _, f in fs if f["kind"] == "sub" and f["model"] and now - f["mtime"] < ACTIVE_WINDOW),
                      key=lambda f: -f["mtime"])[:USAGE_AGENTS]
        agents = {f["agent"]: {"model": f["model"], "in": f["read"], "out": f["out"],
                               "usd": None if f["unp"] else round(f["usd"], 4)} for f in subs}
        if agents:
            d["agents"] = agents
        out[sess] = d
    usage_out = out


def usage_loop():
    """보는 화면이 있을 때만, 등록된 파일을 조금씩 읽어 usage_out 을 새로 만든다."""
    found = 0.0
    while True:
        more = False
        if time.time() - last_client < 90:
            try:
                if time.time() - found > 5:
                    usage_find_subs()
                    found = time.time()
                with usage_lock:
                    items = list(usage_files.items())
                for path, f in items:
                    if usage_read(path, f):
                        more = True
                        time.sleep(0.005)     # 큰 파일을 읽는 동안에도 화면 요청이 끼어들 틈을 줌
                usage_publish()
            except Exception:
                pass
        time.sleep(0.05 if more else 2)


# ───────── hook: Claude Code·Codex가 세션 시작/끝/승인 대기를 직접 알려 줌 ─────────
# 로그 파일엔 '세션이 꺼졌다'는 기록도, 프로세스 번호(PID)도 없어서 화면이 세션을 지울 때를 몰랐다.
# hook 을 등록하면 각 도구가 이벤트마다 이 파일을 `--hook claude|codex` 로 실행하고, 그게 서버에 알려 준다.
#   Claude Code: SessionStart · SessionEnd · Stop · Notification(권한 승인 대기)
#   Codex:       SessionStart · Stop · PermissionRequest   (세션 끝 이벤트가 없어서 PID 가 사라지면 끝으로 봄)
# SessionStart 때 hook 을 실행한 claude/codex 프로세스의 PID 를 기억해 두고, 그 프로세스가 사라지면
# (터미널을 그냥 닫은 경우 등) 세션이 끝난 걸로 본다.
HOOK_TAG = "agent_office_server.py"         # 우리가 넣은 hook 인지 알아보는 표시 (명령줄에 들어 있음)
CLAUDE_HOOK_EVENTS = ["SessionStart", "SessionEnd", "Stop", "Notification"]
CODEX_HOOK_EVENTS = ["SessionStart", "Stop", "PermissionRequest"]
AGENT_RE = {"claude": re.compile(r"(^|[\\/\s])claude(\.exe|\.cmd)?(\s|$)|claude-code", re.I),
            "codex": re.compile(r"(^|[\\/\s])codex(\.exe|\.cmd|\.js)?(\s|$)|@openai[\\/]codex", re.I)}
hook_pids = {}                              # 세션 키 -> {"pid", "src", "proj", "id"}
hook_ended = {}                             # 세션 키 -> 끝난 시각 (서버를 다시 켜도 다시 안 나오게)
HOOK_STATE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "agent-office", "hook_sessions.json")
_restored_ends = []                         # 다시 켰을 때 화면에 다시 알려 줄 '끝난 세션'


def _state_lock():
    """여러 서버가 '읽고-합치고-쓰기'를 동시에 하지 않게 잠금 파일로 차례를 맞춘다 (최대 약 1초 기다림)."""
    path = HOOK_STATE + ".lock"
    for _ in range(50):
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return path
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > 5:   # 꺼진 서버가 남긴 잠금
                    os.remove(path)
                    continue
            except OSError:
                pass
            time.sleep(0.02)
        except OSError:
            return None
    return None


def _read_state():
    try:
        with open(HOOK_STATE, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}, {}
    if not isinstance(d, dict):
        return {}, {}
    pick = lambda x: {k: v for k, v in (x or {}).items() if isinstance(k, str) and isinstance(v, dict)}
    return pick(d.get("pids")), pick(d.get("ended"))


def merge_state(pids_a, ended_a, pids_b, ended_b):
    """세션마다 가장 최근 기록 하나만 남긴다: 살아 있음(pid, at) 과 끝남(at) 중 더 늦은 쪽. 같으면 끝남."""
    pids, ended = {}, {}
    for k in set(pids_a) | set(ended_a) | set(pids_b) | set(ended_b):
        best = None
        for kind, rec in (("pid", pids_a.get(k)), ("pid", pids_b.get(k)), ("end", ended_a.get(k)), ("end", ended_b.get(k))):
            if not rec:
                continue
            key = (float(rec.get("at") or 0), kind == "end")
            if best is None or key > best[0]:
                best = (key, kind, rec)
        if best:
            (pids if best[1] == "pid" else ended)[k] = best[2]
    return pids, ended


def save_hook_state():
    """파일에 이미 있는 다른 서버의 기록과 합쳐서 쓴다 (통째로 덮어써서 남의 기록을 지우지 않게).
    합친 결과로 이 서버의 기억도 맞춘다: 다른 서버가 끝을 본 세션은 여기서도 퇴근, 모르던 PID 는 배움."""
    tmp = f"{HOOK_STATE}.{os.getpid()}.tmp"     # 서버마다 다른 임시 파일 (여러 서버가 동시에 써도 안 섞이게)
    lk = None
    try:
        os.makedirs(os.path.dirname(HOOK_STATE), exist_ok=True)
        lk = _state_lock()
        fp, fe = _read_state()
        pids, ended = merge_state(hook_pids, hook_ended, fp, fe)
        cut = time.time() - ACTIVE_WINDOW
        ended = {k: v for k, v in ended.items() if float(v.get("at") or 0) > cut}
        for k in list(hook_pids):
            if k not in pids:
                h = hook_pids.pop(k)
                if k in ended:              # 다른 서버가 먼저 끝을 봤음
                    hook_event(h.get("src", "claude"), k, h.get("proj", ""), "end", "other_server", ended[k].get("at"))
        for k, v in pids.items():
            if k not in hook_pids and k in hook_ended:      # 끝난 줄 알았는데 다른 서버가 살아 있는 걸 봤음
                hook_event(v.get("src", "claude"), k, v.get("proj", ""), "start", "alive")
            hook_pids.setdefault(k, v)
        hook_ended.clear()
        hook_ended.update(ended)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"pids": pids, "ended": ended}, fh)
        os.replace(tmp, HOOK_STATE)
    except OSError:
        try:
            os.remove(tmp)                  # 바꿔치기에 실패하면 임시 파일은 치움
        except OSError:
            pass
    finally:
        if lk:
            try:
                os.remove(lk)
            except OSError:
                pass


def load_hook_state():
    try:
        with open(HOOK_STATE, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return
    hook_pids.update({k: v for k, v in (d.get("pids") or {}).items() if isinstance(v, dict)})
    hook_ended.update({k: v for k, v in (d.get("ended") or {}).items() if isinstance(v, dict)})
    _restored_ends.extend(hook_ended.items())
hook_seen = set()                           # hook 을 한 번이라도 보낸 도구 ("claude", "codex")
_last_alive_check = 0.0


def hook_sources():
    """hook 이 동작 중인 도구: 이 도구의 세션 중 hook 신호가 한 번도 없던 건 'hook 이전 세션'으로 본다."""
    return sorted(hook_seen | {h.get("src", "claude") for h in hook_pids.values()}
                  | {e.get("src", "claude") for e in hook_ended.values()})


def hook_sess(src, sid):
    sid = str(sid or "")
    return ("cx" + re.sub(r"[^0-9a-f]", "", sid.lower())[-6:]) if src == "codex" else sid[:8]


SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh", "env", "cmd", "cmd.exe", "powershell", "powershell.exe",
          "pwsh", "pwsh.exe", "bash.exe", "sh.exe"}


def _win_procs():
    """윈도우: {pid: (부모 pid, 실행 파일 이름)} (추가 설치 없이 ctypes 로)."""
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(2, 0)
    out, e = {}, PE()
    e.dwSize = ctypes.sizeof(PE)
    ok = k.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
        ok = k.Process32NextW(snap, ctypes.byref(e))
    k.CloseHandle(snap)
    return out


def _cmdline(pid):
    if SYSTEM == "Windows":
        try:
            return (_win_procs().get(pid) or (0, ""))[1]
        except Exception:
            return ""
    if SYSTEM == "Linux":
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                return fh.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            return ""
    return run(["ps", "-o", "command=", "-p", str(pid)], timeout=3)


def _parent(pid):
    if SYSTEM == "Windows":
        try:
            return (_win_procs().get(pid) or (0, ""))[0]
        except Exception:
            return 0
    if SYSTEM == "Linux":
        return proc_ppid(pid)
    try:
        return int(run(["ps", "-o", "ppid=", "-p", str(pid)], timeout=3) or 0)
    except ValueError:
        return 0


def _is_shell(cmd):
    first = (shlex.split(cmd, posix=SYSTEM != "Windows")[:1] or [""])[0] if cmd else ""
    return os.path.basename(first.strip('"')).lower() in SHELLS


def agent_pid(src):
    """이 hook 을 실행한 claude/codex 프로세스: 부모를 따라 올라가며 hook 을 띄운 셸을 건너뛴 첫 프로세스.
    (설치 방식마다 프로그램 이름·경로가 달라서 이름으로 찾지 않는다)"""
    pid = os.getppid()
    for _ in range(6):
        if pid <= 1:
            return None
        try:
            cmd = _cmdline(pid)
        except Exception:
            cmd = ""
        if cmd and HOOK_TAG not in cmd and not _is_shell(cmd):
            return pid
        pid = _parent(pid)
    return None


def pid_alive(pid, src=None):
    if SYSTEM == "Windows":
        try:
            return pid in _win_procs()
        except Exception:
            return True                         # 확인할 수 없으면 살아 있다고 봄 (잘못 지우지 않게)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        pass
    if SYSTEM == "Linux":                   # 끝났지만 아직 거둬지지 않은(좀비) 프로세스는 죽은 걸로
        try:
            with open(f"/proc/{pid}/stat") as fh:
                return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
        except (OSError, IndexError):
            return False
    return True


# 켜져 있는 서버 목록: 서버마다 자기 포트를 이 폴더에 파일 하나로 적어 두고(<포트>.json), 끌 때 지운다.
# hook 은 이 목록 전체에 이벤트를 보낸다 (포트를 hook 명령에 박아 두면 마지막에 켠 서버 하나만 받았음).
SERVERS_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "agent-office", "servers")


def register_server(port):
    try:
        os.makedirs(SERVERS_DIR, exist_ok=True)
        path = os.path.join(SERVERS_DIR, f"{port}.json")
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"port": port, "pid": os.getpid(), "started": int(time.time())}, fh)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[!] 서버 목록에 적지 못했어요 ({e}). hook 은 {port}번으로만 보내져요.")


def unregister_server(port):
    path = os.path.join(SERVERS_DIR, f"{port}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            if json.load(fh).get("pid") != os.getpid():   # 그 사이 같은 포트로 다른 서버가 켜졌으면 두기
                return
        os.remove(path)
    except (OSError, ValueError):
        pass


def listed_servers():
    """[(포트, pid, 파일)] — 프로세스가 사라진 항목은 지운다."""
    out = []
    try:
        names = os.listdir(SERVERS_DIR)
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        path = os.path.join(SERVERS_DIR, n)
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            port, pid = int(d["port"]), int(d.get("pid") or 0)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if pid and not pid_alive(pid):
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        out.append((port, pid, path))
    return out


def hook_main(src, port=None):
    """`--hook claude|codex`: 도구가 넘겨준 JSON(stdin)을 켜져 있는 서버 모두에게 전달하고 조용히 끝난다.
    아무것도 출력하지 않는다 (SessionStart 출력은 대화에 끼어들고, PermissionRequest 출력은 승인 결정이 되기 때문)."""
    try:
        raw = sys.stdin.read()
        d = json.loads(raw) if raw.strip() else {}
        body = json.dumps({"src": src, "event": d.get("hook_event_name"), "session_id": d.get("session_id"),
                           "cwd": d.get("cwd"), "transcript_path": d.get("transcript_path"),
                           "reason": d.get("reason") or d.get("notification_type") or d.get("source") or d.get("tool_name"),
                           "model": d.get("model"), "pid": agent_pid(src)}).encode()
        ports = {p for p, _, _ in listed_servers()}
        if port:
            ports.add(port)                 # 예전 방식 (--port 를 붙인 hook) 도 계속 받게
        if not ports:
            ports = {8765}

        def send(p):
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{p}/api/hook", data=body,
                                             headers={"Content-Type": "application/json", "X-Agent-Office": "1"})
                urllib.request.urlopen(req, timeout=1.5).read()
            except Exception:
                pass                        # 꺼진 서버는 건너뜀

        ts = [threading.Thread(target=send, args=(p,), daemon=True) for p in sorted(ports)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(2)
    except Exception:
        pass                                # 서버가 꺼져 있어도 도구 쪽 작업은 막지 않는다
    return 0


def hook_event(src, sess, proj, kind, reason="", at=None):
    """화면에 보낼 hook 이벤트 (로그 줄과 같은 흐름에 'h' 필드로 섞어 보냄)."""
    global seq
    seq += 1
    events.append({"q": seq, "s": sess, "p": proj, "src": src,
                   "h": {"e": kind, "r": reason or "", "t": int((at or time.time()) * 1000)}})


def take_hook(b):
    src = "codex" if b.get("src") == "codex" else "claude"
    sid = str(b.get("session_id") or "")
    if not re.fullmatch(r"[0-9A-Za-z_-]{6,80}", sid):
        return False
    sess = hook_sess(src, sid)
    ev = str(b.get("event") or "")
    reason = str(b.get("reason") or "")[:40]
    tp, cwd = b.get("transcript_path") or "", b.get("cwd") or ""
    with lock:
        try:                                # 그 사이 쌓인 로그 줄을 먼저 읽어 순서를 맞춤 (도구 호출 → 승인 대기)
            scan(Handler.root)
            if CODEX_ON:
                scan_codex()
        except Exception:
            pass
        hook_seen.add(src)
        if src == "claude" and tp:
            proj = proj_label(os.path.basename(os.path.dirname(tp)))
        else:
            proj = (hook_pids.get(sess) or {}).get("proj") or os.path.basename(str(cwd).rstrip("/\\")) or src
        pid = b.get("pid") if isinstance(b.get("pid"), int) and b.get("pid") > 1 else None
        if ev == "SessionEnd":
            hook_pids.pop(sess, None)
            hook_ended[sess] = {"at": time.time(), "src": src, "proj": proj}
            hook_event(src, sess, proj, "end", reason)
            save_hook_state()
            return True
        h = hook_pids.get(sess)
        if ev == "SessionStart" or not h or (pid and h.get("pid") != pid):   # 처음 보거나 PID 를 새로 알게 됨
            hook_pids[sess] = {"pid": pid or (h or {}).get("pid"), "src": src, "proj": proj, "id": sid, "at": time.time(),
                               **{k: h[k] for k in ("model", "mat") if h and k in h}}
            model = b.get("model")
            if ev == "SessionStart" and isinstance(model, str) and 0 < len(model) < 80:
                hook_pids[sess].update(model=model, mat=time.time())     # 지금 켜진 모델 (이어서 열면 로그의 옛 모델과 다를 수 있음)
            hook_ended.pop(sess, None)
            save_hook_state()
        if ev == "SessionStart":
            hook_event(src, sess, proj, "start", reason)
        elif ev == "Stop":
            hook_event(src, sess, proj, "stop")
        elif ev == "Notification" and reason == "permission_prompt" or ev == "PermissionRequest":
            hook_event(src, sess, proj, "ask", reason)
        else:
            return True
    return True


def check_alive():
    """SessionStart 때 기억한 프로세스가 사라졌으면 세션 끝으로 알린다 (5초에 한 번)."""
    global _last_alive_check
    now = time.time()
    if now - _last_alive_check < 5:
        return
    _last_alive_check = now
    changed = False
    while _restored_ends:                   # 다시 켠 직후: 전에 끝난 세션을 화면에 다시 알려 줌 (로그 줄보다 뒤에)
        sess, e = _restored_ends.pop()
        hook_event(e.get("src", "claude"), sess, e.get("proj", ""), "end", "restored", e.get("at"))   # 원래 끝난 시각 → 화면은 걷지 않고 바로 뺌
    for sess, h in list(hook_pids.items()):
        if h.get("pid") and not pid_alive(h["pid"], h.get("src")):
            hook_pids.pop(sess, None)
            hook_ended[sess] = {"at": now, "src": h.get("src", "claude"), "proj": h.get("proj", "")}
            hook_event(h.get("src", "claude"), sess, h.get("proj", ""), "end", "process_gone")
            changed = True
    if changed:
        save_hook_state()


def hook_command(src, port=None):
    """포트를 넣지 않음: 어느 서버가 등록해도 같은 명령이고, hook 이 서버 목록을 보고 모두에게 보낸다."""
    py = sys.executable.replace("\\", "/")
    me = os.path.abspath(__file__).replace("\\", "/")
    return f'"{py}" "{me}" --hook {src}'


def _edit_hooks(path, events_, cmd):
    """settings.json / hooks.json 의 hooks 에 우리 명령을 넣거나(cmd) 빼고(None), 원래 파일은 .bak 으로 남긴다."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        data = json.loads(text) if text.strip() else {}
    except FileNotFoundError:
        text, data = None, {}
    except (OSError, ValueError) as e:
        return f"[!] {path} 를 읽지 못해서 건드리지 않았어요 ({e})"
    if not isinstance(data, dict):
        return f"[!] {path} 형식이 예상과 달라서 건드리지 않았어요"
    orig = json.loads(json.dumps(data))
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return f"[!] {path} 의 hooks 형식이 예상과 달라서 건드리지 않았어요"
    for ev in set(events_) | set(k for k in hooks):
        groups = hooks.get(ev)
        if not isinstance(groups, list):
            continue
        keep = []
        for g in groups:
            hs = [h for h in (g.get("hooks") or []) if HOOK_TAG not in str(h.get("command", ""))] if isinstance(g, dict) else None
            if hs is None:
                keep.append(g)
            elif hs:
                keep.append({**g, "hooks": hs})
        hooks[ev] = keep
        if not keep:
            hooks.pop(ev)
    if cmd:
        for ev in events_:
            hooks.setdefault(ev, []).append({"hooks": [{"type": "command", "command": cmd, "timeout": 5}]})
    if not hooks:
        data.pop("hooks", None)
    if data == orig:                        # 이미 그대로면 파일을 건드리지 않음
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not data and text is not None and not cmd:       # 우리 것만 있던 파일이면 지움
        os.replace(path, path + ".agent-office.bak")
        return path
    if text is not None:
        with open(path + ".agent-office.bak", "w", encoding="utf-8") as fh:
            fh.write(text)
    tmp = f"{path}.{os.getpid()}.tmp"       # 서버 여러 개가 동시에 켜져도 임시 파일이 겹치지 않게
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return path


CLAUDE_SETTINGS = os.path.expanduser("~/.claude/settings.json")
CODEX_HOOKS = os.path.expanduser("~/.codex/hooks.json")


def install_hooks(port, codex=True):
    out = [_edit_hooks(CLAUDE_SETTINGS, CLAUDE_HOOK_EVENTS, hook_command("claude", port))]
    if codex and os.path.isdir(os.path.expanduser("~/.codex")):
        out.append(_edit_hooks(CODEX_HOOKS, CODEX_HOOK_EVENTS, hook_command("codex", port)))
    return [x for x in out if x]


def uninstall_hooks():
    return [x for x in (_edit_hooks(CLAUDE_SETTINGS, CLAUDE_HOOK_EVENTS, None),
                        _edit_hooks(CODEX_HOOKS, CODEX_HOOK_EVENTS, None)) if x]


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
CODEX_RE = re.compile(r"(^|[\\/])codex(\.exe|\.cmd)?(\s|$)", re.I)
SESS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "sessions")   # Claude Code가 남기는 <pid>.json (세션 ID·폴더)


def claude_processes(rx=CLAUDE_RE, word="claude"):
    """실행 중인 Claude Code(또는 rx 에 맞는 프로그램) 프로세스 목록: [{pid, ppid, tty, start, args, cwd}]"""
    out = []
    if SYSTEM == "Windows":
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '" + word + "' -and "
              "$_.Name -match '^(node|" + word + "|bun)' } | ForEach-Object { [pscustomobject]@{ "
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
    raw = run(["ps", "-axo" if SYSTEM == "Darwin" else "-eo", fmt], env={**os.environ, "LC_ALL": "C"})   # 시작 시각을 영어 형식으로 (한국어 로캘이면 칸 수가 달라짐)
    for line in raw.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        pid, ppid, tty = parts[0], parts[1], parts[2]
        args = parts[8]
        if not rx.search(args) or "agent_office_server" in args:
            continue
        if os.path.basename(args.split()[0]) == "tmux":       # 'tmux new -s x claude' 같은 tmux 자신
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
                    "start": start, "lstart": _lstart(" ".join(parts[3:8])), "args": args, "cwd": cwd})
    return out


def _lstart(text):
    """ps 의 lstart ("Sun Nov 15 15:00:29 2026") → 그 글자 그대로의 시각 (어느 시간대인지는 모름)."""
    try:
        return calendar.timegm(time.strptime(" ".join(str(text).split()), "%a %b %d %H:%M:%S %Y"))
    except (ValueError, TypeError):
        return None


def session_pids(procs=None):
    """Claude Code가 적어 둔 ~/.claude/sessions/<pid>.json 을 읽는다: {pid: 세션 ID}
    procs(지금 도는 프로세스)를 주면, 죽은 프로세스가 남긴 파일의 PID 를 다른 프로세스가 다시 쓰는 경우를 걸러 낸다:
    파일에 적힌 시작 시각(procStart)이 실제와 다르면 뺌 (시간대만 다를 수 있어 15분 단위 차이는 같은 것으로 봄)."""
    real = {p["pid"]: p.get("lstart") for p in procs or []}
    out = {}
    try:
        names = os.listdir(SESS_DIR)
    except OSError:
        return out
    for fn in names:
        if not re.fullmatch(r"\d+\.json", fn):
            continue
        try:
            with open(os.path.join(SESS_DIR, fn), encoding="utf-8") as fh:
                d = json.load(fh)
            pid, a, b = int(fn[:-5]), _lstart(d.get("procStart")), real.get(int(fn[:-5]))
            if a is not None and b is not None and min((a - b) % 900, (b - a) % 900) > 3:
                continue
            out[pid] = str(d.get("sessionId") or "")
        except (OSError, ValueError, AttributeError):
            pass
    return out


# hook 신호가 없는 세션도 실행 중인지 짐작: 돌고 있는 claude 프로세스를 세션 파일과 짝지음 (30초마다)
#   명령줄에 세션 ID 가 있으면(--resume) 그 파일, 아니면 같은 폴더의 프로젝트 기록 중 가장 최근 것
#   hook 으로 PID 를 아는 세션·프로세스는 빼고 짝지음. 윈도우는 작업 폴더를 못 읽어서 하지 않음.
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
force_paths = set()                         # 하루가 지났어도 읽을 세션 파일 (프로세스가 살아 있음)
_session_files = {}                         # 전체 세션 ID -> 로그 파일 (session_file)
_alive_guess = {"at": 0.0, "sess": {}}


def project_dir_for(root, cwd):
    """Claude Code 가 작업 폴더별로 쓰는 기록 폴더 (/a/b.c → -a-b-c)."""
    name = re.sub(r"[^A-Za-z0-9]", "-", cwd)
    path = os.path.join(root, name)
    if os.path.isdir(path):
        return path
    try:
        for d in os.listdir(root):
            if d.lower() == name.lower():
                return os.path.join(root, d)
    except OSError:
        pass
    return None


def revive_ended(procs, known):
    """'끝남'으로 적힌 세션인데 그 세션을 돌리는 claude 가 살아 있으면(pid 파일 기준) 끝남 표시를 지우고 다시 출근시킨다.
    같은 세션을 두 군데서 열어 두고 한쪽만 껐거나, 끝 알림 뒤에 hook 신호 없이 다시 이어 연 경우."""
    now, changed = time.time(), False
    hooked = {h.get("pid") for h in hook_pids.values() if h.get("pid")}
    for p in procs:
        sid = known.get(p["pid"])
        key = hook_sess("claude", sid) if sid else ""
        e = hook_ended.get(key)
        if not e or p["pid"] in hooked or e.get("src", "claude") != "claude" or now - float(e.get("at") or 0) < 10:
            continue                        # 방금 끝난 건 기다림 (/clear 직후엔 pid 파일이 아직 옛 세션일 수 있음)
        hook_ended.pop(key, None)
        _restored_ends[:] = [x for x in _restored_ends if x[0] != key]
        hook_pids[key] = {"pid": p["pid"], "src": "claude", "proj": e.get("proj", ""), "id": sid, "at": now}
        hooked.add(p["pid"])
        hook_event("claude", key, e.get("proj", ""), "start", "alive")
        print(f"[세션] {key}: 끝남으로 적혀 있었지만 pid {p['pid']} 가 돌리고 있어서 다시 출근")
        changed = True
    if changed:
        save_hook_state()


def guess_alive(root):
    """{세션 키: 파일} — hook 없이도 프로세스가 살아 있다고 짐작되는 세션."""
    now = time.time()
    if now - _alive_guess["at"] < 30:
        return _alive_guess["sess"]
    _alive_guess["at"] = now
    out = {}
    if SYSTEM != "Windows":
        try:
            procs = claude_processes()
        except Exception:
            procs = []
        pids = {p["pid"] for p in procs}
        known = session_pids(procs)
        revive_ended(procs, known)
        hooked = {h.get("pid") for h in hook_pids.values() if h.get("pid")}
        claimed = set(hook_pids)
        for p in sorted(procs, key=lambda p: -(p["start"] or 0)):
            if p["pid"] in hooked or p["ppid"] in pids:      # hook 으로 아는 프로세스, claude 가 띄운 자식은 빼고
                continue
            m = UUID_RE.search(p["args"] or "")
            path = session_file(root, known.get(p["pid"])) or (session_file(root, m.group(0)) if m else None)   # pid 파일 → 명령줄의 세션 ID
            if not path and p["cwd"]:
                pdir = project_dir_for(root, p["cwd"])
                if pdir:
                    try:
                        files = [os.path.join(pdir, f) for f in os.listdir(pdir) if f.endswith(".jsonl") and f[:8] not in claimed]
                        files.sort(key=lambda f: -os.path.getmtime(f))
                        path = files[0] if files else None
                    except OSError:
                        path = None
            if path:
                key = os.path.basename(path)[:8]
                if key not in claimed:
                    out[key] = path
                    claimed.add(key)
    _alive_guess["sess"] = out
    return out


def session_file(root, sid):
    """전체 세션 ID → 그 세션의 로그 파일 (어느 프로젝트 폴더에 있든). 없으면 None."""
    if not sid:
        return None
    if sid not in _session_files:
        try:
            dirs = os.listdir(root)
        except OSError:
            return None
        path = next((f for f in (os.path.join(root, d, sid + ".jsonl") for d in dirs) if os.path.isfile(f)), None)
        if not path:
            return None                     # 아직 파일이 없을 수 있으니 못 찾은 건 기억하지 않음
        _session_files[sid] = path
    return _session_files[sid]


def alive_sessions(root):
    """화면에 알려 줄 '실행 중' 세션: hook 으로 PID 를 아는 것 + 짐작한 것.
    그 세션들의 파일은 하루 넘게 조용했어도 읽게 한다 (옛 세션을 이어서 열고 아직 아무것도 안 시킨 경우)."""
    global force_paths
    guessed = guess_alive(root)
    hooked = {k: h for k, h in hook_pids.items() if h.get("pid")}
    paths = set(guessed.values())
    for h in hooked.values():
        f = session_file(root, h.get("id")) if h.get("src", "claude") == "claude" else None
        if f:
            paths.add(f)
    force_paths = paths                     # 통째로 바꿔 끼움 (사용량 스레드가 읽는 중에 비지 않게)
    return sorted(set(guessed) | set(hooked))


def hook_owners():
    """{pid: 세션 키} — hook 으로 아는, 그 프로세스가 지금 돌리는 Claude 세션.
    한 프로세스가 /clear·/resume 으로 다른 세션으로 넘어가면 가장 나중에 알린 세션이 주인."""
    own = {}
    for k, h in list(hook_pids.items()):
        pid = h.get("pid")
        if not pid or h.get("src", "claude") != "claude":      # Codex 앱은 프로세스 하나가 여러 세션을 돌림
            continue
        if pid not in own or float(h.get("at") or 0) > float(hook_pids[own[pid]].get("at") or 0):
            own[pid] = k
    return own


def find_process(m):
    """세션에 해당하는 프로세스를 고른다. 확실한 것부터:
    1) hook 이나 Claude Code 의 pid 파일이 '이 프로세스가 지금 이 세션'이라고 알려 주는 것
    2) 명령줄에 세션 ID 가 있는 것(--resume) — 단, 지금은 다른 세션을 돌리는 프로세스는 아님
    3) 같은 폴더(cwd)에서 도는 것 중 시작 시각이 가장 가까운 것 (짐작). 끝난 걸 아는 세션, 다른 세션의 프로세스,
       claude 가 띄운 자식, 이 세션의 마지막 기록보다 나중에 켜진 프로세스는 고르지 않는다 (엉뚱한 터미널로 가지 않게)."""
    key = m.get("key") or ""
    if m.get("src") == "codex":            # Codex: 터미널에서 도는 CLI만 (같은 폴더)
        procs = [p for p in claude_processes(CODEX_RE, "codex") if p["tty"] or SYSTEM == "Windows"]
        known, own = {}, {}
    else:
        procs = claude_processes()
        known, own = session_pids(procs), hook_owners()
        for p in procs:                    # 기억한 뒤에 켜진 프로세스 = 같은 번호를 다시 받은 남
            if p["pid"] in own and p["start"] and p["start"] > float(hook_pids[own[p["pid"]]].get("at") or 0) + 5:
                del own[p["pid"]]
    sure = [{**p, "how": "hook" if p["pid"] in own else "pid 파일"} for p in procs    # hook 이 pid 파일보다 먼저 (더 최근 소식)
            if (own.get(p["pid"]) == key if p["pid"] in own else known.get(p["pid"]) == m["id"])]
    pids = {p["pid"] for p in procs}
    procs = [p for p in procs if p["pid"] not in own and not known.get(p["pid"])]
    sure += [{**p, "how": "명령줄의 세션 ID"} for p in procs if m["id"] in p["args"]]
    if sure:                               # 같은 세션을 두 군데서 열어 뒀으면(tmux 에 둔 채 다른 터미널에서 이어 엶) 나중에 켠 쪽
        return max(sure, key=lambda p: p["start"] or 0)
    if key in hook_ended:
        return None
    try:
        last = os.path.getmtime(m.get("file") or "")
    except OSError:
        last = None
    procs = [p for p in procs if p["ppid"] not in pids and not (last and p["start"] and p["start"] > last + 5)]
    cands = [p for p in procs if p["cwd"] and m["cwd"] and same_dir(p["cwd"], m["cwd"])]
    if not cands and SYSTEM == "Windows":
        cands = procs            # 윈도우는 cwd를 못 읽으니 시작 시각으로만 고름
    if not cands:
        return None
    if m["started"]:
        cands.sort(key=lambda p: abs((p["start"] or 0) - m["started"]))
    return {**cands[0], "how": "같은 폴더 (짐작)"}


OSA_DENIED = False            # 마지막 osascript 가 자동화 권한(-1743)에 막혔는지


def osa(script):
    global OSA_DENIED
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return ""
    OSA_DENIED = "-1743" in (r.stderr or "")
    return r.stdout.strip()


def focus_mac(p, m):
    denied = False
    if p["tty"]:
        tty = "/dev/" + p["tty"]
        if re.fullmatch(r"/dev/tty[a-z]*\d+", tty):
            r = osa(f'''if application id "com.apple.Terminal" is running then
  tell application id "com.apple.Terminal"
    repeat with w in windows
      repeat with t in tabs of w
        if tty of t is "{tty}" then
          if miniaturized of w then set miniaturized of w to false
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
            denied = OSA_DENIED
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
            denied = denied or OSA_DENIED
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
            if denied and name in ("Terminal", "iTerm", "iTerm2"):
                return True, (f"{name} 창을 앞으로 가져왔어요. 탭까지 고르려면 시스템 설정 → 개인정보 보호 및 보안 → 자동화에서 "
                              f"python이 {name}을 제어하도록 허용해 주세요.")
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
        return ("GNOME(Wayland)은 다른 프로그램이 창을 앞으로 꺼내지 못하게 막아 둬요. 'Window Calls'라는 "
                "GNOME 확장(작은 추가 기능)을 깔면 풀려요: 터미널에서 서버를 켜면 설치할지 물어봐요. "
                "(직접 하려면 '확장 관리자' 앱에서 Window Calls 검색)")
    if st == "wayland":
        return (f"{de or '이 데스크톱'}(Wayland)에서는 바깥 프로그램이 창을 앞으로 가져올 수 없어요. "
                "tmux·kitty·WezTerm 안에서 claude를 쓰면 돼요. 지금은 '이어하기'를 써 주세요.")
    if st == "x11":
        return "X11에서는 wmctrl이나 xdotool이 있으면 돼요: sudo apt install wmctrl  (서버를 켤 때 설치를 물어봐요)"
    return "화면 세션(DISPLAY)을 찾지 못했어요. 데스크톱에서 연 터미널로 서버를 켜 주세요."


# ── gnome-terminal 탭 고르기 ──
# gnome-terminal은 '이 탭 보여줘' API가 없어서, 그 세션의 터미널 제목을 잠깐 표식으로 바꾼 뒤
# 창마다 탭을 하나씩 넘겨 보며(org.gtk.Actions 'active-tab' 또는 'tab-switch-right')
# 창 제목이 표식이 되는 탭을 찾는다. 창 제목은 Window Calls 확장이나 X11 도구로 읽는다.

def gt_windows(service=""):
    """탭을 넘겨 볼 gnome-terminal 창들: [(D-Bus 이름, 창 경로)].
    service 는 그 탭의 GNOME_TERMINAL_SERVICE (그 탭을 띄운 터미널 서버의 버스 이름). --app-id 로 따로 띄운 터미널은
    이름도 경로도 org.gnome.Terminal 이 아니라서, 그 서버를 통째로 훑어 .../window/N 을 찾는다 (엉뚱한 서버의 탭을 넘기지 않게)."""
    if re.fullmatch(r"[A-Za-z0-9_.:-]+", service or ""):
        out = run(["gdbus", "introspect", "--session", "--dest", service, "--object-path", "/", "--recurse"], timeout=10)
        stack, found = [], []
        for ln in out.splitlines():
            ln = ln.strip()
            m = re.fullmatch(r"node\s+(\S+)\s*\{", ln)
            if m:                              # 하위 노드는 전체 경로로도, 이름만으로도 나올 수 있다
                name = m.group(1)
                up = next((x for x in reversed(stack) if x), "")
                path = name if name.startswith("/") else up.rstrip("/") + "/" + name
                stack.append(path)
                if re.search(r"/window/\d+$", path) and path not in found:
                    found.append(path)
            elif ln.endswith("{"):
                stack.append(None)
            elif ln in ("}", "};") and stack:
                stack.pop()
        if found:
            return [(service, x) for x in found]
    out = run(["gdbus", "introspect", "--session", "--dest", "org.gnome.Terminal",
               "--object-path", "/org/gnome/Terminal/window"])
    # 첫 줄 'node /org/gnome/Terminal/window {'(자기 자신)는 빼고 하위 노드(창)만
    return [("org.gnome.Terminal", "/org/gnome/Terminal/window/" + n) for n in re.findall(r"node\s+([^/\s]\S*)\s*\{", out)]


def gt_action(win, method, *args):
    return run(["gdbus", "call", "--session", "--dest", win[0], "--object-path", win[1],
                "--method", "org.gtk.Actions." + method, *args]).strip()


def tty_write(tty, data):
    try:
        with open(tty, "w") as fh:
            fh.write(data)
        return True
    except OSError:
        return False


def wc_activate(wid):
    run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell",
         "--object-path", "/org/gnome/Shell/Extensions/Windows",
         "--method", "org.gnome.Shell.Extensions.Windows.Activate", str(wid)])


def title_finder():
    """창 제목으로 창을 찾는 함수와 그 창을 앞으로 가져오는 함수 (find, activate). 방법이 없으면 None.
    GNOME 'Window Calls' 확장(Wayland도 가능) → X11이면 xdotool → wmctrl 순서."""
    wins = gnome_window_calls()
    if wins is not None and all("title" in w for w in wins):
        return (lambda t: next((w.get("id") for w in gnome_window_calls() or [] if w.get("title") == t), None),
                wc_activate)
    if linux_session()[0] == "wayland":
        return None
    if shutil.which("xdotool"):
        return (lambda t: (run(["xdotool", "search", "--name", "^" + re.sub(r"([.\[\]{}()*+?^$|\\])", r"\\\1", t) + "$"]).split() or [None])[-1],
                lambda wid: run(["xdotool", "windowactivate", wid]))
    if shutil.which("wmctrl"):
        def find(t):
            for ln in run(["wmctrl", "-l"]).splitlines():
                cols = ln.split(None, 3)            # 창 ID, 데스크톱, 호스트, 제목
                if len(cols) == 4 and cols[3] == t:
                    return cols[0]
            return None
        return find, lambda wid: run(["wmctrl", "-ia", wid])
    return None


def gnome_terminal_pick(tty, service="", title=""):
    """그 tty가 있는 탭을 띄우고 그 창을 앞으로 가져온다. 못 찾으면 False.
    service: 그 탭의 GNOME_TERMINAL_SERVICE (gt_windows). title: 그 탭에 붙어 있을 제목 — tmux 가 제목을 직접 정하면(set-titles)
    표식을 덮어쓸 수 있어서, 창 제목이 표식이거나 이 제목이면 찾은 것으로 본다."""
    if not re.fullmatch(r"/dev/pts/\d+", tty or "") or not shutil.which("gdbus"):
        return False
    finder = title_finder()
    if not finder:                             # 창 제목을 읽을 방법이 없으면 탭을 넘겨 봐도 알 수 없다
        return False
    find_win, activate = finder
    marker = f"agent-office-{os.getpid()}-{int(time.time() * 1000) % 1000000}"
    if not tty_write(tty, "\033[22;0t"):       # 지금 제목을 쌓아 두고(끝나면 되돌림) 표식을 건다
        return False

    def find():
        # Claude Code는 일하는 동안 제목을 계속 다시 써서, 볼 때마다 표식을 다시 건다
        tty_write(tty, f"\033]0;{marker}\007")
        time.sleep(0.04)
        return find_win(marker) or (find_win(title) if title else None)

    hit = None
    try:
        for _ in range(4):                     # 지금 보이는 탭이 그 탭인지 (제목이 반영될 때까지 잠깐 기다림)
            hit = find()
            if hit:
                break
        if not hit:
            for path in gt_windows(service):
                # 방법 A: active-tab 을 0, 1, 2… 로 불러 본다 (탭 개수를 넘는 번호는 무시돼서 상태가 안 바뀜)
                def active():
                    return re.findall(r"<(?:int32\s+)?(-?\d+)>", gt_action(path, "Describe", "active-tab"))

                orig = active()
                if orig:
                    for i in range(0, 40):
                        gt_action(path, "Activate", "active-tab", f"[<int32 {i}>]", "{}")
                        if active()[-1:] != [str(i)]:
                            break              # 탭 개수를 넘어감 (탭이 하나뿐인 창은 0에서 그대로)
                        hit = find()
                        if hit:
                            break
                    if not hit:                    # 이 창엔 없었으면 원래 보던 탭으로 되돌림
                        gt_action(path, "Activate", "active-tab", f"[<int32 {orig[-1]}>]", "{}")
                else:
                    # 방법 B: 오른쪽 탭으로 넘기기를 한 바퀴
                    for _ in range(40):
                        if gt_action(path, "Activate", "tab-switch-right", "[]", "{}") != "()":
                            break
                        hit = find()
                        if hit:
                            break
                if hit:
                    break
    finally:
        tty_write(tty, "\033[23;0t")           # 쌓아 둔 원래 제목으로 되돌림
    if hit:
        activate(hit)
    return bool(hit)


def konsole_pick(env):
    """Konsole: 탭마다 넣어 주는 KONSOLE_DBUS_* 값으로 그 세션의 탭을 고른다 (D-Bus라 X11·Wayland 모두)."""
    svc = env.get("KONSOLE_DBUS_SERVICE", "")
    m = re.fullmatch(r"/Sessions/(\d+)", env.get("KONSOLE_DBUS_SESSION", ""))
    if not (m and re.fullmatch(r"[\w.:-]+", svc) and shutil.which("gdbus")):
        return False
    sid = m.group(1)

    def call(path, method, *args):
        return run(["gdbus", "call", "--session", "--dest", svc, "--object-path", path,
                    "--method", "org.kde.konsole.Window." + method, *args])

    out = run(["gdbus", "introspect", "--session", "--dest", svc, "--object-path", "/Windows"])
    wins = ["/Windows/" + n for n in re.findall(r"node\s+(\d+)\s*\{", out)]
    own = env.get("KONSOLE_DBUS_WINDOW", "")       # 탭을 만든 창 (다른 창으로 옮겼으면 달라짐)
    for w in wins or ([own] if re.fullmatch(r"/Windows/\d+", own) else []):
        if f"'{sid}'" in call(w, "sessionList"):
            return call(w, "setCurrentSession", sid) == "()"
    return False


def check_terminal():
    """--check-terminal: 이 리눅스에서 '터미널로 이동'에 쓰이는 것들을 점검해서 출력."""
    st, de = linux_session()
    print(f"화면: {st or '(없음)'} · 데스크톱: {de or '(없음)'}")
    for tool in ("gdbus", "tmux", "kitty", "wezterm", "wmctrl", "xdotool"):
        print(f"  {tool:8s} {'있음' if shutil.which(tool) else '-'}")
    wins = gnome_window_calls()
    print(f"Window Calls 확장: {'동작함 (창 ' + str(len(wins)) + '개)' if wins is not None else '없음'}")
    if wins and not all("title" in w for w in wins):
        print("  창 목록에 제목이 없어요 (오래된 판). 확장을 업데이트해 주세요.")
    print(f"창 제목 읽기(탭 찾기에 필요): {'됨' if title_finder() else '안 됨'}")
    svc = os.environ.get("GNOME_TERMINAL_SERVICE", "")
    gws = gt_windows(svc)
    print(f"gnome-terminal 창: {len(gws)}개 ({gws[0][0] if gws else svc or '-'}) {[w[1] for w in gws[:6]]}")
    if gws:
        print("  active-tab:", gt_action(gws[0], "Describe", "active-tab") or "(지원 안 함)")
        print("  tab-switch-right:", gt_action(gws[0], "Describe", "tab-switch-right") or "(지원 안 함)")
    # 이 점검을 돌린 탭을 실제로 찾아 본다 (제목에 표식 걸기 → 창 제목에서 찾기 → 앞으로 가져오기)
    tty = ""
    if os.environ.get("TMUX"):
        tty = run(["tmux", "display-message", "-p", "#{client_tty}"])
    elif sys.stdout.isatty():
        tty = os.ttyname(sys.stdout.fileno())
    if gws and tty and os.environ.get("GNOME_TERMINAL_SCREEN"):
        t0 = time.time()
        print(f"이 탭 찾기 시험 ({tty}): {'됨' if gnome_terminal_pick(tty, svc) else '안 됨'} ({time.time() - t0:.1f}초)")
    if shutil.which("tmux"):
        rows = run(["tmux", "list-clients", "-F", "#{session_name} ← pid #{client_pid} #{client_tty}"]).splitlines()
        print(f"tmux를 띄워 둔 터미널: {len(rows)}개 {rows[:6]}")
    procs = claude_processes()
    print(f"실행 중인 claude: {len(procs)}개")
    for pr in procs[:20]:
        env = proc_env(pr["pid"])
        keys = [k for k in ("TMUX_PANE", "GNOME_TERMINAL_SCREEN", "GNOME_TERMINAL_SERVICE", "KONSOLE_DBUS_SESSION", "KITTY_WINDOW_ID", "WEZTERM_PANE",
                            "WINDOWID", "PTYXIS_VERSION", "TILIX_ID", "VTE_VERSION", "TERM_PROGRAM") if env.get(k)]
        print(f"  pid {pr['pid']}  tty {pr['tty']}  cwd {pr['cwd']}  {' '.join(k + '=' + env[k] for k in keys)}  [{pr['args'][:50]}]")


def open_terminal(argv, cwd=None):
    """(리눅스) 새 터미널 창에서 argv 를 실행한다. 열 수 있는 터미널 프로그램이 없으면 False."""
    line = (f"cd {shlex.quote(cwd)} && " if cwd else "") + " ".join(shlex.quote(a) for a in argv)
    for term, args in (("gnome-terminal", (["--working-directory", cwd] if cwd else []) + ["--"] + argv),
                       ("konsole", (["--workdir", cwd] if cwd else []) + ["-e"] + argv),
                       ("x-terminal-emulator", ["-e", "bash", "-lc", line]),
                       ("xterm", ["-e", "bash", "-lc", line])):
        if shutil.which(term):
            # tmux 안에서 켠 서버라도 새 터미널은 tmux 바깥으로 (안 그러면 tmux attach 가 거절됨)
            subprocess.Popen([term] + args, env={k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")})
            return True
    return False


def raise_window(chain, env=None):
    pids = list(chain)
    # X11: 터미널이 탭을 열 때 넣어 주는 창 번호(WINDOWID). gnome-terminal 은 창이 여러 개여도 프로세스가 하나라 PID 로는 못 가림
    wid = (env or {}).get("WINDOWID", "")
    if wid.isdigit() and linux_session()[0] == "x11":
        if (shutil.which("xdotool") and run_ok(["xdotool", "windowactivate", wid])) or \
                (shutil.which("wmctrl") and run_ok(["wmctrl", "-ia", wid])):
            return True, "터미널 창을 앞으로 가져왔어요."
    wins = gnome_window_calls()
    if wins:
        for pid in pids:
            for w in wins:
                if w.get("pid") == pid:
                    wc_activate(w.get("id"))
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
    if wins is not None or (st != "wayland" and (shutil.which("xdotool") or shutil.which("wmctrl"))):
        return False, "그 세션을 띄운 터미널 창은 찾지 못했어요."
    return False, linux_hint()


def has_window(chain):
    """그 프로세스 줄기(자신·조상) 중에 화면에 창을 가진 프로세스가 있나. 알 수 없으면 None.
    tmux 클라이언트가 터미널 창 안에 있는지(조상에 gnome-terminal-server 등), 웹 화면의 내장 터미널처럼
    창 없는 프로그램(node 등)이 띄운 것인지 가리는 데 쓴다."""
    pids = set(chain)
    wins = gnome_window_calls()
    if wins is not None:
        return any(w.get("pid") in pids for w in wins)
    if linux_session()[0] == "wayland":
        return None
    if shutil.which("wmctrl"):
        return any(len(c) >= 3 and c[2].isdigit() and int(c[2]) in pids
                   for c in (ln.split(None, 4) for ln in run(["wmctrl", "-lp"]).splitlines()))
    if shutil.which("xdotool"):
        return any(run(["xdotool", "search", "--pid", str(p)]) for p in pids)
    return None


def tmux_pane(env, tty, chain):
    """그 프로세스가 실제로 들어 있는 tmux 패널: (tmux 명령 앞부분, 패널 ID). tmux 안이 아니면 None.
    환경 변수(TMUX_PANE)만으로는 알 수 없다: tmux 안에서 띄운 터미널(이어하기로 연 창 등)에서 켠 claude 도 그 값을 물려받고,
    tmux 를 다시 켜면 같은 번호(%0)가 다른 패널이 된다. 그래서 패널의 tty 나 패널의 셸(조상 프로세스)이 맞는지 본다."""
    if not shutil.which("tmux"):
        return None
    sock = env.get("TMUX", "").split(",")[0]
    for base in ([["tmux", "-S", sock]] if sock else []) + [["tmux"]]:
        rows = [ln.split() for ln in run(base + ["list-panes", "-a", "-F", "#{pane_id} #{pane_pid} #{pane_tty}"]).splitlines()]
        rows = [r for r in rows if len(r) == 3 and r[1].isdigit()]
        for r in rows:
            if tty and r[2] == tty:
                return base, r[0]
        for r in rows:
            if int(r[1]) in chain:
                return base, r[0]
    return None


def focus_linux(p):
    pid = p["pid"]
    env = proc_env(pid)
    chain = ancestors(pid)
    tty = "/dev/" + p["tty"] if p.get("tty") else ""
    picked = title = ""
    # 1) tmux: 그 세션이 있는 창·패널로 전환. 그다음은 tmux를 띄운 쪽(클라이언트)의 터미널을 찾는다
    tp = tmux_pane(env, tty, chain)
    if env.get("TMUX_PANE") or tp:
        print(f"[터미널로 이동] tmux: 환경 변수 {env.get('TMUX_PANE') or '없음'} · 실제 패널 {tp[1] if tp else '없음 (tmux 밖)'}")
    if tp:
        base, pane = tp
        if run_ok(base + ["select-window", "-t", pane]):
            run_ok(base + ["select-pane", "-t", pane])
            picked = "tmux에서 그 창을"
            # 그 tmux 세션을 지금 띄워 둔 터미널(클라이언트) 중 가장 최근에 쓴 것
            sess = run(base + ["display-message", "-p", "-t", pane, "#{session_id}"])
            rows = [ln.split(None, 2) for ln in run(base + ["list-clients"] + (["-t", sess] if sess else []) +
                                                    ["-F", "#{client_activity} #{client_pid} #{client_tty}"]).splitlines()]
            rows = sorted((r for r in rows if len(r) == 3 and r[1].isdigit()), key=lambda r: r[0], reverse=True)
            # 창 없는 프로그램이 띄운 클라이언트(웹 화면의 내장 터미널 등)는 갈 곳이 없으니 뺀다.
            # 창이 있는지 알 수 없는 환경(Wayland 에 Window Calls 없음 등)이면 예전처럼 다 남긴다
            shown = [r for r in rows if has_window(ancestors(int(r[1]))) is not False]
            if rows and not shown:
                print(f"[터미널로 이동] tmux 클라이언트 {len(rows)}개가 모두 터미널 창 밖 (내장 터미널 등)")
            embedded, rows = bool(rows) and not shown, shown
            env, tty, chain = {}, "", []       # 패널 안의 값은 tmux 서버를 켠 때 것이라 믿을 수 없다
            if rows:
                cpid = int(rows[0][1])
                chain, env, tty = ancestors(cpid), proc_env(cpid), rows[0][2]
                # tmux 가 터미널 제목을 직접 정하고 있으면(set-titles) 그 제목 — 탭을 찾을 때 표식과 함께 씀
                tt = run(base + ["display-message", "-p", "-t", pane, "#{set-titles} #{E:set-titles-string}"]).split(None, 1)
                title = tt[1].strip() if len(tt) == 2 and tt[0] in ("1", "on") else ""
            elif sess and open_terminal(base + ["attach-session", "-t", sess]):
                return True, ("이 tmux 세션은 터미널 창 밖(내장 터미널 등)에서만 열려 있어서, 새 터미널 창에도 열었어요."
                              if embedded else "이 tmux 세션을 띄워 둔 터미널이 없어서, 새 터미널 창에 열었어요.")
            else:
                return False, ("이 세션은 tmux 안에서 도는데, 그 tmux를 띄워 둔 터미널이 없어요. "
                               "터미널에서 tmux attach 로 열어 주세요.")
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
    # 4) gnome-terminal이면 그 세션의 탭을 찾아 띄운다 (창 제목을 읽을 수 있어야 함)
    gt = bool(env.get("GNOME_TERMINAL_SCREEN"))
    if gt and gnome_terminal_pick(tty, env.get("GNOME_TERMINAL_SERVICE", ""), title):
        return True, "gnome-terminal에서 그 탭을 띄우고 창을 앞으로 가져왔어요."
    # 5) Konsole이면 D-Bus로 그 탭을 고른다 (창은 그다음에 앞으로)
    if env.get("KONSOLE_DBUS_SESSION") and konsole_pick(env):
        picked = "Konsole에서 그 탭을"
    # 6) 창 자체를 앞으로
    ok, msg = raise_window(chain, env)
    if ok:
        if picked:
            return True, picked + " 고르고 " + msg
        if gt:
            msg += " (그 탭을 찾지 못해 창만 가져왔어요. --check-terminal 결과를 알려주시면 고칠게요)"
        elif env.get("PTYXIS_VERSION") or env.get("VTE_VERSION"):
            msg += " (이 터미널은 바깥에서 탭을 고를 수 없어서 창만 가져왔어요)"
        return True, msg
    if picked:
        return True, picked + " 골랐어요. 터미널 창은 직접 눌러 주세요. (" + msg + ")"
    return False, msg


WINDOW_CALLS_UUID = "window-calls@domandoman.xyz"


def install_window_calls(marker):
    """GNOME 기본 설치 창으로 Window Calls 확장을 설치 (사용자가 '설치'를 눌러야 진행, 로그아웃 불필요)."""
    try:
        ans = input("    GNOME 'Window Calls' 확장을 지금 설치할까요? GNOME 설치 창이 뜨면 '설치'를 눌러 주세요. [y/N] ").strip().lower()
    except EOFError:
        ans = ""
    if ans in ("y", "yes", "ㅛ"):
        out = run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell.Extensions",
                   "--object-path", "/org/gnome/Shell/Extensions",
                   "--method", "org.gnome.Shell.Extensions.InstallRemoteExtension", WINDOW_CALLS_UUID], timeout=180)
        if "success" in out and gnome_window_calls() is not None:
            print("    설치했어요. 이제 '터미널로 이동'이 동작해요.")
        elif "cancel" in out:
            print("    설치를 취소했어요. 나중에 Extension Manager 앱에서 'Window Calls'를 찾아 설치해도 돼요.")
        else:
            print("    자동 설치가 안 됐어요. 'Extension Manager' 앱(sudo apt install gnome-shell-extension-manager)에서")
            print("    'Window Calls'를 찾아 설치하거나, extensions.gnome.org/extension/4724/window-calls/ 에서 설치해 주세요.")
            if out:
                print(f"    (GNOME 응답: {out.strip()})")
    else:
        print("    건너뛸게요. 다음부터는 묻지 않아요. (다시 물어보려면 .agent_office_setup 파일을 지우세요)")
    try:
        with open(marker, "w") as fh:
            fh.write(ans or "n")
    except OSError:
        pass


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
    marker = os.path.join(HERE, ".agent_office_setup")
    if os.path.exists(marker) or not (os.isatty(0) and os.isatty(1)):
        return
    if st == "wayland" and "GNOME" in de.upper() and shutil.which("gdbus"):
        install_window_calls(marker)
        return
    if st != "x11":
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


CODEX_APP = "com.openai.codex"            # Codex 데스크톱 앱 (macOS)


def focus_codex_app():
    """터미널이 아니라 Codex 앱에서 도는 세션: 앱을 앞으로 (대화까지는 고를 수 없음)."""
    if SYSTEM != "Darwin":
        return None
    try:
        ok = subprocess.run(["open", "-b", CODEX_APP], capture_output=True, timeout=6).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    return (True, "Codex 앱을 앞으로 가져왔어요. (대화까지는 고를 수 없어요)") if ok else None


def proc_info(pid):
    """PID 하나의 정보 (claude_processes 항목과 같은 모양)."""
    if SYSTEM == "Windows":
        return {"pid": pid, "ppid": _parent(pid), "tty": None, "start": None, "args": _cmdline(pid), "cwd": None}
    fmt = "pid=,ppid=,tty=,lstart=,command=" if SYSTEM == "Darwin" else "pid=,ppid=,tty=,lstart=,args="
    parts = run(["ps", "-o", fmt, "-p", str(pid)], env={**os.environ, "LC_ALL": "C"}).split(None, 8)
    if len(parts) < 9:
        return None
    try:
        start = time.mktime(time.strptime(" ".join(parts[3:8]), "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        start = None
    return {"pid": pid, "ppid": int(parts[1]), "tty": None if parts[2] in ("?", "??") else parts[2],
            "start": start, "args": parts[8], "cwd": None}


def hook_process(m):
    """hook 으로 기억한 PID 가 지금도 이 세션의 프로세스일 때만 돌려준다.
    그 프로세스가 죽고 같은 번호를 다른 프로세스가 받았거나(기억한 뒤에 켜짐), 다른 세션으로 넘어갔으면 아님."""
    key = m.get("key") or ""
    h = hook_pids.get(key) or {}
    pid = h.get("pid")
    if not pid or not pid_alive(pid, h.get("src")):
        return None
    p = proc_info(pid)
    if not p or (p["start"] and h.get("at") and p["start"] > float(h["at"]) + 5):
        return None
    if hook_owners().get(pid, key) != key:
        return None
    return {**p, "how": "hook"}


_resumed = {}                 # 세션 → '터미널로 이동'으로 이어서 연 시각 (연달아 눌러도 한 번만 열리게)


def resume_ended(m):
    """'터미널로 이동'을 눌렀는데 도는 프로세스가 없을 때: 끝난 세션이니 새 터미널에서 이어서 연다."""
    key, now = m.get("key") or m["id"], time.time()
    if now - _resumed.get(key, 0) < 20:        # 방금 연 터미널에서 claude 가 뜨는 중
        return True, "방금 새 터미널에서 열었어요. 잠깐만 기다려 주세요."
    try:
        busy = now - os.path.getmtime(m.get("file") or "") < 30
    except OSError:
        busy = False
    if busy:                   # 기록이 방금까지 쓰였으면 어딘가에서 도는데 못 찾은 것 → 하나 더 열지 않는다
        return False, "방금까지 일하던 세션인데 터미널을 찾지 못했어요. 끝난 세션이면 '이어하기'로 다시 열 수 있어요.", {"gone": True}
    ok, msg = do_resume(m)
    if not ok:
        return False, "끝난 세션이에요. " + msg
    _resumed[key] = now
    return True, "끝난 세션이라 " + msg, {"resumed": True}


def do_focus(m):
    """hook 으로 알게 된 PID 가 있으면 그걸로 정확히, 없으면 Claude Code 가 적어 둔 pid 파일·폴더·시작 시각으로 찾는다.
    도는 프로세스가 없으면(끝난 세션) 새 터미널에서 이어서 연다."""
    h, f = hook_process(m), find_process(m)
    p = h or f
    if (h and f and m.get("src") != "codex" and f["pid"] != h["pid"] and f.get("how") != "같은 폴더 (짐작)"
            and (f["start"] or 0) > (h["start"] or 0)):
        p = f                              # hook 은 마지막으로 소식을 준 프로세스만 기억함: 같은 세션을 나중에 켠 프로세스가 있으면 그쪽
    print(f"[터미널로 이동] {m.get('key') or m['id'][:8]} → " + (f"pid {p['pid']} ({p.get('how')}, {p.get('tty') or 'tty 없음'})" if p else "도는 프로세스 없음"))
    if not p and m.get("src") == "codex":
        return (("desktop" in (m.get("app") or "") and focus_codex_app())
                or (False, "실행 중인 Codex를 찾지 못했어요. 끝난 세션 같아요."))
    if not p:
        return resume_ended(m)
    r = focus_mac(p, m) if SYSTEM == "Darwin" else focus_windows(p) if SYSTEM == "Windows" else focus_linux(p)
    print(f"[터미널로 이동] {m.get('key') or m['id'][:8]} → {r[1]}")
    return r


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
    if open_terminal(["claude", "--resume", sid], cwd):
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
    "id": "/",
    "launch_handler": {"client_mode": ["focus-existing", "auto"]},
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
    "iVBORw0KGgoAAAANSUhEUgAAAMAAAADACAYAAABS3GwHAAAQAElEQVR4nOydB5gUVbbH/9VpuidnhklkUIJiBhbf0xUFBVFXBWRR"
    "14xhddVlTbsqi2FXwYCrsk9Mq2JYREVBXRHRJSuKkhkYwuSByaG7p0O9e2oYZrqruqd7Qk9Vzf19X33dfau6u+rec24499xzTVAB"
    "oqN2qEfwDBdEsQ9EIUMEvYoZoiD0EYA+7IoMQIgBR0OIDazMSkWgjJVrKQShTGCfIYhlrFxLjaJxl2CN34seRkAPITbVnOH2eC5j"
    "7y5jGXMCOL0OVtHtZiK4zGQ0fCRYEn9ADxAxBRBF0QhH9Xi36L1MEIRLWVI/cDitHGIy8pFJMHwEa+JaJiNeRIBuVwBRrEp0O8T7"
    "BBE3s39LBofTHqJYzrpJr5ishgWCkFiFbqTbFIBps81rr7qL9QHvY/+SCA4nXERUMQH9u8GWtJC1CHZ0A12uAEzwTV5n1Q2iV3yY"
    "DXwyweF0FlEshgFzjVHJrzFFcKML6TIFYIIveOyVV4oC5rFB7VBwOF0MGzTvZV3pPxttyUuZIojoArpEAZjwx3nsVUvYr00Bh9Pd"
    "iPjMaEuayZSgDp2k0wpANny36FrOav1h4HAiBGsN9pgE89TOziUY0AncjsrJHtH1PRd+TqQhmSPZIxlEJ+iQAlB/32WvmMvU8FN2"
    "K/HgcHoEJntMBpksPkoyiQ4Q9pd4f5+jSjo4LghLAXh/n6NmOjIuCLkLJJk5RddCLvwctdI8LnA/F053KGQFcDurnmR/MREcjrq5"
    "sFlWQyMkTXHbK25gly4Gh6MVRHG6KTrlg/Yua1cBxMaKcR5BWMPemsHhaAbRbjQaxgmWpK3BrgqqAEz4sz0QfmRXpYHD0R4FRlEc"
    "J0SnFAa6IOAYgA0krG4In3Lh52iYHCbDy0mWA10QUAHYDNv9goDR4HA0DJPhU0iWA55XShTFiniPXTjMziaAw9E6IqqNNvQXhOQa"
    "/1OKLYDbgXu48HN0gwBalXi38ik/RLG+j8fetIcrAEdXBGgFZC2A2+58gAs/R3cEaAV8WgCp9nc4D7JkKzgcvSG1ApYTBSG2tCXJ"
    "pwWQan8u/By9Qq2A3Xm/b9IxmK3U7HFUHuX+/RxdI6LGaEtKEwTBRR+PtwBuZ+V5XPg5uoeNb5tlvZnjCiCIUrQ2Dkf/eDGp5a2p"
    "TfIkcDi9AaFV1qUWQHTWUnBaHquT0yughTPHZL5ZAbweN+/+cHoVLTLfrAAQuQJwehUtMi+wya8Mj6OpGD24VwCH0wOIRmtUlsHt"
    "dJLLMxd+Tm9DcDsdJxsE0ZABDqcXQrJvEqS9uKA7tv2yDSs+WwGLxYJLLrsEgwYNAid09u3bj0+WfQSX240pF0/ByFEjoTdI9gVX"
    "Y8VzbFr4LugIURQxccJEHDly9Hja9TdchzvuvAPsWcEJDOXdC8//A6+/9vrxtLS0VHy56kvd5R171ucN7KF01wXa8sMWH+EnXnv1"
    "ddx91z2w27tloxFdQHlDedRW+AnKyy1bfoTeINk3iIDuFGD3rt2K6d+u+RY3/O4GlJeVg+ML5QnlDeWRErt37oLeINk3sEatP3RG"
    "YWHAKBjYxZRj1sxZAZWkN0J5MWP6VVLeBKKoqAj6Q8ygiTDdtQBFxcVBz1OTft2112PNN2vQ26E8uPbq36GqMvhmjO3lqRYRREFS"
    "gCjojOLC9msrh8Mh9XdfXfwaeiuLX3lVyoOmpqZ2rw0lTzWHgIRO7RCjVgrDKKx/LPwHHrz/IbhcLvQW6Fnn3PsnvPjCiyF/p6Cg"
    "EHpEdwpQWVmpWKNd9z/pAb/z+crPccuNt6C6qhp6h57x5htuxqqvVimejzIJ+J1CXlGeVlV1657VPYLuFKC4SLmvevXZ6Xj9liFI"
    "jDEqnv/pp62YedVvceDAAegVerYZ067C1q0/K55PjTNh0Q2DcU2AyqJIh90g3SlAkYICxNkMiDIbMLSvDW/MHooB6crDnpLiElw9"
    "8xps2rgJeoOe6bczZqGsrEzx/JAMKxbfPETKoyiTAfFWuWgU63AgbILOUDLXZSZYjr9PizNj8U1D8NAHh7AxT76dVENDA26bfTvu"
    "f/B+XDntCnQltbV1bLKpUZpwcjicxyflbDYbrNYo6dVmi0Z8fBy6kveWvIenn5oPr9ereH78sHjMvSIXVnOr0GckWlBb6vC5rqiI"
    "K4DqUaql+iZbfD5TQc+f2R+LVpXi7XVHZNeToDzx2BPYu2ePpAhGoxGhUFZaKnUzDh8uZF2xIhSyo4QJDQ0g6+rC29OZlCA7JweZ"
    "mZnIymJHdjZyc7LRf+AA9OnTJ6Tf8Hg8+Ouj87D8k+UBr7l6fBpuOS9D5ubQN8mCvX4KUMwVQP0UFcoLKSPBIkujAr/1/L4Y2MeK"
    "xz8ugEehclz67w+ZMBdgwbPzERsb63Pu4MGD2MrGDXl79yEvLw+72ExpfX09ugpqLXbu2Ckd/tC9DB8xHIMHD8bQYUMw+pTR6NfP"
    "d0Ur3ctdv/8DfgzgwmAyCnjwkmxMPClJ8Ty1AP7ocTJMdwpQotQCJFkCXk8CkMnOz3nnIOocHtn5zZs2S+OCF1/+B+wOO776zyp8"
    "zSwo5C3ZU5Bw033R0cKQIYMx4YIJmDhpIswmM2bfPDug6TLeZsRTrAUclRMT8D8yFRSAxkh6Q3DbK0XoiNNGny7r61J3Z+zQ4CGP"
    "SqqbcNe/8lFU6WtCJe9ImjExGIRj79UPtW5esTkPBL+1TrmpUXhm1gD0TbQE/Y31e2ox592DPmkGgwFbtv4APaErKxA5dCkN9DLa"
    "KWyCBILMpKP7xZDUS0eLwFP3uKuFP8YMjMs1SkdMF+++RvcqCb7Y8ijNz3L6wFhmABjcrvATGUnym6K8PVJ+BHpCV12gQP4qmcnt"
    "FzhhYrX8/54Qj11FDXC6O7ZONMZiwPCcaCTHmJDC7OqpsWYkxZqkz9HsXHSUkQ3CBTjKS+FxuaXvGM0mWNMz4HCJaHR60NjkRUW9"
    "G1XsqGhwoaLOjUr2fmdhIxqavCHfS+vAVpD+82xm7YmJCm1An5WsbCqmPE5L18+uWbpSgGKFQVpStEmyawfD4fLio81H8c76o6hq"
    "cCMcEqONGN0/BqNzY3AKex3Ux4a66lpUldOsaRMS02KQkOwbbd7ldOKwq/V/SBFSbIA50TcucU1FNaqPNkjvk9NTEZsYh/1ldvx0"
    "sAFbDzdIrzWNHoQCKdeznxfjrbXlmMUsP1NPTZHmRgJBeUbPVu33+5THo0efDL2g+xagb5Da385q2w+/r8C764/ICjoQcVHNAn/a"
    "wBic2j9WEvi2iNRNKKZuQnPtW1FWgbiEWBjamFLdLvl/UZq5TaXrZSZM+m5Lz6u8uByxCXEYnBEtHVeOSZO6NfnlDvx4sB5b8plS"
    "MIWocwZ/jqOsNXnu8xK8+d0RzPpVGi49I8XH/t8WMh5UN/ouINLbXIC+WgAFE2jfBOUO9rc7a/D0iqKQa/xLT0vGRaOTMCKI5YRo"
    "ctIgurXzJHpF2BsdiIkL/j1/HOw7vsMOQfLHibK2agl1cUgB6bjyrOZuyY6CBqzcWoWPt1QG/X167hf+U4J3NxzBnClZbDJMvicK"
    "jRV2FfkqQLHOTKH6UgClFsBvwFdV75IE/9tdtWiPDKY8vzkzBRez7gKZDkPBoDBp5nGH160i3C63wm+3b7MgBaXjlgl9sXxLBZZt"
    "rkBZbWBPV2oR7nv3EH49IgH3Ts5k3Z7WCkPJFFqsM1Oo7scAmW2sGZ/8UIGXvyptt5uQk2LBTef2wXkjkxAuZjMpQLPptAV3U2jd"
    "q7bIFUBk9v3QlJAghZ01Pl06Vm2rxuI1pSioCOz3v3pHDX7YX4c7JmZi8inJUprS/AlvAVRMSUmpLE3yabG78fDSw/h+f/CZ2iym"
    "LNef0wcXjEqS7P4dQjDAyATV42611rjd4a818B8n0G/Sb3eECaMSpRr+y1+q8Pq3ZSiqUr6fWocXT3xSiG9Y9/DRy3MVzce8BVAp"
    "paWlinMADU4vZr24VzIrBiI93iz5wE8+JQkmY+enRkxmM1MA5/HPHlcHWgA/paHZ3c5ACn3h6GScz5RhxU+VeOPbcpTXKefJhrw6"
    "XP3SXvx+ony1LOUx5XVGhj5W0upGAfxXgbVMXD3Can5vgDksNrcrDR5nT8gIahIMFxOrrZ1tPrtcnR8D0FxBV0AKfsnpqZh0cjJe"
    "WlWCpZsofIy8tStn44ZHPyw4NhAXfZzlyBLEFUBltO2bts7gCgGFnwa4D/8mByf3i0VX4y+s7o4Mgt2+rYbJHHr/PxRI4e++MItN"
    "/CVg3rLDiq0BOQgKzRPKPpSW6KcbpBtXiOKi1kIhwQ8WxWziSYl4+/ah3SL8hNlPAcgUSq7JoULXin6aazJ3T1116oBYvPP7YdIY"
    "IRD+/kQFh/WzPlg/LUAIq5WizAIeujQH541IRHdiNMmz1dPkhjFEU6pHYYG+0dx9RRVtMWLelf0wdkglnmEmYrsruN+TnlaG6aYF"
    "ONjOWt7Bfax469ah3S78hFlBWMPpBinNFJvN3V9XXcQGyW+yPBqQFjxSzsEDB6EXdKEAFOlgh8LCkRYuYJYPKthADl5djbHTCuAO"
    "6Te7A8qjt28fJuVZIGiRTm1N+xOJWkDzCuB0OqXFH4HWu158arI02I0krZNhrYQzGdbZSbCugPLs0tOTFc95vB7cftsdUnAxraNp"
    "BaDB4j1/uAd79uxVPE+xgO6fmh35sN7HJsPaEs5kWFdOgnUUyrM5U7IDxlPavm07/njPnIAVj1bQtAI8/OdHsH7dBsVz912chRt/"
    "3XO2apoMa0vbmWFLFM2wtm0hxGNpx671+JtAe85WQXl456S+iufWrV2Hx+c9AS2jWQWgBesrV6xUPHfH+RmYeloKehJbtK9vf5S1"
    "VcCpPx8TTybYZiWg9237+BarrwtCdEw0epLpY5ojRyix7MNl+Pijj6FVNLkm+NDBQ5h2xXTFEIjkskymzp7GzUyZtC6gsd6O2IRY"
    "pKQnw2Qx+13jltYs+qe7mlyoLK9EfU09omNtSM9Mj9ggOBgUPYNcrf2x2qz494cfIDs7G1pDcwpAgV2vmj4T+xWiMpwxMBYLZg2A"
    "0RDhPn8vwcMm5+58Mx9bDzXIzp1w4gl4651/wWTS1tSS5rpAC599XlH40+LNeHx6Py783Qjl7ZMz+iE5Vi7ktMnGiwtDjzatFjSl"
    "AHt278Hbby+RpZOR5wkm/KEu+OZ0nHibic0a5yqee+ONN5G/Px9aQlMK8Ni8xxXTr/vfPhie1bMDxd7E6H6xuPZs5cgQjz+mLauQ"
    "ZhTg66++lmzP/pyYZWMKkA5OZCHz6PAsmyydQjEG2mhPjWhCAWjgO//pBbJ06u7TyiUD3/s34lCe/+U3uVAaci1gZRWO92tPogkF"
    "eHfJe9IqJH8uOyMF2cm62+JMM+SmROHi0+TuEhST9P333ocWUL0CkBPZawob2UVHGXDjuaGFCed0HzedmyFFnfPn9Vff0ISbhOoV"
    "YPXXq1FTUyNLJx8V/9aKPQAAEABJREFUskhwepakGBOuOVs+Bjt69Ci+/Ub9YwHVKwC5PPhDtf8VZ6WCow6mj02TFhv5s3Tph1A7"
    "qlaAkpISfL/5e1n6xackwWLS5Q6vmoRCK04ZLY+htH7detWHUVG1FH366WeK6ZefyWt/tTFtrPK8wJdffAk1o2oFWPfdWlka+ftk"
    "ccuP6iBrnLS3gh/r/rsWaka1CkCbyv3yyzZZ+oSR3b+ml9MxzldYRkn7L4e7QWAkUa0C/DdAzTH+hHhw1Mm4ofLtXckUunH9BqgV"
    "1SqAUvdnUB8rEqO56VOtpMdb0C9NHk907dr1UCuqVYCff/5ZljZ2cNduIM3pesYMlrfQP2/9GWpFlQpAvj9KO5GMzOEen2pnlEIZ"
    "FRQUKK7eUwOqVIC8vXmK6QPSreCom4Fp8jKicYBag2mpskOdny9fVEE7m/eU41t5TRM27quT7oF84TOTQtt1MtKo4T6zU6JgZv/v"
    "8viutM3PP4Chw4ZCbahTAfbLwxwOTo+88FOU6YVflOADKYR4K9POSpVChQgqccNW033SsknajHt/mW/QrAMqXSmmyi5QWVmZLG1A"
    "ug2RxN7kwcP/PiwTKoLS6FyTu+e9HdV4nwMVKqtShTJVA6pUgMbGRllaWnxkGyvaHXH1zpqA5+nc9oJG9DRqvM/UOPluNkplqgZU"
    "qQANDfKwG1ZzZG/1n6vbd+J6dU3P12pqvE+bRR6cQKlM1YBmWgBygY4UFXUuVmva272O4uPU2ntu6Z9a79Om4BrdyBUgdBoa5AoQ"
    "yRagoiH0UOalNT1n31brfVoVWgDeBQoDpY2lI7nwvaIudMEK59quRq33qbSdWVNT+FvFRgJVmkFt0XKLD213GilGZIc+4xzOtV2N"
    "Wu+zUaGsbDZ1TmKqsgWIiZYXVkNT5PqwtMt6bAhjDloPG2/ruWh0ar3PegUFiInpng0JO4sqFUApHLjdEVlb9nmj2l93MFlhGWCk"
    "UeN9NjjllVVMbAzUiDoVIFqeWY1NkbW23HRuH8RYAmdPYrQR1/xPz0ekU+N9NiooQGwMV4CQ6ZMuX19KO5dHkqQYM56/dqAkQP5Q"
    "2vzfDlBFMF413md5jbys0tPVGb5SlYPgfgMGyNIOlEd+Q7YTs6Kx6IbBeHttOTbtb17Wd9agOMwan46cFPWsS1bbfSqVVf+B/aFG"
    "VKkA/fv3k6UVV7skn5ZIh0MhAXrgkp7fcaY91HKf9iYvyhVMrv0VKjU1oMouUP/+/RXT95W2P+vJ6VkCldHQIUOgRlSpAKlpqcxs"
    "Jh807ShS52wip5XtBXKXh+TkZMW5HTWg2jXBI08aJUvbmKfe8BqcZjbtr5eljRw1EmpFtQowduwYWdqWAw2q8MHvKvaU2LFXR906"
    "KhulDfTGjDkLakVTCkDL7H4+1DGvQtFjhOiMh2hPgrcxFWJjGntNhuhIhNgUTbuVdiluJgz/2VbF7rde8TwJy9xlhzB36WH2XMpK"
    "vZV996tt1XB7ulbp6Vnpmb32xOY8kPIiVcobKY+8HTObbsmvly2FJMYolKVaUG2QHVo/mpSchKpK331pV22vxhmDwgiP4jFLQg5P"
    "ax9U8HuVcLohWpiwWmq6ZAnhX5Yewne769h/iHh65gCMHeobLmTRqhIcOtLsofnPr0txxwWZPufX76nFnHcPSHe5Zlc8Hp/WH52F"
    "lk6iKYE9K+Wf0ef5ffOCVQrGRgjWGnZZ6PMvq3ZUy9LI/j9goDotQISqY4OOGzdOlkYKQKa2UBA9Fngb0n2EP/DFpuaCt6e2bODe"
    "YY6ySTsSfulnmWg9wmr5ggrn8fNUq7+/seL453fXH8XqNsJz+IgTjyw7jBaxXLOzFtWNnZsIlFo4R5r0jCT87eKJlvJOdJsRCuT+"
    "8PV2+cq0sePGQs2oWgEmTZooS3O4RKzYWolQEO0pTITCa84FdwxEV+csFqnxZpw+oNWK1cAU9g//ysfHP1Sw2r4ET35SIPsO7cK+"
    "eHUpln1fgbveyvfxqKSAwInRoQliQOiZXOF5hFLeiY7QInF/9mOlYvdn0oUXQM2oeqd4arIvmjhZtj/YwHQr3rqtnRAbXhPE+kx0"
    "CFMDhOgKdIby2iZc82Ie6pyd82GKsxnw1q3DpI3AO4PYmMIGJh3zxxFii1lVGXw9wbSFu1FU6bvoJjs7G8tXfKKa6BlKqLoFoIy7"
    "cvqVsvR8NtW+7XDwwbAIDzs6OHg0dH7xCMXJXHB1f6THBR5mUTjxk3ID18oZCWY8d/XATgu/RAefifJQRPDv/nSwXib8xLQZ01Qt"
    "/ISqWwCiuroaE849X7btJnULnrtmYNDvivZk1uyH54cuCl5W+5dAMHaN9ymtxX3juzJ8uLmCWXOaszo51oQbzumDS05LlvrmH7Gu"
    "0Wtrylg/v/k/LUYBV4xJwbVnpyPW2kV2CtYieuszWLcmzDrPwgby1qqgl8x+dR+2+UWeMJvNWP3t14iNVec6gBZUrwDE/X96QHGn"
    "kadm9sOvhiYE/iKZ+xxJTAlCtBoJTABtZRBMXb98sM7hwTdsoJsaa8aZg2NhMvoKIplNN7NJpMoGN84ZHt91gt8GGtCK9nQIYojj"
    "IjMbyFsrg9bia3bW4KEPDsnSp14yFXPnPQq1owkFyN+fj8svu0KWnpVswZLbh0mhAIMhui1sYMuUwB3NCl9+rWhwQaDCNrO+v0H1"
    "2dEpRK8AwRUDL8sPwSvvWokCs1uZGiXhF0zBF9LTXMb0hXtkruoGgwEfLf8IubnqdyLURLD9gYMG4vIrfoMPly7zSad+56trSnHL"
    "eX2Dfp8KUjBVsO4GG9hS7ScaqKTZCa9U6xt0LvRtkRQ8qh4GdlAeSJNelB9M8Ck/BJYfoXbbX/mmVHGdBvX9tSD8hCZaAIImxC6a"
    "NBkOh6+vORXWy9cPwqgcda440ivbCxtwy+L9snRyYlz55QrEx2tjJx/N7DVKs8I3z75Zlk6DSJpoCnVyjNN5aNLrLx8cVjx3y623"
    "aEb4CU1ttnv1NbMwePBgWXpZjQvPrCwEJzLM/6xIsesz7IRhuGrmDGgJTSmAyWTC0888BYtFHvd+5dZqdoQ2Q8zpOJ9sqcB/tsl9"
    "fqhMFjwzXyojLaG57dZptdjd996teO7JTwqxIa8WnO6B8vZpVvsr8af75iArOwtaQ3MKQMy4arqii62XjQcefP+Q5GfP6VooTylv"
    "ldzGx589HpdfeTm0iGasQP7U1tZi1syrUXBY7liWEG3EazcPQUaiOrcy0hql1U24/v/yUNMonx3PycnGkveXqH7GNxCabAEIsjQs"
    "+ufLiIuTz/JSQd32+n4UV6lzZ0ItUcKE/9bX9isKf2JiIha98k/NCj+hWQUgMrMy8cJLL0h+J/6QZeimxXk4cCTy8YT0wqGjDtz4"
    "Sp6ixScqKgovLXoRmZl9oWU0rQDEySefhCf+9oTiueoGj+SotbuYR5MIl72sz3/z4n1SHvpDvkHzn3kaJw4/EVpH8wpATDj/PPz1"
    "sbmK5+odXvz+zXys21sDTmj8d3cN60Luk/JOiceemCcNfPWAZgfBSnzx+Zd46IGHpI2Z5Yi45ux03HRuBgwGdfuo9xReZkaj9clv"
    "ryuH3yphCaPRKNX855x7DvSCrhSAWP31atw353643couzbQI5ckZ/RBv09aETXdT1eDGnz84pBjWhKAJrmcXPovx438FPaE7BSA2"
    "btiIO++4Cy6X8kJy2jDivqlZOHtYAjjA+r21eOzjAkVLD0FGBjI2nHXWmdAbulQAYsuWH/HHe/6I6qrqgNecPyoBd1+YxeYNemdr"
    "QJEmFnxWHHSf4cSkRDz7/LMYPfpk6BHdKgBx9OhR/OHOu7Fj+46A11AM/XsuysR5I3t+t5dI8uUvVXju8+Kg26eOGDkCz7FuT2pq"
    "aJEhtIiuFYCgscCCpxfgvXffD3odLU6/c1ImTszsuU3vIgH58S/8ogQ7CoObhq/67VW45967NefcFi66V4AWVn21Cn9+8C9wOp1B"
    "rxs3NA6zf52BQRnqjGbcUfaX2vHSqhJs3Fcf9DqrzYp5j/2VmZYnoDfQaxSAKCwsxNxH/oofvv+hnStFnDEwDpednoLxJ8TDqFGz"
    "KcUU/W53rRSQiwILt8fpZ5yOufPman52Nxx6lQK08OnyT7Fg/jOoqW5/cozi+lx8WjIuOS0FKXFdEJ8nAlTUuZjQV2L5jxU4GsIG"
    "2UlJSbh3zj2YPGUyehu9UgEIsg49+8xzWP7J8pC/Q92j8UPjcc7wBNVZjsiiQzFEaRa3vW5OWyh8CfX1ExJ7p0m41ypAC9u3bcei"
    "lxdh3dr1YX2PBs3jh8XjdNZVGta3Z8YL5OP0Q3491u6plQWmao9fjR+H2+64HcN14M/TGXq9ArTwy8+/4KWXFmETm0TrCCdm2TCU"
    "KcKwDCsG97EhN82KOGvXbE9aw2ZpC6uakMcGsuSkRotTdhd3bNEPCf7sW2ereteWSMIVwI+8vXlY8s4SrFzxBZqanOgM8VYDspKj"
    "kJNsQSZ7jY4ywGYxwmYWpNcY9tkrirA30eGB3dX8SpGhi6qcKKxoko7OBti1WKIwZeoUzJgxDUOGqnOzup6iVyoARZ2mWKMtr146"
    "2Hsvs5q0ONI1NNRj5covpDFCYYE2I07k5ObikksvlsLMx8Q0L1qhqG0GIzsEgb0amYXLIL1SutoD2XYHulcAScjZZJibCTkJu9vl"
    "bt4pJQzy8vZhw4YNrHu0Cbt27Qr7+5GCBJh89MeMGYOxY8di8JBBYX2flMBoMkpenyZSDjYJpnel0JUC+Au7x+0J4BrdcaprqrF5"
    "42asX7ceW7f+jJqanl1nkJCQIPnpkH/+mWeeifiErg1KpXel0IUCkJA7HQ64WO3e1QLfHsXFxZIlafv2ndixYzsO5B/othaCBI/2"
    "2xoxYiRGjhwu+epkZUU2FImkCEwhoqxWSTm0jqYVgITd3tgoCb6aOHToEEpLSplylKCkpJgdpWzSrRqNdjscdgfsDjtTWCcbZzTP"
    "zlI8zShrFGxWm+SKEG2zMbt8Ivr2zWBHpjQz27dvX+T2y4WaMJtNsEVHa1oRNKsAJPx1tXWq7Y/3Fkj4Y+NiNasEBojQ5GJZWuzC"
    "hb/noYoo0MIj1cNk3yAKYik0CPVFOepAq2VBsk87I2hSAchPPSZG3777WoDKQLtrBoRSEzNoaVIBCLPFgjhW+zjY4FJtA2G9QwNg"
    "Kxusa7klJtk3sX50qZbtulQAMbGx0nigqalJ6o+6uTJ0CyYm9LRAnkKh62EugGTfxCbAS/UwlKQCoXB9dJAykCKQQnBl6Bwk9CTw"
    "JPh6mxVmlquDJlGgMYC+rClUUFRobTfSIGsF+fx42ryKXlG2/3Bvg1pQwSAc9wlq6xukd1j5sy6Q4C1V2jpUb0hOYOxQGq5JytFy"
    "eDzH3rc6zGkZqgyMkkALxxzhjMfzojcIeTCo8hdEsaGvx+GkbT94vMB2aFES2iWC1IKU4/hBLUrLe7r4mN60KFCg1xZaunYpef8A"
    "AAN8SURBVBeBXql0hGOfJcFlr0LL0XLdsXO9XbBDRDRakxJMghBT4mqs2Mwy8CxwgsKFSz+wCohkvk4qTTYQ/hgcTi+iReabFcBo"
    "4grA6VW0yLykAEJU/G7Wc90DDqcXQLJOMk/vDW1SvwCH0xsQWrv8rQpg4ArA6SWIwnFZP276ZKNis8dedYSl8KD5HB0j1hqtyanM"
    "AiT5cB9vAShBNGAROBwdwya/Xm4RfsJn8ksUK+I9duEwbwU4+kSq/bPJ/t+S4jOrIwgptUwj/gYOR4cIovBkW+GX0vwvYmOBKI+9"
    "8iDThgxwOHpBFMuNtuRcpgA+4f5k8/p0gWAQ5oLD0RFMph/xF34pXeli1goYPI6qPPZ2IDgc7XPQaE0axBRAFjRK0bNLulDEQ+Bw"
    "9ICIB5SEnwjo2miKTn6PvSwBh6NtlhyTZUWCrgFgXSGb21H5owDhBHA4GkOEuNtkTT6V1f4BN1MI6txOXzQJ5ku1GjyL04thMkuy"
    "G0z4iXZXdwjW+D3sqpnsbWSjznI4HcdLMivJbjuEtLyJNSMrWXMyDxyOBhCYAYdkNqRrESJsPCB47FWfsm/0vr00OdpBxAo26J0S"
    "6uVhLYQnXyG3A5v4oJijRpoHvTiLXHpC/U5YK7zph1nTcib7q1XgcFSFuIpkMxzhJ8IOcUDOREZr8iRRwN/B4agAJotPkUz6O7qF"
    "QqdiAbkbK2eyX3idvbWAw4k8Tazfcx3r83d4wrbTwbDExoqxHmApaxoyweFEClEsNgJXCNEpG9AJuiQaHEWXc9udKwQBp4DD6WZE"
    "ET+ZbFGTKagbOkmXhDmjGzHZksYwBbidNBMcTncgiiVMxu5olrXOCz/R5fFAyX/Ia6+8VYRwP/v1NHA4nUXEUQHi3wy25Jfac20I"
    "l24LiMsUIdbrqLqTNVdz2L8kgsMJFxHVrMafb7AmPc8Evx7dQLdHhBbFqkS3Q7yPTU/fyP4tFRxOe7Aan5k2F5uswt8FIaka3UjE"
    "QqLTKjPYK890C8JU9nEq++MR4HCOIQI72MunJlFcDlvypkALWLqaHtsTQLRX9fOK3su9TCHYTYxnSXzf096Fi0nBd4Jg+NQg4mPB"
    "lnQIPYAqNsWgqHRw1uS4RTGX3VAOG/Dkshohh52SXukzu9V4cDSEWMsMIYdZeRawD9IrfWblWWAShAJEJRxuG6Cqp/h/AAAA//+Q"
    "QDHYAAAABklEQVQDAPT2NaENz7Q0AAAAAElFTkSuQmCC"
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


class Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # 브라우저가 받는 도중에 끊은 것(새로고침·위젯 숨김)은 정상이라 로그에 남기지 않음
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


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

    def _host_ok(self):
        """DNS 리바인딩 막기: localhost 주소로 들어온 요청만."""
        return self.headers.get("Host") in {f"localhost:{self.port}", f"127.0.0.1:{self.port}"}

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
        global last_client
        u = urlparse(self.path)
        if u.path in ("/", "/index.html", "/characters"):   # /characters: 캐릭터 설정 페이지 (같은 파일)
            try:
                with open(os.path.join(HERE, "agent_office.html"), "rb") as fh:
                    body = fh.read()
            except OSError:
                self.send_error(404, "agent_office.html not found next to this script")
                return
            if not body.lstrip()[:15].lower().startswith(b"<!doctype"):
                # 문서 형식 선언·화면 설정을 붙여 표준 모드로 (폰에서도 모바일 레이아웃이 제대로 적용됨)
                body = (b'<!doctype html>\n<meta charset="utf-8">\n'
                        b'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                        + body)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            # 위젯으로 끼워 넣기: 내 PC(localhost)의 웹 툴과 --allow-embed 로 허용한 사이트만
            anc = " ".join(["'self'", "http://localhost:*", "http://127.0.0.1:*", "https://localhost:*"] + EMBED_ORIGINS)
            self.send_header("Content-Security-Policy", "frame-ancestors " + anc)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/manifest.webmanifest":
            self._raw(json.dumps(MANIFEST, ensure_ascii=False).encode(), "application/manifest+json")
        elif u.path == "/sw.js":
            self._raw(SW_JS.encode(), "text/javascript; charset=utf-8", {"Service-Worker-Allowed": "/"})
        elif u.path in ICONS or u.path == "/favicon.ico":
            self._raw(ICONS.get(u.path, ICONS["/icon-192.png"]), "image/png", {"Cache-Control": "max-age=86400"})
        elif u.path == "/widget.js":
            self._raw(WIDGET_JS.encode(), "text/javascript; charset=utf-8")
        elif u.path.startswith("/api/") and not self._host_ok():
            self._json({"ok": False}, 403)
        elif u.path == "/api/team":
            repo = norm_repo((parse_qs(u.query).get("repo") or [""])[0])
            if repo and not REPO_RE.match(repo):
                self._json({"repo": None, "members": [], "error": "저장소 이름 형식이 이상해요 (owner/repo)."}, 400)
                return
            repo = repo or DEFAULT_REPO or detect_repo()
            fresh = (parse_qs(u.query).get("fresh") or [""])[0] == "1"
            out = with_yaml_looks(get_team(repo, fresh)) if repo else {"repo": None, "members": []}
            self._json(dict(out, charsPath=local_chars_path(), localChars=local_chars()))   # 저장 위치, 그 파일에 적힌 아이디들
        elif u.path == "/api/me":
            self._json({"login": gh_me()})
        elif u.path == "/api/ping":
            last_client = time.time()
            code_changed_restart()
            self._json({"ok": True, "dir": self.root, "os": SYSTEM, "open": True,
                        "v": html_version(), "boot": BOOT_ID, "hooks": sorted(hook_seen)})
        elif u.path == "/api/events":
            with lock:
                alive = alive_sessions(self.root)   # 먼저: 하루 지난 파일이라도 실행 중이면 읽도록
                scan(self.root)
                if CODEX_ON:
                    scan_codex()
                check_alive()
                try:
                    since = int(parse_qs(u.query).get("since", ["0"])[0])
                except ValueError:
                    since = 0
                out = [e for e in events if e["q"] > since][:400]
                cur = seq
            last_client = time.time()
            self._json({"seq": cur, "events": out, "v": html_version(), "boot": BOOT_ID,
                        "tracked": sorted(hook_pids), "hookSrc": hook_sources(), "alive": alive,
                        "usage": usage_out})
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/restart":                      # 앱의 '서버 다시 켜기' 버튼: 최신 코드로 받고 다시 켬
            if not self._trusted():
                self._json({"ok": False, "msg": "이 페이지에서만 할 수 있어요."}, 403)
                return
            try:
                updated = try_update()
            except Exception:
                updated = False
            self._json({"ok": True, "msg": "새 버전을 받아서 다시 켜요…" if updated else "서버를 다시 켜요…"})
            threading.Timer(0.6, restart_self).start()
            return
        if path in ("/api/characters", "/api/characters/open", "/api/team/refresh"):
            if not self._trusted():
                self._json({"ok": False, "msg": "이 페이지에서만 할 수 있어요."}, 403)
                return
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 65536)
                b = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                b = {}
            try:
                if path == "/api/characters":
                    chars = b.get("chars") if isinstance(b, dict) else None
                    if not isinstance(chars, dict):
                        self._json({"ok": False, "msg": "저장할 내용이 없어요."}, 400)
                        return
                    where = save_local_chars(chars)
                    self._json({"ok": True, "msg": f"내 컴퓨터에 저장했어요: {where}", "path": where})
                elif path == "/api/characters/open":
                    open_in_editor(local_chars_path())
                    self._json({"ok": True, "msg": f"설정 파일을 열었어요: {local_chars_path()}", "path": local_chars_path()})
                else:
                    repo = norm_repo(str(b.get("repo") or "")) or DEFAULT_REPO or detect_repo()
                    if not repo or not REPO_RE.match(repo):
                        self._json({"ok": False, "msg": "팀 저장소를 모르겠어요."})
                        return
                    d = refresh_team(repo)
                    self._json({"ok": not d.get("error"), "msg": f"{repo} 설정을 다시 받았어요." if not d.get("error") else f"다시 받지 못했어요 ({d.get('error')})"})
            except OSError as e:
                self._json({"ok": False, "msg": f"하지 못했어요 ({e})"})
            return
        if path == "/api/hook":
            if not self._trusted():
                self._json({"ok": False}, 403)
                return
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 16384)
                b = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                b = {}
            self._json({"ok": isinstance(b, dict) and take_hook(b)})
            return
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
        if m.get("src") == "codex" and action == "resume":   # 이어하기는 Claude Code 전용
            self._json({"ok": False, "msg": "Codex 세션은 이어하기를 지원하지 않아요."})
            return
        m["key"] = sid
        if not re.fullmatch(r"[0-9A-Za-z-]{8,64}", m["id"]):
            self._json({"ok": False, "msg": "세션 ID 형식이 이상해요."}, 400)
            return
        try:
            ok, msg, *more = ACTIONS[action](m)
        except Exception as e:  # 실패해도 서버는 계속 돈다
            ok, msg, more = False, f"실행 중 문제가 생겼어요: {e}", []
        self._json({"ok": ok, "msg": msg, **(more[0] if more else {})})

    def log_message(self, *args):   # 요청 로그는 조용히
        pass


# ───────── 깃허브 팀: 저장소 기여자 정보 (위젯의 본사 건물에 출근) ─────────
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
GH_HOST = "github.com"         # --github-host 로 회사 깃허브(GitHub Enterprise Server) 주소를 정함


def api_base():
    """깃허브 API 주소: github.com / *.ghe.com / 회사 서버(https://호스트/api/v3)."""
    if GH_HOST == "github.com":
        return "https://api.github.com"
    if GH_HOST.endswith(".ghe.com"):
        return "https://api." + GH_HOST
    return f"https://{GH_HOST}/api/v3"


def norm_repo(v):
    """'owner/name', 저장소 주소(https·git@, .git 붙어도, 뒤에 /tree/… 붙어도) → 'owner/name'."""
    v = re.sub(r"^(git@[^:/]+:|ssh://git@[^/]+/|https?://[^/]+/)", "", (v or "").strip(), flags=re.I)
    m = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:[/?#].*)?$", v)
    return f"{m.group(1)}/{m.group(2)}" if m else v


def gh_repo_of_url(url):
    """git origin 주소가 이 서버가 보는 깃허브(github.com 또는 --github-host)면 'owner/name'."""
    m = re.match(r"^(?:git@([^:/]+):|ssh://git@([^/:]+)(?::\d+)?/|https?://(?:[^@/]+@)?([^/:]+)(?::\d+)?/)", (url or "").strip(), re.I)
    if not m or (m.group(1) or m.group(2) or m.group(3)).lower().removeprefix("www.") != GH_HOST:
        return None
    r = norm_repo(url)
    return r if REPO_RE.match(r) else None
TEAM_TTL = 30 * 60             # 30분마다 새로 받기 (API 한도 아끼기)
TEAM_MAX = 24                  # 본사에 등록하는 최대 인원
DEFAULT_REPO = None            # --repo 로 정한 기본 저장소
EMBED_ORIGINS = []             # --allow-embed 로 허용한 바깥 사이트
team_cache = {}                # repo -> {"at": 시각, "data": {...}}
team_locks = collections.defaultdict(threading.Lock)
repo_of_cwd = {}
_gh_token = None


def repo_of(cwd):
    """작업 폴더의 git origin 이 깃허브면 'owner/repo'."""
    if cwd in repo_of_cwd:
        return repo_of_cwd[cwd]
    r = None
    if cwd and os.path.isdir(cwd):
        r = gh_repo_of_url(run(["git", "-C", cwd, "config", "--get", "remote.origin.url"], timeout=3) or "")
    repo_of_cwd[cwd] = r
    return r


def detect_repo():
    """가장 최근에 움직인 세션의 작업 폴더에서 저장소를 찾는다."""
    with lock:
        items = [(m.get("file"), m.get("cwd")) for m in meta.values() if m.get("cwd")]
    def mtime(p):
        try:
            return os.stat(p).st_mtime
        except (OSError, TypeError):
            return 0
    for _, cwd in sorted(items, key=lambda x: -mtime(x[0])):
        r = repo_of(cwd)
        if r:
            return r
    return None


def gh_token():
    """GITHUB_TOKEN / GH_TOKEN, 없으면 gh CLI 로그인 토큰 (있으면 API 한도가 넉넉해짐)."""
    global _gh_token
    if _gh_token is None:
        if GH_HOST == "github.com":
            _gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        else:                                   # 회사 깃허브: gh 와 같은 환경변수 이름
            _gh_token = os.environ.get("GH_ENTERPRISE_TOKEN") or os.environ.get("GITHUB_ENTERPRISE_TOKEN") or ""
        if not _gh_token and shutil.which("gh"):
            _gh_token = run(["gh", "auth", "token", "--hostname", GH_HOST], timeout=5) or ""
    return _gh_token


def gh_get(path, use_token=True):
    global _gh_token
    req = urllib.request.Request(api_base() + path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "agent-office"})
    tok = gh_token() if use_token else ""
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if tok and e.code == 401:              # 토큰이 만료됐으면 토큰 없이 다시
            _gh_token = ""
            return gh_get(path, False)
        raise
    return json.loads(body) if body else []


LOOK_FILE = "nyang-office.json"
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
    if d.get("gender") in ("f", "m"):          # 본인이 고른 성별 (고르지 않으면 빈 값)
        out["gender"] = d["gender"]
    for k in LOOK_COLORS:
        v = d.get(k)
        if isinstance(v, str) and HEX_RE.match(v):
            out[k] = v.lower()
    return out or None


# ───────── 기여자 캐릭터 설정 (YAML) ─────────
# 기본은 아이디 해시로 정한 모습. YAML 에 아이디별 값을 적어 두면 그 값이 먼저다.
#   우선순위: 내 컴퓨터 파일 > 저장소의 .nyang-office.yml > 본인 gist(nyang-office.json) > 아이디 해시
# 내 컴퓨터 파일: --characters 경로, 없으면 ~/.config/agent-office/characters.yml
# 저장소 파일: 팀 저장소 기본 브랜치 맨 위의 .nyang-office.yml (팀 정보와 같이 30분마다 받음)
CHAR_REPO_FILES = (".nyang-office.yml", ".nyang-office.yaml")
CHAR_LOCAL = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "agent-office", "characters.yml")
GENDER_ALIAS = {"f": "f", "m": "m", "여": "f", "여자": "f", "여성": "f", "female": "f", "남": "m", "남자": "m", "남성": "m", "male": "m"}
_char_local = {"path": None, "mtime": None, "data": {}}


def _yaml_scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _yaml_strip_comment(line):
    """# 뒤는 주석. 다만 '키: #3b2a22' 처럼 색 값은 따옴표 없이 써도 받아 준다."""
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            q = None if ch == q else q
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            if re.match(r"#[0-9a-fA-F]{6}\b", line[i:]) and line[:i].rstrip().endswith(":"):
                out.append(line[i:i + 7])
                rest = line[i + 7:]
                j = rest.find(" #")
                out.append(rest if j < 0 else rest[:j])
                return "".join(out)
            break
        out.append(ch)
    return "".join(out)


def parse_simple_yaml(text):
    """냥오피스 설정에 필요한 만큼만 읽는 YAML: 들여쓰기로 겹친 '키: 값' 과 한 줄 {키: 값, ...}."""
    root = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = _yaml_strip_comment(raw.rstrip())
        if not line.strip() or line.strip() in ("---", "..."):
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, sep, val = line.strip().partition(":")
        if not sep:
            continue
        key, val = _yaml_scalar(key), val.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if not val:
            parent[key] = {}
            stack.append((indent, parent[key]))
        elif val.startswith("{") and val.endswith("}"):
            d = {}
            for part in val[1:-1].split(","):
                k, sp, v = part.partition(":")
                if sp:
                    d[_yaml_scalar(k)] = _yaml_scalar(v)
            parent[key] = d
        else:
            parent[key] = _yaml_scalar(val)
    return root


def chars_from_yaml(text):
    """{아이디(소문자): 모습}. 맨 위에 characters: (또는 members:) 로 한 번 감싸도 된다."""
    data = parse_simple_yaml(text or "")
    if isinstance(data.get("characters"), dict):
        data = data["characters"]
    elif isinstance(data.get("members"), dict):
        data = data["members"]
    out = {}
    for login, d in data.items():
        if not isinstance(d, dict) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", str(login)):
            continue
        d = dict(d)
        if "gender" in d:
            d["gender"] = GENDER_ALIAS.get(str(d["gender"]).strip().lower(), "")
        for k in LOOK_COLORS:
            v = d.get(k)
            if isinstance(v, str) and re.fullmatch(r"[0-9a-fA-F]{6}", v.strip()):
                d[k] = "#" + v.strip()
        lk = clean_look(d)
        if lk:
            out[str(login).lower()] = lk
    return out


def local_chars():
    """내 컴퓨터의 캐릭터 설정 (파일이 바뀌면 다시 읽음)."""
    path = local_chars_path()
    try:
        mt = os.path.getmtime(path)
    except OSError:
        _char_local.update(mtime=None, data={})
        return {}
    if mt != _char_local["mtime"] or path != _char_local.get("read"):
        _char_local["read"] = path
        try:
            with open(path, encoding="utf-8") as fh:
                data = chars_from_yaml(fh.read())
        except (OSError, UnicodeDecodeError):
            data = {}
        _char_local.update(mtime=mt, data=data)
    return _char_local["data"]


CHAR_HEADER = """# 냥오피스 기여자 캐릭터 설정
# 냥오피스의 "🎨 캐릭터 설정"에서 저장하면 여기에 써져요. GitHub 저장소의 .nyang-office.yml 보다 먼저예요.
# 직접 고쳐도 돼요: 고치고 저장하면 몇 초 안에 반영돼요 (페이지 새로고침이면 바로).
#   gender: f / m   art: wavy longglasses ponytail ponyglasses bunhood bob / short fringe curly beanie
#   색(#rrggbb): hair skin shirt inner pants hat
"""


def project_chars_file():
    """냥오피스 코드를 다른 프로젝트 안(예: vendor/agent-office)에 넣어 쓸 때: 그 프로젝트의 .nyang-office.yml.
    서버 파일이 있는 폴더의 위쪽 폴더들을 차례로 찾고(프로젝트 맨 위까지), 없으면 그 폴더 안(스냅샷 안)도 봄.
    냥오피스 저장소를 git 으로 받아 쓰는 경우엔 저장소 자체의 .nyang-office.yml 은 쓰지 않음 (고치면 자동 업데이트가 막힘)."""
    here = os.path.dirname(os.path.abspath(__file__))
    home = os.path.expanduser("~")
    d = os.path.dirname(here)
    for _ in range(6):
        if not d or d == os.path.dirname(d) or d == home:
            break
        for n in CHAR_REPO_FILES:
            f = os.path.join(d, n)
            if os.path.isfile(f):
                return f
        if os.path.isdir(os.path.join(d, ".git")):   # 프로젝트 맨 위에서 멈춤
            break
        d = os.path.dirname(d)
    if not os.path.isdir(os.path.join(here, ".git")):
        for n in CHAR_REPO_FILES:
            f = os.path.join(here, n)
            if os.path.isfile(f):
                return f
    return None


def local_chars_path():
    """내 컴퓨터에서 읽고 '💾 저장'이 쓰는 파일: --characters(또는 NYANG_OFFICE_CHARACTERS) > 프로젝트의 .nyang-office.yml
    > ~/.config/agent-office/characters.yml"""
    return _char_local["path"] or os.environ.get("NYANG_OFFICE_CHARACTERS") or project_chars_file() or CHAR_LOCAL


def dump_chars_yaml(chars):
    keys = ("gender", "art") + LOOK_COLORS
    lines = [CHAR_HEADER, "characters:"]
    for login in sorted(chars, key=str.lower):
        d = chars[login]
        lines.append(f"  {login}:")
        for k in keys:
            if d.get(k):
                lines.append(f"    {k}: " + (d[k] if k in ("gender", "art") else f'"{d[k]}"'))
    return "\n".join(lines) + "\n"


def save_local_chars(updates):
    """{아이디: 모습(빈 값이면 지움)} 을 내 컴퓨터 파일에 합쳐 씀. 원래 파일은 .bak 으로 남김."""
    path = local_chars_path()
    cur = {}
    try:
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
        cur = chars_from_yaml(old)
        with open(path + ".bak", "w", encoding="utf-8") as fh:
            fh.write(old)
    except OSError:
        pass
    for login, look in updates.items():
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", str(login)):
            continue
        lk = clean_look(look) if look else None
        cur.pop(str(login).lower(), None)
        if lk:
            cur[str(login)] = lk
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(dump_chars_yaml(cur))
    os.replace(tmp, path)
    _char_local["mtime"] = None                 # 다음 요청에서 바로 다시 읽음
    return path


def open_in_editor(path):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(CHAR_HEADER + "characters:\n")
    if SYSTEM == "Darwin":
        run(["open", "-t", path])
    elif SYSTEM == "Windows":
        os.startfile(path)  # noqa: 윈도우 전용
    else:
        subprocess.Popen(["xdg-open", path])


def refresh_team(repo):
    """저장소 팀 정보와 .nyang-office.yml 을 지금 바로 다시 받음."""
    _team_fresh.discard(repo)
    _chars_at.pop(repo, None)
    return get_team(repo)


def fetch_repo_chars(repo):
    for name in CHAR_REPO_FILES:
        try:
            f = gh_get(f"/repos/{repo}/contents/{name}")
        except Exception:
            continue
        if isinstance(f, dict) and f.get("content"):
            try:
                return chars_from_yaml(base64.b64decode(f["content"]).decode("utf-8", "replace"))
            except ValueError:
                return {}
    return {}


def with_yaml_looks(data):
    """팀 정보에 YAML 캐릭터 설정을 덮어씀 (받아 둔 팀 정보 자체는 건드리지 않음)."""
    loc, rep_ = local_chars(), data.get("chars") or {}
    if not data.get("members") or not (loc or rep_):
        return {k: v for k, v in data.items() if k != "chars"}
    members = []
    for m in data["members"]:
        key = (m.get("login") or "").lower()
        y = loc.get(key) or rep_.get(key)
        if y:
            m = dict(m, look=dict(m.get("look") or {}, **y), lookFrom="local" if key in loc else "repo", yaml=y)
        members.append(m)
    return dict({k: v for k, v in data.items() if k != "chars"}, members=members)


def gh_send(method, path, body):
    req = urllib.request.Request(api_base() + path, method=method, data=json.dumps(body).encode(), headers={
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
    host = urlparse(raw).hostname or ""
    if not (raw.startswith("https://") and host in ("gist.githubusercontent.com", GH_HOST, "gist." + GH_HOST)):
        return None
    req = urllib.request.Request(raw, headers={"User-Agent": "agent-office"})
    if GH_HOST != "github.com" and gh_token():  # 회사 깃허브는 로그인해야 보이는 경우가 많음
        req.add_header("Authorization", "Bearer " + gh_token())
    with urllib.request.urlopen(req, timeout=10) as r:
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


def fetch_team(repo):
    contributors = gh_get(f"/repos/{repo}/contributors?per_page=60") or []
    try:
        commits = gh_get(f"/repos/{repo}/commits?per_page=100") or []
    except Exception:
        commits = []
    last, recent = {}, collections.Counter()
    month = time.time() - 30 * 86400
    for c in commits:
        login = (c.get("author") or {}).get("login")
        info = c.get("commit") or {}
        ts = parse_ts(((info.get("author") or {}).get("date")) or "")
        if not login or ts is None:
            continue
        if login not in last:
            last[login] = {"ts": ts, "msg": (info.get("message") or "").split("\n")[0][:120]}
        if ts >= month:
            recent[login] += 1
    members = []
    for c in contributors:
        login = c.get("login") or ""
        if not login or c.get("type") == "Bot" or login.endswith("[bot]"):
            continue
        lc = last.get(login) or {}
        members.append({"login": login, "avatar": c.get("avatar_url") or "", "url": c.get("html_url") or "",
                        "contributions": c.get("contributions") or 0, "lastAt": int(lc["ts"] * 1000) if lc else 0,
                        "lastMsg": lc.get("msg", ""), "recent": recent.get(login, 0),
                        "name": "", "bio": "", "company": "", "location": ""})
        if len(members) >= TEAM_MAX:
            break
    for m in members[:12]:                      # 자기소개용 프로필 (상위 12명만, 한도 아끼기)
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
            pass
    try:
        chars = fetch_repo_chars(repo)          # 저장소에 둔 팀 캐릭터 설정 (.nyang-office.yml)
    except Exception:
        chars = {}
    return {"repo": repo, "host": GH_HOST, "fetched": int(time.time() * 1000), "members": members, "chars": chars}


def team_cache_path(repo):
    base = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "agent-office")
    host = "" if GH_HOST == "github.com" else GH_HOST + "__"
    return os.path.join(base, "team_" + host + repo.replace("/", "__") + ".json")


_team_fresh = set()                             # 이번 서버 실행에서 새로 받은 저장소 (서버를 다시 켜면 처음엔 꼭 새로 받음)
_chars_at = {}                                  # 저장소 → 캐릭터 설정(.nyang-office.yml)을 마지막으로 받은 시각


def get_team(repo, fresh_chars=False):
    """fresh_chars: 페이지를 새로 열었을 때 — 팀 정보는 받아 둔 걸 쓰더라도 캐릭터 설정 파일은 다시 받음 (1분에 한 번까지)."""
    with team_locks[repo]:                      # 같은 저장소를 동시에 두 번 받지 않게
        c = team_cache.get(repo)
        if not c:
            try:
                with open(team_cache_path(repo), encoding="utf-8") as fh:
                    c = team_cache[repo] = json.load(fh)
            except (OSError, ValueError):
                c = None
        if c and time.time() - c["at"] < TEAM_TTL and repo in _team_fresh:
            if fresh_chars and time.time() - _chars_at.get(repo, 0) > 60:
                try:
                    c["data"] = dict(c["data"], chars=fetch_repo_chars(repo))
                    _chars_at[repo] = time.time()
                except Exception:
                    pass
            return c["data"]
        try:
            data = fetch_team(repo)
        except Exception as e:
            msg = str(getattr(e, "code", "") or e)
            if c:                               # 못 받아 오면 예전 정보라도
                return dict(c["data"], stale=True, error=msg)
            return {"repo": repo, "members": [], "error": msg}
        c = team_cache[repo] = {"at": time.time(), "data": data}
        _team_fresh.add(repo)
        _chars_at[repo] = time.time()
        try:
            os.makedirs(os.path.dirname(team_cache_path(repo)), exist_ok=True)
            with open(team_cache_path(repo), "w", encoding="utf-8") as fh:
                json.dump(c, fh, ensure_ascii=False)
        except OSError:
            pass
        return data


# 다른 웹 툴에 끼워 넣는 위젯 스크립트: <div data-agent-office></div><script src=".../widget.js"></script>
WIDGET_JS = r"""(function(){
  "use strict";
  var me = document.currentScript, base = new URL(".", me ? me.src : location.href), ORIGIN = base.origin;
  var KEYS = ["repo", "theme", "tod", "team", "follow", "demo", "layout", "view", "cam", "controls", "wheel"];
  function mount(el, opts){
    if (!el || el.__agentOffice) return el && el.__agentOffice;
    opts = opts || {};
    var p = new URLSearchParams({embed: "1"});
    KEYS.forEach(function(k){ var v = opts[k] != null ? opts[k] : el.getAttribute("data-" + k); if (v != null && v !== "") p.set(k, v); });
    var f = document.createElement("iframe");
    f.src = base.href + "?" + p.toString();
    f.title = el.getAttribute("data-title") || "냥오피스";
    f.allow = "clipboard-write";
    f.style.cssText = "display:block;width:100%;height:100%;border:0;border-radius:inherit;color-scheme:normal";
    if (!el.style.height && el.clientHeight < 40) el.style.height = opts.height || el.getAttribute("data-height") || "420px";
    el.appendChild(f);
    el.__agentOffice = {frame: f, el: el, send: function(type, data){ f.contentWindow && f.contentWindow.postMessage(Object.assign({source: "agent-office-host", type: type}, data || {}), ORIGIN); }};
    return el.__agentOffice;
  }
  addEventListener("message", function(e){
    var d = e.data;
    if (e.origin !== ORIGIN || !d || d.source !== "agent-office") return;
    var els = document.querySelectorAll("[data-agent-office]");
    for (var i = 0; i < els.length; i++){
      var w = els[i].__agentOffice;
      if (w && w.frame.contentWindow === e.source)
        els[i].dispatchEvent(new CustomEvent("agent-office:" + d.type, {detail: d, bubbles: true}));
    }
  });
  function scan(root){ (root.querySelectorAll ? root : document).querySelectorAll("[data-agent-office]").forEach(function(el){ mount(el); }); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function(){ scan(document); }); else scan(document);
  new MutationObserver(function(ms){ ms.forEach(function(m){ m.addedNodes.forEach(function(n){
    if (n.nodeType !== 1) return; if (n.hasAttribute("data-agent-office")) mount(n); scan(n); }); }); })
    .observe(document.documentElement, {childList: true, subtree: true});
  window.AgentOffice = {mount: mount, origin: ORIGIN};
})();
"""


# ───────── 창 열기: 이미 열린 창이 있으면 그대로, 설치한 앱이 있으면 앱으로 ─────────
APP_NAMES = ("냥오피스", "Agent Office")


def find_installed_app():
    """Chrome·Edge로 설치한 냥오피스 앱을 찾는다: (종류, 경로) 또는 None."""
    home = os.path.expanduser("~")
    if SYSTEM == "Darwin":
        for d in ("Chrome Apps.localized", "Chrome Apps", "Edge Apps.localized", "Edge Apps", "Chromium Apps.localized"):
            for name in APP_NAMES:
                p = os.path.join(home, "Applications", d, name + ".app")
                if os.path.isdir(p):
                    return "mac", p
    elif SYSTEM == "Windows":
        base = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
        for sub in ("Chrome Apps", "Edge Apps", ""):
            for name in APP_NAMES:
                p = os.path.join(base, sub, name + ".lnk")
                if os.path.isfile(p):
                    return "win", p
    else:
        appdir = os.path.join(home, ".local", "share", "applications")
        try:
            files = sorted(os.listdir(appdir))
        except OSError:
            files = []
        for fn in files:
            if not fn.endswith(".desktop"):
                continue
            p = os.path.join(appdir, fn)
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            if "--app-id" in text and any(f"Name={n}" in text for n in APP_NAMES):
                return "linux", p
    return None


def open_window(url):
    app = find_installed_app()
    if app:
        kind, p = app
        try:
            if kind == "mac":
                subprocess.Popen(["open", "-a", p])
                return "설치한 앱"
            if kind == "win":
                os.startfile(p)  # noqa: 윈도우 전용
                return "설치한 앱"
            if shutil.which("gio"):
                subprocess.Popen(["gio", "launch", p])
                return "설치한 앱"
            if shutil.which("gtk-launch"):
                subprocess.Popen(["gtk-launch", os.path.basename(p)[:-8]])
                return "설치한 앱"
            with open(p, encoding="utf-8") as fh:
                m = re.search(r"^Exec=(.*)$", fh.read(), re.M)
            if m:
                subprocess.Popen([a for a in shlex.split(m.group(1)) if not a.startswith("%")])
                return "설치한 앱"
        except Exception:
            pass
    webbrowser.open(url)
    return "브라우저"


def open_when_needed(url):
    """서버가 막 켜졌을 때: 이미 열린 창이 다시 연결되면 그대로 두고, 아니면 연다."""
    deadline = time.time() + 4.5
    while time.time() < deadline:
        if time.time() - last_client < 5:
            print("이미 열린 창이 다시 연결됐어요. 새 창은 열지 않을게요.")
            return
        time.sleep(0.25)
    print(f"{open_window(url)}으로 열었어요.")


def server_alive(port):
    """그 포트에서 에이전트 오피스 서버가 돌고 있으면 ping 응답을, 아니면 None."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1.5) as r:
            d = json.loads(r.read() or b"{}")
            return d if d.get("ok") else None
    except Exception:
        return None


# ───────── 자동 업데이트: git 저장소에서 실행 중이면 새 버전을 받아 온다 ─────────
UPDATE_EVERY = 3 * 3600


def git(*a, timeout=60):
    try:
        r = subprocess.run(["git", "-C", HERE, *a], capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def code_changed_restart():
    """누가 git pull 등으로 서버 코드를 바꿨는데 서버는 예전 코드로 돌고 있으면 (화면은 새 것, 서버는 옛 것 → 404 등)
    알아서 다시 켬. 30초에 한 번만 확인."""
    w = _code_watch
    if not w["on"] or time.time() - w["at"] < 30:
        return
    w["at"] = time.time()
    try:
        h = file_hash(os.path.abspath(__file__))
    except OSError:
        return
    if w["hash"] and h != w["hash"]:
        w["on"] = False
        print("[업데이트] 서버 코드가 바뀌어서 새 코드로 다시 켤게요.")
        threading.Timer(0.5, restart_self).start()


def file_hash(p):
    try:
        with open(p, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()
    except OSError:
        return ""


def try_update():
    """새 버전을 받았고 서버 코드가 바뀌었으면 True (다시 켜야 함)."""
    if not (os.path.isdir(os.path.join(HERE, ".git")) and shutil.which("git")):
        return False
    rc, _ = git("fetch", "--quiet")
    if rc != 0:
        return False
    rc, behind = git("rev-list", "--count", "HEAD..@{u}")
    if rc != 0 or not behind.isdigit() or int(behind) == 0:
        return False
    rc, dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        print("[업데이트] 새 버전이 있지만 직접 고친 파일이 있어서 건너뛰어요. (git status로 확인)")
        return False
    before = file_hash(os.path.abspath(__file__))
    rc, out = git("pull", "--ff-only", "--quiet")
    if rc != 0:
        print(f"[업데이트] 새 버전을 받지 못했어요: {out}")
        return False
    print(f"[업데이트] 새 버전을 받았어요 (커밋 {behind}개).")
    return file_hash(os.path.abspath(__file__)) != before


def restart_self():
    args = [a for a in sys.argv[1:] if a not in ("--restarted",)]
    if "--no-browser" not in args:
        args.append("--no-browser")
    print("[업데이트] 서버를 새 버전으로 다시 켤게요.", flush=True)
    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + args + ["--restarted"])


def update_loop():
    while True:
        time.sleep(UPDATE_EVERY)
        try:
            if try_update():
                restart_self()
        except Exception as e:
            print(f"[업데이트] 확인 중 문제가 생겼어요: {e}")


# ───────── 자동 시작: 로그인할 때 서버를 뒤에서 켠다 ─────────

def autostart_paths():
    home = os.path.expanduser("~")
    if SYSTEM == "Darwin":
        return os.path.join(home, "Library", "LaunchAgents", "com.agentoffice.server.plist")
    if SYSTEM == "Windows":
        return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs",
                            "Startup", "AgentOffice.vbs")
    return os.path.join(home, ".config", "autostart", "agent-office.desktop")


def background_cmd(port, extra):
    py = sys.executable
    if SYSTEM == "Windows":
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        py = pyw if os.path.isfile(pyw) else py
    return [py, os.path.abspath(__file__), "--no-browser"] + (["--port", str(port)] if port != 8765 else []) + extra


def log_path():
    if SYSTEM == "Darwin":
        return os.path.expanduser("~/Library/Logs/agent-office.log")
    if SYSTEM == "Windows":
        return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "agent-office.log")
    return os.path.join(os.path.expanduser("~/.cache"), "agent-office.log")


def start_background(port, extra):
    lp = log_path()
    os.makedirs(os.path.dirname(lp), exist_ok=True)
    out = open(lp, "a", encoding="utf-8")
    if SYSTEM == "Windows":
        subprocess.Popen(background_cmd(port, extra), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                         creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        subprocess.Popen(background_cmd(port, extra), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                         start_new_session=True)


def install_autostart(port, extra):
    p = autostart_paths()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cmd = background_cmd(port, extra)
    if SYSTEM == "Darwin":
        import plistlib
        lp = log_path()
        with open(p, "wb") as fh:
            plistlib.dump({"Label": "com.agentoffice.server", "ProgramArguments": cmd, "RunAtLoad": True,
                           "KeepAlive": {"SuccessfulExit": False}, "StandardOutPath": lp, "StandardErrorPath": lp,
                           "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")}}, fh)
        subprocess.run(["launchctl", "unload", p], capture_output=True)
        subprocess.run(["launchctl", "load", "-w", p], capture_output=True)   # 지금 바로 켜짐
    elif SYSTEM == "Windows":
        line = " ".join('""' + c + '""' if " " in c or "\\" in c else c for c in cmd)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(f'CreateObject("WScript.Shell").Run "{line}", 0, False\n')
    else:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("[Desktop Entry]\nType=Application\nName=Agent Office 서버\n"
                     "Comment=냥오피스 로컬 서버 (Claude Code 세션 감시)\n"
                     f"Exec={' '.join(shlex.quote(c) for c in cmd)}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")
    return p


def uninstall_autostart():
    p = autostart_paths()
    if not os.path.exists(p):
        return None
    if SYSTEM == "Darwin":
        subprocess.run(["launchctl", "unload", "-w", p], capture_output=True)
    os.remove(p)
    return p


def main():
    ap = argparse.ArgumentParser(description="에이전트 오피스 라이브 서버")
    ap.add_argument("--dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-update", action="store_true", help="자동 업데이트 끄기")
    ap.add_argument("--no-codex", action="store_true", help="Codex 세션(~/.codex/sessions)은 보여주지 않기")
    ap.add_argument("--install", action="store_true", help="로그인할 때 서버 자동 시작 (지금도 켬)")
    ap.add_argument("--uninstall", action="store_true", help="자동 시작 해제")
    ap.add_argument("--check-terminal", action="store_true", help="'터미널로 이동' 환경 점검만 하고 종료 (리눅스)")
    ap.add_argument("--github-host", metavar="HOST",
                    help="회사 깃허브(GitHub Enterprise Server) 주소 (예: github.company.net, 기본: github.com)")
    ap.add_argument("--characters", help=f"기여자 캐릭터 설정 YAML 파일 (기본: {CHAR_LOCAL})")
    ap.add_argument("--repo", help="위젯 본사에 보여줄 깃허브 저장소 (owner/repo, 기본: 세션 폴더에서 자동으로 찾음)")
    ap.add_argument("--allow-embed", action="append", default=[], metavar="ORIGIN",
                    help="위젯을 끼워 넣을 수 있는 바깥 사이트 (예: https://tool.example.com). localhost 는 기본 허용")
    ap.add_argument("--no-hooks", action="store_true", help="Claude Code·Codex hook 을 등록하지 않기 (세션 끝을 로그로만 짐작)")
    ap.add_argument("--uninstall-hooks", action="store_true", help="등록한 hook 을 빼고 종료")
    ap.add_argument("--hook", choices=["claude", "codex"], help=argparse.SUPPRESS)   # 도구가 hook 으로 부를 때
    ap.add_argument("--restarted", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.hook:
        explicit = any(a == "--port" or a.startswith("--port=") for a in sys.argv[1:])
        sys.exit(hook_main(args.hook, args.port if explicit else None))
    if args.uninstall_hooks:
        done = uninstall_hooks()
        print("hook 을 뺐어요: " + ", ".join(done) if done else "등록된 hook 이 없어요.")
        return
    if args.repo:
        args.repo = norm_repo(args.repo)
    url = f"http://localhost:{args.port}"
    extra = (["--dir", args.dir] if args.dir != os.path.expanduser("~/.claude/projects") else []) + \
            (["--no-update"] if args.no_update else []) + \
            (["--no-codex"] if args.no_codex else []) + \
            (["--no-hooks"] if args.no_hooks else []) + \
            (["--characters", os.path.abspath(os.path.expanduser(args.characters))] if args.characters else []) + \
            (["--repo", args.repo] if args.repo else []) + \
            (["--github-host", args.github_host] if args.github_host else []) + \
            [x for o in args.allow_embed for x in ("--allow-embed", o)]
    global DEFAULT_REPO, CODEX_ON, GH_HOST
    if args.github_host:
        h = re.sub(r"^https?://", "", args.github_host.strip(), flags=re.I).strip("/").lower()
        if not re.fullmatch(r"[a-z0-9.-]+(:\d+)?", h):
            print(f"[!] --github-host 값이 이상해요: {args.github_host} (예: github.company.net)")
            return
        GH_HOST = args.github_host = h
    CODEX_ON = not args.no_codex
    if args.repo:
        if not REPO_RE.match(args.repo):
            print("[!] --repo 는 owner/repo 형식으로 적어 주세요 (예: square/okhttp).")
            return
        DEFAULT_REPO = args.repo
    for o in args.allow_embed:
        if not re.fullmatch(r"(\*|https?://[A-Za-z0-9.-]+(:\d+|:\*)?)", o):
            print(f"[!] --allow-embed 값이 이상해요: {o} (예: https://tool.example.com)")
            return
        EMBED_ORIGINS.append(o)

    if args.check_terminal:
        check_terminal()
        return
    if args.uninstall:
        p = uninstall_autostart()
        print(f"자동 시작을 해제했어요: {p}" if p else "자동 시작이 설정돼 있지 않아요.")
        print("지금 켜져 있는 서버는 그대로예요. 다음 로그인부터 자동으로 켜지지 않아요.")
        return
    if args.install:
        p = install_autostart(args.port, extra)
        print(f"자동 시작을 등록했어요: {p}")
        if not server_alive(args.port) and SYSTEM != "Darwin":
            start_background(args.port, extra)
        for _ in range(20):
            if server_alive(args.port):
                break
            time.sleep(0.25)
        print("서버가 뒤에서 켜져 있어요." if server_alive(args.port) else f"서버를 켜지 못했어요. 로그를 확인해 주세요: {log_path()}")
        print(f"로그: {log_path()}")
        print(f"이제 {url} 를 Chrome·Edge로 열고 '📲 앱으로 설치'를 누르면, 다음부터는 냥오피스 아이콘만 누르면 돼요.")
        if not args.no_browser:
            open_when_needed(url)
        return

    # 이미 서버가 켜져 있으면(예: 자동 시작) 창만 연다
    alive = server_alive(args.port)
    if alive:
        print(f"이미 서버가 켜져 있어요: {url}")
        if not args.no_browser:
            print(f"{open_window(url)}으로 열었어요.")
        return

    if not args.no_update and not args.restarted:
        try:
            if try_update():
                restart_self()
        except Exception as e:
            print(f"[업데이트] 확인 중 문제가 생겼어요: {e}")

    Handler.root = args.dir
    Handler.port = args.port
    if not args.no_update:                      # 서버 코드가 바뀌면 다시 켜기 (자동 업데이트를 끈 경우는 그대로)
        try:
            _code_watch.update(hash=file_hash(os.path.abspath(__file__)), on=True, at=time.time())
        except OSError:
            pass
    load_hook_state()
    if args.characters:
        _char_local["path"] = os.path.abspath(os.path.expanduser(args.characters))
    if not args.no_hooks:
        try:
            for path in install_hooks(args.port, codex=CODEX_ON):
                print(f"세션 시작·끝을 알려 주는 hook 을 등록했어요: {path}  (빼려면 --uninstall-hooks)")
        except OSError as e:
            print(f"[!] hook 을 등록하지 못했어요 ({e}). 세션 끝은 로그로만 짐작해요.")
    if not os.path.isdir(args.dir):
        print(f"[!] 로그 폴더가 없어요: {args.dir}")
        print("    Claude Code를 이 PC에서 한 번이라도 실행했는지 확인해 주세요.")
    if SYSTEM == "Linux" and not args.restarted:
        linux_setup_check()

    try:
        srv = Server(("127.0.0.1", args.port), Handler)
    except OSError as e:
        print(f"[!] {args.port}번 포트를 쓸 수 없어요 ({e}). --port 9000 처럼 다른 번호로 켜 주세요.")
        return
    register_server(args.port)
    atexit.register(unregister_server, args.port)
    print(f"에이전트 오피스 라이브 서버: {url}")
    print(f"감시 중: {args.dir}   (Ctrl+C 로 종료)")
    threading.Thread(target=usage_loop, daemon=True).start()
    if not args.no_update:
        threading.Thread(target=update_loop, daemon=True).start()
    if not args.no_browser and not args.restarted:
        threading.Thread(target=open_when_needed, args=(url,), daemon=True).start()
    if SYSTEM != "Windows":
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # kill 로 꺼도 서버 목록에서 지워지게
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")
    finally:
        unregister_server(args.port)


if __name__ == "__main__":
    main()
