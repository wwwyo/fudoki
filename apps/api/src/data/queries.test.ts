import { beforeEach, afterEach, expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { readFileSync } from "node:fs";
import { sqliteD1 } from "../../test/database";
import { aggregate, files, pageLines, resolveRelease } from "./queries";
import { aggregateQuerySchema, lineQuerySchema } from "../contract";

const R1 = "r-" + "1".repeat(32),
  R2 = "r-" + "2".repeat(32);
const secret = "test-only-secret-with-at-least-32-characters";
let sqlite: Database;
let db: ReturnType<typeof sqliteD1>;
beforeEach(() => {
  sqlite = new Database(":memory:");
  sqlite.exec(
    readFileSync(
      new URL(
        "../../../../packages/data-contracts/schema.sql",
        import.meta.url,
      ),
      "utf8",
    ),
  );
  db = sqliteD1(sqlite);
  for (const release of [R1, R2]) {
    sqlite.run("INSERT INTO releases VALUES(?,1,'published',NULL,NULL,?,?)", [
      release,
      "a".repeat(40),
      "b".repeat(64),
    ]);
    for (const [dataset, kind, phase] of [
      ["budget", "budget", "approved"],
      ["settlement", "settlement", "executed"],
    ]) {
      sqlite.run("INSERT INTO fiscal_datasets VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
        release,
        dataset!,
        "132195",
        2026,
        "expenditure",
        kind!,
        "c".repeat(64),
        JSON.stringify([phase]),
        JSON.stringify({
          documentLabel: kind,
          landingPage: "https://example.org",
          licenseId: "NOASSERTION",
          attribution: "自治体",
          rawForm: "extracted",
        }),
        JSON.stringify({ hierarchy: ["moku"], dimensions: [] }),
        3,
      ]);
      for (let i = 1; i <= 3; i++) {
        const id = dataset + ":" + i;
        sqlite.run("INSERT INTO fiscal_lines VALUES(?,?,?,?,?,?)", [
          release,
          id,
          dataset!,
          i,
          "01",
          "一般会計",
        ]);
        sqlite.run("INSERT INTO amounts VALUES(?,?,?,?,?,?,?)", [
          release,
          id,
          phase!,
          i * (release === R1 ? 100 : 1000),
          i,
          "円",
          1,
        ]);
        sqlite.run("INSERT INTO cofog VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
          release,
          id,
          "assigned",
          "09",
          "09.1",
          "09.1.1",
          i === 3 ? "eliminated" : "retained",
          "目",
          "rule",
          "根拠",
          "",
        ]);
        sqlite.run("INSERT INTO line_hierarchy VALUES(?,?,?,?,?,?,?)", [
          release,
          id,
          0,
          "moku",
          "001",
          "教育",
          "original",
        ]);
        sqlite.run("INSERT INTO names VALUES(?,?,?,?,?,?,?)", [
          release,
          id,
          "hierarchy",
          "moku",
          i === 1 ? "教育%_" : "教育' OR 1=1 --",
          "canonical",
          "",
        ]);
      }
    }
  }
  sqlite.run("INSERT INTO active_release(singleton,release_id) VALUES(1,?)", [
    R1,
  ]);
});
afterEach(() => sqlite.close());
const query = () =>
  lineQuerySchema.parse({ datasetIds: ["budget"], pageSize: 2 });
test("a cursor keeps the old published release after active release changes", async () => {
  const first = await pageLines(db, secret, query());
  expect(first.lines.map((l) => l.value)).toEqual([100, 200]);
  sqlite.run("UPDATE active_release SET release_id=?", [R2]);
  const next = await pageLines(db, secret, {
    ...query(),
    cursor: first.nextCursor,
  });
  expect(next.releaseId).toBe(R1);
  expect(next.lines.map((l) => l.value)).toEqual([300]);
  expect(next.nextCursor).toBeUndefined();
  expect((await pageLines(db, secret, query())).releaseId).toBe(R2);
});
test("tampering with sort position or query cannot produce an accepted cursor", async () => {
  const first = await pageLines(db, secret, query());
  const [body, sig] = first.nextCursor!.split(".");
  const payload = JSON.parse(Buffer.from(body!, "base64url").toString());
  payload.after = "budget:0";
  const forged =
    Buffer.from(JSON.stringify(payload)).toString("base64url") + "." + sig;
  await expect(
    pageLines(db, secret, { ...query(), cursor: forged }),
  ).rejects.toThrow("Invalid cursor");
  await expect(
    pageLines(db, secret, {
      ...query(),
      pageSize: 1,
      cursor: first.nextCursor,
    }),
  ).rejects.toThrow("another query");
});
test("missing or unpublished cursor release expires without silently changing its version", async () => {
  const first = await pageLines(db, secret, query());
  sqlite.run("UPDATE releases SET state='staging' WHERE release_id=?", [R1]);
  await expect(
    pageLines(db, secret, { ...query(), cursor: first.nextCursor }),
  ).rejects.toMatchObject({ code: "RELEASE_EXPIRED" });
  await expect(resolveRelease(db)).rejects.toMatchObject({
    code: "UNAVAILABLE",
  });
});
test("aggregation refuses two documents from the same scope and unavailable money phases", async () => {
  await expect(
    aggregate(
      db,
      R1,
      aggregateQuerySchema.parse({
        datasetIds: ["budget", "settlement"],
        phase: "approved",
        groupBy: ["year"],
      }),
    ),
  ).rejects.toThrow("double counting");
  await expect(
    pageLines(
      db,
      secret,
      lineQuerySchema.parse({ datasetIds: ["settlement"], phase: "approved" }),
    ),
  ).rejects.toThrow("not available");
  const result = await aggregate(
    db,
    R1,
    aggregateQuerySchema.parse({
      datasetIds: ["budget"],
      phase: "approved",
      groupBy: ["cofog.division"],
      consolidation: "retained",
    }),
  );
  expect(result.total).toEqual({ amount: 300, lineCount: 2 });
  expect(result.cells[0]?.keys).toEqual(["09"]);
});
test("names are matched literally with bound SQL, including SQL and LIKE metacharacters", async () => {
  const percent = await pageLines(
    db,
    secret,
    lineQuerySchema.parse({ datasetIds: ["budget"], name: "%_" }),
  );
  expect(percent.lines.map((l) => l.id)).toEqual(["budget:1"]);
  const sql = await pageLines(
    db,
    secret,
    lineQuerySchema.parse({ datasetIds: ["budget"], name: "' OR 1=1 --" }),
  );
  expect(sql.lines.map((l) => l.id)).toEqual(["budget:2", "budget:3"]);
  expect(sql.lines[0]?.hierarchy[0]?.label).toBe("教育");
});
test("download URLs come from file metadata without requesting R2 or reading the file body", async () => {
  sqlite.run("INSERT INTO files VALUES(?,?,?,?,?,?)", [
    R1,
    "fiscal/000001/expenditure.csv",
    `fiscal/000001/p-${"a".repeat(64)}/expenditure.csv`,
    "a".repeat(64),
    100,
    "application/json; charset=utf-8",
  ]);
  const result = await files(db, R1, "https://download.example.org");
  expect(result[0]?.url).toBe(
    `https://download.example.org/fiscal/000001/p-${"a".repeat(64)}/expenditure.csv`,
  );
});
test("two releases use the same immutable package URL for unchanged data", async () => {
  const key = `fiscal/000001/p-${"b".repeat(64)}/expenditure.csv`;
  for (const release of [R1, R2])
    sqlite.run("INSERT INTO files VALUES(?,?,?,?,?,?)", [
      release,
      "fiscal/000001/expenditure.csv",
      key,
      "a".repeat(64),
      100,
      "text/csv; charset=utf-8",
    ]);
  const first = await files(db, R1, "https://download.example.org", "000001");
  const next = await files(db, R2, "https://download.example.org", "000001");
  expect(first).toEqual(next);
  expect(next[0]?.url).toBe(`https://download.example.org/${key}`);
});

test("name matching respects case and Unicode representation and accepts Japanese phrases longer than 50 bytes", async () => {
  const long = "児童福祉施設における保育サービスの運営及び施設整備事業";
  const variants = ["ABC", "ＡＢＣ", "é", "e\u0301", long];
  for (const [i, name] of variants.entries())
    sqlite.run("INSERT INTO names VALUES(?,?,?,?,?,?,?)", [
      R1,
      "budget:1",
      "project",
      "variant" + i,
      name,
      "canonical",
      "",
    ]);
  for (const name of variants)
    expect(
      (
        await pageLines(
          db,
          secret,
          lineQuerySchema.parse({ datasetIds: ["budget"], name }),
        )
      ).lines.map((l) => l.id),
    ).toEqual(["budget:1"]);
  expect(
    (
      await pageLines(
        db,
        secret,
        lineQuerySchema.parse({ datasetIds: ["budget"], name: "abc" }),
      )
    ).lines,
  ).toEqual([]);
  expect(
    (
      await pageLines(
        db,
        secret,
        lineQuerySchema.parse({ datasetIds: ["budget"], name: "ＡBC" }),
      )
    ).lines,
  ).toEqual([]);
  expect(new TextEncoder().encode(long).length).toBeGreaterThan(50);
});
