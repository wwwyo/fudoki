import { WorkerEntrypoint, RpcTarget } from 'cloudflare:workers'
import {
  Verification,
  type VerificationEnv,
  type HashStream,
} from './verification'
import {
  manifestSchema,
  type ReleaseManifest,
  type TABLES,
} from '@fudoki/data-contracts'

const hashStream: HashStream = async (stream) => {
  const runtime = crypto as typeof crypto & {
    DigestStream: new (
      algorithm: string
    ) => WritableStream<Uint8Array> & { digest: Promise<ArrayBuffer> }
  }
  const digest = new runtime.DigestStream('SHA-256')
  let bytes = 0
  await stream
    .pipeThrough(
      new TransformStream<Uint8Array, Uint8Array>({
        transform(chunk, controller) {
          bytes += chunk.byteLength
          controller.enqueue(chunk)
        },
      })
    )
    .pipeTo(digest)
  return {
    bytes,
    sha256: [...new Uint8Array(await digest.digest)]
      .map((b) => b.toString(16).padStart(2, '0'))
      .join(''),
  }
}
class VerificationSession extends RpcTarget {
  #verification: Verification
  constructor(env: VerificationEnv, manifest: ReleaseManifest) {
    super()
    this.#verification = new Verification(env, hashStream, manifest)
  }
  existingFile(releaseId: string, path: string) {
    return this.#verification.existingFile(releaseId, path)
  }
  candidate(releaseId: string) {
    return this.#verification.candidate(releaseId)
  }
  file(releaseId: string, path: string) {
    return this.#verification.file(releaseId, path)
  }
  chunk(releaseId: string, table: (typeof TABLES)[number], after?: unknown[]) {
    return this.#verification.chunk(releaseId, table, after)
  }
  api(releaseId: string, datasetId: string, phase: string) {
    return this.#verification.api(releaseId, datasetId, phase)
  }
  measure(releaseId: string) {
    return this.#verification.measure(releaseId)
  }
  publicContracts(releaseId: string) {
    return this.#verification.publicContracts(releaseId)
  }
  downloads(releaseId: string) {
    return this.#verification.downloads(releaseId)
  }
  download(releaseId: string, path: string) {
    return this.#verification.download(releaseId, path)
  }
}
export class PipelineVerification extends WorkerEntrypoint<VerificationEnv> {
  session(manifest: ReleaseManifest) {
    return new VerificationSession(this.env, manifestSchema.parse(manifest))
  }
}
export default {
  fetch() {
    return new Response(null, { status: 404 })
  },
}
