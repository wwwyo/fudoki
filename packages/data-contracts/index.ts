import { z } from "zod";

export const CONTRACT_VERSION = 1;
export const TABLES = [
  "release_jurisdictions",
  "fiscal_datasets",
  "fiscal_lines",
  "amounts",
  "cofog",
  "line_hierarchy",
  "line_dimensions",
  "names",
] as const;
export const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/);
export const jurisdictionMasterSchema = z
  .object({
    jurisdiction_code: z.string().regex(/^\d{6}$/),
    name: z.string().min(1),
    ocd_id: z.string().min(1),
  })
  .strict();
export const releaseIdSchema = z.string().regex(/^r-[a-f0-9]{32}$/);
export const packageIdSchema = z.string().regex(/^p-[a-f0-9]{64}$/);
export const distributionKeySchema = z
  .string()
  .regex(/^fiscal\/\d{6}\/p-[a-f0-9]{64}\/[a-z_]+\.(?:csv|json)$/);
export const directionSchema = z.enum(["expenditure", "revenue"]);
export const documentKindSchema = z.enum([
  "budget",
  "supplementary",
  "settlement",
]);
export const phaseSchema = z.enum([
  "approved",
  "adjusted",
  "adjusted-before-transfer",
  "executed",
]);
export const cofogStatusSchema = z.enum([
  "assigned",
  "unclassifiable",
  "out-of-scope",
  "not-applicable",
]);
export const nameSourceSchema = z.enum([
  "canonical",
  "settlement-pdf",
  "judgment",
  "",
]);
export const amountUnitSchema = z.enum(["円", "千円"]);
export const fileSchema = z.object({
  path: z.string().regex(/^fiscal\/\d{6}\/[a-z_]+\.(?:csv|json)$/),
  objectKey: distributionKeySchema,
  sha256: sha256Schema,
  bytes: z.number().int().nonnegative(),
  contentType: z.enum([
    "text/csv; charset=utf-8",
    "application/json; charset=utf-8",
  ]),
});
export const packageSchema = z.object({
  jurisdictionCode: z.string().regex(/^\d{6}$/),
  packageId: packageIdSchema,
  datasetIds: z.array(z.string().min(1)).min(1),
});
export async function derivePackageId(
  files: Pick<
    z.infer<typeof fileSchema>,
    "path" | "sha256" | "bytes" | "contentType"
  >[],
): Promise<string> {
  const contents = [...files]
    .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0))
    .map(({ path, sha256, bytes, contentType }) => ({
      path,
      sha256,
      bytes,
      contentType,
    }));
  const hash = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify(contents)),
  );
  return (
    "p-" +
    [...new Uint8Array(hash)]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("")
  );
}
export const manifestSchema = z
  .object({
    schemaVersion: z.literal(CONTRACT_VERSION),
    releaseId: releaseIdSchema,
    codeRevision: z.string().regex(/^[a-f0-9]{40}$/),
    inputFingerprint: sha256Schema,
    judgmentFingerprint: sha256Schema,
    queryFingerprint: sha256Schema,
    manifestSha256: sha256Schema,
    jurisdictionMasterSha256: sha256Schema,
    files: z.array(fileSchema).min(1),
    packages: z.array(packageSchema),
    totals: z
      .array(
        z.object({
          datasetId: z.string(),
          phase: phaseSchema,
          rows: z.number().int().nonnegative(),
          amount: z.number().int().safe(),
        }),
      )
      .default([]),
    tables: z.record(
      z.enum(TABLES),
      z.object({
        rows: z.number().int().nonnegative(),
        sha256: sha256Schema,
        canonicalSha256: sha256Schema,
        chunks: z.array(sha256Schema),
      }),
    ),
  })
  .superRefine((manifest, context) => {
    const packages = new Map(
      manifest.packages.map((pkg) => [pkg.jurisdictionCode, pkg]),
    );
    if (packages.size !== manifest.packages.length)
      context.addIssue({
        code: "custom",
        message: "Duplicate jurisdiction package",
      });
    const datasets = manifest.packages.flatMap((pkg) => pkg.datasetIds);
    if (new Set(datasets).size !== datasets.length)
      context.addIssue({
        code: "custom",
        message: "Dataset belongs to multiple packages",
      });
    for (const file of manifest.files) {
      const match = /^fiscal\/(\d{6})\/([a-z_]+\.(?:csv|json))$/.exec(
        file.path,
      );
      const pkg = match ? packages.get(match[1]!) : undefined;
      const expected =
        match && pkg
          ? `fiscal/${pkg.jurisdictionCode}/${pkg.packageId}/${match[2]}`
          : undefined;
      if (!expected || file.objectKey !== expected)
        context.addIssue({
          code: "custom",
          message: "File key differs from its package or release",
        });
    }
    for (const pkg of manifest.packages)
      if (
        !manifest.files.some((file) =>
          file.path.startsWith(`fiscal/${pkg.jurisdictionCode}/`),
        )
      )
        context.addIssue({ code: "custom", message: "Package has no files" });
    if (
      new Set(manifest.files.map((file) => file.path)).size !==
      manifest.files.length
    )
      context.addIssue({ code: "custom", message: "Duplicate release file" });
    if (
      new Set(
        manifest.totals.map((total) => `${total.datasetId}:${total.phase}`),
      ).size !== manifest.totals.length
    )
      context.addIssue({
        code: "custom",
        message: "Duplicate dataset phase total",
      });
    for (const table of TABLES)
      if (
        manifest.tables[table].chunks.length !==
        Math.ceil(manifest.tables[table].rows / 500)
      )
        context.addIssue({
          code: "custom",
          message: `Chunk count differs: ${table}`,
        });
  });
export type ReleaseManifest = z.infer<typeof manifestSchema>;

export const distributionManifestSchema = z
  .object({
    schemaVersion: z.literal(CONTRACT_VERSION),
    buildId: releaseIdSchema,
    codeRevision: z.string().regex(/^[a-f0-9]{40}$/),
    inputFingerprint: sha256Schema,
    judgmentFingerprint: sha256Schema,
    files: z.array(fileSchema).min(1),
    packages: z.array(packageSchema),
    jurisdictions: z.array(
      z.looseObject({
        jurisdiction_code: z.string().regex(/^\d{6}$/),
        caveats: z.array(z.unknown()),
      }),
    ),
    datasets: z.array(
      z.looseObject({
        dataset_id: z.string().min(1),
        jurisdiction_code: z.string().regex(/^\d{6}$/),
        fiscal_year: z.number().int(),
        direction: directionSchema,
        document_kind: documentKindSchema,
        origin_sha256: sha256Schema,
        phases: z.array(phaseSchema),
        source: z.record(z.string(), z.unknown()),
        structure: z.record(z.string(), z.unknown()),
      }),
    ),
    amountUnit: z.literal("JPY"),
    documents: z.array(documentKindSchema),
    phases: z.array(phaseSchema),
    selection: z.string(),
  })
  .superRefine((manifest, context) => {
    const packages = new Map(
      manifest.packages.map((p) => [p.jurisdictionCode, p]),
    );
    if (packages.size !== manifest.packages.length)
      context.addIssue({
        code: "custom",
        message: "Duplicate jurisdiction package",
      });
    const datasetIds = manifest.datasets.map((d) => d.dataset_id);
    if (new Set(datasetIds).size !== datasetIds.length)
      context.addIssue({ code: "custom", message: "Duplicate dataset" });
    const adopted = manifest.packages.flatMap((p) => p.datasetIds);
    if (
      adopted.length !== datasetIds.length ||
      new Set(adopted).size !== adopted.length ||
      datasetIds.some((id) => !adopted.includes(id))
    )
      context.addIssue({
        code: "custom",
        message: "Package dataset coverage differs",
      });
    for (const dataset of manifest.datasets)
      if (
        !packages
          .get(dataset.jurisdiction_code)
          ?.datasetIds.includes(dataset.dataset_id)
      )
        context.addIssue({
          code: "custom",
          message: "Dataset belongs to another jurisdiction package",
        });
    if (
      new Set(manifest.files.map((f) => f.path)).size !== manifest.files.length
    )
      context.addIssue({
        code: "custom",
        message: "Duplicate distribution file",
      });
    for (const file of manifest.files) {
      const [_, code, name] = file.path.split("/");
      const pkg = packages.get(code!);
      if (!pkg || file.objectKey !== `fiscal/${code}/${pkg.packageId}/${name}`)
        context.addIssue({
          code: "custom",
          message: "File key differs from its package",
        });
    }
  });
export type DistributionManifest = z.infer<typeof distributionManifestSchema>;

export interface D1Statement {
  bind(...values: unknown[]): D1Statement;
  all<T = Record<string, unknown>>(): Promise<{
    results: T[];
    success: boolean;
    meta?: { changes?: number; rows_read?: number };
  }>;
  first<T = Record<string, unknown>>(): Promise<T | null>;
  run(): Promise<{ success: boolean; meta: { changes: number } }>;
}
export interface D1Database {
  prepare(sql: string): D1Statement;
  batch<T = Record<string, unknown>>(
    statements: D1Statement[],
  ): Promise<{ results: T[]; success: boolean; meta: { changes: number } }[]>;
}
export interface R2Object {
  key: string;
  size: number;
  httpEtag: string;
  body: ReadableStream<Uint8Array>;
  json<T>(): Promise<T>;
  arrayBuffer(): Promise<ArrayBuffer>;
  writeHttpMetadata(headers: Headers): void;
}
export interface R2Bucket {
  get(key: string): Promise<R2Object | null>;
  head(key: string): Promise<{ size: number; httpEtag: string } | null>;
  list(options: {
    prefix: string;
    delimiter?: string;
    cursor?: string;
    limit?: number;
  }): Promise<{
    objects: { key: string }[];
    delimitedPrefixes: string[];
    truncated: boolean;
    cursor?: string;
  }>;
}

export const TABLE_COLUMNS = {
  jurisdictions: ["jurisdiction_code", "name", "ocd_id"],
  release_jurisdictions: [
    "jurisdiction_code",
    "name_snapshot",
    "ocd_id_snapshot",
    "caveats_json",
  ],
  fiscal_datasets: [
    "dataset_id",
    "jurisdiction_code",
    "fiscal_year",
    "direction",
    "document_kind",
    "origin_sha256",
    "phases_json",
    "source_json",
    "structure_json",
    "line_count",
  ],
  fiscal_lines: [
    "fiscal_line_id",
    "dataset_id",
    "source_row",
    "fund_code",
    "fund_label",
  ],
  amounts: [
    "fiscal_line_id",
    "phase",
    "value",
    "source_amount",
    "source_amount_unit",
    "is_primary",
  ],
  cofog: [
    "fiscal_line_id",
    "status",
    "division",
    "group",
    "class",
    "consolidation",
    "decided_at_level",
    "rule_id",
    "basis",
    "counterpart_fund",
  ],
  line_hierarchy: [
    "fiscal_line_id",
    "ordinal",
    "level",
    "code",
    "label",
    "name_source",
  ],
  line_dimensions: ["fiscal_line_id", "dimension", "code", "label"],
  names: [
    "fiscal_line_id",
    "name_kind",
    "level",
    "value",
    "name_source",
    "basis",
  ],
} as const;
export const TABLE_KEYS = {
  jurisdictions: ["jurisdiction_code"],
  release_jurisdictions: ["jurisdiction_code"],
  fiscal_datasets: ["dataset_id"],
  fiscal_lines: ["fiscal_line_id"],
  amounts: ["fiscal_line_id", "phase"],
  cofog: ["fiscal_line_id"],
  line_hierarchy: ["fiscal_line_id", "ordinal"],
  line_dimensions: ["fiscal_line_id", "dimension"],
  names: ["fiscal_line_id", "name_kind", "level"],
} as const;
export function canonicalRow(
  table: keyof typeof TABLE_COLUMNS,
  row: Record<string, unknown>,
): string {
  return (
    JSON.stringify(
      Object.fromEntries(
        TABLE_COLUMNS[table].map((column) => [column, row[column]]),
      ),
    ) + "\n"
  );
}
