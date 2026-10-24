from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .links import kind_of


@dataclass
class Record:
    url: str
    source: str = ""
    name: str = ""
    kind: str = "page"
    status: str = "queued"
    direct_url: str = ""
    resolved_url: str = ""
    error: str = ""
    depth: int = 0
    expected_host: str = ""


def output_links(records, host_links=False):
    result = {}
    for record in records:
        url = record.url if host_links and record.kind in {"ff", "direct"} else (record.direct_url or record.resolved_url)
        if url:
            result.setdefault(url, None)
    return list(result)


def direct_download_links(records):
    """Only successfully extracted FF download URLs, in input order."""
    return list(dict.fromkeys(
        record.direct_url for record in records
        if record.status == "done" and record.direct_url and kind_of(record.direct_url) == "direct"
    ))


def export_records(path, records, host_links=False):
    path = Path(path)
    records = list(records)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps([asdict(record) for record in records],
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        links = output_links(records, host_links)
        path.write_text("\n".join(links) + ("\n" if links else ""), encoding="utf-8")
