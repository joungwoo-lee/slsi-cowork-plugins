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
1. 질문의 entity, action, constraint, error 단서를 찾는다.
2. ABOUT 일치 Room을 찾고 NOT으로 배제한다.
3. QTYPE과 SECTIONS로 먼저 볼 closet 위치를 좁힌다.
4. SOURCE LINKS를 따라 원문을 읽는다.

## WING: auth
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

### Step 4A. 검증

저장 전 아래를 확인한다.

1. `Q:` quote가 원문에 문자열 그대로 존재하는가
2. `ABOUT`와 `NOT`가 서로 겹치지 않는가
3. `QTYPE`이 실제 질문 형태와 연결되는가
4. `SECTIONS`가 실제 읽을 위치를 가리키는가
5. 긴 문서인데 zettel이 지나치게 적지 않은가
6. 반복되는 키워드가 `K:`로 적절히 축약되었는가

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

1. `AGENTS.md`에서 `ABOUT`, `NOT`, `QTYPE`, `SECTIONS`를 먼저 본다.
2. 가장 가까운 room의 closet을 연다.
3. 관련 section과 zettel을 확인한다.
4. `SOURCE LINKS`를 따라 원본을 읽는다.
5. tunnel이 있으면 연결 room도 함께 확인한다.

Closet만 읽고 끝내지 말고, 최종 답변은 원문 기반으로 만든다.

## 상태 확인

```bash
python3 <skill_dir>/scripts/ingest.py <folder_path> --status
```
