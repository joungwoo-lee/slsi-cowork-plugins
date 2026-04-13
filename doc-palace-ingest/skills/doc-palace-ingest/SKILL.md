---
name: doc-palace-ingest
description: "문서 폴더를 기억 궁전으로 인제스트. Wing/Hall/Room 구조의 AGENTS.md 인덱스와 AAAK 압축 Closet 파일들을 생성/업데이트한다."
user-invocable: true
---

# doc-palace-ingest

문서 폴더를 **기억 궁전(Memory Palace)** 구조로 인제스트하는 스킬.

- **MemPalace** Wing/Hall/Room/Closet/Drawer 구조 적용
- **Karpathy LLM Wiki 패턴** 적용: AI가 마크다운 인덱스를 직접 유지
- 인덱스(`AGENTS.md`)와 AAAK 압축 요약(`_closets/`)을 폴더 안에 생성
- 원본 파일은 절대 수정하지 않음

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
- `ZID`: Z1, Z2, Z3... (파일 내 청크 순번)
- `ENTITIES`: 청크의 주요 엔티티 코드 (ENT SPEC에 정의한 것), 없으면 생략
- `topic_keywords`: 쉼표 구분, 최대 5개, 소문자
- `"key_quote"`: 원문에서 그대로 발췌한 핵심 문장 1개 (반드시 원문 그대로)
- `weight`: 중요도 1-5 (핵심 결정/아키텍처=5, 일반 참고=2)
- `flags`: `TECHNICAL`, `DECISION`, `CORE`, `ORIGIN` 중 해당하는 것만
- `T:` 줄: 같은 주제로 연결되는 ZID 쌍 (선택)

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
T:Z1<->Z2|token_pair_lifecycle

2|ERR|2026-04-13|JWT 에러 응답 정의
Z4:ERR|401,expired,token_invalid|"토큰 만료 시 401 EXPIRED_TOKEN 반환"|4|TECHNICAL
Z5:ERR|403,scope,insufficient|"권한 부족 시 403 INSUFFICIENT_SCOPE"|3|TECHNICAL

## SOURCE LINKS
- [jwt-design.md](../auth/jwt-design.md) — 5 chunks
```

### Step 4. AGENTS.md 생성/업데이트

폴더 루트에 `AGENTS.md`를 생성(이미 있으면 전체 재생성)한다.

**AGENTS.md 형식:**

```markdown
<!-- PALACE_INDEX|{folder_name}|{date}|{total_doc_count} -->

# 🏛️ {folder_name} 기억 궁전 인덱스

## PALACE META
GEN:{date}|DOCS:{count}|WINGS:{n}|ROOMS:{m}|TUNNELS:{k}

## QUERY PROTOCOL
1. 질문 → 아래 Wing/Hall/Room 스캔 → 해당 Closet 열기
2. Closet ZID → SOURCE LINKS → 원본 파일 열기
3. 원본 파일 읽어 팩트 기반 답변 생성
4. TUNNELS 섹션 확인 — 연결된 다른 Room도 참조할 것

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

**이미 AGENTS.md가 있을 때**: LOG 섹션의 기존 항목은 유지하고 새 항목을 추가.
Wing/Room 구조는 전체 재생성 (기존 state + 신규 파일 합산).

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
- Wing/Room 구조 간략 요약

---

## 쿼리 프로토콜 (인제스트 없이 질문 받을 때)

이 스킬이 인제스트한 폴더에 대해 질문을 받으면:

1. **AGENTS.md 먼저 읽기** — Wing/Hall/Room 인덱스 스캔
2. **관련 Room의 Closet 파일 열기** — `_closets/<room>.aaak.md`
3. **SOURCE LINKS 따라가기** — 원본 파일 직접 읽기
4. **팩트 기반 답변** — Closet 요약이 아닌 원본 내용 기반
5. **TUNNELS 확인** — 연결 Room도 있으면 함께 참조

> Closet만 읽고 답변하지 말 것. 원본까지 반드시 추적.

---

## 상태 확인

```bash
python3 <skill_dir>/scripts/ingest.py <folder_path> --status
```

---

## 참조

- [MemPalace](https://github.com/MemPalace/mempalace) — Wing/Room/Drawer 구조, AAAK 다이얼렉트
- [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — LLM 유지 마크다운 위키 패턴
