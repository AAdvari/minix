# Layout-aware document pre-processor: noise removal, section detection, metadata tagging.
import re
from dataclasses import dataclass


@dataclass
class TextSection:
    content: str
    section_type: str
    level: int = 0
    page: int | None = None
    parent_heading: str = ""


_PAGE_NUMBER = re.compile(
    r"^\s*[-–—]?\s*(?:page|pg\.?|p\.?)?\s*\d+\s*(?:of\s*\d+)?\s*[-–—]?\s*$",
    re.IGNORECASE,
)
_HEADER_FOOTER = re.compile(
    r"^\s*(?:confidential|draft|internal use only|all rights reserved|"
    r"copyright\s*©?\s*\d{4}|proprietary)\s*$",
    re.IGNORECASE,
)
_REPEATED_CHARS = re.compile(r"^(.)\1{20,}$")

_HEADING_PATTERNS = [
    re.compile(r"^(\d+(?:\.\d+)*)\.?\s+([A-Z].{2,})$"),
    re.compile(r"^(?:chapter|section|part)\s+\d+[.:]\s*(.+)$", re.IGNORECASE),
    re.compile(r"^([A-Z][A-Z\s]{5,78}[A-Z])$"),
]

_LIST_ITEM = re.compile(r"^\s*(?:[-•●○▪]\s+|\d+[.)]\s+|[a-z][.)]\s+)")
_TABLE_LINE = re.compile(r"^.*\|.*\|")
_CODE_FENCE = re.compile(r"^```")

# Tokens that look like code/tech identifiers, URLs, or emails — never headings.
# Used to suppress false positives like "Node.js", "C++", "v1.2.3", "x@y.com".
_TECH_TOKEN = re.compile(
    r"(?:://|@|[A-Za-z]\+\+|#[A-Za-z]|\.js\b|\.ts\b|\.py\b|\.io\b|\.com\b|\.net\b|\.org\b"
    r"|\b\w+\.\w+(?:\.\w+)*\b)",
    re.IGNORECASE,
)

# Common lower-case stop words that are allowed mid-heading (e.g. "Table of Contents").
_HEADING_STOPWORDS = {
    "a", "an", "and", "of", "the", "to", "for", "in", "on", "with", "by",
    "or", "as", "at", "from", "is", "vs",
}


def _is_fallback_heading(stripped: str) -> bool:
    """Structural heading detection for lines not caught by the explicit patterns.

    Tightened from the original permissive rule to avoid over-fragmenting documents
    that contain tech-term fragments (e.g. "Node.js", "C++") which previously
    tripped the heuristic and emitted one-word chunks.
    """
    if len(stripped) > 60 or len(stripped) < 3:
        return False
    if stripped.endswith(".") or stripped.endswith(","):
        return False
    if not stripped[0].isupper():
        return False
    if _LIST_ITEM.match(stripped):
        return False
    if _TECH_TOKEN.search(stripped):
        return False

    words = stripped.split()
    if not (1 <= len(words) <= 8):
        return False

    # Single-word heading: must be alphabetic (allowing a trailing colon) and
    # at least 4 chars — filters "Go", "R", "I", "v1", anything with digits or
    # mid-word symbols, while still accepting "Education" and "Experience:".
    if len(words) == 1:
        core = words[0].rstrip(":;")
        return core.isalpha() and len(core) >= 4

    # Multi-word: accept if it ends with a colon, OR if every word is either
    # Uppercase-initial or a stopword (title-case-ish).
    if stripped.rstrip().endswith(":"):
        return True
    ok = 0
    for w in words:
        if w[0].isupper() or w.lower() in _HEADING_STOPWORDS:
            ok += 1
    return ok == len(words)


def remove_noise(text: str) -> str:
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append("")
            continue
        if _PAGE_NUMBER.match(stripped):
            continue
        if _HEADER_FOOTER.match(stripped):
            continue
        if _REPEATED_CHARS.match(stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def detect_sections(text: str) -> list[TextSection]:
    lines = text.splitlines()
    sections: list[TextSection] = []
    current_lines: list[str] = []
    current_type = "paragraph"
    current_heading = ""
    in_code_block = False

    def _flush():
        nonlocal current_lines
        content = "\n".join(current_lines).strip()
        if content:
            level = 0
            if current_type == "heading":
                match = re.match(r"^(\d+(?:\.\d+)*)", content)
                level = len(match.group(1).split(".")) if match else 1
            sections.append(TextSection(
                content=content,
                section_type=current_type,
                level=level,
                parent_heading=current_heading,
            ))
        current_lines = []

    for line in lines:
        stripped = line.strip()

        if _CODE_FENCE.match(stripped):
            if in_code_block:
                current_lines.append(line)
                in_code_block = False
                _flush()
                current_type = "paragraph"
                continue
            else:
                _flush()
                current_type = "code"
                in_code_block = True
                current_lines.append(line)
                continue

        if in_code_block:
            current_lines.append(line)
            continue

        if not stripped:
            if current_lines:
                _flush()
                current_type = "paragraph"
            continue

        is_heading = False
        for pattern in _HEADING_PATTERNS:
            if pattern.match(stripped):
                is_heading = True
                break

        if not is_heading and _is_fallback_heading(stripped):
            is_heading = True

        if is_heading and current_type != "heading":
            _flush()
            current_type = "heading"
            current_heading = stripped
            current_lines.append(line)
            _flush()
            current_type = "paragraph"
            continue

        if _TABLE_LINE.match(stripped):
            if current_type != "table":
                _flush()
                current_type = "table"
            current_lines.append(line)
            continue

        if _LIST_ITEM.match(stripped):
            if current_type != "list":
                _flush()
                current_type = "list"
            current_lines.append(line)
            continue

        if current_type in ("table", "list"):
            _flush()
            current_type = "paragraph"
        current_lines.append(line)

    _flush()
    return sections
