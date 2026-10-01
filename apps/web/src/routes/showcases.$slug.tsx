import { useEffect, useRef, useState } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { NodeList } from '../components/node-list'
import { showcases } from '../generated/showcases'

const RETURN_FOCUS_KEY = 'ctrlc:showcase-return-focus'

export const Route = createFileRoute('/showcases/$slug')({
  validateSearch: (search: Record<string, unknown>) => ({
    node: typeof search.node === 'string' ? search.node : undefined,
  }),
  loader: ({ params }) => ({ showcase: showcases.find((entry) => entry.slug === params.slug) }),
  head: ({ loaderData }) => ({
    meta: [
      { title: loaderData?.showcase ? `${loaderData.showcase.title} inspector — ctrlc` : 'Showcase not found — ctrlc' },
      {
        name: 'description',
        content: loaderData?.showcase
          ? `Inspect saved UI elements from ${loaderData.showcase.title}.`
          : 'The requested saved scene could not be found.',
      },
    ],
  }),
  component: ShowcaseDetailPage,
})

function ShowcaseDetailPage() {
  const { slug } = Route.useParams()
  const { node } = Route.useSearch()
  const { showcase } = Route.useLoaderData()
  const frameRef = useRef<HTMLIFrameElement>(null)
  const navigate = useNavigate()
  const [clientReady, setClientReady] = useState(false)
  const [iframeLoaded, setIframeLoaded] = useState(false)
  useEffect(() => setClientReady(true), [])
  const browserNode = clientReady ? new URLSearchParams(window.location.search).get('node') ?? undefined : undefined
  const selectedNodeId = clientReady ? node ?? browserNode : undefined
  const selectedNode = showcase?.nodes.find((entry) => entry.id === selectedNodeId)
  const invalidSelection = Boolean(selectedNodeId && !selectedNode)
  const inspectorUrl = showcase ? `${showcase.inspectorUrl}#node=` : ''

  useEffect(() => {
    const frame = frameRef.current
    if (!clientReady || !frame || !showcase) return
    try {
      const frameWindow = frame.contentWindow
      const expectedPath = new URL(showcase.inspectorUrl, window.location.href).pathname
      if (frameWindow?.location.origin === window.location.origin
          && frameWindow.location.pathname === expectedPath
          && frame.contentDocument?.readyState === 'complete') {
        setIframeLoaded(true)
      }
    } catch {
      // The generated inspector stays same-origin; an unavailable frame remains unselected.
    }
  }, [clientReady, showcase?.slug])

  useEffect(() => {
    const frameWindow = frameRef.current?.contentWindow
    if (!iframeLoaded || !frameWindow || !showcase) return
    const selectionHash = `#node=${selectedNode ? encodeURIComponent(selectedNode.id) : ''}`
    try {
      const expectedPath = new URL(showcase.inspectorUrl, window.location.href).pathname
      if (frameWindow.location.origin !== window.location.origin || frameWindow.location.pathname !== expectedPath) return
      if (frameWindow.location.hash !== selectionHash) frameWindow.history.replaceState(null, '', selectionHash)
      frameWindow.postMessage({
        type: 'ctrlc-inspector-sync-selection',
        node: selectedNode?.id ?? null,
      }, window.location.origin)
    } catch {
      // The generated inspector stays same-origin; an unavailable frame simply remains unselected.
    }
  }, [iframeLoaded, selectedNode?.id, showcase?.slug])

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== frameRef.current?.contentWindow) return
      if (event.data?.type === 'ctrlc-inspector-close') {
        void navigate({ to: '/' })
        return
      }
      if (event.data?.type === 'ctrlc-inspector-select'
          && typeof event.data.node === 'string'
          && showcase?.nodes.some((entry) => entry.id === event.data.node)) {
        void navigate({
          to: '/showcases/$slug',
          params: { slug },
          search: { node: event.data.node },
        })
      }
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') void navigate({ to: '/' })
    }
    window.addEventListener('message', handleMessage)
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('message', handleMessage)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [navigate, showcase, slug])

  if (!showcase) {
    return (
      <main className="not-found">
        <h1>Showcase not found</h1>
        <p>That saved scene is not in the curated catalog.</p>
        <Link to="/" className="text-link">Back to showcases</Link>
      </main>
    )
  }

  const selectNode = (nodeId: string) => {
    void navigate({
      to: '/showcases/$slug',
      params: { slug },
      search: { node: nodeId },
    })
  }

  return (
    <main className="detail-shell">
      <nav className="detail-nav" aria-label="Showcase navigation">
        <Link
          to="/"
          className="back-link"
          onClick={() => window.sessionStorage.setItem(RETURN_FOCUS_KEY, slug)}
        >
          <span aria-hidden="true">←</span> Back to showcases
        </Link>
        <Link to="/" className="wordmark" aria-label="ctrlc home">ctrlc</Link>
      </nav>
      <div className="detail-intro">
        <div>
          <h1 className="detail-title">{showcase.title}</h1>
          <p>{showcase.context} · {showcase.nodes.filter((entry) => entry.depth === 0).length} components</p>
        </div>
        <div className="detail-copy">
          <span>{showcase.reviewed ? 'Semantically reviewed scene' : 'Local extraction'}</span>
          <Link to="/">Browse other showcases</Link>
        </div>
      </div>
      {invalidSelection && (
        <p className="invalid-selection" role="status">That element ID is not in this saved scene. No element was selected.</p>
      )}
      <details className="detail-elements">
        <summary>Choose a saved element with the keyboard</summary>
        <NodeList nodes={showcase.nodes} onSelect={selectNode} />
      </details>
      <iframe
        ref={frameRef}
        key={showcase.slug}
        className="inspector-frame"
        src={inspectorUrl}
        title={`${showcase.title} saved scene inspector`}
        onLoad={() => setIframeLoaded(true)}
        allow="clipboard-read; clipboard-write"
      />
    </main>
  )
}
