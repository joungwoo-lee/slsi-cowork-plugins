---
name: docs-index-build2
description: "문서 폴더를 인제스트해 배제 성능이 더 강한 AGENTS.md 라우팅 인덱스와 압축 AAAK closet 파일을 생성/업데이트한다."
user-invocable: true
---

# docs-index-build2

문서 폴더를 인제스트해 `AGENTS.md`와 `_closets/*.aaak.md`를 만드는 스킬.

- 기존 `docs-index-build`보다 `배제 메타데이터`를 더 많이 만든다.
- 질문과 가까운 Room/Section만 먼저 읽도록 유도한다.
- AAAK는 `E:`, `K:`, `F:` 코드북으로 반복 토큰을 줄인다.
- 원본 파일은 절대 수정하지 않는다.

## 절대 금지

- `wing`, `hall`, `room` 이름의 새 디렉터리를 만들지 말 것
- 원본 폴더 구조를 재배치하거나 복사하지 말 것
- 새로 만들 수 있는 것은 `AGENTS.md`와 `_closets/` 및 그 안의 `.aaak.md` 파일뿐이다
- `AGENTS.md`를 `_closets/` 안이나 다른 하위 폴더 안에 만들지 말 것
- AAAK를 외부 명령, 외부 서비스, 외부 MCP 도구처럼 취급하지 말 것

## 필수 전제

Closet 파일을 쓰기 전에 반드시 같은 디렉터리의 `AAAK_WRITING_GUIDE.md`를 읽고 규칙을 그대로 따른다.

- `Q:` quote는 반드시 원문 그대로 복사할 것
- `ABOUT`는 포함 신호, `NOT`는 배제 신호라는 점을 기억할 것
- `QTYPE`과 `SECTIONS`는 라우팅용이므로 질문과 바로 연결되게 쓸 것
- 애매하면 더 짧고 보수적으로 쓰되, 중요한 내용은 빠뜨리지 말 것

## 인제스트 실행 절차

### Step 1. 스캔 실행

```bash
python3 <skill_dir>/scripts/ingest.py <folder_path>
```

출력 JSON의 `status`가 `up_to_date`면 Step 6으로 건너뛴다.

### Step 2. 작업 데이터 파악

JSON의 핵심 필드:

```json
{
  "new_and_changed": [
    {
      "path": "auth/jwt-design.md",
      "wing": "auth",
      "room": "auth-jwt-design",
      "dominant_hall": "technical",
      "about": ["jwt", "access_token", "refresh_token"],
      "not_about": ["oauth_login", "saml"],
      "qtypes": ["auth_flow", "token_lifetime", "error_policy"],
      "entities": ["JWT", "ACC", "REF", "ERR"],
      "sections": [
        {"id": "S1", "label": "token model", "keywords": ["jwt", "access_token"]}
      ]
    }
  ],
  "all_documents": [...],
  "wing_index": [...],
  "room_index": [...],
  "tunnels": [...]
}
```

### Step 3. Closet 파일 생성

`new_and_changed`의 각 Room에 대해 `_closets/<room>.aaak.md`를 생성하거나 갱신한다.

Closet은 문서의 거의 모든 의미 있는 내용을 담아야 하지만, 반복 토큰은 코드북으로 줄인다.

형식:

```markdown
<!-- CLOSET_V2|{room}|{wing}|{hall}|{date} -->

# CLOSET: {room}

## AAAK SPEC
E: JWT=jwt_token, ACC=access_token
K: k1=access_token, k2=refresh_token
F: T=TECHNICAL, D=DECISION, C=CORE, O=ORIGIN

## ROUTING
ABOUT: jwt, access_token, refresh_token
NOT: oauth_login, saml
QTYPE: auth_flow, token_lifetime, error_policy
SECTIONS:
- S1|token model|jwt,access_token,refresh_token
- S2|error responses|401,403,error_code

## ZETTELS
1|JWT|260414|JWT auth design
Z1|JWT+ACC|k1,header,bearer,15m|Q:"access token은 15분 유효, Authorization 헤더로 전달"|5|TD
L|1-2|token_pair_lifecycle

## SOURCE LINKS
- [jwt-design.md](../auth/jwt-design.md) | chunks:5 | sections:token model,refresh rotation,error responses
```

규칙:

- `ABOUT`: 이 room이 실제로 다루는 핵심 주제
- `NOT`: 헷갈리기 쉬운 비대상 주제
- `QTYPE`: 사용자가 던질 질문 유형
- `SECTIONS`: room 안에서 먼저 읽을 위치
- `Q:` quote는 항상 원문 그대로
- 긴 문서는 여전히 충분히 많은 zettel을 써야 함

### Step 4. AGENTS.md 생성/업데이트

폴더 루트에 `AGENTS.md`를 생성한다. 기존 파일이 있으면 Wing/Room 구조는 전체 재생성하고, 가능하면 `LOG`는 유지한다.

형식:

```markdown
<!-- PALACE_INDEX_V2|{folder_name}|{date}|{total_doc_count} -->

# {folder_name} routing index

## PALACE META
GEN:{date}|DOCS:{count}|WINGS:{n}|ROOMS:{m}|TUNNELS:{k}

## QUERY PROTOCOL
1. 사용자의 질문을 받으면 먼저 `entity`, `action`, `constraint`, `error`, `time/version` 단서를 추출한다.
2. `ABOUT`가 맞고 `NOT`와 충돌하지 않는 Room만 후보로 남긴다.
3. 후보 Room 중 `QTYPE`이 가장 가까운 Room을 먼저 고르고, 나머지는 보조 후보로 둔다.
4. 선택한 Room에서는 전체 closet을 무작정 읽지 말고 `SECTIONS`가 가장 가까운 항목부터 읽는다.
5. closet을 읽은 뒤 반드시 `SOURCE LINKS`를 따라 원문을 열어 사실을 검증한다.
6. closet만으로 답을 확정하지 말고, 최종 답변은 원문에서 확인한 사실만 사용한다.
7. 관련 `TUNNELS`가 있으면 연결 Room도 추가로 확인한다.
8. 후보가 여러 개이거나 충돌이 있으면 불확실성을 드러내고, 어떤 Room/Section을 기준으로 답했는지 분명히 한다.

## WING: auth
> auth, jwt, error_policy

### HALL: technical
- ROOM:auth-jwt-design | [_closets/auth-jwt-design.aaak.md] | 2docs | ABOUT:jwt,access_token,refresh_token,rotation,revocation | NOT:oauth_login,saml,billing | QTYPE:auth_flow,token_lifetime,error_policy | E:JWT,ACC,REF,ERR
  SECTIONS: token model; refresh rotation; logout invalidation; error responses

## TUNNELS
T:auth-jwt-design<->api-error-contract|shared:error_policy
```

작성 규칙:

- `top_keywords`만 쓰지 말고 `ABOUT`, `NOT`, `QTYPE`, `E`, `SECTIONS`를 함께 적는다.
- `NOT`는 room과 가까운 오탐 주제만 넣는다.
- `TUNNELS`는 같은 room명 기준이 아니라 공유 엔티티/공유 주제/명시적 참조 기반으로 작성한다.
- `wing_index`의 `summary`를 Wing 한 줄 설명 초안으로 우선 사용한다.
- `room_index`의 `summary`를 room 1차 설명 근거로 사용하고, `ABOUT`를 그대로 반복하지 말고 짧게 압축한다.
- room 순서는 `wing -> hall -> room_rank 내림차순 -> room 이름` 순으로 고정한다.
- 한 room 항목은 한 줄에 가능한 한 유지하고, `SECTIONS`만 다음 줄로 내린다.
- `ABOUT`는 최대 5개, `NOT`는 최대 4개, `QTYPE`은 최대 4개, `E`는 최대 4개만 노출한다.
- `SECTIONS`는 최대 4개만 노출하고, 각 section label은 1차 탐색에 필요한 것만 남긴다.
- Wing 설명, Room 설명, TUNNELS 라벨은 새 해석을 추가하지 말고 `wing_index`, `room_index`, `tunnels` 값만 재조합한다.
- `QUERY PROTOCOL`은 인덱스 설명이 아니라 실제 행동 지침처럼 쓴다.
- `QUERY PROTOCOL`에는 반드시 `질문 단서 추출 -> 후보 배제 -> section 우선 열람 -> 원문 검증 -> 불확실성 처리` 순서가 들어가야 한다.
- `QUERY PROTOCOL`에는 반드시 `closet만으로 답을 확정하지 말 것` 문구를 포함한다.
- `QUERY PROTOCOL`에는 반드시 `어떤 Room/Section을 기준으로 읽을지 먼저 결정하라`는 문구를 포함한다.

### Step 4B. 결정적 생성 규칙

`AGENTS.md`는 가능한 한 매 실행마다 같은 구조가 나오도록 아래 순서를 고정한다.

1. `wing_index` 순서대로 Wing을 쓴다.
2. 각 Wing 안에서 Hall 순서는 `decisions`, `technical`, `problems`, `milestones`, `reference` 고정이다.
3. 각 Hall 안의 Room 순서는 `room_rank` 내림차순, 동률이면 room 이름 오름차순이다.
4. Room 항목에는 스캐너가 준 값만 사용하고, 비어 있는 필드는 생략하지 말고 가능한 범위 내에서 축약한다.
5. `NOT`가 비어 있으면 임의 추론으로 채우지 말고 빈 값으로 둔다.
6. `SECTIONS` 중 중복 label은 하나만 남긴다.
7. `TUNNELS`는 label, room_a, room_b 순으로 정렬해서 쓴다.
8. 기존 `LOG`가 있으면 보존하고 새 항목만 뒤에 추가한다.

### Step 4A. 검증

저장 전 아래를 확인한다.

1. `Q:` quote가 원문에 문자열 그대로 존재하는가
2. `ABOUT`와 `NOT`가 서로 겹치지 않는가
3. `QTYPE`이 실제 질문 형태와 연결되는가
4. `SECTIONS`가 실제 읽을 위치를 가리키는가
5. 긴 문서인데 zettel이 지나치게 적지 않은가
6. 반복되는 키워드가 `K:`로 적절히 축약되었는가
7. Wing/Room 정렬이 결정적 생성 규칙과 일치하는가
8. `ABOUT`, `NOT`, `QTYPE`, `E`, `SECTIONS` 개수 제한을 지켰는가

### Step 5. 완료 처리

```bash
python3 <skill_dir>/scripts/ingest.py <folder_path> --finalize
```

### Step 6. 완료 보고

사용자에게 아래를 알려 준다.

- 신규/변경/삭제 파일 수
- 생성/업데이트된 closet 파일 목록
- `AGENTS.md` 생성/업데이트 여부
- 주요 Wing/Room/QTYPE 요약
- 실제 생성 경로: `AGENTS.md`는 루트, closet은 `_closets/` 아래만

## 질문만 받을 때의 프로토콜

1. `AGENTS.md`에서 먼저 질문 단서와 맞는 `ABOUT`, `NOT`, `QTYPE`, `SECTIONS`를 찾는다.
2. `NOT`와 충돌하는 Room은 제외하고, `QTYPE`이 가장 가까운 Room부터 연다.
3. closet에서는 관련 `SECTIONS`와 zettel만 먼저 읽고, 필요 없는 section은 건너뛴다.
4. 반드시 `SOURCE LINKS`를 따라 원문을 읽어 확인한다.
5. 관련 tunnel이 있으면 연결 Room도 함께 확인한다.
6. 최종 답변은 원문에서 확인한 사실만 사용한다.

Closet만 읽고 끝내지 말 것. `AGENTS.md`는 라우팅용이고, closet은 압축 기억이며, 원문이 최종 증거다.

## 상태 확인

```bash
python3 <skill_dir>/scripts/ingest.py <folder_path> --status
```
