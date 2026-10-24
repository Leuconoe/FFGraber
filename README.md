# FFGraber

FuckingFast 파일 URL 여러 개를 받아 최종 다운로드 주소를 수집하는 한국어 데스크톱 프로그램입니다. Chrome과 Edge를 지원하며 GUI와 CLI로 실행할 수 있습니다.

## 기능

- 여러 FuckingFast URL 순차 추출
- XHR 응답의 `HX-Redirect` / `Location` 헤더에서 최종 URL 수집
- 실제 파일 다운로드 차단
- 성공 URL 전체 복사, 선택 URL 복사, 우클릭 메뉴
- 중복 제거, TXT/JSON 저장
- 중지와 실패 항목 재시도, 부분 결과 보존

## 실행

Python 3.10 이상과 Google Chrome 또는 Microsoft Edge가 필요합니다.

Windows에서는 **`start.bat`**을 실행하세요. 첫 실행 시 프로젝트 내부 `.venv`를 만들고 의존성을 설치합니다. 패키지와 브라우저 드라이버를 처음 받을 때 인터넷 연결이 필요합니다.

직접 실행할 수도 있습니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

FuckingFast 파일 URL을 한 줄에 하나씩 붙여 넣고 **추출 시작**을 누릅니다. 인증이 나오면 열린 브라우저에서 처리하면 됩니다.

## URL 복사

- **성공 URL 전체 복사** 또는 `Ctrl+Shift+C`: 성공한 최종 주소 전체를 줄바꿈으로 복사합니다.
- **선택 URL 복사**, 결과표의 `Ctrl+C`, 우클릭 메뉴: 선택한 성공 항목만 복사합니다.
- 실패·대기 항목과 중복 URL은 제외합니다. 복사할 주소가 없으면 기존 클립보드를 유지합니다.
- **FF 페이지 링크 복사**는 원본 파일 페이지 주소를 복사합니다.

## CLI

한 줄에 URL 하나씩 저장한 UTF-8 파일 `links.txt`를 준비하세요.

```powershell
.\.venv\Scripts\python.exe -m ffgraber --input links.txt --output results.json --browser chrome
.\.venv\Scripts\python.exe -m ffgraber --input links.txt --output results.txt --browser chrome
start.bat --gui --input links.txt
```

`--browser auto`는 Chrome, Edge 순서로 선택합니다. `--timeout`은 페이지당 대기 시간이며 기본 180초입니다. `--host-only`는 최종 주소 추출 없이 입력된 원본 FF 페이지 링크만 정리합니다.

TXT에는 수집된 URL만, JSON에는 원본 URL·파일명·상태·오류도 저장합니다. CLI 종료 코드는 전체 성공이면 0, 실패·중지·실행 오류이면 1입니다.

## 동작 방식

기본 엔진은 `setuptools`, `selenium`, `undetected-chromedriver`를 사용합니다. 브라우저에서 다운로드를 차단하고 다운로드 버튼을 클릭한 뒤 XHR 응답의 리다이렉트 헤더를 포착합니다. 성공한 주소는 이후 파일의 실패와 관계없이 보존합니다. 브라우저의 다운로드 차단 설정이 실패하면 파일 페이지를 열기 전에 중단합니다.

이 프로그램은 현재 FuckingFast 전용입니다. 최종 URL은 만료되거나 IP·세션에 종속될 수 있습니다.

개발 환경에서는 Chrome 실행과 다운로드 차단 설정을 확인했습니다. 실제 사이트 탐색은 해당 환경의 `ERR_NETWORK_ACCESS_DENIED` 제한으로 완료하지 못했으므로 전체 사이트 동작이 검증된 상태로 표시하지 않습니다.

참고 소스: [zouhirdev/fitgirl-ff-link-extractor](https://github.com/zouhirdev/fitgirl-ff-link-extractor). 참고 프로젝트 원본, 테스트 코드·입력·검증 결과와 가상환경은 이 저장소에 포함하지 않습니다.
