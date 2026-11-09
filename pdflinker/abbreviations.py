"""Infer initialisms from this document's phrases, without a business dictionary."""
from collections import defaultdict
import re

from .text_normalization import normalize_phrase


_INITIALISM = re.compile(r'(?<!\w)(?:[A-Za-z](?:[/.-][A-Za-z]){1,5}\.?|[A-Z]{2,6})(?!\w)')
_EXPANSION = re.compile(r'(?<!\w)(?:[a-z](?:[/ .-]+[a-z]){1,5}\.?|[a-z]{2,6})(?!\w)')


def _key(value):
    return ''.join(re.findall(r'[a-z]',value.casefold()))


def abbreviation_candidates(fields, columns):
    """Return each detected initialism and its document-backed possibilities."""
    texts=list(columns)
    for field in fields:
        texts.extend(p for p in (field.pdf_label,field.label,field.section,field.question,field.context) if p)
    texts=list(dict.fromkeys(texts))
    spaced=[re.sub(r'([A-Z]+)([A-Z][a-z])',r'\1 \2',text) for text in texts]
    keys={_key(m.group()) for text in spaced for m in _INITIALISM.finditer(text)}
    # Words such as RENT in an uppercase heading are not automatically acronyms.
    words={word.casefold() for text in texts for word in re.findall(r'[A-Za-z]{2,}',text) if not word.isupper()}
    keys-=words
    candidates=defaultdict(set)
    for text in texts:
        tokens=normalize_phrase(text).split()
        for length in {len(key) for key in keys}:
            for start in range(len(tokens)-length+1):
                phrase=tokens[start:start+length]
                if any(len(t)<2 or not t.isalpha() for t in phrase):continue
                key=''.join(t[0] for t in phrase)
                if key in keys:candidates[key].add(' '.join(phrase))
    # An initialism with two plausible expansions stays as written for review.
    return {key:sorted(candidates[key]) for key in sorted(keys)}


def infer_abbreviations(fields, columns):
    return {key:values[0] for key,values in abbreviation_candidates(fields,columns).items() if len(values)==1}


def expand_for_matching(text, expansions):
    expanded=_EXPANSION.sub(lambda m:expansions.get(_key(m.group()),m.group()),normalize_phrase(text))
    return normalize_phrase(expanded)
