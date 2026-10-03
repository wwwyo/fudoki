import { defineWranglerConfig } from 'wrangler/experimental-config'

export default defineWranglerConfig({
  types: { generate: false },
  dev: { port: 5173, inspectorPort: 9233 },
})
