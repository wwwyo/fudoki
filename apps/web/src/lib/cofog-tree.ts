/**
 * 分析画面の COFOG ツリーの型。
 *
 * ⚠️ **ここでは組み立てない。** 木は API の `getCofogBreakdown` が
 * `report/budget/cofog.ts` の `buildCofogTree()` で組んで返す（AGENTS.md の「集計は1箇所」）。
 * 以前はここで `byCode` を division → group → class へ `+=` で積み上げ直していたが、
 * それ自体が画面側の二重集計だったので生成側へ移した。
 * 画面はこの型を使って API の応答（`cofog.tree`）をそのままネストして描くだけでよい。
 */
import type { RouterClient } from "@orpc/server"
import type { Router } from "@fudoki/api/router"

/** `getCofogBreakdown` の応答。画面はここから導出した型だけを使い、別経路で導出し直さない */
export type CofogBreakdown = Awaited<ReturnType<RouterClient<Router>["getCofogBreakdown"]>>["cofog"]

/** `cofog.tree` の要素の型。API の応答から導出し、二重宣言しない */
export type CofogTreeNode = CofogBreakdown["tree"][number]

/** ツリーのノードに紐づく statement filter。選択可能なノードだけが持つ */
export type CofogNodeFilter = NonNullable<CofogTreeNode["filter"]>
