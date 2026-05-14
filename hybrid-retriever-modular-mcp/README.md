# hybrid-retriever-modular-mcp

FastAPI 서버 없이 MCP 프로세스 안에서 직접 동작하는 자체 완결형 로컬 리트리버입니다. `email-mcp`와 같은 방식으로 `py server.py`가 stdio MCP 서버를 띄우고, 도구 호출 시 로컬 SQLite FTS5와 선택적 Qdrant 벡터 DB를 직접 사용합니다.

## 구조

```
Claude Desktop / Code --stdio--> py server.py
                                   |-- SQLite FTS5 keyword index
                                   |-- Qdrant local vector store (optional)
                                   `-- C:\Retriever_Data\Files source store
```

외부 `hybrid_retriever_windows_local` FastAPI 서버나 `RETRIEVER_BASE_URL`은 필요하지 않습니다.

## 도구

| 도구 | 설명 |
|---|---|
| `search` | dataset 안의 chunk를 키워드/하이브리드 검색. `linear`/`rrf` fusion, metadata filter, parent chunk replace 지원 |
| `list_datasets`, `get_dataset`, `create_dataset`, `delete_dataset` | 데이터셋 관리 |
| `upload_document` | 로컬 TXT/MD/PDF/DOCX/XLSX 파일을 복사, 청킹, SQLite 색인, 선택적 임베딩/Qdrant 업서트 |
| `list_documents`, `get_document`, `delete_document` | 문서 관리 |
| `list_chunks` | 문서 chunk 확인 |
| `get_document_content` | 저장된 원문 텍스트 조회 |
| `list_pipelines` | 현재 로컬 ingest/search 설정 조회 |
| `health` | DB, 데이터 루트, 인덱스 카운트 확인 |

## 설치

새 PC에서 한 번만:

```powershell
.\claude-mcp-add-retriever.ps1
```

이게 Claude Code(CLI)에 MCP를 등록합니다. **의존성은 첫 도구 호출 시 자동 설치** — `mcp_server/dispatch.boot_doctor`가 누락 패키지를 확인하고, 현재 MCP 서버를 실행 중인 Python으로 `.mcp_deps/`에 `pip install -r requirements.txt --target .mcp_deps`를 실행합니다.

`.env`만 실제 값으로 편집:

```env
RETRIEVER_DATA_ROOT=C:\Retriever_Data
RETRIEVER_DEFAULT_DATASETS=my_docs
```

semantic search가 필요하면 임베딩 API 설정도 채웁니다. 비워두면 SQLite FTS5 키워드 검색만 동작합니다.

> **한국어 검색**: FTS5는 `trigram` 토크나이저를 사용합니다. 어절 중간 부분일치(`보고서` → `보고서를`)가 자동으로 매치됩니다. 검색어는 **3글자 이상**이어야 trigram이 만들어지므로 1~2글자 키워드는 매치되지 않을 수 있습니다. 기존 DB는 첫 실행 시 자동으로 재색인됩니다.

## 이식된 로컬 리트리버 기능

`hybrid_retriever_windows_local`의 Windows-local 핵심 경로를 MCP 내부 구현으로 옮겼습니다.

| 기능 | 상태 |
|---|---|
| SQLite FTS5 keyword backend (trigram tokenizer, 한국어 부분일치) | 지원 |
| Qdrant local vector backend | 임베딩 설정 시 지원 |
| TXT/MD/PDF/DOCX/XLSX reader | 지원 |
| default chunking | 지원 |
| parent-child hierarchical chunking | `use_hierarchical=true` 또는 `full`로 지원 |
| linear fusion | 지원 |
| RRF fusion | `fusion=rrf`로 지원 |
| parent chunk replacement | 지원 |
| metadata 저장/검색 필터 | 지원 |
| FastAPI/React UI/API key server | MCP에는 불필요하므로 제외 |

## Claude 설정 예시

```json
{
  "mcpServers": {
    "retriever": {
      "command": "py",
      "args": ["-3", "C:\\Users\\<YOU>\\.claude\\skills\\hybrid-retriever-modular-mcp\\server.py"],
      "env": {
        "RETRIEVER_DATA_ROOT": "C:\\Retriever_Data",
        "RETRIEVER_DEFAULT_DATASETS": "my_docs"
      }
    }
  }
}
```

## 제한

PDF/Office 파싱은 `pypdf`, `python-docx`, `openpyxl` 의존성을 사용합니다. 암호화/스캔 PDF처럼 텍스트 추출이 불가능한 파일은 별도 OCR이 필요합니다.
