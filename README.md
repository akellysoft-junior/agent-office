# Agent Office 🐾

내 PC에서 돌아가는 **Claude Code 세션들을 고양이 동네의 사무실로 실시간 시각화**하는 로컬 웹 툴입니다.

- 세션 하나 = 사무실 한 채. 메인 에이전트는 대장 고양이가 맡아요.
- 서브에이전트가 생기면 새끼 고양이가 출근하고, 그 수만큼 책상이 늘어나요.
- 할 일이 없는 고양이는 휴게공간(소파·캣타워·러그·밥그릇)에서 쉬어요.
- 세션이 답을 마치고 명령을 기다리면 대장이 문 앞에서 "냥?" 팻말을 들고 기다려요.
- 작업이 끝나면 "완료!" 도장, 꽃가루, 결과 알림이 떠요.
- 세션마다 "지금 하는 일" 요약 카드(요청, 할 일 진행률, 현재 작업, 통계)를 보여줘요.
- 카드에서 그 세션의 터미널로 이동하거나, 새 터미널에서 이어하기(`claude --resume`)를 할 수 있어요.
- 반응이 생긴 세션으로 카메라가 자동으로 따라가요 (🎥 자동 따라가기).
- 실제 시각에 맞춘 낮/노을/밤 사이클과 라이트/다크 테마가 있어요.
- Chrome·Edge에서 **앱으로 설치**하면 독립된 창으로 쓰고, 확인 안 한 완료·질문 수가 아이콘 배지로 떠요.
- 폰이나 좁은 창에서도 끌어서 동네를 둘러볼 수 있어요.

파이썬 표준 라이브러리만 쓰기 때문에 따로 설치할 것이 없어요.

## 한 번만 설정하기 (추천)

```bash
git clone https://github.com/akellysoft-junior/agent-office.git
cd agent-office
python3 agent_office_server.py --install      # 윈도우: py agent_office_server.py --install
```

- **자동 시작**: 로그인할 때마다 서버가 뒤에서 자동으로 켜져요. 지금 바로도 켜져요.
  - 리눅스: `~/.config/autostart/agent-office.desktop`
  - 맥: `~/Library/LaunchAgents/com.agentoffice.server.plist`
  - 윈도우: 시작프로그램 폴더의 `AgentOffice.vbs`
- **앱 설치**: 열린 페이지에서 **📲 앱으로 설치**를 누르세요. 그다음부터는 **냥오피스 아이콘만 누르면** 돼요.
- **자동 업데이트**: 서버가 켜질 때와 3시간마다 이 저장소의 새 버전을 받아 와요.
  - 서버 코드가 바뀌면 서버가 스스로 다시 켜지고, 화면이 바뀌면 열린 창이 알아서 새로고침해요.
  - 직접 고친 파일이 있으면 업데이트를 건너뛰어요. 끄려면 `--no-update`를 붙이세요.
- **해제**: `python3 agent_office_server.py --uninstall`
- **로그**: 리눅스 `~/.cache/agent-office.log`, 맥 `~/Library/Logs/agent-office.log`, 윈도우 `%LOCALAPPDATA%\agent-office.log`

## 실행

파이썬 3.8 이상이 필요해요.

```bash
# 맥 / 리눅스
python3 agent_office_server.py

# 윈도우
py agent_office_server.py
```

**🔴 LIVE**가 뜨면 성공이에요. 끌 때는 `Ctrl + C`.

- **창이 이미 열려 있으면**: 앱이나 탭이 이미 열려 있으면 그 창이 서버에 다시 붙고, 새 창은 열지 않아요.
- **창이 없으면**: 설치한 냥오피스 앱이 있으면 앱으로, 없으면 브라우저로 열어요.
- **서버가 이미 켜져 있으면**: 자동 시작 등으로 켜져 있으면 다시 실행해도 서버를 또 켜지 않고 창만 열어요.
- **창을 먼저 연 경우**: 서버가 꺼진 채로 창을 열어 두면, 서버가 켜지는 순간 알아서 라이브 모드로 바뀌어요.

### 옵션

| 옵션 | 설명 | 기본값 |
| --- | --- | --- |
| `--dir PATH` | 감시할 Claude Code 로그 폴더 | `~/.claude/projects` |
| `--port N` | 서버 포트 | `8765` |
| `--no-browser` | 창 자동 열기 끄기 | 꺼짐 |
| `--no-update` | 자동 업데이트 끄기 | 꺼짐 |
| `--install` / `--uninstall` | 로그인 시 자동 시작 등록 / 해제 | |
| `--check-terminal` | (리눅스) '터미널로 이동' 환경 점검 | |
| `--repo owner/name` | 본사에 보여줄 깃허브 저장소 | 세션 폴더의 git origin에서 자동으로 찾음 |
| `--allow-embed ORIGIN` | 위젯을 끼워 넣을 수 있는 바깥 사이트 (여러 번 쓸 수 있음) | localhost만 허용 |

### 매번 치기 귀찮다면

```bash
# ~/.zshrc 또는 ~/.bashrc
alias cats='python3 ~/path/to/agent-office/agent_office_server.py'
```

윈도우는 같은 폴더에 `냥이오피스.bat`을 만들고 `py "%~dp0agent_office_server.py"` 한 줄을 넣으면 더블클릭으로 실행돼요.

## 앱으로 설치 (웹앱)

1. 서버를 켜고 Chrome이나 Edge로 `http://localhost:8765`를 엽니다.
2. 위쪽 **📲 앱으로 설치** 버튼(또는 주소창 오른쪽의 설치 아이콘)을 누릅니다.
3. 이제 독·시작 메뉴의 **냥오피스** 아이콘으로 열 수 있어요.

- 앱도 이 서버에서 데이터를 받아요. 쓰기 전에 서버를 켜 두세요. 서버가 꺼져 있으면 마지막 화면으로 시뮬레이션 모드가 열려요.
- 포트를 바꾸면(`--port`) 다른 앱으로 인식돼요. 늘 같은 포트로 켜는 걸 추천해요.
- 아이콘 배지와 창 제목의 숫자는 아직 확인하지 않은 완료·질문 수예요. 그 세션에 새 요청을 보내거나 사무실을 열어 보면 지워져요.

## 화면 보는 법

- **동네 화면**: 입주한 사무실 위 이름표에 상태(⚙ 작업 중 · 💬 명령 대기 · ✓ 완료 · ❓ 답변 대기 · ⏳ 승인 필요?)가 떠요.
- **캐릭터 클릭**: 고양이(AI)나 사람(깃허브 기여자)을 누르면 확대되고 대화창에서 자기소개를 해요. 대사를 누르거나 Enter로 다음, `Esc`로 닫아요.
- **사무실 클릭**: 그 사무실로 확대되고, 오른쪽 목록이 고양이별(대장 + 새끼냥) 현황으로 바뀌어요. `Esc` 또는 "← 동네로"로 돌아와요.
- **지금 하는 일 카드**
  - ✎ 이름 바꾸기 (브라우저에 저장)
  - 터미널로 이동 / 이어하기 / 폴더 / 명령 복사 / 사무실 보기
- **🔔 완료 알림**: 켜면 완료 시 차임 소리와, 페이지를 보고 있지 않을 때 PC 알림이 와요.
- **🖥 백그라운드 작업 · 도구**: 세션이 백그라운드로 켠 모니터링 스크립트·개발 서버(`run_in_background`)는 사무실 북쪽 벽의 관제 모니터로 보여요.
  - 실행 중엔 초록 선이 흐르고, 끝나면 ✓, 실패하면 ✕, 멈추면 ■가 떠요. 출력을 확인(`BashOutput`)할 때마다 그 모니터가 반짝여요.
  - 요약 카드에 백그라운드 작업 상태와 이번 요청에서 쓴 도구 횟수(읽기·수정·명령·웹, 🔌MCP 서버별, 🧩스킬)가 나와요.
  - 사무실을 확대하면 고양이 아래에 백그라운드 작업 목록도 보여요.
- **🎥 자동 따라가기**: 새 요청·완료·질문이 생긴 세션으로 카메라가 이동해요. 한 사무실에 최소 8초 머물고, 완료·질문은 바로 보여줘요. 모두 45초 조용하면 동네 전체로 돌아와요. 끌기·확대·사무실 선택 같은 조작을 하면 30초 동안 멈춰요.
- **🌓 테마**: 자동(OS 설정) / 라이트 / 다크. 동네 그림의 낮·밤은 **시간** 버튼으로 따로 골라요.
- **둘러보기**: 마우스로 끌기, 폰에선 가로로 쓸기. ＋/－/⤢ 버튼이나 Ctrl+휠로 확대해요.
- **멀티 세션 데모**: 서버 없이 가짜 세션 4개로 모든 기능을 체험할 수 있어요.
- 서버 없이 HTML만 열면 시뮬레이션과 로그 파일(.jsonl) 재생 모드로 동작해요.

## 내 웹 툴에 위젯으로 넣기

서버를 켜 둔 상태에서, 내 웹 툴의 원하는 자리에 아래 두 줄을 넣으면 그 상자 크기에 맞춰 동네 화면만 들어가요. 설명 카드나 버튼은 빠지고, 캐릭터를 누르면 확대되면서 자기소개를 해요. 고양이는 AI, 사람은 깃허브 기여자예요.

```html
<div data-agent-office data-theme="light" style="height:420px"></div>
<script src="http://localhost:8765/widget.js"></script>
```

| 속성 | 설명 |
| --- | --- |
| `data-repo="owner/name"` | 본사에 보여줄 깃허브 저장소. 없으면 서버가 정한 저장소(`--repo` 또는 자동) |
| `data-theme="light\|dark\|auto"` | 페이지 테마 |
| `data-tod="day\|dusk\|night\|auto"` | 동네 그림의 낮·밤 |
| `data-team="0"` | 깃허브 팀 끄기 |
| `data-follow="0"` | 자동 따라가기 끄기 |
| `data-demo="1"` | 가짜 세션·가짜 팀으로 보기 |
| `data-height="360px"` | 상자에 높이가 없을 때 쓸 높이 (기본 420px) |

- React·Vue처럼 화면을 나중에 그리는 앱도 괜찮아요. `data-agent-office`가 붙은 요소가 생기면 알아서 채워요. 직접 넣으려면 `AgentOffice.mount(요소, {repo:"owner/name"})`.
- iframe 한 줄로 넣어도 돼요: `<iframe src="http://localhost:8765/?embed=1&repo=owner/name" style="width:100%;height:420px;border:0"></iframe>`
- 기본으로 `localhost`에서 도는 웹 툴만 끼워 넣을 수 있어요. 다른 주소의 사이트라면 서버를 `--allow-embed https://tool.example.com`으로 켜 주세요.

**위젯이 보내는 이벤트** (위젯을 넣은 요소에서 받아요)

```js
const box = document.querySelector("[data-agent-office]");
box.addEventListener("agent-office:select", e => console.log(e.detail));    // 고양이를 눌렀을 때 {kind:"human"|"ai-main"|"ai-sub", name, login?, session?}
box.addEventListener("agent-office:close", () => {});                       // 대화창을 닫았을 때
box.addEventListener("agent-office:attention", e => e.detail.count);        // 확인 안 한 완료·질문 수
box.addEventListener("agent-office:team", e => e.detail);                   // 팀 정보를 불러왔을 때 {repo, members}
box.__agentOffice.send("select", {login:"octocat"});                         // 바깥에서 그 사람에게 말 걸기
```

### 깃허브 팀 (본사)

저장소에 커밋한 사람들이 **본사** 건물에 사람 캐릭터로 출근해요 (AI는 고양이). 머리 모양·옷 색·안경은 아이디마다 정해져서 매번 같은 모습이에요.

- **상주 멤버**: 기여 상위 2명이거나, 3일 안에 커밋했거나, 최근 한 달 커밋이 10개 이상. 거의 늘 자리에 있고 가끔 휴게실에 다녀와요.
- **자주 오는 멤버**: 기여 비중이 8% 이상이거나 한 달 안에 커밋했어요. 몇 분 일하다 퇴근하고 조금 뒤 다시 와요.
- **가끔 들르는 손님**: 그 밖의 기여자. 아주 가끔 잠깐 들렀다 사라져요.
- 누르면 이름·소개(bio)·커밋 수·기여 순위·마지막 커밋 메시지를 이야기하고, GitHub 프로필로 갈 수 있어요.
- 저장소는 `data-repo` → 서버의 `--repo` → 가장 최근에 움직인 세션 폴더의 git origin 순서로 정해요.
- 깃허브 정보는 30분마다 새로 받고 `~/.cache/agent-office`에 저장해 둬요. `GITHUB_TOKEN`이나 `gh` 로그인이 있으면 그걸 써서 비공개 저장소도 볼 수 있고 API 한도도 넉넉해져요. 토큰은 서버 안에서만 쓰고 페이지로 보내지 않아요.

### 내 캐릭터 꾸미기 (본인 것만)

기본 모습은 아이디로 정해지는데, 본인이 직접 고를 수도 있어요. 성별을 추측하지 않고 각자 고르게 하려는 기능이에요.

- 화면에서 **내 캐릭터**를 누르면 대화창에 `내 캐릭터 꾸미기`가 나와요. 모양(머리·옷 10종)과 머리색·피부·상의·안에 입은 옷·바지·모자 색을 고르면 바로 미리 보여요.
- **나**는 이 PC의 `gh` 로그인(또는 `GITHUB_TOKEN`) 계정이에요. 다른 사람 캐릭터에는 버튼이 나오지 않아요.
- 저장하면 **내 GitHub 계정의 공개 gist** `nyang-office.json`에 남아요. 내 계정이라 나만 고칠 수 있고, 같은 저장소를 보는 다른 사람 화면에도 다음 갱신 때(최대 30분) 반영돼요.
- 저장이 안 되면 `gh auth refresh -s gist`로 gist 권한을 추가해 주세요.
- 성별(여성·남성·고르지 않음)을 고르면 모양 목록이 그에 맞게 바뀌어요. 성별만 고르고 모양을 안 고르면 그 안에서 아이디로 정해져요.
- 직접 만들어도 돼요. 공개 gist 에 이 파일 하나면 돼요: `{"gender":"m","art":"short","hair":"#2b2522","shirt":"#7fb2ea"}` (성별: `f` `m`, 생략 가능) (모양: `wavy` `longglasses` `ponytail` `ponyglasses` `bunhood` `bob` `short` `fringe` `curly` `beanie`)

## 터미널 열기 지원 범위

| 환경 | 터미널로 이동 | 이어하기 |
| --- | --- | --- |
| macOS Terminal / iTerm2 | 그 세션의 **탭까지** 앞으로 | Terminal 새 창 |
| macOS VS Code·Android Studio 등 안의 터미널 | 그 앱(프로젝트) 창을 앞으로 | Terminal 새 창 |
| Windows | 그 터미널 창을 앞으로 (탭 선택은 불가) | Windows Terminal 또는 cmd 새 창 |
| Linux | 아래 순서로 되는 방법을 찾아요 | gnome-terminal / konsole / xterm |

### 리눅스에서 "터미널로 이동"

리눅스는 화면 방식(X11 / Wayland)과 터미널 프로그램에 따라 되는 방법이 달라서, 아래 순서로 시도해요.

1. **tmux 안에서 claude를 실행 중이면**: 그 tmux 창·패널로 바로 전환해요. 설치할 것 없이, X11·Wayland 모두 돼요.
2. **kitty**: 원격 제어(`allow_remote_control yes`, `listen_on unix:/tmp/kitty`)를 켜 두면 그 창을 앞으로 가져와요.
3. **WezTerm**: 그 패널을 앞으로 가져와요.
4. **GNOME + [Window Calls](https://extensions.gnome.org/extension/4724/window-calls/) 확장**: Wayland에서도 창을 앞으로 가져와요.
   서버를 켤 때 GNOME(Wayland)인데 확장이 없으면 설치할지 물어봐요. y를 누르면 GNOME 설치 창이 뜨고, '설치'만 누르면 로그아웃 없이 바로 켜져요.
   직접 설치하려면 Extension Manager 앱(`sudo apt install gnome-shell-extension-manager`)에서 'Window Calls'를 찾으면 돼요.
5. **X11**: `wmctrl` 또는 `xdotool`로 가져와요. 둘 다 없으면 서버를 켤 때 설치할지 한 번 물어봐요. 대답은 `.agent_office_setup` 파일에 기억하고, 이 파일을 지우면 다시 물어봐요.

- Wayland에서는 보안 때문에 `wmctrl`·`xdotool`이 동작하지 않아요. 우분투 기본 화면은 Wayland예요.
- 서버를 켜면 터미널에 이 PC에서 무엇이 되는지("터미널로 이동: 준비됨" 또는 필요한 것)가 한 줄로 나와요.
- **gnome-terminal 탭**: gnome-terminal에는 탭을 고르는 기능이 바깥에 열려 있지 않아요. 그래서 그 세션 탭의 제목을 잠깐 표식으로 바꾸고, 탭을 하나씩 넘기며 찾아서 띄워요. Window Calls 확장이 필요해요. 찾는 동안 탭이 잠깐 넘어가는 게 보일 수 있고, 다른 창의 탭은 원래대로 되돌려요. 탭 제목은 Claude Code가 곧 다시 써요.
- 잘 안 되면 `python3 agent_office_server.py --check-terminal`을 실행해 보세요. 이 PC에서 무엇이 되는지 점검 결과를 보여줘요.

맥에서 처음 "터미널로 이동"을 누르면 "Python이 Terminal을 제어하려고 합니다"라는 창이 떠요. **허용**을 눌러야 동작해요.

## 안전

- 서버는 Claude Code 로그를 **읽기만** 해요. 설정이나 파일을 바꾸지 않아요.
- `127.0.0.1`에만 열려 있어서 다른 기기에서는 접속할 수 없어요.
- 다른 웹사이트가 이 서버를 몰래 부르지 못하게 `localhost` 주소로 온 요청만 받아요. 위젯도 localhost와 `--allow-embed`로 허용한 사이트에만 끼워 넣을 수 있어요.
- 터미널 열기 API는 이 페이지에서 보낸 요청만 받고(Host·Origin·전용 헤더 확인), 정해진 동작(이동·이어하기·폴더)만 실행해요.

## 자주 생기는 상황

- **사무실이 다 "입주 대기"예요**: 최근 6시간 안에 활동한 세션만 보여줘요. Claude Code에서 아무 작업이나 시키면 바로 입주해요.
- **로그 폴더가 없다고 나와요**: 기본 위치는 맥·리눅스 `~/.claude/projects`, 윈도우 `C:\Users\<사용자>\.claude\projects`예요. 다르면 `--dir`로 지정해 주세요.
- **포트가 이미 쓰이고 있어요**: `--port 9000`처럼 바꿔 주세요.
- **글씨체가 기본 폰트로 나와요**: 폰트를 Google Fonts에서 받아와요. 오프라인이어도 기능은 같아요.

## 파일

| 파일 | 설명 |
| --- | --- |
| `agent_office.html` | 화면 전체 (캔버스 렌더러, 시뮬레이션, 재생, 라이브 모드) |
| `agent_office_server.py` | 로그 감시 + 화면 제공 + 터미널 열기 + 웹앱(manifest·service worker·아이콘) 로컬 서버 |
