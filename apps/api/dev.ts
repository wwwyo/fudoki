import { spawn } from 'node:child_process'

const port = Number(process.env.FUDOKI_API_PORT ?? 8787)
if (!Number.isInteger(port) || port < 1024 || port > 65535)
  throw new Error('FUDOKI_API_PORT must be a port between 1024 and 65535')
const child = spawn(
  'mise',
  [
    'exec',
    '--',
    'cf',
    'dev',
    '--mode',
    'development',
    '--host',
    '127.0.0.1',
    '--port',
    String(port),
  ],
  {
    cwd: import.meta.dirname,
    stdio: 'inherit',
    env: { ...process.env, WRANGLER_LOG: 'error' },
  }
)
for (const signal of ['SIGINT', 'SIGTERM'] as const)
  process.on(signal, () => child.kill(signal))
child.on('error', (error) => {
  throw error
})
child.on('exit', (code, signal) => {
  process.exit(code ?? (signal ? 1 : 0))
})
