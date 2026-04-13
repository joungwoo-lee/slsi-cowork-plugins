# AAAK Writing Guide v2

This guide is for `docs-index-build2`.

AAAK is not an external tool. Write the closet text directly.

## Goal

Preserve the document's meaningful content while making routing cheaper.

That means:

- keep enough detail to answer targeted questions
- keep exact source anchoring through quotes
- reduce repeated tokens through codebooks
- make section-level lookup easy before reopening the source

## Non-Negotiable Rules

1. Read the whole document before writing any AAAK.
2. Do not invent facts.
3. Every `Q:` quote must be copied exactly from the source.
4. Capture decisions, constraints, procedures, exceptions, failure cases, and important examples.
5. Dense documents still need dense zettels.
6. Prefer compact notation by reusing `E:`, `K:`, and `F:` codes.

## Closet Shape

```markdown
<!-- CLOSET_V2|{room}|{wing}|{hall}|{date} -->

# CLOSET: {room}

## AAAK SPEC
E: JWT=jwt_token, ACC=access_token
K: k1=access_token, k2=refresh_token
F: T=TECHNICAL, D=DECISION, C=CORE, O=ORIGIN

## ROUTING
ABOUT: jwt, access_token, refresh_token
NOT: oauth_login, billing
QTYPE: auth_flow, token_lifetime, error_policy
SECTIONS:
- S1|token model|jwt,access_token,refresh_token
- S2|error responses|401,403,error_code

## ZETTELS
1|JWT|260414|JWT auth design
Z1|JWT+ACC|k1,header,bearer,15m|Q:"access token은 15분 유효, Authorization 헤더로 전달"|5|TD
Z2|JWT+REF|k2,httponly,cookie,7d|Q:"refresh token은 7일, HttpOnly 쿠키 전용"|5|TD
L|1-2|token_pair_lifecycle

## SOURCE LINKS
- [jwt-design.md](../auth/jwt-design.md) | chunks:5 | sections:token model,refresh rotation,error responses
```

## Field Rules

### `E:`

- Define only repeated or retrieval-important entities.
- Use 2 to 4 uppercase ASCII letters.
- One code must map to one meaning only inside the closet.

### `K:`

- Define repeated topic keywords or long phrases worth compressing.
- Use `k1`, `k2`, `k3` style codes.
- Keep raw keywords when they are already short.

### `F:`

- Fixed shorthand map:
- `T=TECHNICAL`
- `D=DECISION`
- `C=CORE`
- `O=ORIGIN`

### `ABOUT`

- 3 to 8 terms.
- What this room is actually about.

### `NOT`

- 0 to 6 terms.
- Close-but-wrong topics that should be excluded.
- Prefer sibling topics a user may confuse with this room.

### `QTYPE`

- 2 to 6 short query categories.
- Examples: `setup`, `config`, `api_contract`, `error_policy`, `decision_log`, `troubleshooting`.

### `SECTIONS`

- 2 to 8 section pointers.
- Format: `S{n}|{section label}|{keywords}`.
- Use headings when available.
- If the source has no headings, synthesize sections from major topic shifts.

### Zettel line

Format:

```text
Z{n}|{entities}|{keywords}|Q:"{exact_quote}"|{weight}|{flags}
```

Rules:

- `entities`: `JWT+ACC` style, or blank
- `keywords`: up to 5 items, lowercase where possible
- `weight`: integer `1` to `5`
- `flags`: compact letters such as `TD`, `T`, `C`, `TO`

### Link line

Format:

```text
L|1-2|token_pair_lifecycle
```

- Use for strong within-document links.

## Density Guidance

- short simple document: at least 3 zettels if there are 3 or more distinct points
- medium document: usually 5 to 10 zettels
- dense technical document: often 8+ zettels

Do not compress many rules into one zettel just to save tokens.

## Conversion Procedure

1. Read the whole document.
2. Extract candidate entities, repeated keywords, and section labels.
3. Write `ABOUT`, `NOT`, `QTYPE`, and `SECTIONS` first.
4. Build `E:` and `K:` codebooks for repeated terms.
5. Write one zettel per meaningful point.
6. Add `L` lines for strong relations.
7. Add source links.
8. Re-check every quote against the source.

## Quality Checklist

- Whole document read before writing.
- Quotes are verbatim.
- `ABOUT` and `NOT` help routing rather than restating the title.
- `QTYPE` names match realistic user questions.
- `SECTIONS` point to where to read first.
- Repeated keywords are compressed through `K:` when useful.
- The closet is still dense enough to answer detailed questions.
