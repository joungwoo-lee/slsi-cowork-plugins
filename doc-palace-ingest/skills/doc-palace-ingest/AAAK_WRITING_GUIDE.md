# AAAK Writing Guide

This guide is for an AI that has never seen AAAK before.

Follow this guide exactly when converting source text into AAAK closet content for `doc-palace-ingest`.

## Goal

Turn each source document chunk into a short, source-grounded AAAK zettel that helps a later AI locate the right original file quickly.

AAAK here is not free-form prose. It is a compact indexing format.

## Non-Negotiable Rules

1. Do not invent facts.
2. Do not paraphrase the `key_quote` field. It must be copied exactly from the source chunk.
3. Do not add entities, flags, relationships, or conclusions unless the chunk supports them.
4. Keep each zettel compact. It is an index pointer, not a full summary.
5. If uncertain, choose the simpler output.

## Output Shape

Each closet file uses this structure:

```markdown
<!-- CLOSET|{room}|{wing}|{dominant_hall}|{date} -->

# CLOSET: {room}

## AAAK SPEC
ENT: {CODE}={meaning}, {CODE}={meaning}

## ZETTELS

{file_num}|{primary_entity}|{date}|{title}
{ZID}:{ENTITIES}|{topic_keywords}|"{key_quote}"|{weight}|{flags}
T:{ZID_a}<->{ZID_b}|{relation_label}

## SOURCE LINKS
- [{filename}](../{relative_path}) — {chunk_count} chunks
```

`T:` lines are optional.

## How To Build One Zettel

For each chunk, produce exactly one zettel line.

Format:

```text
{ZID}:{ENTITIES}|{topic_keywords}|"{key_quote}"|{weight}|{flags}
```

Example:

```text
Z2:JWT+ACC|access_token,header,bearer,15min,expiry|"access token은 15분 유효, Authorization 헤더로 전달"|5|TECHNICAL+DECISION
```

## Field Rules

### 1. `ZID`

- Use `Z1`, `Z2`, `Z3` in chunk order within the current file.
- Never skip numbers.

### 2. `ENTITIES`

- Use `+` between codes.
- Include 1 to 3 important entity codes only.
- If there is no clear entity, leave it empty after the colon.

Allowed:

```text
Z1:JWT+ACC|...
Z2:ERR|...
Z3:|...
```

### 3. `topic_keywords`

- Lowercase only.
- Comma-separated.
- Maximum 5 keywords.
- Prefer nouns or short noun phrases.
- Do not use full sentences.
- Do not repeat the entity code as a keyword unless it adds meaning.

Good:

```text
access_token,header,bearer,15min,expiry
```

Bad:

```text
we decided to use access token in header because security
```

### 4. `key_quote`

- Must be copied exactly from the source chunk.
- Use one sentence or one sentence fragment only.
- Prefer the sentence that carries the most concrete decision, rule, behavior, constraint, or definition.
- Keep punctuation and wording exactly as written in the source.
- If the chunk has no strong sentence, choose the shortest exact sentence that still captures the point.

Good:

```text
"refresh token은 7일, HttpOnly 쿠키 전용"
```

Bad:

```text
"refresh token lasts seven days in a cookie"
```

The bad example is not exact.

### 5. `weight`

Use only integers `1` to `5`.

- `5`: core architecture, irreversible decision, security rule, central contract, hard requirement
- `4`: important implementation rule, key error handling, major constraint, important mechanism
- `3`: useful design detail, common operational behavior, standard reference fact
- `2`: supporting detail, secondary example, routine note
- `1`: minor context with low retrieval value

When unsure, prefer `3`.

### 6. `flags`

Only use these flags:

- `TECHNICAL`
- `DECISION`
- `CORE`
- `ORIGIN`

Rules:

- `TECHNICAL`: architecture, API, schema, config, data model, implementation behavior
- `DECISION`: explicit choice, selected option, should/decided/chosen/standardized direction
- `CORE`: central principle or invariant that many later answers may depend on
- `ORIGIN`: beginning of a feature, project, migration, incident, or policy

Use `+` when more than one flag clearly applies.

If no flag clearly applies, leave the field empty but keep the separator.

Allowed:

```text
|5|TECHNICAL+DECISION
|3|TECHNICAL
|2|
```

## Entity Code Rules

The `ENT:` section defines code mappings used in the closet.

### When To Create An Entity Code

Create a code only if the entity appears repeatedly or is retrieval-important.

Good candidates:

- protocols or token types: `JWT`, `ACC`, `REF`
- system components: `API`, `DB`, `SDK`
- named services or products: `S3`, `IAM`, `OIDC`
- recurring domain concepts: `USR`, `ORG`, `ACL`
- stable error buckets: `ERR`

Do not create too many codes. A small stable legend is better.

### How To Write Codes

- Prefer 2 to 4 uppercase ASCII letters.
- Reuse obvious industry abbreviations if they are already standard.
- If there is no standard abbreviation, choose a short stable code.
- One code must map to one meaning only within the same closet file.

Good:

```text
ENT: JWT=jwt_token, ACC=access_token, REF=refresh_token, ERR=error_response
```

Bad:

```text
ENT: A=access_token, A=auth_header
```

## Choosing `primary_entity`

Header format:

```text
{file_num}|{primary_entity}|{date}|{title}
```

- `primary_entity` is the single most representative entity code for that source file.
- If no strong entity exists, use `GEN`.

Examples:

```text
1|JWT|2026-04-13|JWT 인증 흐름 설계
2|ERR|2026-04-13|JWT 에러 응답 정의
3|GEN|2026-04-13|배포 체크리스트
```

## When To Add `T:` Tunnel Lines

Add `T:` lines only when two zettels in the same closet are clearly connected by:

- lifecycle
- cause and effect
- request and response
- rule and exception
- decision and consequence

Format:

```text
T:Z1<->Z2|token_pair_lifecycle
```

Use a short lowercase relation label with underscores.

## Required Conversion Procedure

For every source document:

1. Read all chunks in order.
2. Identify repeated entities worth defining in `ENT:`.
3. Choose one `primary_entity` for the file header.
4. For each chunk:
   - pick 1 exact quote
   - pick up to 3 entities
   - pick up to 5 lowercase keywords
   - assign weight 1-5
   - assign only supported flags
5. Add `T:` lines only for strong, obvious links.
6. Add source links at the end.
7. Re-check that every `key_quote` is verbatim.

## Quality Checklist

Before finalizing a closet file, verify all of the following:

- Every zettel has the same 5-part shape.
- Every `key_quote` exists literally in the source chunk.
- No keyword list exceeds 5 items.
- No entity code is ambiguous within the file.
- Weight values are integers only.
- Flags only come from the allowed list.
- The closet is useful as an index, not bloated as a summary.

## Full Example

```markdown
<!-- CLOSET|auth-jwt-design|auth|technical|2026-04-13 -->

# CLOSET: auth-jwt-design

## AAAK SPEC
ENT: JWT=jwt_token, ACC=access_token, REF=refresh_token, ERR=error_response

## ZETTELS

1|JWT|2026-04-13|JWT 인증 흐름 설계
Z1:JWT+ACC|access_token,header,bearer,15min,expiry|"access token은 15분 유효, Authorization 헤더로 전달"|5|TECHNICAL+DECISION
Z2:JWT+REF|refresh_token,httponly,cookie,7day,rotation|"refresh token은 7일, HttpOnly 쿠키 전용"|5|TECHNICAL+DECISION
Z3:JWT|blacklist,redis,jti,logout,invalidate|"로그아웃 시 Redis에 jti 블랙리스트 등록"|4|TECHNICAL
T:Z1<->Z2|token_pair_lifecycle

2|ERR|2026-04-13|JWT 에러 응답 정의
Z1:ERR|expired_token,401,error_code,response|"토큰 만료 시 401 EXPIRED_TOKEN 반환"|4|TECHNICAL
Z2:ERR|insufficient_scope,403,authorization,response|"권한 부족 시 403 INSUFFICIENT_SCOPE"|3|TECHNICAL

## SOURCE LINKS
- [jwt-design.md](../auth/jwt-design.md) — 5 chunks
- [jwt-errors.md](../auth/jwt-errors.md) — 2 chunks
```
