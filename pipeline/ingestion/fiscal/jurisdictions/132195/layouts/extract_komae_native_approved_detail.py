"""Cache-only fixed native observation/transcription extraction for ten approved originals."""

from importlib import import_module as _ingestion_module
from ingestion.inputs import record_input
import argparse,hashlib,json
from pathlib import Path
import duckdb
from ingestion.paths import PIPELINE
Runtime = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.native_council_provider').Runtime
CONFIG = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.native_council_provider').CONFIG
parse = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.decode_komae_native_observations').parse
COLUMNS = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.decode_komae_native_observations').COLUMNS
VERSION=1
DEFAULT_OUTPUT=PIPELINE/'.cache/acquisition/raw/native-council-approved-detail'
def materialize(c,result,output,ledger_ref):
 if not result['fully_complete_observed_grain'] or not result['fully_complete'] or result['parser_problems']:raise ValueError('Whole scope control/printed statutory correspondence incomplete')
 if len(result['rows'])!=c['expected_rows'] or any(r['setsu_code'] is None for r in result['rows']):raise ValueError('Exact ten-edition row/code count differs')
 if [r['source_row'] for r in result['rows']]!=list(range(1,len(result['rows'])+1)):raise ValueError('Original occurrence sequence differs')
 for row in result['rows']:
  if row['effective_date'] is not None or row['source_amount_unit']!='千円':raise ValueError('Effective date inferred or printed unit differs')
  if not c['first_page']<=row['page_number']<=c['last_page']:raise ValueError('Cross-account/issue physical page')
 directory=output/f"year={c['fiscal_year']}"/f"account={c['fund_label']}"/f"issue={c['amendment_number']}"/f"edition={c['expected_sha256']}"/f"table={c['table_id']}";directory.mkdir(parents=True,exist_ok=True);pq=directory/'data.parquet'
 with duckdb.connect() as con:
  con.execute('create table t ('+','.join(k+' '+v for k,v in COLUMNS.items())+')');con.executemany('insert into t values ('+','.join('?' for _ in COLUMNS)+')',[[r[k] for k in COLUMNS] for r in result['rows']]);con.execute('copy (select * from t order by source_row) to ? (format parquet, compression zstd)',[str(pq)]);con.execute('copy (select * from t order by source_row) to ? (format csv, header true)',[str(directory/'data.csv')])
 sha=hashlib.sha256(pq.read_bytes()).hexdigest()
 if c['expected_table_sha256'] is not None and sha!=c['expected_table_sha256']:raise ValueError('Canonical table byte contract differs')
 proof={**{k:v for k,v in result.items() if k not in ('rows','original_candidate')},'schema_version':1,'rows':len(result['rows']),'columns':COLUMNS,'extractor':'extract_komae_native_approved_detail.py@1','origin_object':c['origin_object'],'table_id':c['table_id'],'parquet_sha256':sha,'source_amount_unit':'千円','unit_multiplier':1000,'effective_date':None,'adoption_status':'fixed-input-provider-extracted','current_build_verified':False,'frozen_native_page_refs':c['native_page_refs'],'date_anomaly':c['date_anomaly'],'source_key':c['source_key'],'jurisdiction_code':'132195','fiscal_year':c['fiscal_year'],'fund_label':c['fund_label'],'amendment_number':c['amendment_number'],'request_url':c['url'],'sha256':c['expected_sha256'],'fetched_at':c['fetched_at'],'document_kind':'supplementary','direction':'expenditure','document_title':c['document_title'],'raw_form':'extracted','roundtrip_verified':False,'grain':result['rows'][0]['source_grain'],'pages':result['source_page_range'],'configured_attachment_pages':[c['first_page'],c['last_page']],'observation_role':'authoritative-native-council-supplementary-detail','effective_at':None,'effective_at_basis':result['effective_date_basis'],'baseline_status':'unconfirmed','verification':'whole-numbered-original-native-cell-transcriptions-independent-signed-moku-project-left-legal-article-and-exact-approval','extraction_evidence':{'rows_one_to_one':True,'reserve_exception_rows':0},'visual_ledger_file':ledger_ref,'logical_input_path':f"native-council-approved-detail/jurisdiction=132195/year={c['fiscal_year']}/document_kind=supplementary/edition={c['expected_sha256']}/direction=expenditure/table={c['table_id']}"}
 record_input(directory, proof)
 return dict(identity=c['identity'],rows=len(result['rows']),directory=str(directory),parquet_sha256=sha,parquet_bytes=pq.stat().st_size)
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,default=CONFIG);parser.add_argument('--object-dir',type=Path);parser.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT);parser.add_argument('--describe',action='store_true');args=parser.parse_args()
 if args.describe:
  print(json.dumps(dict(version=VERSION,config=str(args.config),default_output=str(DEFAULT_OUTPUT),columns=COLUMNS,source_grain='unchanged original project × expenditure setsu',contract='Only ten fixed originals plus frozen native observations/direct-cell declarations; ordinary effective_date remains NULL',default_private_dependency=False)));return
 runtime=Runtime(args.config,**({'objects':args.object_dir} if args.object_dir else {}));runtime.verify_all_objects();summaries=[]
 for c in runtime.candidates:
  result=parse(c,runtime);runtime.verify_rows(c,result['rows']);summaries.append(materialize(c,result,args.output_dir,runtime.data['visual_ledger_file']));print(json.dumps(summaries[-1],ensure_ascii=False),flush=True)
 args.output_dir.mkdir(parents=True,exist_ok=True);(args.output_dir/'wave-results.json').write_text(json.dumps(dict(editions=summaries,rows=sum(x['rows'] for x in summaries),immutable_objects_verified=len(runtime.verified),canonical_adoption=False,current_build_verified=False),ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
