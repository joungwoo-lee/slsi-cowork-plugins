# outlook-search

로컬 Outlook 데스크탑(Windows)에 저장된 메일을 COM으로 검색·조회하는 Claude Code 스킬.

## 설치

1. **이 폴더를 Windows의 Claude 스킬 디렉토리로 복사**
   ```
   %USERPROFILE%\.claude\skills\outlook-search\
   ```
   (WSL에서 만들었다면 `\\wsl$\<distro>\home\<user>\.claude\skills\outlook-search\`에서 복사)

2. **Windows Python에 pywin32 설치**
   ```cmd
   pip install pywin32
   ```

3. **Outlook 데스크탑 실행** — 계정 설정 완료된 상태여야 함.

4. **Claude Code도 Windows 네이티브에서 실행** (WSL에서는 COM 사용 불가).

## 빠른 확인

```cmd
python "%USERPROFILE%\.claude\skills\outlook-search\scripts\list_folders.py"
```
계정과 폴더 트리가 JSON으로 나오면 정상.

```cmd
python "%USERPROFILE%\.claude\skills\outlook-search\scripts\search_outlook.py" --limit 5
```
받은편지함 최근 5건이 나오면 끝.

## Claude에게 시키는 예시

- "아웃룩에서 지난주 김부장한테 온 메일 찾아줘"
- "Outlook 받은편지함에서 '계약서' 들어간 메일 10개"
- "프로젝트A 폴더에서 첨부파일 있는 미읽음 메일만"

Claude가 SKILL.md를 보고 적절한 플래그를 조합해 `search_outlook.py`를 호출하고, 결과 JSON을 읽어 한국어로 요약해줍니다.

## 보안 프롬프트가 뜰 때

Outlook 2016 이후 기본적으로 외부 프로그램의 메일 접근을 막는 경고가 뜹니다.
- 일회성 허용: "허용" 클릭
- 영구 허용: Outlook → 파일 → 옵션 → 보안 센터 → 보안 센터 설정 → 프로그래밍 방식 액세스
  → "바이러스 백신 상태에 관계없이 경고하지 않음" (관리자 권한 필요)
  또는 신뢰할 수 있는 발행자/매크로 설정 조정.

회사 정책상 위 설정이 잠겨 있으면, 매번 "허용" 누르거나 IT에 문의 필요.

## 한계

- Outlook 데스크탑이 켜져 있고 동기화된 메일만 검색 가능 (PST/OST 캐시 범위).
- 매우 큰 폴더(수십만 건)는 첫 검색이 느릴 수 있음 → `--since`로 좁히세요.
- 첨부파일 본문 검색은 안 함. 파일명만 결과에 포함.
- macOS/Linux/WSL 미지원.
