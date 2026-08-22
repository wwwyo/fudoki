/**
 * 報告のうち、**実行結果から導けない内容**。判断・調査・宣言なので手で書く。
 *
 * JSON ではなく TS にしてあるのは、`ReportData` の該当部分として
 * 型検査を通すため。JSON だと形を変えても画面が壊れるまで気づかない。
 */
import type { ReportData } from './schema'

type Static = Pick<ReportData, 'notYetReconciled' | 'customColumnTypes' | 'portability' | 'caveats'>

export const STATIC: Static = {
  "notYetReconciled": {
    "scope": "特別会計（国民健康保険事業・介護サービス事業・介護保険事業・後期高齢者医療）の款別・項別",
    "reason": "施政方針・予算概要は一般会計の款別までしか載せておらず、特別会計の款別は予算書にしかない",
    "wouldComeFrom": "https://www.city.mitaka.lg.jp/c_service/090/090334.html（過去の予算書）",
    "currentEvidence": "歳出と歳入の会計別合計が一致することのみ（原典の内部整合であり、外部資料による裏づけではない）"
  },
  "customColumnTypes": [
    {
      "name": "fund:code",
      "dataType": "string",
      "unique": true,
      "why": "会計（一般会計・各特別会計）。administrative-classification は資金管理の責任を負う組織単位を指すもので、会計は資金の区分であり別概念。標準に該当する列型が無い"
    },
    {
      "name": "fund:label",
      "dataType": "string",
      "labelOf": "fund:code",
      "why": "会計の表示名"
    },
    {
      "name": "fin-source:generic:level4:code",
      "dataType": "string",
      "unique": true,
      "prior": "fin-source:generic:level3:code",
      "why": "歳入の節。標準の fin-source は level3 までしか定義が無いため同じ命名規則で拡張した"
    },
    {
      "name": "fin-source:generic:level4:label",
      "dataType": "string",
      "labelOf": "fin-source:generic:level4:code",
      "why": "歳入の節の表示名"
    },
    {
      "name": "fin-source:generic:level5:code",
      "dataType": "string",
      "unique": true,
      "prior": "fin-source:generic:level4:code",
      "why": "歳入の細節"
    },
    {
      "name": "fin-source:generic:level5:label",
      "dataType": "string",
      "labelOf": "fin-source:generic:level5:code",
      "why": "歳入の細節の表示名"
    },
    {
      "name": "fin-source:generic:level6:code",
      "dataType": "string",
      "unique": true,
      "prior": "fin-source:generic:level5:code",
      "why": "歳入の細々節"
    },
    {
      "name": "fin-source:generic:level6:label",
      "dataType": "string",
      "labelOf": "fin-source:generic:level6:code",
      "why": "歳入の細々節の表示名"
    },
    {
      "name": "fudoki:jurisdiction:code",
      "dataType": "string",
      "unique": true,
      "why": "全国地方公共団体コード。外部データとの接続キー。FDP の geo:* は住所や地理コードを指すもので、行政主体の識別子ではない"
    },
    {
      "name": "fudoki:jurisdiction:label",
      "dataType": "string",
      "labelOf": "fudoki:jurisdiction:code",
      "why": "自治体名"
    },
    {
      "name": "fudoki:source:cell",
      "dataType": "string",
      "why": "code と label へ分ける前の原典のセル。先頭のゼロや全角数字といった表記を保ち、code + label を連結して原文に戻ることを検証に使う"
    },
    {
      "name": "fudoki:source:amount",
      "dataType": "number",
      "why": "原典の金額。円へ正規化する前の値"
    },
    {
      "name": "fudoki:source:amount-unit",
      "dataType": "string",
      "why": "原典の金額の単位。FDP に倍率を表す ColumnType が無いため別列に残す"
    },
    {
      "name": "fudoki:source:row",
      "dataType": "integer",
      "why": "原典の物理行番号。特定のスナップショット内でのみ意味を持つ証跡で、外部が参照する識別子ではない"
    },
    {
      "name": "fudoki:hierarchy-path",
      "dataType": "string",
      "why": "階層のコードを連結した可読なパス。コードは兄弟間で一意とは限らないので識別子には使わない"
    },
    {
      "name": "fudoki:cofog:status",
      "dataType": "string",
      "why": "分類の軸。assigned / unclassifiable / out-of-scope。分類できなかったものと、そもそも分類の対象でないものを区別する"
    },
    {
      "name": "fudoki:cofog:consolidation",
      "dataType": "string",
      "why": "連結の軸。retained / eliminated。分類の軸とは別の問いなので1つの状態に畳まない"
    },
    {
      "name": "fudoki:cofog:counterpart-id",
      "dataType": "string",
      "why": "消去する行の相手側 budget-line-id"
    },
    {
      "name": "fudoki:cofog:basis",
      "dataType": "string",
      "why": "割り当ての根拠。割当済みと未分類のいずれについても残す"
    },
    {
      "name": "fudoki:cofog:decided-at-level",
      "dataType": "string",
      "why": "款・項・目・事項のどの単位で割り当てが決まったか"
    }
  ],
  "portability": [
    {
      "element": "CKAN からのリソース解決と証跡の記録（Extract）",
      "kind": "再利用の候補",
      "verifyNext": "東京都カタログ以外（BODIK・独自 DCAT）でも同じ形で引けるか"
    },
    {
      "element": "完全修飾パスから識別子を導く方式",
      "kind": "再利用の候補",
      "verifyNext": "階層の深さが違う団体でも一意になるか。狛江市は事業階層が3段ある"
    },
    {
      "element": "原典の値と単位を別列に残したうえで円へ正規化する方式",
      "kind": "再利用の候補",
      "verifyNext": "単位が円の団体（狛江市は「予算額(円)」）で倍率1が素通りするか"
    },
    {
      "element": "検査の並べ方（多重集合一致・従属関係・複合主キー・公表値突合）",
      "kind": "再利用の候補",
      "verifyNext": "公表資料が款別を載せない団体でも代替の外部突合が立つか"
    },
    {
      "element": "COFOG の2軸（分類 / 連結）と規則エンジンの形",
      "kind": "再利用の候補",
      "verifyNext": "規則の本数が団体ごとに増えるか、款の語彙が共通で使い回せるか"
    },
    {
      "element": "「事項」を事業階層として宣言すること",
      "kind": "三鷹市に固有",
      "verifyNext": "狛江市は「大事業 / 中事業 / 小事業」。宣言の粒度が団体ごとに違う前提で足りるか"
    },
    {
      "element": "歳入の細々節を `0` で埋めるプレースホルダ",
      "kind": "三鷹市に固有",
      "verifyNext": "他団体が空文字・全角ゼロ・ハイフンなど別の表現を使うか"
    },
    {
      "element": "2桁コード + 名称という1セルの書式",
      "kind": "三鷹市に固有",
      "verifyNext": "桁数が違う団体、コードと名称が別列の団体でセル分解の宣言が要るか"
    },
    {
      "element": "歳出と歳入の合計一致という検算",
      "kind": "三鷹市に固有",
      "verifyNext": "当初予算以外や企業会計を持つ団体では成立しない。取得元ごとの設定で切れているか"
    },
    {
      "element": "款 → COFOG ディビジョンの対応そのもの",
      "kind": "一般性を判定できない",
      "verifyNext": "款の名称は法定なので共通のはずだが、項・目の名称は団体差がある。項以下の規則が何本必要になるか"
    },
    {
      "element": "事項が1つの事業に対応するという前提",
      "kind": "一般性を判定できない",
      "verifyNext": "複数の活動をまとめた事項や管理的な費目が混ざっていないか。2団体目で概念として確定させる"
    },
    {
      "element": "`fin-source:generic:level4〜6` という標準の拡張",
      "kind": "一般性を判定できない",
      "verifyNext": "他団体の歳入も6階層か。3階層で足りるなら拡張自体をやめられる"
    }
  ],
  "caveats": [
    {
      "topic": "TypeScript 版との同一性を示す検査は、TypeScript 版とともに削除した",
      "body": "移行の正しさは、識別子（歳出 5,613 行・歳入 821 行すべて一致）と COFOG の割当（status / division / consolidation / 決まった単位 / 規則 ID がすべて一致）を 1行ずつ突き合わせて示した。証明そのものは git 履歴に残る（識別子は 944866c、COFOG は 83bd132）。**これ以降、識別子が変わっていないことを保証するのは検査ではなく成果物そのもの**である — 正本をリポジトリに commit しているので、導出を変えれば data/packages/132047/expenditure.csv の diff として必ず現れる。"
    },
    {
      "topic": "配布形式は CSV のまま。全量では作り直しになりうる",
      "body": "62団体 × 9年度への外挿は CSV 1.1 GB / gzip 156 MB / Parquet 141 MB。gzip は Data Package の仕様に compression プロパティが無く、Parquet は format が「csv, xls, json etc.」と開いているだけで明記が無い。**1団体しか無い段階で外挿値だけを根拠に標準から外れる判断はしない。** 実際に増えたときに決める。"
    },
    {
      "topic": "事項を事業として扱う妥当性が未検証（Design Doc Caveats 1）",
      "body": "名称を持つことは、その区分が1つの事業に対応することの証明にならない。複数の活動をまとめた事項や管理的な費目が含まれうる。自治体横断の「事業」概念として確定するのは2団体目以降とする。現状は `activity:generic:program` に置いてあるが、これは候補としての割り当てである。"
    },
    {
      "topic": "COFOG の割り当てが款の単位で成立するかは部分的（Design Doc Caveats 2）",
      "body": "実データを通した結果、**款だけでは決まらない款が実在した**。衛生費（保健衛生費 → 07 / 清掃費 → 05）と土木費と教育費は項へ、公債費（元金 → 対象外 / 利子 → 01）と都市計画費と生涯学習費は目へ下げて決着した。どこまで下げれば決まるかは「款で決まらず、下の単位まで下げたもの」を見ること。"
    },
    {
      "topic": "PRD の「938件の事項」は事項の件数ではない",
      "body": "実測すると、938 は**事項のセル文字列（コード + 名称）の異なり数**であって、階層としての事項の件数ではない。完全修飾で数えると全会計 996 件・一般会計 913 件、名称の異なり数は全会計 918 件・一般会計 856 件になる。ただし「すべて名称を持つ」という主張自体は正しい（名称が空の事項は0件）。三鷹市を選んだ判断は変わらないが、数字は置き換える必要がある。"
    },
    {
      "topic": "Design Doc は歳入を6階層としていたが、原典は7階層",
      "body": "原典の歳入は会計/款/項/目/節/細節に加えて**細々節を持つ**。821 行中 18 行が実際に使っており、細々節を落とすと識別子が7組衝突する。Design Doc の記述ではなく実物の列で判定した（パーサ設計の原則3）。"
    },
    {
      "topic": "識別子はコードのパスでは作れなかった",
      "body": "Design Doc は「`款01/項03/目01` の形で連結する」としていたが、三鷹市の細々節は**同じ節の下でコードを再利用する**（実測 710 箇所・1,615 行）。コードのパスでは 5,613 行が 4,708 通りにしかならない。そこでパスの構成要素を**セル全文（コード + 名称）**に取った。副作用として、自治体が名称を直すと識別子が変わる。コードだけなら耐えられたはずの変更なので、これは失ったものである。"
    },
    {
      "topic": "仕様が正準と宣言する taxonomy の URL が 404",
      "body": "`https://specs.frictionlessdata.io/taxonomies/fiscal/budgets.json` は 404 を返す（2026-08-16 実測）。ColumnType の一覧を機械可読な形で参照する経路が存在しないため、仕様の原文（Markdown）から起こして `src/budget/taxonomy/` に取り込み、fudoki 側で保守する。descriptor の `columnTypes` は仕様どおりこの URL を指しているが、**利用者がこれを辿っても取得できない**。"
    },
    {
      "topic": "`fin-source:generic:level4〜6` は標準の名前空間を fudoki が拡張したもの",
      "body": "歳入の階層は6段あるが、標準の `fin-source:generic` は level3 までしか定義が無い。`prior` を繋いで順序が保たれるよう同じ命名規則で拡張した。標準側が後から level4 を別の意味で定義すると衝突する。FDP は 2024-03 で更新が止まっているため当面は起きないと見ているが、独自の名前空間に逃がす選択肢もあった。"
    },
    {
      "topic": "繰出金と繰入金は行どうしが1対1に対応しない",
      "body": "歳出の繰出金と歳入の繰入金は細々節の切り方が違うため、行の対応は N 対 M になる。金額が厳密に一致するのは**会計の対どうしの合計**で、そこは5対すべてで一致した。各行の `cofog_counterpart_ids` には受け皿側の該当行の識別子を並べてあるが、これは「その行1件の相手」ではなく**相手のグループ**である。"
    },
    {
      "topic": "特別会計は外部資料で裏づけていない",
      "body": "施政方針・予算概要は一般会計の款別までしか載せていない。特別会計の款別を突合するには予算書（別資料）が要る。現状の根拠は歳出と歳入の会計別合計が一致することだけで、これは原典の内部整合であって外部からの裏づけではない。"
    },
    {
      "topic": "河川費と生涯学習費の割り当ては判断の幅がある",
      "body": "COFOG は治水を明示的に置いていないため、河川費（15,852千円）は 05 環境保護に寄せたが 04 経済業務にも読める。生涯学習費のうち図書館費は COFOG 08.2 が図書館を明示的に含むため 08 に置き、それ以外（生涯学習総務・青少年育成・生涯学習センター）は社会教育として 09 に置いた。いずれも根拠を `cofog_basis` に書いてあるので、判断を変えたければそこを見て変えられる。"
    }
  ],
}
