import { useEffect, useId, useRef, useState } from 'react'
import type { Cooling, ScenarioInputs } from '../types'
import MwSlider from './MwSlider'

const COOLING: { value: Cooling; label: string; note: string }[] = [
  { value: 'evaporative', label: 'Evaporative', note: 'cools by evaporating water' },
  { value: 'closed_loop', label: 'Closed loop', note: 'recirculates water to the chips' },
]

const ZIP = /^\d{5}$/

type Props = {
  onSubmit: (inputs: ScenarioInputs) => void
  // The engine's answer when it could not run the ZIP (its 404 text, a range
  // error); shown under the form until the next edit.
  error?: string | null
  // A request is in flight: the button shows a spinner and the inputs hold.
  busy?: boolean
  // Starting values, e.g. when the panel reopens on a scenario's own inputs.
  initial?: Partial<Pick<ScenarioInputs, 'zip' | 'mw' | 'cooling'>>
  // Leave out the heading and the one-line explanation (when the page has its own).
  compact?: boolean
}

// "Drop a data center on your town": ZIP, campus size and cooling. Nothing here
// needs a sign-in or a model; the engine answers with arithmetic. The pin is
// the ZIP's centre until the reader drags it on the scenario map.
export default function WhatIfPanel({ onSubmit, error = null, busy = false, initial, compact = false }: Props) {
  const [zip, setZip] = useState(initial?.zip ?? '')
  const [mw, setMw] = useState(initial?.mw ?? 100)
  const [cooling, setCooling] = useState<Cooling>(initial?.cooling ?? 'evaporative')
  const [invalid, setInvalid] = useState<string | null>(null)
  // The engine's error belongs to the inputs it was given; an edit clears it.
  const [editedSinceError, setEditedSinceError] = useState(false)
  const [lastError, setLastError] = useState(error)
  if (error !== lastError) {
    setLastError(error)
    setEditedSinceError(false)
  }
  const zipRef = useRef<HTMLInputElement>(null)
  // Disabling the form while busy drops focus to <body>; when the engine
  // answers with an error, put the reader back on the field it is about.
  useEffect(() => {
    if (error && !busy) zipRef.current?.focus()
  }, [error, busy])

  const id = useId()
  const zipId = `${id}-zip`
  const msgId = `${id}-msg`
  const headId = `${id}-head`
  const shownError = invalid ?? (error && !editedSinceError ? error : null)

  function edited() {
    setInvalid(null)
    setEditedSinceError(true)
  }

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    const z = zip.trim()
    if (!ZIP.test(z)) {
      setInvalid('Enter a five-digit US ZIP code, like 20147.')
      zipRef.current?.focus()
      return
    }
    setInvalid(null)
    setEditedSinceError(false)
    onSubmit({ zip: z, mw, cooling, pin: null })
  }

  return (
    <section aria-labelledby={compact ? undefined : headId} aria-label={compact ? 'What-if' : undefined}>
      {!compact && (
        <>
          <h2 id={headId} className="text-2xl font-bold leading-none">Drop a data center on your town</h2>
          <p className="mt-3 max-w-[56ch] text-[var(--ink-soft)]">
            A ZIP code, a size and a way to cool it. The engine works out the power, water, land and
            bill from cited figures. Hypothetical, modelled, no sign-in.
          </p>
        </>
      )}
      <form onSubmit={submit} noValidate className={compact ? '' : 'mt-6'} aria-busy={busy}>
        {/* Stacked: the panel sits in half the page beside the address form. */}
        <div className="grid gap-y-6">
          <div className="max-w-[11rem]">
            <label htmlFor={zipId} className="block text-sm text-[var(--ink-soft)]">ZIP code</label>
            <input
              id={zipId}
              ref={zipRef}
              name="zip"
              inputMode="numeric"
              autoComplete="postal-code"
              pattern="[0-9]{5}"
              maxLength={5}
              placeholder="20147"
              value={zip}
              disabled={busy}
              aria-invalid={Boolean(shownError)}
              aria-describedby={shownError ? msgId : undefined}
              onChange={(e) => {
                setZip(e.target.value.replace(/\D/g, '').slice(0, 5))
                edited()
              }}
              className="num mt-2 w-full border-2 border-[var(--ink)] bg-white px-3 py-2.5 text-lg tracking-widest"
            />
          </div>
          <MwSlider value={mw} onChange={(v) => { setMw(v); edited() }} disabled={busy} />
        </div>

        <fieldset className="mt-6">
          <legend className="text-sm text-[var(--ink-soft)]">Cooling</legend>
          <div className="seg mt-2 inline-flex">
            {COOLING.map((c) => (
              <label key={c.value} className="seg-option" title={c.note}>
                <input
                  type="radio"
                  name={`${id}-cooling`}
                  value={c.value}
                  checked={cooling === c.value}
                  disabled={busy}
                  onChange={() => { setCooling(c.value); edited() }}
                  className="sr-only"
                />
                <span className="block px-4 py-2 text-[15px]">{c.label}</span>
              </label>
            ))}
          </div>
          <p className="mt-2 text-sm text-[var(--ink-soft)]">
            {COOLING.find((c) => c.value === cooling)?.note}.
          </p>
        </fieldset>

        <div className="mt-6 flex flex-wrap items-center gap-4">
          <button type="submit" disabled={busy} className="btn-signal inline-flex items-center gap-2 px-6 py-3 text-lg">
            {busy && <span className="spinner" aria-hidden />}
            {busy ? 'Working it out…' : 'Drop it here'}
          </button>
          {busy && <span className="sr-only" role="status">Working out the scenario</span>}
        </div>
        {shownError && (
          <p id={msgId} className="mt-3 text-sm" role="alert">{shownError}</p>
        )}
      </form>
    </section>
  )
}
