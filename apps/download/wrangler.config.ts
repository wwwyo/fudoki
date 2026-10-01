import { defineWranglerConfig } from 'wrangler/experimental-config'

export default defineWranglerConfig({
  dev: { ip: '127.0.0.1', port: 8788, inspectorPort: 9238 },
  types: {
    generate: false,
  },
})
