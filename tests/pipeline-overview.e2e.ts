import { test } from '@e2e-dev/web'
import { expect } from 'e2e'

test('the local pipeline overview explains the data flow', async ({
  app,
  screen,
  browser,
}) => {
  await app.open('/')

  await expect(screen.getByRole('heading', { level: 1 })).toContainText(
    '比べられるデータにする。'
  )
  await expect(
    screen.getByRole('navigation', { name: 'このページの目次' })
  ).toBeVisible()
  await expect(browser).toHaveURL('/pipeline/')
})
