# hybrid-retriever-modular-mcp 셋업

## 1. 의존성 설치

```powershell
py -3 -m pip install -r requirements.txt
Copy-Item .env.example .env
```

## 2. 환경 설정

`.env` 또는 MCP env에 다음을 설정합니다.

```env
RETRIEVER_DATA_ROOT=C:\Retriever_Data
RETRIEVER_DEFAULT_DATASETS=my_docs
```

임베딩 API 설정은 선택입니다. 설정하지 않으면 키워드 검색만 동작합니다.

## 3. MCP 단독 확인

```powershell
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual","version":"0"}}}' | py -3 server.py
```

## 4. Claude 연결

`claude_desktop_config.example.json`을 참고해 Claude 설정에 추가합니다.

## 5. 스모크 테스트

1. `health`로 로컬 DB 상태 확인
2. `create_dataset`로 `my_docs` 생성
3. `upload_document`로 텍스트 파일 업로드
4. `search`로 검색 확인
