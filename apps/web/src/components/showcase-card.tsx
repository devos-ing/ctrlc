import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import type { MouseEvent, PointerEvent } from 'react'
import type { Showcase, ShowcaseNode } from '../generated/showcases'
import { findPreviewNode, measurePreview, type PreviewMetrics } from '../lib/preview-geometry'

const RETURN_FOCUS_KEY = 'ctrlc:showcase-return-focus'

type ShowcaseCardProps = { showcase: Showcase }

export function ShowcaseCard({ showcase }: ShowcaseCardProps) {
  const navigate = useNavigate()
  const frameRef = useRef<HTMLAnchorElement>(null)
  const imageRef = useRef<HTMLImageElement>(null)
  const pointerRef = useRef<{ clientX: number; clientY: number } | null>(null)
  const [metrics, setMetrics] = useState<PreviewMetrics | null>(null)
  const [hoveredNode, setHoveredNode] = useState<ShowcaseNode>()

  useEffect(() => {
    const frame = frameRef.current
    const image = imageRef.current
    if (!frame || !image) return
    const update = () => {
      const latest = measurePreview(image, frame)
      setMetrics(latest)
      if (pointerRef.current) {
        setHoveredNode(findPreviewNode(
          pointerRef.current.clientX,
          pointerRef.current.clientY,
          latest,
          showcase,
        ))
      }
    }
    update()
    image.addEventListener('load', update)
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, { capture: true, passive: true })
    const observer = new ResizeObserver(update)
    observer.observe(frame)
    observer.observe(image)
    return () => {
      image.removeEventListener('load', update)
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
      observer.disconnect()
    }
  }, [showcase])

  const nodeAt = (event: Pick<PointerEvent<HTMLAnchorElement>, 'clientX' | 'clientY'>) => {
    pointerRef.current = { clientX: event.clientX, clientY: event.clientY }
    const frame = frameRef.current
    const image = imageRef.current
    const latest = frame && image ? measurePreview(image, frame) : metrics
    setMetrics(latest)
    return findPreviewNode(event.clientX, event.clientY, latest, showcase)
  }

  const openInspector = async (nodeId?: string) => {
    window.sessionStorage.setItem(RETURN_FOCUS_KEY, showcase.slug)
    await navigate({
      to: '/showcases/$slug',
      params: { slug: showcase.slug },
      search: { node: nodeId },
    })
  }

  const handlePreviewClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    window.sessionStorage.setItem(RETURN_FOCUS_KEY, showcase.slug)
    const node = event.detail > 0 ? nodeAt(event) : undefined
    if (!node) return
    event.preventDefault()
    void openInspector(node.id)
  }

  const highlight = hoveredNode
  const box = highlight?.box
  const outlineStyle = metrics && box ? {
    left: metrics.left + (showcase.roi[0] + box[0]) * metrics.scale,
    top: metrics.top + (showcase.roi[1] + box[1]) * metrics.scale,
    width: box[2] * metrics.scale,
    height: box[3] * metrics.scale,
  } : undefined
  const labelStyle = metrics && box ? {
    left: metrics.left + (showcase.roi[0] + box[0]) * metrics.scale,
    top: Math.max(4, metrics.top + (showcase.roi[1] + box[1]) * metrics.scale - 34),
  } : undefined

  return (
    <article className="showcase-card">
      <div className="screenshot-stage">
        <Link
          ref={frameRef}
          to="/showcases/$slug"
          params={{ slug: showcase.slug }}
          search={{ node: undefined }}
          className="screenshot-link"
          id={`showcase-${showcase.slug}-preview`}
          aria-label={`Open ${showcase.title} inspector`}
          onClick={handlePreviewClick}
          onPointerMove={(event) => {
            if (event.pointerType === 'touch') return
            setHoveredNode(nodeAt(event))
          }}
          onPointerLeave={() => {
            pointerRef.current = null
            setHoveredNode(undefined)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setHoveredNode(undefined)
          }}
        >
          <img
            ref={imageRef}
            src={showcase.imageUrl}
            alt={`${showcase.title} screenshot`}
            width={showcase.imageSize[0]}
            height={showcase.imageSize[1]}
            loading="lazy"
            decoding="async"
            draggable={false}
          />
          {highlight && outlineStyle && (
            <span className="node-overlay" data-node-id={highlight.id} style={outlineStyle} aria-hidden="true" />
          )}
          {highlight && labelStyle && (
            <span className="node-label" style={labelStyle} aria-hidden="true">{highlight.name}</span>
          )}
        </Link>
      </div>
      <div className="showcase-caption">
        <div className="caption-main">
          <h3>{showcase.title}</h3>
          <span className="node-count">{showcase.nodes.filter((node) => node.depth === 0).length} components</span>
        </div>
        <p className="showcase-context">
          {showcase.context} · {showcase.reviewed ? 'Semantically reviewed' : 'Local extraction'}
        </p>
      </div>
    </article>
  )
}
