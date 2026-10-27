import argparse
import asyncio
import sys

from . import __version__
from .engine import ExtractionEngine, Options
from .i18n import LANGUAGES, load_language, translate
from .links import parse_input
from .models import export_records, output_links
from .reference import validate_ff_urls


def main(argv=None):
    language_parser = argparse.ArgumentParser(add_help=False)
    language_parser.add_argument("--language", choices=LANGUAGES, default=load_language())
    language = language_parser.parse_known_args(argv)[0].language

    def tr(message, **values):
        return translate(message, language, **values)

    parser = argparse.ArgumentParser(description=tr("참고 소스 방식으로 FuckingFast 최종 다운로드 URL을 추출합니다."))
    parser.add_argument("--language", choices=LANGUAGES, default=language, help=tr("인터페이스 언어 (ko / en)"))
    parser.add_argument("--version", action="version", version=f"FFGraber {__version__}")
    parser.add_argument("urls", nargs="*", help=tr("추출할 URL. 생략하면 데스크톱 UI를 엽니다."))
    parser.add_argument("--input", help=tr("한 줄에 URL 하나씩 저장된 UTF-8 텍스트 파일"))
    parser.add_argument("--gui", action="store_true", help=tr("입력 파일의 URL을 GUI에 불러옵니다"))
    parser.add_argument("--output", default="results.txt", help=tr("결과 경로 (.txt / .json)"))
    parser.add_argument("--browser", choices=["auto", "chrome", "msedge", "chromium"], default="auto")
    parser.add_argument("--engine", choices=["reference", "auto"], default="reference", help=tr("기본값은 검증된 참고 소스 방식"))
    parser.add_argument("--timeout", type=float, default=180, help=tr("페이지당 대기 시간(초), 10~900"))
    parser.add_argument("--host-only", action="store_true", help=tr("FF 페이지 링크까지만 수집"))
    args = parser.parse_args(argv)
    if not args.urls and not args.input:
        from .gui import main as gui_main
        gui_main(language=language)
        return 0
    if not 10 <= args.timeout <= 900:
        parser.error(tr("--timeout은 10~900초여야 합니다."))
    try:
        text = "\n".join(args.urls)
        if args.input:
            from pathlib import Path
            text += "\n" + Path(args.input).read_text(encoding="utf-8-sig")
        urls = validate_ff_urls(parse_input(text))
        if args.engine == "reference" and args.browser == "chromium":
            raise ValueError(tr("참고 소스 엔진은 Chrome 또는 Edge를 선택하세요."))
    except (ValueError, OSError) as exc:
        parser.error(tr(str(exc)))
    if args.gui:
        from .gui import main as gui_main
        gui_main(urls, language=language)
        return 0

    def emit(event):
        if event["type"] == "log":
            print(event["message"], file=sys.stderr, flush=True)

    engine = ExtractionEngine(Options(backend=args.engine, browser=args.browser, timeout=args.timeout,
                                      resolve_direct=not args.host_only, language=language), emit=emit)
    success = True
    try:
        asyncio.run(engine.run(urls))
    except KeyboardInterrupt:
        print(tr("중지했습니다. 수집한 결과를 저장합니다."), file=sys.stderr)
        success = False
    except Exception as exc:
        print(tr("오류: {error}", error=tr(str(exc))), file=sys.stderr)
        success = False
    records = list(engine.records.values())
    try:
        export_records(args.output, records, host_links=args.host_only)
    except OSError as exc:
        print(tr("저장 실패: {error}", error=str(exc)), file=sys.stderr)
        return 1
    links = output_links(records, host_links=args.host_only)
    print(tr("{count}개 URL 저장: {path}", count=len(links), path=args.output))
    return 0 if success and links and not any(r.status in {"failed", "cancelled"} for r in records) else 1
