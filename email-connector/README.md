# email-connector

PST 파일을 Outlook 없이 직접 디코딩하여 **메일 본문 + 첨부파일(PDF/DOCX) 텍스트**를 통합 마크다운으로 만들고, **SQLite FTS5(키워드) + Qdrant(의미)** 하이브리드 검색을 제공하는 Claude Code 스킬.

## 핵심 특징
- **첨부파일 본문까지 검색** — PDF는 PyMuPDF로, Word(.docx)는 python-docx로 텍스트를 추출하여 메일 본문 마크다운 뒤에 `[첨부파일: 파일명.pdf]` 구분자와 함께 병합.
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

3. 설정 파일 작성
   ```cmd
   copy config.example.json config.json
   notepad config.json
   ```
   - `embedding.endpoint`, `embedding.api_key`, `embedding.model`, `embedding.dim` 채우기
   - 필요하면 `data_root` 변경 (기본 `C:\Outlook_Data`)

## 빠른 사용

```cmd
:: PST 인제스트
python scripts\ingest.py --pst "C:\Users\me\Documents\archive.pst" --config config.json

:: 하이브리드 검색
python scripts\search.py --query "협력사 보안 점검 결과 보고서" --config config.json --top 10
```

## 저장소 구조 (기본 `C:\Outlook_Data\`)
```
Files\[Mail_ID]\body.md          # 본문 + 첨부 통합 마크다운
Files\[Mail_ID]\attachments\     # 원본 첨부파일 보관
metadata.db                      # SQLite metadata + FTS5
VectorDB\                        # Qdrant 로컬
```

## 의존성
```
pypff-python    # PST 디코딩
libratom        # PST 보조 유틸
markdownify     # HTML → 마크다운
pymupdf         # PDF 텍스트 추출
python-docx     # DOCX 텍스트 추출
qdrant-client   # Qdrant 로컬 모드
requests        # 외부 임베딩 API 호출
```

## 제한 사항
- Windows 전용. macOS/Linux/WSL에서는 pypff wheel이 없어 동작하지 않음.
- 비밀번호로 보호된 PST는 미지원.
- 첨부파일 중 PDF/DOCX만 본문 추출 대상. 그 외 형식(xlsx, pptx, zip 등)은 메타데이터만 인덱싱하고 원본은 보관.

자세한 명령은 [`SKILL.md`](./SKILL.md) 참조.
