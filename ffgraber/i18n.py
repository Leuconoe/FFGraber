"""Korean and English UI messages and a local language preference."""

import json
import os
from pathlib import Path
import re
import tempfile

LANGUAGES = {"ko": "한국어", "en": "English"}

# Korean is the source language; untranslated technical errors remain intact.
MESSAGES = {
    "브라우저 링크 추출기": "Browser link extractor",
    "언어": "Language",
    "FuckingFast 파일 링크를 붙여 넣으면 최종 다운로드 주소를 수집합니다.": "Paste FuckingFast file links to extract their final download URLs.",
    "FuckingFast 파일 URL · 한 줄에 하나씩": "FuckingFast file URLs · one per line",
    "클립보드 붙여넣기": "Paste from clipboard",
    "자동 선택 (Chrome → Edge)": "Automatic (Chrome → Edge)",
    "Google Chrome": "Google Chrome",
    "Microsoft Edge": "Microsoft Edge",
    "페이지 대기(초)": "Timeout (seconds)",
    "최종 다운로드 URL까지 추출 (끄면 FuckingFast 페이지 링크만 수집)": "Extract final download URLs (off: collect FuckingFast page links only)",
    "웹페이지에서 복사한 하이퍼링크도 실제 URL로 자동 변환합니다. Ctrl+V로 붙여넣을 수 있습니다.": "Copied hyperlinks are converted to their URLs. Use Ctrl+V to paste.",
    "추출 시작": "Start extraction",
    "중지": "Stop",
    "현재 페이지 건너뛰기": "Skip current page",
    "실패·중지 항목 재시도": "Retry failed / stopped items",
    "URL 입력 후 추출 시작을 누르세요. Ctrl+Enter로도 시작할 수 있습니다.": "Enter URLs and click Start extraction, or press Ctrl+Enter.",
    "추출 결과 · 선택 후 아래에서 상세 내용 확인": "Results · select an item to view details below",
    "종류": "Type",
    "파일 / 항목": "File / item",
    "상태": "Status",
    "다운로드 URL / 원본": "Download URL / source",
    "선택한 다운로드 URL 복사": "Copy selected download URLs",
    "성공 URL 전체 복사": "Copy all successful URLs",
    "추출 URL": "Extracted URLs",
    "추출한 링크 복사": "Copy extracted links",
    "{count}개 추출 링크": "{count} extracted links",
    "선택 항목 상세": "Selected item details",
    "진행 로그": "Activity log",
    "FF 페이지 링크 복사": "Copy FF page links",
    "선택 URL 복사": "Copy selected URLs",
    "TXT / JSON 저장": "Save TXT / JSON",
    "Ctrl+Shift+C: 성공 URL 전체 복사 · 결과표에서 Ctrl+C 또는 우클릭: 선택 URL 복사": "Ctrl+Shift+C: copy successful URLs · Ctrl+C / right-click in results: copy selected URLs",
    "인증·비밀번호는 열린 브라우저에서 처리하세요. 완료되면 자동으로 이어갑니다. 실제 파일은 다운로드하지 않습니다.": "Complete verification or passwords in the browser. Extraction resumes automatically. Files are not downloaded.",
    "클립보드에 텍스트나 하이퍼링크가 없습니다.": "The clipboard contains no text or hyperlinks.",
    "붙여넣기 완료 · 하이퍼링크는 실제 URL로 변환됩니다.": "Pasted · hyperlinks are converted to their URLs.",
    "페이지 대기 시간은 10~900초로 입력하세요.": "Set a timeout between 10 and 900 seconds.",
    "입력 확인": "Check input",
    "브라우저를 준비하고 있습니다…": "Preparing the browser…",
    "중지됨": "Stopped",
    "작업 종료": "Finished",
    "{prefix} · 추출 URL {links}개 · FF 페이지 {pages}개 · 실패 {failed}개 · 건너뜀 {skipped}개": "{prefix} · {links} extracted URLs · {pages} FF pages · {failed} failed · {skipped} skipped",
    "추출 오류": "Extraction error",
    "재시도할 실패·중지·건너뜀 항목이 없습니다.": "There are no failed, stopped, or skipped items to retry.",
    "중지 중… 수집된 결과는 보존됩니다.": "Stopping… collected results will be kept.",
    "이름: {name}\n상태: {status}\n원본: {url}\n발견한 페이지: {source}\n최종 다운로드 URL: {direct}\n메시지: {error}": "Name: {name}\nStatus: {status}\nSource URL: {url}\nFound on: {source}\nFinal download URL: {direct}\nMessage: {error}",
    "복사할 링크가 없습니다.": "There are no links to copy.",
    "{count}개 URL을 복사했습니다.": "Copied {count} URLs.",
    "저장할 결과가 없습니다.": "There are no results to save.",
    "URL 목록": "URL list",
    "상세 결과와 오류": "Detailed results and errors",
    "저장 완료: {path}": "Saved: {path}",
    "저장 실패": "Save failed",
    "언어를 변경했습니다.": "Language changed.",
    "언어를 변경했지만 설정을 저장하지 못했습니다: {error}": "Language changed, but the preference could not be saved: {error}",
    "대기": "Queued", "추출 중": "Extracting", "브라우저 확인": "Check browser",
    "목록 확인": "Scanned", "FF 링크 발견": "FF link found", "완료": "Done",
    "실패": "Failed", "건너뜀": "Skipped", "웹 페이지": "Web page",
    "링크 목록": "Link list", "Filecrypt": "Filecrypt", "Filecrypt 개별": "Filecrypt link",
    "FuckingFast": "FuckingFast", "직접 URL": "Direct URL",
    "http:// 또는 https:// URL을 입력하세요.": "Enter an http:// or https:// URL.",
    "인증 정보가 포함된 URL은 지원하지 않습니다.": "URLs containing credentials are not supported.",
    "올바르지 않은 URL: {value}": "Invalid URL: {value}",
    "URL은 한 줄에 하나씩 입력하세요. 공백은 %20으로 표시하세요.": "Enter one URL per line. Encode spaces as %20.",
    "추출할 URL을 한 개 이상 입력하세요.": "Enter at least one URL to extract.",
    "FuckingFast URL만 입력하세요: {value}": "Enter FuckingFast URLs only: {value}",
    "FuckingFast 파일 페이지 URL을 입력하세요.": "Enter a FuckingFast file page URL.",
    "추출할 FuckingFast URL을 입력하세요.": "Enter FuckingFast URLs to extract.",
    "참고 소스 엔진의 의존성이 없습니다. start.bat을 실행해 requirements.txt를 설치하세요.": "Required browser packages are missing. Run start.bat to install requirements.txt.",
    "참고 엔진에서는 Chrome 또는 Edge를 선택하세요.": "Select Chrome or Edge for the reference engine.",
    "설치된 Chrome 또는 Edge를 찾을 수 없습니다. 브라우저를 설치하고 다시 실행하세요.": "Chrome or Edge was not found. Install a browser and try again.",
    "참고 소스 엔진으로 브라우저 시작 중…": "Starting the browser with the reference engine…",
    "브라우저 준비 완료 · 다운로드 차단 활성화": "Browser ready · file downloads blocked",
    "사용자가 중지했습니다.": "Stopped by the user.",
    "사용자가 건너뛰었습니다.": "Skipped by the user.",
    "최종 URL을 찾지 못했습니다. 브라우저의 인증·오류 메시지를 확인하세요.": "No final URL found. Check the browser for verification or error messages.",
    "실패: {name} — {error}": "Failed: {name} — {error}",
    "인증 화면이 있으면 열린 브라우저에서 처리하세요. 자동으로 이어집니다.": "Complete verification in the browser. Extraction will resume automatically.",
    "참고 소스 방식으로 FuckingFast 최종 다운로드 URL을 추출합니다.": "Extract final FuckingFast download URLs using a browser.",
    "추출할 URL. 생략하면 데스크톱 UI를 엽니다.": "URLs to extract. Omit to open the desktop UI.",
    "한 줄에 URL 하나씩 저장된 UTF-8 텍스트 파일": "UTF-8 text file with one URL per line",
    "입력 파일의 URL을 GUI에 불러옵니다": "Load the input URLs in the desktop UI",
    "결과 경로 (.txt / .json)": "Output path (.txt / .json)",
    "기본값은 검증된 참고 소스 방식": "Use the reference engine by default",
    "페이지당 대기 시간(초), 10~900": "Timeout per page in seconds, 10–900",
    "FF 페이지 링크까지만 수집": "Collect FF page links only",
    "인터페이스 언어 (ko / en)": "Interface language (ko / en)",
    "--timeout은 10~900초여야 합니다.": "--timeout must be between 10 and 900 seconds.",
    "참고 소스 엔진은 Chrome 또는 Edge를 선택하세요.": "Select Chrome or Edge for the reference engine.",
    "중지했습니다. 수집한 결과를 저장합니다.": "Stopped. Saving collected results.",
    "오류: {error}": "Error: {error}",
    "저장 실패: {error}": "Save failed: {error}",
    "{count}개 URL 저장: {path}": "Saved {count} URLs: {path}",
    "브라우저 시작: {browser}": "Starting browser: {browser}",
    "브라우저를 시작할 수 없습니다. Chrome 또는 Edge를 설치하거나 install_browser.bat을 실행해 Chromium을 설치하세요.\n{errors}": "Could not start a browser. Install Chrome or Edge, or run install_browser.bat to install Chromium.\n{errors}",
    "설치된 브라우저로 시작했습니다. 별도 패키지 설치가 필요하지 않습니다.": "Started an installed browser. No additional packages are needed.",
    "탐색 한도에 도달했습니다. 이 URL로 별도 추출하세요.": "The page limit was reached. Extract this URL separately.",
    "열기: {url}": "Opening: {url}",
    "링크가 삭제되었거나 없습니다. (HTTP {status})": "The link is missing or was deleted. (HTTP {status})",
    "브라우저 탭이 닫혔습니다. 다시 추출하세요.": "The browser tab was closed. Start extraction again.",
    "Filecrypt 개별 링크가 삭제되었거나 없습니다.": "The Filecrypt link is missing or was deleted.",
    "인증/비밀번호/추가 버튼이 있으면 열린 브라우저에서 처리하세요. 자동 감지 후 계속합니다.": "Complete verification, passwords, or additional buttons in the browser. Extraction resumes automatically.",
    "{seconds}초 동안 링크를 찾지 못했습니다. 인증·비밀번호·사이트 상태를 확인하세요.": "No links found within {seconds} seconds. Check verification, passwords, and the site status.",
    "DevTools 연결은 로컬 브라우저만 허용합니다.": "DevTools connections are limited to local browsers.",
    "Chrome DevTools WebSocket 연결이 거부되었습니다.": "The Chrome DevTools WebSocket connection was refused.",
    "DevTools 응답 크기가 한도를 초과했습니다.": "The DevTools response exceeded the size limit.",
    "브라우저 연결이 닫혔습니다. {error}": "The browser connection was closed. {error}",
    "브라우저가 시작 직후 종료되었습니다.": "The browser exited immediately after starting.",
    "브라우저의 DevTools 준비 시간이 초과되었습니다.": "Timed out waiting for browser DevTools.",
}

_REVERSE = {value: key for key, value in MESSAGES.items()}
_DYNAMIC = []
for _source, _english in MESSAGES.items():
    if "{" in _source:
        for _template in (_source, _english):
            _pattern = re.escape(_template)
            for _name in re.findall(r"\{(\w+)\}", _template):
                _pattern = _pattern.replace(re.escape("{" + _name + "}"), f"(?P<{_name}>.+?)")
            _DYNAMIC.append((re.compile(_pattern, re.DOTALL), _source))


def translate(message, language="ko", **values):
    source = _REVERSE.get(message, message)
    if not values and source not in MESSAGES:
        for pattern, template in _DYNAMIC:
            match = pattern.fullmatch(message)
            if match:
                source, values = template, match.groupdict()
                break
    template = MESSAGES.get(source, source) if language == "en" else source
    return template.format(**values) if values else template


def settings_path():
    base = os.environ.get("APPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "FFGraber" / "settings.json"


def load_language(path=None):
    try:
        data = json.loads((path or settings_path()).read_text(encoding="utf-8"))
        language = data.get("language") if isinstance(data, dict) else None
        return language if isinstance(language, str) and language in LANGUAGES else "ko"
    except (OSError, ValueError):
        return "ko"


def save_language(language, path=None):
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix="settings-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump({"language": language}, file)
            file.write("\n")
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
