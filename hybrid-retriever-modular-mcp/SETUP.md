# retriever-mcp 셋업 가이드

`retriever-mcp` 를 Claude Desktop / Claude Code 에 연결하는 절차서. 에이전트가 그대로 따라 실행할 수 있게 단계 마커(`[USER]` / `[AGENT]` / `[CHECK]`)를 사용한다.

> **TL;DR**: `hybrid_retriever_windows_local` 의 retriever_engine 이 떠 있고 → claude config 에 항목 추가하고 → 재시작.

## 단계 마커
- **[USER]** — 사용자가 직접 해야 함. 완료 응답을 받기 전엔 다음 STEP 진행 금지.
- **[AGENT]** — 에이전트가 명령을 실행하고 결과를 보고.
- **[CHECK]** — 검증. 실패 시 표시된 STEP 으로 회귀.

## 일반 원칙
1. **retriever_engine 이 선행**되어야 한다. `health` 도구가 `degraded` 만 떠도 일단 통과로 본다 (외부 임베딩 API 가 죽어 있을 수 있어도 키워드 검색은 살아 있을 수 있음).
2. retriever-mcp 자체는 의존성이 없다. `pip install` 단계가 없다.

---

## STEP 1. retriever_engine 동작 확인 [USER + AGENT][CHECK]

```cmd
curl http://127.0.0.1:9380/health
```

- `{"status":"healthy",...}` → STEP 2.
- 연결 거부됨 → retriever_engine 을 먼저 띄운다:
  ```powershell
  cd <hybrid_retriever_windows_local>\retriever_engine
  .\.venv\Scripts\Activate.ps1
  .\scripts\start_windows.ps1
  ```
- 다른 포트 / 호스트면 그 주소를 메모해서 STEP 3 의 `RETRIEVER_BASE_URL` 에 반영.

## STEP 2. retriever-mcp 폴더 배치 [USER][CHECK]

권장 배치 (email-mcp 와 sibling):
```
%USERPROFILE%\.claude\skills\
├── email-mcp\
└── retriever-mcp\          (이번에 추가)
    ├── server.py
    ├── README.md
    ├── SETUP.md
    ├── claude_desktop_config.example.json
    └── mcp_server\
        ├── __init__.py
        ├── bootstrap.py
        ├── protocol.py
        ├── runtime.py
        ├── catalog.py
        ├── handlers.py
        └── dispatch.py
```

복사 명령 예시:
```cmd
git clone https://github.com/joungwoo-lee/slsi-cowork-plugins %TEMP%\slsi-plugins
xcopy /E /I /Y %TEMP%\slsi-plugins\retriever-mcp %USERPROFILE%\.claude\skills\retriever-mcp
```

## STEP 3. 서버 단독 기동 테스트 [AGENT][CHECK]

JSON-RPC `initialize` 한 번을 보내 `serverInfo` 가 돌아오는지 확인한다.

```cmd
cd /d %USERPROFILE%\.claude\skills\retriever-mcp
echo {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual","version":"0"}}} | py -3 server.py
```

기대 출력 (한 줄, stdout):
```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{"listChanged":false}},"serverInfo":{"name":"retriever-mcp","version":"0.1.0"}}}
```

stderr 에는 `[retriever-mcp] starting ... (base_url=http://127.0.0.1:9380, ...)` 한 줄.

## STEP 4. Claude Desktop 연결 [USER + AGENT]

### 4-1. 설정 파일 위치
```cmd
dir "%APPDATA%\Claude\claude_desktop_config.json"
```

### 4-2. 설정 작성 [AGENT]
`claude_desktop_config.example.json` 을 참고:
```json
{
  "mcpServers": {
    "retriever": {
      "command": "py",
      "args": [
        "-3",
        "C:\\Users\\<YOU>\\.claude\\skills\\retriever-mcp\\server.py"
      ],
      "env": {
        "RETRIEVER_BASE_URL": "http://127.0.0.1:9380",
        "RETRIEVER_API_KEY": "ragflow-key",
        "RETRIEVER_DEFAULT_DATASETS": "my_docs"
      }
    }
  }
}
```

> JSON 안 백슬래시는 반드시 `\\` 로 두 번. 한 번이면 파싱 에러.

### 4-3. Claude Desktop 재시작 [USER]
설정 파일 변경은 재시작 후에만 반영.

### 4-4. 도구 노출 검증 [USER][CHECK]
도구 아이콘에서 `retriever` 서버의 도구 13개가 보이면 성공:
- 검색: `search`
- 데이터셋: `list_datasets`, `get_dataset`, `create_dataset`, `delete_dataset`
- 문서: `upload_document`, `list_documents`, `get_document`, `list_chunks`, `get_document_content`, `delete_document`
- 운영: `list_pipelines`, `health`

도구가 안 보이면 `%APPDATA%\Claude\logs\mcp-server-retriever.log` 확인.

## STEP 5. Claude Code 연결 (선택) [AGENT]

```cmd
claude mcp add retriever py -3 %USERPROFILE%\.claude\skills\retriever-mcp\server.py ^
  --env RETRIEVER_BASE_URL=http://127.0.0.1:9380 ^
  --env RETRIEVER_API_KEY=ragflow-key ^
  --env RETRIEVER_DEFAULT_DATASETS=my_docs
claude mcp list
```

또는 폴더에 들어 있는 `claude-mcp-add-retriever.bat` 더블클릭.

## STEP 6. 도구 스모크 테스트 [AGENT][CHECK]

1. **health**: "retriever health 도구로 진단해줘"
   → `keyword: ok`, `qdrant: ok` 확인.
2. **list_datasets**: "어떤 데이터셋이 있어?"
   → `datasets` 배열에 알려진 dataset 보임.
3. **upload_document** (선택): "이 파일을 my_docs 에 올려줘 — file_path: C:\\Users\\me\\Desktop\\test.md"
   → `response.chunks_count` > 0 이면 성공.
4. **search**: "my_docs 에서 'XX' 검색해줘 (top_n=5)"
   → `contexts` 배열에 텍스트 + similarity 포함.
5. **get_document_content**: 위 결과의 `document_id` 로 원본 조회.

## 셋업 종료 보고
- ✅/❌ 각 STEP 결과
- Claude Desktop / Code 어느 쪽에 연결했는지
- 다음 사용 예시:
  > "내 문서에서 작년 보안 보고서 찾아줘" → retriever-mcp.search 자동 호출
