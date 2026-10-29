import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'

export default function About() {
  const { hash } = useLocation()
  useEffect(() => {
    if (!hash) return
    document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [hash])

  return (
    <main className="mx-auto max-w-3xl px-4 pb-24 pt-10 sm:pt-16">
      <nav className="text-sm">
        <Link to="/" className="no-underline"><span className="wide font-semibold">Who's on my grid</span></Link>
      </nav>
      <h1 className="sign mt-8 text-[clamp(2.6rem,9vw,5rem)]">About</h1>

      <section className="mt-8 max-w-[64ch] space-y-4">
        <p>
          Type a US address and get one brief: which data centers are on your local grid, what is being
          built near you, what your bill has done, whether your state's large-load tariff shields
          households, and what was said at the last hearing.
        </p>
        <p>
          Every section is one of four kinds. <b className="tag-measured">Measured</b> comes from public
          data the engine reads itself: PeeringDB and OpenStreetMap for facilities, HIFLD for the serving
          utility, EIA-861 for prices, USDA aerial imagery for new construction, the county's own hearing
          archive for what was said. <b className="tag-reported">Reported</b> is a sentence a model wrote
          with a page it cites, and a second model checked the sentence against that page.{' '}
          <b className="tag-modelled">Modeled</b> is arithmetic over a measured number, shown as a range.{' '}
          <b className="tag-unavailable">Unavailable</b> means the brief does not know, and says so.
        </p>
        <p>
          The brief never claims that a data center caused a bill increase. It shows the numbers and
          cites who attributes what.
        </p>
      </section>

      <section id="data" className="mt-12 max-w-[64ch] space-y-4">
        <h2 className="text-xl font-semibold">What is stored</h2>
        <p>
          A brief is kept under an id that is a hash of the address, so a link can be shared and
          reopened. The address itself appears only inside that brief, shortened to street and city.
          It is never logged and never written anywhere else.
        </p>
        <p>
          Making a new brief costs model time, so it needs a Google sign-in. For a signed-in user we
          keep the email address, when it was first and last seen, and the ids of the briefs it
          generated, with a daily limit per person and overall. Opening a brief, and running one of the
          example addresses, needs no sign-in and stores nothing about you. Nothing is sold or shared.
        </p>
      </section>

      <section className="mt-12 max-w-[64ch] space-y-4">
        <h2 className="text-xl font-semibold">Who made it</h2>
        <p>
          Who's On My Grid is an <a href="https://www.ecoprism.com" rel="noopener">EcoPrism</a> project.
          Drafting is Muse Spark,
          checking is Muse Spark Open, seeing is SAM 3.1 and hearing is Muse Voice Transcribe. The code
          is on <a href="https://github.com/EcoPrism/whos-on-my-grid" rel="noopener">GitHub</a>.
        </p>
      </section>
    </main>
  )
}
