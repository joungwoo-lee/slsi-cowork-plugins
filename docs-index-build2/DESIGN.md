# docs-index-build2: 설계 문서

## 개요

`docs-index-build2`는 기존 `docs-index-build`의 후속 버전이다.

목표는 3가지다.

- 찾는 정보가 아닌 것을 더 빨리 배제한다.
- 질문과 가까운 Room/Section만 먼저 읽게 만든다.
- closet 요약의 토큰 비용을 줄이되 원문 역추적 가능성은 유지한다.

핵심 차이점:

- `AGENTS.md`를 단순 키워드 목록이 아니라 라우팅 인덱스로 강화
- Room마다 `ABOUT`, `NOT`, `QTYPE`, `E`, `SECTIONS`를 기록
- tunnel을 room 이름 일치가 아니라 공유 엔티티/주제 기반으로 생성
- closet 포맷에 `K:`와 `F:` 코드북을 도입해 반복 토큰을 축약

## 정보 탐색 흐름

```text
사용자 질문
    |
    v
[1] AGENTS.md
    - ABOUT / NOT / QTYPE / E 스캔
    - 관련 Room 후보 축소
    |
    v
[2] Room의 SECTIONS 확인
    - 가장 가까운 section만 우선 열람
    |
    v
[3] _closets/<room>.aaak.md
    - 압축 zettel 확인
    - SOURCE LINKS 확인
    |
    v
[4] 원본 파일 직접 읽기
    - 최종 팩트 검증
```

## AGENTS.md 구조

```markdown
<!-- PALACE_INDEX_V2|{folder_name}|{date}|{doc_count} -->

# {folder_name} routing index

## PALACE META
GEN:{date}|DOCS:{count}|WINGS:{n}|ROOMS:{m}|TUNNELS:{k}

## QUERY PROTOCOL
1. 질문에서 entity, action, constraint, error 단서를 찾는다.
2. ABOUT 일치 Room을 고르고 NOT 항목으로 오탐을 배제한다.
3. QTYPE과 SECTIONS로 가장 가까운 section을 고른다.
4. closet을 열고 SOURCE LINKS를 따라 원문을 읽는다.

## WING: auth
### HALL: technical
- ROOM:auth-jwt-design | [_closets/auth-jwt-design.aaak.md] | 2docs | ABOUT:jwt,access_token,refresh_token,rotation,revocation | NOT:oauth_login,saml,billing | QTYPE:auth_flow,token_lifetime,error_policy | E:JWT,ACC,REF,ERR
  SECTIONS: token model; refresh rotation; logout invalidation; error responses

## TUNNELS
T:auth-jwt-design<->api-error-contract|shared:error_policy
```

## Closet 구조

```markdown
<!-- CLOSET_V2|{room}|{wing}|{hall}|{date} -->

# CLOSET: {room}

## AAAK SPEC
E: JWT=jwt_token, ACC=access_token, REF=refresh_token, ERR=error_response
K: k1=access_token, k2=refresh_token, k3=rotation, k4=revocation
F: T=TECHNICAL, D=DECISION, C=CORE, O=ORIGIN

## ROUTING
ABOUT: jwt, access_token, refresh_token, rotation, revocation
NOT: oauth_login, saml, billing
QTYPE: auth_flow, token_lifetime, logout_invalidation, error_policy
SECTIONS:
- S1|token model|jwt,access_token,refresh_token
- S2|refresh rotation|rotation,replay,revocation

## ZETTELS
1|JWT|260414|JWT auth design
Z1|JWT+ACC|k1,header,bearer,15m|Q:"access token은 15분 유효, Authorization 헤더로 전달"|5|TD
Z2|JWT+REF|k2,k3,httponly,cookie|Q:"refresh token은 7일, HttpOnly 쿠키 전용"|5|TD
L|1-2|token_pair_lifecycle

## SOURCE LINKS
- [jwt-design.md](../auth/jwt-design.md) | chunks:5 | sections:token model,refresh rotation,error responses
```

## 스캐너 출력

`scripts/ingest.py`는 단순 청킹 결과만 내지 않고, AI가 바로 라우팅 인덱스를 쓸 수 있는 메타데이터까지 같이 출력한다.

```json
{
  "status": "needs_update",
  "new_and_changed": [
    {
      "path": "auth/jwt-design.md",
      "wing": "auth",
      "room": "auth-jwt-design",
      "dominant_hall": "technical",
      "about": ["jwt", "access_token", "refresh_token", "rotation"],
      "not_about": ["oauth_login", "saml"],
      "qtypes": ["auth_flow", "token_lifetime", "error_policy"],
      "entities": ["JWT", "ACC", "REF", "ERR"],
      "sections": [
        {"id": "S1", "label": "token model", "keywords": ["jwt", "access_token"]},
        {"id": "S2", "label": "refresh rotation", "keywords": ["rotation", "revocation"]}
      ],
      "chunks": [
        {"index": 0, "hall": "technical", "text": "..."}
      ]
    }
  ],
  "all_documents": [...],
  "wing_index": [
    {
      "wing": "auth",
      "summary": "jwt, token, error_policy",
      "room_order": ["auth-jwt-design", "auth-oauth-policy"],
      "hall_counts": {"technical": 1, "decisions": 1}
    }
  ],
  "room_index": [...],
  "tunnels": [
    {"room_a": "auth-jwt-design", "room_b": "api-error-contract", "label": "shared_qtype:error_policy"}
  ]
}
```

핵심은 3단계 출력이다.

- `new_and_changed`: 이번 실행에서 실제로 closet을 다시 써야 하는 문서
- `all_documents`: state와 합쳐 재구성한 전체 문서 메타
- `wing_index`: Wing 설명과 정렬에 바로 사용할 wing 단위 집계
- `room_index`: AGENTS.md를 쓸 때 바로 사용할 room 단위 집계

## 메타데이터 추출 규칙

### ABOUT

- 제목과 heading에서 얻은 토큰에 더 높은 가중치를 준다.
- 본문 전체 토큰 빈도를 합쳐 상위 주제를 선택한다.
- `overview`, `readme`, `general` 같은 희석 토큰은 제외한다.

### NOT

- 같은 wing 안의 다른 room과 비교해, 헷갈리기 쉬운 sibling topic을 뽑는다.
- 현재 room의 `ABOUT`에는 없지만, 유사 room에 강하게 나타나는 토큰을 우선 사용한다.
- 목적은 요약이 아니라 오탐 배제다.

### QTYPE

- `setup`, `config`, `api_contract`, `error_policy`, `decision_log`, `architecture`, `workflow`, `troubleshooting`, `security`, `reference` 같은 질의 유형을 정규식으로 추론한다.
- AGENTS.md에서 room 선택 순서를 줄이기 위한 질의 라벨이다.

### SECTIONS

- 가능한 경우 실제 heading을 사용한다.
- heading이 부족하면 주제 전환 지점을 기반으로 합성 section을 만든다.
- 목적은 room 전체가 아니라 먼저 읽을 위치를 지정하는 것이다.
- room 집계 시 중복 section label은 제거하고 재번호를 매긴다.

### SUMMARY / RANK

- `room_index.summary`는 room을 한 줄로 설명하는 압축형 요약이다.
- `room_rank`는 `doc_count`, `about`, `qtypes`, `entities` 개수를 기반으로 계산한 정렬 점수다.
- `wing_index.summary`는 wing 안의 상위 topic과 qtype을 합쳐 만든다.
- AGENTS.md 작성 시 자유문장 생성을 줄이고 이 필드를 재사용한다.

## 압축 전략

기존 버전과 달리 `docs-index-build2`는 요약 품질을 해치지 않는 범위에서 반복 토큰을 줄인다.

- `E:`: 반복 엔티티를 짧은 코드로 압축
- `K:`: 반복 키워드와 긴 표현을 `k1`, `k2` 같은 코드로 압축
- `F:`: `TECHNICAL`, `DECISION`, `CORE`, `ORIGIN`을 단문 코드로 압축
- 날짜는 `260414`처럼 짧은 형식 사용 가능
- 관계선은 `T:` 대신 `L|1-2|...` 형식으로 축약

단, 아래는 압축하지 않는다.

- 원문 검증용 `Q:"..."` exact quote
- SOURCE LINKS의 원본 경로
- room 식별에 직접 필요한 `ABOUT`, `NOT`, `QTYPE`, `SECTIONS`

## 터널 규칙

기존 버전은 같은 room 이름이 여러 wing에 나타날 때만 tunnel을 만들었다.

`docs-index-build2`는 아래 우선순위로 tunnel을 만든다.

1. 공유 엔티티가 있으면 `shared_entity:{entity}`
2. 공유 QTYPE이 있으면 `shared_qtype:{qtype}`
3. 공유 ABOUT 토큰이 2개 이상이면 `shared_topic:{token}`

이렇게 하면 room 이름이 달라도 실제로 함께 읽어야 할 문서를 더 잘 연결할 수 있다.

## AGENTS.md 자동 생성 규칙

성능을 위해 `AGENTS.md`는 요약문이 아니라 결정적 필터여야 한다. 그래서 자동 생성 규칙을 강하게 고정한다.

1. Wing 순서는 `wing_index` 순서를 따른다.
2. Hall 순서는 항상 `decisions -> technical -> problems -> milestones -> reference`다.
3. Room 순서는 `room_rank` 내림차순, 동률이면 room 이름 오름차순이다.
4. Wing 한 줄 설명은 `wing_index.summary`를 우선 사용한다.
5. Room 설명은 `room_index.summary`를 우선 사용하고, 새 문장 창작을 최소화한다.
6. 노출 개수는 고정한다.
7. `ABOUT` 최대 5개, `NOT` 최대 4개, `QTYPE` 최대 4개, `E` 최대 4개, `SECTIONS` 최대 4개.
8. `NOT`가 비어 있으면 억지로 채우지 않는다.
9. `SECTIONS`는 중복 label 제거 후 출력한다.
10. `TUNNELS`는 `label`, `room_a`, `room_b` 기준 정렬해 출력한다.

이 규칙의 목적은 세 가지다.

- 같은 문서셋에서 인덱스 구조가 흔들리지 않게 한다.
- AI가 임의 문장을 길게 만들어 토큰을 낭비하지 않게 한다.
- 질문 시 first-pass filtering이 항상 비슷한 품질로 동작하게 한다.

## 상태 저장

`.doc-palace-state.json`에는 파일별 최소 라우팅 메타를 저장한다.

- `mtime`
- `wing`
- `room`
- `dominant_hall`
- `chunk_count`
- `content_preview`
- `headings`
- `about`
- `not_about`
- `qtypes`
- `entities`
- `sections`

다음 인제스트에서는 변경되지 않은 파일도 이 state를 통해 room 집계와 AGENTS.md 재생성에 다시 포함된다.

## 설계 원칙

- 인덱스는 풍부한 본문 요약이 아니라 빠른 필터여야 한다.
- `NOT`는 자주 헷갈리는 주제를 배제하는 데 사용한다.
- `SECTIONS`는 room 전체가 아니라 읽을 위치를 가리키는 라우팅 포인터다.
- closet은 원문 대체물이 아니라 압축된 중간 기억이다.
- 인용문은 검증성과 역추적을 위해 유지하되, 반복 필드는 코드북으로 줄인다.
