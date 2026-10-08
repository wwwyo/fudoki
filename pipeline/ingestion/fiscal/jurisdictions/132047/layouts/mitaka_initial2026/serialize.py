"""Declared 25-field serializer: JSONL rows -> Parquet via PyArrow 25.0.1 only.
The CLI emits JSONL; this script is the separate, reviewed serializer step."""
import json,sys
from pathlib import Path

F25=['source_key','fiscal_year','document_kind','account','amendment','direction',
 'row_type','grain','name','printed_text','printed_amounts','amount_semantics','phase',
 'page','line','indent','col_context','table_index','section','sec_i','ordinal',
 'kan_amount','row_label','cells','extra']

def run(inp,out):
    import pyarrow as pa,pyarrow.parquet as pq
    rows=[json.loads(x) for x in Path(inp).read_text().splitlines()]
    cols={k:[json.dumps(r[k],ensure_ascii=False) if isinstance(r[k],(dict,list))
            else None if r[k] is None else str(r[k]) for r in rows] for k in F25}
    table=pa.table({k:pa.array(v) for k,v in cols.items()})
    pq.write_table(table,out)
    return table

if __name__=='__main__':
    run(sys.argv[1],sys.argv[2])
