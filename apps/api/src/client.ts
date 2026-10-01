import { createORPCClient } from '@orpc/client'
import { RPCLink } from '@orpc/client/fetch'
import type { RouterClient } from '@orpc/server'
import type { Router } from './router'

export function createPublicClient(base: string): RouterClient<Router> {
  return createORPCClient(new RPCLink({ url: new URL('/rpc', base).href }))
}
