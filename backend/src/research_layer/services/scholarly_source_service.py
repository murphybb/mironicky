from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.scholarly_connector import (
    ScholarlyConnector,
    ScholarlyProviderError,
)

_METADATA_CACHE_TTL = timedelta(days=30)


@dataclass(slots=True)
class EvidenceRefDraft:
    ref_type: str
    layer: str
    title: str
    doi: str | None
    url: str | None
    venue: str | None
    publication_year: int | None
    authors: list[str]
    excerpt: str
    locator: dict[str, object]
    authority_score: float
    authority_tier: str
    metadata: dict[str, object]


class ScholarlySourceService:
    def __init__(
        self,
        store: ResearchApiStateStore,
        connector: ScholarlyConnector | None = None,
    ) -> None:
        self._store = store
        self._connector = connector or ScholarlyConnector()

    def lookup_and_cache_source(
        self,
        *,
        workspace_id: str,
        source_id: str,
        request_id: str,
        force_refresh: bool = False,
    ) -> dict[str, object]:
        source = self._store.get_source(source_id)
        if source is None:
            raise ScholarlyProviderError(
                status_code=404,
                error_code="research.not_found",
                message="source not found",
                details={"source_id": source_id},
            )
        if str(source["workspace_id"]) != workspace_id:
            raise ScholarlyProviderError(
                status_code=409,
                error_code="research.conflict",
                message="workspace_id does not match source ownership",
                details={"source_id": source_id},
            )

        query = self._build_query(source)
        cached = self._store.list_scholarly_cache_records(normalized_query=query)
        fresh_cached = [item for item in cached if self._is_cache_fresh(item)]
        if fresh_cached and not force_refresh:
            provider_trace = [
                {
                    "provider_name": item["provider_name"],
                    "cache_hit": True,
                    "request_id": item["metadata"].get("request_id")
                    if isinstance(item.get("metadata"), dict)
                    else None,
                    "request_url": item["metadata"].get("request_url")
                    if isinstance(item.get("metadata"), dict)
                    else None,
                    "http_status": item["metadata"].get("http_status")
                    if isinstance(item.get("metadata"), dict)
                    else None,
                }
                for item in fresh_cached
            ]
            self._store.emit_event(
                event_name="scholarly_lookup_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                source_id=source_id,
                component="scholarly_source_service",
                step="lookup",
                status="completed",
                refs={
                    "source_id": source_id,
                    "normalized_query": query,
                    "cache_hit": True,
                    "provider_names": [item["provider_name"] for item in fresh_cached],
                },
                metrics={"cache_record_count": len(fresh_cached)},
            )
            return {
                "source_id": source_id,
                "workspace_id": workspace_id,
                "query": query,
                "cache_hit": True,
                "provider_trace": provider_trace,
                "cache_records": fresh_cached,
                "source_metadata": dict(source.get("metadata", {})),
            }

        try:
            lookup_result = self._connector.lookup(
                doi=self._source_doi(source),
                title=str(source.get("title") or ""),
                request_id=request_id,
            )
        except ScholarlyProviderError as exc:
            self._store.emit_event(
                event_name="scholarly_lookup_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                source_id=source_id,
                component="scholarly_source_service",
                step="lookup",
                status="failed",
                refs={"source_id": source_id, "normalized_query": query, "cache_hit": False},
                error={
                    "error_code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            )
            raise
        except Exception as exc:
            error = ScholarlyProviderError(
                status_code=503,
                error_code="research.scholarly_provider_unavailable",
                message="scholarly provider unavailable",
                details={"provider_name": "crossref", "reason": str(exc)},
            )
            self._store.emit_event(
                event_name="scholarly_lookup_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                source_id=source_id,
                component="scholarly_source_service",
                step="lookup",
                status="failed",
                refs={"source_id": source_id, "normalized_query": query, "cache_hit": False},
                error={
                    "error_code": error.error_code,
                    "message": error.message,
                    "details": error.details,
                },
            )
            raise error from exc

        persisted = [
            self._store.create_scholarly_cache_record(
                normalized_query=query,
                provider_name=str(match["provider_name"]),
                provider_record_id=str(match["provider_record_id"]),
                title=str(match["title"]),
                doi=self._optional_str(match.get("doi")),
                url=self._optional_str(match.get("url")),
                venue=self._optional_str(match.get("venue")),
                publication_year=(
                    int(match["publication_year"])
                    if match.get("publication_year") is not None
                    else None
                ),
                authors=[str(item) for item in match.get("authors", [])],
                abstract_excerpt=self._optional_str(match.get("abstract_snippet")),
                metadata={
                    **(
                        dict(match.get("raw_metadata", {}))
                        if isinstance(match.get("raw_metadata"), dict)
                        else {}
                    ),
                    "lookup_mode": match.get("lookup_mode"),
                    "citation_count": match.get("citation_count"),
                    "influential_citation_count": match.get(
                        "influential_citation_count"
                    ),
                },
                authority_tier=self._authority_tier_from_match(match),
                authority_score=self._authority_score_from_match(match),
            )
            for match in lookup_result["matches"]
        ]
        adopted_metadata = self._merge_source_metadata(
            existing=dict(source.get("metadata", {})),
            cache_records=persisted,
            provider_trace=lookup_result["provider_trace"],
            normalized_query=query,
            cache_hit=False,
        )
        self._store.update_source_metadata(source_id=source_id, metadata=adopted_metadata)
        self._store.emit_event(
            event_name="scholarly_lookup_completed",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            source_id=source_id,
            component="scholarly_source_service",
            step="lookup",
            status="completed",
            refs={
                "source_id": source_id,
                "normalized_query": query,
                "cache_hit": False,
                "provider_names": [item["provider_name"] for item in persisted],
            },
            metrics={"cache_record_count": len(persisted)},
        )
        return {
            "source_id": source_id,
            "workspace_id": workspace_id,
            "query": query,
            "cache_hit": False,
            "provider_trace": lookup_result["provider_trace"],
            "cache_records": persisted,
            "source_metadata": adopted_metadata,
        }

    def persist_evidence_refs_for_confirmation(
        self,
        *,
        candidate: dict[str, object],
        object_type: str,
        object_id: str,
        request_id: str,
        conn=None,
    ) -> list[dict[str, object]]:
        source = self._store.get_source(str(candidate["source_id"]), conn=conn)
        metadata = dict(source.get("metadata", {})) if isinstance(source, dict) else {}
        base_title = str(
            metadata.get("scholarly_title") or source.get("title") or "scholarly source"
        )
        doi = self._optional_str(metadata.get("doi"))
        url = self._optional_str(metadata.get("url"))
        venue = self._optional_str(metadata.get("venue"))
        publication_year = (
            int(metadata["publication_year"])
            if metadata.get("publication_year") is not None
            else None
        )
        authors = self._normalize_authors(metadata.get("authors"))
        authority_tier = self._authority_tier_from_source(source or {}, metadata)
        authority_score = self._authority_score_from_source(source or {}, metadata)
        locator = self._normalize_locator(candidate.get("source_span"))

        drafts = [
            EvidenceRefDraft(
                ref_type="literature" if str(source.get("source_type")) == "paper" else "note",
                layer="work",
                title=base_title,
                doi=doi,
                url=url,
                venue=venue,
                publication_year=publication_year,
                authors=authors,
                excerpt=str(source.get("title") or base_title),
                locator={"source_id": candidate["source_id"], "scope": "work"},
                authority_score=authority_score,
                authority_tier=authority_tier,
                metadata={
                    "source_input_mode": metadata.get("source_input_mode"),
                    "external_provider": metadata.get("external_provider"),
                },
            ),
            EvidenceRefDraft(
                ref_type="literature" if str(source.get("source_type")) == "paper" else "note",
                layer="fragment",
                title=base_title,
                doi=doi,
                url=url,
                venue=venue,
                publication_year=publication_year,
                authors=authors,
                excerpt=str(candidate.get("text") or ""),
                locator=locator,
                authority_score=min(1.0, authority_score + 0.03),
                authority_tier=authority_tier,
                metadata={
                    "candidate_id": candidate.get("candidate_id"),
                    "candidate_batch_id": candidate.get("candidate_batch_id"),
                    "request_id": request_id,
                },
            ),
        ]

        created: list[dict[str, object]] = []
        for draft in drafts:
            created.append(
                self._store.create_evidence_ref(
                    workspace_id=str(candidate["workspace_id"]),
                    source_id=str(candidate["source_id"]),
                    object_type=object_type,
                    object_id=object_id,
                    ref_type=draft.ref_type,
                    layer=draft.layer,
                    title=draft.title,
                    doi=draft.doi,
                    url=draft.url,
                    venue=draft.venue,
                    publication_year=draft.publication_year,
                    authors=draft.authors,
                    excerpt=draft.excerpt,
                    locator=draft.locator,
                    authority_score=draft.authority_score,
                    authority_tier=draft.authority_tier,
                    metadata=draft.metadata,
                    confirmed_at=self._store.now(),
                    conn=conn,
                )
            )
        return created

    def _build_query(self, source: dict[str, object]) -> str:
        doi = self._source_doi(source)
        if doi:
            return f"doi:{doi}"
        title = self._connector.normalize_title(str(source.get("title") or ""))
        if title:
            return f"title:{title.lower()}"
        raise ScholarlyProviderError(
            status_code=400,
            error_code="research.invalid_request",
            message="source is missing scholarly lookup identifiers",
            details={"source_id": source.get("source_id")},
        )

    def _source_doi(self, source: dict[str, object]) -> str | None:
        metadata = source.get("metadata")
        doi = None
        if isinstance(metadata, dict):
            doi = metadata.get("doi")
            if (
                str(metadata.get("source_input_mode") or "").strip().lower() == "local_file"
                and not self._is_present_metadata_value(doi)
            ):
                return None
        return self._connector.normalize_doi(str(doi or ""))

    def _is_present_metadata_value(self, value: object | None) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

    def _is_cache_fresh(self, item: dict[str, object]) -> bool:
        created_at = item.get("created_at")
        if created_at is None:
            return False
        return (self._store.now() - created_at) <= _METADATA_CACHE_TTL

    def _merge_source_metadata(
        self,
        *,
        existing: dict[str, object],
        cache_records: list[dict[str, object]],
        provider_trace: list[dict[str, object]],
        normalized_query: str,
        cache_hit: bool,
    ) -> dict[str, object]:
        merged = dict(existing)
        source_input_mode = str(merged.get("source_input_mode") or "").strip().lower()
        local_file_mode = source_input_mode == "local_file"
        if cache_records:
            preferred = cache_records[0]
            merged["doi"] = preferred.get("doi") or merged.get("doi")
            merged["url"] = preferred.get("url") or merged.get("url")
            merged["venue"] = preferred.get("venue") or merged.get("venue")
            if not local_file_mode:
                merged["publication_year"] = preferred.get("publication_year") or merged.get(
                    "publication_year"
                )
            if preferred.get("authors"):
                merged["authors"] = preferred["authors"]
            if not local_file_mode:
                merged["scholarly_title"] = preferred.get("title") or merged.get("scholarly_title")
            merged["external_provider"] = preferred.get("provider_name")
        merged["scholarly_lookup"] = {
            "normalized_query": normalized_query,
            "cache_hit": cache_hit,
            "provider_names": [item["provider_name"] for item in cache_records],
            "cache_record_ids": [item["cache_id"] for item in cache_records],
            "provider_trace": provider_trace,
        }
        return merged

    def _authority_tier_from_match(self, match: dict[str, object]) -> str:
        if match.get("doi"):
            return "tier_a_peer_reviewed"
        return "tier_e_unverified_external"

    def _authority_score_from_match(self, match: dict[str, object]) -> float:
        score = 0.95 if match.get("doi") else 0.25
        if match.get("venue"):
            score += 0.02
        if match.get("authors"):
            score += 0.01
        return min(1.0, round(score, 4))

    def _authority_tier_from_source(
        self, source: dict[str, object], metadata: dict[str, object]
    ) -> str:
        if str(source.get("source_type")) == "paper" and metadata.get("doi"):
            return "tier_a_peer_reviewed"
        if str(source.get("source_type")) == "paper":
            return "tier_b_preprint_or_official_report"
        if str(source.get("source_type")) in {"note", "failure_record"}:
            return "tier_c_internal_research_note"
        return "tier_d_feedback_or_dialogue"

    def _authority_score_from_source(
        self, source: dict[str, object], metadata: dict[str, object]
    ) -> float:
        tier = self._authority_tier_from_source(source, metadata)
        base = {
            "tier_a_peer_reviewed": 0.95,
            "tier_b_preprint_or_official_report": 0.80,
            "tier_c_internal_research_note": 0.60,
            "tier_d_feedback_or_dialogue": 0.45,
        }.get(tier, 0.25)
        if metadata.get("venue"):
            base += 0.02
        if metadata.get("authors"):
            base += 0.01
        return min(1.0, round(base, 4))

    def _normalize_locator(self, raw_locator: object) -> dict[str, object]:
        if not isinstance(raw_locator, dict):
            return {}
        char_start = raw_locator.get("char_start", raw_locator.get("start"))
        char_end = raw_locator.get("char_end", raw_locator.get("end"))
        return {
            "section": raw_locator.get("section"),
            "paragraph_index": raw_locator.get("paragraph_index"),
            "char_start": char_start,
            "char_end": char_end,
            # Keep aliases for consumers that still read source_span style offsets.
            "start": char_start,
            "end": char_end,
            "chunk_id": raw_locator.get("chunk_id"),
            "text": raw_locator.get("text"),
        }

    @staticmethod
    def _optional_str(raw: object) -> str | None:
        if raw is None:
            return None
        normalized = str(raw).strip()
        return normalized or None

    @staticmethod
    def _normalize_authors(raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]
