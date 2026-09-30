import { join } from 'node:path'
import { BUILD, LATEST } from '../paths'
import { verifyCandidate } from '../fdp/manifest'

if (!LATEST)
  throw new Error('Run pipeline:build before loading local downloads')
await verifyCandidate(join(BUILD, 'releases', LATEST.releaseId))
const child = Bun.spawn(
  ['node', join(import.meta.dirname, 'setup-download.mjs')],
  {
    stdout: 'inherit',
    stderr: 'inherit',
  }
)
if ((await child.exited) !== 0)
  throw new Error('Unable to load local downloads')
