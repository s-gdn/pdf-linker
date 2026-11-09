"""General attribute evidence and constrained assignment; no form-specific mappings."""
from dataclasses import dataclass
import re
from .text_normalization import normalize_phrase


@dataclass(frozen=True)
class Attribute:
    kind:str=''
    purpose:str=''
    entity:frozenset=frozenset()
    manual:bool=False
    inferred_group:str=''


_FILLER=set('a an the of for to in on is was were be been being when what how many much please optional your details information request record internal existing current proposed revised new last previous next first most recent date day number no id identifier reference ref code amount price cost fee charge frequency cycle interval payment billing full name'.split())
_PURPOSES={
    'current':{'current','existing','present'},'proposed':{'proposed','revised','new','renewal'},
    'birth':{'birth','born','birthday','dob'},'start':{'start','starts','started','starting','begin','begins','commences','commencement','entry','joined'},
    'end':{'end','ends','finish','finishes','completion','deadline','due'},
    'dispatch':{'dispatch','dispatched','sent','shipped','departure'},'arrival':{'arrival','arrive','delivery','delivered'},
}


def attribute(text,values=(),context=''):
    text=normalize_phrase(text);tokens=set(text.split());ctx=set(normalize_phrase(context).split())
    manual=bool(tokens & {'signature','signed','handwritten'} or 'by hand' in text)
    if tokens & {'email'} or 'electronic mail' in text:kind='email'
    elif tokens & {'phone','telephone','tel','mobile'}:kind='phone'
    elif 'county' in tokens:kind='county'
    elif tokens & {'postcode','postal'} or {'post','code'}<=tokens:kind='address'
    elif tokens & {'address','city','town'}:kind='address'
    elif tokens & {'name','names'}:kind='name'
    elif tokens & {'consent','permission','approved','approval'} or 'may we' in text:kind='boolean'
    elif tokens & {'frequency','freq','cycle','interval','often'}:kind='frequency'
    elif 'number of' in text or 'how many' in text:kind='quantity'
    elif tokens & {'cost','budget'} and tokens & {'centre','center','account'}:kind='identifier'
    elif tokens & {'identifier','reference','ref','id','code','number','serial','vin','rma'}:kind='identifier'
    elif (tokens & {'date','dob','born','birthday','commencement'} or
          tokens & {'start','starts','begin','begins','commences','joined','ends','finishes','deadline'} or
          (tokens & {'arrival','departure','dispatch','collection','referral'} and
           (len(tokens)==1 or bool(tokens & {'at','on','from','expected'}))) or
          'first day' in text or 'last day' in text or
          'when' in tokens or 'scheduled for' in text or 'due back' in text or 'due date' in text):kind='date'
    elif tokens & {'amount','price','cost','fee','charge','charges','salary','funding','refund','reimbursement','pay'}:kind='amount'
    elif tokens & {'count','quantity','weight','mass','volume','hours','mileage','odometer','attendees','distance'} or 'how many' in text:kind='quantity'
    elif tokens & {'priority','urgency','terms','title','position','role','analysis','test'}:kind='text'
    elif 'name' in tokens or 'names' in tokens:kind='name'
    else:kind=''
    # Cell evidence is local and only used for narrow, recognisable formats.
    samples=[normalize_phrase(str(v)) for v in values if str(v).strip()][:30]
    raw=[str(v).strip() for v in values if str(v).strip()][:30]
    if kind=='identifier' and 'number' in tokens and not tokens & {'identifier','reference','ref','id','code','serial'} and raw:
        phone_like=lambda value:(bool(re.fullmatch(r'[+\d ()-]+',value)) and
                                 10<=len(re.sub(r'\D','',value))<=15 and value.startswith(('+','0')))
        if sum(phone_like(v) for v in raw)>=.8*len(raw):
            # Formatted telephone values clarify an otherwise ambiguous Number
            # header. Bare numeric identifiers retain their original text and
            # remain ambiguous rather than becoming amounts or phone numbers.
            kind='phone' if any(re.search(r'[+ ()-]',v) for v in raw) else ''
    if not kind and samples:
        if sum(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}(?: 00:00:00)?|\d{1,2}/\d{1,2}/\d{4}',v)) for v in raw)>=.8*len(raw):kind='date'
        elif sum(v in {'daily','weekly','fortnightly','monthly','quarterly','annually','yearly'} for v in samples)>=.8*len(samples):kind='frequency'
        elif sum(v in {'yes','no','true','false'} for v in samples)>=.8*len(samples):kind='boolean'
        elif sum(bool(re.fullmatch(r'[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+',v)) for v in raw)>=.8*len(raw):kind='identifier'
    scope=tokens|ctx
    purpose=''
    if kind in {'amount','frequency','date'}:
        # Local temporal meaning overrides context inherited from a heading.
        for words in (tokens,ctx):
            found=[key for key,vocab in _PURPOSES.items() if words & vocab]
            if kind!='date':found=[p for p in found if p in {'current','proposed'}]
            elif len(found)>1:
                events=[p for p in found if p not in {'current','proposed'}]
                if len(events)==1:found=events
            if len(found)==1:purpose=found[0];break
        if kind=='date':
            if 'first day' in text:purpose='start'
            elif 'last day' in text:purpose='end'
            elif 'check in' in text:purpose='arrival'
            elif 'check out' in text:purpose='dispatch'
    semantic_stop=_FILLER|set().union(*_PURPOSES.values())|{'will','has','have','which','ddmmyyyy','ddmmyy','dd','mm','yyyy'}
    entity=frozenset(t for t in tokens if t not in semantic_stop and len(t)>1 and not t.isdigit())
    return Attribute(kind,purpose,entity,manual)


def column_attributes(columns,rows,expand):
    attributes=[];descriptions=[]
    for index,column in enumerate(columns):
        label=expand(re.sub(r' \(\d+\)$','',column))
        values=[r[index] for r in (rows or [])[:30] if index<len(r)]
        item=attribute(label,values)
        group=''
        # Only adjacent, repeated amount/frequency groups establish this weak
        # spreadsheet-side context; do not infer purpose from suffix (2) alone.
        if item.kind=='frequency' and not item.purpose and index:
            previous=attributes[-1]
            if previous.kind=='amount' and previous.purpose:
                group=previous.purpose
                item=Attribute(item.kind,group,item.entity,item.manual,columns[index-1])
        attributes.append(item)
        if item.kind in {'identifier','date','amount','frequency','quantity','boolean','text'}:
            descriptions.append(normalize_phrase(f'{label} {item.kind} {item.purpose}'))
        else:descriptions.append(expand(column))
    return attributes,descriptions


def field_attribute(field,expand):
    label=field.pdf_label or field.label or field.nearby_label or field.name
    item=attribute(expand(label),context=expand(field.question))
    if item.kind=='date' and not item.entity and field.question:
        question=re.sub(r'^\d+(?:\.\d+)*[.)]?\s*','',field.question)
        question_entity=attribute(expand(question)).entity
        item=Attribute(item.kind,item.purpose,question_entity,item.manual)
    if field.kind in {'checkbox','radio'} and not item.manual:
        item=Attribute('boolean',item.purpose,item.entity,item.manual)
    return item


def compatible(target,source):
    if target.manual:return False
    if target.kind=='county':return source.kind=='county'
    if target.kind and source.kind and target.kind!=source.kind:
        if {target.kind,source.kind}<={'name','text'} or {target.kind,source.kind}<={'amount','quantity'}:pass
        else:return False
    if target.purpose and source.purpose and target.purpose!=source.purpose:return False
    return True


def primary_query(field,item,expand):
    label=expand(field.pdf_label or field.label or field.nearby_label or field.name)
    generic={'date','day','dd','mm','yyyy','ddmmyyyy','ddmmyy','amount','value','frequency',
             'payment','billing','cycle','interval','of','the','a'}
    if field.question and not (set(label.split())-generic):
        question=re.sub(r'^\d+(?:\.\d+)*[.)]?\s*','',field.question)
        label=f'{label} {expand(question)}'
    return normalize_phrase(f'{item.kind} {item.purpose} {label}')


def joint_assignment(edges,columns):
    """Maximum-weight rectangular assignment with an unmatched slot per field.

    Edges contain positive utility above the acceptance floor. Missing edges are
    forbidden. Dummy columns have utility zero, allowing any field to abstain.
    """
    keys=list(edges)
    if not keys:return {}
    count=len(keys);width=len(columns)+count
    costs=[[-edges[key].get(c,-1e6) for c in columns]+[0.]*count for key in keys]
    u=[0.]*(count+1);v=[0.]*(width+1);p=[0]*(width+1);way=[0]*(width+1)
    for i in range(1,count+1):
        p[0]=i;j0=0;minimum=[float('inf')]*(width+1);used=[False]*(width+1)
        while True:
            used[j0]=True;i0=p[j0];delta=float('inf');j1=0
            for j in range(1,width+1):
                if used[j]:continue
                current=costs[i0-1][j-1]-u[i0]-v[j]
                if current<minimum[j]:minimum[j]=current;way[j]=j0
                if minimum[j]<delta:delta=minimum[j];j1=j
            for j in range(width+1):
                if used[j]:u[p[j]]+=delta;v[j]-=delta
                else:minimum[j]-=delta
            j0=j1
            if not p[j0]:break
        while True:
            j1=way[j0];p[j0]=p[j1];j0=j1
            if j0==0:break
    return {keys[p[j]-1]:columns[j-1] for j in range(1,len(columns)+1)
            if p[j] and edges[keys[p[j]-1]].get(columns[j-1],0)>0}
