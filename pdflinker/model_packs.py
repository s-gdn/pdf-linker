"""Pinned data-only matching packs. No pip, scripts, or executable downloads."""
import hashlib
import json
import math
import os
from pathlib import Path,PurePosixPath
import shutil
import tempfile
import urllib.request
import zipfile
import re


class Cancelled(Exception):pass


def bundled_model_directory():
    return Path(__file__).with_name('models')


def model_directory():
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'PDFLinker'/'models'


def file_digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


class PackManager:
    def __init__(self,root=None,catalog=None):
        self.root=Path(root) if root else model_directory()
        source=Path(__file__).with_name('assets')/'matching-packs.json'
        self.catalog=catalog or json.loads(source.read_text(encoding='utf-8'))
        if self.catalog.get('version')!=1:raise ValueError('Unsupported model catalogue.')
        for pack in self.catalog['packs']:
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',pack['id']):raise ValueError('Invalid pack identifier.')
            if not re.fullmatch(r'[0-9a-f]{64}',pack['sha256']):raise ValueError('Invalid pack digest.')
            for file in pack['files']:
                p=PurePosixPath(file['path'])
                if p.is_absolute() or '..' in p.parts or '\\' in str(p) or ':' in str(p):raise ValueError('Invalid catalogue path.')
        self.packs={p['id']:p for p in self.catalog['packs']}

    def installed(self,pack_id,verify=False):
        pack=self.packs[pack_id];folder=self.root/pack_id
        if not (folder/'installed.json').is_file():return False
        try:
            marker=json.loads((folder/'installed.json').read_text())
            if marker.get('id')!=pack_id or marker.get('sha256')!=pack['sha256']:return False
        except (OSError,ValueError):return False
        for item in pack['files']:
            path=folder/item['path']
            if not path.is_file() or path.stat().st_size!=item['size']:return False
            if verify and file_digest(path)!=item['sha256']:return False
        return True

    def available(self):
        return [p for p in self.packs.values() if self.installed(p['id'])]

    def install_archive(self,pack_id,archive,cancel=None):
        pack=self.packs[pack_id]
        if file_digest(archive)!=pack['sha256']:raise ValueError('Model pack checksum does not match the trusted catalogue.')
        self.root.mkdir(parents=True,exist_ok=True)
        expected={f['path']:f for f in pack['files']}
        with tempfile.TemporaryDirectory(prefix='.install-',dir=self.root) as temporary:
            stage=Path(temporary)
            with zipfile.ZipFile(archive) as bundle:
                names=[i.filename for i in bundle.infolist() if not i.is_dir()]
                if len(names)!=len(set(names)) or set(names)!=set(expected):raise ValueError('Unexpected files in model pack.')
                for name in names:
                    path=PurePosixPath(name)
                    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:raise ValueError('Invalid model pack path.')
                    if path.suffix not in {'.onnx','.onnx_data','.json','.md','.txt'} and path.name not in {'LICENSE','NOTICE','COPYING'}:
                        raise ValueError('Executable or unsupported model pack file.')
                    info=bundle.getinfo(name)
                    if info.file_size!=expected[name]['size']:raise ValueError('Model pack file size mismatch.')
                    target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
                    with bundle.open(info) as source,target.open('wb') as output:
                        while chunk:=source.read(1024*1024):
                            if cancel and cancel.is_set():raise Cancelled('Installation cancelled.')
                            output.write(chunk)
                    if file_digest(target)!=expected[name]['sha256']:raise ValueError('Model pack file checksum mismatch.')
            (stage/'installed.json').write_text(json.dumps({'id':pack_id,'sha256':pack['sha256']}))
            destination=self.root/pack_id
            if destination.exists():
                # This fixed child was obtained from the trusted catalogue, never an archive member.
                resolved=destination.resolve()
                if resolved.parent!=self.root.resolve():raise ValueError('Invalid model destination.')
                shutil.rmtree(destination)
            shutil.move(str(stage),str(destination))

    def download(self,pack_id,progress=None,cancel=None):
        pack=self.packs[pack_id]
        if not pack['url'].startswith('https://'):raise ValueError('Model downloads require HTTPS.')
        self.root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.download-',dir=self.root) as temporary:
            path=Path(temporary)/'pack.zip';done=0
            request=urllib.request.Request(pack['url'],headers={'User-Agent':'PDFLinker-model-packs/1'})
            with urllib.request.urlopen(request,timeout=60) as response,path.open('wb') as output:
                if not response.geturl().startswith('https://'):raise ValueError('Insecure model download redirect.')
                while chunk:=response.read(1024*1024):
                    if cancel and cancel.is_set():raise Cancelled('Download cancelled.')
                    done+=len(chunk)
                    if done>pack['download_bytes']:raise ValueError('Download exceeds trusted model pack size.')
                    output.write(chunk)
                    if progress:progress(done,pack['download_bytes'])
            if done!=pack['download_bytes']:raise ValueError('Model download was incomplete.')
            self.install_archive(pack_id,path,cancel)

    def remove(self,pack_id):
        if pack_id not in self.packs:raise ValueError('Unknown model pack.')
        path=(self.root/pack_id).resolve()
        if path.parent!=self.root.resolve():raise ValueError('Invalid model directory.')
        if path.exists():shutil.rmtree(path)


class PackMatcher:
    def __init__(self,manager,pack_id):
        from .semantic_engine import SemanticModel
        if not manager.installed(pack_id,verify=True):
            raise ValueError('The bundled matching models are missing or damaged. Re-extract the complete application ZIP. If running from source, run scripts/prepare_models.py first.')
        self.pack=manager.packs[pack_id]
        self.models={name:SemanticModel(manager.root/pack_id/'models'/name,spec)
                     for name,spec in self.pack['models'].items()}

    def links(self,fields,columns,existing,cancel=None,minimum_score=.4,rows=None,abbreviations=None,rrf=None):
        from .field_matching import context_links,semantic_query,address_part,_tokens,_scope,_section,duplicate_columns
        from .text_normalization import normalize_phrase
        from .abbreviations import infer_abbreviations,expand_for_matching
        from rapidfuzz import fuzz
        from .fusion import validate_rrf,reciprocal_rank_scores
        from .structured_matching import (column_attributes,field_attribute,compatible,
                                          primary_query,joint_assignment)
        rrf=validate_rrf(rrf) if rrf is not None else None
        use_rrf=rrf is not None and rrf['enabled']
        ranking_floor=rrf['minimum_rank_score'] if use_rrf else minimum_score
        if not 0<=minimum_score<=1:raise ValueError('Minimum suggestion score must be between 0 and 1.')
        result=context_links(fields,columns,existing,rows)
        pending=[f for f in fields if f.key not in result and f.constant_value is None and f.match_basis!='ambiguous_id']
        if not pending or not columns:return result
        expansions=infer_abbreviations(fields,columns) if abbreviations is None else dict(abbreviations)
        expand=lambda text:expand_for_matching(text,expansions)
        source_attributes,model_columns=column_attributes(columns,rows,expand)
        target_attributes={f.key:field_attribute(f,expand) for f in pending}
        pending=[f for f in pending if not target_attributes[f.key].manual]
        if not pending:return result
        duplicates=duplicate_columns(columns,rows)
        def canonical(column):return re.sub(r' \(\d+\)$','',column) if column in duplicates else column
        normal_columns=[expand_for_matching(c,expansions) for c in columns]
        queries=[expand_for_matching(semantic_query(field),expansions) for field in pending]
        # Models receive headers, context and derived types, never record values.
        for model in self.models.values():model.prepare(queries,model_columns)
        def full_address(column):
            tokens=_tokens(normal_columns[columns.index(column)])
            return 'address' in tokens and not tokens & {'first','second','line1','line2','line'}
        # Equal values do not prove two general-purpose columns have the same
        # meaning (e.g. two payment intervals). Only merge repeated address data.
        duplicates={c for c in duplicates if full_address(c)}
        projected_parts={'line1','line2','city','postcode'}
        used={canonical(c) for c in result.values()}
        address_sources={}
        for field in fields:
            if field.key not in result:continue
            used.update(canonical(c) for c in field.companion_columns)
            if address_part(field) in projected_parts and full_address(result[field.key]) and any(_scope(field)):
                address_sources.setdefault(_scope(field),set()).add(result[field.key])
        raw_scores={}
        def score_query(query,field=None):
            if cancel and cancel.is_set():raise Cancelled('Auto-link cancelled.')
            combined=[0.]*len(columns)
            members=self.pack['recipe']['members']
            if not members:raise ValueError('The matching pack has no models.')
            individual={}
            target=target_attributes[field.key] if field is not None else None
            business=target is not None and target.kind in {'identifier','date','amount','frequency','quantity','boolean','text'}
            local=primary_query(field,target,expand) if business else query
            for member in self.pack['recipe']['members']:
                values=self.models[member['name']].score(query,model_columns)
                if business and local!=query:
                    short=self.models[member['name']].score(local,model_columns)
                    values=[.35*float(full)+.65*float(label) for full,label in zip(values,short)]
                lexical=[max(fuzz.ratio(query,c),fuzz.token_sort_ratio(query,c))/100 for c in normal_columns]
                mixed=[member['weight']*max(0,float(v))+(1-member['weight'])*l for v,l in zip(values,lexical)]
                if not all(math.isfinite(float(v)) for v in values):
                    raise ValueError('The matching model returned a non-finite score.')
                combined=[total+max(0.,min(1.,score))/len(members) for total,score in zip(combined,mixed)]
                individual[member['name']]=list(map(float,values))
            # Typed evidence restricts eligibility and ranking; it does not
            # inflate the average model score shown to the user.
            allowed=[target is None or compatible(target,source) for source in source_attributes]
            penalties=[1.]*len(columns)
            if target is not None and target.kind=='identifier' and target.entity:
                specific=any(s.kind=='identifier' and s.entity and compatible(target,s) for s in source_attributes)
                for i,source in enumerate(source_attributes):
                    if source.kind=='identifier' and not source.entity:
                        penalties[i]=.6 if specific else .85
            raw_scores[query]=combined
            if use_rrf:
                individual={name:[value if allowed[i] else -1. for i,value in enumerate(values)]
                            for name,values in individual.items()}
                ranked=reciprocal_rank_scores(individual,rrf)
                return [s*penalties[i] if allowed[i] and average>=minimum_score else 0. for i,(s,average) in enumerate(zip(ranked,combined))]
            return [value*penalties[i] if allowed[i] else 0. for i,value in enumerate(combined)]
        field_scores={field.key:score_query(query,field) for field,query in zip(pending,queries)}
        field_confidences={field.key:raw_scores[query] for field,query in zip(pending,queries)}
        def eligible(field,index):
            return (compatible(target_attributes[field.key],source_attributes[index]) and
                    field_confidences[field.key][index]>=minimum_score and field_scores[field.key][index]>=ranking_floor)
        # Address components describe one logical value. Rank their common source
        # as a group before a word such as "first" can send one part to a date.
        groups={}
        for field in fields:
            if address_part(field) in projected_parts and any(_scope(field)):
                groups.setdefault(_scope(field),[]).append(field)
        group_candidates=[];grouped=set()
        address_columns=[i for i,c in enumerate(columns) if full_address(c) and (c not in duplicates or c in result.values())]
        for scope,siblings in groups.items():
            remaining=[f for f in siblings if f.key in field_scores]
            if not remaining or (len(siblings)<2 and scope not in address_sources) or not address_columns:continue
            grouped.update(f.key for f in remaining)
            fixed=address_sources.get(scope,set())
            for i in address_columns:
                column=columns[i]
                if fixed and column not in fixed:continue
                if canonical(column) in used and column not in fixed:continue
                scores=[field_scores[f.key][i] for f in remaining]
                mean=sum(scores)/len(scores)
                if mean>=ranking_floor:
                    group_candidates.append((mean,scope,column,remaining,i))
        group_candidates.sort(key=lambda row:(-row[0],row[1],normalize_phrase(row[2]),row[2]))
        assigned_groups=set()
        for _,scope,column,remaining,i in group_candidates:
            if scope in assigned_groups:continue
            if canonical(column) in used and column not in address_sources.get(scope,set()):continue
            accepted=[f for f in remaining if eligible(f,i)]
            if not accepted:continue
            assigned_groups.add(scope);used.add(canonical(column))
            address_sources.setdefault(scope,set()).add(column)
            for field in accepted:
                result[field.key]=column
                field.match_basis='semantic_address_group';field.match_score=field_confidences[field.key][i]
                field.source_part=address_part(field);field.companion_columns=();field.transform_source=column
        # A linked address supplies a role clue for names in that same section.
        # Infer the role from the actual header, not a dictionary of occupations.
        def section_key(field):return field.section_id or _section(field)
        roles={}
        address_words={'address','addresses','mailing','postal','street','contact','full'}
        for field in fields:
            column=result.get(field.key)
            if not column or not section_key(field) or not full_address(column):continue
            if address_part(field) not in projected_parts:continue
            normalized=normal_columns[columns.index(column)]
            role=' '.join(t for t in normalized.split() if t not in address_words and t in _tokens(normalized))
            if role:roles.setdefault(section_key(field),set()).add(role)
        contextual_names=set()
        for field in pending:
            clues=roles.get(section_key(field),set())
            label_tokens=_tokens(field.pdf_label or field.label or field.nearby_label)
            if field.key in result or len(clues)!=1 or 'name' not in label_tokens or 'signature' in label_tokens:continue
            role=next(iter(clues))
            query=expand_for_matching(f'{role} name {semantic_query(field)}',expansions)
            field_scores[field.key]=score_query(query,field)
            field_confidences[field.key]=raw_scores[query]
            contextual_names.add(field.key)
        # Solve the remaining assignment jointly, keeping explicit/prepared links
        # and completed address groups fixed. Each target can choose unmatched.
        available=[c for c in columns if c not in duplicates and canonical(c) not in used]
        remaining=[f for f in pending if f.key not in result and f.key not in grouped]
        edges={f.key:{c:field_scores[f.key][i]-ranking_floor+1e-9 for i,c in enumerate(columns)
                      if c in available and eligible(f,i)} for f in remaining}
        for field in remaining:
            target=target_attributes[field.key]
            if target.kind=='date' and target.purpose:
                for i,column in enumerate(columns):
                    if column in edges[field.key] and source_attributes[i].purpose==target.purpose:
                        # Event-supported dates outrank vague Date labels when
                        # competing for a source with an explicit date purpose.
                        edges[field.key][column]+=.5
            if target.kind not in {'date','identifier'} or not target.entity:continue
            anchors=[c for i,c in enumerate(columns) if c in edges[field.key] and
                     source_attributes[i].kind==target.kind and source_attributes[i].entity==target.entity and
                     source_attributes[i].purpose==target.purpose]
            if len(anchors)==1:
                # A unique, eligible type/entity/purpose agreement must not lose
                # its column to a weaker generic label elsewhere in the form.
                edges[field.key][anchors[0]]+=1.
        selected_pairs=joint_assignment(edges,available)
        for field in remaining:
            if cancel and cancel.is_set():raise Cancelled('Suggest links cancelled.')
            selected=selected_pairs.get(field.key)
            if selected is None:continue
            part=address_part(field);scope=_scope(field)
            projected=part in projected_parts and full_address(selected) and any(scope)
            shared=projected and selected in address_sources.get(scope,set())
            if canonical(selected) in used and not shared:continue
            result[field.key]=selected
            used.add(canonical(selected))
            field.match_basis='semantic_section_context' if field.key in contextual_names else 'semantic_context'
            field.match_score=field_confidences[field.key][columns.index(selected)]
            source=source_attributes[columns.index(selected)]
            target=target_attributes[field.key]
            field.match_note=''
            if target.kind:
                field.match_note=f'Attribute: {target.kind}'+(f'; purpose: {target.purpose}' if target.purpose else '')+'.'
            if source.inferred_group:
                field.match_note+=f' Column group inferred from "{source.inferred_group}"; review this context.'
            field.source_part,field.companion_columns,field.transform_source='',(),''
            if part in projected_parts and full_address(selected):
                field.source_part,field.transform_source=part,selected
                if any(scope):address_sources.setdefault(scope,set()).add(selected)
        return result
