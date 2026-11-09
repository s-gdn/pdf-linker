"""The shared, meaning-preserving input contract for every matching tier."""
import re
import unicodedata


def normalize_phrase(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def prepare_query(label: str, context: str = "") -> str:
    return normalize_phrase(f"{context} {label}" if context.strip() else label)
