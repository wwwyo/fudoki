import { resolve } from 'node:path'

export const PIPELINE = import.meta.dirname
export const REPO = resolve(PIPELINE, '..')
