import { Link, Outlet } from 'react-router-dom'

// Every page sits inside the shell: the page, then one footer. The footer is
// the fence at the edge of the yard: ink, a signal stripe along the top, and
// three things on it: whose project this is, the key to the four colours
// every brief uses, and where the fine print lives.
const LEGEND = [
  { status: 'measured', word: 'Measured', text: 'read from public data by the engine itself' },
  { status: 'reported', word: 'Reported', text: 'a model wrote it, cited a page, and a second model checked it' },
  { status: 'modelled', word: 'Modeled', text: 'arithmetic over a measured number, shown as a range' },
  { status: 'unavailable', word: 'Not known', text: 'the brief does not know, and says so' },
]

export default function Shell() {
  return (
    <>
      <Outlet />
      <footer className="mt-24 border-t-4 border-[var(--signal)] bg-[var(--ink)] text-[var(--paper)]">
        <div className="mx-auto grid max-w-5xl gap-x-12 gap-y-10 px-4 py-12 md:grid-cols-[1.1fr_1.3fr_auto]">
          <div>
            <a href="https://www.ecoprism.com" rel="noopener" className="inline-flex items-center gap-3 no-underline">
              <span className="inline-flex h-12 items-center rounded-sm bg-[var(--paper)] px-4">
                <img src="/ecoprism.png" alt="EcoPrism" className="h-7 w-auto" />
              </span>
              <span className="text-lg font-semibold">An EcoPrism project</span>
            </a>
            <p className="mt-4 text-xs font-semibold uppercase tracking-wider text-[var(--signal)]">
              ESG and sustainability technology
            </p>
            <p className="mt-2 max-w-[40ch] text-sm leading-relaxed text-[var(--paper-soft)]">
              Who's on my grid is built by EcoPrism. An address in, a checked brief out. Every sentence
              cites a page you can open.
            </p>
            <a href="https://www.ecoprism.com" rel="noopener" className="footlink mt-3 inline-block text-sm">
              ecoprism.com →
            </a>
          </div>

          <dl className="grid gap-y-2 text-sm">
            {LEGEND.map((l) => (
              <div key={l.status} className={`key key-${l.status} pl-3`}>
                <dt className="inline font-semibold">{l.word}</dt>
                <dd className="inline text-[var(--paper-soft)]">{' '}{l.text}</dd>
              </div>
            ))}
          </dl>

          <nav className="flex flex-col gap-2 text-sm md:items-end">
            <Link to="/about" className="footlink">About</Link>
            <Link to="/about#data" className="footlink">What is stored</Link>
            <a href="https://github.com/EcoPrism/whos-on-my-grid" rel="noopener" className="footlink">Source on GitHub</a>
            <a href="https://www.peeringdb.com/" rel="noopener" className="footlink">Data: PeeringDB, OpenStreetMap, EIA</a>
          </nav>
        </div>
      </footer>
    </>
  )
}
