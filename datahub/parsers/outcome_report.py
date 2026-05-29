"""Extract reviewable outcome metric candidates from school/major reports."""
from __future__ import annotations

import csv
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

from datahub.config import load_outcome_metrics


CANDIDATE_COLUMNS = [
    "domain",
    "entity_code",
    "entity_name",
    "metric_key",
    "metric_label",
    "metric_unit",
    "metric_year",
    "candidate_value",
    "candidate_text_value",
    "source_title",
    "source_url",
    "evidence_quote",
    "metric_scope",
    "source_date",
    "availability_date",
    "page_number",
    "match_alias",
    "confidence",
    "review_status",
    "notes",
]

PERCENT_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*%")
NUMBER_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)(?!\d)")
SPACE_RE = re.compile(r"\s+")
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
PDF_INLINE_SPACE_RE = re.compile(r"(?<=[\u4e00-\u9fff0-9０-９A-Za-z])\s+(?=[\u4e00-\u9fff0-9０-９A-Za-z%％])")
CLAUSE_SPLIT_RE = re.compile(r"[。；;]")
OFD_PAGE_RE = re.compile(r"(?:^|/)Pages/Page_(\d+)/Content\.xml$")
OFD_BOUNDARY_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def extract_outcome_metric_candidates_from_pdf(
    path: Path,
    *,
    domain: str,
    entity_code: str,
    entity_name: str,
    metric_year: int,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
) -> list[dict[str, Any]]:
    _require_pdf_file(path)
    _require_pdf_reader()
    reader = PdfReader(str(path))
    page_lines: list[tuple[int, str]] = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        page_lines.extend((page_index, line) for line in text.splitlines())
    return extract_outcome_metric_candidates_from_lines(
        page_lines,
        domain=domain,
        entity_code=entity_code,
        entity_name=entity_name,
        metric_year=metric_year,
        source_title=source_title,
        source_url=source_url,
        source_date=source_date,
        availability_date=availability_date,
    )


def extract_outcome_metric_candidates_from_report(
    path: Path,
    *,
    domain: str,
    entity_code: str,
    entity_name: str,
    metric_year: int,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    kwargs = {
        "domain": domain,
        "entity_code": entity_code,
        "entity_name": entity_name,
        "metric_year": metric_year,
        "source_title": source_title,
        "source_url": source_url,
        "source_date": source_date,
        "availability_date": availability_date,
    }
    if suffix == ".pdf":
        return extract_outcome_metric_candidates_from_pdf(path, **kwargs)
    if suffix == ".ofd":
        return extract_outcome_metric_candidates_from_ofd(path, **kwargs)
    if suffix == ".docx":
        return extract_outcome_metric_candidates_from_docx(path, **kwargs)
    raise ValueError(f"unsupported report format: {suffix or '<none>'}")


def extract_outcome_metric_candidates_from_docx(
    path: Path,
    *,
    domain: str,
    entity_code: str,
    entity_name: str,
    metric_year: int,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
) -> list[dict[str, Any]]:
    _require_docx_file(path)
    page_lines = _extract_docx_page_lines(path)
    return extract_outcome_metric_candidates_from_lines(
        page_lines,
        domain=domain,
        entity_code=entity_code,
        entity_name=entity_name,
        metric_year=metric_year,
        source_title=source_title,
        source_url=source_url,
        source_date=source_date,
        availability_date=availability_date,
    )


def extract_outcome_metric_candidates_from_ofd(
    path: Path,
    *,
    domain: str,
    entity_code: str,
    entity_name: str,
    metric_year: int,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
) -> list[dict[str, Any]]:
    _require_ofd_file(path)
    page_lines = _extract_ofd_page_lines(path)
    return extract_outcome_metric_candidates_from_lines(
        page_lines,
        domain=domain,
        entity_code=entity_code,
        entity_name=entity_name,
        metric_year=metric_year,
        source_title=source_title,
        source_url=source_url,
        source_date=source_date,
        availability_date=availability_date,
    )


def extract_outcome_metric_candidates_from_lines(
    lines: Iterable[str | tuple[int, str]],
    *,
    domain: str,
    entity_code: str,
    entity_name: str,
    metric_year: int,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
) -> list[dict[str, Any]]:
    config = load_outcome_metrics()
    metrics = config.get("domains", {}).get(domain)
    if not isinstance(metrics, dict):
        raise KeyError(f"unknown outcome domain: {domain}")

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    context_line_count = _context_line_count(config)
    page_lines = list(_iter_page_lines(lines))
    for page_number, base_line, context_line in _iter_context_lines(page_lines, context_line_count):
        if not base_line:
            continue
        for metric_key, metric in metrics.items():
            alias = _matched_alias(base_line, metric)
            if not alias:
                continue
            if not _context_allowed(context_line, metric):
                continue
            values = _candidate_values(context_line, metric, alias)
            for text_value, numeric_value in values:
                evidence_quote = _quote(context_line)
                key = (metric_key, str(numeric_value), evidence_quote, str(page_number))
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "domain": domain,
                    "entity_code": entity_code,
                    "entity_name": entity_name,
                    "metric_key": metric_key,
                    "metric_label": metric.get("label", metric_key),
                    "metric_unit": metric.get("unit", ""),
                    "metric_year": metric_year,
                    "candidate_value": _format_number(numeric_value),
                    "candidate_text_value": text_value,
                    "source_title": source_title,
                    "source_url": source_url,
                    "evidence_quote": evidence_quote,
                    "metric_scope": _infer_metric_scope(evidence_quote),
                    "source_date": source_date,
                    "availability_date": availability_date,
                    "page_number": page_number,
                    "match_alias": alias,
                    "confidence": _confidence(alias, metric, len(values)),
                    "review_status": "needs_review",
                    "notes": "Candidate only; verify source context before merging into outcome collection plan.",
                })
    return rows


def write_outcome_metric_candidate_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANDIDATE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _infer_metric_scope(evidence_quote: str) -> str:
    quote = evidence_quote.strip()
    scope_parts: list[str] = []
    cohort_match = re.search(r"([0-9０-９]{4})\s*届", quote)
    if cohort_match:
        scope_parts.append(f"{cohort_match.group(1)}届")
    if "本科应届毕业生" in quote:
        scope_parts.append("本科应届毕业生")
    elif "本科毕业生" in quote:
        scope_parts.append("本科毕业生")
    elif "毕业研究生" in quote or "研究生毕业生" in quote:
        scope_parts.append("研究生")
    elif "专科毕业生" in quote or "高职" in quote:
        scope_parts.append("专科/高职毕业生")
    elif "毕业生" in quote:
        scope_parts.append("毕业生总体")

    if "辽宁省内" in quote or "在辽就业" in quote or "辽宁省就业" in quote or "留辽" in quote:
        scope_parts.append("辽宁省内去向，不是学校总体就业率或本科总体口径")
    if "专业对口" in quote or "对口就业率" in quote:
        scope_parts.append("专业对口口径，不是学校总体就业率或本科总体口径")
    if "专业毕业生" in quote or re.search(r"[\u4e00-\u9fa5]{2,24}专业[^。；;]{0,12}就业率", quote):
        scope_parts.append("专业口径，不是学校总体就业率或本科总体口径")
    if "男生" in quote or "女生" in quote or "男/女" in quote:
        scope_parts.append("性别分组，不是学校总体就业率或本科总体口径")
    if "师范生" in quote or "非师范生" in quote:
        scope_parts.append("培养类型分组，不是学校总体就业率或本科总体口径")
    if "学位点" in quote:
        scope_parts.append("学位点口径，不是学校总体就业率或本科总体口径")
    if re.search(r"((比例|率)[^。；;]{0,12}|较\s*去年[^。；;]{0,6})(上升|增长|提高|提升|下降|降低)", quote):
        scope_parts.append("变化幅度，不是学校总体就业率或本科总体口径")
    if "国内升学" in quote:
        scope_parts.append("国内升学")
    elif "升学" in quote:
        scope_parts.append("升学")
    if "年终" in quote:
        scope_parts.append("年终毕业去向")
    elif "初次" in quote:
        scope_parts.append("初次毕业去向")
    elif "毕业去向落实率" in quote:
        scope_parts.append("毕业去向落实率")
    elif "就业率" in quote:
        scope_parts.append("就业率")
    if "截至" in quote:
        match = re.search(r"截至\s*([0-9０-９]{4}\s*年\s*[0-9０-９]{1,2}\s*月\s*[0-9０-９]{1,2}\s*日|[0-9０-９]{1,2}\s*月\s*[0-9０-９]{1,2}\s*日)", quote)
        if match:
            scope_parts.append(f"截至{match.group(1)}")
    return "，".join(dict.fromkeys(scope_parts))


def _require_pdf_file(path: Path) -> None:
    header = _read_header(path)
    lowered = header.lstrip().lower()
    if lowered.startswith(b"<!doctype html") or lowered.startswith(b"<html"):
        raise ValueError(f"outcome report is HTML, not PDF: {path}")
    if not header.startswith(b"%PDF"):
        raise ValueError(f"outcome report has invalid PDF header: {path}")


def _require_pdf_reader() -> None:
    if PdfReader is None:
        raise RuntimeError("pypdf is required for PDF report parsing. Install dependencies with: pip install pypdf")


def _require_ofd_file(path: Path) -> None:
    header = _read_header(path)
    lowered = header.lstrip().lower()
    if lowered.startswith(b"<!doctype html") or lowered.startswith(b"<html"):
        raise ValueError(f"outcome report is HTML, not OFD: {path}")
    if not zipfile.is_zipfile(path):
        raise ValueError(f"outcome report has invalid OFD container: {path}")


def _require_docx_file(path: Path) -> None:
    header = _read_header(path)
    lowered = header.lstrip().lower()
    if lowered.startswith(b"<!doctype html") or lowered.startswith(b"<html"):
        raise ValueError(f"outcome report is HTML, not DOCX: {path}")
    if not zipfile.is_zipfile(path):
        raise ValueError(f"outcome report has invalid DOCX container: {path}")
    with zipfile.ZipFile(path) as zf:
        if "word/document.xml" not in zf.namelist():
            raise ValueError(f"outcome report DOCX is missing word/document.xml: {path}")


def _read_header(path: Path) -> bytes:
    try:
        return path.read_bytes()[:256]
    except OSError as exc:
        raise ValueError(f"cannot read outcome report: {path}: {exc}") from exc


def _extract_ofd_page_lines(path: Path) -> list[tuple[int, str]]:
    page_lines: list[tuple[int, str]] = []
    with zipfile.ZipFile(path) as zf:
        page_names = sorted(
            (name for name in zf.namelist() if OFD_PAGE_RE.search(name)),
            key=_ofd_page_sort_key,
        )
        for page_name in page_names:
            page_number = _ofd_page_number(page_name)
            with zf.open(page_name) as f:
                objects = _extract_ofd_text_objects(f.read())
            for line in _group_ofd_text_objects(objects):
                page_lines.append((page_number, line))
    return page_lines


def _extract_docx_page_lines(path: Path) -> list[tuple[int, str]]:
    with zipfile.ZipFile(path) as zf:
        with zf.open("word/document.xml") as f:
            root = ET.fromstring(f.read())
    lines: list[tuple[int, str]] = []
    for element in root.iter():
        if _local_name(element.tag) != "p":
            continue
        text = "".join(
            str(child.text or "")
            for child in element.iter()
            if _local_name(child.tag) == "t"
        )
        cleaned = _clean_line(text)
        if cleaned:
            lines.append((1, cleaned))
    return lines


def _extract_ofd_text_objects(content_xml: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(content_xml)
    objects: list[dict[str, Any]] = []
    for element in root.iter():
        if _local_name(element.tag) != "TextObject":
            continue
        text = "".join(
            str(child.text or "")
            for child in element.iter()
            if _local_name(child.tag) == "TextCode"
        ).strip()
        if not text:
            continue
        boundary = _parse_ofd_boundary(element.attrib.get("Boundary", ""))
        if not boundary:
            continue
        objects.append({
            "x": boundary[0],
            "y": boundary[1],
            "text": text,
        })
    return objects


def _group_ofd_text_objects(
    objects: list[dict[str, Any]],
    *,
    y_tolerance: float = 1.2,
) -> list[str]:
    rows: list[list[dict[str, Any]]] = []
    for item in sorted(objects, key=lambda obj: (obj["y"], obj["x"])):
        if rows and abs(rows[-1][0]["y"] - item["y"]) <= y_tolerance:
            rows[-1].append(item)
        else:
            rows.append([item])
    lines = []
    for row in rows:
        line = "".join(item["text"] for item in sorted(row, key=lambda obj: obj["x"]))
        if _clean_line(line):
            lines.append(line)
    return lines


def _parse_ofd_boundary(value: str) -> tuple[float, float, float, float] | None:
    numbers = [float(item) for item in OFD_BOUNDARY_RE.findall(str(value or ""))]
    if len(numbers) < 4:
        return None
    return numbers[0], numbers[1], numbers[2], numbers[3]


def _ofd_page_sort_key(name: str) -> int:
    match = OFD_PAGE_RE.search(name)
    return int(match.group(1)) if match else 0


def _ofd_page_number(name: str) -> int:
    return _ofd_page_sort_key(name) + 1


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _iter_page_lines(lines: Iterable[str | tuple[int, str]]) -> Iterable[tuple[int, str]]:
    for item in lines:
        if isinstance(item, tuple):
            yield int(item[0]), str(item[1])
        else:
            yield 1, str(item)


def _iter_context_lines(
    page_lines: list[tuple[int, str]],
    context_line_count: int,
) -> Iterable[tuple[int, str, str]]:
    for index, (page_number, raw_line) in enumerate(page_lines):
        base_line = _clean_line(raw_line)
        context_parts = [base_line] if base_line else []
        for next_page_number, next_raw_line in page_lines[index + 1:index + context_line_count]:
            if next_page_number != page_number:
                break
            next_line = _clean_line(next_raw_line)
            if next_line:
                context_parts.append(next_line)
        yield page_number, base_line, _clean_line(" ".join(context_parts))


def _context_line_count(config: dict[str, Any]) -> int:
    extraction_config = config.get("extraction") or {}
    value = extraction_config.get("max_context_lines", 1)
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(count, 5))


def _matched_alias(line: str, metric: dict[str, Any]) -> str:
    aliases = [str(metric.get("label") or "")]
    aliases.extend(str(item) for item in metric.get("aliases", []) if str(item).strip())
    for alias in aliases:
        if alias and alias in line:
            return alias
    return ""


def _context_allowed(line: str, metric: dict[str, Any]) -> bool:
    if _blocked_evaluation_context(line):
        return False
    blocked = [str(item) for item in metric.get("blocked_context_any", []) if str(item).strip()]
    if any(item in line for item in blocked):
        return False
    required = [str(item) for item in metric.get("required_context_any", []) if str(item).strip()]
    return not required or any(item in line for item in required)


def _blocked_evaluation_context(line: str) -> bool:
    text = str(line or "")
    compact = re.sub(r"\s+", "", text)
    return (
        ("满意度" in text and ("问卷" in text or "调查" in text or "学习收获" in text))
        or "学生学习满意度" in text
        or "教育教学整体满意度" in text
        or ("满意度" in compact and ("问卷" in compact or "调查" in compact or "学习收获" in compact))
        or "学生学习满意度" in compact
        or "教育教学整体满意度" in compact
    )


def _candidate_values(line: str, metric: dict[str, Any], alias: str) -> list[tuple[str, float]]:
    unit = str(metric.get("unit") or "")
    search_start = line.find(alias) + len(alias) if alias and alias in line else 0
    if unit == "ratio":
        if alias == "升学" and not _broad_postgrad_alias_allowed(line, search_start):
            return []
        clause = _candidate_clause(line, search_start)
        matches = list(PERCENT_RE.finditer(clause))
        match = _nearest_match(matches, search_start, max_before_distance=8)
        if match and _ratio_match_crosses_other_metric_context(alias, clause[search_start:match.start()]):
            return []
        if match:
            return [(match.group(0), round(float(match.group(1)) / 100, 6))]
        compact_table_match = _compact_table_ratio_match(clause[search_start:])
        if compact_table_match:
            value = compact_table_match.group(1)
            return [(f"{value}%", round(float(value) / 100, 6))]
        occupied = _occupied_ratio_match(clause[search_start:])
        if occupied:
            return [(occupied.group(0), round(float(occupied.group(1)) / 100, 6))]
        return []
    if unit == "score":
        matches = [match for match in NUMBER_RE.finditer(line) if 0 <= float(match.group(1)) <= 100]
        match = _nearest_match(matches, search_start, max_before_distance=8)
        return [(match.group(1), float(match.group(1)))] if match else []
    matches = list(NUMBER_RE.finditer(line))
    match = _nearest_match(matches, search_start, max_before_distance=8)
    return [(match.group(1), float(match.group(1)))] if match else []


def _candidate_clause(line: str, search_start: int) -> str:
    suffix = str(line or "")[search_start:]
    split = CLAUSE_SPLIT_RE.search(suffix)
    if split:
        return str(line or "")[: search_start + split.start()]
    return str(line or "")


def _occupied_ratio_match(clause: str) -> re.Match[str] | None:
    match = re.search(r"占(?:比|本科毕业生总数|毕业生总数|应届本科毕业生总数)?\s*[^%]{0,12}?" + PERCENT_RE.pattern, clause)
    return match


def _compact_table_ratio_match(clause: str) -> re.Match[str] | None:
    return re.search(r"^\s*\d{1,6}(\d{1,2}\.\d+)\s*%", str(clause or ""))


def _broad_postgrad_alias_allowed(line: str, search_start: int) -> bool:
    alias_start = max(0, search_start - len("升学"))
    before = str(line or "")[max(0, alias_start - 4):alias_start]
    if any(item in before for item in ("不含", "除", "国内", "境外", "出国")):
        return False
    after = str(line or "")[search_start:]
    return re.match(r"\s*\d+\s*人", after) is not None


def _ratio_match_crosses_other_metric_context(alias: str, between_text: str) -> bool:
    if "就业率" not in alias and "就业落实率" not in alias and "毕业去向落实率" not in alias:
        return False
    return any(item in str(between_text or "") for item in ("升学", "留学", "出国", "出境", "自主创业"))


def _nearest_match(
    matches: list[re.Match[str]],
    start: int,
    *,
    max_before_distance: int,
) -> re.Match[str] | None:
    if not matches:
        return None
    after = [match for match in matches if match.start() >= start]
    if after:
        return min(after, key=lambda match: match.start() - start)
    before = [
        match
        for match in matches
        if 0 <= start - match.end() <= max_before_distance
    ]
    if before:
        return min(before, key=lambda match: start - match.end())
    return None


def _confidence(alias: str, metric: dict[str, Any], value_count: int) -> str:
    label = str(metric.get("label") or "")
    if value_count != 1:
        return "low"
    if alias == label:
        return "medium"
    return "low"


def _clean_line(value: Any) -> str:
    text = CONTROL_CHAR_RE.sub("", str(value or ""))
    text = SPACE_RE.sub(" ", text.strip())
    return PDF_INLINE_SPACE_RE.sub("", text)


def _quote(line: str) -> str:
    return line[:240]


def _format_number(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"
