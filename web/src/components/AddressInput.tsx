import { useEffect, useRef, useState } from 'react'

// A plain input by default. When VITE_GOOGLE_MAPS_API_KEY is set, Google
// Places Autocomplete (US only) is mounted instead; if the script fails to
// load, or Google rejects the key for this origin, the plain input is used.
// Either way the parent gets a string: the picked suggestion or the typed text.

const KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined

interface Props {
  value: string
  onChange: (v: string) => void
  disabled?: boolean
}

const INPUT_CLASS =
  'w-full border-2 border-[var(--ink)] bg-white px-4 py-3 text-lg placeholder:text-[var(--line)] disabled:opacity-60'

export default function AddressInput({ value, onChange, disabled }: Props) {
  const [places, setPlaces] = useState<PlacesLib | null>(null)
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!KEY) return
    let cancelled = false
    loadPlaces(KEY)
      .then((lib) => { if (!cancelled) setPlaces(lib) })
      .catch(() => { /* stay on the plain input */ })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!places || !host.current) return
    const el = new places.PlaceAutocompleteElement({ componentRestrictions: { country: ['us'] } })
    el.id = 'address'
    const onSelect = async (e: PlaceSelectEvent) => {
      const place = e.placePrediction ? e.placePrediction.toPlace() : e.place
      if (!place) return
      await place.fetchFields({ fields: ['formattedAddress'] })
      if (place.formattedAddress) onChange(place.formattedAddress)
    }
    // Typed text counts as the address too, so the form works when no
    // suggestion is picked (or none arrives). `input` is composed, so it
    // crosses the widget's shadow boundary.
    const onInput = (e: Event) => {
      const target = e.composedPath()[0]
      if (target instanceof HTMLInputElement) onChange(target.value)
    }
    // A blocked key (wrong referrer, quota) must not take the address box
    // down with it: go back to the plain input.
    const onError = () => setPlaces(null)
    el.addEventListener('gmp-select', onSelect)
    el.addEventListener('gmp-placeselect', onSelect)
    el.addEventListener('input', onInput)
    el.addEventListener('gmp-requesterror', onError)
    host.current.replaceChildren(el)
    return () => { el.remove() }
  }, [places, onChange])

  if (places) {
    return <div ref={host} className="w-full border-2 border-[var(--ink)] bg-white px-2 py-1 text-lg" />
  }
  return (
    <input
      id="address"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="21715 Filigree Ct, Ashburn, VA"
      autoComplete="street-address"
      disabled={disabled}
      className={INPUT_CLASS}
    />
  )
}

// --- Google Maps JS API, loaded on demand --------------------------------

interface Place {
  fetchFields(o: { fields: string[] }): Promise<unknown>
  formattedAddress?: string | null
}
interface PlaceSelectEvent extends Event {
  placePrediction?: { toPlace(): Place }
  place?: Place
}
interface PlacesLib {
  PlaceAutocompleteElement: new (o: { componentRestrictions?: { country: string[] } }) => HTMLElement
}
declare global {
  interface Window {
    google?: { maps?: { importLibrary(name: string): Promise<unknown> } }
    __gridMapsReady?: () => void
  }
}

let loading: Promise<PlacesLib> | null = null

// With loading=async the API finishes initialising after the script's own
// onload, so importLibrary is only safe to call from the callback parameter.
function loadPlaces(key: string): Promise<PlacesLib> {
  if (loading) return loading
  loading = new Promise<PlacesLib>((resolve, reject) => {
    window.__gridMapsReady = () => {
      const maps = window.google?.maps
      if (!maps) return reject(new Error('maps missing'))
      maps.importLibrary('places').then((lib) => resolve(lib as PlacesLib), reject)
    }
    const s = document.createElement('script')
    s.src =
      `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}` +
      '&loading=async&v=weekly&callback=__gridMapsReady'
    s.async = true
    s.onerror = () => reject(new Error('maps script failed'))
    document.head.appendChild(s)
  })
  return loading
}
