PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS database_identity (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1), identity TEXT NOT NULL
);
INSERT OR IGNORE INTO database_identity VALUES(1,lower(hex(randomblob(16))));
CREATE TABLE IF NOT EXISTS jurisdictions (
  jurisdiction_code TEXT PRIMARY KEY, name TEXT NOT NULL, ocd_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cofog_codes (
  code TEXT PRIMARY KEY, label TEXT NOT NULL,
  level TEXT NOT NULL CHECK(level IN ('division','group','class')),
  parent_code TEXT REFERENCES cofog_codes(code),
  CHECK((level='division' AND length(code)=2 AND parent_code IS NULL)
    OR (level='group' AND length(code)=4 AND parent_code=substr(code,1,2))
    OR (level='class' AND length(code)=6 AND parent_code=substr(code,1,4)))
);
CREATE TABLE IF NOT EXISTS fiscal_jurisdiction_versions (
  version_id TEXT PRIMARY KEY,
  jurisdiction_code TEXT NOT NULL REFERENCES jurisdictions(jurisdiction_code),
  contract_version INTEGER NOT NULL CHECK(contract_version=2),
  package_id TEXT,
  name_snapshot TEXT NOT NULL, ocd_id_snapshot TEXT NOT NULL, caveats_json TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  manifest_url TEXT NOT NULL, manifest_sha256 TEXT NOT NULL,
  UNIQUE(version_id,jurisdiction_code)
);
CREATE INDEX IF NOT EXISTS fiscal_versions_latest ON fiscal_jurisdiction_versions(jurisdiction_code,registered_at DESC,version_id DESC);
CREATE TABLE IF NOT EXISTS fiscal_datasets (
  version_id TEXT NOT NULL, dataset_id TEXT NOT NULL, jurisdiction_code TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('expenditure','revenue')),
  document_kind TEXT NOT NULL CHECK(document_kind IN ('budget','supplementary','settlement','carryover','reserve-allocation','transfer')),
  origin_sha256 TEXT NOT NULL, source_json TEXT NOT NULL, structure_json TEXT NOT NULL,
  line_count INTEGER NOT NULL CHECK(line_count>=0),
  amendment_number INTEGER, effective_at TEXT, source_amount_kind TEXT,
  coverage_json TEXT NOT NULL,
  PRIMARY KEY(version_id,dataset_id),
  FOREIGN KEY(version_id,jurisdiction_code) REFERENCES fiscal_jurisdiction_versions(version_id,jurisdiction_code)
);
CREATE TABLE IF NOT EXISTS fiscal_package_files (
  version_id TEXT NOT NULL, path TEXT NOT NULL, jurisdiction_code TEXT NOT NULL,
  object_key TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL CHECK(bytes>=0),content_type TEXT NOT NULL,
  PRIMARY KEY(version_id,path),
  FOREIGN KEY(version_id,jurisdiction_code) REFERENCES fiscal_jurisdiction_versions(version_id,jurisdiction_code)
);
CREATE TABLE IF NOT EXISTS fiscal_settlement_expenditure_lines (
  version_id TEXT NOT NULL, fiscal_line_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
  source_row INTEGER NOT NULL, fund_code TEXT NOT NULL, fund_label TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND abs(amount)<=9007199254740991),
  consolidation TEXT NOT NULL CHECK(consolidation IN ('retained','eliminated')),
  counterpart_fund TEXT NOT NULL,
  cofog_code TEXT REFERENCES cofog_codes(code),
  cofog_status TEXT NOT NULL CHECK(cofog_status IN ('assigned','unclassifiable','out-of-scope')),
  cofog_basis TEXT NOT NULL,
  CHECK((cofog_status='assigned' AND cofog_code IS NOT NULL) OR (cofog_status!='assigned' AND cofog_code IS NULL)),
  PRIMARY KEY(version_id,fiscal_line_id),
  FOREIGN KEY(version_id,dataset_id) REFERENCES fiscal_datasets(version_id,dataset_id)
);
CREATE INDEX IF NOT EXISTS fiscal_settlement_expenditure_lines_dataset ON fiscal_settlement_expenditure_lines(version_id,dataset_id,fiscal_line_id);
CREATE TABLE IF NOT EXISTS fiscal_settlement_expenditure_line_hierarchy (
  version_id TEXT NOT NULL,fiscal_line_id TEXT NOT NULL,ordinal INTEGER NOT NULL,level TEXT NOT NULL,code TEXT NOT NULL,label TEXT NOT NULL,name_source TEXT NOT NULL,
  PRIMARY KEY(version_id,fiscal_line_id,ordinal),
  FOREIGN KEY(version_id,fiscal_line_id) REFERENCES fiscal_settlement_expenditure_lines(version_id,fiscal_line_id)
);
CREATE TABLE IF NOT EXISTS fiscal_settlement_expenditure_line_dimensions (
  version_id TEXT NOT NULL,fiscal_line_id TEXT NOT NULL,dimension TEXT NOT NULL,code TEXT NOT NULL,label TEXT NOT NULL,
  PRIMARY KEY(version_id,fiscal_line_id,dimension),
  FOREIGN KEY(version_id,fiscal_line_id) REFERENCES fiscal_settlement_expenditure_lines(version_id,fiscal_line_id)
);
CREATE TABLE IF NOT EXISTS fiscal_settlement_expenditure_line_names (
  version_id TEXT NOT NULL,fiscal_line_id TEXT NOT NULL,name_kind TEXT NOT NULL,level TEXT NOT NULL,value TEXT NOT NULL,name_source TEXT NOT NULL,basis TEXT NOT NULL,
  PRIMARY KEY(version_id,fiscal_line_id,name_kind,level),
  FOREIGN KEY(version_id,fiscal_line_id) REFERENCES fiscal_settlement_expenditure_lines(version_id,fiscal_line_id)
);
CREATE TABLE IF NOT EXISTS fiscal_expenditure_budget_items (
  version_id TEXT NOT NULL,budget_item_id TEXT NOT NULL,jurisdiction_code TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,fund_code TEXT NOT NULL,fund_label TEXT NOT NULL,
  account_path_json TEXT NOT NULL,dimensions_json TEXT NOT NULL,names_json TEXT NOT NULL,
  initial_state TEXT NOT NULL CHECK(initial_state IN ('recorded','verified-zero','unknown')),
  PRIMARY KEY(version_id,budget_item_id),
  FOREIGN KEY(version_id,jurisdiction_code) REFERENCES fiscal_jurisdiction_versions(version_id,jurisdiction_code)
);
CREATE TABLE IF NOT EXISTS fiscal_initial_expenditure_budget_lines (
  version_id TEXT NOT NULL,fiscal_line_id TEXT NOT NULL,dataset_id TEXT NOT NULL,
  budget_item_id TEXT NOT NULL,source_row INTEGER NOT NULL,amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND abs(amount)<=9007199254740991),
  consolidation TEXT NOT NULL CHECK(consolidation IN ('retained','eliminated')),
  counterpart_fund TEXT NOT NULL,
  cofog_code TEXT REFERENCES cofog_codes(code),
  cofog_status TEXT NOT NULL CHECK(cofog_status IN ('assigned','unclassifiable','out-of-scope')),
  cofog_basis TEXT NOT NULL,
  CHECK((cofog_status='assigned' AND cofog_code IS NOT NULL) OR (cofog_status!='assigned' AND cofog_code IS NULL)),
  PRIMARY KEY(version_id,fiscal_line_id),UNIQUE(version_id,budget_item_id),
  FOREIGN KEY(version_id,dataset_id) REFERENCES fiscal_datasets(version_id,dataset_id),
  FOREIGN KEY(version_id,budget_item_id) REFERENCES fiscal_expenditure_budget_items(version_id,budget_item_id)
);
CREATE TABLE IF NOT EXISTS fiscal_expenditure_budget_changes (
  version_id TEXT NOT NULL,change_id TEXT NOT NULL,dataset_id TEXT NOT NULL,budget_item_id TEXT NOT NULL,
  amount_delta INTEGER NOT NULL CHECK(typeof(amount_delta)='integer' AND abs(amount_delta)<=9007199254740991),
  change_kind TEXT NOT NULL CHECK(change_kind IN ('supplementary','carryover','reserve-allocation','transfer')),
  effective_at TEXT NOT NULL,sequence INTEGER NOT NULL,source_row INTEGER NOT NULL,
  counterpart_budget_item_id TEXT,carryover_from_year INTEGER,carryover_to_year INTEGER,
  cofog_code TEXT REFERENCES cofog_codes(code),
  cofog_status TEXT NOT NULL CHECK(cofog_status IN ('assigned','unclassifiable','out-of-scope')),
  cofog_basis TEXT NOT NULL,
  CHECK((cofog_status='assigned' AND cofog_code IS NOT NULL) OR (cofog_status!='assigned' AND cofog_code IS NULL)),
  PRIMARY KEY(version_id,change_id),
  FOREIGN KEY(version_id,dataset_id) REFERENCES fiscal_datasets(version_id,dataset_id),
  FOREIGN KEY(version_id,budget_item_id) REFERENCES fiscal_expenditure_budget_items(version_id,budget_item_id),
  FOREIGN KEY(version_id,counterpart_budget_item_id) REFERENCES fiscal_expenditure_budget_items(version_id,budget_item_id)
);
CREATE TABLE IF NOT EXISTS fiscal_expenditure_settlement_links (
  version_id TEXT NOT NULL,budget_item_id TEXT NOT NULL,settlement_line_id TEXT NOT NULL,
  match_status TEXT NOT NULL CHECK(match_status IN ('verified','unconfirmed')),
  match_group_id TEXT NOT NULL,basis TEXT NOT NULL,
  PRIMARY KEY(version_id,budget_item_id,settlement_line_id),
  FOREIGN KEY(version_id,budget_item_id) REFERENCES fiscal_expenditure_budget_items(version_id,budget_item_id),
  FOREIGN KEY(version_id,settlement_line_id) REFERENCES fiscal_settlement_expenditure_lines(version_id,fiscal_line_id)
);
CREATE TRIGGER IF NOT EXISTS fiscal_settlement_expenditure_lines_insert_scope BEFORE INSERT ON fiscal_settlement_expenditure_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind='settlement')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_settlement_expenditure_lines_update_scope BEFORE UPDATE ON fiscal_settlement_expenditure_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind='settlement')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_expenditure_budget_lines_insert_scope BEFORE INSERT ON fiscal_initial_expenditure_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind='budget')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_expenditure_budget_lines_update_scope BEFORE UPDATE ON fiscal_initial_expenditure_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind='budget')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_budget_changes_insert_scope BEFORE INSERT ON fiscal_expenditure_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind=NEW.change_kind)
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_budget_changes_update_scope BEFORE UPDATE ON fiscal_expenditure_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='expenditure' AND d.document_kind=NEW.change_kind)
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TABLE IF NOT EXISTS fiscal_settlement_revenue_lines (
  version_id TEXT NOT NULL, fiscal_line_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
  source_row INTEGER NOT NULL, fund_code TEXT NOT NULL, fund_label TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND abs(amount)<=9007199254740991),
  consolidation TEXT NOT NULL CHECK(consolidation IN ('retained','eliminated')),
  counterpart_fund TEXT NOT NULL,

  PRIMARY KEY(version_id,fiscal_line_id),
  FOREIGN KEY(version_id,dataset_id) REFERENCES fiscal_datasets(version_id,dataset_id)
);
CREATE INDEX IF NOT EXISTS fiscal_settlement_revenue_lines_dataset ON fiscal_settlement_revenue_lines(version_id,dataset_id,fiscal_line_id);
CREATE TABLE IF NOT EXISTS fiscal_settlement_revenue_line_hierarchy (
  version_id TEXT NOT NULL,fiscal_line_id TEXT NOT NULL,ordinal INTEGER NOT NULL,level TEXT NOT NULL,code TEXT NOT NULL,label TEXT NOT NULL,name_source TEXT NOT NULL,
  PRIMARY KEY(version_id,fiscal_line_id,ordinal),
  FOREIGN KEY(version_id,fiscal_line_id) REFERENCES fiscal_settlement_revenue_lines(version_id,fiscal_line_id)
);
CREATE TABLE IF NOT EXISTS fiscal_settlement_revenue_line_dimensions (
  version_id TEXT NOT NULL,fiscal_line_id TEXT NOT NULL,dimension TEXT NOT NULL,code TEXT NOT NULL,label TEXT NOT NULL,
  PRIMARY KEY(version_id,fiscal_line_id,dimension),
  FOREIGN KEY(version_id,fiscal_line_id) REFERENCES fiscal_settlement_revenue_lines(version_id,fiscal_line_id)
);
CREATE TABLE IF NOT EXISTS fiscal_settlement_revenue_line_names (
  version_id TEXT NOT NULL,fiscal_line_id TEXT NOT NULL,name_kind TEXT NOT NULL,level TEXT NOT NULL,value TEXT NOT NULL,name_source TEXT NOT NULL,basis TEXT NOT NULL,
  PRIMARY KEY(version_id,fiscal_line_id,name_kind,level),
  FOREIGN KEY(version_id,fiscal_line_id) REFERENCES fiscal_settlement_revenue_lines(version_id,fiscal_line_id)
);
CREATE TABLE IF NOT EXISTS fiscal_revenue_budget_items (
  version_id TEXT NOT NULL,budget_item_id TEXT NOT NULL,jurisdiction_code TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,fund_code TEXT NOT NULL,fund_label TEXT NOT NULL,
  account_path_json TEXT NOT NULL,dimensions_json TEXT NOT NULL,names_json TEXT NOT NULL,
  initial_state TEXT NOT NULL CHECK(initial_state IN ('recorded','verified-zero','unknown')),
  PRIMARY KEY(version_id,budget_item_id),
  FOREIGN KEY(version_id,jurisdiction_code) REFERENCES fiscal_jurisdiction_versions(version_id,jurisdiction_code)
);
CREATE TABLE IF NOT EXISTS fiscal_initial_revenue_budget_lines (
  version_id TEXT NOT NULL,fiscal_line_id TEXT NOT NULL,dataset_id TEXT NOT NULL,
  budget_item_id TEXT NOT NULL,source_row INTEGER NOT NULL,amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND abs(amount)<=9007199254740991),
  consolidation TEXT NOT NULL CHECK(consolidation IN ('retained','eliminated')),
  counterpart_fund TEXT NOT NULL,

  PRIMARY KEY(version_id,fiscal_line_id),UNIQUE(version_id,budget_item_id),
  FOREIGN KEY(version_id,dataset_id) REFERENCES fiscal_datasets(version_id,dataset_id),
  FOREIGN KEY(version_id,budget_item_id) REFERENCES fiscal_revenue_budget_items(version_id,budget_item_id)
);
CREATE TABLE IF NOT EXISTS fiscal_revenue_budget_changes (
  version_id TEXT NOT NULL,change_id TEXT NOT NULL,dataset_id TEXT NOT NULL,budget_item_id TEXT NOT NULL,
  amount_delta INTEGER NOT NULL CHECK(typeof(amount_delta)='integer' AND abs(amount_delta)<=9007199254740991),
  change_kind TEXT NOT NULL CHECK(change_kind IN ('supplementary','carryover')),
  effective_at TEXT NOT NULL,sequence INTEGER NOT NULL,source_row INTEGER NOT NULL,
  counterpart_budget_item_id TEXT,carryover_from_year INTEGER,carryover_to_year INTEGER,

  PRIMARY KEY(version_id,change_id),
  FOREIGN KEY(version_id,dataset_id) REFERENCES fiscal_datasets(version_id,dataset_id),
  FOREIGN KEY(version_id,budget_item_id) REFERENCES fiscal_revenue_budget_items(version_id,budget_item_id),
  FOREIGN KEY(version_id,counterpart_budget_item_id) REFERENCES fiscal_revenue_budget_items(version_id,budget_item_id)
);
CREATE TABLE IF NOT EXISTS fiscal_revenue_settlement_links (
  version_id TEXT NOT NULL,budget_item_id TEXT NOT NULL,settlement_line_id TEXT NOT NULL,
  match_status TEXT NOT NULL CHECK(match_status IN ('verified','unconfirmed')),
  match_group_id TEXT NOT NULL,basis TEXT NOT NULL,
  PRIMARY KEY(version_id,budget_item_id,settlement_line_id),
  FOREIGN KEY(version_id,budget_item_id) REFERENCES fiscal_revenue_budget_items(version_id,budget_item_id),
  FOREIGN KEY(version_id,settlement_line_id) REFERENCES fiscal_settlement_revenue_lines(version_id,fiscal_line_id)
);
CREATE TRIGGER IF NOT EXISTS fiscal_settlement_revenue_lines_insert_scope BEFORE INSERT ON fiscal_settlement_revenue_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind='settlement')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_settlement_revenue_lines_update_scope BEFORE UPDATE ON fiscal_settlement_revenue_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind='settlement')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_revenue_budget_lines_insert_scope BEFORE INSERT ON fiscal_initial_revenue_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind='budget')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_revenue_budget_lines_update_scope BEFORE UPDATE ON fiscal_initial_revenue_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind='budget')
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_budget_changes_insert_scope BEFORE INSERT ON fiscal_revenue_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind=NEW.change_kind)
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_budget_changes_update_scope BEFORE UPDATE ON fiscal_revenue_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_datasets d WHERE d.version_id=NEW.version_id AND d.dataset_id=NEW.dataset_id AND d.direction='revenue' AND d.document_kind=NEW.change_kind)
BEGIN SELECT RAISE(ABORT,'Fiscal dataset direction or document differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_expenditure_budget_lines_insert_item_scope BEFORE INSERT ON fiscal_initial_expenditure_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_datasets d ON d.version_id=b.version_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_expenditure_budget_lines_update_item_scope BEFORE UPDATE ON fiscal_initial_expenditure_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_datasets d ON d.version_id=b.version_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_budget_changes_insert_item_scope BEFORE INSERT ON fiscal_expenditure_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_datasets d ON d.version_id=b.version_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_budget_changes_update_item_scope BEFORE UPDATE ON fiscal_expenditure_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_datasets d ON d.version_id=b.version_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_settlement_links_insert_scope BEFORE INSERT ON fiscal_expenditure_settlement_links
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_settlement_expenditure_lines l ON l.version_id=b.version_id AND l.fund_code=b.fund_code JOIN fiscal_datasets d ON d.version_id=l.version_id AND d.dataset_id=l.dataset_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND l.fiscal_line_id=NEW.settlement_line_id)
BEGIN SELECT RAISE(ABORT,'Settlement correspondence scope differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_expenditure_settlement_links_update_scope BEFORE UPDATE ON fiscal_expenditure_settlement_links
WHEN NOT EXISTS(SELECT 1 FROM fiscal_expenditure_budget_items b JOIN fiscal_settlement_expenditure_lines l ON l.version_id=b.version_id AND l.fund_code=b.fund_code JOIN fiscal_datasets d ON d.version_id=l.version_id AND d.dataset_id=l.dataset_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND l.fiscal_line_id=NEW.settlement_line_id)
BEGIN SELECT RAISE(ABORT,'Settlement correspondence scope differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_revenue_budget_lines_insert_item_scope BEFORE INSERT ON fiscal_initial_revenue_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_datasets d ON d.version_id=b.version_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_initial_revenue_budget_lines_update_item_scope BEFORE UPDATE ON fiscal_initial_revenue_budget_lines
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_datasets d ON d.version_id=b.version_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_budget_changes_insert_item_scope BEFORE INSERT ON fiscal_revenue_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_datasets d ON d.version_id=b.version_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_budget_changes_update_item_scope BEFORE UPDATE ON fiscal_revenue_budget_changes
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_datasets d ON d.version_id=b.version_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND d.dataset_id=NEW.dataset_id)
BEGIN SELECT RAISE(ABORT,'Budget item jurisdiction or fiscal year differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_settlement_links_insert_scope BEFORE INSERT ON fiscal_revenue_settlement_links
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_settlement_revenue_lines l ON l.version_id=b.version_id AND l.fund_code=b.fund_code JOIN fiscal_datasets d ON d.version_id=l.version_id AND d.dataset_id=l.dataset_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND l.fiscal_line_id=NEW.settlement_line_id)
BEGIN SELECT RAISE(ABORT,'Settlement correspondence scope differs'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_revenue_settlement_links_update_scope BEFORE UPDATE ON fiscal_revenue_settlement_links
WHEN NOT EXISTS(SELECT 1 FROM fiscal_revenue_budget_items b JOIN fiscal_settlement_revenue_lines l ON l.version_id=b.version_id AND l.fund_code=b.fund_code JOIN fiscal_datasets d ON d.version_id=l.version_id AND d.dataset_id=l.dataset_id AND d.jurisdiction_code=b.jurisdiction_code AND d.fiscal_year=b.fiscal_year
WHERE b.version_id=NEW.version_id AND b.budget_item_id=NEW.budget_item_id AND l.fiscal_line_id=NEW.settlement_line_id)
BEGIN SELECT RAISE(ABORT,'Settlement correspondence scope differs'); END;
