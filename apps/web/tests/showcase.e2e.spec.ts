import { expect, test } from '@playwright/test'

type SceneNode = {
  id: string
  type: string
  box: [number, number, number, number]
  children?: SceneNode[]
}

function findNode(nodes: SceneNode[], id: string): SceneNode | undefined {
  for (const node of nodes) {
    if (node.id === id) return node
    const child = findNode(node.children ?? [], id)
    if (child) return child
  }
  return undefined
}

async function savedNodePoint(page: import('@playwright/test').Page, slug: string, id: string) {
  const response = await page.request.get(`/showcases/${slug}/scene.json`)
  expect(response.ok()).toBeTruthy()
  const scene = await response.json() as {
    imageSize: [number, number]
    roi: [number, number, number, number]
    nodes: SceneNode[]
  }
  const node = findNode(scene.nodes, id)
  expect(node).toBeDefined()
  const image = page.locator(`#showcase-${slug}-preview img`)
  await expect(image).toHaveJSProperty('complete', true)
  return await image.evaluate((element, bounds) => {
    const img = element as HTMLImageElement
    const rect = img.getBoundingClientRect()
    const scale = Math.min(rect.width / bounds.imageSize[0], rect.height / bounds.imageSize[1])
    return {
      x: rect.left + (bounds.roi[0] + bounds.box[0] + bounds.box[2] / 2) * scale,
      y: rect.top + (bounds.roi[1] + bounds.box[1] + bounds.box[3] / 2) * scale,
      width: rect.width,
      box: bounds.box,
      roi: bounds.roi,
      imageSize: bounds.imageSize,
      scale,
      imageLeft: rect.left,
      imageTop: rect.top,
    }
  }, { imageSize: scene.imageSize, roi: scene.roi, box: node!.box })
}

test('desktop copies the published command and inspects the saved nested element at two image sizes', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/')
  const installCommand = 'curl -fsSL https://raw.githubusercontent.com/devos-ing/ctrlc/main/install.sh | sh'
  const copyButton = page.getByRole('button', { name: 'Copy' })
  await copyButton.click()
  await expect(page.getByRole('button', { name: 'Copied' })).toBeVisible()
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(installCommand)

  const preview = page.getByRole('link', { name: 'Open Brokerage inspector' })
  await page.setViewportSize({ width: 1440, height: 650 })
  await preview.scrollIntoViewIfNeeded()
  for (const width of [1440, 320]) {
    await page.setViewportSize({ width, height: 650 })
    await preview.scrollIntoViewIfNeeded()
    const point = await savedNodePoint(page, 'brokerage', 'b1.2')
    await page.mouse.move(point.x, point.y)
    await expect(preview.locator('.node-label')).toHaveText('Brokerage label')
    const outline = await preview.locator('[data-node-id="b1.2"]').boundingBox()
    expect(outline).not.toBeNull()
    expect(Math.abs(outline!.x - (point.imageLeft + (point.roi[0] + point.box[0]) * point.scale))).toBeLessThan(2)
    expect(Math.abs(outline!.y - (point.imageTop + (point.roi[1] + point.box[1]) * point.scale))).toBeLessThan(2)
    if (width === 1440) expect(point.width).toBeGreaterThan(245)
    else expect(point.width).toBeLessThan(225)
    await page.mouse.click(point.x, point.y)
    await expect(page).toHaveURL(/\/showcases\/brokerage\?node=b1\.2$/)
    const inspector = page.frameLocator('iframe[title="Brokerage saved scene inspector"]')
    await expect(inspector.locator('.el-selected-title')).toHaveText('Brokerage label')
    if (width === 1440) {
      await inspector.locator('body').press('Escape')
      await expect(page).toHaveURL(/\/$/)
      await expect(preview).toBeFocused()
    }
  }
})

test('mobile tap and keyboard node selection survive direct reload and Escape returns focus', async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 393, height: 844 },
    isMobile: true,
    hasTouch: true,
  })
  const page = await context.newPage()
  await page.goto('/')
  const preview = page.getByRole('link', { name: 'Open Brokerage inspector' })
  await preview.scrollIntoViewIfNeeded()
  const point = await savedNodePoint(page, 'brokerage', 'b1.2')
  await expect(preview.locator('.node-label')).toHaveCount(0)
  await page.touchscreen.tap(point.x, point.y)
  await expect(page).toHaveURL(/\/showcases\/brokerage\?node=b1\.2$/)
  let inspector = page.frameLocator('iframe[title="Brokerage saved scene inspector"]')
  await expect(inspector.locator('.el-selected-title')).toHaveText('Brokerage label')

  await page.getByRole('link', { name: 'Back to showcases' }).click()
  await expect(preview).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/showcases\/brokerage$/)
  const browserSummary = page.getByText('Choose a saved element with the keyboard')
  await browserSummary.focus()
  await page.keyboard.press('Enter')
  const keyboardNode = page.getByRole('button', { name: 'Brokerage label text' })
  await keyboardNode.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/showcases\/brokerage\?node=b1\.2$/)

  await page.goto('/showcases/brokerage?node=b1.2')
  await page.reload()
  inspector = page.frameLocator('iframe[title="Brokerage saved scene inspector"]')
  await expect(inspector.locator('.el-selected-title')).toHaveText('Brokerage label')
  const menuIcon = inspector.getByRole('button', { name: 'Menu icon' })
  await menuIcon.focus()
  await menuIcon.press('Enter')
  await expect(page).toHaveURL(/\/showcases\/brokerage\?node=b1\.1$/)
  await expect(inspector.locator('.el-selected-title')).toHaveText('Menu icon')
  await expect(menuIcon).toBeFocused()
  await page.goBack()
  await expect(page).toHaveURL(/\/showcases\/brokerage\?node=b1\.2$/)
  await expect(inspector.locator('.el-selected-title')).toHaveText('Brokerage label')
  await expect(menuIcon).toBeFocused()
  await menuIcon.press('Escape')
  await expect(page).toHaveURL(/\/$/)
  await expect(preview).toBeFocused()

  await page.goto('/showcases/brokerage?node=not-a-real-id')
  await expect(page.getByRole('status')).toHaveText('That element ID is not in this saved scene. No element was selected.')
  await expect(page.frameLocator('iframe[title="Brokerage saved scene inspector"]')
    .locator('.el-empty')).toBeVisible()
  await page.goto('/showcases/not-in-catalog')
  await expect(page.getByRole('heading', { name: 'Showcase not found' })).toBeVisible()
  await context.close()
})
