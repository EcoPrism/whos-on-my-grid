import { Link, Outlet } from 'react-router-dom'

// Every page sits inside the shell: the page, then one footer. The brief
// page keeps its own top line; the footer is where EcoPrism and the fine
// print live, so the sign at the top stays the product's.
export default function Shell() {
  return (
    <>
      <Outlet />
      <footer className="border-t border-[var(--line)]">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-8 gap-y-3 px-4 py-6 text-sm text-[var(--ink-soft)]">
          <a href="https://www.ecoprism.com" className="flex items-center gap-2 no-underline" rel="noopener">
            <img src="/ecoprism.svg" alt="EcoPrism" height={20} className="h-5 w-auto" />
            <span>An EcoPrism project</span>
          </a>
          <nav className="flex flex-wrap gap-x-5 gap-y-1">
            <Link to="/about">About</Link>
            <Link to="/about#data">What is stored</Link>
            <a href="https://github.com/EcoPrism/whos-on-my-grid" rel="noopener">Source</a>
          </nav>
        </div>
      </footer>
    </>
  )
}
