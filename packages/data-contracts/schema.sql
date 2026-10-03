PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS database_identity (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1), identity TEXT NOT NULL
);
INSERT OR IGNORE INTO database_identity VALUES(1,lower(hex(randomblob(16))));
CREATE TABLE IF NOT EXISTS jurisdiction_master (
  jurisdiction_code TEXT PRIMARY KEY, name TEXT NOT NULL, ocd_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cofog_master (
  code TEXT PRIMARY KEY, label TEXT NOT NULL,
  level TEXT NOT NULL CHECK(level IN ('division','group','class')),
  parent_code TEXT REFERENCES cofog_master(code),
  CHECK((level='division' AND length(code)=2 AND parent_code IS NULL)
    OR (level='group' AND length(code)=4 AND parent_code=substr(code,1,2))
    OR (level='class' AND length(code)=6 AND parent_code=substr(code,1,4)))
);
CREATE TABLE IF NOT EXISTS fiscal_expenditure_setsu_master (
  expenditure_setsu_id TEXT PRIMARY KEY,
  code TEXT NOT NULL, label TEXT NOT NULL,
  valid_from_fiscal_year INTEGER, valid_to_fiscal_year INTEGER,
  legal_basis TEXT NOT NULL,
  CHECK(valid_from_fiscal_year IS NULL OR valid_to_fiscal_year IS NULL
    OR valid_from_fiscal_year<=valid_to_fiscal_year)
);
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_setsu_master_no_overlap BEFORE INSERT ON fiscal_expenditure_setsu_master
WHEN EXISTS(SELECT 1 FROM fiscal_expenditure_setsu_master m WHERE (m.code=NEW.code OR m.label=NEW.label) AND m.expenditure_setsu_id<>NEW.expenditure_setsu_id
  AND coalesce(m.valid_from_fiscal_year,-9223372036854775808)<=coalesce(NEW.valid_to_fiscal_year,9223372036854775807)
  AND coalesce(NEW.valid_from_fiscal_year,-9223372036854775808)<=coalesce(m.valid_to_fiscal_year,9223372036854775807))
BEGIN SELECT RAISE(ABORT,'Setsu definitions overlap'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_setsu_master_no_overlap_update BEFORE UPDATE ON fiscal_expenditure_setsu_master
WHEN EXISTS(SELECT 1 FROM fiscal_expenditure_setsu_master m WHERE (m.code=NEW.code OR m.label=NEW.label) AND m.expenditure_setsu_id<>NEW.expenditure_setsu_id
  AND coalesce(m.valid_from_fiscal_year,-9223372036854775808)<=coalesce(NEW.valid_to_fiscal_year,9223372036854775807)
  AND coalesce(NEW.valid_from_fiscal_year,-9223372036854775808)<=coalesce(m.valid_to_fiscal_year,9223372036854775807))
BEGIN SELECT RAISE(ABORT,'Setsu definitions overlap'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_setsu_master_no_stranded BEFORE UPDATE ON fiscal_expenditure_setsu_master
WHEN EXISTS(
  SELECT 1 FROM fiscal_expenditure_budget_items i WHERE i.expenditure_setsu_id=NEW.expenditure_setsu_id
    AND ((NEW.valid_from_fiscal_year IS NOT NULL AND i.fiscal_year<NEW.valid_from_fiscal_year)
      OR (NEW.valid_to_fiscal_year IS NOT NULL AND i.fiscal_year>NEW.valid_to_fiscal_year)))
BEGIN SELECT RAISE(ABORT,'Setsu period change strands existing budget items'); END;
CREATE TABLE IF NOT EXISTS fiscal_jurisdiction_data (
  version_id TEXT NOT NULL UNIQUE,
  jurisdiction_code TEXT PRIMARY KEY REFERENCES jurisdiction_master(jurisdiction_code),
  contract_version INTEGER NOT NULL CHECK(contract_version=4),
  package_id TEXT,
  name_snapshot TEXT NOT NULL, ocd_id_snapshot TEXT NOT NULL, caveats_json TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  manifest_url TEXT NOT NULL, manifest_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fiscal_datasets (
  dataset_id TEXT NOT NULL, jurisdiction_code TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('expenditure','revenue')),
  document_kind TEXT NOT NULL CHECK(document_kind IN ('budget','supplementary','settlement','carryover','reserve-allocation','transfer')),
  origin_sha256 TEXT NOT NULL, source_json TEXT NOT NULL, structure_json TEXT NOT NULL,
  line_count INTEGER NOT NULL CHECK(line_count>=0),
  amendment_number INTEGER, effective_at TEXT, source_amount_kind TEXT,
  coverage_json TEXT NOT NULL,
  PRIMARY KEY(dataset_id),
  FOREIGN KEY(jurisdiction_code) REFERENCES fiscal_jurisdiction_data(jurisdiction_code)
);
CREATE TABLE IF NOT EXISTS fiscal_package_files (
  path TEXT NOT NULL, jurisdiction_code TEXT NOT NULL,
  object_key TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL CHECK(bytes>=0),content_type TEXT NOT NULL,
  PRIMARY KEY(path),
  FOREIGN KEY(jurisdiction_code) REFERENCES fiscal_jurisdiction_data(jurisdiction_code)
);
CREATE TABLE IF NOT EXISTS fiscal_settlement_expenditure_lines (
  fiscal_line_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
  source_row INTEGER NOT NULL, fund_code TEXT NOT NULL, fund_label TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND abs(amount)<=9007199254740991),
  consolidation TEXT NOT NULL CHECK(consolidation IN ('retained','eliminated')),
  counterpart_fund TEXT NOT NULL,
  cofog_code TEXT REFERENCES cofog_master(code),
  cofog_status TEXT NOT NULL CHECK(cofog_status IN ('assigned','unclassifiable','out-of-scope')),
  cofog_basis TEXT NOT NULL,
  CHECK((cofog_status='assigned' AND cofog_code IS NOT NULL) OR (cofog_status!='assigned' AND cofog_code IS NULL)),
  PRIMARY KEY(fiscal_line_id),
  FOREIGN KEY(dataset_id) REFERENCES fiscal_datasets(dataset_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS fiscal_settlement_expenditure_lines_dataset ON fiscal_settlement_expenditure_lines(dataset_id,fiscal_line_id);
CREATE TABLE IF NOT EXISTS fiscal_settlement_expenditure_line_hierarchy (
  fiscal_line_id TEXT NOT NULL,ordinal INTEGER NOT NULL,level TEXT NOT NULL,code TEXT NOT NULL,label TEXT NOT NULL,name_source TEXT NOT NULL,
  PRIMARY KEY(fiscal_line_id,ordinal),
  FOREIGN KEY(fiscal_line_id) REFERENCES fiscal_settlement_expenditure_lines(fiscal_line_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fiscal_settlement_expenditure_line_dimensions (
  fiscal_line_id TEXT NOT NULL,dimension TEXT NOT NULL,code TEXT NOT NULL,label TEXT NOT NULL,
  PRIMARY KEY(fiscal_line_id,dimension),
  FOREIGN KEY(fiscal_line_id) REFERENCES fiscal_settlement_expenditure_lines(fiscal_line_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fiscal_settlement_expenditure_line_names (
  fiscal_line_id TEXT NOT NULL,name_kind TEXT NOT NULL,level TEXT NOT NULL,value TEXT NOT NULL,name_source TEXT NOT NULL,basis TEXT NOT NULL,
  PRIMARY KEY(fiscal_line_id,name_kind,level),
  FOREIGN KEY(fiscal_line_id) REFERENCES fiscal_settlement_expenditure_lines(fiscal_line_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fiscal_expenditure_budget_items (
  budget_item_id TEXT NOT NULL,jurisdiction_code TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,fund_code TEXT NOT NULL,fund_label TEXT NOT NULL,
  expenditure_setsu_id TEXT REFERENCES fiscal_expenditure_setsu_master(expenditure_setsu_id),
  line_granularity TEXT NOT NULL CHECK(line_granularity IN ('expenditure_setsu','origin_line')),
  account_path_json TEXT NOT NULL,dimensions_json TEXT NOT NULL,names_json TEXT NOT NULL,
  initial_state TEXT NOT NULL CHECK(initial_state IN ('recorded','verified-zero','unknown')),
  PRIMARY KEY(budget_item_id),
  FOREIGN KEY(jurisdiction_code) REFERENCES fiscal_jurisdiction_data(jurisdiction_code)
);
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_budget_items_setsu_period BEFORE INSERT ON fiscal_expenditure_budget_items
WHEN NEW.expenditure_setsu_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM fiscal_expenditure_setsu_master m WHERE m.expenditure_setsu_id=NEW.expenditure_setsu_id
    AND (m.valid_from_fiscal_year IS NULL OR NEW.fiscal_year>=m.valid_from_fiscal_year)
    AND (m.valid_to_fiscal_year IS NULL OR NEW.fiscal_year<=m.valid_to_fiscal_year))
BEGIN SELECT RAISE(ABORT,'Setsu definition does not cover the fiscal year'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_budget_items_setsu_period_update BEFORE UPDATE ON fiscal_expenditure_budget_items
WHEN NEW.expenditure_setsu_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM fiscal_expenditure_setsu_master m WHERE m.expenditure_setsu_id=NEW.expenditure_setsu_id
  AND (m.valid_from_fiscal_year IS NULL OR NEW.fiscal_year >= m.valid_from_fiscal_year)
  AND (m.valid_to_fiscal_year IS NULL OR NEW.fiscal_year <= m.valid_to_fiscal_year))
BEGIN SELECT RAISE(ABORT,'Setsu definition does not cover the fiscal year'); END;
CREATE TABLE IF NOT EXISTS fiscal_initial_expenditure_budget_lines (
  fiscal_line_id TEXT NOT NULL,dataset_id TEXT NOT NULL,
  budget_item_id TEXT NOT NULL,source_row INTEGER NOT NULL,amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND abs(amount)<=9007199254740991),
  details_json TEXT NOT NULL,
  consolidation TEXT NOT NULL CHECK(consolidation IN ('retained','eliminated')),
  counterpart_fund TEXT NOT NULL,
  cofog_code TEXT REFERENCES cofog_master(code),
  cofog_status TEXT NOT NULL CHECK(cofog_status IN ('assigned','unclassifiable','out-of-scope')),
  cofog_basis TEXT NOT NULL,
  CHECK((cofog_status='assigned' AND cofog_code IS NOT NULL) OR (cofog_status!='assigned' AND cofog_code IS NULL)),
  PRIMARY KEY(fiscal_line_id),UNIQUE(budget_item_id),
  FOREIGN KEY(dataset_id) REFERENCES fiscal_datasets(dataset_id) ON DELETE CASCADE,
  FOREIGN KEY(budget_item_id) REFERENCES fiscal_expenditure_budget_items(budget_item_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fiscal_expenditure_budget_changes (
  change_id TEXT NOT NULL,dataset_id TEXT NOT NULL,budget_item_id TEXT NOT NULL,
  amount_delta INTEGER NOT NULL CHECK(typeof(amount_delta)='integer' AND abs(amount_delta)<=9007199254740991),
  details_json TEXT NOT NULL,
  change_kind TEXT NOT NULL CHECK(change_kind IN ('supplementary','carryover','reserve-allocation','transfer')),
  effective_at TEXT NOT NULL,sequence INTEGER NOT NULL,source_row INTEGER NOT NULL,
  counterpart_budget_item_id TEXT,carryover_from_year INTEGER,carryover_to_year INTEGER,
  cofog_code TEXT REFERENCES cofog_master(code),
  cofog_status TEXT NOT NULL CHECK(cofog_status IN ('assigned','unclassifiable','out-of-scope')),
  cofog_basis TEXT NOT NULL,
  CHECK((cofog_status='assigned' AND cofog_code IS NOT NULL) OR (cofog_status!='assigned' AND cofog_code IS NULL)),
  PRIMARY KEY(change_id),
  FOREIGN KEY(dataset_id) REFERENCES fiscal_datasets(dataset_id) ON DELETE CASCADE,
  FOREIGN KEY(budget_item_id) REFERENCES fiscal_expenditure_budget_items(budget_item_id) ON DELETE CASCADE,
  FOREIGN KEY(counterpart_budget_item_id) REFERENCES fiscal_expenditure_budget_items(budget_item_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fiscal_expenditure_settlement_links (
  budget_item_id TEXT NOT NULL,settlement_line_id TEXT NOT NULL,
  match_status TEXT NOT NULL CHECK(match_status IN ('verified','unconfirmed')),
  match_group_id TEXT NOT NULL,basis TEXT NOT NULL,
  PRIMARY KEY(budget_item_id,settlement_line_id),
  FOREIGN KEY(budget_item_id) REFERENCES fiscal_expenditure_budget_items(budget_item_id) ON DELETE CASCADE,
  FOREIGN KEY(settlement_line_id) REFERENCES fiscal_settlement_expenditure_lines(fiscal_line_id) ON DELETE CASCADE
);
CREATE TRIGGER IF NOT EXISTS fiscal_settlement_expenditure_lines_insert_scope BEFORE INSERT ON fiscal_settlement_expenditure_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind='settlement')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_settlement_expenditure_lines_update_scope BEFORE UPDATE ON fiscal_settlement_expenditure_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind='settlement')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_expenditure_budget_lines_insert_scope BEFORE INSERT ON fiscal_initial_expenditure_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind='budget')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_expenditure_budget_lines_update_scope BEFORE UPDATE ON fiscal_initial_expenditure_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind='budget')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_budget_changes_insert_scope BEFORE INSERT ON fiscal_expenditure_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind=NEW.change_kind)
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_budget_changes_update_scope BEFORE UPDATE ON fiscal_expenditure_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind=NEW.change_kind)
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TABLE IF NOT EXISTS fiscal_settlement_revenue_lines (
  fiscal_line_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
  source_row INTEGER NOT NULL, fund_code TEXT NOT NULL, fund_label TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND abs(amount)<=9007199254740991),
  consolidation TEXT NOT NULL CHECK(consolidation IN ('retained','eliminated')),
  counterpart_fund TEXT NOT NULL,

  PRIMARY KEY(fiscal_line_id),
  FOREIGN KEY(dataset_id) REFERENCES fiscal_datasets(dataset_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS fiscal_settlement_revenue_lines_dataset ON fiscal_settlement_revenue_lines(dataset_id,fiscal_line_id);
CREATE TABLE IF NOT EXISTS fiscal_settlement_revenue_line_hierarchy (
  fiscal_line_id TEXT NOT NULL,ordinal INTEGER NOT NULL,level TEXT NOT NULL,code TEXT NOT NULL,label TEXT NOT NULL,name_source TEXT NOT NULL,
  PRIMARY KEY(fiscal_line_id,ordinal),
  FOREIGN KEY(fiscal_line_id) REFERENCES fiscal_settlement_revenue_lines(fiscal_line_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fiscal_settlement_revenue_line_dimensions (
  fiscal_line_id TEXT NOT NULL,dimension TEXT NOT NULL,code TEXT NOT NULL,label TEXT NOT NULL,
  PRIMARY KEY(fiscal_line_id,dimension),
  FOREIGN KEY(fiscal_line_id) REFERENCES fiscal_settlement_revenue_lines(fiscal_line_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fiscal_settlement_revenue_line_names (
  fiscal_line_id TEXT NOT NULL,name_kind TEXT NOT NULL,level TEXT NOT NULL,value TEXT NOT NULL,name_source TEXT NOT NULL,basis TEXT NOT NULL,
  PRIMARY KEY(fiscal_line_id,name_kind,level),
  FOREIGN KEY(fiscal_line_id) REFERENCES fiscal_settlement_revenue_lines(fiscal_line_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fiscal_revenue_budget_items (
  budget_item_id TEXT NOT NULL,jurisdiction_code TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,fund_code TEXT NOT NULL,fund_label TEXT NOT NULL,
  account_path_json TEXT NOT NULL,dimensions_json TEXT NOT NULL,names_json TEXT NOT NULL,
  initial_state TEXT NOT NULL CHECK(initial_state IN ('recorded','verified-zero','unknown')),
  PRIMARY KEY(budget_item_id),
  FOREIGN KEY(jurisdiction_code) REFERENCES fiscal_jurisdiction_data(jurisdiction_code)
);
CREATE TABLE IF NOT EXISTS fiscal_initial_revenue_budget_lines (
  fiscal_line_id TEXT NOT NULL,dataset_id TEXT NOT NULL,
  budget_item_id TEXT NOT NULL,source_row INTEGER NOT NULL,amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND abs(amount)<=9007199254740991),
  consolidation TEXT NOT NULL CHECK(consolidation IN ('retained','eliminated')),
  counterpart_fund TEXT NOT NULL,

  PRIMARY KEY(fiscal_line_id),UNIQUE(budget_item_id),
  FOREIGN KEY(dataset_id) REFERENCES fiscal_datasets(dataset_id) ON DELETE CASCADE,
  FOREIGN KEY(budget_item_id) REFERENCES fiscal_revenue_budget_items(budget_item_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fiscal_revenue_budget_changes (
  change_id TEXT NOT NULL,dataset_id TEXT NOT NULL,budget_item_id TEXT NOT NULL,
  amount_delta INTEGER NOT NULL CHECK(typeof(amount_delta)='integer' AND abs(amount_delta)<=9007199254740991),
  change_kind TEXT NOT NULL CHECK(change_kind IN ('supplementary','carryover')),
  effective_at TEXT NOT NULL,sequence INTEGER NOT NULL,source_row INTEGER NOT NULL,
  counterpart_budget_item_id TEXT,carryover_from_year INTEGER,carryover_to_year INTEGER,

  PRIMARY KEY(change_id),
  FOREIGN KEY(dataset_id) REFERENCES fiscal_datasets(dataset_id) ON DELETE CASCADE,
  FOREIGN KEY(budget_item_id) REFERENCES fiscal_revenue_budget_items(budget_item_id) ON DELETE CASCADE,
  FOREIGN KEY(counterpart_budget_item_id) REFERENCES fiscal_revenue_budget_items(budget_item_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fiscal_revenue_settlement_links (
  budget_item_id TEXT NOT NULL,settlement_line_id TEXT NOT NULL,
  match_status TEXT NOT NULL CHECK(match_status IN ('verified','unconfirmed')),
  match_group_id TEXT NOT NULL,basis TEXT NOT NULL,
  PRIMARY KEY(budget_item_id,settlement_line_id),
  FOREIGN KEY(budget_item_id) REFERENCES fiscal_revenue_budget_items(budget_item_id) ON DELETE CASCADE,
  FOREIGN KEY(settlement_line_id) REFERENCES fiscal_settlement_revenue_lines(fiscal_line_id) ON DELETE CASCADE
);
CREATE TRIGGER IF NOT EXISTS fiscal_settlement_revenue_lines_insert_scope BEFORE INSERT ON fiscal_settlement_revenue_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind='settlement')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_settlement_revenue_lines_update_scope BEFORE UPDATE ON fiscal_settlement_revenue_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind='settlement')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_revenue_budget_lines_insert_scope BEFORE INSERT ON fiscal_initial_revenue_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind='budget')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_revenue_budget_lines_update_scope BEFORE UPDATE ON fiscal_initial_revenue_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind='budget')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_budget_changes_insert_scope BEFORE INSERT ON fiscal_revenue_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind=NEW.change_kind)
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_budget_changes_update_scope BEFORE UPDATE ON fiscal_revenue_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind=NEW.change_kind)
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_expenditure_budget_lines_insert_item_scope BEFORE INSERT ON fiscal_initial_expenditure_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_datasets d ON d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_expenditure_budget_lines_update_item_scope BEFORE UPDATE ON fiscal_initial_expenditure_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_datasets d ON d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_budget_changes_insert_item_scope BEFORE INSERT ON fiscal_expenditure_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_datasets d ON d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_budget_changes_update_item_scope BEFORE UPDATE ON fiscal_expenditure_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_datasets d ON d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_settlement_links_insert_scope BEFORE INSERT ON fiscal_expenditure_settlement_links
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_settlement_expenditure_lines l ON l.fund_code=b.fund_code JOIN fiscal_datasets d ON d.dataset_id=l.dataset_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND l.fiscal_line_id=NEW.settlement_line_id)
BEGIN SELECT RAISE(ABORT,'Settlement correspondence scope differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_settlement_links_update_scope BEFORE UPDATE ON fiscal_expenditure_settlement_links
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_settlement_expenditure_lines l ON l.fund_code=b.fund_code JOIN fiscal_datasets d ON d.dataset_id=l.dataset_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND l.fiscal_line_id=NEW.settlement_line_id)
BEGIN SELECT RAISE(ABORT,'Settlement correspondence scope differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_revenue_budget_lines_insert_item_scope BEFORE INSERT ON fiscal_initial_revenue_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_datasets d ON d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_revenue_budget_lines_update_item_scope BEFORE UPDATE ON fiscal_initial_revenue_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_datasets d ON d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_budget_changes_insert_item_scope BEFORE INSERT ON fiscal_revenue_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_datasets d ON d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_budget_changes_update_item_scope BEFORE UPDATE ON fiscal_revenue_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_datasets d ON d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_settlement_links_insert_scope BEFORE INSERT ON fiscal_revenue_settlement_links
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_settlement_revenue_lines l ON l.fund_code=b.fund_code JOIN fiscal_datasets d ON d.dataset_id=l.dataset_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND l.fiscal_line_id=NEW.settlement_line_id)
BEGIN SELECT RAISE(ABORT,'Settlement correspondence scope differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_settlement_links_update_scope BEFORE UPDATE ON fiscal_revenue_settlement_links
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_settlement_revenue_lines l ON l.fund_code=b.fund_code JOIN fiscal_datasets d ON d.dataset_id=l.dataset_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.budget_item_id=NEW.budget_item_id AND l.fiscal_line_id=NEW.settlement_line_id)
BEGIN SELECT RAISE(ABORT,'Settlement correspondence scope differs'); END;
