# Inside AI — 한국어 안내

영문 개요는 [README.md](../README.md).

CLI 에이전트(agy·Claude Code·Codex)가 남기는 생각 기록을 옆 터미널에서 보여주는 도구.
기존 CLI는 수정하지 않고, 각 CLI가 로컬에 쓰는 세션 기록 파일을 읽기만 한다.

## 설치

에이전트(Claude Code·Codex·agy)에게 이렇게 말하면 된다.

> https://github.com/gitvssh/inside-ai 의 docs/install.md를 따라 Inside AI를 설치하고 `ia doctor` 결과를 알려줘.

[install.md](install.md)는 에이전트가 읽고 그대로 실행하는 설치 절차서(영문)다. Linux·WSL2, Windows
PowerShell, macOS별 절차와 환경 확인, uv로 공개 소스 압축본에서 설치(Git 필요 없음), 번역기·말투 선택, 점검,
업데이트, 제거까지 담았다. 프로젝트 파일·CLAUDE.md·AGENTS.md·스킬·CLI 설정은 고치지 않도록 정해 두었다.
첫 설치 때 에이전트가 원하는 번역 말투를 한 번 묻는다(답하지 않으면 기본 auto 유지). 직접 설치하려면:

```bash
uv tool install https://github.com/gitvssh/inside-ai/archive/refs/heads/main.zip   # ia, inside-ai 명령 생성
ia setup              # 번역기(기본 agy)와 말투 선택. 에이전트용: ia setup --translator agy
ia doctor             # 오프라인 점검. --probe를 붙이면 합성 문장 1건을 실제 번역
```

- 검증된 환경은 Linux와 WSL2다. Windows(PowerShell 5.1/7)와 macOS는 코드와 계약 테스트를 준비했지만 실기 검증은
  아직 없다(`ia doctor`가 `!`로 알려 준다). PyPI에는 올리지 않았다.
- PowerShell: 설치 직후 이 창에서 `ia`가 안 보이면 `$env:Path = "$(uv tool dir --bin);$env:Path"`, 새 창부터는
  `uv tool update-shell`. uv가 없으면 `winget install --id=astral-sh.uv -e`(실행 정책은 바꾸지 않는다).
- 업데이트: `uv tool upgrade --reinstall inside-ai` 후 `ia doctor`. 압축본 설치는 버전이 같으면 `--reinstall`
  없이는 새 내용을 받지 않는다. 0.2까지 `git+https://…`로 설치했다면 `uv tool upgrade inside-ai`도 그대로 된다.
  제거: `uv tool uninstall inside-ai`. 설정(`~/.config/inside-ai/config.toml`)·말투 파일·번역 캐시는 그대로 남는다.
  Windows에서도 위치는 `%USERPROFILE%\.config\inside-ai\`처럼 사용자 홈 아래 같은 경로다.

## ia: CLI를 그대로 쓰면서 옆 창에 생각 보기

```bash
ia claude            # 원래 옵션 그대로: ia claude --resume <id>, ia claude -c
ia codex             # ia codex resume --last
ia agy               # ia agy --conversation <id>
```

- 화면을 세로로 나눠 오른쪽에 **이 세션 전용** 생각 창(`<클로드>의 생각은?` / `<지피티>` / `<제미나이>`)을 연다.
  - tmux 안: 그 tmux 창을 분할.
  - Windows Terminal + WSL Windows 연동(interop) 가능: Windows Terminal 창을 분할.
  - Windows(PowerShell) + Windows Terminal: 현재 창을 분할(실기 미검증). 그 밖의 콘솔은 두 번째 창에서 `ia view <id>`.
  - macOS: tmux가 있으면 위와 같고, 없으면 두 번째 터미널 창에서 `ia view <id>`.
  - 그 밖(기본): ia 전용 tmux 화면(`tmux -L inside-ai`)을 만들어 왼쪽 CLI·오른쪽 생각 창으로 띄운다.
    CLI가 끝나면 화면째 닫히고, 터미널 창을 닫으면 CLI도 함께 종료된다(백그라운드 잔류 없음).
    마우스 휠로 각 창을 스크롤할 수 있고, 글자 선택은 Shift+드래그. 끄려면 `IA_TMUX=0`.
- 창을 자동으로 못 열면 안내만 출력하며, 다른 창에서 `ia view`를 실행하면 가장 최근 ia 세션에 붙는다.
- ia는 연결 기록만 남기고 자기 프로세스를 CLI로 바꾼다(exec). 입력·승인·종료 코드는 CLI가 그대로 처리한다.
  Windows는 exec가 없어 같은 콘솔에서 CLI를 실행하고 끝날 때까지 기다려 종료 코드를 그대로 돌려준다(Ctrl+C는 CLI가 처리).
  npm으로 설치한 `claude.cmd`·`codex.cmd`는 cmd.exe를 거치지 않고 검증한 패키지 엔트리를 node로 직접 실행해,
  공백·한글·따옴표·`&`·`%`·`;`가 든 인자도 그대로 넘긴다.
- 세션 연결: Claude는 `--session-id`를 미리 정해 넘겨 정확히 연결. Codex·agy는 ia 실행 이후 시작된 같은
  폴더의 세션을 고르며, 다른 ia 창이 이미 연결한 세션은 건너뛴다.
- `claude mcp`, `codex login`, `--version` 같은 대화가 아닌 명령은 창 없이 그대로 실행한다.
- 끄기: `IA_OFF=1 ia claude`(창 없이 실행), `IA_NO_PANE=1`(창 자동 열기만 끔).
- 연결 기록·번역 캐시: `~/.local/state/inside-ai/` (7일 지난 연결 기록은 자동 정리).

## 전체 감시·목록

```bash
inside-ai sessions                        # 최근 24시간 세션과 생각 블록 수
inside-ai sessions -p agy --since 7d
inside-ai watch                           # 모든 CLI의 새 생각을 실시간 출력
inside-ai watch -p claude --project inside-ai
inside-ai watch -s 9e7562b9 --replay        # 특정 세션을 처음부터
inside-ai watch --jsonl --redact           # 측정용: 본문 없이 시각·지연·글자수만
```

- `watch`는 시작 시점 이후에 새로 기록된 생각만 낸다(`--replay`는 기존 기록 포함).
- 여러 세션·여러 CLI를 동시에 감시하며, 같은 생각은 한 번만 낸다. 기록 파일이
  다시 쓰이면 처음부터 읽되 이미 낸 블록은 건너뛰고, 내용이 바뀐 블록만 `수정됨`으로 낸다.

## 개발

```bash
git clone https://github.com/gitvssh/inside-ai && cd inside-ai
uv run --group dev pytest
```

기록 형식과 측정 결과는 [log-formats.md](log-formats.md).

## 한국어 번역

- 번역기는 `ia setup`으로 고른다. 감시하는 CLI와 번역기는 별개다(예: `ia claude`의 생각을 agy로 번역).

  | 번역기 | 쓰는 것 | 생각 원문이 전송되는 곳 | 한 건 지연(실측) |
  |---|---|---|---|
  | `agy` (기본) | 기존 agy 로그인 | Google(agy 계정) | 7~20초(모델에 따라) |
  | `claude` | 기존 Claude Code 로그인 | Anthropic | 16~23초(haiku) |
  | `codex` | 기존 Codex 로그인 | OpenAI | 6~10초 |
  | `gemini-api` | Gemini API 키 | Google Gemini API | 1~2초 |
  | `none` | — | 전송 안 함(원문) | — |

  `--model`을 생략하면 그 CLI의 기본 모델을 쓴다(`agy models`로 목록 확인, Claude는 `haiku`·`sonnet` 같은 별칭).
  Codex는 사용자 설정을 제외하므로 내장 기본 모델을 쓴다. Claude Code는 haiku로 검증했다.
  모델·계정에 따라 제공자 거절이 발생할 수 있으며, 이때 이유와 원문을 표시한다.
  번역은 고른 계정의 사용량·구독 한도를 쓴다.
- CLI 번역기는 번역 한 건마다 빈 임시 폴더에서 비대화로 새로 실행한다. 원문은 stdin으로만 보내고, 사용자 코딩
  세션을 이어 쓰지 않으며, 도구·MCP·훅·스킬·프로젝트 지침은 CLI가 허용하는 만큼 끈다. 권한 우회 플래그는 쓰지 않는다.
  agy는 모든 도구를 끄는 방법이 확인되지 않았다. 도구 단계가 보이면 중단하지만 이미 시작된 동작은
  막지 못할 수 있고, 기존 agy 권한 설정이 적용된다(자세한 한계는 install.md의 격리 표).
- agy는 번역 호출도 자기 대화 목록에 남긴다. Inside AI는 그 세션을 알아보고(요청 첫 줄의 표식, 기록한 대화 ID,
  임시 폴더 이름) 생각 창·`watch`·세션 연결에서 뺀다. agy의 `/resume` 목록에는 남는다.
- **생각 원문이 고른 제공자로 전송된다.** 코드·경로·비밀값이 생각에 들어 있으면 함께 전송될 수 있다.
  민감한 작업은 `ia view --original` 또는 `IA_TRANSLATE=0 ia claude`로 원문만 본다.
- Gemini API 키: `GEMINI_API_KEY` 환경변수 → 없으면 설정 파일의 `[gemini] key_command`(키를 표준출력으로 내는
  명령, 셸 없이 실행)로 받아 메모리에만 둔다. 0.1.x처럼 `[gemini]` 설정이나 `GEMINI_API_KEY`가 있고 `[translation]`이
  없으면 계속 Gemini API로 번역한다. agy로 바꾸려면 `ia setup --translator agy`.
- 번역기를 시작할 수 없으면(설치 안 됨·키 없음) 창에 이유를 한 줄 알리고 원문으로 표시한다. 다른 번역기로 몰래
  바꾸지 않는다. 번역이 실패한 생각은 이유를 한 번 알리고 `원문(번역 실패)` 표시와 함께 원문으로 보여준다.
- **말투(페르소나)**: 기본값 `auto`는 CLI마다 작성자가 만든 의인화 캐릭터 말투로 옮긴다(`src/inside_ai/personas.py`).
  | CLI | 캐릭터 | 말투 |
  |---|---|---|
  | Claude Code | 클로드쨩 | 차분하고 따뜻한 해요체, 사용자 감정을 먼저 헤아림 |
  | Codex | 지피짱 | 조용하고 말수 적은 반말, 일할 땐 원인·다음 할 일을 딱 잘라 말하는 실무형 |
  | agy | 젬쨩 | 자신감 있고 살짝 도도한 반말, 잘 풀리면 뿌듯, 혼나면 살짝 삐짐 |

  말버릇·감탄사는 고정 대사가 아니라 감정·실수·사용자 반응이 있을 때만 가끔 나오게 했다. 같은 창에서 직전
  번역 3개를 함께 넘겨 어미·시작 표현이 반복되지 않게 한다(말 높임은 유지). 뜻·코드·경로는 바꾸지 않는다.
  말투 지시 내용의 해시별로 번역 캐시가 따로 저장된다.
  평범한 번역으로 보려면 `IA_PERSONA=0 ia claude`.
- 말투 고르기·만들기(번역기·모델은 바뀌지 않는다. 새로 여는 창부터 적용):

  ```bash
  ia persona list                               # 기본 제공·사용자 말투와 CLI별 적용 상태(--json: 에이전트용)
  ia setup --persona polite                     # 모든 CLI를 차분한 해요체로
  ia setup --persona plain --for-agent codex    # Codex를 볼 때만 담백한 반말
  ia setup --persona inherit --for-agent codex  # 그 예외 지우기
  ia persona create my-tone --name "내 말투" --style "차분하고 짧게, 해요체로. 비유는 쓰지 않음."
  ia setup --persona my-tone
  ia persona preview --persona my-tone          # 고정 합성 예문 1건을 실제 번역기로(사용량 소비, 세션 기록은 안 씀)
  ```

  기본 제공: `auto`(CLI별 캐릭터), `plain`(담백한 반말), `polite`(차분한 해요체), `claude-chan`·`gpt-chan`·
  `gemini-chan`(캐릭터 직접 지정). 사용자 말투는 설정 폴더의 `personas/<id>.toml`(name·style·color)이며 코드나
  명령을 실행하지 않는 데이터 파일이다. 파일을 복사해 다른 사람과 공유할 수 있다. 적용 순서는 `IA_PERSONA`
  → `[persona.agents]` → `[persona] default` → `auto`. 잘못된 말투는 조용히 무시하지 않고 창에 이유·복구 방법을
  보여 준 뒤 auto로 번역한다(`ia doctor`는 ✗).
- 번역 지시문 구조는 [omp-thinking-ko](https://github.com/hvvsdcm/omp-thinking-ko)(MIT)를 참고했다.

## 번역 캐시

번역 결과는 `~/.local/state/inside-ai/translations.sqlite`에 원문 해시(번역기 ID 포함) 단위로 저장한다.
창 여러 개가 같은 생각을 동시에 만나도 한 창만 번역하고 나머지는 결과를 기다린다. 창을 다시 열거나
재시작해도 저장된 번역을 재사용한다. 번역 중 창이 죽으면 번역 제한 시간보다 조금 더 지난 뒤(기본 2분) 다른 창이 이어받는다. 번역기·모델·말투가 바뀌면 캐시도 따로 쌓인다(같은 이름의 말투라도 내용이 바뀌면 분리).
