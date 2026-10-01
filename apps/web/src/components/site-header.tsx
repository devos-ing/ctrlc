import { Link } from '@tanstack/react-router'

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link to="/" className="wordmark" aria-label="ctrlc home">ctrlc</Link>
      <a className="github-link" href="https://github.com/devos-ing/ctrlc" target="_blank" rel="noreferrer">
        GitHub ↗
      </a>
    </header>
  )
}
