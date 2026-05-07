# email-connector

PST 파일을 Outlook 없이 직접 디코딩하여 **메일 본문 + 첨부파일(PDF/DOCX) 텍스트**를 통합 마크다운으로 만들고, **SQLite FTS5(키워드) + Qdrant(의미)** 하이브리드 검색을 제공하는 Claude Code 스킬.

## 핵심 특징
- **첨부파일 본문까지 검색** — 메일 본문 + 모든 첨부파일 텍스트를 하나의 `body.md`로 통합. 첨부 안 단어로 매칭돼도 메일 단위 결과로 반환되며, 통합 마크다운에 본문과 첨부 내용이 모두 들어 있어 한 파일만 읽으면 풀 컨텍스트 확보.
- **첨부 변환 형식**: `.pdf` (PyMuPDF), `.docx` (python-docx), `.xlsx` (openpyxl, 시트별 표), `.pptx` (python-pptx, 슬라이드+노트), `.rtf` (striprtf), `.html`/`.htm` (markdownify), 텍스트 계열(`.txt`/`.csv`/`.tsv`/`.log`/`.md`/`.json`/`.xml`/`.yaml`/`.ini`/`.sql`/`.py`/`.js`/`.ts`/`.sh`/`.bat`/`.ps1`). 이미지(`.jpg`/`.png` 등)와 미지원 형식은 한 줄 스텁으로 표기 + 원본 파일은 `attachments/`에 보관.
- **2-Track 검색** — 정확한 단어(품번, 계약번호 등)는 SQLite FTS5, 의미적 질의는 Qdrant 로컬 컬렉션.
- **Windows 네이티브 + Python 3.9** — pypff 등 prebuilt wheel 사용. C++ Build Tools 불필요.
- **로컬 임베딩 연산 없음** — 외부 API endpoint 호출로 Dense Vector 획득.

## 설치

1. 이 폴더를 Windows의 Claude 스킬 디렉토리로 복사
   ```
   %USERPROFILE%\.claude\skills\email-connector\
   ```

2. Python 3.9 + 의존성 설치
   ```cmd
   pip install -r requirements.txt
   ```

3. 설정 파일 작성 — **`.env` 사용**
   ```cmd
   copy .env.example .env
   notepad .env
   ```
   변수명은 `retriever_engine` 프로젝트와 호환:
   - `PST_PATH` — 인덱싱할 PST 절대경로
   - `EMBEDDING_API_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` / `EMBEDDING_DIM`
   - `EMBEDDING_API_X_DEP_TICKET` — 사내 인증 헤더 `x-dep-ticket` 값 (필요 없으면 비워두기)
   - `EMBEDDING_API_X_SYSTEM_NAME` — `x-system-name` 헤더 (기본 `email-connector`)
   - `EMBEDDING_VERIFY_SSL` — 기본 `false` (사내 MITM 환경 대응)
   - `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` — 사내 프록시
   - `DATA_ROOT` — 데이터 저장 루트 (기본 `C:\Outlook_Data`)

## 빠른 사용

파이프라인은 **변환(Phase 1)** 과 **인덱싱(Phase 2)** 으로 나뉘어 있습니다. 각 단계 단독 실행, 연속 실행 모두 지원. PST 경로는 `.env`의 `PST_PATH`에서 자동으로 읽으므로 인자 생략 가능.

> ⚠️ **반드시 `py -3.9`로 실행**. bare `python`/`python3`/`py`는 다른 인터프리터를 잡아 ImportError 또는 RuntimeError로 떨어집니다 (libpff-python wheel은 cp39-win_amd64 전용).

```cmd
:: ① 한 번에 (변환 + 인덱싱) — .env의 PST_PATH 사용
py -3.9 scripts\ingest.py

:: ② 변환만 (PST → body.md + 원본 확장자 첨부파일 + meta.json)
py -3.9 scripts\convert.py
py -3.9 scripts\convert.py --pst "C:\다른경로\archive.pst"   :: .env 무시하고 명시적 경로

:: ③ 변환된 파일들을 인덱싱만 (PST 다시 안 읽음)
py -3.9 scripts\index.py
py -3.9 scripts\index.py --skip-embedding   :: FTS5만, 임베딩 생략

:: 하이브리드 검색
py -3.9 scripts\search.py --query "협력사 보안 점검 결과 보고서" --top 10
```

### Phase 분리의 이점
- 변환 결과(`body.md`/원본 첨부)를 **사람이 직접 열어 검수** 가능. 검색 인덱스가 빠진 상태에서도 마크다운 자체로 활용.
- 임베딩 모델/dim을 바꿀 때 PST 재디코딩 없이 **Phase 2만 재실행**.
- 일부 메일만 재인덱싱: `py -3.9 scripts\index.py --mail-id <id1> --mail-id <id2>`.

## 임베딩 API 호출 방식
`retriever_engine/api/modules/retrieval/engine.py:embed_texts`와 동일한 헤더/페이로드:
```http
POST <EMBEDDING_API_URL>
Content-Type: application/json
Authorization: Bearer <EMBEDDING_API_KEY>
x-dep-ticket: <EMBEDDING_API_X_DEP_TICKET>
x-system-name: <EMBEDDING_API_X_SYSTEM_NAME>

{"model": "<EMBEDDING_MODEL>", "input": [<text>, ...]}
```
응답 파싱은 OpenAI 호환 (`data[i].embedding`)과 raw 형태(`embeddings`) 양쪽 모두 처리.

## 저장소 구조 (기본 `C:\Outlook_Data\`)
```
Files\[Mail_ID]\body.md          # 본문 + 첨부 통합 마크다운
Files\[Mail_ID]\attachments\     # 원본 첨부파일 보관
metadata.db                      # SQLite metadata + FTS5
VectorDB\                        # Qdrant 로컬
```

## 의존성
```
libpff-python==20211114   # PST 디코딩 (모듈 import는 pypff). 이 버전만 Windows wheel 제공.
markdownify               # HTML 본문 → 마크다운
striprtf                  # RTF 본문 / .rtf 첨부 (순수 Python)
pymupdf                   # .pdf 첨부
python-docx               # .docx 첨부
openpyxl                  # .xlsx 첨부 (순수 Python)
python-pptx               # .pptx 첨부 (순수 Python)
qdrant-client==1.7.0      # 임베디드 모드 (별도 서버 불필요)
requests                  # 외부 임베딩 API 호출
python-dotenv             # .env 로더
```

> ⚠️ **`pypff-python`이라는 이름은 PyPI에 없습니다.** 정확한 패키지명은 `libpff-python`. 그리고 최신 버전(20231205)은 macOS wheel만 제공하므로 Windows에서는 반드시 `==20211114`로 버전을 못박아야 prebuilt wheel(`cp39-win_amd64`)로 깔립니다. 다른 Python 버전을 쓰면 wheel이 없어 sdist로 떨어지고 C 빌드를 시도하므로 실패합니다 — Python 3.9 64-bit 필수.

## 제한 사항
- Windows 전용. macOS/Linux/WSL에서는 pypff wheel이 없어 동작하지 않음.
- 비밀번호로 보호된 PST는 미지원.
- 첨부파일 본문 추출 대상: PDF, DOCX, XLSX, PPTX, RTF, HTML, 텍스트 계열. 레거시 OLE 형식(`.doc`/`.xls`/`.ppt`)과 `.msg`/`.eml`/`.zip`/이미지 등은 원본만 `attachments/`에 보관하고 `body.md`에는 한 줄 스텁만 표기 (검색 인덱스에 파일명·확장자 정도는 포함).
- 이미지 OCR 미지원 (의도적; tesseract 의존성 추가 부담).

자세한 명령은 [`SKILL.md`](./SKILL.md) 참조.
