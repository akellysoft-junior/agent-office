# Agent Office 🐾

내 PC에서 돌아가는 **Claude Code 세션들을 고양이 동네의 사무실로 실시간 시각화**하는 로컬 웹 툴입니다.

- 세션 하나 = 사무실 한 채. 메인 에이전트는 대장 고양이가 맡아요.
- 서브에이전트가 생기면 새끼 고양이가 출근하고, 그 수만큼 책상이 늘어나요.
- 할 일이 없는 고양이는 휴게공간(소파·캣타워·러그·밥그릇)에서 쉬어요.
- 세션이 답을 마치고 명령을 기다리면 대장이 문 앞에서 "냥?" 팻말을 들고 기다려요.
- 작업이 끝나면 "완료!" 도장, 꽃가루, 결과 알림이 떠요.
- 세션마다 "지금 하는 일" 요약 카드(요청, 할 일 진행률, 현재 작업, 통계)를 보여줘요.
- 고양이를 누르면 뜨는 대화창이나 카드에서 그 세션의 터미널로 이동하거나, 새 터미널에서 이어하기(`claude --resume`)를 할 수 있어요. 위젯에서도 돼요.
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
| `--no-codex` | Codex 세션(`~/.codex/sessions`)은 보여주지 않기 | 꺼짐 (Codex 세션도 함께 보여줌) |
| `--install` / `--uninstall` | 로그인 시 자동 시작 등록 / 해제 | |
| `--no-hooks` / `--uninstall-hooks` | 세션 시작·끝을 알려 주는 hook 을 등록하지 않기 / 등록한 hook 빼기 | 켜짐 (서버를 켤 때 등록) |
| `--check-terminal` | (리눅스) '터미널로 이동' 환경 점검 | |
| `--repo owner/name` | 본사에 보여줄 깃허브 저장소 | 세션 폴더의 git origin에서 자동으로 찾음 |
| `--github-host HOST` | 회사 깃허브(GitHub Enterprise Server) 주소 (예: `github.company.net`). 토큰은 `gh auth login --hostname HOST` 또는 `GH_ENTERPRISE_TOKEN` | github.com |
| `--allow-embed ORIGIN` | 위젯을 끼워 넣을 수 있는 바깥 사이트 (여러 번 쓸 수 있음) | localhost만 허용 |

### 매번 치기 귀찮다면

```bash
# ~/.zshrc 또는 ~/.bashrc
alias cats='python3 ~/path/to/agent-office/agent_office_server.py'
```

윈도우는 같은 폴더에 `냥이오피스.bat`을 만들고 `py "%~dp0agent_office_server.py"` 한 줄을 넣으면 더블클릭으로 실행돼요.

## 세션이 끝나면 퇴근 (hook)

로그 파일에는 "세션이 꺼졌다"는 기록이 없어서, 서버를 켤 때 Claude Code와 Codex에 hook 을 등록해 두고 각 도구가 직접 알려 주게 해요.

- Claude Code (`~/.claude/settings.json`): 세션 시작·끝, 턴 끝, 권한 승인 대기
- Codex (`~/.codex/hooks.json`): 세션 시작, 턴 끝, 권한 승인 대기. 세션 끝 이벤트가 없어서, 시작할 때 기억한 Codex 프로세스가 사라지면 끝난 걸로 봐요. Codex는 새 hook 을 한 번 신뢰(승인)해 줘야 동작해요.
- 터미널을 그냥 닫아서 끝 알림이 안 와도, 기억해 둔 프로세스가 사라지면 퇴근해요 (macOS·리눅스·윈도우).
- 기억한 세션 정보는 `~/.cache/agent-office/hook_sessions.json` 에 저장해서, 서버가 업데이트로 다시 켜져도 이어서 지켜봐요.
- 서버를 여러 개 켜 두면(포트가 달라도) 모두 같은 신호를 받아요. 켜진 서버는 `~/.cache/agent-office/servers/<포트>.json` 에 자기 포트를 적어 두고 끌 때 지우며, hook 은 이 목록 전체에 보내요.
- 같은 정보로 '터미널로 이동'이 정확한 터미널을 찾아가요. Codex 세션에서도, 위젯에서도 쓸 수 있어요.
- 원래 설정 파일은 `*.agent-office.bak` 으로 남기고, 이미 등록돼 있으면 건드리지 않아요. 빼려면 `--uninstall-hooks`.
- hook 을 등록하기 전에 켠 세션은 예전처럼 로그로만 짐작해요.

### 쉬기·퇴근 규칙
- 명령을 15분 넘게 기다리면 휴게실에서 쉬어요. 질문·계획·승인을 기다릴 땐 자리에서 팻말을 들고 기다려요.
- 마지막 기록 뒤 12시간이 지나면 휴게실, 24시간이 지나면 화면에서 빠져요. 다만 그 세션의 프로그램(터미널)이 아직 켜져 있으면 하루가 지나도 휴게실에 남아요.
- hook 이 없는 세션도 실행 중인지 짐작해요: 돌고 있는 claude 프로세스를 30초마다 찾아서, 명령줄의 세션 ID나 같은 작업 폴더의 가장 최근 기록과 짝지어요 (macOS·리눅스).
- hook 을 쓰기 전부터 남아 있던 세션(hook 신호가 한 번도 없던 세션)은 2개까지만(실행 중인 것 먼저, 그다음 최근 것), 그것도 hook 세션이 자리를 다 쓰지 않을 때만 보여요. 그 세션을 다시 쓰면 최근 순서대로 다시 골라요.

## 기여자 캐릭터 정하기 (YAML)

기본은 GitHub 아이디로 정해지는 모습이에요. YAML 파일에 아이디별로 그림 종류·성별·색을 적어 두면 그 값으로 바뀌어요. 적는 법은 `characters.example.yml` 을 보세요.

가장 쉬운 방법은 캐릭터 설정 페이지예요: `http://localhost:8765/?page=characters` (또는 `/characters`) (상단 **🎨 캐릭터 설정** 버튼을 누르면 새 탭으로 열려요). 왼쪽에 기여자 목록, 가운데에 서 있는·일하는 모습 미리보기가 있어요. 위젯을 쓸 때도 이 페이지에서 정하면 위젯에 그대로 나와요. 기여자를 골라 성별·모양·색을 고르면 바로 미리 보여 주고, 아래 버튼으로 마무리해요.
- **💾 내 컴퓨터에 저장 (바로 적용)**: `~/.config/agent-office/characters.yml` 에 써서 화면에 바로 반영돼요 (원래 파일은 `.bak` 으로 남김).
- **📂 설정 파일 열기**: 그 파일을 편집기로 열어요. 직접 고치고 저장하면 몇 초 안에 반영돼요.
- **🔄 저장소 설정 다시 받기**: 팀 저장소의 `.nyang-office.yml` 을 기다리지 않고 지금 다시 받아요.
- **🎲 랜덤 조합**: 모양과 색을 새로 뽑아요 (성별을 골라 두면 그 성별 안에서). 마음에 들면 저장하세요.
- **복사**: 팀 모두에게 보이게 하려면 복사해서 저장소 `.nyang-office.yml` 에 붙여 넣으세요.

성별만 적으면 랜덤이 아니라 아이디로 정해진 모습이에요 (매번 같음). 매번 다른 조합을 보고 싶으면 🎲 랜덤 조합을 누르세요.

- 내 컴퓨터: `~/.config/agent-office/characters.yml` (또는 `--characters 경로`). 파일을 고치면 5분 안에 반영돼요.
- 팀 저장소: 저장소 맨 위에 `.nyang-office.yml` 을 두면 팀 모두에게 같은 모습으로 보여요. 30분마다 다시 받고, 서버를 다시 켜거나 페이지를 새로고침하면 바로 다시 받아요 (페이지 새로고침은 1분에 한 번까지).
- 냥오피스 코드를 다른 프로젝트 안(예: `vendor/agent-office/`)에 넣어 쓴다면: 그 프로젝트 맨 위에 `.nyang-office.yml` 을 두세요. 서버가 자기 폴더 위쪽을 찾아 올라가서 읽고, 🎨 캐릭터 설정의 저장도 그 파일에 써요 (프로젝트와 같이 커밋하면 팀이 공유). `vendor/agent-office/` 안에 둬도 읽지만, 스냅샷을 새로 받으면 덮어써지니 프로젝트 맨 위를 권해요.
- 내 컴퓨터에서 읽는 파일 고르는 순서: `--characters 경로`(또는 환경변수 `NYANG_OFFICE_CHARACTERS`) > 프로젝트의 `.nyang-office.yml` > `~/.config/agent-office/characters.yml`
- 우선순위: 내 컴퓨터에서 읽은 파일 > GitHub 저장소 파일 > 본인 gist > 아이디 기본 모습

## 앱으로 설치 (웹앱)

1. 서버를 켜고 Chrome이나 Edge로 `http://localhost:8765`를 엽니다.
2. 위쪽 **📲 앱으로 설치** 버튼(또는 주소창 오른쪽의 설치 아이콘)을 누릅니다.
3. 이제 독·시작 메뉴의 **냥오피스** 아이콘으로 열 수 있어요.

- 앱도 이 서버에서 데이터를 받아요. 쓰기 전에 서버를 켜 두세요. 서버가 꺼져 있으면 마지막 화면으로 시뮬레이션 모드가 열려요.
- 포트를 바꾸면(`--port`) 다른 앱으로 인식돼요. 늘 같은 포트로 켜는 걸 추천해요.
- 아이콘 배지와 창 제목의 숫자는 아직 확인하지 않은 완료·질문 수예요. 그 세션에 새 요청을 보내거나 사무실을 열어 보면 지워져요.

## 화면 보는 법

- **동네 화면**: 입주한 사무실 위 이름표에 상태(⚙ 작업 중 · 💬 명령 대기 · ✓ 완료 · ❓ 답변 대기 · ⏳ 승인 필요?)가 떠요.
- **캐릭터 클릭**: 고양이(AI)나 사람(깃허브 기여자)을 누르면 확대되고 대화창에서 자기소개를 해요. 대사를 누르거나 Enter로 다음, `Esc`로 닫아요. AI 고양이는 대화창의 **터미널로 이동**을 누르거나 고양이를 **두 번 누르면** 그 세션이 도는 터미널 탭이 앞으로 와요. 끝난 세션(기록만 남아 고양이가 보이는 경우)이면 새 터미널에서 그 세션을 이어서 열어요(`claude --resume`).
- **모델·요금·컨텍스트**: 팀장냥은 자기소개 다음에 지금 쓰는 모델, 그 세션이 지금까지 쓴 요금(새끼냥 몫 포함), 컨텍스트가 얼마나 찼는지를 한 줄로 말해요 (“두뇌는 Opus 5.5! 지금까지 츄르값 $71.21어치 썼고, 머릿속은 29% 찼어요.”). 새끼냥도 자기 모델과 요금을 말해요. 요금은 서버가 세션 로그의 사용량을 처음부터 더해 **공개 API 정가**로 환산한 값이라, 구독 요금제로 쓰면 실제로 내는 돈과 달라요. Claude Code가 세션을 끌 때 로그에 적어 두는 누적 요금이 있으면 그 값에서 이어 세서, 다시 열었을 때 터미널에 보이는 값과 맞춰요. 옛 세션을 이어서 열면, 첫 응답이 오기 전까지는 로그의 옛 모델 대신 지금 켜진 모델을 말해요. 요금표(`agent_office_server.py`의 `CLAUDE_PRICES`·`CODEX_PRICES`, 2026-11-24 기준)에 없는 모델은 금액을 빼고 말해요. 컨텍스트 크기는 모델 기준(대부분 100만 토큰)이라 요금제에 따라 실제 한도와 다를 수 있어요.
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
- **둘러보기**: 마우스로 끌기, 폰에선 가로로 쓸기. ＋/－/⤢ 버튼이나 마우스 휠(트랙패드는 두 손가락 쓸기·핀치)로 확대해요.
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
| `data-repo="owner/name"` | 본사에 보여줄 깃허브 저장소. 깃 주소(`https://github.com/owner/name.git`, `git@github.com:…`)도 돼요. 없으면 서버가 정한 저장소(`--repo` 또는 자동) |
| `data-theme="light\|dark\|auto"` | 페이지 테마 |
| `data-tod="day\|dusk\|night\|auto"` | 동네 그림의 낮·밤 |
| `data-team="0"` | 깃허브 팀 끄기 |
| `data-follow="0"` | 자동 따라가기 끄기 |
| `data-controls="0"` | 왼쪽 위 ＋/－/⤢ 확대 버튼 숨기기 (기본은 보임. 숨겨도 휠·핀치로는 확대돼요) |
| `data-wheel="ctrl"` | 그냥 휠은 바깥 페이지 스크롤에 양보하고 Ctrl(⌘)+휠·핀치일 때만 확대. 기본은 위젯 위에서 그냥 휠로 확대 |
| `data-demo="1"` | 가짜 세션·가짜 팀으로 보기 |
| `data-height="360px"` | 상자에 높이가 없을 때 쓸 높이 (기본 420px) |

- React·Vue처럼 화면을 나중에 그리는 앱도 괜찮아요. `data-agent-office`가 붙은 요소가 생기면 알아서 채워요. 직접 넣으려면 `AgentOffice.mount(요소, {repo:"owner/name"})`.
- 휠과 확대 버튼은 쓰는 중에도 바꿀 수 있어요. 예를 들어 평소엔 버튼을 숨기고 휠로 확대하다가, 페이지 스크롤이 필요한 상황에선 `send("wheel", {value:"ctrl"})` 로 휠을 양보하고 `send("controls", {value:true})` 로 버튼을 꺼내 주세요.
- iframe 한 줄로 넣어도 돼요: `<iframe src="http://localhost:8765/?embed=1&repo=owner/name" style="width:100%;height:420px;border:0"></iframe>`
- 기본으로 `localhost`에서 도는 웹 툴만 끼워 넣을 수 있어요. 다른 주소의 사이트라면 서버를 `--allow-embed https://tool.example.com`으로 켜 주세요.

**위젯이 보내는 이벤트** (위젯을 넣은 요소에서 받아요)

```js
const box = document.querySelector("[data-agent-office]");
box.addEventListener("agent-office:select", e => console.log(e.detail));    // 고양이를 눌렀을 때 {kind:"human"|"ai-main"|"ai-sub", name, login?, session?}
box.addEventListener("agent-office:close", () => {});                       // 대화창을 닫았을 때
box.addEventListener("agent-office:attention", e => e.detail);             // 확인 안 한 것 {count, questions, done, items:[{session, kind:"question"|"plan"|"approval"|"done"}]}
box.addEventListener("agent-office:team", e => e.detail);                   // 팀 정보를 불러왔을 때 {repo, members}
box.__agentOffice.send("select", {login:"octocat"});                         // 바깥에서 그 사람에게 말 걸기
box.__agentOffice.send("wheel", {value:"ctrl"});                             // 지금부터 휠을 바깥 페이지 스크롤에 양보 ("zoom" 이면 다시 휠로 확대)
box.__agentOffice.send("controls", {value:true});                            // 확대 버튼 보이기 (false 면 숨기기)
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
| Codex 세션 | 터미널에서 도는 CLI는 그 탭, 데스크톱 앱(macOS)은 앱을 앞으로 | 지원 안 함 |
| Windows | 그 터미널 창을 앞으로 (탭 선택은 불가) | Windows Terminal 또는 cmd 새 창 |
| Linux | 아래 순서로 되는 방법을 찾아요 | gnome-terminal / konsole / xterm |

### 리눅스에서 "터미널로 이동"

리눅스는 화면 방식(X11 / Wayland)과 터미널 프로그램에 따라 되는 방법이 달라서, 아래 순서로 시도해요.

1. **tmux 안에서 claude를 실행 중이면**: 그 tmux 창·패널로 바로 전환해요. 설치할 것 없이, X11·Wayland 모두 돼요. 그다음 tmux가 붙어 있는 터미널의 탭·창을 아래 방법으로 찾아요. 그 tmux 세션을 띄워 둔 터미널이 없으면(`tmux new -d` 로 켜 둔 세션, 웹 화면의 내장 터미널에서만 열어 둔 세션 등) 새 터미널 창을 열어 `tmux attach` 해요.
2. **kitty**: 원격 제어(`allow_remote_control yes`, `listen_on unix:/tmp/kitty`)를 켜 두면 그 창을 앞으로 가져와요.
3. **WezTerm**: 그 패널을 앞으로 가져와요.
4. **GNOME + [Window Calls](https://extensions.gnome.org/extension/4724/window-calls/) 확장**: Wayland에서도 창을 앞으로 가져와요.
   서버를 켤 때 GNOME(Wayland)인데 확장이 없으면 설치할지 물어봐요. y를 누르면 GNOME 설치 창이 뜨고, '설치'만 누르면 로그아웃 없이 바로 켜져요.
   직접 설치하려면 Extension Manager 앱(`sudo apt install gnome-shell-extension-manager`)에서 'Window Calls'를 찾으면 돼요.
5. **Konsole**: Konsole이 제공하는 D-Bus로 그 세션의 탭을 골라요. 창을 앞으로 가져오는 건 X11에서만 돼요.
6. **X11**: `wmctrl` 또는 `xdotool`로 가져와요. 둘 다 없으면 서버를 켤 때 설치할지 한 번 물어봐요. 대답은 `.agent_office_setup` 파일에 기억하고, 이 파일을 지우면 다시 물어봐요.

- Wayland에서는 보안 때문에 `wmctrl`·`xdotool`이 동작하지 않아요. 우분투 기본 화면은 Wayland예요.
- 서버를 켜면 터미널에 이 PC에서 무엇이 되는지("터미널로 이동: 준비됨" 또는 필요한 것)가 한 줄로 나와요.
- **gnome-terminal 탭**: gnome-terminal에는 탭을 고르는 기능이 바깥에 열려 있지 않아요. 그래서 그 세션 탭의 제목을 잠깐 표식으로 바꾸고, 탭을 하나씩 넘기며 찾아서 띄워요. 창 제목을 읽을 수 있어야 해서 Wayland에서는 Window Calls 확장이, X11에서는 `xdotool`이나 `wmctrl`이 필요해요. 찾는 동안 탭이 잠깐 넘어가는 게 보일 수 있고, 다른 창의 탭과 탭 제목은 원래대로 되돌려요.
- **탭까지 가는 터미널**: tmux, kitty, WezTerm, gnome-terminal, Konsole. 그 밖의 터미널(Ptyxis, Tilix, xfce4-terminal, VS Code 안의 터미널 등)은 바깥에서 탭을 고르는 방법이 없어서 창만 앞으로 와요. 이런 터미널에서는 tmux 안에서 claude를 쓰면 그 세션 화면까지 가요.
- 잘 안 되면 `python3 agent_office_server.py --check-terminal`을 실행해 보세요. 이 PC에서 무엇이 되는지 점검 결과를 보여줘요.

- 어느 터미널인지는 Claude Code가 남기는 `~/.claude/sessions/<pid>.json`으로 찾아요. 같은 폴더에서 세션을 여러 개 돌려도 정확한 탭으로 가요. (이 파일이 없는 옛 버전은 폴더와 시작 시각으로 골라요.)

맥에서 처음 "터미널로 이동"을 누르면 "Python이 Terminal을 제어하려고 합니다"라는 창이 떠요. **허용**을 눌러야 동작해요.

## 안전

- 서버는 Claude Code 로그를 **읽기만** 해요. 설정이나 파일을 바꾸지 않아요.
- `127.0.0.1`에만 열려 있어서 다른 기기에서는 접속할 수 없어요.
- 다른 웹사이트가 이 서버를 몰래 부르지 못하게 `localhost` 주소로 온 요청만 받아요. 위젯도 localhost와 `--allow-embed`로 허용한 사이트에만 끼워 넣을 수 있어요.
- 터미널 열기 API는 이 페이지에서 보낸 요청만 받고(Host·Origin·전용 헤더 확인), 정해진 동작(이동·이어하기·폴더)만 실행해요.

## 자주 생기는 상황

- **사무실이 다 비어 있어요**: 최근 하루 안에 활동한 세션만 보여줘요. Claude Code에서 아무 작업이나 시키면 바로 입주해요.
- **로그 폴더가 없다고 나와요**: 기본 위치는 맥·리눅스 `~/.claude/projects`, 윈도우 `C:\Users\<사용자>\.claude\projects`예요. 다르면 `--dir`로 지정해 주세요.
- **포트가 이미 쓰이고 있어요**: `--port 9000`처럼 바꿔 주세요.
- **글씨체가 기본 폰트로 나와요**: 폰트를 Google Fonts에서 받아와요. 오프라인이어도 기능은 같아요.

## 파일

| 파일 | 설명 |
| --- | --- |
| `agent_office.html` | 화면 전체 (캔버스 렌더러, 시뮬레이션, 재생, 라이브 모드) |
| `agent_office_server.py` | 로그 감시 + 화면 제공 + 터미널 열기 + 웹앱(manifest·service worker·아이콘) 로컬 서버 |

## 라이선스

[MIT](LICENSE) © 2026 akellysoft-junior. 코드와 `agent_office.html`에 들어 있는 캐릭터 그림 모두 MIT로 써도 돼요.

함께 쓰는 것:
- 글꼴 [Jua](https://fonts.google.com/specimen/Jua), [Gowun Dodum](https://fonts.google.com/specimen/Gowun+Dodum), [IBM Plex Mono](https://fonts.google.com/specimen/IBM+Plex+Mono): SIL Open Font License 1.1. 저장소에 넣지 않고 Google Fonts에서 받아 와요.
- 위젯에 나오는 깃허브 프로필(이름·사진·자기소개)은 실행할 때 GitHub API에서 받아 오는 각 사용자의 정보예요. 저장소에 들어 있지 않아요.
