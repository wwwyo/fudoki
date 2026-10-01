import { expect, test } from "bun:test";
import worker from "./index";
import type { R2Bucket } from "@fudoki/data-contracts";
const releaseId = "r-" + "a".repeat(32);
const file = "fiscal/132195/expenditure.csv";
const packageId = "p-" + "e".repeat(64);
const key = `fiscal/132195/${packageId}/expenditure.csv`;
const body = "value\n100\n";
function storage() {
  const reads: string[] = [];
  const bucket: R2Bucket = {
    async get(key) {
      reads.push(key);
      const value = body;
      return {
        key,
        size: value.length,
        httpEtag: '"r2-etag"',
        body: new Blob([value]).stream(),
        async json<T>() {
          return JSON.parse(value) as T;
        },
        async arrayBuffer() {
          return new TextEncoder().encode(value).buffer;
        },
        writeHttpMetadata() {},
      };
    },
    async head(key) {
      reads.push(key);
      return { size: body.length, httpEtag: '"r2-etag"' };
    },
    async list() {
      throw new Error("File downloads do not enumerate objects");
    },
  };
  return { bucket, reads };
}
const request = (path: string, method = "GET") =>
  new Request(`https://download.example.org${path}`, { method });
test("public package files are independent of the global release manifest", async () => {
  const { bucket, reads } = storage();
  const response = await worker.fetch(request(`/${key}`), { RELEASES: bucket });
  expect(response.status).toBe(200);
  expect(await response.text()).toBe(body);
  expect(reads).toEqual([key]);
});
test("internal objects, legacy release file paths and write methods are refused", async () => {
  const { bucket } = storage();
  for (const path of [
    "/inputs/origin/sha256/x",
    "/_candidates/x/manifest.json",
    `/releases/${releaseId}/${file}`,
  ])
    expect(
      (await worker.fetch(request(path), { RELEASES: bucket })).status,
    ).toBe(404);
  expect(
    (await worker.fetch(request(`/${key}`, "PUT"), { RELEASES: bucket }))
      .status,
  ).toBe(405);
});
test("package bodies stream and use the storage ETag independently of the release", async () => {
  const { bucket } = storage(),
    get = bucket.get;
  bucket.get = async (key) => {
    const object = await get(key);
    if (object) {
      object.arrayBuffer = async () => {
        throw new Error("Do not buffer CSV");
      };
      object.json = async () => {
        throw new Error("Do not parse CSV");
      };
    }
    return object;
  };
  const response = await worker.fetch(request(`/${key}`), { RELEASES: bucket });
  expect(await response.text()).toBe(body);
  expect(response.headers.get("ETag")).toBe('"r2-etag"');
  expect(response.headers.has("X-Fudoki-Release")).toBe(false);
  expect(response.headers.get("Cache-Control")).toContain("immutable");
});
test("HEAD and conditional GET omit the package body", async () => {
  const { bucket } = storage();
  expect(
    await (
      await worker.fetch(request(`/${key}`, "HEAD"), { RELEASES: bucket })
    ).text(),
  ).toBe("");
  const conditional = request(`/${key}`);
  conditional.headers.set("if-none-match", '"r2-etag"');
  const response = await worker.fetch(conditional, { RELEASES: bucket });
  expect(response.status).toBe(304);
  expect(await response.text()).toBe("");
});

test("manifest and release discovery are not R2 resources", async () => {
  const { bucket, reads } = storage();
  for (const path of [
    "/manifest.json",
    "/catalog.json",
    "/releases",
    `/releases/${releaseId}/manifest.json`,
  ])
    expect(
      (await worker.fetch(request(path), { RELEASES: bucket })).status,
    ).toBe(404);
  expect(reads).toEqual([]);
});
