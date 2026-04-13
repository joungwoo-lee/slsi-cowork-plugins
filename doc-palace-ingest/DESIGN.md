# doc-palace-ingest: 설계 문서

## 개요

문서 폴더 인제스트 스킬.

중요:

- `wing`, `hall`, `room`은 인덱스 라벨일 뿐 실제 디렉터리가 아니다
- 이 스킬은 원본 폴더 안에 `wing/`, `hall/`, `room/` 같은 서브폴더를 만들면 안 된다
- 새로 만들 수 있는 것은 `AGENTS.md`, `_closets/`, `_closets/*.aaak.md`, `.doc-palace-state.json` 뿐이다
- `AGENTS.md`는 항상 대상 폴더 루트에만 있어야 하며 `_closets/` 안에 두면 안 된다
- AAAK는 외부 툴이 아니라 closet 파일 안에 직접 쓰는 텍스트 포맷이다

- AI가 스킬을 실행하면 대상 폴더의 문서들을 분석하여
- 폴더 안에 `AGENTS.md` 인덱스를 생성/업데이트하고
- `_closets/` 서브폴더에 AAAK 파일들을 생성한다
- 원본 파일은 절대 수정하지 않는다
- 이후 질문 시 AI는 `AGENTS.md` → `_closets/*.md` → 원본 파일 순으로 탐색한다

---

## 1. 아키텍처 맵

```
[대상 폴더]
├── AGENTS.md                  ← 문서 인덱스 (라벨 목록 + closet 포인터)
├── _closets/                  ← AAAK 파일 저장 폴더
│   ├── <room_name>.aaak.md   ← closet 파일 (AAAK + 원본 링크)
│   └── ...
├── (원본 문서들)               ← 원본 그대로, 절대 수정 안 함
│   ├── api-spec.md
│   ├── architecture.md
│   └── ...
└── .doc-palace-state.json     ← 📋  인제스트 상태 (mtime 트래킹, 증분 업데이트용)
```

### 정보 탐색 흐름

```
사용자 질문
    │
    ▼
[1] AGENTS.md 로드            ← 인덱스 라벨 스캔
    │ Closet 포인터 확인
    ▼
[2] _closets/<room>.aaak.md   ← AAAK 요약본으로 정확한 섹션 위치 파악
    │ 원본 파일 링크 추출
    ▼
[3] 원본 파일 직접 읽기        ← Drawer: 팩트 기반 답변 생성
```

---

## 2. AGENTS.md 구조 (인덱스)

AGENTS.md는 **폴더-레벨 지침**으로, 전역 CLAUDE.md가 아닌  
인제스트된 폴더 내부에만 존재한다.

`wing`, `hall`, `room` 섹션은 모두 텍스트 인덱스다. 실제 디렉터리를 만들라는 뜻이 아니다.

### 형식

```markdown
<!-- PALACE_INDEX|{folder_name}|{date}|{doc_count} -->

# 🏛️ {folder_name} 기억 궁전 인덱스

## PALACE META
GEN:{date}|DOCS:{count}|WINGS:{n}|ROOMS:{m}|TUNNELS:{k}

## QUERY PROTOCOL
1. 질문 → 아래 Wing/Hall/Room 스캔 → 해당 Closet 파일 열기
2. Closet에서 ZID 확인 → 원본 파일 링크 따라가기
3. 원본 파일 읽어 팩트 기반 답변

---

## WING: {wing_name}
> {wing_description_1line}

### HALL: decisions
- ROOM: {room_slug} | {closet_link} | {doc_count}docs | {keywords}

### HALL: technical
- ROOM: {room_slug} | {closet_link} | {doc_count}docs | {keywords}

### HALL: reference
- ROOM: {room_slug} | {closet_link} | {doc_count}docs | {keywords}

---

## TUNNELS
T:{room_a}<->{room_b}|{label}
T:{room_c}<->{room_d}|{label}

---

## LOG
{date}|INGEST|{count}docs|{duration}s
{date}|UPDATE|+{new}docs|-{removed}docs
```

### 실제 예시 (API 문서 폴더)

```markdown
<!-- PALACE_INDEX|slsi-api-docs|2026-04-13|24 -->

# 🏛️ slsi-api-docs 기억 궁전 인덱스

## PALACE META
GEN:2026-04-13|DOCS:24|WINGS:3|ROOMS:11|TUNNELS:4

## QUERY PROTOCOL
1. 질문 → Wing/Hall/Room 스캔 → Closet 열기
2. Closet ZID → 원본 링크
3. 원본 읽어 답변

---

## WING: auth
> 인증/인가 관련 문서

### HALL: technical
- ROOM: jwt-flow | [_closets/auth-jwt-flow.aaak.md] | 3docs | jwt,token,refresh,expire
- ROOM: oauth2 | [_closets/auth-oauth2.aaak.md] | 2docs | oauth,scope,grant_type

### HALL: decisions
- ROOM: auth-decision-log | [_closets/auth-decisions.aaak.md] | 1doc | jwt_vs_session,chosen

---

## WING: api
> REST API 엔드포인트 사양

### HALL: reference
- ROOM: endpoints | [_closets/api-endpoints.aaak.md] | 8docs | GET,POST,path,param
- ROOM: error-codes | [_closets/api-errors.aaak.md] | 2docs | 4xx,5xx,code,message

### HALL: technical
- ROOM: rate-limiting | [_closets/api-rate-limit.aaak.md] | 1doc | throttle,quota,429

---

## WING: infra
> 인프라/배포 관련

### HALL: technical
- ROOM: docker-setup | [_closets/infra-docker.aaak.md] | 3docs | compose,volume,network
- ROOM: ci-pipeline | [_closets/infra-ci.aaak.md] | 4docs | github_actions,deploy,test

---

## TUNNELS
T:jwt-flow<->oauth2|auth_mechanism
T:rate-limiting<->endpoints|api_constraints
T:docker-setup<->ci-pipeline|deployment_flow

---

## LOG
2026-04-13|INGEST|24docs|8.3s
```

---

## 3. Closet 파일 구조 (_closets/<room>.aaak.md)

Closet은 **AAAK 텍스트 + 원본 파일 포인터**.  
AAAK는 외부 툴이 아니라 AI가 closet markdown 안에 직접 쓰는 텍스트 형식이다.

```markdown
<!-- CLOSET|{room}|{wing}|{hall}|{date} -->

# CLOSET: {room}

## AAAK SPEC
ENT: DOC=document, API=api_endpoint, ERR=error_code

## ZETTELS

{file_num}|{primary_entity}|{date}|{title}
{zid}:{entities}|{keywords}|"{key_quote}"|{weight}|{emotions}|{flags}
T:{zid_a}<->{zid_b}|{relation}

## SOURCE LINKS
- [{original_filename}](../{original_filename}) — chunk {n}
```

### 실제 예시

```markdown
<!-- CLOSET|jwt-flow|auth|technical|2026-04-13 -->

# CLOSET: jwt-flow

## AAAK SPEC
ENT: JWT=jwt_token, REF=refresh_token, ACC=access_token, EXP=expiry

## ZETTELS

1|JWT|2026-04-13|JWT 인증 흐름 설계
Z1:JWT+ACC|access_token,15min,expire,header|"access token은 15분, Authorization 헤더에 포함"|5|trust|TECHNICAL+DECISION
Z2:JWT+REF|refresh_token,7day,httponly,cookie|"refresh token은 7일, HttpOnly 쿠키로만 전달"|5|trust|TECHNICAL+DECISION
Z3:JWT|blacklist,redis,logout|"로그아웃 시 redis blacklist에 jti 등록"|4|trust|TECHNICAL
T:Z1<->Z2|token_pair
T:Z3<->Z2|invalidation_flow

2|ERR|2026-04-13|JWT 에러 코드
Z4:ERR|401,expired,token_invalid|"토큰 만료 시 401 EXPIRED_TOKEN 반환"|4|trust|TECHNICAL
Z5:ERR|403,insufficient_scope|"권한 부족 시 403 INSUFFICIENT_SCOPE"|3|trust|TECHNICAL

## SOURCE LINKS
- [auth-jwt-design.md](../auth-jwt-design.md) — chunks 1-4
- [auth-error-spec.md](../auth-error-spec.md) — chunks 1-2
```

---

## 4. 재사용할 코드 (레포별 파일 + 함수)

### 4.1 MemPalace — `mempalace/miner.py`

| 재사용 대상 | 위치 | 용도 |
|---|---|---|
| `READABLE_EXTENSIONS` | L20-50 | 인제스트 가능 파일 확장자 필터 |
| `CHUNK_SIZE = 800` | L52 | 청크 크기 (800자) |
| `CHUNK_OVERLAP = 100` | L53 | 청크 오버랩 |
| `MIN_CHUNK_SIZE = 50` | L54 | 최소 청크 크기 |
| `GitignoreMatcher` | L63 (class) | .gitignore 패턴 파일 제외 |
| `GitignoreMatcher.from_dir()` | L71 | 디렉토리에서 .gitignore 로드 |
| `is_gitignored()` | L186 | 파일이 gitignore 대상인지 체크 |
| `should_skip_dir()` | L196 | `node_modules`, `__pycache__` 등 스킵 |
| `chunk_text()` | L323 | 텍스트 → 오버랩 청크 리스트 변환 |
| `detect_room()` | L276 | 파일 경로+내용 기반 룸 자동 분류 |
| `scan_project()` | L469 | 폴더 재귀 스캔, 파일 목록 반환 |

**ChromaDB 관련 (`add_drawer`, `process_file`)은 재사용하지 않는다.**  
저장소는 마크다운 파일이며 ChromaDB가 아니다.

### 4.2 MemPalace — `mempalace/dialect.py`

| 재사용 대상 | 위치 | 용도 |
|---|---|---|
| `Dialect` (class) | L298 | AAAK 인코더 |
| `Dialect.compress(text, metadata)` | L559 | 텍스트 → AAAK Zettel 문자열 |
| `Dialect.encode_entity(name)` | L387 | 엔티티명 → 3자 코드 |
| `Dialect.encode_emotions(emotions)` | L401 | 감정 리스트 → 코드 문자열 |
| `Dialect.encode_zettel(zettel_dict)` | L701 | Zettel dict → AAAK 줄 |
| `Dialect.encode_tunnel(tunnel_dict)` | L732 | Tunnel → `T:ZID<->ZID|label` |
| `Dialect.from_config(config_path)` | L349 | entities.json에서 엔티티 매핑 로드 |
| `EMOTION_CODES` (dict) | 상단 | 감정 코드 사전 |

**단, `Dialect.compress()`는 regex 기반 휴리스틱이므로**  
일반 기술 문서에서는 단독 사용 불가. LLM 요약 후 AAAK 인코딩으로 2단계 처리 필요.

### 4.3 MemPalace — `mempalace/general_extractor.py`

| 재사용 대상 | 위치 | 용도 |
|---|---|---|
| `extract_memories(text, min_confidence)` | L363 | 청크에서 결정/선호/마일스톤/문제 패턴 추출 (LLM 불필요) |
| `DECISION_MARKERS` | 상단 | 결정 패턴 정규식 리스트 |
| `PREFERENCE_MARKERS` | 상단 | 선호 패턴 정규식 리스트 |
| `MILESTONE_MARKERS` | 상단 | 마일스톤 패턴 정규식 리스트 |
| `PROBLEM_MARKERS` | 상단 | 문제/버그 패턴 정규식 리스트 |

`extract_memories()`가 반환하는 `memory_type` → Hall 분류에 사용:  
`decision` → `HALL: decisions`, `technical` → `HALL: technical`, 등

### 4.4 MemPalace — `mempalace/palace_graph.py`

| 재사용 대상 | 위치 | 용도 |
|---|---|---|
| `build_graph(col)` 의 **로직** | L전체 | 같은 룸명이 여러 Wing에 등장하면 Tunnel 생성 |

ChromaDB col 의존성 제거 후 메모리 내 dict로 동일 로직 재구현.  
`room_data[room]["wings"]`에 여러 wing이 있으면 → Tunnel 엣지 추가.

### 4.5 MemPalace — `mempalace/palace.py`

| 재사용 대상 | 위치 | 용도 |
|---|---|---|
| `file_already_mined()` 의 **mtime 체크 패턴** | L전체 | 증분 업데이트: 파일이 변경됐는지 확인 |
| `SKIP_DIRS` (set) | 상단 | 건너뛸 디렉토리 목록 |

상태는 `.doc-palace-state.json`에 `{filepath: mtime}` 형태로 저장.

### 4.6 MemPalace — `mempalace/config.py`

| 재사용 대상 | 위치 | 용도 |
|---|---|---|
| `sanitize_name(value, field_name)` | L전체 | wing/room 이름 검증 (경로 탐색 방지) |
| `sanitize_content(value, max_length)` | L전체 | 컨텐츠 길이/null byte 검증 |

---

## 5. 인제스트 파이프라인

### 5.1 전체 흐름

```
ingest.py <folder_path>
    │
    ├─ [1] SCAN
    │   └─ miner.scan_project() + GitignoreMatcher + SKIP_DIRS
    │       → 파일 목록 + mtime 체크 (state.json 비교)
    │
    ├─ [2] CHUNK
    │   └─ miner.chunk_text() per file
    │       → 청크 리스트 [{content, chunk_index, source_file}]
    │
    ├─ [3] EXTRACT  (LLM 불필요 1단계)
    │   └─ general_extractor.extract_memories() per chunk
    │       → memory_type (decision/preference/milestone/problem/technical)
    │       → Hall 분류
    │
    ├─ [4] ROOM DETECT
    │   └─ miner.detect_room() 또는 경로 기반 룸 추론
    │       → room_slug (e.g. "jwt-flow", "docker-setup")
    │
    ├─ [5] LLM SUMMARIZE  (LLM 필요, 청크 배치 처리)
    │   └─ 청크 그룹(room 단위) → LLM → structured summary text
    │       입력: "다음 문서 청크들을 DECISIONS/PREFERENCES/TECHNICAL 항목으로 요약해라.
    │              key_quote를 포함하고 중요도(1-5)를 매겨라."
    │       출력: [{entity, keywords, key_quote, weight, flags}] 리스트
    │
    ├─ [6] AAAK ENCODE
    │   └─ Dialect.compress() or Dialect.encode_zettel() per summary item
    │       → AAAK Zettel 줄들
    │
    ├─ [7] TUNNEL DETECT
    │   └─ palace_graph 로직 (메모리 내): 같은 room_slug가 여러 wing에 등장 시 Tunnel
    │
    ├─ [8] WRITE CLOSETS
    │   └─ _closets/<room>.aaak.md 생성/업데이트
    │
    └─ [9] WRITE/UPDATE AGENTS.md
        └─ Wing/Hall/Room 인덱스 + Tunnel 섹션 + LOG 엔트리
```

### 5.2 LLM 요약 프롬프트 (5단계)

```
You are indexing technical documents for a memory palace.
Given the following text chunks from room "{room}" (wing "{wing}"):

{chunks}

Extract structured summaries as JSON array:
[
  {
    "entities": ["name1", "name2"],   // 주요 엔티티 (최대 3개)
    "keywords": ["kw1", "kw2", ...],  // 주제 키워드 (최대 5개)
    "key_quote": "...",               // 핵심 문장 1개 (원문 그대로)
    "weight": 3,                      // 중요도 1-5
    "flags": ["TECHNICAL", "DECISION"] // TECHNICAL/DECISION/CORE/ORIGIN
  }
]

Rules:
- key_quote는 반드시 원문에서 그대로 발췌할 것
- 요약하거나 paraphrase하지 말 것
- flags는 해당하는 것만 포함
```

---

## 6. 업데이트 로직 (증분 처리)

v1은 **변경된 파일만 재처리 + AGENTS.md 전체 재생성** 방식.

```python
# .doc-palace-state.json 구조
{
  "generated_at": "2026-04-13T10:00:00",
  "files": {
    "api-spec.md": {"mtime": 1712995200.0, "room": "endpoints", "wing": "api"},
    "auth-jwt-design.md": {"mtime": 1712908800.0, "room": "jwt-flow", "wing": "auth"}
  }
}
```

처리 단계:
1. 현재 파일 mtime vs state.json 비교
2. 변경/신규 파일만 Step 2-6 재실행 → Closet 업데이트
3. 삭제된 파일의 Closet 항목 제거
4. AGENTS.md 전체 재생성 (state.json의 모든 room 정보 기반)
5. state.json 업데이트

---

## 7. 스킬 파일 구조

```
doc-palace-ingest/
├── SKILL.md          ← 스킬 메타데이터 + AI 실행 지침
├── ingest.py         ← 메인 인제스트 스크립트
├── closet_builder.py ← LLM 요약 → AAAK 인코딩 → Closet 파일 생성
├── agents_writer.py  ← AGENTS.md 생성/업데이트
├── room_classifier.py← detect_room 래퍼 + 커스텀 룸 분류 로직
└── requirements.txt  ← anthropic (LLM), 그 외 stdlib only
```

---

## 8. SKILL.md 구조

```markdown
---
name: doc-palace-ingest
description: "문서 폴더를 기억 궁전으로 인제스트. Wing/Room 인덱스(AGENTS.md)와
             AAAK 압축 Closet 파일들을 생성한다."
user-invocable: true
---

## 인제스트 (문서 → 기억 궁전)

사용자가 폴더를 지정하면:

1. 다음 명령 실행:
   python3 doc-palace-ingest/ingest.py <folder_path>

2. 완료 후 생성/업데이트된 파일 보고:
   - AGENTS.md: 인덱스
   - _closets/*.aaak.md: 룸별 요약

## 쿼리 프로토콜 (질문 → 탐색)

AGENTS.md가 있는 폴더에 대해 질문을 받으면:

1. AGENTS.md 먼저 읽기 (Wing/Hall/Room 스캔)
2. 관련 Room의 Closet 파일 열기 (_closets/<room>.aaak.md)
3. Closet의 SOURCE LINKS에서 원본 파일 확인
4. 원본 파일 읽어 팩트 기반 답변
5. Tunnel이 있으면 연결된 다른 Room도 확인

절대 AGENTS.md나 Closet만 보고 답변하지 말 것.
반드시 원본 Drawer까지 추적할 것.
```

---

## 9. 의존성

```
# requirements.txt
anthropic>=0.40.0        # LLM 요약 (Step 5)
# stdlib only 외 추가 없음 — chromadb 불필요
```

MemPalace 코드는 **직접 복사해서 재사용** (pip install mempalace 불필요).  
필요한 파일만 발췌:
- `mempalace/miner.py` → `_vendor/miner.py`
- `mempalace/dialect.py` → `_vendor/dialect.py`
- `mempalace/general_extractor.py` → `_vendor/general_extractor.py`
- `mempalace/config.py` → `_vendor/config.py`

또는 `pip install mempalace`로 설치 후 import.

---

## 10. 설계 원칙 (MemPalace + Karpathy 결합)

| 원칙 | 출처 | 구현 |
|---|---|---|
| 원본 불변 (Verbatim always) | MemPalace | 원본 파일 절대 수정 안 함. Drawer = 원본 |
| 증분 전용 (Incremental only) | MemPalace | mtime 트래킹, 변경 파일만 재처리 |
| 인덱스 우선 탐색 | Karpathy | AGENTS.md 먼저 읽고 Closet → 원본 순서 |
| LLM이 위키 유지 | Karpathy | AI가 스킬 실행 → 인덱스/요약 자동 생성 |
| 마크다운 전체 | Karpathy | AGENTS.md, Closet 모두 마크다운, git 관리 가능 |
| AAAK 인덱스 레이어 | MemPalace | Closet = AAAK 요약, Drawer = 원본 |
| 터널 크로스 레퍼런스 | MemPalace | 같은 주제 다른 Wing → Tunnel 자동 생성 |
| 로컬 우선 | MemPalace | 외부 API는 LLM 요약만. 저장/검색은 로컬 파일 |

---

## 11. 미구현 범위 (v1 제외)

- ChromaDB 백엔드 (마크다운 파일만으로 충분한 규모 대상)
- BM25/벡터 검색 (AGENTS.md 인덱스 탐색으로 대체)
- 자동 entity disambiguation (수동 entities.json으로 대체)
- 다국어 AAAK 코드 (영어 기준)
- Lint 패스 (AGENTS.md 모순/고아 페이지 검사)

---

## 12. 참조 링크

- [MemPalace 레포](https://github.com/MemPalace/mempalace) — `develop` 브랜치
- [Karpathy LLM Wiki Gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- 재사용 파일 직접 링크:
  - [miner.py](https://github.com/MemPalace/mempalace/blob/develop/mempalace/miner.py)
  - [dialect.py](https://github.com/MemPalace/mempalace/blob/develop/mempalace/dialect.py)
  - [general_extractor.py](https://github.com/MemPalace/mempalace/blob/develop/mempalace/general_extractor.py)
  - [palace_graph.py](https://github.com/MemPalace/mempalace/blob/develop/mempalace/palace_graph.py)
  - [palace.py](https://github.com/MemPalace/mempalace/blob/develop/mempalace/palace.py)
  - [config.py](https://github.com/MemPalace/mempalace/blob/develop/mempalace/config.py)
