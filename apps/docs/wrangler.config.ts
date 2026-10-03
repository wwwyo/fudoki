import { defineWranglerConfig } from 'wrangler/experimental-config'

export default defineWranglerConfig({
  types: { generate: false },
  dev: { port: 5175, inspectorPort: 9235 },
})
