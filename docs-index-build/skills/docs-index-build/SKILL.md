---
name: docs-index-build
description: "문서 폴더를 인제스트해 AGENTS.md 인덱스와 _closets/*.aaak.md 파일을 생성/업데이트한다. AAAK는 외부 툴이 아니라 이 스킬이 직접 작성하는 텍스트 포맷이다."
user-invocable: true
---

# docs-index-build

문서 폴더를 인제스트해 문서 인덱스와 AAAK closet 파일을 만드는 스킬.

- **Karpathy LLM Wiki 패턴** 적용: AI가 마크다운 인덱스를 직접 유지
- 인덱스(`AGENTS.md`)와 AAAK 압축 요약(`_closets/`)을 폴더 안에 생성
- 원본 파일은 절대 수정하지 않음

## 절대 금지

- `wing`, `hall`, `room` 이름의 새 디렉터리를 만들지 말 것
- 원본 폴더 구조를 재배치하거나 복사하지 말 것
- 새로 만들 수 있는 것은 `AGENTS.md`와 `_closets/` 및 그 안의 `.aaak.md` 파일뿐이다
- `AGENTS.md`를 `_closets/` 안이나 다른 하위 폴더 안에 만들지 말 것
- `AGENTS.md`의 정확한 위치는 대상 폴더 루트의 `<folder>/AGENTS.md` 하나뿐이다
- AAAK를 외부 명령, 외부 서비스, 외부 MCP 도구처럼 취급하지 말 것
- AAAK는 이 스킬이 문서 내용을 직접 써 넣는 텍스트 포맷이다

## 필수 전제

Closet 파일이나 AAAK zettel을 작성하기 전에 반드시 같은 디렉토리의 `AAAK_WRITING_GUIDE.md`를 읽고 그 규칙을 그대로 따른다.

- AAAK를 이미 안다고 가정하지 말 것
- AAAK를 외부 툴처럼 찾거나 호출하지 말 것
- `key_quote`는 반드시 원문 그대로 복사할 것
- 가이드에 없는 형식을 임의로 만들지 말 것
- 애매하면 더 짧고 보수적인 AAAK를 쓸 것

---

## 인제스트 실행 절차

사용자가 폴더 인제스트를 요청하면 아래 단계를 순서대로 수행한다.

### Step 1. 스캔 실행

```bash
python3 <skill_dir>/scripts/ingest.py <folder_path>
```

`<skill_dir>`은 이 SKILL.md가 있는 디렉토리다.
출력된 JSON을 읽는다. `status`가 `"up_to_date"`이면 Step 6으로 건너뛴다.

### Step 2. 작업 데이터 파악

JSON의 `new_and_changed` 배열을 읽는다. 각 항목 구조:

```json
{
  "path": "auth/jwt-design.md",
  "wing": "auth",
  "room": "auth-jwt-design",
  "dominant_hall": "technical",
  "chunk_count": 5,
  "chunks": [
    {"index": 0, "hall": "technical", "text": "..."},
    {"index": 1, "hall": "decisions", "text": "..."}
  ],
  "content_preview": "..."
}
```

### Step 3. Closet 파일 생성 (_closets/<room>.aaak.md)

`new_and_changed`의 각 파일에 대해 `_closets/<room>.aaak.md`를 생성한다.
같은 `room`에 여러 파일이 있으면 하나의 Closet 파일에 합산한다.

Closet 파일을 쓰기 전에 반드시 `AAAK_WRITING_GUIDE.md`를 읽고 아래 형식과 필드 규칙을 검증한다.

중요: Closet 안의 AAAK는 얇은 문서 요약이 아니라 문서 내용을 AAAK로 가능한 충실하게 다시 적은 것이어야 한다. `chunks` 배열은 읽기 보조 데이터일 뿐이며, 최종 AAAK는 각 문서를 처음부터 끝까지 읽은 뒤 문서의 의미 있는 내용을 빠짐없이 zettel들로 풀어 써야 한다.

**Closet 파일 형식:**

```markdown
<!-- CLOSET|{room}|{wing}|{dominant_hall}|{date} -->

# CLOSET: {room}

## AAAK SPEC
ENT: {자주 등장하는 엔티티 → 3자 코드, 예: API=api_endpoint, JWT=jwt_token}

## ZETTELS

{file_num}|{primary_entity}|{date}|{title}
{ZID}:{ENTITIES}|{topic_keywords}|"{key_quote}"|{weight}|{flags}
T:{ZID_a}<->{ZID_b}|{relation_label}
```

**AAAK Zettel 작성 규칙:**
- `file_num`: 이 Closet 안에서 파일 순번 (1부터)
- `ZID`: Z1, Z2, Z3... (문서의 의미 있는 포인트 순번)
- `ENTITIES`: 해당 포인트에 중요한 엔티티 코드 (ENT SPEC에 정의한 것), 없으면 생략
- `topic_keywords`: 쉼표 구분, 최대 5개, 소문자
- `"key_quote"`: 문서 어디에서든 원문 그대로 발췌한 핵심 문장 1개 (반드시 원문 그대로)
- `weight`: 중요도 1-5 (해당 포인트의 중요도 기준)
- `flags`: `TECHNICAL`, `DECISION`, `CORE`, `ORIGIN` 중 해당하는 것만
- `T:` 줄: 문서 내 포인트끼리 명확히 연결될 때 사용 (선택)

위 요약 규칙보다 더 구체적인 판단 기준은 모두 `AAAK_WRITING_GUIDE.md`를 우선한다.

문서당 zettel 수를 인위적으로 적게 제한하지 말 것. 긴 기술 문서라면 필요한 만큼 많이 작성한다. 내용이 많은데 AAAK가 짧다면 잘못 작성한 것이다.

**Closet 파일 끝에 SOURCE LINKS 추가:**

```markdown
## SOURCE LINKS
- [{filename}](../{relative_path}) — {chunk_count} chunks
```

**예시:**

```markdown
<!-- CLOSET|auth-jwt-design|auth|technical|2026-04-13 -->

# CLOSET: auth-jwt-design

## AAAK SPEC
ENT: JWT=jwt_token, ACC=access_token, REF=refresh_token, EXP=expiry

## ZETTELS

1|JWT|2026-04-13|JWT 인증 흐름 설계
Z1:JWT+ACC|access_token,15min,header,bearer|"access token은 15분 유효, Authorization 헤더로 전달"|5|TECHNICAL+DECISION
Z2:JWT+REF|refresh_token,7day,httponly,cookie|"refresh token은 7일, HttpOnly 쿠키 전용"|5|TECHNICAL+DECISION
Z3:JWT|blacklist,redis,jti,logout|"로그아웃 시 Redis에 jti 블랙리스트 등록"|4|TECHNICAL
Z4:JWT|rotation,replay,refresh_flow,revocation|"refresh token은 매 재발급 시 rotation한다"|4|TECHNICAL+DECISION
T:Z1<->Z2|token_pair_lifecycle
T:Z2<->Z4|refresh_rotation_flow

2|ERR|2026-04-13|JWT 에러 응답 정의
Z4:ERR|401,expired,token_invalid|"토큰 만료 시 401 EXPIRED_TOKEN 반환"|4|TECHNICAL
Z5:ERR|403,scope,insufficient|"권한 부족 시 403 INSUFFICIENT_SCOPE"|3|TECHNICAL

## SOURCE LINKS
- [jwt-design.md](../auth/jwt-design.md) — 5 chunks
```

### Step 4. AGENTS.md 생성/업데이트

폴더 루트에 `AGENTS.md`를 생성(이미 있으면 전체 재생성)한다.

정확한 경로 규칙:

- 올바름: `<target_folder>/AGENTS.md`
- 올바름: `<target_folder>/_closets/<room>.aaak.md`
- 금지: `<target_folder>/_closets/AGENTS.md`
- 금지: `<target_folder>/wing/...`, `<target_folder>/hall/...`, `<target_folder>/room/...`

여기서 `wing`, `hall`, `room`은 인덱스 라벨일 뿐이다. 실제 디렉터리나 서브폴더를 만들지 말고, 모두 `AGENTS.md` 텍스트 안에만 기록한다.

**AGENTS.md 형식:**

```markdown
<!-- PALACE_INDEX|{folder_name}|{date}|{total_doc_count} -->

# 🏛️ {folder_name} 기억 궁전 인덱스

## PALACE META
GEN:{date}|DOCS:{count}|WINGS:{n}|ROOMS:{m}|TUNNELS:{k}

## QUERY PROTOCOL
1. 사용자의 질문을 받으면 먼저 `entity`, `action`, `constraint`, `error`, `time/version` 단서를 추출한다.
2. 질문과 가장 가까운 Wing/Hall/Room 후보를 고르고, 맞지 않는 Room은 초기에 배제한다.
3. 선택한 Room의 closet을 연 뒤, 전체를 무작정 읽지 말고 관련 zettel과 `SOURCE LINKS`를 먼저 찾는다.
4. `SOURCE LINKS`를 따라 원본 파일을 열어 사실을 검증한다.
5. closet만으로 답을 확정하지 말고, 최종 답변은 원문에서 확인한 사실만 사용한다.
6. `TUNNELS` 섹션에 연결 Room이 있으면 함께 확인한다.
7. 후보가 여러 개이거나 근거가 엇갈리면 불확실성을 드러내고 어떤 Room/원문을 기준으로 답했는지 분명히 한다.

---

## WING: {wing_name}
> {wing 한 줄 설명: 이 Wing이 다루는 주제}

### HALL: technical
- ROOM:{room_slug} | [_closets/{room}.aaak.md] | {n}docs | {top_keywords}

### HALL: decisions
- ROOM:{room_slug} | [_closets/{room}.aaak.md] | {n}docs | {top_keywords}

### HALL: reference
- ROOM:{room_slug} | [_closets/{room}.aaak.md] | {n}docs | {top_keywords}

---

## TUNNELS
T:{room_a}<->{room_b}|{공통_주제}

---

## LOG
{date}|INGEST|+{new}files|{total}total
```

Hall은 `dominant_hall` 기준으로 배치. 같은 Hall이 없는 Wing은 해당 섹션 생략.
`top_keywords`는 해당 Room의 Closet에서 자주 등장하는 키워드 5개.
Tunnels는 JSON의 `tunnels` 배열 사용.

작성 규칙 추가:

- `QUERY PROTOCOL`은 인덱스 설명이 아니라 실제 행동 지침처럼 쓸 것
- `QUERY PROTOCOL`에는 반드시 `질문 단서 추출 -> Room 후보 선택 -> closet 확인 -> 원문 검증 -> tunnel 확장 탐색 -> 근거 기반 응답` 순서가 드러나야 한다
- `QUERY PROTOCOL`에는 반드시 `closet만으로 답을 확정하지 말 것` 문구가 들어가야 한다
- Wing/Hall/Room 항목은 `무엇을 먼저 읽을지 결정하는 라우팅 포인터`로 쓸 것

**이미 AGENTS.md가 있을 때**: LOG 섹션의 기존 항목은 유지하고 새 항목을 추가.
Wing/Room 구조는 전체 재생성 (기존 state + 신규 파일 합산).

### Step 4A. AAAK 검증

Closet 파일 저장 전 아래를 반드시 확인한다.

1. 각 문서를 끝까지 읽은 뒤 AAAK를 작성했는가
2. 모든 zettel이 `{ZID}:{ENTITIES}|{topic_keywords}|"{key_quote}"|{weight}|{flags}` 형식을 지키는가
3. 모든 `key_quote`가 원문 문서 안에 문자열 그대로 존재하는가
4. zettel 집합이 문서의 의미 있는 내용을 거의 다 담고 있는가, 일부 대표 포인트만 남긴 것은 아닌가
5. 결정, 제약, 절차, 예외, 실패 케이스가 있으면 빠지지 않았는가
6. `topic_keywords`가 소문자이며 5개 이하인가
7. `flags`가 허용 목록 안에만 있는가
8. 긴 문서인데도 AAAK가 지나치게 짧지 않은가

### Step 5. 완료 처리

```bash
python3 <skill_dir>/scripts/ingest.py <folder_path> --finalize
```

state.json 업데이트 및 _palace_work.json 정리.

### Step 6. 완료 보고

사용자에게 결과 요약:
- 처리된 파일 수 (신규/변경/삭제)
- 생성/업데이트된 Closet 파일 목록
- AGENTS.md 생성/업데이트 여부
- 인덱스 라벨 구조 간략 요약
- 실제 생성 경로 확인: `AGENTS.md`는 루트, closet은 `_closets/` 아래만

---

## 쿼리 프로토콜 (인제스트 없이 질문 받을 때)

이 스킬이 인제스트한 폴더에 대해 질문을 받으면:

1. **AGENTS.md 먼저 읽기** — 질문의 단서와 맞는 Wing/Hall/Room 후보를 좁힌다.
2. **관련 Room의 Closet 파일 열기** — `_closets/<room>.aaak.md`에서 관련 zettel과 source 포인터를 찾는다.
3. **SOURCE LINKS 따라가기** — 원본 파일을 직접 읽어 확인한다.
4. **팩트 기반 답변** — closet 요약이 아닌 원본 내용 기반으로 답한다.
5. **TUNNELS 확인** — 연결 Room도 있으면 함께 참조한다.
6. **불확실성 처리** — 후보 Room이 여러 개면 어떤 원문을 근거로 썼는지 밝힌다.

> Closet만 읽고 답변하지 말 것. `AGENTS.md`는 라우팅용이고, closet은 압축 기억이며, 원문이 최종 증거다.

---

## 상태 확인

```bash
python3 <skill_dir>/scripts/ingest.py <folder_path> --status
```

---

## 참조

- [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — LLM 유지 마크다운 위키 패턴
- `AAAK_WRITING_GUIDE.md` — 이 스킬 전용 AAAK 작성 스펙 및 변환 절차
