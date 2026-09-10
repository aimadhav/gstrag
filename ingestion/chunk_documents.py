import re
from .clean_text import clean_text

def chunk_sections(text: str, target_words: int = 650, overlap_words: int = 100) -> list[dict]:
    """Section-aware baseline chunker retaining heading context and page markers."""
    text = clean_text(text)
    sections, current = [], []
    for line in text.splitlines():
        if re.match(r"^(chapter|section|\d+(?:\.\d+)*)\b", line, re.I) and current:
            sections.append(current); current = []
        current.append(line)
    if current: sections.append(current)
    result = []
    for section in sections:
        words = " ".join(section).split()
        if len(words) <= target_words:
            result.append({"content": " ".join(words), "section_path": section[:1]})
            continue
        for start in range(0, len(words), max(1, target_words-overlap_words)):
            part = words[start:start+target_words]
            if part: result.append({"content": " ".join(part), "section_path": section[:1]})
    return result
