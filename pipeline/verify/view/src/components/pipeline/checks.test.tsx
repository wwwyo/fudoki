import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { CheckList } from './io-panel'
import type { Check } from '@fudoki/report/common'

test('警告を成功と混ぜず、他団体と対象特定不能を区別する', () => {
  const warning = (name:string, attribution:Check['attribution']):Check => ({name,status:'warn',ok:false,severity:'warn',failures:1,detail:'原典との不一致',binds:[],description:name,explanation:'要確認',attribution})
  const html=renderToStaticMarkup(<CheckList code="132195" checks={[
    warning('当該団体',{kind:'jurisdiction',counts:{'132195':2}}),
    warning('別団体',{kind:'jurisdiction',counts:{'132047':3}}),
    warning('横断',{kind:'cross'}),
  ]} />)
  expect(html.match(/>警告</g)?.length).toBe(3)
  expect(html).not.toContain('>成功<')
  expect(html).toContain('この団体 2 件')
  expect(html).toContain('132047 3 件（この団体の行ではない）')
  expect(html).toContain('横断・対象特定不能')
})
