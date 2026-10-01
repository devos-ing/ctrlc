import { expect, test } from '@playwright/test'

type SceneNode = {
  id: string
  type: string
  box: [number, number, number, number]
  children?: SceneNode[]
}

type PublicScene = {
  imageSize: [number, number]
  roi: [number, number, number, number]
  nodes: SceneNode[]
  measurementArtifact?: unknown
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
  const scene = await response.json() as PublicScene
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

async function expectRootOnlyScene(page: import('@playwright/test').Page, slug: string) {
  const response = await page.request.get(`/showcases/${slug}/scene.json`)
  expect(response.ok()).toBeTruthy()
  const scene = await response.json() as PublicScene
  expect(scene.nodes.length).toBeGreaterThan(0)
  expect(scene.nodes.every((node) => node.children === undefined)).toBeTruthy()
  expect(scene.measurementArtifact).toBeUndefined()
  return scene
}

async function expectRootOnlyInspector(inspector: import('@playwright/test').FrameLocator) {
  await expect(inspector.locator('.el-view-controls')).toBeHidden()
  await expect(inspector.locator('.el-depth')).toBeHidden()
  await expect(inspector.locator('.el-evidence-toggle')).toBeHidden()
  await expect(inspector.locator('[data-measurements]')).toHaveJSProperty('textContent', 'null')
  await expect(inspector.locator('.el-children button')).toHaveCount(0)
}

test('desktop copies the published command and inspects only the saved root at two image sizes', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/')
  const installCommand = 'curl -fsSL https://raw.githubusercontent.com/devos-ing/ctrlc/main/install.sh | sh'
  const copyButton = page.getByRole('button', { name: 'Copy' })
  await copyButton.click()
  await expect(page.getByRole('button', { name: 'Copied' })).toBeVisible()
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(installCommand)

  const preview = page.getByRole('link', { name: 'Open Brokerage inspector' })
  const scene = await expectRootOnlyScene(page, 'brokerage')
  expect(scene.nodes.some((node) => node.id === 'b1')).toBeTruthy()
  await page.setViewportSize({ width: 1440, height: 650 })
  await preview.scrollIntoViewIfNeeded()
  for (const width of [1440, 320]) {
    await page.setViewportSize({ width, height: 650 })
    await preview.scrollIntoViewIfNeeded()
    const point = await savedNodePoint(page, 'brokerage', 'b1')
    await page.mouse.move(point.x, point.y)
    await expect(preview.locator('.node-label')).toHaveText('Brokerage menu')
    const outline = await preview.locator('[data-node-id="b1"]').boundingBox()
    expect(outline).not.toBeNull()
    expect(Math.abs(outline!.x - (point.imageLeft + (point.roi[0] + point.box[0]) * point.scale))).toBeLessThan(2)
    expect(Math.abs(outline!.y - (point.imageTop + (point.roi[1] + point.box[1]) * point.scale))).toBeLessThan(2)
    if (width === 1440) expect(point.width).toBeGreaterThan(245)
    else expect(point.width).toBeLessThan(225)
    await page.mouse.click(point.x, point.y)
    await expect(page).toHaveURL(/\/showcases\/brokerage\?node=b1$/)
    const inspector = page.frameLocator('iframe[title="Brokerage saved scene inspector"]')
    await expect(inspector.locator('.el-selected-title')).toHaveText('Brokerage menu')
    await expectRootOnlyInspector(inspector)
    if (width === 1440) {
      await inspector.locator('body').press('Escape')
      await expect(page).toHaveURL(/\/$/)
      await expect(preview).toBeFocused()
    }
  }
})

test('mobile tap and keyboard select only the saved root and reject nested links', async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 393, height: 844 },
    isMobile: true,
    hasTouch: true,
  })
  const page = await context.newPage()
  await page.goto('/')
  const preview = page.getByRole('link', { name: 'Open Brokerage inspector' })
  const scene = await expectRootOnlyScene(page, 'brokerage')
  expect(scene.nodes.some((node) => node.id === 'b1')).toBeTruthy()
  await preview.scrollIntoViewIfNeeded()
  const point = await savedNodePoint(page, 'brokerage', 'b1')
  await expect(preview.locator('.node-label')).toHaveCount(0)
  await page.touchscreen.tap(point.x, point.y)
  await expect(page).toHaveURL(/\/showcases\/brokerage\?node=b1$/)
  let inspector = page.frameLocator('iframe[title="Brokerage saved scene inspector"]')
  await expect(inspector.locator('.el-selected-title')).toHaveText('Brokerage menu')
  await expectRootOnlyInspector(inspector)

  await page.getByRole('link', { name: 'Back to showcases' }).click()
  await expect(preview).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/showcases\/brokerage$/)
  const browserSummary = page.getByText('Choose a saved element with the keyboard')
  await browserSummary.focus()
  await page.keyboard.press('Enter')
  const keyboardNode = page.getByRole('button', { name: 'Brokerage menu button' })
  await keyboardNode.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/showcases\/brokerage\?node=b1$/)

  await page.reload()
  inspector = page.frameLocator('iframe[title="Brokerage saved scene inspector"]')
  await expect(inspector.locator('.el-selected-title')).toHaveText('Brokerage menu')
  await expectRootOnlyInspector(inspector)
  await page.goBack()
  await expect(page).toHaveURL(/\/showcases\/brokerage$/)
  await expect(inspector.locator('.el-empty')).toBeVisible()
  await page.goForward()
  await expect(page).toHaveURL(/\/showcases\/brokerage\?node=b1$/)
  await expect(inspector.locator('.el-selected-title')).toHaveText('Brokerage menu')
  await page.keyboard.press('Escape')
  await expect(page).toHaveURL(/\/$/)
  await expect(preview).toBeFocused()

  await page.goto('/showcases/brokerage?node=b1.2')
  await expect(page.getByRole('status')).toHaveText('That element ID is not in this saved scene. No element was selected.')
  inspector = page.frameLocator('iframe[title="Brokerage saved scene inspector"]')
  await expect(inspector.locator('.el-empty')).toBeVisible()
  await expect(inspector.locator('.el-inspector-body')).toBeHidden()
  await expectRootOnlyInspector(inspector)

  await page.goto('/showcases/brokerage?node=not-a-real-id')
  await expect(page.getByRole('status')).toHaveText('That element ID is not in this saved scene. No element was selected.')
  await expect(page.frameLocator('iframe[title="Brokerage saved scene inspector"]')
    .locator('.el-empty')).toBeVisible()
  await page.goto('/showcases/not-in-catalog')
  await expect(page.getByRole('heading', { name: 'Showcase not found' })).toBeVisible()
  await context.close()
})
