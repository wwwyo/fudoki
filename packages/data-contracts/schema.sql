PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS database_identity (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  identity TEXT NOT NULL
);
INSERT OR IGNORE INTO database_identity VALUES(1,lower(hex(randomblob(16))));
CREATE TABLE IF NOT EXISTS releases (
  release_id TEXT PRIMARY KEY,
  contract_version INTEGER NOT NULL CHECK (contract_version = 1),
  state TEXT NOT NULL CHECK (state IN ('staging', 'published')),
  manifest_key TEXT,
  manifest_sha256 TEXT,
  code_revision TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS active_release (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  release_id TEXT NOT NULL REFERENCES releases(release_id),
  generation INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS jurisdictions (
  release_id TEXT NOT NULL REFERENCES releases(release_id),
  jurisdiction_code TEXT NOT NULL,
  name TEXT NOT NULL,
  ocd_id TEXT NOT NULL,
  caveats_json TEXT NOT NULL,
  PRIMARY KEY (release_id, jurisdiction_code)
);
CREATE TABLE IF NOT EXISTS fiscal_datasets (
  release_id TEXT NOT NULL REFERENCES releases(release_id),
  dataset_id TEXT NOT NULL,
  jurisdiction_code TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('expenditure', 'revenue')),
  document_kind TEXT NOT NULL,
  origin_sha256 TEXT NOT NULL,
  phases_json TEXT NOT NULL,
  source_json TEXT NOT NULL,
  structure_json TEXT NOT NULL,
  line_count INTEGER NOT NULL,
  PRIMARY KEY (release_id, dataset_id)
);
CREATE TABLE IF NOT EXISTS fiscal_lines (
  release_id TEXT NOT NULL,
  fiscal_line_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  source_row INTEGER NOT NULL,
  fund_code TEXT NOT NULL,
  fund_label TEXT NOT NULL,
  PRIMARY KEY (release_id, fiscal_line_id),
  FOREIGN KEY (release_id, dataset_id) REFERENCES fiscal_datasets(release_id, dataset_id)
);
CREATE TABLE IF NOT EXISTS amounts (
  release_id TEXT NOT NULL,
  fiscal_line_id TEXT NOT NULL,
  phase TEXT NOT NULL CHECK (phase IN ('approved', 'adjusted', 'adjusted-before-transfer', 'executed')),
  value INTEGER NOT NULL,
  source_amount INTEGER NOT NULL,
  source_amount_unit TEXT NOT NULL,
  is_primary INTEGER NOT NULL CHECK (is_primary IN (0, 1)),
  PRIMARY KEY (release_id, fiscal_line_id, phase),
  FOREIGN KEY (release_id, fiscal_line_id) REFERENCES fiscal_lines(release_id, fiscal_line_id)
);
CREATE TABLE IF NOT EXISTS cofog (
  release_id TEXT NOT NULL,
  fiscal_line_id TEXT NOT NULL,
  status TEXT NOT NULL,
  division TEXT NOT NULL,
  "group" TEXT NOT NULL,
  class TEXT NOT NULL,
  consolidation TEXT NOT NULL,
  decided_at_level TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  basis TEXT NOT NULL,
  counterpart_fund TEXT NOT NULL,
  PRIMARY KEY (release_id, fiscal_line_id),
  FOREIGN KEY (release_id, fiscal_line_id) REFERENCES fiscal_lines(release_id, fiscal_line_id)
);
CREATE TABLE IF NOT EXISTS line_hierarchy (
  release_id TEXT NOT NULL,
  fiscal_line_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  level TEXT NOT NULL,
  code TEXT NOT NULL,
  label TEXT NOT NULL,
  name_source TEXT NOT NULL,
  PRIMARY KEY (release_id, fiscal_line_id, ordinal),
  FOREIGN KEY (release_id, fiscal_line_id) REFERENCES fiscal_lines(release_id, fiscal_line_id)
);
CREATE TABLE IF NOT EXISTS line_dimensions (
  release_id TEXT NOT NULL,
  fiscal_line_id TEXT NOT NULL,
  dimension TEXT NOT NULL,
  code TEXT NOT NULL,
  label TEXT NOT NULL,
  PRIMARY KEY (release_id, fiscal_line_id, dimension),
  FOREIGN KEY (release_id, fiscal_line_id) REFERENCES fiscal_lines(release_id, fiscal_line_id)
);
CREATE TABLE IF NOT EXISTS names (
  release_id TEXT NOT NULL,
  fiscal_line_id TEXT NOT NULL,
  name_kind TEXT NOT NULL,
  level TEXT NOT NULL,
  value TEXT NOT NULL,
  name_source TEXT NOT NULL,
  basis TEXT NOT NULL,
  PRIMARY KEY (release_id, fiscal_line_id, name_kind, level),
  FOREIGN KEY (release_id, fiscal_line_id) REFERENCES fiscal_lines(release_id, fiscal_line_id)
);
CREATE TABLE IF NOT EXISTS files (
  release_id TEXT NOT NULL REFERENCES releases(release_id),
  path TEXT NOT NULL,
  object_key TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  content_type TEXT NOT NULL,
  PRIMARY KEY (release_id, path)
);
CREATE INDEX IF NOT EXISTS datasets_scope ON fiscal_datasets(release_id, jurisdiction_code, fiscal_year, direction, document_kind);
CREATE INDEX IF NOT EXISTS lines_dataset ON fiscal_lines(release_id, dataset_id, fiscal_line_id);
CREATE INDEX IF NOT EXISTS amounts_phase ON amounts(release_id, phase, fiscal_line_id);
CREATE INDEX IF NOT EXISTS hierarchy_path ON line_hierarchy(release_id, level, code, fiscal_line_id);
CREATE INDEX IF NOT EXISTS names_line ON names(release_id, fiscal_line_id);
CREATE TABLE IF NOT EXISTS publish_control (
  singleton INTEGER PRIMARY KEY CHECK (singleton=1),
  owner TEXT,
  fence INTEGER NOT NULL DEFAULT 0,
  expires_at INTEGER NOT NULL DEFAULT 0,
  expected_release_id TEXT,
  expected_generation INTEGER NOT NULL DEFAULT 0,
  candidate_release_id TEXT
);
INSERT OR IGNORE INTO publish_control(singleton) VALUES(1);
CREATE TABLE IF NOT EXISTS publish_guard (valid INTEGER NOT NULL CHECK(valid=1));
CREATE TABLE IF NOT EXISTS release_history (
  release_id TEXT PRIMARY KEY REFERENCES releases(release_id),
  generation INTEGER NOT NULL
);
