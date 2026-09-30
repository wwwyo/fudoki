import { WorkerEntrypoint } from 'cloudflare:workers'
import {
  Verification,
  type VerificationEnv,
  type HashStream,
} from './verification'
import type { TABLES } from '@fudoki/data-contracts'

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
export class PipelineVerification extends WorkerEntrypoint<VerificationEnv> {
  private verifier() {
    return new Verification(this.env, hashStream)
  }
  existingManifest(releaseId: string, sha256: string) {
    return this.verifier().existingManifest(releaseId, sha256)
  }
  existingFile(releaseId: string, path: string) {
    return this.verifier().existingFile(releaseId, path)
  }
  candidate(releaseId: string) {
    return this.verifier().candidate(releaseId)
  }
  file(releaseId: string, path: string) {
    return this.verifier().file(releaseId, path)
  }
  chunk(releaseId: string, table: (typeof TABLES)[number], after?: unknown[]) {
    return this.verifier().chunk(releaseId, table, after)
  }
  api(releaseId: string, datasetId: string, phase: string) {
    return this.verifier().api(releaseId, datasetId, phase)
  }
  measure(releaseId: string) {
    return this.verifier().measure(releaseId)
  }
  publicContracts(releaseId: string) {
    return this.verifier().publicContracts(releaseId)
  }
  downloads(releaseId: string) {
    return this.verifier().downloads(releaseId)
  }
  download(releaseId: string, path: string) {
    return this.verifier().download(releaseId, path)
  }
}
export default {
  fetch() {
    return new Response(null, { status: 404 })
  },
}
