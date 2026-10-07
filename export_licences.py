"""Retrieval helpers for public Finnish Government defence-export decisions."""

from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests


ARCHIVE_URL = "https://valtioneuvosto.fi/paatokset/valtioneuvoston-yleisistunto"
SOURCE_LABEL = "Valtioneuvosto, plenary session decision archive"
CACHE_DIR = Path(__file__).parent / "data" / "export-licences"
_PORTLET = (
    "_fi_yja_web_content_listing_portlet_WebContentListingPortlet_INSTANCE_"
    "IYuXlckgMSsA"
)
_SESSION_RE = re.compile(r"/paatokset/istunto\?sessionId=([A-Za-z0-9]+)")
_DECISION_RE = re.compile(r"/paatokset/paatos\?decisionId=([A-Za-z0-9]+)")
_LICENCE_TITLE_RE = re.compile(
    r"(?:^|\s)vientiluvan\s+myöntäminen", re.IGNORECASE
)
_EXPORTER_RE = re.compile(
    r"vientiluvan\s+myöntäminen\s+(.+?):lle(?:\s|$)", re.IGNORECASE
)
_SESSION_DATE_RE = re.compile(
    r"Istunnon ajankohta\s+(\d{1,2}\.\d{1,2}\.\d{4})", re.IGNORECASE
)


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.text = []
        self._anchor_href = None
        self._anchor_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._anchor_href = dict(attrs).get("href")
            self._anchor_text = []

    def handle_data(self, data):
        self.text.append(data)
        if self._anchor_href is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor_href is not None:
            self.links.append(
                (self._anchor_href, " ".join(" ".join(self._anchor_text).split()))
            )
            self._anchor_href = None
            self._anchor_text = []


def _parse_html(content):
    parser = _PageParser()
    parser.feed(content)
    return parser


def _year_page_url(year, page):
    params = {
        "p_p_id": "fi_yja_web_content_listing_portlet_WebContentListingPortlet_INSTANCE_IYuXlckgMSsA",
        "p_p_lifecycle": "0",
        "p_p_state": "normal",
        "p_p_mode": "view",
        f"{_PORTLET}_mvcRenderCommandName": "/webcontentisting/articles/view",
        f"{_PORTLET}_paramYear": str(year),
        f"{_PORTLET}_paramPage": str(page),
    }
    return f"{ARCHIVE_URL}?{urlencode(params)}"


def _get(url, session):
    response = session.get(
        url,
        timeout=30,
        headers={"User-Agent": "Haitem/0.1 (public-data visualization)"},
    )
    response.raise_for_status()
    return response.text


def _enumerate_sessions(year, session):
    first_page = _parse_html(_get(_year_page_url(year, 1), session))
    max_page = 1
    for href, _ in first_page.links:
        query = parse_qs(urlparse(href).query)
        for key, values in query.items():
            if key.endswith("_paramPage"):
                for value in values:
                    if value.isdigit():
                        max_page = max(max_page, int(value))

    session_ids = set()
    for page_number in range(1, max_page + 1):
        page = first_page if page_number == 1 else _parse_html(
            _get(_year_page_url(year, page_number), session)
        )
        for href, _ in page.links:
            match = _SESSION_RE.search(href)
            if match:
                session_ids.add(match.group(1))
        if page_number < max_page:
            time.sleep(0.2)
    return sorted(session_ids)


def _decision_records_from_session(session_id, session):
    session_url = f"https://valtioneuvosto.fi/paatokset/istunto?sessionId={session_id}"
    page = _parse_html(_get(session_url, session))
    page_text = " ".join(" ".join(page.text).split())
    date_match = _SESSION_DATE_RE.search(page_text)
    decision_date = date_match.group(1) if date_match else None
    records = []
    for href, title in page.links:
        decision_match = _DECISION_RE.search(href)
        if not decision_match or not _LICENCE_TITLE_RE.search(title):
            continue
        exporter_match = _EXPORTER_RE.search(title)
        records.append(
            {
                "decisionId": decision_match.group(1),
                "decisionDate": decision_date,
                "decisionTitle": title,
                "exporter": exporter_match.group(1).strip() if exporter_match else None,
                "sourceUrl": urljoin(session_url, href),
                "sourceSessionUrl": session_url,
                "source": SOURCE_LABEL,
            }
        )
    return records


def _cache_path(year):
    return CACHE_DIR / f"decisions-{year}.json"


def load_year(year, refresh=False):
    """Load a year's decisions from the persistent cache or the official archive."""
    cache_path = _cache_path(year)
    if cache_path.exists() and not refresh:
        with cache_path.open(encoding="utf-8") as cache_file:
            return json.load(cache_file)

    session = requests.Session()
    session_ids = _enumerate_sessions(year, session)
    records = []
    warnings = []
    retrieval_failed = False
    for index, session_id in enumerate(session_ids):
        try:
            session_records = _decision_records_from_session(session_id, session)
            for record in session_records:
                if record["exporter"] is None:
                    warnings.append(
                        f"Could not extract exporter from {record['sourceUrl']}: "
                        f"{record['decisionTitle']}"
                    )
                if record["decisionDate"] is None:
                    warnings.append(
                        f"Could not extract session date from {record['sourceSessionUrl']}."
                    )
            records.extend(session_records)
        except requests.RequestException as error:
            retrieval_failed = True
            warnings.append(f"Could not retrieve session {session_id}: {error}")
        if index < len(session_ids) - 1:
            time.sleep(0.2)

    dataset = {
        "year": year,
        "sourceUrl": ARCHIVE_URL,
        "retrievedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "records": records,
        "warnings": warnings,
    }
    if not retrieval_failed:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as cache_file:
            json.dump(dataset, cache_file, ensure_ascii=False, indent=2)
            cache_file.write("\n")
    return dataset


def decisions_in_period(datasets, start_date=None, end_date=None):
    """Return cached decisions in an inclusive date range."""
    decisions = []
    for dataset in datasets:
        for record in dataset["records"]:
            raw_date = record["decisionDate"]
            if start_date or end_date:
                if not raw_date:
                    continue
                try:
                    decision_date = datetime.strptime(raw_date, "%d.%m.%Y").date()
                except ValueError:
                    continue
                if start_date and decision_date < start_date:
                    continue
                if end_date and decision_date > end_date:
                    continue
            decisions.append(record)
    return sorted(
        decisions,
        key=lambda record: (
            record["decisionDate"] or "",
            record["decisionId"],
        ),
    )


def top_exporters(datasets, start_date=None, end_date=None, limit=5):
    """Rank exact normalized exporter names by listed decision count."""
    exporters = {}
    for record in decisions_in_period(datasets, start_date, end_date):
        exporter = record["exporter"]
        if not exporter:
            continue
        key = " ".join(exporter.casefold().split())
        entry = exporters.setdefault(key, {"Exporter": exporter, "Decisions": 0})
        entry["Decisions"] += 1
    ranked = sorted(
        exporters.values(),
        key=lambda item: (-item["Decisions"], item["Exporter"].casefold()),
    )
    return ranked[:limit]
