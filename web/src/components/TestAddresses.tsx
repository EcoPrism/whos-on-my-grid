// The addresses that run without a sign-in: the eval set (eval/addresses.json).
// The API serves the list (`health.test_addresses`), spelled exactly as the
// gate admits them; four of them are offered as one-tap chips, the rest sit in
// a select. Picking one fills the address box, it does not submit: a run
// spends model time, so the button stays the only way to start one.

export interface TestAddress {
  address: string
  expect: string
}

// Notes for the hand-testing dropdown, attached when an address matches.
export const TEST_ADDRESSES: TestAddress[] = [
  { address: '21721 Filigree Court, Ashburn, VA 20147', expect: 'dense cluster, Dominion, GS-5 tariff' },
  { address: '22166 Pacific Boulevard, Sterling, VA 20166', expect: 'Loudoun cluster, Dominion' },
  { address: '8303 Wellington Road, Manassas, VA 20109', expect: 'Digital Gateway, hearing hook' },
  { address: '2313 153rd Ave SE, Bellevue, WA 98007', expect: 'two Colocation Northwest sites, PSE' },
  { address: '1098 F Street Southwest, Quincy, WA 98848', expect: 'Microsoft nearby, flat PUD price' },
  { address: '2001 6th Ave, Seattle, WA 98121', expect: 'downtown colocation' },
  { address: '4606 Singleton Boulevard, Dallas, TX 75212', expect: 'Oncor, Texas SB 6' },
  { address: '2124 Beech Road Northwest, New Albany, OH 43031', expect: 'AEP Ohio tariff, construction' },
  { address: '1207 North Main Street, Prineville, OR 97754', expect: 'Meta and Apple, Pacific Power' },
  { address: '2130 Adventureland Drive, Altoona, IA 50009', expect: 'Meta campus, MidAmerican' },
  { address: '6401 Startown Road, Maiden, NC 28650', expect: 'Apple campus, unnamed in OSM' },
  { address: '10760 South Ellsworth Road, Mesa, AZ 85236', expect: 'Mesa campuses, SRP' },
  { address: '655 North Alvernon Way, Tucson, AZ 85711', expect: 'Project Blue rejected' },
  { address: '111 8th Ave, New York, NY 10011', expect: 'carrier hotel, Con Edison' },
  { address: '425 Eaton Street, Key West, FL 33040', expect: 'null result, Keys Energy' },
  { address: '1228 West Main Street, Bozeman, MT 59717', expect: 'null result, NorthWestern' },
  { address: '998 Mililani Street, Honolulu, HI 96813', expect: 'null result, Hawaiian Electric' },
]

// Four places that tell four different stories, shown as chips.
const FEATURED = ['Ashburn, VA', 'Quincy, WA', 'New Albany, OH', 'Key West, FL']

interface Props {
  items?: string[]
  onPick: (address: string) => void
  disabled?: boolean
}

export default function TestAddresses({ items, onPick, disabled }: Props) {
  const notes = new Map(TEST_ADDRESSES.map((t) => [t.address, t.expect]))
  const list: TestAddress[] = items && items.length > 0
    ? items.map((address) => ({ address, expect: notes.get(address) ?? '' }))
    : TEST_ADDRESSES
  const chips = FEATURED.flatMap((place) => {
    const hit = list.find((t) => t.address.includes(place))
    return hit ? [{ place, address: hit.address }] : []
  })

  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-2 text-sm">
      <span className="mr-1 text-[var(--ink-soft)]">Try</span>
      {chips.map((c) => (
        <button key={c.address} type="button" className="chip" disabled={disabled} onClick={() => onPick(c.address)}>
          {c.place}
        </button>
      ))}
      <label className="inline-flex items-center">
        <span className="sr-only">All test addresses</span>
        <select
          defaultValue=""
          disabled={disabled}
          onChange={(e) => { if (e.target.value) onPick(e.target.value) }}
          className="chip max-w-[14rem] cursor-pointer appearance-none pr-7"
        >
          <option value="">All {list.length} test addresses…</option>
          {list.map((t) => (
            <option key={t.address} value={t.address}>
              {t.expect ? `${t.address} — ${t.expect}` : t.address}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
