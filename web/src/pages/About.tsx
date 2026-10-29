import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useCurrentRegion } from '../lib/region'
import { STATUS_WORD } from '../lib/words'

// DRAFT privacy text for Irish addresses (plan 0.11): for the user's review,
// not legal advice. The EEA transfer mechanism (EU-US Data Privacy Framework or
// SCCs under the Azure terms) is still to be confirmed before it ships on.
function irishRetention(days: number | undefined): string {
  return days && days > 0
    ? `Irish briefs are deleted ${days} days after they are made.`
    : 'Irish briefs are kept until the engine changes.'
}

export default function About() {
  const { hash } = useLocation()
  // Hash links (#data) wait for the region list, which can lengthen the page.
  const { regions } = useCurrentRegion()
  useEffect(() => {
    if (!hash) return
    document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [hash, regions.length])
  const ie = regions.find((r) => r.id === 'ie')

  return (
    <main className="mx-auto max-w-3xl px-4 pb-24 pt-10 sm:pt-16">
      <nav className="text-sm">
        <Link to="/" className="no-underline"><span className="wide font-semibold">Who's on my grid</span></Link>
      </nav>
      <h1 className="sign mt-8 text-[clamp(2.6rem,9vw,5rem)]">About</h1>

      <section className="mt-8 max-w-[64ch] space-y-4">
        <p>
          {ie ? 'Type an address in the US or Ireland' : 'Type a US address'} and get one brief: which data centers are on your local grid, what is being
          built near you, what your bill has done, whether your state's large-load tariff shields
          households, and what was said at the last hearing.
        </p>
        <p>
          Every tile, sentence and section carries one of four words. <b className="tag-measured">{STATUS_WORD.measured}</b>{' '}
          means the engine read it from a public dataset itself: PeeringDB and OpenStreetMap for facilities,
          HIFLD for the serving utility, EIA-861 for prices, USDA aerial imagery for new construction, the
          county's own hearing archive for what was said. <b className="tag-reported">{STATUS_WORD.reported}</b>{' '}
          is a sentence a model wrote with a page it cites, and a second model checked the sentence against
          that page. <b className="tag-modelled">{STATUS_WORD.modelled}</b> is our arithmetic over a cited
          figure, shown as a range, not a measurement. <b className="tag-unavailable">{STATUS_WORD.unavailable}</b>{' '}
          means nobody publishes it, and the brief says so instead of guessing. Next to the word, solid,
          likely or rough says how sure the engine is; the exact figure is in the claims list.
        </p>
        {ie && (
          <p>
            For an Irish address the measured sources are PeeringDB and OpenStreetMap for facilities,
            the ESB Networks service area for the network operator, Eurostat for the national household
            electricity price (the same half-year two years apart), the CRU's connection policy for new
            data centres, and An Coimisiún Pleanála's published decisions for what has been granted
            nearby. Distances are in kilometres and prices in euro. The CRU policy is shown for what it
            requires and what it says its aim is; keeping costs off household bills is not that aim.
          </p>
        )}
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
          example addresses, needs no sign-in and stores nothing about you. Nothing is sold. The
          address goes only to the services named here.
        </p>
        <p>
          For a US address: as you type, Google Places suggests addresses (Google receives what you
          type). When you ask for a brief, the address is sent to the US Census Bureau's geocoder to
          find its location, and the street and city line and the location go to the language-model
          providers that write and check the brief.
        </p>
        {ie && (
          <p>
            For an Irish address: as you type, Google Places suggests addresses (Google receives what
            you type). When you ask for a brief, the address is sent to the OpenStreetMap Foundation's
            Nominatim service (UK) to find its location, which is then rounded to about 100 metres.
            The brief keeps the town, planning authority, Eircode routing key and that rounded point,
            never the house number or full Eircode. The rounded point and the town line are sent to
            the language-model providers that write and check the brief. Briefs and sign-in records
            are stored on Microsoft Azure in the United States, outside the EEA.{' '}
            {irishRetention(ie.brief_ttl_days)} Lawful basis: legitimate interest (GDPR Art. 6(1)(f))
            in answering your request; the sign-in email is processed to provide the account (Art.
            6(1)(b)). Geocoding {ie.geocoder_attribution ?? '© OpenStreetMap contributors'}.
          </p>
        )}
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
