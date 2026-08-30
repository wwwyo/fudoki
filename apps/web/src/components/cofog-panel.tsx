/**
 * COFOG の判断。
 *
 * ここは fudoki が三鷹市の言っていないことを付け加えている唯一の場所なので、
 * 「何をどこへ割り当て、なぜそう決めたか」を根拠まで出す。
 * **分類不能の割合の低さは合否に使わない** — 成立範囲を正直に調べるのが目的で、
 * 割合を目標にすると分類不能を減らす方向へ判断が歪む。
 */
import type { ReportData } from '@/lib/pipeline'
import { DIVISION_COLOR, STATUS_JA, pct, yen, yenShort } from '@/lib/pipeline'
import { Badge } from '@/components/ui/badge'
import { CofogChain } from '@/components/division'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const statusVariant = (s: string) => (s === 'assigned' ? 'secondary' : s === 'unclassifiable' ? 'outline' : 'outline')

export function CofogPanel({ report }: { report: ReportData }) {
  const t = report.transform
  // ⚠️ **画面で集計しない。** 以前はここで byState を status で絞って足していたが、
  // 同じ数字を生成側と画面側の2箇所で計算すると、いずれ食い違う。
  const divs = t.byDivision
  const assigned = t.assigned.sum
  const total = t.total.sum

  return (
    <div className="flex flex-col gap-6">
      <p className="max-w-[72ch] text-sm leading-relaxed text-muted-foreground">
        <span className="font-medium text-foreground">COFOG</span>（Classification of the Functions of Government）は政府支出の機能別分類で、
        教育や保健といった<span className="font-medium text-foreground">10の大分類</span>（01〜10）に分ける国際標準。
        版は {t.cofogVersion} ／
        コード表の取得元 <a className="underline" href={t.cofogSource.url} target="_blank" rel="noreferrer">{t.cofogSource.name}</a> ／
        規則 {t.ruleCount} 本（うち{t.ruleScope.shared} 本は法定語彙にもとづく共通の規則、{t.ruleScope.jurisdictionSpecific} 本はこの団体固有）。
        Budget Standard Taxonomy が提供するのは COFOG を<em>格納する語彙</em>だけで、
        日本の予算科目から COFOG への対応そのものは仕様側に存在しない。以下はすべて fudoki 固有の判断である。
      </p>

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">大分類別の金額</h3>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {divs.map((v) => (
            <span key={v.division} className="inline-flex items-center gap-1.5">
              <i aria-hidden className="size-2.5 rounded-sm" style={{ background: DIVISION_COLOR[v.division] }} />
              <span className="font-medium text-foreground">{v.division}</span> {v.divisionLabel} {yenShort(v.sum)}
            </span>
          ))}
        </div>
        <div className="flex h-6 overflow-hidden rounded-md border" role="img"
          aria-label={`割当済み ${yen(assigned)} 円の内訳: ` + divs.map((v) => `${v.division} ${v.divisionLabel} ${yenShort(v.sum)}`).join('、')}>
          {divs.map((v) => (
            <div key={v.division} style={{ width: `${(v.sum / assigned) * 100}%`, background: DIVISION_COLOR[v.division] }} />
          ))}
        </div>
        <p className="max-w-[72ch] text-xs text-muted-foreground">
          帯は<span className="font-medium text-foreground">割当済みのみ</span>（{yen(assigned)} 円）。
          これに分類不能と対象外を足すと原典の合計 {yen(total)} 円に戻る。
          帯の幅は割当済みの中での構成比であって、総額に対する比ではない。
        </p>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">COFOG のどの深さまで降りているか</h3>
        <p className="max-w-[72ch] text-sm leading-relaxed text-muted-foreground">
          COFOG も階層で、大分類（<code>04</code>）の下に中分類（<code>04.5</code>）、
          その下に小分類（<code>04.5.1</code>）がある。fudoki は
          <span className="font-medium text-foreground">規則が決めた粒度をそのまま持つ</span>。
        </p>
        <p className="max-w-[72ch] rounded-md border border-dashed p-3 text-sm leading-relaxed">
          ⚠️ <span className="font-medium">中分類・小分類が空なのは「該当が無い」ではなく
          「まだ降りていない」</span>という意味である。
          款の名称だけで決まる規則（総務費 → 01、民生費 → 10）は
          <span className="font-medium">大分類止まりが正しく</span>、
          中分類を埋めるには項や目まで下げる判断が要る。
          下表は達成率ではなく<span className="font-medium">現在地</span>で、
          割合の高さを品質の指標として使わない（分類不能の割合と同じ扱い）。
        </p>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>深さ</TableHead>
                <TableHead className="text-right">そこまで降りた行数</TableHead>
                <TableHead className="text-right">割当済みに対する割合</TableHead>
                <TableHead className="text-right">金額（円）</TableHead>
                <TableHead className="text-right">金額の割合</TableHead>
                <TableHead className="text-right">そこで止まった行数</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {t.cofogReach.map((r) => (
                <TableRow key={r.depth}>
                  <TableCell className="whitespace-nowrap">{r.label}</TableCell>
                  <TableCell className="text-right tabular-nums">{yen(r.reached.count)}</TableCell>
                  <TableCell className="text-right tabular-nums">{pct(r.share.count)}</TableCell>
                  <TableCell className="text-right tabular-nums">{yen(r.reached.sum)}</TableCell>
                  <TableCell className="text-right tabular-nums">{pct(r.share.sum)}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{yen(r.deepest.count)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <p className="max-w-[72ch] text-xs text-muted-foreground">
          母数は<span className="font-medium text-foreground">割当済みの {yen(t.assigned.count)} 行</span>
          （{yen(t.assigned.sum)} 円）。分類不能・対象外には割当先が無いので深さも無く、ここには入らない。
          「そこまで降りた」は累積（小分類まで降りた行は中分類にも数える）、
          「そこで止まった」はその深さが最も深い到達点である行。
        </p>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">割当先ごとの金額</h3>
        <p className="max-w-[72ch] text-sm text-muted-foreground">
          割当済みを COFOG のコードごとに。
          同じ大分類が複数行に分かれるのは、降りている深さが規則ごとに違うため
          （<code>09</code> 止まりの行と <code>09.1</code> まで降りた行は別の事実である）。
        </p>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>割当先</TableHead>
                <TableHead className="text-right">行数</TableHead>
                <TableHead className="text-right">金額（円）</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {t.byCode.map((c) => (
                <TableRow key={`${c.division}/${c.group}/${c.class}`}>
                  <TableCell><CofogChain code={c} /></TableCell>
                  <TableCell className="text-right tabular-nums">{yen(c.count)}</TableCell>
                  <TableCell className="text-right tabular-nums">{yen(c.sum)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">どの単位で割り当てが決まったか</h3>
        <p className="max-w-[72ch] text-sm text-muted-foreground">
          款だけで決まらなかった金額が、項・目のどこまで下げれば決まったかを示す。
        </p>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow><TableHead>決まった単位</TableHead><TableHead className="text-right">行数</TableHead><TableHead className="text-right">金額（円）</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {t.byLevel.map((l) => (
                <TableRow key={l.level}>
                  <TableCell>{l.level}</TableCell>
                  <TableCell className="text-right tabular-nums">{yen(l.count)}</TableCell>
                  <TableCell className="text-right tabular-nums">{yen(l.sum)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">款ごとの割当先・状態・根拠</h3>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>会計</TableHead><TableHead>款</TableHead><TableHead>割当先</TableHead>
                <TableHead>状態</TableHead><TableHead>決まった単位</TableHead>
                <TableHead className="text-right">金額（円）</TableHead><TableHead>根拠</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {t.byKan.map((k, i) => (
                <TableRow key={i}>
                  <TableCell className="whitespace-nowrap">{k.fund}</TableCell>
                  <TableCell className="whitespace-nowrap">{k.kan}</TableCell>
                  <TableCell><CofogChain code={k} /></TableCell>
                  <TableCell><Badge variant={statusVariant(k.status)}>{STATUS_JA[k.status] ?? k.status}</Badge></TableCell>
                  <TableCell>{k.decidedAtLevel}</TableCell>
                  <TableCell className="text-right tabular-nums">{yen(k.sum)}</TableCell>
                  <TableCell className="min-w-[36ch] text-xs text-muted-foreground">{k.basis}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">連結の消去</h3>
        <p className="max-w-[72ch] text-sm text-muted-foreground">
          連結の範囲: {t.consolidationScope}。
          歳出の繰出金と歳入の繰入金は行と行が1対1に対応しない（細々節の切り方が両者で違う）。
          金額が厳密に一致するのは会計の対どうしの合計で、下表がその突合結果。
        </p>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>出し手</TableHead><TableHead>受け皿</TableHead>
                <TableHead className="text-right">消去（円）</TableHead><TableHead className="text-right">相手側（円）</TableHead>
                <TableHead>一致</TableHead><TableHead className="text-right">相手側の行数</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {t.consolidationPairs.map((p, i) => (
                <TableRow key={i}>
                  <TableCell>{p.from}</TableCell><TableCell>{p.to}</TableCell>
                  <TableCell className="text-right tabular-nums">{yen(p.eliminated)}</TableCell>
                  <TableCell className="text-right tabular-nums">{yen(p.counterpart)}</TableCell>
                  <TableCell><Badge variant={p.ok ? 'secondary' : 'destructive'}>{p.ok ? '一致' : '不一致'}</Badge></TableCell>
                  <TableCell className="text-right tabular-nums">{p.counterpartCount}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">分類不能と対象外の内訳</h3>
        <p className="max-w-[72ch] text-sm text-muted-foreground">
          分類できなかったものと、そもそも分類の対象でないものを混ぜない。
          公債費の元金償還は「分類できない」のではなく「対象外」である。
        </p>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>状態</TableHead><TableHead>会計</TableHead><TableHead>款</TableHead>
                <TableHead className="text-right">金額（円）</TableHead><TableHead>理由</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {t.notAssigned.map((x, i) => (
                <TableRow key={i}>
                  <TableCell><Badge variant="outline">{STATUS_JA[x.status] ?? x.status}</Badge></TableCell>
                  <TableCell className="whitespace-nowrap">{x.fund}</TableCell>
                  <TableCell className="whitespace-nowrap">{x.kan}</TableCell>
                  <TableCell className="text-right tabular-nums">{yen(x.sum)}</TableCell>
                  <TableCell className="min-w-[36ch] text-xs text-muted-foreground">{x.basis}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  )
}
