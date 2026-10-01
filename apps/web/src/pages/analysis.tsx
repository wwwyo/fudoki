import { useEffect, useState } from 'react'
import { FiscalYearSelect } from '@/components/fiscal-year-select'
import { JurisdictionSelect } from '@/components/jurisdiction-select'
import { Layout } from '@/components/layout'
import { NotCollectedPage } from '@/components/not-collected-page'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/card'
import { withBase } from '@/lib/utils'
import { DIR_JA, count, senYen, type Direction } from '@/lib/display'
import { apiClient } from '@/lib/api-client'
import {
  buildCofogTree,
  type AggregateResponse,
  type CofogNodeFilter,
  type CofogTreeNode,
} from '@/lib/cofog-tree'
import { CofogTree } from '@/components/cofog-tree'
import { CofogStatement } from '@/components/cofog-statement'

type Catalog = Awaited<ReturnType<typeof apiClient.listFiscalDatasets>> &
  Awaited<ReturnType<typeof apiClient.listJurisdictions>>
type Dataset = Catalog['datasets'][number]
const DOCUMENT_LABELS: Record<Dataset['documentKind'], string> = {
  budget: '予算書',
  supplementary: '補正予算書',
  settlement: '決算書',
  carryover: '繰越計算書',
  'reserve-allocation': '予備費充用',
  transfer: '流用',
}
export function AnalysisPage({
  urlCode = null,
  jurisdictionName,
}: { urlCode?: string | null; jurisdictionName?: string } = {}) {
  const [data, setData] = useState<Catalog | null>(null),
    [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let stale = false
    apiClient
      .listJurisdictions({})
      .then(async (jurisdictions) => {
        const datasets = await apiClient.listFiscalDatasets({
          versions: jurisdictions.versions,
        })
        if (stale) return
        setData({ ...jurisdictions, ...datasets })
        if (!urlCode) {
          const first = datasets.datasets[0]?.jurisdictionCode
          if (first) window.location.replace(withBase(`/analysis/${first}/`))
        }
      })
      .catch((e) => {
        if (!stale) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      stale = true
    }
  }, [urlCode])
  const collected =
    data?.datasets.filter((d) => d.jurisdictionCode === urlCode) ?? []
  if (error)
    return (
      <Layout>
        <main className="p-6">
          <Alert variant="destructive">
            <AlertTitle>データを取得できません</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </main>
      </Layout>
    )
  if (!data || !urlCode)
    return (
      <Layout>
        <main className="p-6 text-muted-foreground">読み込み中…</main>
      </Layout>
    )
  if (!collected.length)
    return (
      <NotCollectedPage
        code={urlCode}
        name={jurisdictionName}
        jurisdictions={data.jurisdictions
          .filter((j) =>
            data.datasets.some((d) => d.jurisdictionCode === j.code)
          )
          .map((j) => ({ code: j.code, name: j.name }))}
        basePath="analysis"
      />
    )
  return <CollectedAnalysis key={urlCode} data={data} code={urlCode} />
}
function Choice<T extends string>({
  label,
  value,
  items,
  onChange,
}: {
  label: string
  value: T
  items: { value: T; label: string }[]
  onChange: (value: T) => void
}) {
  return (
    <label className="flex min-w-32 flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <Select
        items={items}
        value={value}
        onValueChange={(v) => {
          if (v !== null) onChange(v as T)
        }}
      >
        <SelectTrigger aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  )
}
function CollectedAnalysis({ data, code }: { data: Catalog; code: string }) {
  const jurisdiction = data.jurisdictions.find((j) => j.code === code)!
  const collected = data.datasets.filter((d) => d.jurisdictionCode === code)
  const years = [...new Set(collected.map((d) => d.fiscalYear))].sort(
    (a, b) => a - b
  )
  const [year, setYear] = useState(years.at(-1)!),
    [direction, setDirection] = useState<Direction>('expenditure'),
    [datasetId, setDatasetId] = useState('')
  const [consolidation, setConsolidation] = useState<
      'all' | 'retained' | 'eliminated'
    >('retained'),
    [fund, setFund] = useState('all')
  const [nodes, setNodes] = useState<CofogTreeNode[]>([]),
    [aggregate, setAggregate] = useState<AggregateResponse | null>(null),
    [selected, setSelected] = useState<CofogNodeFilter | null>(null),
    [error, setError] = useState<string | null>(null)
  const [files, setFiles] = useState<
    Awaited<ReturnType<typeof apiClient.listFiles>>['files']
  >([])
  const choices = collected.filter(
    (d) =>
      d.fiscalYear === year &&
      d.direction === direction &&
      (d.documentKind === 'budget' || d.documentKind === 'settlement')
  )
  const dataset = choices.find((d) => d.id === datasetId) ?? null
  useEffect(() => {
    document.title = `${jurisdiction.name}の支出分析 | 風土記`
  }, [jurisdiction.name])
  useEffect(() => {
    setDatasetId(choices.length === 1 ? choices[0]!.id : '')
    setFund('all')
    setSelected(null)
  }, [year, direction])
  useEffect(() => {
    setSelected(null)
  }, [dataset?.id])
  useEffect(() => {
    let stale = false
    apiClient
      .listFiles({ versions: data.versions, jurisdictionCode: code })
      .then((result) => {
        if (!stale) setFiles(result.files)
      })
      .catch((e) => {
        if (!stale) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      stale = true
    }
  }, [code, data.versions])
  useEffect(() => {
    let stale = false
    setAggregate(null)
    setNodes([])
    setSelected(null)
    setError(null)
    if (!dataset) return
    const query = {
      versions: data.versions,
      datasetIds: [dataset.id],
      consolidation,
      fund: fund === 'all' ? undefined : fund,
    }
    const task =
      direction === 'expenditure'
        ? Promise.all([
            apiClient.aggregateFiscalDatasets({
              ...query,
              groupBy: ['cofog.division'],
            }),
            apiClient.aggregateFiscalDatasets({
              ...query,
              groupBy: ['cofog.division', 'cofog.group'],
            }),
            apiClient.aggregateFiscalDatasets({
              ...query,
              groupBy: ['cofog.division', 'cofog.group', 'cofog.class'],
            }),
          ]).then(([division, group, classification]) => {
            if (!stale) {
              setAggregate(division)
              setNodes(buildCofogTree(division, group, classification))
            }
          })
        : apiClient
            .aggregateFiscalDatasets({ ...query, groupBy: ['year'] })
            .then((result) => {
              if (!stale) setAggregate(result)
            })
    task.catch((e) => {
      if (!stale) setError(e instanceof Error ? e.message : String(e))
    })
    return () => {
      stale = true
    }
  }, [dataset?.id, direction, data.versions, consolidation, fund])
  return (
    <Layout>
      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-8">
        <header className="space-y-4">
          <h1 className="text-2xl font-semibold">
            {jurisdiction.name}の支出分析
          </h1>
          <div className="flex flex-wrap items-end gap-3">
            <JurisdictionSelect
              jurisdictions={data.jurisdictions
                .filter((j) =>
                  data.datasets.some((d) => d.jurisdictionCode === j.code)
                )
                .map((j) => ({ code: j.code, name: j.name }))}
              value={code}
              basePath="analysis"
            />
            <FiscalYearSelect
              years={years}
              value={year}
              onChange={(v) => {
                if (v !== null) setYear(v)
              }}
            />
            <Choice
              label="歳出・歳入"
              value={direction}
              onChange={setDirection}
              items={(['expenditure', 'revenue'] as const).map((d) => ({
                value: d,
                label: DIR_JA[d],
              }))}
            />
            {choices.length > 1 && (
              <Choice
                label="参照する原典"
                value={datasetId}
                onChange={setDatasetId}
                items={[
                  { value: '', label: '原典を選んでください' },
                  ...choices.map((d) => ({
                    value: d.id,
                    label: `${DOCUMENT_LABELS[d.documentKind]} (${d.originSha256.slice(0, 12)})`,
                  })),
                ]}
              />
            )}
            {dataset && (
              <Choice
                label="会計"
                value={fund}
                onChange={setFund}
                items={[
                  { value: 'all', label: '全会計' },
                  ...dataset.structure.funds.map((f) => ({
                    value: f.code,
                    label: f.label || f.code,
                  })),
                ]}
              />
            )}
            <Choice
              label="会計間の繰出入"
              value={consolidation}
              onChange={setConsolidation}
              items={[
                { value: 'retained', label: '会計間移転を除く' },
                { value: 'all', label: '会計間移転を含む' },
                { value: 'eliminated', label: '会計間移転のみ' },
              ]}
            />
          </div>
          {dataset && (
            <p className="text-sm text-muted-foreground">
              {DOCUMENT_LABELS[dataset.documentKind]}（
              {dataset.source.documentLabel}）を参照。
              <a
                className="underline"
                href={dataset.source.landingPage}
                target="_blank"
                rel="noreferrer"
              >
                自治体の原典公開ページ
              </a>{' '}
              / {dataset.source.licenseId}
            </p>
          )}
        </header>
        {error && (
          <Alert variant="destructive">
            <AlertTitle>データを取得できません</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {!choices.length && (
          <p>この年度の{DIR_JA[direction]}は収録していません。</p>
        )}
        {choices.length > 1 && !dataset && (
          <p>
            同じ年度の資料を重ねて集計しないため、参照する原典を一つ選んでください。
          </p>
        )}
        {dataset && aggregate?.total && (
          <Card>
            <CardHeader>
              <CardDescription>
                {year}年度 {DIR_JA[direction]} /{' '}
                {dataset.documentKind === 'settlement'
                  ? '実績額'
                  : '当初予算額'}
              </CardDescription>
              <CardTitle>{senYen(aggregate.total.amount)} 千円</CardTitle>
              <CardDescription>
                {count(aggregate.total.lineCount)} 件。会計間の繰出入:{' '}
                {consolidation === 'all'
                  ? '含む'
                  : consolidation === 'retained'
                    ? '除く'
                    : 'のみ'}
              </CardDescription>
            </CardHeader>
          </Card>
        )}
        {dataset && direction === 'expenditure' && nodes.length > 0 && (
          <CofogTree
            nodes={nodes}
            selected={selected}
            onSelect={setSelected}
            renderDetail={(filter) => (
              <CofogStatement
                versions={data.versions}
                datasetId={dataset.id}
                filter={filter}
                consolidation={consolidation}
                fund={fund === 'all' ? undefined : fund}
              />
            )}
          />
        )}
        {dataset && direction === 'revenue' && (
          <CofogStatement
            versions={data.versions}
            datasetId={dataset.id}
            consolidation={consolidation}
            fund={fund === 'all' ? undefined : fund}
          />
        )}
        <section className="space-y-3">
          <h2 className="font-semibold">データの注意点</h2>
          {jurisdiction.caveats.map((c) => (
            <details key={c.category + ':' + c.topic}>
              <summary>{c.topic}</summary>
              <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                {c.body}
              </p>
            </details>
          ))}
        </section>
        <section className="space-y-2">
          <h2 className="font-semibold">配布データ</h2>
          <div className="flex flex-wrap gap-3 text-sm">
            {files.map((file) => (
              <a key={file.path} className="underline" href={file.url}>
                {file.path.split('/').at(-1)}
              </a>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            団体のデータ版: {jurisdiction.versionId}
          </p>
        </section>
      </main>
    </Layout>
  )
}
