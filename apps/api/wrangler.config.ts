import { defineWranglerConfig } from 'wrangler/experimental-config'

export default defineWranglerConfig({
  dev: { ip: '127.0.0.1', port: 8787, inspectorPort: 9237 },
  types: {
    generate: false,
  },
})
