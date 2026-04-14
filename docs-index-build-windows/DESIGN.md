# docs-index-build: 설계 문서

## 개요

문서 폴더 인제스트 스킬. 이후 이 폴더에서 질의하면 AGENTS.md 파일이 작업폴더 지침으로 동작하여 index를 주입한다. 전체 문서를 컨텍스트에 넣는 것이 낭비 또는 불가능하므로 인덱스를 통해 필요로 하지 않는 정보를 배제하고, AAAK 요약을 통해 삽입하는 문서의 양을 줄이고, 최종적으로 정확한 내용이 필요할 시 원본을 참조하도록 하는 것을 목표로 한다.

- `AGENTS.md`, `_closets/`, `_closets/*.aaak.md`, `.doc-palace-state.json` 을 새로 만든다.
- `AGENTS.md`는 대상 폴더 루트에 둔다. 문서들에 대한 인덱스를 갖으며 해당 폴더에서 질의시 자동 포함된다.
- AAAK는 자연어를 압축된 형태로 표현하는 포맷으로서 외부 툴이 아니라 closet 파일 안에 직접 쓰는 텍스트 포맷이다. 완전한 규격의 AAAK는 아직 존재하지 않으며 개발중인 압축 언어의 컨셉을 차용하여 임의적인 규칙이 섞여있는 상태다.

- AI가 스킬을 실행하면 대상 폴더의 문서들을 분석하여
- 폴더 안에 `AGENTS.md`로 index를 생성/업데이트하고
- `_closets/` 서브폴더에 AAAK 파일들을 생성한다
- 인덱스는 요약을 통해 원본파일까지 링크로 연결된다.
- 이후 질문 시 AI는 `AGENTS.md` → `_closets/*.md` → 원본 파일 순으로 탐색한다.
- index와 wing, hall, room의 구분은 임의적이며 자료에 따라 변형 보강이 필요하다.

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
1. 사용자의 질문을 받으면 먼저 `entity`, `action`, `constraint`, `error`, `time/version` 단서를 추출한다.
2. 질문과 가장 가까운 Wing/Hall/Room 후보를 고르고, 맞지 않는 Room은 초기에 배제한다.
3. 선택한 Room의 closet을 연 뒤, 전체를 다 읽기보다 관련 zettel과 `SOURCE LINKS`를 먼저 찾는다.
4. 원본 파일을 열어 사실을 검증한다.
5. closet만으로 답을 확정하지 않고, 최종 답변은 원문에서 확인한 사실만 사용한다.
6. `TUNNELS`가 있으면 연결 Room도 추가로 확인한다.
7. 근거가 갈리거나 후보가 여럿이면 어떤 Room/원문을 기준으로 답했는지 밝힌다.

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
1. 질문 단서 추출
2. Wing/Hall/Room 후보 선택
3. closet의 관련 zettel 확인
4. SOURCE LINKS 기반 원문 확인
5. 필요 시 TUNNELS 확장 탐색
6. 원문 근거 기반 답변

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

중요:

- `AGENTS.md`는 단순 목차가 아니라 OpenCode가 질문을 받았을 때 따를 질의 처리 지침이어야 한다.
- closet은 원문 대체물이 아니라 중간 압축 기억이다.
- 최종 답변의 근거는 항상 원문이어야 한다.

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

## 4. 실제 재사용/참고 코드

이 절은 현재 `docs-index-build` 구현 기준으로 사실인 내용만 적는다.

### 4.1 MemPalace — `mempalace/miner.py`

현재 스크립트에서 직접 가져왔거나 거의 그대로 옮긴 것은 아래다.

| 항목 | 현재 상태 | 용도 |
|---|---|---|
| `READABLE_EXTENSIONS` | 직접 참고/부분 복사 | 인제스트 가능 파일 확장자 필터 |
| `CHUNK_SIZE`, `CHUNK_OVERLAP`, `MIN_CHUNK_SIZE` | 직접 참고 | 청킹 파라미터 |
| `GitignoreMatcher` | 직접 참고/부분 복사 | `.gitignore` 해석 |
| `is_gitignored()` | 직접 참고/부분 복사 | ignore 대상 판별 |
| `chunk_text()`의 경계 분할 아이디어 | 직접 참고/부분 복사 | 문단 경계 우선 청킹 |

아래 항목은 현재 구현에서 직접 재사용하지 않는다.

| 항목 | 현재 상태 | 비고 |
|---|---|---|
| `detect_room()` | 미사용 | 현재 스킬은 경로 기반 자체 `detect_room()` 구현 사용 |
| `scan_project()` | 미사용 | 현재 스킬은 자체 `scan_folder()` 구현 사용 |
| `should_skip_dir()` | 미사용 | 동일한 취지의 로직을 스크립트 내부에서 직접 구현 |

### 4.2 MemPalace — `mempalace/dialect.py`

`dialect.py`는 현재 코드에서 직접 import 해서 재사용하지 않는다.

실제로 참고하는 것은 코드 자체보다 포맷 규약이다.

| 항목 | 현재 상태 | 용도 |
|---|---|---|
| AAAK header/zettel/tunnel 형식 | 개념 참고 | closet 파일 텍스트 형식 설계 |
| entity/flag 개념 | 개념 참고 | AAAK 작성 규칙 정의 |

주의:

- 현재 `docs-index-build`는 `Dialect.compress()`를 호출하지 않는다.
- AAAK는 `AAAK_WRITING_GUIDE.md`와 `SKILL.md` 규칙에 따라 AI가 직접 텍스트로 작성한다.

### 4.3 MemPalace — `mempalace/general_extractor.py`

현재 스크립트는 `extract_memories()`를 직접 재사용하지 않는다.

대신, 정규식 기반 분류 아이디어를 단순화해서 자체 `classify_chunk()`에 반영했다.

| 항목 | 현재 상태 | 용도 |
|---|---|---|
| 결정/문제/마일스톤 패턴 아이디어 | 개념 참고 | chunk hall 분류 휴리스틱 |
| `extract_memories()` 함수 자체 | 미사용 | 현재 스크립트는 호출하지 않음 |

주의:

- `general_extractor.py`의 `memory_type`은 `decision`, `preference`, `milestone`, `problem`, `emotional`이다.
- `technical` 타입은 원본 `general_extractor.py`가 직접 반환하지 않는다.
- 현재 스킬의 `technical` hall은 `docs-index-build` 쪽에서 별도 휴리스틱으로 추가한 것이다.

### 4.4 MemPalace — `mempalace/palace_graph.py`

현재 구현은 `palace_graph.py`를 직접 재사용하지 않고, 터널 개념만 참고한다.

| 항목 | 현재 상태 | 용도 |
|---|---|---|
| 같은 room이 여러 wing에 걸치면 연결한다는 아이디어 | 개념 참고 | tunnel 계산 규칙 |
| `build_graph()` 함수 자체 | 미사용 | ChromaDB 의존성 때문에 직접 재사용하지 않음 |

### 4.5 MemPalace — `mempalace/palace.py`

| 항목 | 현재 상태 | 용도 |
|---|---|---|
| `SKIP_DIRS` | 직접 참고 | 건너뛸 디렉터리 목록 |
| `file_already_mined()`의 mtime 비교 패턴 | 개념 참고 | 증분 업데이트 설계 |

현재 스킬은 ChromaDB collection 기반 체크 대신 `.doc-palace-state.json`에 mtime을 저장한다.

### 4.6 MemPalace — `mempalace/config.py`

현재 구현은 `sanitize_name()`이나 `sanitize_content()`를 직접 가져다 쓰지 않는다.

| 항목 | 현재 상태 | 용도 |
|---|---|---|
| `sanitize_name()` | 미사용 | 필요 시 future hardening 후보 |
| `sanitize_content()` | 미사용 | 필요 시 future hardening 후보 |

---

## 5. 인제스트 파이프라인

### 5.1 전체 흐름

```
ingest.py <folder_path>
    │
    ├─ [1] SCAN
    │   └─ docs-index-build/scripts/ingest.py 의 scan_folder()
    │      + GitignoreMatcher + SKIP_DIRS 유사 로직
    │       → 파일 목록 + mtime 체크 (state.json 비교)
    │
    ├─ [2] CHUNK
    │   └─ docs-index-build/scripts/ingest.py 의 chunk_text()
    │       → 청크 리스트 생성
    │
    ├─ [3] EXTRACT  (LLM 불필요 1단계)
    │   └─ docs-index-build/scripts/ingest.py 의 classify_chunk()
    │       → hall 분류 (decisions / problems / milestones / technical / reference)
    │
    ├─ [4] ROOM DETECT
    │   └─ docs-index-build/scripts/ingest.py 의 detect_room()
    │       → room_slug (e.g. "jwt-flow", "docker-setup")
    │
    ├─ [5] AAAK WRITE  (AI 작성 단계)
    │   └─ SKILL.md + AAAK_WRITING_GUIDE.md 규칙에 따라
    │      문서 내용을 직접 AAAK 텍스트로 작성
    │
    ├─ [6] TUNNEL DETECT
    │   └─ 같은 room_slug 가 여러 wing 에 등장하면 tunnel 계산
    │
    ├─ [7] WRITE CLOSETS
    │   └─ _closets/<room>.aaak.md 생성/업데이트
    │
    └─ [8] WRITE/UPDATE AGENTS.md
        └─ Wing/Hall/Room 인덱스 + Tunnel 섹션 + LOG 엔트리
```

### 5.2 AI 작성 규칙 (5단계)

```
Read the whole document first.
Do not call an external AAAK tool.
Write AAAK text directly into the closet markdown file.
Follow SKILL.md and AAAK_WRITING_GUIDE.md exactly.

Rules:
- key_quote는 반드시 원문에서 그대로 발췌할 것
- 문서의 의미 있는 내용을 가능한 많이 AAAK로 쓸 것
- 긴 기술 문서를 몇 줄로 축약하지 말 것
- AGENTS.md는 루트에만 두고 _closets 안에 만들지 말 것
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
docs-index-build/
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
name: docs-index-build
description: "문서 폴더를 인제스트해 AGENTS.md 인덱스와
             _closets/*.aaak.md 파일들을 생성한다."
user-invocable: true
---

## 인제스트 (문서 → 기억 궁전)

사용자가 폴더를 지정하면:

1. 다음 명령 실행:
   python3 docs-index-build/ingest.py <folder_path>

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
