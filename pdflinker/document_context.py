"""Read the whole document once; retain layout evidence separately from PDF IDs."""
from collections import Counter
import re

import pymupdf as fitz


def generic_name(value):
    return bool(re.fullmatch(r'(?:text\s*field|field|check\s*box|unnamed\s*field)[\s_\d.-]*',value.strip(),re.I))


def _lines(page):
    result=[]
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines',[]):
            spans=line['spans'];text=''.join(s['text'] for s in spans).strip()
            if not text:continue
            result.append(dict(text=text,bbox=list(line['bbox']),size=max(s['size'] for s in spans),
                               bold=all(s['flags'] & 16 for s in spans if s['text'].strip())))
    return sorted(result,key=lambda line:(line['bbox'][1],line['bbox'][0]))


def _heading(line,lines,fields,body_size):
    text=line['text'];box=line['bbox']
    if re.match(r'^(?:notes?\b|page\s+\d+\b)',text,re.I):return ''
    if re.match(r'^\d+\.\d+(?:\.\d+)*\b',text):
        if re.fullmatch(r'\d+(?:\.\d+)+',text):
            same=[other for other in lines if 0<=other['bbox'][0]-box[2]<=100
                  and abs(other['bbox'][1]-box[1])<4 and not other['text'].lower().startswith('note')]
            if same:line['text']=text+' '+min(same,key=lambda x:x['bbox'][0])['text']
        return 'question'
    if re.match(r'^\d+[.)]\s+\D',text):return 'section'
    if len(text)>100 or len(text.split())>14:return ''
    if text.endswith(('.', '?', '!')):return ''
    if fields and not any(box[0]-10<=f.rect[0]<=box[0]+120 and f.rect[1]>box[1] for f in fields):return ''
    # Avoid promoting bold field labels into section headings.
    is_label=any(0<=f.rect[1]-box[3]<=35 and box[0]<f.rect[2] and box[2]>f.rect[0] for f in fields)
    if not is_label and (line['size']>=body_size*1.2 or line['bold']):return 'section'
    return ''


def build_document_context(doc,fields):
    pages=[]
    for page in doc:
        lines=_lines(page)
        body=Counter(round(line['size'],1) for line in lines).most_common(1)
        local=[f for f in fields if f.page==page.number]
        for line in lines:line['heading']=_heading(line,lines,local,body[0][0] if body else 11)
        pages.append(dict(page=page.number,width=page.cropbox.width,height=page.cropbox.height,lines=lines))
    # Repeated running titles should not reset a section that continues on a new page.
    repeated=Counter(line['text'] for page in pages for line in page['lines'] if line['bbox'][1]<55)
    for page in pages:
        for line in page['lines']:
            if (line['heading']=='section' and line['bbox'][1]<55 and repeated[line['text']]>1
                    and not re.match(r'^\d+[.)]\s',line['text'])
                    and not any(0<=f.rect[1]-line['bbox'][3]<=80 for f in fields if f.page==page['page'])):
                line['heading']=''
    starts=set()
    for page in pages:
        headings=[line for line in page['lines'] if line['heading']=='section']
        for a in headings:
            for b in headings:
                if (abs(a['bbox'][1]-b['bbox'][1])<=12
                        and b['bbox'][0]-a['bbox'][2]>.08*page['width']
                        and b['bbox'][0]-a['bbox'][0]>.25*page['width']):
                    starts.update((round(a['bbox'][0]/page['width'],2),round(b['bbox'][0]/page['width'],2)))
    starts=sorted(starts)
    anchors=[]
    for x in starts:
        if not anchors or x-anchors[-1]>.25:anchors.append(x)
    if not anchors:anchors=[0.]
    boundaries=[(a+b)/2 for a,b in zip(anchors,anchors[1:])]
    def column(x):return sum(x>edge for edge in boundaries)
    states=[dict(section='',question='',section_id='',stack=[],questions=[]) for _ in anchors]
    sections={};field_records={}
    for page in pages:
        native=doc[page['page']]
        local=[f for f in fields if f.page==page['page']]
        rects={f.key:fitz.Rect(f.rect)*native.derotation_matrix if f.manual else fitz.Rect(f.rect) for f in local}
        events=[(line['bbox'][1],0,index,line) for index,line in enumerate(page['lines'])]
        events += [(rects[f.key].y0,1,index,f) for index,f in enumerate(local)]
        for _,kind,index,item in sorted(events,key=lambda e:e[:3]):
            if kind==0:
                line=item;box=line['bbox'];col=column(box[0]/page['width'])
                columns=range(len(states)) if box[2]-box[0]>.65*page['width'] else [col]
                if line['heading']=='section':
                    key=f"{page['page']}:{index}"
                    sections[key]=dict(title=line['text'],page=page['page'],bbox=box,text=[])
                    for c in columns:
                        stack=list(states[c]['stack'])
                        while stack and line['size']>=stack[-1]['size']-.5:stack.pop()
                        if re.match(r'^\d+[.)]\s',line['text']):stack=[]
                        stack.append(dict(title=line['text'],id=key,size=line['size']))
                        states[c]=dict(section=' / '.join(s['title'] for s in stack),question='',section_id=key,
                                       stack=stack,questions=[])
                        sections[key]['parent']=stack[-2]['id'] if len(stack)>1 else None
                elif line['heading']=='question':
                    prefix=re.match(r'^\d+(?:\.\d+)+',line['text'])
                    depth=prefix.group().count('.') if prefix else 1
                    for c in columns:
                        questions=list(states[c]['questions'])
                        while questions and questions[-1][0]>=depth:questions.pop()
                        questions.append((depth,line['text']))
                        states[c]['question']=' / '.join(text for _,text in questions)
                        states[c]['questions']=questions
                key=states[col]['section_id']
                if key:sections[key]['text'].append(dict(page=page['page'],bbox=box,text=line['text']))
                continue
            field=item;rect=rects[field.key];state=states[column(rect.x0/page['width'])]
            candidates=[]
            for line in page['lines']:
                box=fitz.Rect(line['bbox']);text=line['text']
                if line['heading'] or len(text)>120 or re.fullmatch(r'[\d.\s]+',text):continue
                if re.match(r'^(?:notes?\b|page\s+\d+\b)',text,re.I):continue
                if box.y0<0 or box.y1>page['height']-25:continue
                if any(other.contains((box.tl+box.br)/2) for other in rects.values()):continue
                score=None;gap=rect.y0-box.y1
                if 0<=gap<=65 and box.x0<rect.x1 and box.x1>rect.x0:
                    score=gap+abs(rect.x0-box.x0)*.25
                cy=(box.y0+box.y1)/2
                if 0<=rect.x0-box.x1<=180 and rect.y0-4<=cy<=rect.y1+4:
                    score=(rect.x0-box.x1)*.25+abs(cy-(rect.y0+rect.y1)/2)
                if field.kind in {'checkbox','radio'} and 0<=box.x0-rect.x1<=90 and rect.y0-4<=cy<=rect.y1+4:
                    score=(box.x0-rect.x1)*.25+abs(cy-(rect.y0+rect.y1)/2)
                if score is not None:candidates.append((score,text))
            candidates.sort(key=lambda v:(v[0],v[1]))
            field.section=state['section'];field.question=state['question'];field.section_id=state['section_id']
            field.section_path=tuple(s['title'] for s in state['stack'])
            field.nearby_labels=tuple(dict.fromkeys(text for _,text in candidates))
            field.nearby_label=field.nearby_labels[0] if candidates else ''
            # Authored tooltips and field IDs are evidence, never renamed by layout.
            if not field.label or field.label_inferred or generic_name(field.label):
                field.label=field.nearby_label or field.name
                field.label_inferred=True
            field.context=' | '.join(dict.fromkeys(p for p in (field.section,field.question,field.nearby_label) if p))
            local_text=' '.join(line['text'] for line in page['lines'] if line['bbox'][0]<rect.x1
                                and line['bbox'][2]>rect.x0 and 0<=rect.y0-line['bbox'][3]<=150)
            if field.label.lower().startswith('date') and re.search(r'\b(signature|signed|print name)\b',local_text,re.I):
                field.context+=' | signature'
            field_records[field.key]=dict(id=field.name,pdf_label=field.pdf_label,page=field.page,bbox=list(field.rect),
                section_id=field.section_id,section=field.section,question=field.question,label=field.label,
                nearby_labels=list(field.nearby_labels),label_inferred=field.label_inferred)
    return dict(version=1,pages=pages,sections=sections,fields=field_records)
