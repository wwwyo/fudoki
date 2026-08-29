/**
 * OpenAPI spec を contract から生成し、ファイルへ書き出す。
 * 手書きの spec は持たない — 出力は `/v0/openapi.json` が実行時に配信するものと
 * 同じ内容（同じ contract・同じ specGenerateOptions・同じ ZodToJsonSchemaConverter から
 * 生成する）。apps/docs（blume）が静的ファイルとして参照するために使う。
 *
 * 実行: bun run generate-spec.ts <出力先パス>
 */
import { writeFileSync } from 'node:fs'
import { OpenAPIGenerator } from '@orpc/openapi'
import { ZodToJsonSchemaConverter } from '@orpc/zod/zod4'
import { contract } from './src/contract'
import { specGenerateOptions } from './src/spec'

const outPath = process.argv[2]
if (!outPath) {
  console.error('usage: bun run generate-spec.ts <output path>')
  process.exit(1)
}

const generator = new OpenAPIGenerator({
  schemaConverters: [new ZodToJsonSchemaConverter()],
})

const spec = await generator.generate(contract, specGenerateOptions)

writeFileSync(outPath, `${JSON.stringify(spec, null, 2)}\n`)
console.log(`wrote OpenAPI spec -> ${outPath}`)
