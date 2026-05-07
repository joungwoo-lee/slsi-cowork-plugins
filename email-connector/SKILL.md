---
name: email-connector
description: Decode local PST files (no Outlook required) and build a hybrid keyword (SQLite FTS5) + semantic (Qdrant) search index over mail bodies AND attachment text (PDF, DOCX) converted to unified markdown. Use when the user wants to ingest a PST archive on Windows and run keyword + semantic search across mail and attachment contents. ALSO use when the user asks to set up / install / configure email-connector — read SETUP.md and follow it. Triggers on phrases like "PST 인덱싱", "PST 검색", "메일 첨부파일까지 검색", "email-connector ingest", "하이브리드 검색", "email-connector 셋업", "email-connector 설치". Requires Windows 10/11 native + Python 3.9 + an external embedding API endpoint.
---

# Email Connector Skill (PST → Hybrid Search)

PST 파일을 직접 디코딩하여 메일 본문 + 첨부파일(PDF, DOCX) 텍스트를 통합 마크다운으로 변환하고, **SQLite FTS5 (키워드)** + **Qdrant 로컬 (의미)** 두 트랙으로 인덱싱하는 스킬.

## When to use
- 사용자가 .pst 아카이브에서 메일을 검색하려 할 때 (Outlook 실행 없이).
- 첨부 PDF/Word 내부 텍스트까지 함께 검색해야 할 때.
- 키워드 정확매칭과 의미 유사도 검색을 함께 쓰고 싶을 때.

## When NOT to use
- 메일이 클라우드(M365)에만 있을 때 → Graph API 스킬 사용.
- Outlook 실행 중에 라이브로 검색해야 할 때 → `outlook-search` 스킬 사용.
- macOS / Linux / WSL에서 실행 → pypff 휠 미제공. Windows 네이티브에서만 동작.

## Prerequisites
- Windows 10/11 (네이티브, Docker/WSL 사용 안 함)
- Python 3.9 (.exe 설치) — pypff 등 prebuilt wheel 사용 가능, C++ Build Tools 불필요
- 외부 임베딩 API endpoint + API key (Dense Vector 발급)
- 의존성 설치:
  ```cmd
  pip install -r requirements.txt
  ```

## Files
- `SETUP.md` — **셋업/설치 절차서**. 사용자가 "셋업/설치/install/configure" 요청을 할 때 반드시 이 파일을 먼저 읽고, 단계 마커(`[USER]`/`[AGENT]`/`[CHECK]`)에 따라 순서대로 진행한다.
- `scripts/config.py` — 경로/엔드포인트 설정 로더
- `scripts/pst_extractor.py` — pypff 기반 PST 디코딩 (RTF 폴백 포함)
- `scripts/markdown_converter.py` — HTML/PDF/DOCX → 통합 마크다운
- `scripts/embedding_client.py` — 외부 API 임베딩 클라이언트
- `scripts/storage.py` — SQLite (Metadata + FTS5) + Qdrant 로컬 저장
- **`scripts/convert.py` — Phase 1**: PST → `body.md` + 원본 확장자 첨부파일 + `meta.json`
- **`scripts/index.py` — Phase 2**: 변환된 파일들을 SQLite FTS5 + Qdrant로 인덱싱
- `scripts/ingest.py` — Phase 1 + Phase 2 연속 실행 래퍼
- `scripts/search.py` — 하이브리드 검색 (FTS5 + Qdrant 결합)
- `scripts/doctor.py` — 설치 진단 (Python/의존성/config/임베딩 API 도달성 검사)

## Two-phase architecture
파이프라인은 두 단계로 분리되어 단독 / 연속 실행이 모두 가능합니다.

**Phase 1 — 변환 (PST → 파일)**
PST에서 메일을 추출해 메일 ID별 폴더에:
- `body.md` (메일 본문 + 첨부파일 텍스트 통합 마크다운)
- 원본 첨부파일 (확장자 그대로, 변환 없이)
- `meta.json` (제목, 발신자, 수신일 등 — Phase 2가 PST 재읽기 없이 인덱싱하기 위해 보존)

DB나 외부 API를 전혀 호출하지 않음.

**Phase 2 — 인덱싱 (파일 → DB)**
`Files/[Mail_ID]/`를 워킹하면서:
- SQLite metadata + FTS5 키워드 인덱스 갱신
- 옵션: 외부 임베딩 API 호출 → Qdrant 벡터 저장

PST를 다시 읽지 않음. 임베딩 모델/dim 변경, 인덱스 재구축, 일부 메일만 재인덱싱 등이 가볍게 가능.

## Setup workflow
사용자가 셋업/설치/구성을 요청하면:
1. 먼저 `SETUP.md`를 Read 도구로 읽는다.
2. STEP 0부터 순서대로 따라간다. STEP을 건너뛰지 않는다.
3. 각 단계의 마커를 준수한다:
   - **[USER]** — 사용자에게 안내만 하고 응답을 받기 전엔 다음으로 가지 않는다.
   - **[AGENT]** — 직접 명령을 실행하고 결과를 보고한다. 한 번에 하나씩 실행 (병렬 금지).
   - **[CHECK]** — 검증; 실패 시 표시된 회귀 STEP으로 돌아가 사용자에게 원인을 보고한다.
4. WSL/macOS/Linux가 감지되면 즉시 중단하고 사용자에게 알린다.

## Storage layout (default `C:\Outlook_Data\`)
```
C:\Outlook_Data\
├── Files\[Mail_ID]\body.md           # 통합 마크다운 (본문 + 첨부 텍스트)
├── Files\[Mail_ID]\attachments\      # 원본 첨부파일
├── metadata.db                       # SQLite (metadata + FTS5)
└── VectorDB\                         # Qdrant 로컬 폴더
```

## Commands

### 1. 설정 파일 작성
`config.example.json`을 `config.json`으로 복사 후 임베딩 API 정보 입력.

### 2. 변환 + 인덱싱

**연속 실행 (한 번에)**
```cmd
python scripts\ingest.py --pst "C:\path\to\archive.pst" --config config.json
```
옵션:
- `--limit N` — 처음 N개 메일만 처리 (테스트용)
- `--skip-embedding` — Qdrant 인덱싱 생략, SQLite FTS5만
- `--skip-convert` — Phase 1 건너뛰고 기존 변환 결과로 인덱싱만
- `--skip-index` — Phase 1만, 인덱싱 생략

**Phase 1 단독 (변환만 — DB 미접근, 외부 API 미호출)**
```cmd
python scripts\convert.py --pst "C:\path\to\archive.pst" --config config.json [--limit N]
```
산출: `cfg.files_root\[Mail_ID]\{body.md, meta.json, attachments\...}`

**Phase 2 단독 (이미 변환된 파일을 인덱싱)**
```cmd
python scripts\index.py --config config.json [--skip-embedding] [--mail-id ID ...]
```
- PST를 다시 읽지 않고 `Files/` 디렉토리만 스캔.
- `--mail-id`를 반복 지정하면 해당 메일만 재인덱싱. 임베딩 모델/dim 변경 후 전체 재인덱싱이나 부분 재인덱싱에 사용.

### 3. 검색
```cmd
python scripts\search.py --query "협력사 보안 점검 결과 보고서" --config config.json --top 10
```
옵션:
- `--mode hybrid|keyword|semantic` — 검색 모드 (기본 hybrid)
- `--top N` — 반환 개수

결과는 JSON으로 출력되며 각 항목은 `mail_id`, `subject`, `sender`, `received`, `body_path`, `score`, `score_keyword`, `score_semantic`, `snippet`을 포함.

## 검색 시나리오
1. 사용자가 "작년 협력사 보안 점검 결과 보고서 찾아줘" 질문.
2. `search.py`가 SQLite FTS5에서 키워드 매칭, Qdrant에서 의미 유사도 매칭.
3. 두 점수를 정규화·결합해 상위 N개 mail의 통합 마크다운 경로 반환.
4. Claude가 `body.md`를 읽고 어떤 메일·첨부파일에 답이 있는지 인용.
