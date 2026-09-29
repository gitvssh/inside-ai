# Inside AI — 한국어 안내

영문 개요는 [README.md](../README.md).

CLI 에이전트(agy·Claude Code·Codex)가 남기는 생각 기록을 옆 터미널에서 보여주는 도구.
기존 CLI는 수정하지 않고, 각 CLI가 로컬에 쓰는 세션 기록 파일을 읽기만 한다.

## 설치

```bash
git clone https://github.com/gitvssh/inside-ai && cd inside-ai
uv tool install --editable .      # ia, inside-ai 명령이 ~/.local/bin 에 생김
```

## ia: CLI를 그대로 쓰면서 옆 창에 생각 보기

```bash
ia claude            # 원래 옵션 그대로: ia claude --resume <id>, ia claude -c
ia codex             # ia codex resume --last
ia agy               # ia agy --conversation <id>
```

- 화면을 세로로 나눠 오른쪽에 **이 세션 전용** 생각 창(`<클로드>의 생각은?` / `<지피티>` / `<제미나이>`)을 연다.
  - tmux 안: 그 tmux 창을 분할.
  - Windows Terminal + WSL Windows 연동(interop) 가능: Windows Terminal 창을 분할.
  - 그 밖(기본): ia 전용 tmux 화면(`tmux -L inside-ai`)을 만들어 왼쪽 CLI·오른쪽 생각 창으로 띄운다.
    CLI가 끝나면 화면째 닫히고, 터미널 창을 닫으면 CLI도 함께 종료된다(백그라운드 잔류 없음).
    마우스 휠로 각 창을 스크롤할 수 있고, 글자 선택은 Shift+드래그. 끄려면 `IA_TMUX=0`.
- 창을 자동으로 못 열면 안내만 출력하며, 다른 창에서 `ia view`를 실행하면 가장 최근 ia 세션에 붙는다.
- ia는 연결 기록만 남기고 자기 프로세스를 CLI로 바꾼다(exec). 입력·승인·종료 코드는 CLI가 그대로 처리한다.
- 세션 연결: Claude는 `--session-id`를 미리 정해 넘겨 정확히 연결. Codex·agy는 ia 실행 이후 시작된 같은
  폴더의 세션을 고르며, 다른 ia 창이 이미 연결한 세션은 건너뛴다.
- `claude mcp`, `codex login`, `--version` 같은 대화가 아닌 명령은 창 없이 그대로 실행한다.
- 끄기: `IA_OFF=1 ia claude`(창 없이 실행), `IA_NO_PANE=1`(창 자동 열기만 끔).
- 연결 기록·번역 캐시: `~/.local/state/inside-ai/` (7일 지난 연결 기록은 자동 정리).

## 전체 감시·목록

```bash
uv sync
uv run inside-ai sessions                 # 최근 24시간 세션과 생각 블록 수
uv run inside-ai sessions -p agy --since 7d
uv run inside-ai watch                    # 모든 CLI의 새 생각을 실시간 출력
uv run inside-ai watch -p claude --project inside-ai
uv run inside-ai watch -s 9e7562b9 --replay   # 특정 세션을 처음부터
uv run inside-ai watch --jsonl --redact   # 측정용: 본문 없이 시각·지연·글자수만
```

- `watch`는 시작 시점 이후에 새로 기록된 생각만 낸다(`--replay`는 기존 기록 포함).
- 여러 세션·여러 CLI를 동시에 감시하며, 같은 생각은 한 번만 낸다. 기록 파일이
  다시 쓰이면 처음부터 읽되 이미 낸 블록은 건너뛰고, 내용이 바뀐 블록만 `수정됨`으로 낸다.

## 개발

```bash
uv run --group dev pytest
```

기록 형식과 측정 결과는 [log-formats.md](log-formats.md).

## 한국어 번역

- `ia` 생각 창은 기본으로 Gemini API(`gemini-3.8-flash`, 추론 수준 low)로 번역해 보여준다. 한 건 1~2초.
  `inside-ai watch --translate`도 같다.
- **생각 원문이 Google Gemini API로 전송된다.** 코드·경로·비밀값이 생각에 들어 있으면 함께 전송될 수 있다.
  민감한 작업은 `ia view --original` 또는 `IA_TRANSLATE=0 ia claude`로 원문만 본다.
- API 키: `GEMINI_API_KEY` 환경변수 → 없으면 설정 파일 `~/.config/inside-ai/config.toml`의
  `[gemini] key_command`(키를 표준출력으로 내는 명령, 셸 없이 실행)로 받아 메모리에만 둔다.
  비밀 저장소(pass, 1Password CLI, Vault 등)를 쓰려면 그 조회 명령을 적는다. 모델 변경은 `IA_MODEL`
  또는 `[gemini] model`.
- 키를 못 얻으면(비밀 저장소 로그인 만료 등) 창에 이유와 `key_hint`를 한 줄 알리고 원문으로 표시한다. 번역이 실패한 생각은
  `원문(번역 실패)` 표시와 함께 원문으로 보여준다(일시 오류는 한 번 재시도).
- **캐릭터 말투**: CLI마다 작성자가 만든 의인화 캐릭터 설정을 따른 말투로 옮긴다(`src/inside_ai/personas.py`).
  | CLI | 캐릭터 | 말투 |
  |---|---|---|
  | Claude Code | 클로드쨩 | 차분하고 따뜻한 해요체, 사용자 감정을 먼저 헤아림 |
  | Codex | 지피짱 | 조용하고 말수 적은 반말, 일할 땐 원인·다음 할 일을 딱 잘라 말하는 실무형 |
  | agy | 젬쨩 | 자신감 있고 살짝 도도한 반말, 잘 풀리면 뿌듯, 혼나면 살짝 삐짐 |

  말버릇·감탄사는 고정 대사가 아니라 감정·실수·사용자 반응이 있을 때만 가끔 나오게 했다. 같은 창에서 직전
  번역 3개를 함께 넘겨 어미·시작 표현이 반복되지 않게 한다(말 높임은 유지). 뜻·코드·경로는 바꾸지 않는다.
  캐릭터·프롬프트 버전별로 번역 캐시가 따로 저장된다.
  평범한 번역으로 보려면 `IA_PERSONA=0 ia claude`.
- 번역 지시문 구조는 [omp-thinking-ko](https://github.com/hvvsdcm/omp-thinking-ko)(MIT)를 참고했다.

## 번역 캐시

번역 결과는 `~/.local/state/inside-ai/translations.sqlite`에 원문 해시(번역기 ID 포함) 단위로 저장한다.
창 여러 개가 같은 생각을 동시에 만나도 한 창만 번역하고 나머지는 결과를 기다린다. 창을 다시 열거나
재시작해도 저장된 번역을 재사용한다. 번역 중 창이 죽으면 90초 뒤 다른 창이 이어받는다.
