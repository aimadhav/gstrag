import re

def clean_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not re.fullmatch(r"(?:page\s*)?\d+", line, re.I)]
    out = []
    for line in lines:
        if not out or line != out[-1]: out.append(line)
    return "\n".join(out)
