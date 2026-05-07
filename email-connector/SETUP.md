# email-connector 셋업 가이드 (에이전트용 실행 매뉴얼)

이 문서는 사용자가 "email-connector 셋업해줘 / 설치해줘"라고 요청했을 때 **에이전트가 그대로 따라 실행**하기 위한 절차서입니다.

## 단계 마커
- **[USER]** — 에이전트는 사용자에게 안내만 하고, 완료 응답을 받기 전까지 다음 단계로 넘어가지 **않는다**. (사용자 환경에서 GUI 설치 / API 키 발급처럼 자동화할 수 없는 작업)
- **[AGENT]** — 에이전트가 직접 셸/도구 명령을 실행하고 결과를 사용자에게 보고한다.
- **[CHECK]** — 검증 단계. `ok=false`면 표시된 STEP으로 되돌아가 원인을 사용자에게 알리고 재시도.

## 일반 원칙
1. STEP을 건너뛰지 않는다. 순서대로 진행.
2. **[AGENT]** 명령은 한 번에 하나씩 실행하고 출력을 확인한 뒤 다음으로 넘어간다 (병렬 금지). 실패 진단을 단순화하기 위함.
3. 명령이 실패하면 **추측해서 다음 단계로 진행하지 말 것**. 실패 원인을 사용자에게 보고하고 지시받는다.
4. 플랫폼은 Windows 10/11 네이티브 가정. WSL/macOS/Linux 감지 시 **즉시 중단**하고 그 사실을 사용자에게 알린다.

---

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

> **Python 3.9.x (64-bit)** 가 필요합니다. (3.10+ 사용 금지 — `pypff` 휠이 3.9 전용)
>
> 1. https://www.python.org/downloads/release/python-3913/ 접속
> 2. 페이지 하단의 **Windows installer (64-bit)** 다운로드
> 3. 설치 마법사에서 **"Add python.exe to PATH"** 반드시 체크
> 4. 설치 완료되면 "설치 끝났어" 라고 알려주세요.

사용자가 완료를 알리기 전에는 STEP 3 진행 금지.

## STEP 3. Python 검증 [AGENT][CHECK]

```cmd
py -3.9 --version
py -3.9 -c "import struct,sys;print(struct.calcsize('P')*8, sys.executable)"
```
- 첫 줄이 `Python 3.9.`로 시작하지 않으면 → STEP 2 재시도 안내.
- 두 번째 출력의 비트수가 `64`가 아니면 32-bit이므로 64-bit 재설치 요청.

## STEP 4. 의존성 설치 [AGENT]

```cmd
cd /d %USERPROFILE%\.claude\skills\email-connector
py -3.9 -m pip install --upgrade pip
py -3.9 -m pip install -r requirements.txt
```
- pip 종료코드가 0이 아니면 stderr 마지막 30줄을 사용자에게 그대로 보고.
- 자주 발생하는 실패와 대응:
  - `Could not find a version that satisfies the requirement pypff-python` → 옛 잘못된 이름. PyPI에는 `libpff-python`만 존재. requirements.txt가 `libpff-python==20211114`로 되어 있는지 확인.
  - `ERROR: Could not build wheels for libpff-python` 또는 `Microsoft Visual C++ 14.0 or greater is required` → Python이 3.9 64-bit가 아닌 것. `libpff-python`은 `20211114` 버전에서만 `cp39-win_amd64` wheel을 제공하므로 Python 3.9 64-bit 외 환경에서는 sdist로 떨어져 C 빌드를 시도한다. STEP 3로 회귀.
  - `No matching distribution found for libpff-python==20211114` → pip가 매우 오래되어 wheel 태그 호환성 판정 실패 가능. `py -3.9 -m pip install --upgrade pip` 재실행 후 STEP 4 재시도.
  - 사내망 인증서/프록시 문제(`SSL: CERTIFICATE_VERIFY_FAILED`) → 사용자에게 사내 pip 인덱스 / 프록시 설정 필요 여부 질문.

## STEP 5. 임베딩 API 정보 수집 [USER]

다음 4가지를 사용자에게 묻는다 (한 번에 묶어 질문):
1. **endpoint** URL — 예: `https://api.openai.com/v1/embeddings` 또는 사내 게이트웨이 URL
2. **api_key**
3. **model** — 예: `text-embedding-3-small`
4. **dim** (벡터 차원, 정수) — 예: `1536` (3-small) / `3072` (3-large)

dim은 모델 실제 차원과 정확히 일치해야 한다고 사용자에게 강조.

## STEP 6. config.json 작성 [AGENT]

```cmd
cd /d %USERPROFILE%\.claude\skills\email-connector
copy /Y config.example.json config.json
```
그 후 에이전트가 `Edit` 도구로 `config.json`의 `embedding` 블록 4개 필드를 STEP 5에서 받은 값으로 교체.
`api_key`가 `REPLACE_ME`로 남아 있지 않은지 시각적으로 재확인.

## STEP 7. 데이터 경로 생성 [AGENT]

config의 `data_root` 기본값 기준 (`C:\Outlook_Data`):
```cmd
mkdir C:\Outlook_Data 2>nul
mkdir C:\Outlook_Data\Files 2>nul
mkdir C:\Outlook_Data\VectorDB 2>nul
```
사용자가 `data_root`를 다른 경로로 바꿨으면 그 경로로 적용.

## STEP 8. 종합 진단 [AGENT][CHECK]

```cmd
py -3.9 scripts\doctor.py --config config.json
```
출력은 JSON. `all_ok: true`면 셋업 성공.

`ok: false`인 항목별 회귀 매핑:
| 실패 항목 | 회귀 STEP |
|---|---|
| `python_3.9` / `python_64bit` | STEP 2 |
| `dep:*` | STEP 4 |
| `config` | STEP 5–6 |
| `data_root` | STEP 7 (또는 권한 문제 안내) |
| `embedding_api` | STEP 5 (endpoint/key/model/dim 재확인) |

`embedding_api`는 실제 API에 짧은 핑 요청을 보내므로 약간의 토큰 비용이 발생할 수 있음을 사용자에게 사전 고지.

## STEP 9. 스모크 테스트 [USER + AGENT] (선택)

[USER]
> 테스트용 .pst 파일이 있으면 절대경로를 알려주세요. 없으면 "건너뛰기"라고 답해주세요.

경로를 받으면 [AGENT]:
```cmd
py -3.9 scripts\ingest.py --pst "<사용자_경로>" --config config.json --limit 5 --skip-embedding
py -3.9 scripts\search.py --query "테스트" --config config.json --mode keyword --top 3
```
- ingest 출력에 `done. ingested=N` (N>=1) 보이고
- search가 JSON 배열을 반환하면 성공.

## 셋업 종료 보고

다음을 한 번에 사용자에게 요약:
- ✅/❌ 각 STEP 결과
- 생성된 파일 경로 (`config.json`, `C:\Outlook_Data\` 등)
- 다음에 사용자가 실행할 한 줄 명령:
  ```cmd
  py -3.9 scripts\ingest.py --pst "본인_PST_경로" --config config.json
  ```
