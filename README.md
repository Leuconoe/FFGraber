# FFGraber

[English](README.en.md)

FuckingFast 파일 URL 여러 개를 받아 최종 다운로드 주소를 수집하는 데스크톱 프로그램입니다. 한국어·영어, Chrome·Edge, GUI·CLI를 지원합니다.

## 기능

- 여러 FuckingFast URL 순차 추출
- XHR 응답의 `HX-Redirect` / `Location` 헤더에서 최종 URL 수집
- 실제 파일 다운로드 차단
- 성공 URL 전체 복사, 선택 URL 복사, 우클릭 메뉴
- 추출 URL 탭의 전용 복사 버튼과 추출 링크 개수 표시
- 한국어 / English 즉시 전환 및 언어 설정 저장
- 하이퍼링크 붙여넣기 시 실제 URL로 자동 변환 (Ctrl+V 지원)
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

## 하이퍼링크 붙여넣기

웹페이지에서 파일명처럼 표시되는 하이퍼링크를 복사한 뒤 입력창에 **Ctrl+V** 또는 **클립보드 붙여넣기**로 붙여넣으면 실제 URL로 자동 변환합니다. 여러 링크는 한 줄에 하나씩 정리하고 중복 주소를 제거합니다. HTML `<a href="…">파일명</a>` 텍스트도 붙여넣을 수 있습니다.

`Ctrl+V`는 커서 위치에 삽입하거나 선택한 부분을 교체합니다. 붙여넣기 버튼은 입력창 전체를 교체합니다. `Ctrl+Z`로 되돌릴 수 있으며, 클립보드 원본은 변경하지 않습니다. 원본 복사 앱이 주소 없이 파일명만 제공하면 URL을 알아낼 수 없으므로 브라우저에서 **링크 주소 복사**를 사용하세요.

## URL 복사

- **추출 URL** 탭 위의 **추출한 링크 복사** 버튼: 성공한 최종 다운로드 주소를 바로 복사합니다. 성공한 주소가 생기면 활성화되며, 옆에 중복을 제거한 개수를 표시합니다. 추출 도중에도 완료된 주소를 복사할 수 있습니다.
- **성공 URL 전체 복사** 또는 `Ctrl+Shift+C`: 성공한 최종 주소 전체를 줄바꿈으로 복사합니다.
- **선택 URL 복사**, 결과표의 `Ctrl+C`, 우클릭 메뉴: 선택한 성공 항목만 복사합니다.
- 실패·대기 항목과 중복 URL은 제외합니다. 복사할 주소가 없으면 기존 클립보드를 유지합니다.
- **FF 페이지 링크 복사**는 원본 파일 페이지 주소를 복사합니다.

## 언어 설정

창 오른쪽 위의 **언어 / Language**에서 **한국어** 또는 **English**를 선택합니다. 입력과 결과를 유지하면서 화면·상태·프로그램 안내 메시지가 즉시 전환됩니다. Windows에서는 선택한 언어를 `%APPDATA%\FFGraber\settings.json`에 저장하여 다음 실행에도 적용합니다. 브라우저와 드라이버가 제공하는 기술 오류는 원문을 유지할 수 있습니다.

CLI 언어는 `--language ko` 또는 `--language en`으로 지정합니다.

```powershell
start.bat --language en
.\.venv\Scripts\python.exe -m ffgraber --language en --help
```

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
