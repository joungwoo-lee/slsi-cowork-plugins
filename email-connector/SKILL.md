---
name: email-connector
description: Decode local PST files (no Outlook required) and build a hybrid keyword (SQLite FTS5) + semantic (Qdrant) search index over mail bodies AND attachment text (PDF, DOCX) converted to unified markdown. Use when the user wants to ingest a PST archive on Windows and run keyword + semantic search across mail and attachment contents. Triggers on phrases like "PST 인덱싱", "PST 검색", "메일 첨부파일까지 검색", "email-connector ingest", "하이브리드 검색". Requires Windows 10/11 native + Python 3.9 + an external embedding API endpoint.
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
- `scripts/config.py` — 경로/엔드포인트 설정 로더
- `scripts/pst_extractor.py` — pypff 기반 PST 디코딩
- `scripts/markdown_converter.py` — HTML/PDF/DOCX → 통합 마크다운
- `scripts/embedding_client.py` — 외부 API 임베딩 클라이언트
- `scripts/storage.py` — SQLite (Metadata + FTS5) + Qdrant 로컬 저장
- `scripts/ingest.py` — PST → 통합 MD → DB 인덱싱 파이프라인
- `scripts/search.py` — 하이브리드 검색 (FTS5 + Qdrant 결합)

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

### 2. PST 인제스트
```cmd
python scripts\ingest.py --pst "C:\path\to\archive.pst" --config config.json
```
옵션:
- `--limit N` — 처음 N개 메일만 인제스트 (테스트용)
- `--skip-embedding` — Qdrant 인덱싱 생략, FTS5만

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
