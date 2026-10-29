import { useEffect, useRef, type ReactNode } from 'react'
import { latLngBounds, type FitBoundsOptions, type PathOptions } from 'leaflet'
import { Circle, CircleMarker, MapContainer, Polygon, Polyline, Popup, TileLayer, Tooltip, ZoomControl, useMap } from 'react-leaflet'
import type { Facility, Units } from '../types'

export type LatLon = [number, number]

export const FIVE_MILES_M = 8047
export const EIGHT_KM_M = 8000

// The brief's ring: five miles in the US, 8 km where the units are metric.
export function ringRadiusM(units: Units = 'us') {
  return units === 'us' ? FIVE_MILES_M : EIGHT_KM_M
}

// Status is the only color on the map, as on the page.
export const STATUS_COLOR: Record<Facility['status'], string> = {
  live: '#15202b',
  under_construction: '#b7791f',
  announced: '#3b5b8c',
  rejected: '#8a8f98',
}

// Line weight follows load, on a log scale so a 10 MW edge site and a 300 MW
// campus both read without one swamping the other. Nothing else changes the
// weight: the substation flag is an inference and the map must not look like
// proof of it.
export function weightFor(mw: number | null | undefined) {
  const base = mw ? 1.5 + Math.log10(mw + 1) * 1.4 : 1.5
  return Math.min(7, base)
}

export function hasPoint(f: Facility): f is Facility & { lat: number; lon: number } {
  return typeof f.lat === 'number' && typeof f.lon === 'number'
}

export interface GridMarker {
  key: string
  at: LatLon
  radius: number
  pathOptions: PathOptions
  popup?: ReactNode
  interactive?: boolean
}

// A line's dash pattern flows from `from` toward `to` (see .gridline in index.css).
export interface GridLine {
  key: string
  from: LatLon
  to: LatLon
  pathOptions: PathOptions
}

export interface GridPolygon {
  key: string
  positions: LatLon[]
  pathOptions: PathOptions
  popup?: ReactNode
}

export interface GridRing {
  key: string
  // Shown on hover: what the ring measures ("The 8 km ring").
  label?: string
  center: LatLon
  radiusM: number
  pathOptions: PathOptions
}

// The dashed, flowing line that ties a facility to a point: the grid you
// share, drawn. Shared by the brief map and the what-if map.
export function facilityLine(f: Facility & { lat: number; lon: number }, to: LatLon, key: string): GridLine {
  return {
    key,
    from: [f.lat, f.lon],
    to,
    pathOptions: {
      color: STATUS_COLOR[f.status],
      weight: weightFor(f.estimated_mw),
      opacity: f.status === 'announced' ? 0.6 : f.status === 'rejected' ? 0.45 : 0.85,
      dashArray: f.status === 'rejected' ? '2 8' : undefined,
      lineCap: 'round',
      className: `gridline gridline-${f.status}`,
    },
  }
}

export function facilityMarker(f: Facility & { lat: number; lon: number }, key: string): GridMarker {
  return {
    key,
    at: [f.lat, f.lon],
    radius: f.status === 'live' ? 5 : 4.5,
    pathOptions: {
      color: '#15202b',
      weight: 1,
      fillColor: STATUS_COLOR[f.status],
      fillOpacity: f.status === 'announced' ? 0.5 : f.status === 'rejected' ? 0.25 : 0.95,
    },
    popup: (
      <>
        <strong>{f.name}</strong><br />
        {f.operator}{f.codename ? ` (filed as ${f.codename})` : ''}<br />
        {f.status === 'rejected' ? 'rejected or withdrawn' : f.status.replace('_', ' ')}, {f.distance_km.toFixed(1)} km
        {f.estimated_mw ? `, ${f.estimated_mw} MW` : ''}
        {f.shares_substation ? ', likely on your substation (inferred)' : ''}
      </>
    ),
  }
}

// The headline card sits over the top-left of the map on wider screens and
// over the top on phones; keep every point out from under it.
export function headlineBoundsOptions(): FitBoundsOptions {
  const wide = typeof window !== 'undefined' && window.matchMedia('(min-width: 640px)').matches
  return wide
    ? { paddingTopLeft: [470, 40], paddingBottomRight: [24, 24] }
    : { paddingTopLeft: [12, 230], paddingBottomRight: [12, 12] }
}

export interface GridMapProps {
  center: LatLon
  // Points to frame; with fewer than two, the map centres on `center` at `zoom`.
  frame?: LatLon[]
  zoom?: number
  boundsOptions?: FitBoundsOptions
  // When this changes after mount, the view refits to `frame` (or recentres).
  // MapContainer's own center and bounds are read once only.
  viewKey?: string
  markers?: GridMarker[]
  lines?: GridLine[]
  polygons?: GridPolygon[]
  rings?: GridRing[]
  className?: string
  // Extra react-leaflet layers drawn on top, such as a draggable marker.
  children?: ReactNode
}

// Bounds to fit, or undefined to fall back to center and zoom: a frame of one
// point (or of identical points) has no size and would fit at maximum zoom.
function frameOf(frame: LatLon[] | undefined) {
  if (!frame || frame.length < 2) return undefined
  const b = latLngBounds(frame)
  return b.getNorth() === b.getSouth() && b.getEast() === b.getWest() ? undefined : b.pad(0.12)
}

function Refit({ viewKey, center, frame, zoom, boundsOptions }: Pick<GridMapProps, 'viewKey' | 'center' | 'frame' | 'zoom' | 'boundsOptions'>) {
  const map = useMap()
  const first = useRef(viewKey)
  // Read the latest geometry from a ref so only viewKey triggers a refit.
  const latest = useRef({ center, frame, zoom, boundsOptions })
  useEffect(() => {
    latest.current = { center, frame, zoom, boundsOptions }
  })
  useEffect(() => {
    if (viewKey === first.current) return
    first.current = viewKey
    const { center: c, frame: f, zoom: z, boundsOptions: o } = latest.current
    const bounds = frameOf(f)
    if (bounds) map.fitBounds(bounds, o)
    else map.setView(c, z ?? 12)
  }, [map, viewKey])
  return null
}

// A Leaflet map in the product's look: a grey basemap, status colours, and
// whatever rings, lines, polygons and markers the page hands it, drawn in that
// order. react-leaflet adds and removes each layer as the arrays change and on
// unmount, so callers never touch Leaflet layers directly.
export default function GridMap({
  center,
  frame,
  zoom = 12,
  boundsOptions,
  viewKey,
  markers = [],
  lines = [],
  polygons = [],
  rings = [],
  className,
  children,
}: GridMapProps) {
  const bounds = frameOf(frame)
  return (
    <MapContainer
      // react-leaflet uses center and zoom when given, else bounds.
      {...(bounds ? { bounds, boundsOptions } : { center, zoom })}
      scrollWheelZoom={false}
      zoomControl={false}
      className={className ?? 'h-[360px] w-full sm:h-[440px]'}
      attributionControl
    >
      <ZoomControl position="topright" />
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        className="basemap"
      />
      <Refit viewKey={viewKey} center={center} frame={frame} zoom={zoom} boundsOptions={boundsOptions} />

      {rings.map((r) => (
        <Circle key={r.key} center={r.center} radius={r.radiusM} pathOptions={r.pathOptions}>
          {r.label && <Tooltip sticky>{r.label}</Tooltip>}
        </Circle>
      ))}

      {lines.map((l) => (
        <Polyline key={l.key} positions={[l.from, l.to]} pathOptions={l.pathOptions} />
      ))}

      {polygons.map((p) => (
        <Polygon key={p.key} positions={p.positions} pathOptions={p.pathOptions}>
          {p.popup && <Popup>{p.popup}</Popup>}
        </Polygon>
      ))}

      {markers.map((m) => (
        <CircleMarker key={m.key} center={m.at} radius={m.radius} pathOptions={m.pathOptions} interactive={m.interactive ?? true}>
          {m.popup && <Popup>{m.popup}</Popup>}
        </CircleMarker>
      ))}

      {children}
    </MapContainer>
  )
}
