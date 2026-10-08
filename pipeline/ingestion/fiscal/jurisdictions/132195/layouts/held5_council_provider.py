"""Exact five-edition cache-only provider. Historical path labels are never opened."""

from importlib import import_module as _ingestion_module
import copy,hashlib,html,json,re,subprocess
from pathlib import Path
from ingestion.fiscal.layouts.fiscal_general.extract_supplementary_expenditure import norm
validate_candidate = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.extract_komae_council_approved_detail').validate_candidate
HERE=Path(__file__).resolve().parent
OBJECTS=HERE.parents[4]/'.cache/objects'
CONFIG=HERE/'sources-held5-council-approved.json'
class Held5Runtime:
    def __init__(self):
        self.config=json.loads(CONFIG.read_text())
        manifest=json.loads((HERE/'held5-runtime-manifest.json').read_text())
        for name,ref in manifest.items():
            p=HERE/name
            if self.digest(p)!=ref:raise ValueError('Runtime/declaration bytes differ: '+name)
        self.declarations={}
        for name,ref in self.config['declarations'].items():
            p=HERE/name
            if self.digest(p)!=ref:raise ValueError('Frozen declaration differs: '+name)
            self.declarations[name]=json.loads(p.read_text())
        self.inputs={x['sha256']:x for x in self.declarations['held5-immutable-inputs.json']['objects']}
        for sha in self.inputs:self.object(sha)
        self.pages=self.declarations['held5-observation-cell-ledger.json']['pages']
        ledger=self.declarations['held5-observation-cell-ledger.json']
        ref=ledger['raw_cell_ledger_object'];raw_cells=json.loads(self.object(ref['sha256']).read_text())['cells']
        if self.digest(self.object(ref['sha256']))!={k:ref[k]for k in ('sha256','bytes')}:raise ValueError('Raw cell ledger bytes differ')
        observed_count=0
        for pagekey,page_ref in self.pages.items():
            original,page,variant=pagekey.split(':');d=json.loads(self.object(page_ref['native_sha256']).read_text())
            for index,o in enumerate(d['observations']):
                cell=raw_cells[pagekey+':'+str(index)];b=o['bbox']
                if (cell['original_sha256'],cell['physical_pdf_page'],cell['native_json_sha256'],cell['render_sha256'],cell['native_observation_index'],cell['column'],cell['raw_native_text'],cell['recognition_confidence'],cell['bbox_pdf_points'],cell['bbox_normalized'])!=(original,int(page),page_ref['native_sha256'],page_ref['render_sha256'],index,o['column'],o['text'],o['confidence'],b,[b[0]/d['pdf_point_width'],b[1]/d['pdf_point_height'],b[2]/d['pdf_point_width'],b[3]/d['pdf_point_height']]):raise ValueError('Frozen raw cell ledger/native observation differs')
                observed_count+=1
        if observed_count!=len(raw_cells):raise ValueError('Raw cell ledger has unmatched cells')
        decl=self.declarations['held5-direct-cell-transcriptions.json']
        self.transcriptions=[x['transcription']for x in decl]
        self.transcription_indices=[x['archive_index']for x in decl]
        self.moku_transcriptions=self.declarations['held5-direct-moku-transcriptions.json']
        self.candidates=self.config['candidates']
        self.identities={(c['fiscal_year'],c['fund_label'],c['amendment_number'])for c in self.candidates}
        if self.identities!={(2020,'一般会計',9),(2021,'一般会計',8),(2021,'一般会計',11),(2022,'一般会計',1),(2022,'一般会計',2)}:raise ValueError('Exact five scope changed')
        self.whole_scope=self.declarations['held5-whole-attachment-proof.json']
        self.verify_whole_scope()
    @staticmethod
    def digest(p):
        b=p.read_bytes();return {'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
    def object(self,sha):
        ref=self.inputs[sha];key=ref['object_key']
        if key not in {f'inputs/{kind}/sha256/{sha}'for kind in ('origin','native-observation','native-render')}:raise ValueError('Immutable key identity differs')
        p=OBJECTS/key
        if self.digest(p)!={'sha256':sha,'bytes':ref['bytes']}:raise ValueError('Immutable object SHA/bytes differ: '+key)
        return p
    def page_ref(self,c,page,variant):return self.pages[f"{c['expected_sha256']}:{page}:{variant}"]
    def page(self,c,page,variant):
        if not c['first_page']<=page<=c['last_page']:raise ValueError('Page crosses numbered attachment')
        ref=self.page_ref(c,page,variant)
        d=json.loads(self.object(ref['native_sha256']).read_text());self.object(ref['render_sha256'])
        if d['physical_page']!=page or Path(d['pdf']).stem!=c['expected_sha256']:raise ValueError('Native page/original identity differs')
        return copy.deepcopy(d)
    def verify_transcription(self,c,page,variant,t):
        ref=self.page_ref(c,page,variant)
        if (t['original_sha256'],t['physical_pdf_page'],t['ocr_json_sha256'],t['render_sha256'])!=(c['expected_sha256'],page,ref['native_sha256'],ref['render_sha256']):raise ValueError('Visual reading SHA/page/native/render differs')
        self.object(t['ocr_json_sha256']);self.object(t['render_sha256'])
        if t.get('direct_original_render_path'):self.object(t['direct_original_render_sha256'])
        d=json.loads(self.object(ref['native_sha256']).read_text());b=t['bbox']
        if not (0<=b[0]<b[2]<=d['pdf_point_width'] and 0<=b[1]<b[3]<=d['pdf_point_height']):
            # Two accepted full-cover archival readings used a rounded 842-point whole-page box
            # on 841.89 / 841.92004-point rotated covers. They establish title only, never row/cell geometry.
            cover_exceptions={(2022,1,22),(2022,2,5)}
            if not ((c['fiscal_year'],c['amendment_number'],page)in cover_exceptions and page==c['first_page'] and t['column']=='whole' and t['native_observation_index']is None and b==[0,0,842,595] and 841<d['pdf_point_width']<=842 and 595<=d['pdf_point_height']<596):
                raise ValueError('Visual reading physical bbox differs')
        if not t['observed_text'] or not t['basis']:raise ValueError('Explicit observed visual reading required')
    def verify_moku_transcription(self,c,t):
        ref=self.page_ref(c,t['physical_pdf_page'],'vision-final')
        if t['original_sha256']!=c['expected_sha256']or t['render_sha256']!=ref['render_sha256']:raise ValueError('Independent printed moku label evidence differs')
        self.object(t['render_sha256'])
    def verify_reference(self,e):
        if not any(e['url'].startswith(s)for s in ('https://www.city.komae.tokyo.jp/','https://www.city.komae.tokyo.dbsr.jp/')):raise ValueError('Unofficial approval URL')
        path=self.object(e['sha256']);loc=e['location']
        if self.inputs[e['sha256']]['object_key']!='inputs/origin/sha256/'+e['sha256']:raise ValueError('Approval object is not origin')
        if 'physical_pdf_page'in loc:
            raw=subprocess.run(['pdftotext','-layout','-f',str(loc['physical_pdf_page']),'-l',str(loc['physical_pdf_page']),str(path),'-'],capture_output=True,check=True).stdout.decode()
            original=norm(raw)
        elif 'voice_code'in loc:
            m=re.search(r'<li class="voice-block[^>]*data-voice_code="'+str(loc['voice_code'])+r'"[^>]*>(.*?)</li>',path.read_text(),re.S)
            if not m:raise ValueError('Indexed council voice absent')
            original=norm(html.unescape(re.sub('<[^>]*>','',m[1])))
        else:raise ValueError('Exact physical page/indexed voice required')
        if not norm(e['observed_text'])or norm(e['observed_text'])not in original:raise ValueError('Indexed observed original/approval text differs')
        return original
    def verify_whole_scope(self):
        if len(self.whole_scope)!=5:raise ValueError('Whole attachment scope differs')
        for c,s in zip(self.candidates,self.whole_scope,strict=True):
            validate_candidate(c)
            if s['original_sha256']!=c['expected_sha256']or s['url']!=c['url']or s['attachment_pages']!=[c['first_page'],c['last_page']]:raise ValueError('Whole original/account attachment identity differs')
            if [p['physical_pdf_page']for p in s['pages']]!=list(range(c['first_page'],c['last_page']+1)):raise ValueError('Whole attachment page coverage differs')
            for pg in s['pages']:
                for v in pg['observations']:
                    d=self.page(c,pg['physical_pdf_page'],v['variant'])
                    if (d['pdf_point_width'],d['pdf_point_height'])!=(v['pdf_point_width'],v['pdf_point_height']):raise ValueError('Physical page geometry differs')
            if [b['physical_pdf_page']for b in s['boundaries']]!=[c['first_page']-1,c['last_page']+1]:raise ValueError('Adjacent numbered bill bounds differ')
            for b in s['boundaries']:
                text=self.object(b['text_object']['sha256']).read_text()
                if text!=b['observed_text']:raise ValueError('Frozen adjacent bill text differs')
                self.verify_reference({'url':c['url'],'sha256':c['expected_sha256'],'location':{'physical_pdf_page':b['physical_pdf_page']},'observed_text':text})
            for e in c['approval_proof']['original_identity_evidence']+c['approval_proof']['resolution_evidence']:self.verify_reference(e)
    def verify_approval(self,c,pdf,control):
        if (c['fiscal_year'],c['amendment_number'])==(2022,2):
            evidence=c['approval_proof']['resolution_evidence']
            if [e['location'].get('voice_code')for e in evidence]!=[178,179,180,181]:raise ValueError('Original/motion indexed sequence changed')
            observed=[norm(e['observed_text'])for e in evidence]
            if not ('編成替えを求める動議'in observed[0]and '動議は否決されました'in observed[1]and '次に原案について採決'in observed[2]and '原案のとおり可決されました'in observed[3]):raise ValueError('Original passed versus failed motion evidence differs')
        return _verify_approval(c,pdf,control,self.verify_reference)
    def verify_result(self,c,r):
        ident=f"{c['fiscal_year']}-{c['fund_label']}-{c['amendment_number']}";e=self.config['expected_scope'][ident]
        if not r['fully_complete_observed_grain']or r['printed_arithmetic_failures']or r['parser_problems']:raise ValueError('Whole observed-grain extraction gate failed: '+ident)
        if (len(r['rows']),len(r['project_checks']),r['moku_count'],len(r['observed_left_controls']))!=(e['rows'],e['projects'],e['moku'],e['left']):raise ValueError('Whole printed leaf/control scope differs')
        t=r['totals'];reserve=sum(x['amount_delta']for x in r['rows']if x['setsu_code']is None)
        if not(t['first_article']==t['all_moku_sum']==t['printed_project_sum']==t['explanation_setsu_sum']==sum(x['amount_delta']for x in r['rows'])==t['left_setsu_sum']+reserve==e['article']):raise ValueError('Independent original signed controls differ')
        if not all(x['complete']for x in r['project_checks'])or not all(x['observed_grain_complete']for x in r['moku_checks']):raise ValueError('Independent project/moku controls failed')
        expected_reserves={(2021,8,49):(3000,24),(2022,1,57):(1500,39)}
        for row in r['rows']:
            if row['effective_date']is not None or row['executive_disposition_date']is not None:raise ValueError('Unconfirmed ordinary date changed')
            if row['setsu_code']is None:
                key=(c['fiscal_year'],c['amendment_number'],row['source_row'])
                if expected_reserves.get(key)!=(row['amount_delta'],row['page_number'])or row['setsu_label']!='予備費'or row['validation_status']!='unconfirmed':raise ValueError('Reserve NULL observed exception differs')
        return r

def _verify_approval(c,pdf,control,verify_reference):
    p=c['approval_proof'];title=f"令和{c['fiscal_year']-2018}年度狛江市{c['fund_label']}補正予算(第{c['amendment_number']}号)"
    if '計数整理中' in control['printed_cover_text']:raise ValueError('Unfinished original counts cannot be waived')
    origins=[verify_reference(e) for e in p['original_identity_evidence']]
    if not any(title in t and p['resolution_id'] in t for t in origins):raise ValueError('Numbered original proposal/report must name exact title')
    if not any(e['sha256']==c['expected_sha256'] and e['url']==c['url'] for e in p['original_identity_evidence']):raise ValueError('Original byte edition is not explicitly bound to resolution proof')
    for e in p['resolution_evidence']:verify_reference(e)
    # Only the indexed observed decision, never another resolution on the
    # same PDF page, may establish approval of this numbered original.
    resolution=''.join(norm(e['observed_text']) for e in p['resolution_evidence'])
    if p['resolution_id'] not in resolution:raise ValueError('Resolution number absent in decision evidence')
    voted = any(s in resolution for s in ('原案可決','原案のとおり可決されました','承認されました','承認することに決しました'))
    if p['resolution_id'].startswith('報告'):
        voted = any(s in resolution for s in ('承認されました','承認することに決しました')) or ('専決処分の承認を求める' in resolution and resolution.count('承認')>=2)
    if not voted:raise ValueError('Completed council approval required; approval-request title alone is insufficient')
    year,month,day=map(int,p['resolution_date'].split('-'))
    for e in p['resolution_evidence']:
        if 'voice_code' in e['location']:
            anchor=re.search(r'VoiceExpand1=r(\d+)-(\d{2})(\d{2})_',e['url'])
            if not anchor or (2018+int(anchor[1]),int(anchor[2]),int(anchor[3]))!=(year,month,day):raise ValueError('Indexed meeting date differs from resolution date')
        elif f'{month}月{day}日' not in norm(e['observed_text']) or f'令和{year-2018}年' not in norm(e['observed_text']):
            raise ValueError('Resolution table header and decision date must be observed together')
        else:
            decision='承認' if p['resolution_id'].startswith('報告') else '原案可決'
            lines=[norm(line) for line in e['observed_text'].splitlines()]
            target=[line for line in lines if p['resolution_id'] in line]
            if len(target)!=1 or f'{month}月{day}日{decision}' not in target[0]:
                raise ValueError('Exact numbered PDF decision row/date must independently match')
            prefix=title.split('(第')[0]
            if prefix not in norm(e['observed_text']) or f'(第{c["amendment_number"]}号)' not in norm(e['observed_text']):
                raise ValueError('Indexed PDF resolution evidence must name this account/year/issue')
    # Speaker evidence may omit the title at the final vote; indexed original
    # and the exported exact same numbered agenda bind that case separately.
    if p['resolution_id'].startswith('報告'):
        if control['submitted_basis']!='専決' or p.get('executive_disposition_date')!=control['submitted_at']:raise ValueError('Executive disposition report needs exact printed disposition date')
        y,m,d=map(int,control['submitted_at'].split('-'))
        if not any(f'令和{y-2018}年{m}月{d}日' in t for t in origins):raise ValueError('Report must explicitly identify the printed disposition date')

NAMESPACE='held5-council-approved-detail'
def held5_council_sources():
    from ingestion.fiscal.management.sources import Source, Resource
    # Listing declarations must not restore or decode private observation objects.
    candidates = json.loads(CONFIG.read_text())['candidates']
    return {c['source_key']:Source(key=c['source_key'],catalog=None,jurisdiction_code='132195',jurisdiction_name='狛江市',fiscal_year=c['fiscal_year'],fiscal_year_label=None,document_kind='supplementary',document_label=c['document_title'],dataset_title=None,encoding='',redistribute=c['redistribute'],redistribute_basis=c['redistribute_basis'],license_id=c['license_id'],attribution=c['attribution'],landing_page=c['landing_page'],raw_form='extracted',resources=(Resource(direction='expenditure',resource_name=c['document_title'],url=c['url'],url_basis='Exact numbered council-approved original SHA and whole physical attachment',table_id=c['table_id']),))for c in candidates}

def register_held5_council_declarations(rows,history,entries):
    from ingestion.inputs import source_metadata_bytes
    from ingestion.paths import INPUT_LOCK
    runtime=Held5Runtime();specs={c['source_key']:c for c in runtime.candidates};seen=set()
    for entry in entries:
        if not entry['path'].startswith(NAMESPACE+'/'):continue
        p=json.loads(source_metadata_bytes(INPUT_LOCK,entry));c=specs[p['source_key']]
        expected_path=f"{NAMESPACE}/jurisdiction=132195/year={c['fiscal_year']}/document_kind=supplementary/edition={c['expected_sha256']}/direction=expenditure/table={c['table_id']}"
        proof={**c['approval_proof'],'original_identity_evidence':[e for e in c['approval_proof']['original_identity_evidence']if '上記の議案'in e['observed_text']or '地方自治法'in e['observed_text']]}
        ident=f"{c['fiscal_year']}-{c['fund_label']}-{c['amendment_number']}";scope=runtime.config['expected_scope'][ident];reserve_rows=1 if(c['fiscal_year'],c['amendment_number'])in((2021,8),(2022,1))else 0
        if entry['path']in seen or (entry['path'],entry['jurisdiction'],entry['fiscalYear'],entry['direction'],entry['documentKind'],entry['originEdition'],p['table_id'],p['rows'])!=(expected_path,'132195',c['fiscal_year'],'expenditure','supplementary',c['expected_sha256'],c['table_id'],scope['rows']):raise ValueError('Adopted held5 exact edition/table occurrence differs')
        seen.add(entry['path'])
        if {k:entry['table'][k]for k in ('sha256','bytes')}!=c['expected_output']['data.parquet']or p['approval_proof']!=proof or p['effective_date']is not None or p['executive_disposition_date']is not None or p['reserve_null_rows']!=reserve_rows:raise ValueError('Adopted held5 original values/grain/approval/date/NULL proof differs')
        dataset=f"132195:{c['fiscal_year']}:expenditure:supplementary:{c['expected_sha256']}:{c['table_id']}"
        source=dict(documentKind='supplementary',documentLabel=c['document_title'],landingPage=c['landing_page'],url=c['url'],sha256=c['expected_sha256'],licenseId=c['license_id'],attribution=c['attribution'],rawForm='extracted',tableId=c['table_id'],pages=p['source_page_range'],grain='project × printed setsu; observed reserve NULL exceptions',observationRole='authoritative-held5-council-supplementary-detail',canonicalChanges=True,approvalStatus=c['approval_status'],approvalDate=p['council_resolution_date'],councilResolutionDate=p['council_resolution_date'],printedSubmissionDate=p['printed_submission_date'],executiveDispositionDate=None,effectiveDate=None,effectiveDateBasis=p['effective_date_basis'],approvalProof=proof,amendmentNumber=c['amendment_number'],fundLabel=c['fund_label'],sourceAmountUnit='千円',unitMultiplier=1000,rawTableSha256=entry['table']['sha256'],reserveExceptionRows=reserve_rows,initialState='unconfirmed',independentControls=p['totals'])
        row=dict(dataset_id=dataset,jurisdiction_code='132195',fiscal_year=c['fiscal_year'],direction='expenditure',document_kind='supplementary',source_json=json.dumps(source,ensure_ascii=False,sort_keys=True));rows.append(row)
        structure=dict(hierarchy=['kan','kou','moku','project','setsu'],dimensions=['department'],funds=[dict(code='',label=c['fund_label'])],scope=dict(granularity=source['grain'],authoritativeSupplementaryChanges=True,sourceAmountUnit='千円',initialState='unconfirmed',reserveExceptionRows=reserve_rows,expenditureSetsuStatus='printed-code-full-name-active-year-master-required'))
        history.append(dict(**row,origin_sha256=c['expected_sha256'],effective_at=None,amendment_number=c['amendment_number'],fund_label=c['fund_label'],line_count=p['rows'],structure_json=json.dumps(structure,ensure_ascii=False,sort_keys=True)))
    return rows,history


def evidence_objects():
    """Fixed origin/native/render refs, including all whole-attachment proof objects."""
    config=json.loads(CONFIG.read_text());name='held5-immutable-inputs.json';path=HERE/name
    if Held5Runtime.digest(path)!=config['declarations'][name]:raise ValueError('Immutable manifest bytes differ')
    return sorted([{'key':r['object_key'],'sha256':r['sha256'],'bytes':r['bytes']}for r in json.loads(path.read_text())['objects']],key=lambda r:r['key'])

def restore_evidence(objects=OBJECTS,*,remote=False,include_tables=False):
    """Restore only missing exact evidence keys. Extraction itself never networks."""
    refs=evidence_objects()
    if include_tables:
        for c in json.loads(CONFIG.read_text())['candidates']:
            r=c['expected_output']['data.parquet'];refs.append({'key':'inputs/table/sha256/'+r['sha256'],**r})
    for r in refs:
        p=Path(objects)/r['key']
        if p.exists():
            if Held5Runtime.digest(p)!={k:r[k]for k in('sha256','bytes')}:raise ValueError('Cached immutable restore conflict')
            continue
        if not remote:raise FileNotFoundError('Immutable cache object absent: '+r['key'])
        body=subprocess.run(['cf','r2','objects','get',r['key'],'--bucket-name','fudoki-inputs','--quiet'],capture_output=True,check=True).stdout
        if hashlib.sha256(body).hexdigest()!=r['sha256']or len(body)!=r['bytes']:raise ValueError('Immutable remote restore conflict')
        p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb')as f:f.write(body)
    return refs

def main():
    import argparse
    parser=argparse.ArgumentParser(description='Exact held5 immutable evidence and table restoration')
    parser.add_argument('--describe',action='store_true')
    parser.add_argument('--restore',action='store_true')
    parser.add_argument('--remote',action='store_true',help='Explicit cf GET only, never mutable origin URLs or PUT')
    args=parser.parse_args()
    if args.describe:
        print(json.dumps({'schema_version':1,'evidence':evidence_objects(),'tables':[{'key':'inputs/table/sha256/'+c['expected_output']['data.parquet']['sha256'],**c['expected_output']['data.parquet']}for c in json.loads(CONFIG.read_text())['candidates']],'defaults':'Cache beside supported code; reconstruction never networks','scope':'Five approved originals only'}));return
    if not args.restore:parser.error('--describe or --restore is required')
    refs=restore_evidence(remote=args.remote,include_tables=True)
    print(json.dumps({'status':'immutable-held5-cache-restored','objects':len(refs),'remote_explicit':args.remote}))
if __name__=='__main__':main()
