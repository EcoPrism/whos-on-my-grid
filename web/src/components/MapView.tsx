import type { Brief } from '../types'
import GridMap, {
  FIVE_MILES_M,
  facilityLine,
  facilityMarker,
  hasPoint,
  headlineBoundsOptions,
  type GridMarker,
  type GridPolygon,
  type LatLon,
} from './GridMap'

interface Props {
  brief: Brief
  className?: string
}

// The five-mile ring is the product's unit of concern. Each facility is tied
// to the address by a line that flows toward it: the grid you share, drawn.
export function BriefMap({ brief, className }: Props) {
  const { lat, lon } = brief.address
  const here: LatLon = [lat, lon]
  // Live and under-construction sites live on "On your grid"; announced
  // campuses on "Coming". Both belong on the map.
  const placed = [
    ...(brief.sections.on_your_grid.facilities ?? []),
    ...(brief.sections.coming.facilities ?? []),
  ].filter(hasPoint)
  const construction = brief.sections.coming.construction ?? []

  // Frame the address and everything tied to it, so the lines have length.
  // With nothing nearby, show the five-mile ring instead.
  const frame: LatLon[] = [
    here,
    ...placed.map((f): LatLon => [f.lat, f.lon]),
    ...construction.flatMap((c) => c.polygon ?? []),
  ]

  const polygons: GridPolygon[] = construction
    .filter((c) => c.polygon && c.polygon.length > 2)
    .map((c, i) => ({
      key: c.label ?? `construction-${i}`,
      positions: c.polygon!,
      pathOptions: { color: '#0f766e', weight: 2, fillColor: '#0f766e', fillOpacity: c.in_database ? 0.15 : 0.35 },
      popup: (
        <>
          <strong>{c.label}</strong><br />
          {c.footprint_acres_then} → {c.footprint_acres_now} acres ({c.vintages[0]} → {c.vintages[1]})<br />
          {c.in_database ? 'listed in a facility database' : 'in no facility database'}
        </>
      ),
    }))

  const markers: GridMarker[] = [
    ...placed.map((f, i) => facilityMarker(f, `${i}-${f.name}`)),
    // The address: a pulse ring under a solid marker.
    { key: 'here-pulse', at: here, radius: 7, pathOptions: { color: '#ffc300', weight: 2, fill: false, className: 'pulse' }, interactive: false },
    { key: 'here', at: here, radius: 7, pathOptions: { color: '#15202b', fillColor: '#ffc300', fillOpacity: 1, weight: 2 }, popup: 'Your address' },
  ]

  return (
    <GridMap
      center={here}
      frame={frame}
      boundsOptions={headlineBoundsOptions()}
      rings={[{ key: 'ring', center: here, radiusM: FIVE_MILES_M, pathOptions: { color: '#15202b', weight: 1.5, dashArray: '6 6', fill: false } }]}
      lines={placed.map((f, i) => facilityLine(f, here, `line-${i}-${f.name}`))}
      polygons={polygons}
      markers={markers}
      className={className}
    />
  )
}

export default BriefMap
