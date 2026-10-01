declare module 'cloudflare:workers' {
  export class RpcTarget {}
  export class WorkerEntrypoint<Env> {
    protected env: Env
  }
}
