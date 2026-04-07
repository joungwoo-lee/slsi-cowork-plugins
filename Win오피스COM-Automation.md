# [요구사항 및 설계 명세서] Windows Native 오피스 COM 객체 자동화(COM Automation) 기반 범용 DRM 문서 읽기 전용(Read-Only) CLI 툴 및 에이전트 스킬
## 1. 프로젝트 개요
 * **목표**: WSL이 없는 순수 Windows 환경에서 동작하며, 사내 DRM이 적용된 MS Office 문서(.docx, .xlsx, .pptx)를 **실제 백그라운드 오피스 프로세스를 띄우는 'COM 객체 자동화(COM Automation)' 방식**을 통해 열고, 문서의 내용과 구조를 텍스트/마크다운 형태로 완벽하게 추출하는 단일 실행 파일(Single Binary) CLI 툴과 에이전트 스킬을 개발한다.
 * **핵심 포커스**: 편집 기능은 일절 구현하지 않는다. 오버헤드가 큰 COM Interop 제어 방식의 단점을 극복하기 위해, **버전 종속성이 없는 NetOffice 라이브러리를 활용**하며, **DRM 딜레이 극복, 팝업/Hang 방지, 완벽한 프로세스 종료(메모리 누수 방지)** 에 모든 엔지니어링 역량을 집중한다.
## 2. 시스템 아키텍처
 1. **LLM / 에이전트**: 사용자의 문서 분석 요청을 받아 에이전트 스킬(Tool)을 호출.
 2. **에이전트 스킬 (Python/Node.js)**: 타겟 파일 경로를 인자로 전달하여 단일 바이너리 CLI를 서브프로세스로 실행.
 3. **단일 바이너리 CLI (C# .NET)**: 확장자를 판별하여 적절한 Office 프로그램(Word, Excel, PPT)을 NetOffice를 통해 백그라운드 호출. DRM 복호화 대기 후 텍스트를 추출하여 표준 출력(stdout)으로 반환.
## 3. 컴포넌트 1: 단일 바이너리 CLI 툴 설계 (C# .NET)
### 3.1. 개발 환경 및 빌드 설정
 * **언어/프레임워크**: C# / .NET 8 (또는 최신 버전) Console Application.
 * **핵심 라이브러리 (필수)**: 마이크로소프트 공식 Interop 대신, 오피스 버전 충돌을 방지하는 **NetOfficeFw.WordApi, NetOfficeFw.ExcelApi, NetOfficeFw.PowerPointApi** (NuGet 패키지)를 사용한다.
 * **빌드 조건**: 실행 환경에 .NET 런타임이 없어도 동작하도록 단일 파일로 빌드 (<PublishSingleFile>true</PublishSingleFile>).
### 3.2. CLI 입출력(I/O) 규격
 * **입력 방식**: Command Line Arguments (명령줄 인수)
 * **출력 방식**:
   * 추출 완료된 텍스트(Markdown 형식 권장)는 **표준 출력(stdout)** 으로 반환.
   * 에러 메시지나 진행 로그(디버깅용)는 반드시 **표준 에러(stderr)** 로 분리하여 에이전트의 파싱을 방해하지 않아야 함.
 * **명령어 구조 예시**:
   ```bash
   DocReaderCli.exe --file "C:\secure_folder\report.docx"
   
   ```
### 3.3. 핵심 로직 및 제어 흐름 (Robust Reading Flow)
 1. **확장자 판별 및 초기화**: 파일의 확장자(.docx, .xlsx, .pptx)를 확인하고 알맞은 NetOffice Application 객체 생성.
 2. **스텔스 모드 설정**: Visible = false, DisplayAlerts = false (경고창, 업데이트 팝업 등 UI 인터랙션 원천 차단).
 3. **DRM 복호화 Polling (가장 중요)**:
   * Documents.Open(ReadOnly: true) 형태의 읽기 전용 호출 수행.
   * DRM 플러그인이 문서를 복호화하여 메모리에 적재할 때까지 수 초의 지연이 발생하므로, 문서의 내용이 실제로 읽히는 상태(예: 글자 수가 0보다 커짐)가 될 때까지 **Polling(주기적 확인) 루프**를 돈다.
   * 최대 대기 시간(예: 15초)을 설정하여, 무한 대기에 빠지지 않도록 Timeout 예외를 발생시킨다.
 4. **내용 추출 (추출 품질 최적화)**:
   * **Word**: 문단(Paragraphs)과 표(Tables)를 순회하며 텍스트를 추출. Heading 스타일 등은 Markdown 기호(#)로 변환하여 에이전트가 구조를 파악할 수 있게 함.
   * **Excel**: UsedRange를 순회하며 셀의 표시된 텍스트(Text 속성)를 읽어 CSV 또는 Markdown 표 형태로 조립.
   * **PowerPoint**: 슬라이드를 순회하며 텍스트 셰이프의 내용을 추출.
## 4. 컴포넌트 2: 에이전트 스킬 / Tool 설계 (LangChain / MCP 규격 호환)
### 4.1. Tool 정의 (Schema)
 * **Tool Name**: read_secure_office_document
 * **Description**:
   "Windows 로컬 환경에서 사내 DRM이 적용되어 일반적인 파서로는 읽을 수 없는 MS Office 문서(.docx, .xlsx, .pptx)의 내용을 읽어옵니다. COM 객체 자동화(COM Automation)를 통해 백그라운드에서 실제 프로그램을 실행하여 안전하게 텍스트와 구조를 추출합니다."
 * **Parameters**:
   * file_path (string, required): 읽어올 로컬 문서의 절대 경로.
### 4.2. Tool 실행 로직 (Subprocess Wrapper)
 1. 경로의 유효성(존재 여부)을 1차 검증합니다.
 2. Python subprocess.run() (또는 Node.js child_process.exec)을 사용하여 DocReaderCli.exe를 호출합니다.
 3. **에이전트 단의 타임아웃 방어선**: 서브프로세스 실행에 엄격한 타임아웃(예: 30초)을 설정합니다.
 4. stdout으로 반환된 텍스트/마크다운을 성공적으로 파싱하면 LLM에게 컨텍스트로 반환하고, stderr에 에러가 잡히면 실패 원인을 LLM에게 알립니다.
## 5. AI 구현 시 반드시 지켜야 할 '치명적 예외 처리' (Critical Constraints)
이 시스템은 단순한 라이브러리가 아닌 무거운 데스크톱 GUI 프로세스를 백그라운드로 제어합니다. 아래의 예외 처리를 누락하면 OS의 메모리와 프로세스가 마비됩니다. 코드 생성 시 반드시 최우선으로 반영하세요.
 1. **철저한 메모리 및 객체 해제 (NetOffice 기능 적극 활용)**
   * 거대한 try-catch-finally 블록을 구성하십시오.
   * finally 구문에서는 예외 발생 여부와 상관없이 무조건 **NetOffice가 제공하는 Application.Dispose() 메서드**를 호출하십시오. 이를 통해 생성된 모든 COM 프록시 객체를 한 번에 메모리에서 안전하게 해제하고, 오피스 프로세스가 종료되도록 보장해야 합니다.
 2. **좀비 프로세스 강제 사살 (Watchdog & Kill)**
   * 화면에 보이지 않는 DRM 팝업(비밀번호 입력 창 등)이 뜨면 프로세스가 영원히 멈춥니다(Hang).
   * System.Diagnostics.Process를 활용하여, 툴 자신이 띄운 winword.exe나 excel.exe의 **PID(Process ID)를 추적**하십시오.
   * 타임아웃(예: 20초) 내에 추출이 끝나지 않으면, 추적해둔 **해당 PID를 찾아 Process.Kill()로 강제 살해**하는 워치독(Watchdog) 로직을 반드시 포함하세요. (단, 사용자가 직접 띄워놓은 기존 문서 프로세스는 죽이지 않도록 PID를 정확히 구분할 것).
