# email-connector 셋업 가이드 (에이전트용 실행 매뉴얼)

이 문서는 사용자가 "email-connector 셋업해줘 / 설치해줘"라고 요청했을 때 **에이전트가 그대로 따라 실행**하기 위한 절차서입니다.

## 단계 마커
- **[USER]** — 에이전트는 사용자에게 안내만 하고, 완료 응답을 받기 전까지 다음 단계로 넘어가지 **않는다**. (사용자 환경에서 GUI 설치 / API 키 발급처럼 자동화할 수 없는 작업)
- **[AGENT]** — 에이전트가 직접 셸/도구 명령을 실행하고 결과를 사용자에게 보고한다.
- **[CHECK]** — 검증 단계. `ok=false`면 표시된 STEP으로 되돌아가 원인을 사용자에게 알리고 재시도.

## 일반 원칙
1. **STEP A(진단)를 항상 먼저 실행한다**. STEP 0~10은 STEP A가 가리킨 항목만 선택적으로 실행한다. 절대 STEP 0부터 처음부터 일괄 재설치하지 말 것 — 이미 깔린 패키지를 다시 깔라고 하는 건 시간 낭비이고 사용자를 화나게 한다.
2. **[AGENT]** 명령은 한 번에 하나씩 실행하고 출력을 확인한 뒤 다음으로 넘어간다 (병렬 금지). 실패 진단을 단순화하기 위함.
3. 명령이 실패하면 **추측해서 다음 단계로 진행하지 말 것**. 실패 원인을 사용자에게 보고하고 지시받는다.
4. 플랫폼은 Windows 10/11 네이티브 가정. WSL/macOS/Linux 감지 시 **즉시 중단**하고 그 사실을 사용자에게 알린다.
5. **`.env` 우선 원칙** — STEP 4(프록시) / STEP 6(.env 작성)에서 사용자에게 값을 묻기 전에, **`<skill_root>/.env`에 이미 들어있는 값이 있으면 그 값을 그대로 사용한다**. 사용자에게 "이미 .env에 있어서 재사용합니다"라고 보고하고 다시 묻지 않는다. 누락된 값(또는 placeholder인 `your_*`/`REPLACE_ME` 같은 값)만 새로 묻고, 받은 값을 .env에 기록한다.
6. 모든 Python 호출은 `py -3.9` 명시 (SKILL.md의 Runtime invocation rule 참조).

---

## STEP A. 현재 설치 상태 진단 [AGENT][CHECK] — 항상 먼저 실행

사용자가 "셋업 / 설치 / 살펴봐 / 점검 / 동작 확인" 어떤 표현으로 요청해도 **이 STEP을 가장 먼저 실행한다**.

### A-1. 부트스트랩 빠른 확인
doctor.py를 돌리려면 Python 3.9 + 스킬 폴더 + 의존성이 최소한 깔려 있어야 한다. 먼저 그것만 본다:
```cmd
py -3.9 --version
dir "%USERPROFILE%\.claude\skills\email-connector\SKILL.md"
```
- `py -3.9 --version` 실패 → STEP 2(Python 설치)부터 진행 후 A-1 재시도.
- `SKILL.md` 없음 → STEP 1(스킬 폴더 배치)부터 진행 후 A-1 재시도.
- 둘 다 OK → A-2로.

### A-2. 종합 진단
```cmd
cd /d %USERPROFILE%\.claude\skills\email-connector
py -3.9 scripts\doctor.py
```
출력은 JSON. **`all_ok: true`이면 즉시 보고 후 종료**:
> ✅ email-connector 셋업이 이미 완료되어 있습니다. 모든 검사 통과.
> 다음 명령으로 바로 사용하세요:
> ```cmd
> py -3.9 scripts\ingest.py
> py -3.9 scripts\search.py --query "..."
> ```

`all_ok: false`이면 `checks` 배열에서 `ok=false`인 항목만 추려 아래 표대로 **그 STEP만** 실행. 통과한 항목은 절대 다시 건드리지 않는다.

| 실패한 check | 실행할 STEP | 비고 |
|---|---|---|
| `platform_windows` | 중단 | WSL/Linux/macOS — 사용자에게 알리고 끝 |
| `python_3.9` / `python_64bit` | STEP 2 → A-1 | Python 재설치 |
| `dep:libpff-python` | STEP 5 | pip가 이미 설치된 것은 알아서 skip |
| `dep:*` (그 외) | STEP 5 |  |
| `env_file` | STEP 6-0 | `.env` 파일만 생성 (.env.example 복사) |
| `config` (missing values) | STEP 6-1, 6-2, 6-3 | **이미 있는 값은 재사용**, 비어 있는 키만 사용자에게 질의 |
| `pst_path` | STEP 6-2 (PST_PATH만) → STEP 7 | PST 경로 다시 묻기 (다른 .env 값은 건드리지 않기) |
| `data_root` | STEP 6-4 | mkdir만 |
| `embedding_api` (connection error / proxy) | STEP 4 | 프록시 설정 점검 |
| `embedding_api` (HTTP 401/403) | STEP 6-2 (api_key, x-dep-ticket만) |  |
| `embedding_api` (dim mismatch) | STEP 6-2 (model, dim만) |  |

### A-3. 재진단
필요한 STEP만 실행한 뒤 **반드시 doctor를 한 번 더 돌려** `all_ok: true`를 확인. 통과하면 A-2의 성공 보고로 종료. 또 실패하면 같은 매핑으로 한 번 더 시도하되 같은 항목이 계속 실패하면 **사용자에게 에러 메시지 그대로 보고**하고 더 이상 추측해서 진행하지 말 것.

## STEP 0. 플랫폼 검증 [AGENT][CHECK]

```cmd
ver
```
- 출력이 `Microsoft Windows ...`로 시작하지 않으면 중단.

WSL/Linux에서 실행되었는지도 확인:
```bash
uname -a 2>/dev/null || true
```
- 출력에 `Microsoft` 또는 `WSL` 또는 `Linux`가 보이면 즉시 중단하고 사용자에게 "이 스킬은 Windows 네이티브에서만 동작합니다"라고 보고.

## STEP 1. 스킬 폴더 위치 확인 [AGENT][CHECK]

```cmd
dir "%USERPROFILE%\.claude\skills\email-connector\SKILL.md"
```
- 파일이 없으면 사용자에게 다음을 안내 [USER]:
  > 이 스킬 폴더가 `%USERPROFILE%\.claude\skills\email-connector\` 아래에 있어야 합니다.
  > 다음 명령으로 복사해 주세요:
  > ```cmd
  > git clone https://github.com/joungwoo-lee/slsi-cowork-plugins %TEMP%\slsi-plugins
  > xcopy /E /I /Y %TEMP%\slsi-plugins\email-connector %USERPROFILE%\.claude\skills\email-connector
  > ```
- 복사 완료를 사용자가 확인하면 다시 STEP 1 검증부터.

## STEP 2. Python 3.9 설치 [USER]

다음 안내를 그대로 사용자에게 전달:

> **Python 3.9.13 (64-bit)** 가 필요합니다. (3.10+ 사용 금지 — `libpff-python` 휠이 3.9 전용)
>
> 1. 다음 직접 다운로드 링크에서 설치 파일 받기:
>    **https://www.python.org/ftp/python/3.9.13/python-3.9.13-amd64.exe**
> 2. 다운받은 `python-3.9.13-amd64.exe` 실행
> 3. 설치 마법사에서 **"Add python.exe to PATH"** 반드시 체크
> 4. **Install Now** 클릭
> 5. 설치 완료되면 "설치 끝났어" 라고 알려주세요.

> 사내망 등으로 위 URL이 막혀 있으면 사용자에게 그 사실을 보고하고, 사내 소프트웨어 포털에서 동일 버전(Python 3.9.13 64-bit)을 받을 수 있는지 문의하도록 안내한다.

사용자가 완료를 알리기 전에는 STEP 3 진행 금지.

## STEP 3. Python 검증 [AGENT][CHECK]

```cmd
py -3.9 --version
py -3.9 -c "import struct,sys;print(struct.calcsize('P')*8, sys.executable)"
```
- 첫 줄이 `Python 3.9.`로 시작하지 않으면 → STEP 2 재시도 안내.
- 두 번째 출력의 비트수가 `64`가 아니면 32-bit이므로 64-bit 재설치 요청.

## STEP 4. 프록시 설정 (사내망인 경우만) [USER + AGENT]

### 4-0. .env에 이미 값이 있는지 확인 [AGENT]
`<skill_root>/.env`가 존재하면 Read 도구로 읽어 `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` 값을 확인.
- 모두 비어 있으면 4-1로 진행.
- 이미 채워져 있으면 사용자에게 "이미 .env에 프록시 설정이 있습니다: HTTP_PROXY=..., NO_PROXY=... — 이 값을 그대로 쓸까요? 아니면 변경?" 물어 확인. 그대로 쓰면 4-2로 건너뜀.

### 4-1. 프록시 정보 수집 [USER]
> 사내망/프록시 환경에서 작업하시나요? 그렇다면 다음을 알려주세요:
> 1. **프록시 URL** (예: `http://proxy.company.com:8080`, 인증이 필요하면 `http://user:pass@proxy.company.com:8080`)
> 2. **NO_PROXY** 대상 (프록시를 우회해야 하는 호스트들 — 보통 사내 임베딩 API 호스트, `localhost`, `127.0.0.1`, 사내 도메인)
>
> 직접 인터넷 접근이 가능한 환경이면 "프록시 없음"이라고 답해주세요.

"프록시 없음"이면 `HTTP_PROXY=""` / `HTTPS_PROXY=""` / `NO_PROXY="localhost,127.0.0.1"` 로 처리하고 4-3로.

### 4-2. 셸 환경변수 설정 (현재 세션 + 영구) [AGENT]
pip와 Python 프로세스(`requests`/`urllib`) 모두 이 변수를 따른다. .env에 적힌 값이 있어도 셸 측에 set/setx로 같이 넣어야 STEP 5의 pip가 즉시 프록시를 탄다.
```cmd
set HTTP_PROXY=<proxy_url>
set HTTPS_PROXY=<proxy_url>
set NO_PROXY=<no_proxy_list>

setx HTTP_PROXY "<proxy_url>"
setx HTTPS_PROXY "<proxy_url>"
setx NO_PROXY "<no_proxy_list>"
```
> `setx`는 영구 저장이지만 **현재 세션에는 반영되지 않으므로** 위처럼 `set`도 함께 실행해야 한다.

### 4-3. .env에 기록 [AGENT]
`<skill_root>/.env` (없으면 `.env.example`을 복사하여 생성)에 다음 키를 갱신:
```
HTTP_PROXY=<proxy_url 또는 빈 값>
HTTPS_PROXY=<proxy_url 또는 빈 값>
NO_PROXY=<no_proxy_list>
```
이렇게 .env에 적어두면 STEP 9 doctor가 fresh shell에서 실행돼도 동일 프록시를 사용한다.

### 4-4. pip 전용 추가 설정 (선택, MITM 인증서 환경)
`SSL: CERTIFICATE_VERIFY_FAILED`가 발생하면 `%APPDATA%\pip\pip.ini`:
```ini
[global]
proxy = <proxy_url>
trusted-host =
    pypi.org
    files.pythonhosted.org
    pypi.python.org
```

### 4-5. NO_PROXY 작성 시 주의
- 임베딩 endpoint가 사내 호스트라면 **반드시 NO_PROXY에 그 호스트를 추가**해야 한다. 그렇지 않으면 STEP 9 doctor가 사내 endpoint를 외부 프록시로 보내 실패한다.
- 외부 endpoint(예: `api.openai.com`)면 NO_PROXY에 넣지 말 것.
- 도메인 와일드카드는 점 prefix로: `.company.com`.

### 4-6. 검증 [CHECK]
```cmd
echo %HTTP_PROXY%
echo %NO_PROXY%
py -3.9 -c "import os; print({k:os.environ.get(k) for k in ('HTTP_PROXY','HTTPS_PROXY','NO_PROXY')})"
```
빈 값이면 4-2 재실행 (`set` 누락).

## STEP 5. 의존성 설치 [AGENT]

```cmd
cd /d %USERPROFILE%\.claude\skills\email-connector
py -3.9 -m pip install --upgrade pip
py -3.9 -m pip install -r requirements.txt
```
- pip 종료코드가 0이 아니면 stderr 마지막 30줄을 사용자에게 그대로 보고.
- 자주 발생하는 실패와 대응:
  - `Could not find a version that satisfies the requirement pypff-python` → 옛 잘못된 이름. PyPI에는 `libpff-python`만 존재. requirements.txt가 `libpff-python==20211114`로 되어 있는지 확인.
  - `ERROR: Could not build wheels for libpff-python` 또는 `Microsoft Visual C++ 14.0 or greater is required` → Python이 3.9 64-bit가 아닌 것. STEP 3으로 회귀.
  - `No matching distribution found for libpff-python==20211114` → `py -3.9 -m pip install --upgrade pip` 후 재시도.
  - `SSL: CERTIFICATE_VERIFY_FAILED` / `ProxyError` / `Cannot connect to proxy` → STEP 4로 회귀.

## STEP 6. .env 작성 [USER + AGENT][CHECK]

이 STEP에서 모든 런타임 값을 `<skill_root>/.env`에 기록한다. 변수명은 `retriever_engine` 프로젝트와 호환된다 (`EMBEDDING_API_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_API_X_DEP_TICKET` 등).

### 6-0. .env 파일 준비 [AGENT]
```cmd
cd /d %USERPROFILE%\.claude\skills\email-connector
if not exist .env copy .env.example .env
```

### 6-1. 기존 값 로드 [AGENT]
Read 도구로 `.env` 내용을 읽고, 다음 키가 비어 있는지 / placeholder(`your_*`, `REPLACE_ME`, `C:\Users\me\...`)인지 판정:
- `PST_PATH`
- `EMBEDDING_API_URL`
- `EMBEDDING_API_KEY`
- `EMBEDDING_MODEL`
- `EMBEDDING_DIM`
- `EMBEDDING_API_X_DEP_TICKET` (비어도 OK — 사내 인증 필요 없으면 빈 값 유지)
- `EMBEDDING_API_X_SYSTEM_NAME` (디폴트 `email-connector`로 OK)
- `EMBEDDING_VERIFY_SSL` (디폴트 `false`로 OK)
- `DATA_ROOT` (디폴트 `C:\Outlook_Data`로 OK)

이미 실제값(placeholder 아님)이 있는 키는 사용자에게 "이미 .env에 있습니다: KEY=값" 알리고 **다시 묻지 않는다**.

### 6-2. 누락된 값 [USER]
누락/placeholder인 키들을 한 번에 묶어 사용자에게 묻는다:

> 다음 값을 알려주세요 (이미 .env에 있는 항목은 생략됨):
> 1. **PST_PATH** — 인덱싱할 PST 파일의 절대경로 (예: `C:\Users\me\Documents\archive.pst`)
> 2. **EMBEDDING_API_URL** — 임베딩 API 엔드포인트 (예: `http://localhost:8080/v1/embeddings`)
> 3. **EMBEDDING_API_KEY** — 임베딩 API 키
> 4. **EMBEDDING_MODEL** — 모델명 (예: `BAAI/bge-m3`, `text-embedding-3-small`)
> 5. **EMBEDDING_DIM** — 모델 실제 벡터 차원 (정수). bge-m3=1024, 3-small=1536, 3-large=3072
> 6. **EMBEDDING_API_X_DEP_TICKET** — 사내 인증 헤더 `x-dep-ticket` 값. 필요 없으면 "없음"
>
> SSL 인증서 검증은 기본 `false`(MITM 환경 대응). 외부 공인 CA endpoint(예: `api.openai.com`) + 엄격 검증을 원하면 알려주세요.

`EMBEDDING_DIM`은 모델의 실제 차원과 정확히 일치해야 함을 강조.

### 6-3. .env에 기록 [AGENT]
Edit 도구로 `.env`의 각 라인을 받은 값으로 교체. placeholder 패턴(`your_*`, `REPLACE_ME`)은 모두 사라져야 한다. 마지막에 Read 도구로 다시 읽어 시각적 재확인.

### 6-4. 데이터 경로 생성 [AGENT]
`.env`의 `DATA_ROOT` 값에 따라:
```cmd
mkdir <DATA_ROOT> 2>nul
mkdir <DATA_ROOT>\Files 2>nul
mkdir <DATA_ROOT>\VectorDB 2>nul
```

## STEP 7. PST 파일 접근 검증 [AGENT][CHECK]

`.env`의 `PST_PATH`가 실제로 존재하고 읽을 수 있는지 확인:
```cmd
dir "<PST_PATH>"
```
- 파일이 없으면 STEP 6-2의 PST_PATH 재질문 (경로 오타 가능성).
- 권한 거부면 사용자에게 PST 파일 위치 권한 확인 요청.

## STEP 8. 종합 진단 [AGENT][CHECK]

```cmd
py -3.9 scripts\doctor.py
```
출력은 JSON. `all_ok: true`면 셋업 성공.

`ok: false`인 항목별 회귀 매핑:
| 실패 항목 | 회귀 STEP |
|---|---|
| `python_3.9` / `python_64bit` | STEP 2 |
| `dep:*` | STEP 5 |
| `env_file` | STEP 6-0 |
| `config` (missing values) | STEP 6-2 |
| `pst_path` | STEP 6-2 (PST_PATH) / STEP 7 |
| `data_root` | STEP 6-4 (또는 권한 문제 안내) |
| `embedding_api` (HTTP/connection error) | STEP 4 (프록시 / NO_PROXY 재확인) |
| `embedding_api` (HTTP 401/403) | STEP 6-2 (`EMBEDDING_API_KEY` 또는 `x-dep-ticket`) |
| `embedding_api` (dim mismatch) | STEP 6-2 (`EMBEDDING_MODEL` / `EMBEDDING_DIM`) |

`embedding_api`는 실제 API에 짧은 핑 요청을 보내므로 약간의 토큰 비용이 발생할 수 있음을 사용자에게 사전 고지.

## STEP 9. 스모크 테스트 [AGENT] (선택)

`.env`의 `PST_PATH`가 STEP 8까지 통과했으므로 별도 인자 없이 실행 가능. Phase별 분리 검증:

### 9-1. Phase 1 (변환만)
```cmd
py -3.9 scripts\convert.py --limit 5
```
출력 `{"converted": N, ...}` (N>=1)이면 성공. `<DATA_ROOT>\Files\` 아래 메일별 폴더에 `body.md` + `meta.json` + `attachments\` 가 보여야 함.

### 9-2. Phase 2 (인덱싱만, FTS5만)
```cmd
py -3.9 scripts\index.py --skip-embedding
```
출력 `{"indexed": N, ...}`. SQLite FTS5에만 적재.

### 9-3. 검색
```cmd
py -3.9 scripts\search.py --query "테스트" --mode keyword --top 3
```
JSON 배열 반환되면 성공.

### 9-4. (선택) 임베딩 포함
```cmd
py -3.9 scripts\index.py
py -3.9 scripts\search.py --query "테스트" --mode hybrid --top 3
```
임베딩 API + Qdrant까지 동작하면 hybrid 결과 반환.

## 셋업 종료 보고

- ✅/❌ 각 STEP 결과
- 생성된 파일 경로 (`<skill_root>\.env`, `<DATA_ROOT>\` 등)
- 다음에 사용자가 실행할 한 줄 명령:
  ```cmd
  py -3.9 scripts\ingest.py
  ```
  (`PST_PATH`가 .env에 있으므로 인자 불필요)
