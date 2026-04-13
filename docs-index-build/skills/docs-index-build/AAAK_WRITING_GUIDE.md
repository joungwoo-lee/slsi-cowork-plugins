# AAAK Writing Guide

This guide is for an AI that has never seen AAAK before.

Follow this guide exactly when converting source documents into AAAK closet content for `docs-index-build`.

AAAK is not an external tool, command, API, model, or plugin.
AAAK here means: a text notation that you write directly into the closet markdown file yourself.

Do not search for an AAAK executable.
Do not attempt to call AAAK.
Do not claim AAAK is unavailable.
Just write the AAAK text.

## Goal

Write the document content into AAAK as fully as practical.

Do not produce a thin overview. Do not collapse a long document into only a few lines unless the document itself is very short.

The closet should preserve nearly all meaningful document content in AAAK form so a later AI can recover most of the document's substance without reopening the source immediately.

## Non-Negotiable Rules

1. Read the whole document before writing any AAAK for that document.
2. Convert the document's meaningful content, not just its headline ideas.
3. Do not invent facts.
4. Do not paraphrase the `key_quote` field. It must be copied exactly from the source document.
5. Capture decisions, rules, constraints, procedures, exceptions, edge cases, examples, and error handling when present.
6. If the document contains many distinct points, write many zettels.
7. Sparse AAAK is a failure.

## What A Closet Should Contain

One closet file may cover multiple documents that share the same room.

Within that closet, each source document gets:

- one file header line
- as many zettels as needed to cover the document's meaningful content
- optional `T:` lines linking related zettels

Do not cap yourself at 1 to 5 zettels. Use as many as necessary.

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

## Summary Unit

The summary unit is the document, but the coverage target is the document's full content.

That means:

- first read all chunks in order
- understand the document structure
- then write zettels for each meaningful point in the document
- do not stop after only the main ideas

Meaningful points include:

- core design
- decisions
- constraints
- invariants
- procedures
- setup steps
- configuration rules
- exceptions
- edge cases
- failure modes
- warnings
- examples that clarify behavior

If a document is dense, the AAAK should also be dense.

## How To Build Full-Content Zettels

For each document, after reading the whole document, produce zettels until the document's meaningful content has been covered.

Format:

```text
{ZID}:{ENTITIES}|{topic_keywords}|"{key_quote}"|{weight}|{flags}
```

Example:

```text
Z1:JWT+ACC|access_token,header,bearer,15min,expiry|"access token은 15분 유효, Authorization 헤더로 전달"|5|TECHNICAL+DECISION
```

## Coverage Rules

Do not write only one zettel per chunk, but also do not compress many chunks into too few zettels.

Instead:

- one zettel per meaningful point
- multiple zettels may come from one chunk if that chunk contains multiple distinct rules or facts
- one zettel may be grounded by a sentence in one chunk and still represent a broader document section, as long as it stays faithful

### Minimum Density Rule

Use this as a floor, not a ceiling:

- short simple document: at least 3 zettels if it contains 3 or more distinct points
- medium document: usually 6 to 12 zettels
- dense technical document: often 10+ zettels

If a long technical document ends up with only a few zettels, it is almost certainly too sparse.

## Field Rules

### 1. `ZID`

- Use `Z1`, `Z2`, `Z3` in the order you present the document's points.
- Never skip numbers.
- Group related points near each other.

### 2. `ENTITIES`

- Use `+` between codes.
- Include 1 to 3 important entity codes only.
- Choose entities relevant to the point represented by that zettel.
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
- Pick keywords that make that specific point retrievable.

Good:

```text
access_token,header,bearer,15min,expiry
```

Bad:

```text
we decided to use access token in header because security
```

### 4. `key_quote`

- Must be copied exactly from the source document.
- Use one sentence or one sentence fragment only.
- Pick the sentence that best grounds the zettel's point.
- Keep punctuation and wording exactly as written in the source.
- A `key_quote` can come from any chunk, as long as it comes from the same document.

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
- `DECISION`: explicit choice, selected option, chosen standard, accepted tradeoff
- `CORE`: central principle or invariant the rest of the document depends on
- `ORIGIN`: beginning of a feature, migration, policy, workflow, or important initiative

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

Create a code if the entity is repeated or retrieval-important in the room.

Good candidates:

- protocols or token types: `JWT`, `ACC`, `REF`
- system components: `API`, `DB`, `SDK`
- named services or products: `S3`, `IAM`, `OIDC`
- recurring domain concepts: `USR`, `ORG`, `ACL`
- stable error buckets: `ERR`

Do not create too many codes, but do create enough codes to avoid vague AAAK.

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

- `primary_entity` is the single most representative entity code for that document.
- If no strong entity exists, use `GEN`.

Examples:

```text
1|JWT|2026-04-13|JWT 인증 흐름 설계
2|ERR|2026-04-13|JWT 에러 응답 정의
3|GEN|2026-04-13|배포 체크리스트
```

## When To Add `T:` Tunnel Lines

Add `T:` lines when two zettels in the same document are clearly connected by:

- lifecycle
- cause and effect
- request and response
- rule and exception
- decision and consequence
- procedure and result

Format:

```text
T:Z1<->Z2|token_pair_lifecycle
```

Use a short lowercase relation label with underscores.

## Required Conversion Procedure

For every source document:

1. Read all chunks in order until you understand the whole document.
2. Identify repeated entities worth defining in `ENT:`.
3. Make a rough list of all meaningful points in the document.
4. Choose one `primary_entity` for the file header.
5. For each meaningful point, create one zettel:
   - pick 1 exact quote from the document
   - pick up to 3 entities
   - pick up to 5 lowercase keywords
   - assign weight 1-5
   - assign only supported flags
6. If one chunk contains several meaningful points, split them into multiple zettels.
7. Add `T:` lines for strong links.
8. Add source links at the end.
9. Re-check that every `key_quote` is verbatim.
10. Re-check that the resulting AAAK is not sparse.

## Quality Checklist

Before finalizing a closet file, verify all of the following:

- You read the whole document before writing AAAK.
- The zettels cover nearly all meaningful document content.
- Decisions, constraints, procedures, exceptions, and failure cases were not silently dropped.
- Every zettel has the same 5-part shape.
- Every `key_quote` exists literally in the source document.
- No keyword list exceeds 5 items.
- No entity code is ambiguous within the file.
- Weight values are integers only.
- Flags only come from the allowed list.
- The AAAK is dense enough that it would help answer detailed questions, not only broad ones.

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
Z4:JWT|token_rotation,replay_defense,refresh_flow,revocation|"refresh token은 매 재발급 시 rotation한다"|4|TECHNICAL+DECISION
T:Z1<->Z2|token_pair_lifecycle
T:Z2<->Z4|refresh_rotation_flow

2|ERR|2026-04-13|JWT 에러 응답 정의
Z1:ERR|expired_token,401,error_code,response|"토큰 만료 시 401 EXPIRED_TOKEN 반환"|4|TECHNICAL
Z2:ERR|insufficient_scope,403,authorization,response|"권한 부족 시 403 INSUFFICIENT_SCOPE"|3|TECHNICAL
Z3:ERR|invalid_signature,401,verification,failure|"서명이 유효하지 않으면 401 INVALID_TOKEN 반환"|4|TECHNICAL

## SOURCE LINKS
- [jwt-design.md](../auth/jwt-design.md) — 5 chunks
- [jwt-errors.md](../auth/jwt-errors.md) — 2 chunks
```
