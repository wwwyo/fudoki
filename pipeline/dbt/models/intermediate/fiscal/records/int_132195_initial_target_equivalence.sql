select i.budget_item_id,i.initial_namespace_budget_item_id,
       i.fiscal_line_id as initial_fiscal_line_id,i.dataset_id as initial_dataset_id,
       i.source_row as initial_source_row,i.initial_yen as amount_initial,
       i.initial_target_identity_json,i.supplementary_compatibility_identity_json,
       i.observed_account_path_json,i.account_path_json,i.dimensions_json,i.source_grain,
       i.namespace_equivalence_status,
       count(*) as supplementary_source_rows,
       to_json(list(struct_pack(fiscalLineId:=s.fiscal_line_id,datasetId:=s.dataset_id,
          sourceRow:=s.source_row,changeId:='c-' || sha256(s.fiscal_line_id),printedDepartment:=s.department_text,
          originalSha256:=s.origin_sha256,page:=s.page_number,sourceLocations:=s.source_locations_json::json)
          order by s.fiscal_line_id))::varchar as supplementary_source_evidence_json,
       json_object('initialFiscalLineId',i.fiscal_line_id,'initialSourceRow',i.source_row,
          'initialNamespaceIdentity',i.initial_target_identity_json::json,
          'existingSupplementaryIdentity',i.supplementary_compatibility_identity_json::json,
          'originalPrintedHierarchy',i.observed_account_path_json::json,
          'projectionBasis','Existing supplementary identity has empty kan/kou labels; all printed labels retained separately; codes/moku/project/department/setsu/sourceGrain remain exact',
          'originalSha256',i.origin_sha256,'url',i.source_url,'page',i.page_number,
          'sourceLocations',i.source_locations_json::json,'printedValue',i.printed_amount_text,
          'sourceAmountUnit',i.source_amount_unit,'printedDepartment',i.department_text)::varchar as initial_source_evidence_json
from {{ ref('int_132195_initial_detail') }} i
join {{ ref('int_supplementary_expenditure_changes') }} s
  on s.target_identity_json=i.supplementary_compatibility_identity_json
where i.namespace_equivalence_status='confirmed-exact-printed-identity-including-sourceGrain'
group by all
