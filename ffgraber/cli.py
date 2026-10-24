import argparse
import asyncio
import sys

from .engine import ExtractionEngine, Options
from .links import parse_input
from .models import export_records, output_links
from .reference import validate_ff_urls


def main(argv=None):
    parser = argparse.ArgumentParser(description="참고 소스 방식으로 FuckingFast 최종 다운로드 URL을 추출합니다.")
    parser.add_argument("urls", nargs="*", help="추출할 URL. 생략하면 데스크톱 UI를 엽니다.")
    parser.add_argument("--input", help="한 줄에 URL 하나씩 저장된 UTF-8 텍스트 파일")
    parser.add_argument("--gui", action="store_true", help="입력 파일의 URL을 GUI에 불러옵니다")
    parser.add_argument("--output", default="results.txt", help="결과 경로 (.txt / .json)")
    parser.add_argument("--browser", choices=["auto", "chrome", "msedge", "chromium"], default="auto")
    parser.add_argument("--engine", choices=["reference", "auto"], default="reference", help="기본값은 검증된 참고 소스 방식")
    parser.add_argument("--timeout", type=float, default=180, help="페이지당 대기 시간(초), 10~900")
    parser.add_argument("--host-only", action="store_true", help="FF 페이지 링크까지만 수집")
    args = parser.parse_args(argv)
    if not args.urls and not args.input:
        from .gui import main as gui_main
        gui_main()
        return 0
    if not 10 <= args.timeout <= 900:
        parser.error("--timeout은 10~900초여야 합니다.")
    try:
        text = "\n".join(args.urls)
        if args.input:
            from pathlib import Path
            text += "\n" + Path(args.input).read_text(encoding="utf-8-sig")
        urls = validate_ff_urls(parse_input(text))
        if args.engine == "reference" and args.browser == "chromium":
            raise ValueError("참고 소스 엔진은 Chrome 또는 Edge를 선택하세요.")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if args.gui:
        from .gui import main as gui_main
        gui_main(urls)
        return 0

    def emit(event):
        if event["type"] == "log":
            print(event["message"], file=sys.stderr, flush=True)

    engine = ExtractionEngine(Options(backend=args.engine, browser=args.browser, timeout=args.timeout,
                                      resolve_direct=not args.host_only), emit=emit)
    success = True
    try:
        asyncio.run(engine.run(urls))
    except KeyboardInterrupt:
        print("중지했습니다. 수집한 결과를 저장합니다.", file=sys.stderr)
        success = False
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        success = False
    records = list(engine.records.values())
    try:
        export_records(args.output, records, host_links=args.host_only)
    except OSError as exc:
        print(f"저장 실패: {exc}", file=sys.stderr)
        return 1
    links = output_links(records, host_links=args.host_only)
    print(f"{len(links)}개 URL 저장: {args.output}")
    return 0 if success and links and not any(r.status in {"failed", "cancelled"} for r in records) else 1
