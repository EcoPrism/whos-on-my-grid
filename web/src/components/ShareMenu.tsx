import { useEffect, useId, useRef, useState } from 'react'
import { getCard } from '../lib/api'
import type { CardInfo } from '../types'

type Props = { kind: CardInfo['kind']; id: string; disabled?: boolean }

type Load = { kind: 'idle' } | { kind: 'loading' } | { kind: 'error' } | { kind: 'ready'; info: CardInfo }

// One button that opens the ways out: the platforms' own compose intents, the
// phone's share sheet, the link and the PNG. Text, link and image all come
// from the card endpoint, so the post says what the picture says, and the
// prefilled text says it is AI-assisted. Nothing is posted on the user's
// behalf; every intent opens the platform's own compose box.
export default function ShareMenu({ kind, id, disabled = false }: Props) {
  const [load, setLoad] = useState<Load>({ kind: 'idle' })
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  // Bumped to fetch again after a failure.
  const [attempt, setAttempt] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const menuId = useId()

  // Fetched as soon as sharing is allowed, so the native share sheet opens
  // inside the click that asked for it. A failure is fetched again when the
  // menu reopens or on Try again.
  useEffect(() => {
    if (disabled) return
    let cancelled = false
    setLoad({ kind: 'loading' })
    getCard(kind, id)
      .then((info) => { if (!cancelled) setLoad({ kind: 'ready', info }) })
      .catch(() => { if (!cancelled) setLoad({ kind: 'error' }) })
    return () => { cancelled = true }
  }, [kind, id, disabled, attempt])

  useEffect(() => { if (disabled) setOpen(false) }, [disabled])

  // Escape closes and hands focus back; a click elsewhere closes.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        button.current?.focus()
      }
    }
    const onDown = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown)
    }
  }, [open])

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 2000)
    return () => clearTimeout(t)
  }, [copied])

  const info = load.kind === 'ready' ? load.info : null
  const canNativeShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function'

  async function copyLink(url: string) {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
    } catch {
      window.prompt('Copy this link', url)
    }
  }

  async function nativeShare(i: CardInfo) {
    try {
      await navigator.share({ title: i.spec.title, text: textWithoutUrl(i), url: i.url })
      setOpen(false)
    } catch {
      /* dismissed */
    }
  }

  const item = 'block w-full px-3 py-2 text-left text-[15px] no-underline hover:bg-[var(--paper-deep)] focus-visible:bg-[var(--paper-deep)]'

  return (
    <div ref={root} className="relative inline-block">
      <button
        ref={button}
        type="button"
        disabled={disabled}
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => {
          if (!open && load.kind === 'error') setAttempt((a) => a + 1)
          setOpen((o) => !o)
        }}
        className="btn-signal px-4 py-2 disabled:cursor-not-allowed"
      >
        Share <span aria-hidden>▾</span>
      </button>
      {open && (
        <div
          id={menuId}
          className="absolute left-0 z-[1200] mt-2 w-64 border-2 border-[var(--ink)] bg-white shadow-[4px_4px_0_var(--ink)]"
        >
          {load.kind === 'loading' && <p className="px-3 py-2 text-sm text-[var(--ink-soft)]">Preparing the card…</p>}
          {load.kind === 'error' && (
            <p className="px-3 py-2 text-sm text-[var(--reported)]" role="alert">
              Could not load the share card.{' '}
              <button type="button" className="underline" onClick={() => setAttempt((a) => a + 1)}>Try again</button>
            </p>
          )}
          {info && (
            <ul className="py-1">
              {intents(info).map(([label, href]) => (
                <li key={label}>
                  <a className={item} href={href} target="_blank" rel="noopener noreferrer" onClick={() => setOpen(false)}>{label}</a>
                </li>
              ))}
              {canNativeShare && (
                <li><button type="button" className={item} onClick={() => nativeShare(info)}>More apps…</button></li>
              )}
              <li className="mt-1 border-t border-[var(--line)] pt-1">
                <button type="button" className={item} onClick={() => copyLink(info.url)} aria-live="polite">
                  {copied ? 'Link copied' : 'Copy link'}
                </button>
              </li>
              <li>
                <a className={item} href={info.image_url} download={`whos-on-my-grid-${info.id}.png`}>Download image (PNG)</a>
              </li>
              <li className="border-t border-[var(--line)] px-3 py-2 text-xs text-[var(--ink-soft)]">
                The text says the brief is AI-assisted, every claim cited. The image carries the same line.
              </li>
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

// share_text ends with the link; intents that take the link separately get
// the text without it, so the post does not carry it twice.
function textWithoutUrl(i: CardInfo): string {
  return i.share_text.endsWith(i.url) ? i.share_text.slice(0, -i.url.length).trim() : i.share_text
}

function intents(i: CardInfo): [string, string][] {
  const e = encodeURIComponent
  const text = textWithoutUrl(i)
  const full = `${text} ${i.url}`
  return [
    ['X', `https://x.com/intent/post?text=${e(text)}&url=${e(i.url)}`],
    ['Bluesky', `https://bsky.app/intent/compose?text=${e(full)}`],
    ['Threads', `https://www.threads.net/intent/post?text=${e(full)}`],
    ['LinkedIn', `https://www.linkedin.com/sharing/share-offsite/?url=${e(i.url)}`],
    ['Facebook', `https://www.facebook.com/sharer/sharer.php?u=${e(i.url)}`],
    ['WhatsApp', `https://wa.me/?text=${e(full)}`],
  ]
}
