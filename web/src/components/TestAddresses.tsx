// A dropdown of addresses from the eval set (eval/addresses.json), each with
// what the brief should say. For testing full and agent mode by hand; picking
// one fills the address box, it does not submit.

export interface TestAddress {
  address: string
  expect: string
}

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

interface Props {
  onPick: (address: string) => void
  disabled?: boolean
}

export default function TestAddresses({ onPick, disabled }: Props) {
  return (
    <label className="mt-3 flex flex-col gap-1 text-sm text-[var(--ink-soft)] sm:flex-row sm:items-baseline sm:gap-3">
      <span className="shrink-0">Or pick a test address</span>
      <select
        aria-label="Test addresses"
        defaultValue=""
        disabled={disabled}
        onChange={(e) => { if (e.target.value) onPick(e.target.value) }}
        className="w-full border border-[var(--line)] bg-white px-2 py-1 text-base text-[var(--ink)] disabled:opacity-60"
      >
        <option value="">Choose one…</option>
        {TEST_ADDRESSES.map((t) => (
          <option key={t.address} value={t.address}>
            {t.address} — {t.expect}
          </option>
        ))}
      </select>
    </label>
  )
}
