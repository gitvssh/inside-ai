# CLI 생각 기록 형식과 1단계 측정 결과

last_verified: 2026-09-28 (agy 1.2.7, Codex CLI 0.157.1, Claude Code 현행)

## 도구별 기록 위치

| 도구 | 파일 | 생각 필드 | 세션 ID | 작업 폴더 |
|---|---|---|---|---|
| agy | `~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript_full.jsonl` | `source=MODEL, type=PLANNER_RESPONSE` 레코드의 `thinking` | 폴더명 | `conversation_summaries.db`의 `workspace_uris`(비어 있는 세션 많음) |
| Claude Code | `~/.claude/projects/<인코딩된 cwd>/<session>.jsonl` | `type=assistant` 의 `message.content[type=thinking].thinking` | 파일명 | 각 레코드 `cwd` |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | `response_item` / `payload.type=reasoning` 의 `summary[].text` | `session_meta.payload.id` | `session_meta.payload.cwd` |

- agy `transcript.jsonl`은 긴 필드를 잘라 저장한다(`truncated_fields`). 전체본은 `transcript_full.jsonl`이며,
  `chunks/transcript_full/*.jsonl`은 같은 내용을 100KB 단위로 나눈 사본이다.
- Claude Code의 thinking 블록은 빈 문자열(서명만)인 경우가 많다. 최근 15개 세션 표본: 비어 있음 3351, 내용 있음 1008.
  원인: 설정 `showThinkingSummaries`가 없거나 false면 Anthropic API가 thinking을 가린다(공식 문서
  https://code.claude.com/docs/en/settings-reference#showthinkingsummaries, "in interactive sessions").
  `true`로 두면 요약이 채워진다. 2026-09-28 `ia claude -p` 시험 세션도 빈 블록이었다(현재 설정 미지정).
- Codex의 원문 추론은 `encrypted_content`로만 저장된다. 요약(`summary`)은 현재 설정(`model_reasoning_summary` 미설정)에서
  최근 표본 모두 비어 있다.

## 기록 시점 측정 (2026-09-28)

| 도구 | 방법 | 결과 |
|---|---|---|
| agy | `agy -p` 짧은 질문 1회, 0.5초 간격으로 파일 크기 표본 + 수집기 실시간 감시 | 생각은 **step이 끝날 때 한 번에** 기록됨(생각 중 스트리밍 없음). step 시작 기준 9.2초 뒤 표시, step 종료와 거의 동시. 저장된 생각 281자 / thinking_tokens 813 → 원문 전체가 아닌 요약으로 보임 |
| Claude Code | 동시에 돌던 실제 세션들을 3분간 감시(본문 비출력) | 생각 3건, 레코드 시각 대비 1.3~6.5초(중앙값 2.0초) 뒤 표시. 블록 단위로 한 줄씩 추가 기록 |
| Codex | — | 요약이 비어 있어 측정 불가. 요약 설정을 켠 시험 세션 필요 |

## 수집기 동작·부하 (143개 세션 동시 감시 기준)

- 변경 없는 폴링 1회당 읽기량 0.1KB. 세션 탐색(5초마다) 추가 읽기 없음. 시작 시 1회 약 60MB(작업 폴더 확인용 첫 줄들).
- 3분 감시: 읽은 줄 304, 중복 0, 파일 재작성 감지 0.
- 시작 시점의 파일 크기를 기준선으로 삼아, 오래 쉬던 세션이 재개돼도 과거 생각을 새것으로 내지 않는다.

## ia 실제 동작 확인 (2026-09-28, tmux)

- `ia agy --effort medium -p ...`: 오른쪽 창 자동 분할 → 세션 연결 → 생각 1건 표시 → CLI 종료 후 안내.
- `ia agy -p ...`(effort 미지정, 쉬운 질문): 연결은 됐지만 모델이 생각 없이 답해 표시할 것이 없었다.
- `ia claude -p ...`: `--session-id`로 정확히 연결. 저장된 thinking이 비어 있어 표시 없음(위 설정 문제).
- 사용자 WSL 셸에서 `ia claude`가 분할 없이 안내만 출력: WT_SESSION 없음 + WSL Windows 연동 꺼짐
  (`/proc/sys/fs/binfmt_misc/WSLInterop` 없음, `cmd.exe` Exec format error). → tmux 밖이면 ia 전용 tmux 화면을
  만드는 방식을 기본으로 추가. 가짜 CLI로 분할·연결·표시·종료 시 정리·터미널 닫힘 시 정리 확인.

## 다음 단계로 넘길 확인 항목

- 창 두 개·재시작 시 중복 번역 방지: SQLite 번역 캐시로 해결(tests/test_translate.py). 실제 번역기 연결은 3단계.
- agy 헤드리스 실행은 작업 폴더가 기록되지 않는다(`-` 표시).

## 번역 모델 비교 (2026-09-28, 직접 만든 예시 생각 3개)

| 모델 | 지연 | 비고 |
|---|---|---|
| gemini-3.8-flash, thinkingLevel=low | 1.3~1.8초 | 채택. 코드·경로·숫자 보존, 자연스러운 혼잣말. `minimal`은 이 모델에서 400 오류 |
| gemini-3.5-flash-lite | 0.9~1.3초 | 품질 비슷, 약간 더 빠름. `IA_MODEL`로 전환 가능 |

- agy CLI(`agy -p`)는 호출당 약 20초 + 호출마다 agy 세션이 새로 생겨 `ia agy` 세션 연결과 섞일 수 있어 제외.
- 실제 세션 생각 1건 번역: 비밀 저장소 키 조회 포함 2.3초, 캐시 재사용 시 0.7초(키 조회만).
