import { ApiError } from './api'
import type { Scenario } from '../types'

// What the reader sees when the engine could not run a what-if. Shared by the
// home page's panel and the what-if page's own controls. Never echoes the ZIP.
export function scenarioMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.status) {
      case 404:
        return err.detail === 'zip_not_found'
          ? 'That ZIP code is not in the Census list of ZIP areas. Check the five digits.'
          : 'No what-if with that id.'
      case 422:
        return 'The engine cannot run those inputs. Use a five-digit ZIP and a size between 20 and 2,000 MW.'
      case 403:
        return 'That request did not come from this page. Reload and try again.'
      case 429:
        return "Today's what-if budget is spent. Shared what-ifs still open."
      case 503:
        if (err.detail === 'scenarios_unavailable') return 'The what-if engine is not running on this server.'
        return 'The ZIP lookup is not answering. Try again in a minute.'
      default:
        return `Something went wrong (${err.status}).`
    }
  }
  return 'Cannot reach the what-if service. Is it running?'
}

// A scenario leaves the page only once its claims are checked, or when no
// verifier is configured (then every claim stays "unchecked" and none carries
// a `verified_by`, and the page says so). The engine checks before it answers,
// so in practice this holds as soon as the scenario arrives.
export function shareable(s: Scenario): boolean {
  const verifierOn = s.claims.some((c) => c.verified_by)
  return !verifierOn || s.claims.every((c) => c.verdict !== 'unchecked')
}
