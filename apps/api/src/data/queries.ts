import type { D1Database } from "@fudoki/data-contracts";
import {
  aggregateQuerySchema,
  type AggregateQuery,
  type Dataset,
  type FiscalLine,
  type LineQuery,
} from "../contract";
import { decodeCursor, encodeCursor, fingerprint } from "../lib/cursor";

export class QueryError extends Error {
  code: "BAD_REQUEST" | "NOT_FOUND" | "RELEASE_EXPIRED" | "UNAVAILABLE";
  constructor(code: QueryError["code"], message: string) {
    super(message);
    this.code = code;
  }
}
async function rows<T>(
  db: D1Database,
  sql: string,
  args: unknown[],
): Promise<T[]> {
  const result = await db
    .prepare(sql)
    .bind(...args)
    .all<T>();
  if (!result.success) throw new Error("Database query failed");
  return result.results;
}
export async function resolveRelease(
  db: D1Database,
  explicit?: string,
): Promise<string> {
  const result = explicit
    ? await db
        .prepare(
          "SELECT release_id FROM releases WHERE release_id=? AND state='published' AND contract_version=1",
        )
        .bind(explicit)
        .first<{ release_id: string }>()
    : await db
        .prepare(
          "SELECT r.release_id FROM active_release a JOIN releases r USING(release_id) WHERE a.singleton=1 AND r.state='published' AND r.contract_version=1",
        )
        .first<{ release_id: string }>();
  if (!result)
    throw new QueryError(
      explicit ? "RELEASE_EXPIRED" : "UNAVAILABLE",
      explicit
        ? "This release is no longer available"
        : "No published release is active",
    );
  return result.release_id;
}
function dataset(row: Record<string, unknown>): Dataset {
  return {
    id: row.dataset_id as string,
    jurisdictionCode: row.jurisdiction_code as string,
    fiscalYear: row.fiscal_year as number,
    direction: row.direction as Dataset["direction"],
    documentKind: row.document_kind as Dataset["documentKind"],
    originSha256: row.origin_sha256 as string,
    phases: JSON.parse(row.phases_json as string),
    source: JSON.parse(row.source_json as string),
    structure: JSON.parse(row.structure_json as string),
    lineCount: row.line_count as number,
  };
}
export async function listDatasets(
  db: D1Database,
  releaseId: string,
  filter: {
    jurisdictionCode?: string;
    fiscalYear?: number;
    direction?: string;
    documentKind?: string;
  } = {},
): Promise<Dataset[]> {
  const clauses = ["release_id=?"],
    args: unknown[] = [releaseId];
  for (const [field, column] of [
    ["jurisdictionCode", "jurisdiction_code"],
    ["fiscalYear", "fiscal_year"],
    ["direction", "direction"],
    ["documentKind", "document_kind"],
  ] as const) {
    if (filter[field] !== undefined) {
      clauses.push(`${column}=?`);
      args.push(filter[field]);
    }
  }
  return (
    await rows<Record<string, unknown>>(
      db,
      `SELECT * FROM fiscal_datasets WHERE ${clauses.join(" AND ")} ORDER BY jurisdiction_code,fiscal_year,direction,document_kind,dataset_id`,
      args,
    )
  ).map(dataset);
}
export async function selectDatasets(
  db: D1Database,
  releaseId: string,
  ids: string[],
  phase?: string,
  aggregation = false,
): Promise<Dataset[]> {
  if (new Set(ids).size !== ids.length)
    throw new QueryError("BAD_REQUEST", "datasetIds contains duplicates");
  const found = (
    await rows<Record<string, unknown>>(
      db,
      "SELECT * FROM fiscal_datasets WHERE release_id=? AND dataset_id IN (SELECT value FROM json_each(?)) ORDER BY dataset_id",
      [releaseId, JSON.stringify(ids)],
    )
  ).map(dataset);
  if (found.length !== ids.length)
    throw new QueryError(
      "NOT_FOUND",
      "A selected dataset is not present in this release",
    );
  if (aggregation) {
    const scopes = found.map(
      (d) => `${d.jurisdictionCode}:${d.fiscalYear}:${d.direction}`,
    );
    if (new Set(scopes).size !== scopes.length)
      throw new QueryError(
        "BAD_REQUEST",
        "Choose one document and edition per jurisdiction, year and direction to avoid double counting",
      );
    if (new Set(found.map((d) => d.direction)).size !== 1)
      throw new QueryError(
        "BAD_REQUEST",
        "Revenue and expenditure require separate aggregates",
      );
  }
  if (
    phase &&
    found.some((d) => !d.phases.includes(phase as Dataset["phases"][number]))
  )
    throw new QueryError(
      "BAD_REQUEST",
      `phase ${phase} is not available for every selected dataset`,
    );
  return found;
}
function conditions(
  releaseId: string,
  input: Omit<LineQuery, "pageSize" | "cursor">,
) {
  const where = [
      "l.release_id=?",
      "l.dataset_id IN (SELECT value FROM json_each(?))",
    ],
    args: unknown[] = [releaseId, JSON.stringify(input.datasetIds)];
  if (input.phase) {
    where.push("a.phase=?");
    args.push(input.phase);
  } else where.push("a.is_primary=1");
  if (input.fund !== undefined) {
    where.push("l.fund_code=?");
    args.push(input.fund);
  }
  if (input.consolidation !== "all") {
    where.push("l.consolidation=?");
    args.push(input.consolidation);
  }
  for (const h of input.hierarchy) {
    where.push(
      "EXISTS(SELECT 1 FROM line_hierarchy h WHERE h.release_id=l.release_id AND h.fiscal_line_id=l.fiscal_line_id AND h.level=? AND h.code=?)",
    );
    args.push(h.level, h.code);
  }
  for (const field of ["division", "group", "class", "status"] as const) {
    const value = input.cofog?.[field];
    if (value !== undefined) {
      where.push(field === "status" ? "l.cofog_status=?" : `c."${field}"=?`);
      args.push(value);
    }
  }
  if (input.name) {
    where.push(
      "EXISTS(SELECT 1 FROM names n WHERE n.release_id=l.release_id AND n.fiscal_line_id=l.fiscal_line_id AND instr(n.value,?)>0)",
    );
    args.push(input.name);
  }
  return { where: where.join(" AND "), args };
}
const joined = `FROM fiscal_lines l JOIN amounts a ON a.release_id=l.release_id AND a.fiscal_line_id=l.fiscal_line_id
   LEFT JOIN (SELECT n.code,
     CASE n.level WHEN 'division' THEN n.code WHEN 'group' THEN p.code ELSE g.code END AS division,
     CASE n.level WHEN 'group' THEN n.code WHEN 'class' THEN p.code ELSE '' END AS "group",
     CASE n.level WHEN 'class' THEN n.code ELSE '' END AS class
     FROM cofog_codes n LEFT JOIN cofog_codes p ON p.code=n.parent_code LEFT JOIN cofog_codes g ON g.code=p.parent_code
   ) c ON c.code=l.cofog_code`;
const lineSelect = `SELECT l.fiscal_line_id AS id,l.dataset_id AS datasetId,l.source_row AS sourceRow,l.fund_code AS fundCode,l.fund_label AS fundLabel,
 a.phase,a.value,a.source_amount AS sourceAmount,a.source_amount_unit AS sourceAmountUnit,
 (SELECT json_group_array(json_object('level',h.level,'code',h.code,'label',h.label,'nameSource',h.name_source)) FROM (SELECT * FROM line_hierarchy WHERE release_id=l.release_id AND fiscal_line_id=l.fiscal_line_id ORDER BY ordinal) h) AS hierarchy,
 (SELECT json_group_array(json_object('dimension',d.dimension,'code',d.code,'label',d.label)) FROM (SELECT * FROM line_dimensions WHERE release_id=l.release_id AND fiscal_line_id=l.fiscal_line_id ORDER BY dimension) d) AS dimensions,
 (SELECT json_group_array(json_object('kind',n.name_kind,'level',n.level,'value',n.value,'nameSource',n.name_source,'basis',n.basis)) FROM (SELECT * FROM names WHERE release_id=l.release_id AND fiscal_line_id=l.fiscal_line_id ORDER BY name_kind,level) n) AS names,
 json_object('status',l.cofog_status,'division',coalesce(c.division,''),'group',coalesce(c."group",''),'class',coalesce(c.class,''),'consolidation',l.consolidation,'decidedAtLevel',l.cofog_decided_at_level,'ruleId',l.cofog_rule_id,'basis',l.cofog_basis,'counterpartFund',l.counterpart_fund) AS cofog`;
export async function queryLines(
  db: D1Database,
  releaseId: string,
  input: LineQuery,
  after = "",
): Promise<FiscalLine[]> {
  await selectDatasets(db, releaseId, input.datasetIds, input.phase);
  const scope = conditions(releaseId, input);
  const result = await rows<Record<string, unknown>>(
    db,
    `${lineSelect} ${joined} WHERE ${scope.where} AND l.fiscal_line_id>? ORDER BY l.fiscal_line_id LIMIT ?`,
    [...scope.args, after, input.pageSize + 1],
  );
  return result.map(
    (row) =>
      ({
        ...row,
        hierarchy: JSON.parse(row.hierarchy as string),
        dimensions: JSON.parse(row.dimensions as string),
        names: JSON.parse(row.names as string),
        cofog: JSON.parse(row.cofog as string),
      }) as FiscalLine,
  );
}
export async function pageLines(
  db: D1Database,
  secret: string,
  input: LineQuery,
) {
  if (!secret || secret.length < 32)
    throw new QueryError("UNAVAILABLE", "Cursor signing is not configured");
  let cursor;
  if (input.cursor) {
    try {
      cursor = await decodeCursor(input.cursor, secret);
    } catch {
      throw new QueryError("BAD_REQUEST", "Invalid cursor");
    }
  }
  const { cursor: _, releaseId: requested, ...query } = input;
  query.datasetIds = [...query.datasetIds].sort();
  query.hierarchy = [...query.hierarchy].sort(
    (a, b) => a.level.localeCompare(b.level) || a.code.localeCompare(b.code),
  );
  const hash = await fingerprint(query);
  if (
    cursor &&
    (cursor.fingerprint !== hash ||
      (requested !== undefined && requested !== cursor.releaseId))
  )
    throw new QueryError(
      "BAD_REQUEST",
      "Cursor belongs to another query or release",
    );
  const releaseId = await resolveRelease(db, cursor?.releaseId ?? requested);
  const result = await queryLines(
    db,
    releaseId,
    { ...query, releaseId },
    cursor?.after,
  );
  const more = result.length > input.pageSize;
  const lines = result.slice(0, input.pageSize);
  return {
    releaseId,
    lines,
    nextCursor: more
      ? await encodeCursor(
          { v: 1, releaseId, fingerprint: hash, after: lines.at(-1)!.id },
          secret,
        )
      : undefined,
  };
}
export async function aggregate(
  db: D1Database,
  releaseId: string,
  input: AggregateQuery,
) {
  input = aggregateQuerySchema.parse(input);
  if (new Set(input.groupBy).size !== input.groupBy.length)
    throw new QueryError("BAD_REQUEST", "groupBy contains duplicates");
  const datasets = await selectDatasets(
    db,
    releaseId,
    input.datasetIds,
    input.phase,
    true,
  );
  if (
    new Set(datasets.map((d) => d.jurisdictionCode)).size > 1 &&
    !input.groupBy.includes("jurisdiction")
  )
    throw new QueryError(
      "BAD_REQUEST",
      "Comparisons between jurisdictions must group by jurisdiction",
    );
  if (
    new Set(datasets.map((d) => d.fiscalYear)).size > 1 &&
    !input.groupBy.includes("year")
  )
    throw new QueryError(
      "BAD_REQUEST",
      "Comparisons between years must group by year",
    );
  const expressions = input.groupBy.map((key) => {
    if (key === "jurisdiction") return "d.jurisdiction_code";
    if (key === "year") return "CAST(d.fiscal_year AS TEXT)";
    if (key === "fund") return "l.fund_code";
    if (key.startsWith("cofog."))
      return `CASE WHEN l.cofog_status!='assigned' THEN l.cofog_status ELSE coalesce(nullif(c."${key.slice(6)}",''),'not-descended') END`;
    return `(SELECT json_group_array(json_array(h.level,h.code)) FROM (SELECT level,code FROM line_hierarchy WHERE release_id=l.release_id AND fiscal_line_id=l.fiscal_line_id AND ordinal<=(SELECT ordinal FROM line_hierarchy WHERE release_id=l.release_id AND fiscal_line_id=l.fiscal_line_id AND level='${key}') ORDER BY ordinal) h)`;
  });
  if (
    datasets[0]?.direction === "revenue" &&
    input.groupBy.some((k) => k.startsWith("cofog."))
  )
    throw new QueryError(
      "BAD_REQUEST",
      "COFOG classification applies to expenditure",
    );
  for (const key of input.groupBy.filter(
    (k) =>
      !["jurisdiction", "year", "fund"].includes(k) && !k.startsWith("cofog."),
  )) {
    const missing = await db
      .prepare(
        `SELECT 1 FROM fiscal_lines l WHERE l.release_id=? AND l.dataset_id IN (SELECT value FROM json_each(?)) AND NOT EXISTS(SELECT 1 FROM line_hierarchy h WHERE h.release_id=l.release_id AND h.fiscal_line_id=l.fiscal_line_id AND h.level=?) LIMIT 1`,
      )
      .bind(releaseId, JSON.stringify(input.datasetIds), key)
      .first();
    if (missing)
      throw new QueryError(
        "BAD_REQUEST",
        `Hierarchy level ${key} is not available for every selected line`,
      );
  }
  const scope = conditions(releaseId, input);
  const columns = expressions.map((e, i) => `${e} AS k${i}`).join(",");
  const result = await rows<Record<string, unknown>>(
    db,
    `SELECT ${columns},sum(a.value) AS amount,count(*) AS lineCount ${joined} JOIN fiscal_datasets d ON d.release_id=l.release_id AND d.dataset_id=l.dataset_id WHERE ${scope.where} GROUP BY ${expressions.map((_, i) => `k${i}`).join(",")} ORDER BY ${expressions.map((_, i) => `k${i}`).join(",")} LIMIT 10001`,
    scope.args,
  );
  if (result.length > 10000)
    throw new QueryError(
      "BAD_REQUEST",
      "Too many aggregate cells; restrict dataset or hierarchy scope",
    );
  const cells = result.map((r) => ({
    keys: expressions.map((_, i) => String(r[`k${i}`] ?? "")),
    amount: r.amount as number,
    lineCount: r.lineCount as number,
  }));
  const totals = await rows<{
    datasetId: string;
    phase: AggregateQuery["phase"];
    amount: number;
    lineCount: number;
  }>(
    db,
    `SELECT l.dataset_id AS datasetId,a.phase,sum(a.value) AS amount,count(*) AS lineCount ${joined} WHERE ${scope.where} GROUP BY l.dataset_id,a.phase ORDER BY l.dataset_id,a.phase`,
    scope.args,
  );
  if (
    cells.some((c) => !Number.isSafeInteger(c.amount)) ||
    totals.some((t) => !Number.isSafeInteger(t.amount))
  )
    throw new QueryError(
      "BAD_REQUEST",
      "Aggregate exceeds the exact integer range",
    );
  const total =
    totals.length === 1
      ? { amount: totals[0]!.amount, lineCount: totals[0]!.lineCount }
      : undefined;
  return { releaseId, datasets, groupBy: input.groupBy, cells, totals, total };
}
export async function jurisdictions(db: D1Database, releaseId: string) {
  const result = await rows<{
    jurisdiction_code: string;
    name: string;
    ocd_id: string;
    caveats_json: string;
  }>(
    db,
    "SELECT jurisdiction_code,name_snapshot AS name,ocd_id_snapshot AS ocd_id,caveats_json FROM release_jurisdictions WHERE release_id=? ORDER BY jurisdiction_code",
    [releaseId],
  );
  return result.map((r) => ({
    code: r.jurisdiction_code,
    name: r.name,
    ocdId: r.ocd_id,
    caveats: JSON.parse(r.caveats_json),
  }));
}
export async function files(
  db: D1Database,
  releaseId: string,
  baseUrl: string,
  jurisdictionCode?: string,
) {
  const args: unknown[] = [releaseId];
  const scope = jurisdictionCode ? " AND path LIKE ?" : "";
  if (jurisdictionCode) args.push(`fiscal/${jurisdictionCode}/%`);
  const result = await rows<{
    path: string;
    sha256: string;
    bytes: number;
    content_type: string;
    object_key: string;
  }>(
    db,
    `SELECT path,object_key,sha256,bytes,content_type FROM files WHERE release_id=?${scope} ORDER BY path`,
    args,
  );
  return result.map((r) => ({
    path: r.path,
    url: `${baseUrl.replace(/\/$/, "")}/${r.object_key}`,
    sha256: r.sha256,
    bytes: r.bytes,
    contentType: r.content_type,
  }));
}
