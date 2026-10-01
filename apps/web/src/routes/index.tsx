import { useEffect, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import copyIcon from '../assets/copy.svg?url'
import { ShowcaseCard } from '../components/showcase-card'
import { SiteHeader } from '../components/site-header'
import { showcases } from '../generated/showcases'

const INSTALL_COMMAND = 'curl -fsSL https://raw.githubusercontent.com/devos-ing/ctrlc/main/install.sh | sh'
const RETURN_FOCUS_KEY = 'ctrlc:showcase-return-focus'

export const Route = createFileRoute('/')({
  component: HomePage,
})

function HomePage() {
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState('')

  useEffect(() => {
    const slug = window.sessionStorage.getItem(RETURN_FOCUS_KEY)
    if (!slug) return
    window.sessionStorage.removeItem(RETURN_FOCUS_KEY)
    requestAnimationFrame(() => document.getElementById(`showcase-${slug}-preview`)?.focus())
  }, [])

  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  const copyInstallCommand = async () => {
    setCopyError('')
    try {
      await navigator.clipboard.writeText(INSTALL_COMMAND)
      setCopied(true)
    } catch {
      setCopied(false)
      setCopyError('Copy unavailable. Select the command to copy it.')
    }
  }

  return (
    <>
      <SiteHeader />
      <main>
        <section className="hero" aria-labelledby="hero-title">
          <h1 id="hero-title">Your screenshot. Every element.</h1>
          <p className="hero-subtitle">A local CLI for turning screenshots into inspectable UI.</p>
          <div className="install-command" aria-label="Install command">
            <code>{INSTALL_COMMAND}</code>
            <button className="copy-button" type="button" onClick={() => void copyInstallCommand()}>
              <span className="copy-icon-slot"><img src={copyIcon} alt="" width="14.9333" height="14.9333" /></span>
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          </div>
          <p className="hero-footnote">v0.1.1 · Built for shell-capable agents</p>
          <p className="copy-status" role="status" aria-live="polite">{copyError}</p>
        </section>
        <section className="showcases" aria-labelledby="showcases-title">
          <div className="showcases-heading">
            <h2 id="showcases-title">Showcases</h2>
            <p>Hover a screenshot to inspect its elements.</p>
          </div>
          <div className="showcase-grid">
            {showcases.map((showcase) => <ShowcaseCard key={showcase.slug} showcase={showcase} />)}
          </div>
        </section>
      </main>
    </>
  )
}
