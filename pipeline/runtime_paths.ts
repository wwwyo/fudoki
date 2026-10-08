import { resolve, join } from 'node:path'

export const PIPELINE = import.meta.dirname
export const REPO = resolve(PIPELINE, '..')
export const CACHE = join(PIPELINE, '.cache')
export const BUILD = join(PIPELINE, '.build')
export const WAREHOUSE = join(BUILD, 'warehouse.duckdb')
export const DBT_TARGET = join(BUILD, 'dbt')
export const REPORT = join(BUILD, 'report')
