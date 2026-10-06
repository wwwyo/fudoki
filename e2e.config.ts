import { randomUUID } from 'node:crypto'
import { createOpenAICompatible } from '@ai-sdk/openai-compatible'
import { web } from '@e2e-dev/web'
import type { E2EConfig } from 'e2e'

if (process.env.E2E_TELEMETRY_DISABLED !== '1') {
  throw new Error('Set E2E_TELEMETRY_DISABLED=1 before starting e2e.')
}

const apiKey = process.env.OPENCODE_API_KEY
const model = process.env.OPENCODE_E2E_MODEL

const agents =
  apiKey && model
    ? {
        default: {
          model: createOpenAICompatible({
            name: 'opencode-go',
            baseURL: 'https://opencode.ai/zen/go/v1',
            apiKey,
            supportsStructuredOutputs: true,
            headers: {
              'User-Agent': 'wwwyo-e2e/0.1',
              'x-opencode-session': randomUUID(),
            },
          })(model),
          system:
            'Verify every goal on screen. Create and clean up your own test data.',
          maxSteps: 15,
          maxModelCalls: 15,
        },
      }
    : undefined

export default {
  tests: 'tests/**/*.e2e.ts',
  targets: [
    {
      engine: web(),
      app: {
        url: 'http://127.0.0.1:5174',
        command: {
          executable: 'bun',
          args: ['run', 'dev'],
          cwd: '.',
          env: { E2E_TELEMETRY_DISABLED: '1' },
          log: '.e2e/logs/app.log',
        },
      },
    },
  ],
  workers: 1,
  ...(agents ? { agents } : {}),
} satisfies E2EConfig
