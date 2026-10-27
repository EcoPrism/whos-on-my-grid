import { latLngBounds } from 'leaflet'
import { Circle, CircleMarker, MapContainer, Polygon, Polyline, Popup, TileLayer, ZoomControl } from 'react-leaflet'
import type { Brief, Facility } from '../types'

const FIVE_MILES_M = 8047

// Status is the only color on the map, as on the page.
const STATUS_COLOR: Record<Facility['status'], string> = {
  live: '#15202b',
  under_construction: '#b7791f',
  announced: '#3b5b8c',
}

// Line weight follows load, on a log scale so a 10 MW edge site and a 300 MW
// campus both read without one swamping the other. Nothing else changes the
// weight: the substation flag is an inference and the map must not look like
// proof of it.
function weightFor(mw: number | null | undefined) {
  const base = mw ? 1.5 + Math.log10(mw + 1) * 1.4 : 1.5
  return Math.min(7, base)
}

function hasPoint(f: Facility): f is Facility & { lat: number; lon: number } {
  return typeof f.lat === 'number' && typeof f.lon === 'number'
}

interface Props {
  brief: Brief
  className?: string
}

// The five-mile ring is the product's unit of concern. Each facility is tied
// to the address by a line that flows toward it: the grid you share, drawn.
export default function MapView({ brief, className }: Props) {
  const { lat, lon } = brief.address
  // Live and under-construction sites live on "On your grid"; announced
  // campuses on "Coming". Both belong on the map.
  const placed = [
    ...(brief.sections.on_your_grid.facilities ?? []),
    ...(brief.sections.coming.facilities ?? []),
  ].filter(hasPoint)
  const construction = brief.sections.coming.construction ?? []

  // Frame the address and everything tied to it, so the lines have length.
  // With nothing nearby, show the five-mile ring instead.
  const points: [number, number][] = [
    [lat, lon],
    ...placed.map((f): [number, number] => [f.lat, f.lon]),
    ...construction.flatMap((c) => c.polygon ?? []),
  ]
  const bounds = points.length > 1 ? latLngBounds(points).pad(0.12) : undefined
  // The headline card sits over the top-left of the map on wider screens and
  // over the top on phones; keep every facility out from under it.
  const wide = typeof window !== 'undefined' && window.matchMedia('(min-width: 640px)').matches
  const boundsOptions = wide
    ? { paddingTopLeft: [470, 40] as [number, number], paddingBottomRight: [24, 24] as [number, number] }
    : { paddingTopLeft: [12, 230] as [number, number], paddingBottomRight: [12, 12] as [number, number] }

  return (
    <MapContainer
      // react-leaflet uses center and zoom when given, else bounds.
      {...(bounds ? { bounds, boundsOptions } : { center: [lat, lon] as [number, number], zoom: 12 })}
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

      <Circle center={[lat, lon]} radius={FIVE_MILES_M} pathOptions={{ color: '#15202b', weight: 1.5, dashArray: '6 6', fill: false }} />

      {placed.map((f) => (
        <Polyline
          key={`line-${f.name}`}
          positions={[[f.lat, f.lon], [lat, lon]]}
          pathOptions={{
            color: STATUS_COLOR[f.status],
            weight: weightFor(f.estimated_mw),
            opacity: f.status === 'announced' ? 0.6 : 0.85,
            lineCap: 'round',
            className: `gridline gridline-${f.status}`,
          }}
        />
      ))}

      {construction.filter((c) => c.polygon && c.polygon.length > 2).map((c) => (
        <Polygon
          key={c.label}
          positions={c.polygon!}
          pathOptions={{ color: '#0f766e', weight: 2, fillColor: '#0f766e', fillOpacity: c.in_database ? 0.15 : 0.35 }}
        >
          <Popup>
            <strong>{c.label}</strong><br />
            {c.footprint_acres_then} → {c.footprint_acres_now} acres ({c.vintages[0]} → {c.vintages[1]})<br />
            {c.in_database ? 'listed in a facility database' : 'in no facility database'}
          </Popup>
        </Polygon>
      ))}

      {placed.map((f) => (
        <CircleMarker
          key={f.name}
          center={[f.lat, f.lon]}
          radius={f.status === 'live' ? 5 : 4.5}
          pathOptions={{
            color: '#15202b',
            weight: 1,
            fillColor: STATUS_COLOR[f.status],
            fillOpacity: f.status === 'announced' ? 0.5 : 0.95,
          }}
        >
          <Popup>
            <strong>{f.name}</strong><br />
            {f.operator}{f.codename ? ` (filed as ${f.codename})` : ''}<br />
            {f.status.replace('_', ' ')}, {f.distance_km.toFixed(1)} km
            {f.estimated_mw ? `, ${f.estimated_mw} MW` : ''}
            {f.shares_substation ? ', likely on your substation (inferred)' : ''}
          </Popup>
        </CircleMarker>
      ))}

      {/* The address: a pulse ring under a solid marker. */}
      <CircleMarker center={[lat, lon]} radius={7} pathOptions={{ color: '#ffc300', weight: 2, fill: false, className: 'pulse' }} interactive={false} />
      <CircleMarker center={[lat, lon]} radius={7} pathOptions={{ color: '#15202b', fillColor: '#ffc300', fillOpacity: 1, weight: 2 }}>
        <Popup>Your address</Popup>
      </CircleMarker>
    </MapContainer>
  )
}
