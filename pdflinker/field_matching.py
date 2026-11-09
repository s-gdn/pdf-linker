"""Identifier-first linking, followed by document-context matching."""
from difflib import SequenceMatcher
import re
from .text_normalization import normalize_phrase,prepare_query
from .document_context import generic_name


def exact_match(label,columns,context=''):
    index={}
    for column in columns:
        index.setdefault(normalize_phrase(column),[]).append(column)
    queries=[prepare_query(label,context),normalize_phrase(label)] if context else [normalize_phrase(label)]
    for query in dict.fromkeys(queries):
        if not query:continue
        matches=index.get(query,[])
        if len(matches)==1:return matches[0]
        if len(matches)>1:return None
    return None


def _assign(field,column,result,basis):
    result[field.key]=column
    field.match_basis=basis
    field.match_score=None
    field.match_note=''
    field.source_part,field.companion_columns,field.transform_source='',(),''


def _pending(field,result):
    return field.key not in result and field.constant_value is None and field.match_basis not in {'ambiguous_id','id_needs_review'}


def _close_identifier(value,columns):
    target=normalize_phrase(value)
    numbers=re.findall(r'\d+',target)
    scores=sorted(((SequenceMatcher(None,target,normalize_phrase(c)).ratio(),c) for c in columns
                   if re.findall(r'\d+',normalize_phrase(c))==numbers
                   and len(normalize_phrase(c).split())==len(target.split())),reverse=True)
    if not scores or scores[0][0]<.94:return None,False
    if len(scores)>1 and scores[0][0]-scores[1][0]<.08:return None,True
    return scores[0][1],False


def prepared_links(fields,columns,existing,close=False):
    result=dict(existing)
    for field in fields:
        if field.key not in result and field.constant_value is None:
            field.match_basis=''
            field.match_score=None
            field.match_note=''
            field.source_part,field.companion_columns,field.transform_source='',(),''
    # Complete the ID stage for every field before considering visible labels.
    for field in fields:
        if not _pending(field,result):continue
        matches=[c for c in columns if normalize_phrase(c)==normalize_phrase(field.name)]
        if len(matches)==1:_assign(field,matches[0],result,'field_id_exact')
        elif len(matches)>1:field.match_basis='ambiguous_id'
    if close:
        for field in fields:
            if not _pending(field,result) or generic_name(field.name):continue
            match,ambiguous=_close_identifier(field.name,columns)
            if match:_assign(field,match,result,'field_id_close')
            elif ambiguous:field.match_basis='ambiguous_id'
    else:
        # Exact link must not fill a typo in a prepared ID from contradictory
        # surrounding text before Suggest links gets to check that ID.
        for field in fields:
            if not _pending(field,result) or generic_name(field.name):continue
            match,ambiguous=_close_identifier(field.name,columns)
            if match or ambiguous:field.match_basis='id_needs_review'
    for field in fields:
        if not _pending(field,result):continue
        label=field.pdf_label or (field.label if not field.label_inferred else '')
        if not label or generic_name(label):continue
        if _bare_is_ambiguous(field,label,fields):continue
        match=exact_match(label,columns)
        if match is None and close:match,_=_close_identifier(label,columns)
        if match:_assign(field,match,result,'pdf_label')
    return result


# These are grammatical/structural words, not a catalogue of business roles.
_STRUCTURE={'a','an','the','of','for','to','in','on','and','your','please','optional',
            'details','information','particulars','section','contact','applicable','if','s'}


def _section(field):
    value=field.section or (field.context.split(' | ')[0] if field.context else '')
    return ' '.join(t for t in normalize_phrase(value).split() if t not in _STRUCTURE and not t.isdigit())


def _labels(field):
    return list(dict.fromkeys(v for v in (field.pdf_label,field.label,field.nearby_label) if v and not generic_name(v)))


def _scope(field):
    return normalize_phrase(_section(field)),normalize_phrase(field.question)


def _section_variants(field):
    path=field.section_path or ((field.section,) if field.section else ())
    if not path:return [_section(field)] if _section(field) else []
    parts=[' '.join(t for t in normalize_phrase(p).split() if t not in _STRUCTURE and not t.isdigit()) for p in path]
    return list(dict.fromkeys(' '.join(parts[i:]) for i in range(len(parts))))


def _bare_is_ambiguous(field,label,fields):
    scope=_scope(field)
    return bool(any(scope) and any(other.key!=field.key and any(_scope(other)) and _scope(other)!=scope
                               and normalize_phrase(label) in {normalize_phrase(v) for v in _labels(other)} for other in fields))


def lite_links(fields,columns,existing):
    result=prepared_links(fields,columns,existing)
    return _context_exact(fields,columns,result)


def _context_exact(fields,columns,result):
    for field in fields:
        if not _pending(field,result):continue
        for label in _labels(field):
            queries=[query for section in _section_variants(field) for query in (f'{section} {label}',f'{label} of {section}')]
            question=re.sub(r'^\d+(?:\.\d+)*[.)]?\s*','',field.question)
            if question and set(normalize_phrase(label).split())<=set(normalize_phrase(question).split()):queries.append(question)
            if not _bare_is_ambiguous(field,label,fields):queries.append(label)
            matches={m for query in queries if (m:=exact_match(query,columns)) is not None}
            if len(matches)==1:
                _assign(field,next(iter(matches)),result,'context_exact')
                break
    return result


def _tokens(value):
    aliases={'names':'name','addresses':'address','telephone':'phone','tel':'phone','e-mail':'email'}
    return {aliases.get(t,t) for t in normalize_phrase(value).split() if t not in _STRUCTURE}


def address_part(field):
    tokens=_tokens(field.label or field.nearby_label)
    if 'address' in tokens and ('line1' in tokens or 'line' in tokens and tokens & {'first','1'}):return 'line1'
    if 'address' in tokens and ('line2' in tokens or 'line' in tokens and tokens & {'second','2'}):return 'line2'
    if 'postcode' in tokens or 'postal' in tokens or {'post','code'}<=tokens:return 'postcode'
    if 'city' in tokens or 'town' in tokens:return 'city'
    if 'county' in tokens:return 'county'
    return ''


def duplicate_columns(columns,rows):
    """Collapse auto-suffixed headers only when their nonblank data agrees."""
    duplicate=set()
    if rows:
        for i,c in enumerate(columns):
            base=re.sub(r' \(\d+\)$','',c)
            if base!=c and base in columns:
                j=columns.index(base)
                if any(row[i] for row in rows) and all(row[i]==row[j] for row in rows):duplicate.add(c)
    return duplicate


def context_links(fields,columns,existing,rows=None):
    """Use header vocabulary and document sections, without fixed business roles."""
    result=prepared_links(fields,columns,existing,close=True)
    # Exact context matching must not undo the already resolved ID stages.
    result=_context_exact(fields,columns,result)
    duplicate=duplicate_columns(columns,rows)
    available=[c for c in columns if c not in duplicate]
    for field in fields:
        if not _pending(field,result):continue
        label=field.label or field.nearby_label or field.name
        vocabulary=set().union(*(_tokens(c) for c in columns)) if columns else set()
        tokens=_tokens(label);section=_tokens(_section(field)) & vocabulary;part=address_part(field)
        section_variants=[_tokens(s)&vocabulary for s in _section_variants(field)]
        # Full-address columns can supply several address widgets, with explicit
        # value projections. County is intentionally not guessed from free text.
        if part:
            base={'address'}
            question=re.sub(r'^\d+(?:\.\d+)*[.)]?\s*','',field.question)
            patterns=[base|s for s in section_variants if s]+[base|_tokens(question)]
            matches=[c for c in available if _tokens(c) in patterns]
            if len(matches)==1 and part!='county':
                _assign(field,matches[0],result,'context_address')
                field.source_part=part;field.transform_source=matches[0]
                continue
        patterns=[tokens|s for s in section_variants if s]
        if not section and not _bare_is_ambiguous(field,label,fields):patterns.append(tokens)
        if field.pdf_label or not field.label_inferred:
            if not _bare_is_ambiguous(field,label,fields):patterns.append(tokens)
        matches=[c for c in available if _tokens(c) in patterns]
        if len(matches)==1:_assign(field,matches[0],result,'context_tokens')
        elif 'name' in tokens and re.search(r'\(s\)|\bnames\b',label,re.I):
            group=[c for c in available if {_t for _t in _tokens(c) if not _t.isdigit()} in patterns
                   and len(re.findall(r'\d+',c))==1]
            if len(group)>1 and len({re.findall(r'\d+',c)[0] for c in group})==len(group):
                group.sort(key=lambda c:int(re.findall(r'\d+',c)[0]))
                _assign(field,group[0],result,'context_combined')
                field.companion_columns=tuple(group[1:]);field.transform_source=group[0]
    return result


def semantic_query(field):
    # The document index retains all page text. Compact relevant evidence here
    # avoids silently truncating a whole PDF to an embedding model's token limit.
    question=re.sub(r'^\d+(?:\.\d+)*[.)]?\s*','',field.question)
    parts=[field.pdf_label or field.label or field.name,_section(field),question,field.nearby_label]
    parts.extend(re.sub(r'^\d+(?:\.\d+)*[.)]?\s*','',p) for p in field.context.split(' | ') if p)
    selected=[];seen=set()
    for part in parts:
        if part and (_tokens(part)-seen or not selected):
            selected.append(part);seen.update(_tokens(part))
    return normalize_phrase(' '.join(selected))


def compatible_columns(field,fields,columns):
    """Infer discriminating section words from this document and its headers."""
    vocabulary=set().union(*(_tokens(c) for c in columns)) if columns else set()
    sections=[_tokens(_section(f)) & vocabulary for f in fields]
    own=_tokens(_section(field)) & vocabulary
    other=set().union(*(s-own for s in sections)) if sections else set()
    ambiguous=any(_bare_is_ambiguous(field,label,fields) for label in _labels(field))
    return [c for c in columns if (not (_tokens(c)&other) or bool(_tokens(c)&own))
            and (not ambiguous or bool(_tokens(c)&own))]


def score_decision(query,columns,scores,threshold,margin):
    ranked=sorted(zip(map(float,scores),columns),key=lambda x:(-x[0],x[1]))
    if not ranked:return None
    gap=ranked[0][0]-ranked[1][0] if len(ranked)>1 else ranked[0][0]
    return ranked[0][1] if ranked[0][0]>=threshold and gap>=margin else None
