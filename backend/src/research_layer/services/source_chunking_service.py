from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from research_layer.services.source_parser import ParsedSegment, ParsedSource

_NUMERIC_HEADING_RE = re.compile(r"^\d+\.\d+(?:\.\d+){0,2}[.)、:：\s-]*\S{1,64}$")
_CJK_HEADING_RE = re.compile(r"^[一二三四五六七八九十]{1,3}[、.)：:\s-]+\S{1,64}$")
_CHAPTER_HEADING_RE = re.compile(r"^第[一二三四五六七八九十\d]{1,6}[章节部分篇][：:\s-]*\S{0,64}$")


@dataclass(frozen=True)
class SourceChunk:
    chunk_id: str
    chunk_index: int
    section_hint: str
    start: int
    end: int
    text: str
    chunk_hash: str


@dataclass(frozen=True)
class SourceChunkPlan:
    source_id: str
    chunks: list[SourceChunk]


class SourceChunkingService:
    def __init__(self, *, max_chars: int = 3200, max_segments: int = 10) -> None:
        self._max_chars = max(400, int(max_chars))
        self._max_segments = max(1, int(max_segments))

    def plan(self, *, source_id: str, parsed: ParsedSource) -> SourceChunkPlan:
        chunks: list[SourceChunk] = []
        pending_segments: list[ParsedSegment] = []
        current_section = "full"
        current_chars = 0

        for segment in parsed.segments:
            text = str(segment.text or "").strip()
            if not text:
                continue
            if self._looks_like_heading(text):
                if pending_segments:
                    chunks.append(
                        self._build_chunk(
                            source_id=source_id,
                            chunk_index=len(chunks),
                            section_hint=current_section,
                            segments=pending_segments,
                        )
                    )
                    pending_segments = []
                    current_chars = 0
                current_section = text
                pending_segments.append(segment)
                current_chars = len(text)
                continue

            next_chars = current_chars + len(text) + (2 if pending_segments else 0)
            if pending_segments and (
                next_chars > self._max_chars
                or len(pending_segments) >= self._max_segments
            ):
                chunks.append(
                    self._build_chunk(
                        source_id=source_id,
                        chunk_index=len(chunks),
                        section_hint=current_section,
                        segments=pending_segments,
                    )
                )
                pending_segments = []
                current_chars = 0
            pending_segments.append(segment)
            current_chars += len(text) + (2 if current_chars else 0)

        if pending_segments:
            chunks.append(
                self._build_chunk(
                    source_id=source_id,
                    chunk_index=len(chunks),
                    section_hint=current_section,
                    segments=pending_segments,
                )
            )

        if not chunks:
            chunks.append(
                SourceChunk(
                    chunk_id=f"{source_id}:chunk:0",
                    chunk_index=0,
                    section_hint="full",
                    start=0,
                    end=len(parsed.normalized_content),
                    text=parsed.normalized_content,
                    chunk_hash=self._hash_text(parsed.normalized_content),
                )
            )
        return SourceChunkPlan(source_id=source_id, chunks=chunks)

    def _build_chunk(
        self,
        *,
        source_id: str,
        chunk_index: int,
        section_hint: str,
        segments: list[ParsedSegment],
    ) -> SourceChunk:
        start = int(segments[0].start)
        end = int(segments[-1].end)
        text = "\n\n".join(str(segment.text).strip() for segment in segments if str(segment.text).strip())
        return SourceChunk(
            chunk_id=f"{source_id}:chunk:{chunk_index}",
            chunk_index=chunk_index,
            section_hint=section_hint or "full",
            start=start,
            end=end,
            text=text,
            chunk_hash=self._hash_text(text),
        )

    def _looks_like_heading(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped or len(stripped) > 80:
            return False
        if "\n" in stripped:
            return False
        digit_count = len(re.findall(r"\d", stripped))
        semantic_letter_count = len(re.findall(r"[A-Za-z\u4e00-\u9fff]", stripped))
        if digit_count >= 1 and semantic_letter_count <= 4 and len(stripped) <= 18:
            return False
        if stripped.endswith(("。", "！", "？", "!", "?", "；", ";", "，", ",")):
            return False
        if _NUMERIC_HEADING_RE.match(stripped):
            return True
        if _CJK_HEADING_RE.match(stripped):
            return True
        return _CHAPTER_HEADING_RE.match(stripped) is not None

    def _hash_text(self, text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
