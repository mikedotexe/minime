"""Research parsing, quality, memory admission, and rendering primitives."""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ResearchHit:
    title: str
    snippet: str
    url: str


@dataclass
class ResearchOutcome:
    source_kind: str
    raw_text: str
    anchor: str
    meaning_summary: str
    hits: List[ResearchHit] = field(default_factory=list)
    url: Optional[str] = None
    soft_failure_reason: Optional[str] = None

    def succeeded(self) -> bool:
        return self.soft_failure_reason is None

    def prompt_body(self) -> str:
        if self.source_kind == "search":
            return (
                f"{self.meaning_summary}\n\nTop results:\n"
                f"{format_research_hits(self.hits)}"
            )
        return self.raw_text


def text_quality_flags(text: str) -> Dict[str, Any]:
    replacement_count = text.count("\ufffd")
    control_count = sum(
        1 for char in text if ord(char) < 32 and char not in "\n\t\r"
    )
    length = max(len(text), 1)
    return {
        "replacement_char_count": replacement_count,
        "control_char_count": control_count,
        "replacement_ratio": replacement_count / length,
        "control_ratio": control_count / length,
        "starts_with_pdf_header": text.lstrip().startswith("%PDF-"),
    }


def text_looks_noisy_or_binary(text: str) -> bool:
    flags = text_quality_flags(text)
    return (
        bool(flags["starts_with_pdf_header"])
        or flags["replacement_char_count"] >= 12
        or flags["control_char_count"] >= 24
        or flags["replacement_ratio"] > 0.01
        or flags["control_ratio"] > 0.01
    )


def response_looks_like_pdf(url: str, content_type: str, body: bytes) -> bool:
    lowered_type = content_type.lower()
    lowered_url = url.lower().split("?", 1)[0]
    return (
        "application/pdf" in lowered_type
        or lowered_url.endswith(".pdf")
        or body.lstrip().startswith(b"%PDF-")
    )


def response_looks_textual(content_type: str) -> bool:
    lowered = content_type.lower()
    return (
        not lowered
        or lowered.startswith("text/")
        or "html" in lowered
        or "xml" in lowered
        or "json" in lowered
    )


RESEARCH_MEMORY_STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "being",
    "below",
    "could",
    "current",
    "entry",
    "feels",
    "first",
    "given",
    "having",
    "might",
    "private",
    "should",
    "state",
    "their",
    "there",
    "these",
    "think",
    "those",
    "through",
    "today",
    "where",
    "which",
    "while",
    "would",
    "write",
    "yourself",
}


def research_memory_keywords(text: str) -> List[str]:
    words = re.findall(r"[a-z][a-z0-9_-]{4,}", text.lower())
    return sorted(
        {
            word.strip("-_")
            for word in words
            if len(word.strip("-_")) > 4
            and word.strip("-_") not in RESEARCH_MEMORY_STOPWORDS
        }
    )


def quality_flags_indicate_noise(quality: Dict[str, Any]) -> bool:
    return (
        bool(quality.get("starts_with_pdf_header"))
        or int(quality.get("replacement_char_count") or 0) >= 12
        or int(quality.get("control_char_count") or 0) >= 24
        or float(quality.get("replacement_ratio") or 0.0) > 0.01
        or float(quality.get("control_ratio") or 0.0) > 0.01
    )


def research_entry_allowed_for_memory(entry: Dict[str, Any]) -> bool:
    if entry.get("memory_injection_allowed") is False:
        return False
    if entry.get("source") != "search":
        return False
    if not str(entry.get("meaning_summary") or "").strip():
        return False
    quality = entry.get("quality")
    if isinstance(quality, dict) and quality_flags_indicate_noise(quality):
        return False
    results = str(entry.get("results") or "")
    return not text_looks_noisy_or_binary(results)


def trim_chars(text: str, max_chars: int) -> str:
    return text[:max_chars]


def format_research_hits(hits: List[ResearchHit]) -> str:
    lines = []
    for idx, hit in enumerate(hits, start=1):
        lines.append(
            f"{idx}. {hit.title}\n"
            f"   {hit.snippet}\n"
            f"   URL: {hit.url}"
        )
    return "\n".join(lines)


def render_hits_plain(hits: List[ResearchHit]) -> str:
    return "\n\n".join(
        f"{hit.title} — {hit.snippet} [{hit.url}]" for hit in hits
    )


def decode_ddg_result_url(raw_url: str) -> Optional[str]:
    from urllib.parse import unquote

    if "uddg=" in raw_url:
        encoded = raw_url.split("uddg=", 1)[1].split("&", 1)[0]
        return unquote(encoded)
    if raw_url.startswith("http"):
        return raw_url
    return None


def extract_duckduckgo_anchors(html_text: str) -> List[tuple]:
    anchors = []
    pos = 0
    while True:
        idx = html_text.find("result__a", pos)
        if idx < 0:
            break
        href_idx = html_text.find('href="', idx)
        if href_idx < 0:
            pos = idx + 8
            continue
        href_start = href_idx + 6
        href_end = html_text.find('"', href_start)
        if href_end < 0:
            pos = href_start
            continue
        raw_url = html_text[href_start:href_end].strip()
        url = decode_ddg_result_url(raw_url)
        gt = html_text.find(">", idx)
        end = html_text.find("</a>", gt)
        if gt < 0 or end < 0:
            pos = idx + 8
            continue
        import re
        import html as html_mod
        title = re.sub(r"<[^>]+>", "", html_text[gt + 1:end]).strip()
        title = html_mod.unescape(title)
        if url and url.startswith("http"):
            anchors.append((url, trim_chars(title, 200)))
        pos = end + 4
        if len(anchors) >= 5:
            break
    return anchors


def extract_duckduckgo_snippets(html_text: str) -> List[str]:
    import re
    import html as html_mod

    snippets = []
    pos = 0
    while len(snippets) < 5:
        idx = html_text.find("result__snippet", pos)
        if idx < 0:
            break
        gt = html_text.find(">", idx)
        end = html_text.find("</", gt)
        if gt < 0 or end < 0:
            break
        raw = html_text[gt + 1:end]
        clean = re.sub(r"<[^>]+>", "", raw).strip()
        clean = html_mod.unescape(clean)
        if len(clean) > 20:
            snippets.append(trim_chars(clean, 600))
        pos = end
    return snippets


def extract_duckduckgo_hits(html_text: str) -> List[ResearchHit]:
    anchors = extract_duckduckgo_anchors(html_text)
    snippets = extract_duckduckgo_snippets(html_text)
    hits = []
    for idx, (url, title) in enumerate(anchors):
        snippet = snippets[idx] if idx < len(snippets) else ""
        if title or snippet:
            hits.append(
                ResearchHit(
                    title=title or trim_chars(snippet, 80),
                    snippet=snippet,
                    url=url,
                )
            )
    return hits[:5]


def extract_html_title(html_text: str) -> Optional[str]:
    lower = html_text.lower()
    start = lower.find("<title")
    if start < 0:
        return None
    gt = lower.find(">", start)
    end = lower.find("</title>", gt)
    if gt < 0 or end < 0:
        return None
    import re
    import html as html_mod
    title = re.sub(r"<[^>]+>", "", html_text[gt + 1:end]).strip()
    return html_mod.unescape(title) or None


def classify_soft_failure(status_code: int, title: Optional[str], cleaned: str) -> Optional[str]:
    if status_code != 200:
        return f"HTTP {status_code} from the source."

    trimmed = cleaned.strip()
    if len(trimmed) < 50:
        return "The page content was too short to be meaningfully readable."

    title_lower = (title or "").lower()
    prefix = trim_chars(trimmed.lower(), 500)
    signals = [
        "page not found",
        "not found",
        "access denied",
        "enable javascript",
        "forbidden",
        "error",
        "bad request",
        "service unavailable",
        "you are trying to reach cannot be found",
    ]

    if len(trimmed) < 180:
        for signal in signals:
            if signal in title_lower or signal in prefix:
                return f"The page appears to be an error or access-gate page ({signal})."

    signal_count = sum(1 for signal in signals if signal in title_lower or signal in prefix)
    if signal_count >= 2:
        return "The page content is dominated by error-template language instead of readable material."

    return None


def slug_anchor_from_url(url: str) -> str:
    after_scheme = url.split("://", 1)[-1]
    path = after_scheme.split("/", 1)[-1]
    pieces = []
    for chunk in re.split(r"[/?#\-_+=]+", path):
        chunk = chunk.strip()
        if len(chunk) > 2:
            pieces.append(chunk)
        if len(pieces) >= 6:
            break
    return trim_chars(" ".join(pieces) or url, 120)


def derive_browse_anchor(preferred: Optional[str], context: Optional[str], url: str) -> str:
    if preferred and preferred.strip():
        return trim_chars(" ".join(preferred.split()), 160)
    if context and context.strip():
        return trim_chars(" ".join(context.split()), 160)
    return slug_anchor_from_url(url)


def format_browse_failure_context(url: str, reason: str) -> str:
    return (
        f"[Web access status: the page at {url} could not be meaningfully read: {reason}]\n"
        "[This is ordinary source/site availability, not evidence of a perceptual gate, "
        "internal topology boundary, or spectral event.]\n"
        "[Keep the concrete topic from the URL if useful, but do not build an experience "
        "around the access failure.]\n\n"
        "[Try NEXT: SEARCH with a narrower question, NEXT: BROWSE a different reliable "
        "source, or NEXT: REST.]"
    )


def format_browse_read_context(outcome: ResearchOutcome, chunk: str, remaining: Optional[int]) -> str:
    header = (
        f"[You read the page at {outcome.url}]"
        if remaining is not None
        else f"[You read the full page at {outcome.url}]"
    )
    continuation = (
        f"\n\n[Page continues — {remaining:,} more chars. Write NEXT: READ_MORE to continue reading.]"
        if remaining is not None
        else ""
    )
    return f"{header}\n\n{outcome.meaning_summary}\n\n{chunk}{continuation}"


def format_read_more_context(offset: int, chunk: str, remaining: int, meaning_summary: Optional[str]) -> str:
    summary_block = (
        f"[Meaning summary from this document:]\n{meaning_summary}\n\n"
        if meaning_summary
        else ""
    )
    continuation = (
        f"\n\n[{remaining:,} more chars remain. Write NEXT: READ_MORE to continue.]"
        if remaining > 0
        else "\n\n[End of document.]"
    )
    return (
        f"{summary_block}[Continuing reading from offset {offset:,}...]\n\n"
        f"{chunk}{continuation}"
    )


def extract_label_value(raw: Optional[str], label: str) -> Optional[str]:
    if not raw:
        return None
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith(label):
            value = stripped[len(label):].strip()
            if value:
                return trim_chars(value, 220)
    return None


__all__ = [
    "RESEARCH_MEMORY_STOPWORDS",
    "ResearchHit",
    "ResearchOutcome",
    "classify_soft_failure",
    "decode_ddg_result_url",
    "derive_browse_anchor",
    "extract_duckduckgo_anchors",
    "extract_duckduckgo_hits",
    "extract_duckduckgo_snippets",
    "extract_html_title",
    "extract_label_value",
    "format_browse_failure_context",
    "format_browse_read_context",
    "format_read_more_context",
    "format_research_hits",
    "quality_flags_indicate_noise",
    "render_hits_plain",
    "research_entry_allowed_for_memory",
    "research_memory_keywords",
    "response_looks_like_pdf",
    "response_looks_textual",
    "slug_anchor_from_url",
    "text_looks_noisy_or_binary",
    "text_quality_flags",
    "trim_chars",
]
