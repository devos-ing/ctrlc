import type { Showcase, ShowcaseNode } from '../generated/showcases'

export type PreviewMetrics = {
  left: number
  top: number
  scale: number
  width: number
  height: number
  frameLeft: number
  frameTop: number
}

export function measurePreview(image: HTMLImageElement, frame: HTMLElement): PreviewMetrics | null {
  if (!image.naturalWidth || !image.naturalHeight) return null
  const imageRect = image.getBoundingClientRect()
  const frameRect = frame.getBoundingClientRect()
  const contentOriginLeft = frameRect.left + frame.clientLeft
  const contentOriginTop = frameRect.top + frame.clientTop
  const scale = Math.min(imageRect.width / image.naturalWidth, imageRect.height / image.naturalHeight)
  const width = image.naturalWidth * scale
  const height = image.naturalHeight * scale
  return {
    left: imageRect.left + (imageRect.width - width) / 2 - contentOriginLeft,
    top: imageRect.top + (imageRect.height - height) / 2 - contentOriginTop,
    scale,
    width,
    height,
    frameLeft: contentOriginLeft,
    frameTop: contentOriginTop,
  }
}

export function findPreviewNode(
  clientX: number,
  clientY: number,
  metrics: PreviewMetrics | null,
  showcase: Showcase,
): ShowcaseNode | undefined {
  if (!metrics || metrics.scale <= 0) return undefined
  const imageX = (clientX - metrics.frameLeft - metrics.left) / metrics.scale
  const imageY = (clientY - metrics.frameTop - metrics.top) / metrics.scale
  if (imageX < 0 || imageY < 0 || imageX >= showcase.imageSize[0] || imageY >= showcase.imageSize[1]) {
    return undefined
  }
  const roiX = imageX - showcase.roi[0]
  const roiY = imageY - showcase.roi[1]
  return showcase.nodes
    .filter(({ box }) => roiX >= box[0] && roiY >= box[1] && roiX <= box[0] + box[2] && roiY <= box[1] + box[3])
    .sort((a, b) => b.depth - a.depth || a.box[2] * a.box[3] - b.box[2] * b.box[3])[0]
}
