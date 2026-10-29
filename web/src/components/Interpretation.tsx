import { useCallback, useEffect, useRef, useState } from 'react'
import SignIn from './SignIn'
import { ApiError, getHealth, streamInterpretation, type Health, type Me } from '../lib/api'
import { STATUS_WORD, confidenceWord } from '../lib/words'
import type { Scenario } from '../types'

// The what-if in plain words. The numbers above are the engine's arithmetic
// and free to everyone; this paragraph is Muse Spark's, so it costs a model
// run and needs a sign-in. Once made it is kept with the scenario, tagged
// Reported, and its claims join the cited list below like any other.

type Running = { kind: 'running'; stage: 'starting' | 'drafting' | 'verifying'; verified: number; claims: number }
type Run =
  | { kind: 'idle' }
  | { kind: 'done' }
  | Running
  | { kind: 'signin'; health: Health | null }
  | { kind: 'error'; message: string }

export default function Interpretation({
  scenario: s,
  disabled,
  onScenario,
}: {
  scenario: Scenario
  // True while a change to the campus is pending: the numbers shown are not
  // the ones an explanation would be about.
  disabled: boolean
  onScenario: (s: Scenario) => void
}) {
  const [run, setRun] = useState<Run>({ kind: 'idle' })
  // The stream may finish after the reader moves on (the result is kept with
  // its scenario); only this view's own state stops updating.
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  const id = s.scenario_id
  // A finished run belongs to its scenario, not to the next one shown.
  useEffect(() => {
    setRun((r) => (r.kind === 'done' ? { kind: 'idle' } : r))
  }, [id])
  const start = useCallback(async () => {
    setRun({ kind: 'running', stage: 'starting', verified: 0, claims: 0 })
    try {
      const made = await streamInterpretation(id, (ev) => {
        if (!mounted.current) return
        if (ev.stage === 'drafting') setRun({ kind: 'running', stage: 'drafting', verified: 0, claims: 0 })
        if (ev.stage === 'verifying') setRun({ kind: 'running', stage: 'verifying', verified: ev.verified, claims: ev.claims })
      })
      if (!made.interpretation) throw new ApiError(502, 'no_interpretation')
      onScenario(made)
      if (mounted.current) setRun({ kind: 'done' })
    } catch (err) {
      if (!mounted.current) return
      if (err instanceof ApiError && err.status === 401) {
        setRun({ kind: 'signin', health: null })
        getHealth()
          .then((health) => { if (mounted.current) setRun((r) => (r.kind === 'signin' ? { kind: 'signin', health } : r)) })
          .catch(() => undefined)
        return
      }
      setRun({ kind: 'error', message: interpretMessage(err) })
    }
  }, [id, onScenario])

  // Signed in from the prompt: back to the button, which the reader presses
  // again. Nothing is spent without that second press.
  const onUser = useCallback((me: Me | null) => {
    if (me) setRun({ kind: 'idle' })
    else setRun((r) => (r.kind === 'signin' && r.health ? { kind: 'signin', health: { ...r.health, user: null } } : r))
  }, [])

  const it = s.interpretation
  const running = run.kind === 'running'
  // The model's own claims: engine claims carry drafted_by 'engine'.
  const modelClaims = s.claims.filter((c) => c.drafted_by && c.drafted_by !== 'engine')
  const fromModel = modelClaims.length
  const checked = modelClaims.filter((c) => c.verified_by).length
  const backed = modelClaims.filter((c) => c.verified_by && c.verdict === 'supported').length
  const headId = `interp-${id}`

  // When the paragraph lands the button goes away; focus moves to the
  // paragraph so a keyboard reader is not dropped back at the top.
  const textRef = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (run.kind === 'done' && it) textRef.current?.focus()
  }, [run.kind, it])

  return (
    <section
      aria-labelledby={headId}
      className={`border-l-4 pl-5 sm:pl-7 ${it ? 'rail-reported' : 'interp-idle'}`}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 id={headId} className="text-3xl font-bold leading-none">In plain words</h2>
        {it && (
          <p className="tag-reported text-sm font-semibold">
            {STATUS_WORD.reported}
            {it.draft && checked === 0 && (
              <span className="font-normal text-[var(--ink-soft)]"> · not checked by a second model</span>
            )}
            {it.draft && checked > 0 && (
              <span className="font-normal text-[var(--ink-soft)]">
                {' '}· a second model backed <span className="num">{backed}</span> of <span className="num">{checked}</span>{' '}
                {checked === 1 ? 'claim' : 'claims'}
              </span>
            )}
            {(!it.draft || checked > 0) && (
              <span className="font-normal text-[var(--ink-soft)]"> · {confidenceWord(it.confidence)}</span>
            )}
          </p>
        )}
      </header>

      {it ? (
        <>
          <p
            ref={textRef}
            tabIndex={-1}
            className={`mt-4 max-w-[64ch] text-lg leading-snug focus:outline-none ${it.draft ? 'text-[var(--ink-soft)]' : ''}`}
          >
            {it.draft && <span className="chip-draft">Draft</span>}
            {it.text}
          </p>
          <footer className="mt-4 text-sm text-[var(--ink-soft)]">
            <p>
              Produced by {it.model} from the figures on this page. It describes a hypothetical campus; the numbers are the engine's.
              {fromModel > 0 && <> Its <span className="num">{fromModel}</span> {fromModel === 1 ? 'claim is' : 'claims are'} in the cited list below.</>}
            </p>
          </footer>
        </>
      ) : (
        <>
          <p className="mt-3 max-w-[64ch] text-[15px] text-[var(--ink-soft)]">
            A model can put these figures into a few sentences a neighbour would read. A second model checks each of its claims against the cited page.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              // Not `disabled` while running: a disabled button drops keyboard focus.
              onClick={running ? undefined : start}
              disabled={disabled && !running}
              aria-disabled={running || undefined}
              className="btn-signal inline-flex items-center gap-2 px-5 py-2.5 text-[15px]"
            >
              {running && <span className="spinner" aria-hidden />}
              Explain this in plain words
            </button>
            {disabled && !running && <span className="text-sm text-[var(--ink-soft)]">Available once the new numbers arrive.</span>}
          </div>
        </>
      )}
      <div className={`text-sm ${it ? '' : 'mt-3 min-h-6'}`} aria-live="polite">
        {run.kind === 'running' && <p className="text-[var(--ink-soft)]">{stageText(run)}</p>}
        {run.kind === 'done' && it && <p className="sr-only">The explanation is ready.</p>}
        {run.kind === 'error' && <p role="alert">{run.message}</p>}
        {run.kind === 'signin' && (
          <div className="max-w-[64ch]">
            <p role="alert">
              The numbers on this page stay free without an account. The explanation needs a sign-in because it uses a model, and each account has a daily allowance.
            </p>
            {run.health?.auth === 'google' && (
              <div className="mt-3"><SignIn health={run.health} onUser={onUser} /></div>
            )}
            {run.health && run.health.auth !== 'google' && (
              <p className="mt-2 text-[var(--ink-soft)]">Sign in from the home page, then come back to this link.</p>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

function stageText(run: Running): string {
  switch (run.stage) {
    case 'starting':
      return 'Asking for an explanation…'
    case 'drafting':
      return 'Writing from the figures on this page…'
    case 'verifying':
      return run.claims > 0
        ? `Checking its claims against their sources: ${run.verified} of ${run.claims}.`
        : 'Checking its claims against their sources…'
  }
}

// What the reader sees when the explanation could not be made. Never echoes the ZIP.
function interpretMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.status) {
      case 429:
        return err.detail === 'quota_exceeded_user'
          ? "You have used today's model runs. Try again tomorrow; the numbers above stay free."
          : "Today's model budget is spent. Try again tomorrow; the numbers above stay free."
      case 404:
        return 'This what-if is no longer in the cache. Change the campus above to make it again.'
      case 403:
        return 'That request did not come from this page. Reload and try again.'
      case 503:
        return 'Explanations are not available on this server. The numbers above do not depend on one.'
      case 502:
        return 'The drafting model did not answer. Try again.'
      case 0:
        return err.detail
      default:
        return `Something went wrong (${err.status}).`
    }
  }
  return 'Cannot reach the what-if service. Is it running?'
}
