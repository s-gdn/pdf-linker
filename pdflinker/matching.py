"""Conservative second-pass matching using PDF labels, layout and column meaning."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata


def words(value):
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    value = unicodedata.normalize("NFKD", value).casefold()
    value = value.replace("(s)", "s")
    value = re.sub(r"\br\s*/\s*i\b", "rent increase", value)
    value = re.sub(r"\bproperty manager\b", "agent name", value)
    value = re.sub(r"\bpm\b", "agent", value)
    value = re.sub(r"\bfreq\b", "frequency", value)
    value = re.sub(r"\be[ -]?mail\b", "email", value)
    tokens = re.findall(r"[a-z0-9]+", value)
    aliases = {"names": "name", "tenants": "tenant", "landlords": "landlord", "agents": "agent",
               "premises": "property", "telephone": "phone", "tel": "phone", "mobile": "phone", "postcode": "postal",
               "zip": "postal", "town": "city", "started": "start", "starting": "start", "latest": "last",
               "recent": "last", "previous": "last", "ref": "reference", "no": "number"}
    return [aliases.get(token, token) for token in tokens]


def enrich_context(doc, fields):
    """Carry section roles across pages and find the question above each field."""
    section = ""
    for page in doc:
        lines = [(line["bbox"], "".join(span["text"] for span in line["spans"]).strip())
                 for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])]
        lines = sorted((rect, text) for rect, text in lines if text)
        headings = sorted([(rect[1], text) for rect, text in lines
                           if re.match(r"^\d+\.\s+\D", text) and not text.lower().startswith("note")])
        question_lines = []
        for box, text in lines:
            if re.match(r"^\d+\.\d+\s", text):
                question_lines.append((box, text))
            elif re.fullmatch(r"\d+\.\d+", text):
                same_line = [(other[0], label) for other, label in lines
                             if other[0] >= box[2] and abs(other[1] - box[1]) < 4]
                if same_line:
                    question_lines.append((box, text + " " + min(same_line)[1]))
        for field in fields:
            if field.page != page.number:
                continue
            import pymupdf as fitz
            rect = fitz.Rect(field.rect)
            if field.manual:
                rect = rect * page.derotation_matrix
            active_section = next((text for y, text in reversed(headings) if y < rect.y0), section)
            questions = [(box[1], text) for box, text in question_lines if box[0] < rect.x1 and box[1] < rect.y0]
            question = max(questions, default=(0, ""))[1]
            # Exclude the notes sidebar; labels and questions must be in the field's column.
            above = [(max(0, rect.y0 - box[3]) + abs(rect.x0 - box[0]) * .25, text)
                     for box, text in lines if box[0] < rect.x1 and box[2] > rect.x0
                     and 0 <= rect.y0 - box[3] <= 65 and len(text) > 2
                     and not re.fullmatch(r"[\d.\s]+", text)]
            nearby = min(above, default=(0, ""))[1]
            local = " ".join(text for box, text in lines if box[0] < rect.x1 and box[2] > rect.x0
                             and 0 <= rect.y0 - box[3] <= 150)
            field.context = " | ".join(part for part in (active_section, question, nearby) if part)
            if not field.label or re.fullmatch(r"(?:text\s*field|field|checkbox|check box)\s*\d*", field.label, re.I):
                field.label = nearby or field.name
            if field.label.casefold().startswith("date") and any(word in local.casefold() for word in ("signature", "signed", "print name")):
                field.context += " | signature"
        if headings:
            section = headings[-1][1]


@dataclass
class Meaning:
    role: str = ""
    kind: str = ""
    purpose: str = ""
    part: str = ""
    number: int = 0
    plural: bool = False


def meaning(label, context=""):
    tokens, context_tokens = words(label), words(context)
    own, all_tokens = set(tokens), set(tokens + context_tokens)
    result = Meaning()
    if own & {"signature", "signatory"} or "print" in own or "continued" in own or "sheets" in own:
        return result
    # Only section headings supply a role; a rent question mentioning a landlord does not.
    section = set(words(context.split(" | ")[0]))
    roles = own & {"landlord", "agent", "tenant", "employee", "employer", "applicant", "customer", "client", "company"}
    if not roles:
        roles = section & {"landlord", "agent", "tenant"}
    if len(roles) == 1:
        result.role = next(iter(roles))
    if "email" in own:
        result.kind = "email"
    elif "phone" in own or ("number" in own and result.role == "agent"):
        result.kind = "phone"
    elif own & {"address", "postal", "city", "county"} or {"post", "code"} <= own:
        result.kind = "address"
        if result.role == "tenant" or ("property" in own and not result.role):
            result.role = "property"
        if own & {"postal"} or {"post", "code"} <= own:
            result.part = "postcode"
        elif "city" in own:
            result.part = "city"
        elif "county" in own:
            result.part = "county"
        elif "first" in own or "1" in own or "line1" in own:
            result.part = "line1"
        elif "second" in own or "2" in own or "line2" in own:
            result.part = "line2"
    elif "frequency" in own:
        result.kind = "frequency"
    elif "date" in own or "dob" in own or {"rent", "increase"} <= own and own & {"first", "last"}:
        result.kind = "date"
    elif "rent" in own and not own & {"charges", "services", "tax", "fuel", "water"}:
        result.kind = "rent"
    elif own & {"name", "surname"}:
        result.kind = "name"
        result.plural = bool(re.search(r"name\(s\)|names|tenant\(s\)|tenants", label, re.I))
        numbers = [int(token) for token in tokens if token.isdigit()]
        result.number = numbers[-1] if numbers else 0
        if own & {"first", "given", "forename"}:
            result.part = "first_name"
        elif own & {"last", "surname", "family"}:
            result.part = "last_name"
    if result.kind in {"date", "frequency", "rent"}:
        if all_tokens & {"birth", "dob", "birthday"}:
            result.purpose = "birth"
        elif {"rent", "increase"} <= all_tokens and "first" in all_tokens:
            result.purpose = "first_increase"
        elif {"rent", "increase"} <= all_tokens and "last" in all_tokens:
            result.purpose = "last_increase"
        elif "tenancy" in all_tokens and "start" in all_tokens:
            result.purpose = "tenancy_start"
        elif result.kind == "date" and {"new", "rent", "start"} <= all_tokens:
            result.purpose = "new_rent_start"
        elif "current" in all_tokens:
            result.purpose = "current"
        elif "new" in all_tokens or "proposing" in all_tokens:
            result.purpose = "new_rent_start" if result.kind == "date" and "rent" in all_tokens else "new"
        elif result.kind == "date" and "start" in all_tokens:
            result.purpose = "start"
        if result.kind == "date" and not result.purpose and "signature" in all_tokens:
            result.kind = ""
    return result


def robust_links(fields, headers, result, rows=None):
    targets = {field.key: meaning(field.label or field.name, field.context) for field in fields}
    columns, preceding_rent = {}, ""
    for header in headers:
        base = re.sub(r" \(\d+\)$", "", header)
        item = meaning(base)
        if item.kind == "rent":
            preceding_rent = item.purpose
        elif item.kind == "frequency" and not item.purpose:
            item.purpose = preceding_rent
        columns[header] = item
    duplicates = set()
    if rows:
        for index, header in enumerate(headers):
            base = re.sub(r" \(\d+\)$", "", header)
            if base != header and base in columns and columns[base] == columns[header]:
                other = headers.index(base)
                if any(row[index] for row in rows) and all(row[index] == row[other] for row in rows):
                    duplicates.add(header)
    for field in fields:
        if field.key in result or field.constant_value is not None:
            continue
        target = targets[field.key]
        if not target.kind:
            # Unrecognised business fields can still match their tooltip or visible
            # label. Use the complete label, never a short nearby fragment.
            def canonical(value):
                return " ".join(sorted(token for token in words(value) if token not in {"of", "the", "optional", "your"}))
            label = canonical(field.label or field.name)
            scores = sorted(((SequenceMatcher(None, label, canonical(header)).ratio(), header) for header in headers), reverse=True)
            if scores and (scores[0][0] == 1 or scores[0][0] >= .88 and not any(token.isdigit() for token in words(field.label or field.name))):
                if len(scores) == 1 or scores[0][0] - scores[1][0] >= .12:
                    result[field.key] = scores[0][1]
            continue
        options = []
        for header, source in columns.items():
            if header in duplicates or source.kind != target.kind:
                continue
            if target.role and source.role and target.role != source.role:
                continue
            if target.purpose and source.purpose and target.purpose != source.purpose and not (target.purpose == "new_rent_start" and source.purpose == "start"):
                continue
            if source.number and target.number and source.number != target.number:
                continue
            if target.part and source.part and target.part != source.part:
                continue
            if source.part and not target.part:
                continue
            if target.kind == "name" and target.part != source.part:
                continue
            if target.part == "county" and not source.part:
                continue  # A county cannot reliably be inferred from a free-form address.
            # Generic columns are usable only when the other roles/purposes are
            # explicitly covered. Do not send an unqualified email to every party.
            ambiguous = False
            for attribute in ("role", "purpose"):
                wanted, supplied = getattr(target, attribute), getattr(source, attribute)
                if wanted and not supplied:
                    needed = {getattr(value, attribute) for value in targets.values() if value.kind == target.kind and getattr(value, attribute)}
                    covered = {getattr(value, attribute) for value in columns.values() if value.kind == target.kind and getattr(value, attribute)}
                    if needed - covered != {wanted}:
                        ambiguous = True
            if ambiguous:
                continue
            score = .96 if target.role == source.role else .9
            score += .03 if target.purpose == source.purpose else 0
            score += .02 if target.part == source.part else 0
            options.append((score, header))
        # One plural tenant box can contain several explicitly numbered tenant columns.
        if target.kind == "name" and target.role == "tenant" and target.plural and not target.number:
            group = [header for _, header in options if columns[header].number]
            if len(group) > 1 and len({columns[header].number for header in group}) == len(group):
                group.sort(key=lambda header: columns[header].number)
                result[field.key] = group[0]
                field.transform_source = group[0]
                field.companion_columns = tuple(group[1:])
                continue
        options.sort(reverse=True)
        if not options or len(options) > 1 and options[0][0] - options[1][0] < .08:
            continue
        header = options[0][1]
        result[field.key] = header
        if target.kind == "address" and target.part and not columns[header].part:
            field.transform_source = header
            field.source_part = target.part
    return result
