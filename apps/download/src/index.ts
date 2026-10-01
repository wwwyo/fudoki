import { CONTRACT_VERSION, type R2Bucket } from "@fudoki/data-contracts";
export interface Env {
  RELEASES: R2Bucket;
}
const immutable = "public, max-age=31536000, immutable";
function reply(status: number, message: string) {
  return Response.json(
    { error: message },
    {
      status,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-store",
      },
    },
  );
}
async function packageFile(request: Request, bucket: R2Bucket, key: string) {
  const file = request.method === "HEAD" ? null : await bucket.get(key);
  const object = request.method === "HEAD" ? await bucket.head(key) : file;
  if (!object) return reply(404, "NOT_FOUND");
  const headers = new Headers({
    "Content-Type": key.endsWith(".csv")
      ? "text/csv; charset=utf-8"
      : "application/json; charset=utf-8",
    "Content-Length": String(object.size),
    ETag: object.httpEtag,
    "Cache-Control": immutable,
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Expose-Headers": "ETag,Content-Length",
  });
  if (request.headers.get("if-none-match") === object.httpEtag) {
    if (file) await file.body.cancel();
    headers.delete("Content-Length");
    return new Response(null, { status: 304, headers });
  }
  return new Response(file?.body ?? null, { headers });
}
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== "GET" && request.method !== "HEAD")
      return reply(405, "METHOD_NOT_ALLOWED");
    const path = new URL(request.url).pathname;
    if (path === "/contract")
      return Response.json(
        { contractVersion: CONTRACT_VERSION },
        {
          headers: {
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
          },
        },
      );
    if (!/^\/fiscal\/\d{6}\/p-[a-f0-9]{64}\/[a-z_]+\.(?:csv|json)$/.test(path))
      return reply(404, "NOT_FOUND");
    try {
      return await packageFile(request, env.RELEASES, path.slice(1));
    } catch {
      return reply(503, "PACKAGE_UNAVAILABLE");
    }
  },
};
