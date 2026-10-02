/** 相手が名指しで拒否できるよう、取得時は同じ UA を使う。 */
export const UA = 'fudoki/0.1 (+https://github.com/wwwyo/fudoki)'

export const sha256 = (bytes: Uint8Array) => new Bun.CryptoHasher('sha256').update(bytes).digest('hex')
