# hybrid-retriever-modular-mcp

자체 완결형 로컬 RAG MCP 서버. `py server.py`가 stdio MCP를 띄우고, 도구 호출은 in-process로 **SQLite FTS5 (kiwipiepy 한국어 형태소) + 선택적 Qdrant 벡터 + 임베디드 Kùzu 그래프**를 사용합니다. 별도 백엔드 불필요.

## 도구 노출 — 동작 흐름 기반 점진 노출

`tools/list` cold start = **4개**: `search`, `upload`, `list_datasets`, `admin_help`. 후속 도구는 부모 도구가 실행된 직후 `notifications/tools/list_changed`로 자동 노출됩니다. 작은 모델이 받는 시작 컨텍스트를 최소화하면서, 도구가 필요해진 순간에는 카탈로그가 늘어나 있습니다.

| 부모 호출 | 노출되는 후속 도구 | 이유 |
|---|---|---|
| `upload(async=true)` | `get_job` | 비동기 작업은 `job_id`를 폴링해야 결과 도착 확인 |
| `list_datasets` | `list_documents` | dataset 안 문서로 드릴-다운 자연스러움 |
| `admin_help` | 위 + 모든 관리 도구 | 명시적 admin 진입 |

`search`는 의도적으로 후속 노출이 없습니다. 리턴이 이미 **리랭크된 청크 + citation** 이라 그 자체가 답입니다. `get_document_content`(원문 전체)는 사후 디버깅용이라 `admin_help` 뒤로 둡니다. `get_dataset`도 `list_datasets`가 같은 metadata를 다 돌려주므로 잉여 → admin 뒤.

`admin_help` 게이트 뒤 도구군: **파괴적**(`create_dataset`, `delete_dataset`, `delete_document`) · **잉여/디버깅**(`get_dataset`, `get_document`, `get_document_content`, `list_chunks`, `health`) · **그래프**(`graph_query`, `graph_rebuild`) · **Hippo2**(`hippo2_index`, `hippo2_search`, `hippo2_stats`, …) · **파이프라인**(`list_pipelines`, `save_pipeline`, `open_pipeline_editor`, …).

부모 응답에는 구조화된 `next_action`/`next_actions`(`{tool, arguments, use_when}`)이 포함되어, 클라이언트가 `tools/list_changed`를 무시하는 경우에도 다음 호출 모양을 그대로 받아쓸 수 있습니다.

## 동작 흐름

```
upload(path, [pipeline])  →  ingest → SQLite/Qdrant/그래프 투영
   ├ 동기:  결과 즉시 반환
   └ async: { job_id, next_action: {tool: "get_job", arguments: {job_id}} }
              ↳ 서버가 tools/list_changed 송출 → get_job 노출

search(query, dataset_ids?)  →  dataset metadata가 경로 선택
   └ 리턴: 리랭크된 청크 + citation (= 답 자체, 후속 호출 불필요)

list_datasets()
   └ next_actions.browse_documents → list_documents 노출
```

`tools/list`의 `dataset_id` / `dataset_ids` 파라미터에는 **현재 등록된 dataset과 각 `use_when` 노트**가 동적으로 들어갑니다. 에이전트는 파이프라인이 아닌 dataset만 고르면 됩니다.

## 설치

```powershell
.\claude-mcp-add-retriever.ps1
```

Claude Code CLI에 등록합니다. 의존성은 첫 도구 호출 시 백그라운드 `pip install`로 자동 설치(`boot_doctor`).

`.env.example` → `.env` 복사 후 편집:

```env
RETRIEVER_DATA_ROOT=                       # 비우면 platform-default
RETRIEVER_DEFAULT_DATASETS=my_docs
EMBEDDING_API_URL=https://api.openai.com/v1/embeddings
EMBEDDING_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
```

`EMBEDDING_API_URL`을 비우면 FTS5 키워드 전용. Hippo2는 `EMBEDDING_*` + `LLM_*` 필요(LLM 값 비면 EMBEDDING 값 자동 재사용).

> `load_dotenv(override=True)`: `.env`가 OS 환경변수를 항상 이깁니다(만료 키 silent 우선 사고 방지).

## 한국어 검색

색인·쿼리 양쪽 `kiwipiepy` 형태소. **2글자 한국어**("메일", "엔진")도 매치. 합성어("회의록")는 한 형태소라 "회의"로는 안 잡힘. 스키마 버전 변경 시 자동 재색인.

## 파이프라인 프로파일

| profile | 용도 |
|---|---|
| `default` | 하이브리드(FTS5 + Qdrant, linear fusion, parent-replace) |
| `keyword_only` | FTS5 + RRF만, 임베딩 API 우회 |
| `email` | `.pst` / 변환된 이메일 디렉토리 |
| `hippo2` | `hippo2_unified.json` 기반 모듈러 파이프라인. passage embedding/Qdrant + OpenIE entity/fact embedding 인덱싱 후, 검색은 query-to-triple 정렬 + entity/passage node seed + PPR + LLM 온라인 필터링 |
| `rrf_rerank` | RRF + BGE cross-encoder rerank |
| `rrf_llm_rerank` | RRF + LLM rerank |
| `rrf_graph_rerank` | RRF + 그래프 이웃 + BGE rerank |

토폴로지는 모두 node-centric JSON(`retriever/pipelines/<name>_unified.json`). `open_pipeline_editor`로 비주얼 편집 가능.

`upload`와 `search`는 파이프라인별로 다른 로직을 하드코딩하지 않습니다. 둘 다 공통 엔트리포인트가 선택된 profile의 topology JSON을 로드하고, 그 안의 `nodes`/`inputs`로 정의된 연결 순서대로 모듈을 실행합니다. profile 차이는 결국 어떤 JSON을 쓰는지와 어떤 override를 주입하는지입니다.

## 그래프 / Hippo2

임베디드 Kùzu(`GraphDB/`)에 Document/Chunk/Dataset 노드 + IN_DATASET/HAS_CHUNK/NEXT/MENTIONS/SYNONYM 엣지를 투영합니다. SQLite가 source of truth, Kùzu는 derived.

- `graph_query`: 실행 전 자동 sync. `LIMIT` 미지정 시 안전 한도 부착. 파괴적 키워드(CREATE/DELETE/MERGE/SET/DROP/ALTER/REMOVE) 거부.
- `graph_rebuild`: Kùzu **COPY FROM 벌크 로더** — 청크 1만+엔티티 5천 규모도 수 초.
- Hippo2: `upload(..., pipeline="hippo2")` → `retriever/pipelines/hippo2_unified.json`의 `Hippo2Indexer` 컴포넌트가 passage embedding/Qdrant 이후 LLM OpenIE → entity/fact embeddings → entity+passage 융합 그래프를 구축. 검색은 같은 topology의 `Hippo2Retriever` 컴포넌트가 query-to-triple 매칭과 dense passage 매칭으로 entity/passage 노드를 함께 seed → scipy.sparse PPR(`data_root/ppr_matrix.npz` 캐시) → LLM 온라인 필터링 → 청크 랭킹.

## 테스트

```powershell
py -3.12 scripts_test\e2e_stdio.py                     # MCP stdio 풀 round-trip
py -3.12 scripts_test\test_json_pipeline.py            # JSON 토폴로지 정합성
py -3.12 -m unittest discover -s tests -p "test_*.py"  # 유닛
```

`e2e_stdio.py`는 임시 data_root에서 임베딩 없이 keyword-only로 전체 도구를 검증합니다.

## 파이프라인 성능 벤치마크

10개 문서 · 5개 쿼리 기준:

| 파이프라인 | 인제스트 | 검색 (평균) | 결과수 | 용도 |
|-----------|:-------:|:--------:|:----:|------|
| **keyword_only** | 0.3초 | 0.033초 | 1 | ⚡ 초저지연 (API 불필요) |
| **default** | 2.5초 | 0.029초 | 1 | ⚖️ 속도 + 정확도 균형 |
| **hippo2** | 30초 | 3.2초 | 5 | 🧠 고정확도 (엔티티 그래프) |

**선택 기준:**
- `keyword_only`: 지연 < 50ms 필수, 임베딩 API 불가
- `default`: 일반 검색 (권장)
- `hippo2`: 멀티홉 관계 필요 (배치/오프라인 용)

상세 분석: [`PERFORMANCE_BENCHMARK.md`](./PERFORMANCE_BENCHMARK.md)

## Claude 설정 예시

```json
{
  "mcpServers": {
    "retriever": {
      "command": "py",
      "args": ["-3.12", "C:\\Users\\<YOU>\\slsi-cowork-plugins\\hybrid-retriever-modular-mcp\\server.py"]
    }
  }
}
```

## 제한

- PDF/Office 파싱: `pypdf`, `python-docx`, `openpyxl`. 암호화/스캔 PDF는 OCR 필요.
- 임베딩 API: OpenAI-호환 응답(`data: [{embedding, index}]`).
- Qdrant: 임베디드 모드만, 한 프로세스 단독 접근(path-lock).
