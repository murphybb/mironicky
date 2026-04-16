from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html import unescape
from threading import Lock


_WHITESPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_RETRYABLE_HTTP_STATUSES = {429, 502, 503, 504}
_PROVIDER_LIMITS = {
    "crossref": {"min_interval_seconds": 0.2, "timeout_seconds": 10.0},
    "semantic_scholar": {"min_interval_seconds": 1.0, "timeout_seconds": 12.0},
}
_RATE_LOCK = Lock()
_LAST_REQUEST_TS: dict[str, float] = {}


@dataclass(slots=True)
class ScholarlyProviderError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return self.message


class ScholarlyConnector:
    def lookup(
        self, *, doi: str | None, title: str | None, request_id: str
    ) -> dict[str, object]:
        normalized_doi = self.normalize_doi(doi)
        normalized_title = self.normalize_title(title)
        if not normalized_doi and not normalized_title:
            raise ScholarlyProviderError(
                status_code=400,
                error_code="research.invalid_request",
                message="scholarly lookup requires doi or title",
                details={},
            )

        provider_trace: list[dict[str, object]] = []
        matches: list[dict[str, object]] = []

        if normalized_doi:
            crossref_record, crossref_trace = self._lookup_crossref_by_doi(
                normalized_doi, request_id
            )
            provider_trace.append(crossref_trace)
            if crossref_record is not None:
                matches.append(crossref_record)
            semantic_key = self._semantic_scholar_key()
            if semantic_key:
                semantic_record, semantic_trace = self._lookup_semantic_scholar_by_doi(
                    normalized_doi, request_id, semantic_key
                )
                provider_trace.append(semantic_trace)
                if semantic_record is not None:
                    matches.append(semantic_record)
        else:
            crossref_record, crossref_trace = self._lookup_crossref_by_title(
                normalized_title, request_id
            )
            provider_trace.append(crossref_trace)
            if crossref_record is not None:
                matches.append(crossref_record)
            if not matches:
                semantic_key = self._semantic_scholar_key()
                if semantic_key:
                    semantic_record, semantic_trace = self._lookup_semantic_scholar_by_title(
                        normalized_title, request_id, semantic_key
                    )
                    provider_trace.append(semantic_trace)
                    if semantic_record is not None:
                        matches.append(semantic_record)

        if not matches:
            raise ScholarlyProviderError(
                status_code=404,
                error_code="research.not_found",
                message="no scholarly result found for source metadata",
                details={
                    "doi": normalized_doi,
                    "title": normalized_title,
                    "provider_trace": provider_trace,
                },
            )

        return {
            "query": normalized_doi or normalized_title or "",
            "matches": matches,
            "provider_trace": provider_trace,
        }

    @staticmethod
    def normalize_doi(doi: str | None) -> str | None:
        raw = (doi or "").strip()
        if not raw:
            return None
        raw = raw.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
        raw = raw.removeprefix("doi:")
        normalized = raw.strip().lower()
        return normalized or None

    @staticmethod
    def normalize_title(title: str | None) -> str | None:
        collapsed = _WHITESPACE_RE.sub(" ", (title or "").strip())
        return collapsed or None

    def _lookup_crossref_by_doi(
        self, doi: str, request_id: str
    ) -> tuple[dict[str, object] | None, dict[str, object]]:
        url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}"
        payload, trace = self._request_json(
            provider_name="crossref",
            url=url,
            request_id=request_id,
            headers=self._crossref_headers(),
        )
        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, dict):
            return None, trace
        return self._normalize_crossref_record(message, lookup_mode="doi"), trace

    def _lookup_crossref_by_title(
        self, title: str, request_id: str
    ) -> tuple[dict[str, object] | None, dict[str, object]]:
        params = urllib.parse.urlencode({"query.title": title, "rows": 5})
        url = f"https://api.crossref.org/works?{params}"
        payload, trace = self._request_json(
            provider_name="crossref",
            url=url,
            request_id=request_id,
            headers=self._crossref_headers(),
        )
        message = payload.get("message") if isinstance(payload, dict) else None
        items = message.get("items") if isinstance(message, dict) else None
        if not isinstance(items, list) or not items:
            return None, trace
        for item in items:
            if isinstance(item, dict):
                return self._normalize_crossref_record(item, lookup_mode="title"), trace
        return None, trace

    def _lookup_semantic_scholar_by_doi(
        self, doi: str, request_id: str, api_key: str
    ) -> tuple[dict[str, object] | None, dict[str, object]]:
        url = (
            "https://api.semanticscholar.org/graph/v1/paper/"
            f"DOI:{urllib.parse.quote(doi, safe='')}"
            "?fields=paperId,title,externalIds,url,venue,year,authors,abstract,"
            "citationCount,influentialCitationCount"
        )
        payload, trace = self._request_json(
            provider_name="semantic_scholar",
            url=url,
            request_id=request_id,
            headers={"x-api-key": api_key},
        )
        if not isinstance(payload, dict):
            return None, trace
        return self._normalize_semantic_scholar_record(payload, "doi"), trace

    def _lookup_semantic_scholar_by_title(
        self, title: str, request_id: str, api_key: str
    ) -> tuple[dict[str, object] | None, dict[str, object]]:
        params = urllib.parse.urlencode(
            {
                "query": title,
                "limit": 5,
                "fields": (
                    "paperId,title,externalIds,url,venue,year,authors,abstract,"
                    "citationCount,influentialCitationCount"
                ),
            }
        )
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}"
        payload, trace = self._request_json(
            provider_name="semantic_scholar",
            url=url,
            request_id=request_id,
            headers={"x-api-key": api_key},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            return None, trace
        for item in data:
            if isinstance(item, dict):
                return self._normalize_semantic_scholar_record(item, "title"), trace
        return None, trace

    def _request_json(
        self,
        *,
        provider_name: str,
        url: str,
        request_id: str,
        headers: dict[str, str],
    ) -> tuple[dict[str, object], dict[str, object]]:
        limits = _PROVIDER_LIMITS[provider_name]
        timeout_seconds = float(limits["timeout_seconds"])
        last_error: ScholarlyProviderError | None = None
        for attempt in range(2):
            self._respect_rate_limit(provider_name)
            request_headers = {
                "Accept": "application/json",
                "X-Request-Id": request_id,
                **headers,
            }
            request = urllib.request.Request(url, headers=request_headers)
            try:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    status_code = int(
                        getattr(response, "status", None) or response.getcode() or 200
                    )
                    raw = response.read().decode("utf-8", errors="ignore")
                    payload = json.loads(raw)
                    trace = {
                        "provider_name": provider_name,
                        "cache_hit": False,
                        "request_id": response.headers.get("X-Request-Id"),
                        "request_url": url,
                        "http_status": status_code,
                    }
                    return payload, trace
            except urllib.error.HTTPError as exc:
                status_code = int(exc.code)
                if status_code in _RETRYABLE_HTTP_STATUSES and attempt == 0:
                    time.sleep(0.5)
                    continue
                if status_code in {401, 403}:
                    raise ScholarlyProviderError(
                        status_code=500,
                        error_code="research.scholarly_provider_misconfigured",
                        message="scholarly provider auth/config missing",
                        details={
                            "provider_name": provider_name,
                            "http_status": status_code,
                            "request_url": url,
                        },
                    ) from exc
                if status_code == 404:
                    return {}, {
                        "provider_name": provider_name,
                        "cache_hit": False,
                        "request_id": exc.headers.get("X-Request-Id")
                        if exc.headers is not None
                        else None,
                        "request_url": url,
                        "http_status": status_code,
                    }
                last_error = ScholarlyProviderError(
                    status_code=503,
                    error_code="research.scholarly_provider_unavailable",
                    message="scholarly provider unavailable",
                    details={
                        "provider_name": provider_name,
                        "http_status": status_code,
                        "request_url": url,
                    },
                )
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                last_error = ScholarlyProviderError(
                    status_code=503,
                    error_code="research.scholarly_provider_unavailable",
                    message="scholarly provider unavailable",
                    details={
                        "provider_name": provider_name,
                        "request_url": url,
                        "reason": str(exc),
                    },
                )
            except json.JSONDecodeError as exc:
                raise ScholarlyProviderError(
                    status_code=404,
                    error_code="research.not_found",
                    message="scholarly provider returned unreadable payload",
                    details={
                        "provider_name": provider_name,
                        "request_url": url,
                        "reason": str(exc),
                    },
                ) from exc
        if last_error is not None:
            raise last_error
        raise ScholarlyProviderError(
            status_code=503,
            error_code="research.scholarly_provider_unavailable",
            message="scholarly provider unavailable",
            details={"provider_name": provider_name, "request_url": url},
        )

    def _crossref_headers(self) -> dict[str, str]:
        mailto = os.getenv("SCHOLARLY_CROSSREF_MAILTO", "").strip()
        if not mailto:
            raise ScholarlyProviderError(
                status_code=500,
                error_code="research.scholarly_provider_misconfigured",
                message="crossref mailto is required",
                details={"provider_name": "crossref"},
            )
        return {
            "User-Agent": f"EverMemOS-Scholarly/1.0 (mailto:{mailto})",
            "mailto": mailto,
        }

    @staticmethod
    def _semantic_scholar_key() -> str | None:
        key = os.getenv("SCHOLARLY_SEMANTIC_SCHOLAR_API_KEY", "").strip()
        return key or None

    def _respect_rate_limit(self, provider_name: str) -> None:
        min_interval_seconds = float(_PROVIDER_LIMITS[provider_name]["min_interval_seconds"])
        with _RATE_LOCK:
            now = time.monotonic()
            last = _LAST_REQUEST_TS.get(provider_name)
            if last is not None:
                elapsed = now - last
                if elapsed < min_interval_seconds:
                    time.sleep(min_interval_seconds - elapsed)
            _LAST_REQUEST_TS[provider_name] = time.monotonic()

    def _normalize_crossref_record(
        self, payload: dict[str, object], *, lookup_mode: str
    ) -> dict[str, object]:
        title_values = payload.get("title")
        title = ""
        if isinstance(title_values, list) and title_values:
            title = str(title_values[0])
        elif isinstance(title_values, str):
            title = title_values
        doi = self.normalize_doi(str(payload.get("DOI") or "")) or None
        venue_values = payload.get("container-title")
        venue = None
        if isinstance(venue_values, list) and venue_values:
            venue = str(venue_values[0]).strip() or None
        authors: list[str] = []
        raw_authors = payload.get("author")
        if isinstance(raw_authors, list):
            for item in raw_authors:
                if not isinstance(item, dict):
                    continue
                given = str(item.get("given") or "").strip()
                family = str(item.get("family") or "").strip()
                full_name = " ".join(part for part in [given, family] if part)
                if full_name:
                    authors.append(full_name)
        abstract = self._normalize_excerpt(payload.get("abstract"))
        return {
            "provider_name": "crossref",
            "provider_record_id": doi or str(payload.get("DOI") or ""),
            "lookup_mode": lookup_mode,
            "title": self.normalize_title(title) or doi or "untitled scholarly record",
            "doi": doi,
            "url": str(payload.get("URL") or "").strip() or None,
            "venue": venue,
            "publication_year": self._extract_year(payload),
            "authors": authors,
            "abstract_snippet": abstract,
            "citation_count": None,
            "influential_citation_count": None,
            "raw_metadata": {
                "type": payload.get("type"),
                "score": payload.get("score"),
            },
        }

    def _normalize_semantic_scholar_record(
        self, payload: dict[str, object], lookup_mode: str
    ) -> dict[str, object]:
        external_ids = payload.get("externalIds")
        doi = None
        if isinstance(external_ids, dict):
            doi = self.normalize_doi(str(external_ids.get("DOI") or ""))
        authors: list[str] = []
        raw_authors = payload.get("authors")
        if isinstance(raw_authors, list):
            for item in raw_authors:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        authors.append(name)
        return {
            "provider_name": "semantic_scholar",
            "provider_record_id": str(payload.get("paperId") or doi or ""),
            "lookup_mode": lookup_mode,
            "title": self.normalize_title(str(payload.get("title") or "")) or doi or "untitled scholarly record",
            "doi": doi,
            "url": str(payload.get("url") or "").strip() or None,
            "venue": self.normalize_title(str(payload.get("venue") or "")),
            "publication_year": int(payload["year"]) if payload.get("year") else None,
            "authors": authors,
            "abstract_snippet": self._normalize_excerpt(payload.get("abstract")),
            "citation_count": int(payload["citationCount"])
            if payload.get("citationCount") is not None
            else None,
            "influential_citation_count": int(payload["influentialCitationCount"])
            if payload.get("influentialCitationCount") is not None
            else None,
            "raw_metadata": {},
        }

    @staticmethod
    def _extract_year(payload: dict[str, object]) -> int | None:
        for key in ("published-print", "published-online", "issued", "created"):
            raw_value = payload.get(key)
            if not isinstance(raw_value, dict):
                continue
            date_parts = raw_value.get("date-parts")
            if (
                isinstance(date_parts, list)
                and date_parts
                and isinstance(date_parts[0], list)
                and date_parts[0]
            ):
                try:
                    return int(date_parts[0][0])
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _normalize_excerpt(raw: object) -> str | None:
        if raw is None:
            return None
        text = _TAG_RE.sub(" ", str(raw))
        text = _WHITESPACE_RE.sub(" ", unescape(text)).strip()
        return text[:400] if text else None
