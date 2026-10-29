import { useMemo, useState } from 'react'
import { divIcon, type LeafletEvent, type LeafletKeyboardEvent, type Marker as LeafletMarker } from 'leaflet'
import { Marker, Popup, useMapEvents } from 'react-leaflet'
import type { Facility } from '../types'
import { useAnimatedNumber } from '../lib/motion'
import GridMap, { facilityLine, facilityMarker, hasPoint, headlineBoundsOptions, type GridLine, type GridMarker, type LatLon } from './GridMap'

export interface LatLonPoint {
  lat: number
  lon: number
}

interface Props {
  // The ZIP centroid.
  center: LatLonPoint
  // Where the hypothetical campus sits; null puts it on the centroid.
  pin: LatLonPoint | null
  acres: number
  facilities: Facility[]
  onPinMove: (pin: LatLonPoint) => void
  className?: string
}

const M2_PER_ACRE = 4046.8564224
const M_PER_DEG_LAT = 111_320
const MODELLED = '#b7791f'

// A square of `acres` centred on `at`, as four corners.
function square(at: LatLon, acres: number): LatLon[] {
  const half = Math.sqrt(Math.max(0, acres) * M2_PER_ACRE) / 2
  const dLat = half / M_PER_DEG_LAT
  const dLon = half / (M_PER_DEG_LAT * Math.max(0.01, Math.cos((at[0] * Math.PI) / 180)))
  const [lat, lon] = at
  return [
    [lat - dLat, lon - dLon],
    [lat - dLat, lon + dLon],
    [lat + dLat, lon + dLon],
    [lat + dLat, lon - dLon],
  ]
}

// The campus pin: a hazard-dashed plate in the modelled colour, so it never
// reads as a facility from the data.
const PIN_ICON = divIcon({
  className: '',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
  html: `<div style="width:22px;height:22px;box-sizing:border-box;background:${MODELLED};border:2px solid #15202b;box-shadow:0 0 0 2px #ffc300;cursor:grab"></div>`,
})

// A click on the map (not on a campus marker or line) places the campus
// there: the way to move it without dragging (WCAG 2.5.7).
function PlaceOnClick({ onPick }: { onPick: (p: LatLonPoint) => void }) {
  useMapEvents({
    click(e) {
      const el = e.originalEvent.target as Element | null
      if (el?.closest?.('.leaflet-interactive')) return
      onPick({ lat: e.latlng.lat, lon: e.latlng.lng })
    },
  })
  return null
}

// Arrow keys on the focused plate nudge it: about 200 m a press, 1 km with Shift.
const NUDGE: Record<string, [number, number]> = {
  ArrowUp: [1, 0],
  ArrowDown: [-1, 0],
  ArrowLeft: [0, -1],
  ArrowRight: [0, 1],
}

// The what-if map: the hypothetical campus as a square footprint on a
// draggable pin, with flowing lines from it to the ZIP centroid and to every
// campus already there. The footprint grows with the engine's acres.
export default function ScenarioMap({ center, pin, acres, facilities, onPinMove, className }: Props) {
  const centroid: LatLon = [center.lat, center.lon]
  const pinAt: LatLon = pin ? [pin.lat, pin.lon] : centroid

  // While dragging (and after a drop until the new pin arrives), draw from the
  // marker's own position so the footprint and lines follow the hand.
  const [dragAt, setDragAt] = useState<LatLon | null>(null)
  const [pinSeen, setPinSeen] = useState(pinAt)
  if (pinSeen[0] !== pinAt[0] || pinSeen[1] !== pinAt[1]) {
    setPinSeen(pinAt)
    setDragAt(null)
  }
  const at = dragAt ?? pinAt

  const side = useAnimatedNumber(acres, 600)
  const placed = facilities.filter(hasPoint)

  const lines: GridLine[] = [
    {
      key: 'to-centroid',
      from: at,
      to: centroid,
      pathOptions: { color: MODELLED, weight: 2.5, opacity: 0.85, lineCap: 'round', className: 'gridline gridline-under_construction' },
    },
    // The same dashed flow as the brief map, running out from the campus.
    ...placed.map((f, i) => ({ ...facilityLine(f, at, `to-${i}-${f.name}`), from: at, to: [f.lat, f.lon] as LatLon })),
  ]

  const markers: GridMarker[] = [
    ...placed.map((f, i) => facilityMarker(f, `${i}-${f.name}`)),
    {
      key: 'centroid',
      at: centroid,
      radius: 6,
      pathOptions: { color: '#15202b', weight: 2, fillColor: '#eef0f2', fillOpacity: 1 },
      popup: 'Centre of the ZIP code',
    },
  ]

  // The footprint's corners at the engine's full acreage are in the frame, so
  // a ZIP with no mapped campuses still frames the campus with some town
  // around it instead of zooming to the tile layer's maximum.
  const frame: LatLon[] = [centroid, pinAt, ...square(pinAt, Math.max(acres, 1)), ...placed.map((f): LatLon => [f.lat, f.lon])]

  const [atLat, atLon] = at
  const handlers = useMemo(
    () => ({
      drag(e: LeafletEvent) {
        const ll = (e.target as LeafletMarker).getLatLng()
        setDragAt([ll.lat, ll.lng])
      },
      dragend(e: LeafletEvent) {
        const ll = (e.target as LeafletMarker).getLatLng()
        setDragAt([ll.lat, ll.lng])
        onPinMove({ lat: ll.lat, lon: ll.lng })
      },
      keydown(e: LeafletKeyboardEvent) {
        const k = e.originalEvent
        const d = NUDGE[k.key]
        if (!d || k.altKey || k.ctrlKey || k.metaKey) return
        k.preventDefault()
        k.stopPropagation()
        const step = k.shiftKey ? 0.01 : 0.002
        const next: LatLon = [atLat + d[0] * step, atLon + d[1] * step]
        setDragAt(next)
        onPinMove({ lat: next[0], lon: next[1] })
      },
    }),
    [onPinMove, atLat, atLon],
  )

  return (
    <GridMap
      center={centroid}
      frame={frame}
      zoom={12}
      boundsOptions={{ ...headlineBoundsOptions(), maxZoom: 15 }}
      viewKey={`${center.lat},${center.lon}`}
      lines={lines}
      polygons={[
        {
          key: 'footprint',
          positions: square(at, side),
          pathOptions: { color: MODELLED, weight: 2, dashArray: '5 4', fillColor: MODELLED, fillOpacity: 0.28 },
          popup: (
            <>
              <strong>Hypothetical campus</strong><br />
              <span className="num">{Math.round(acres).toLocaleString('en-US')}</span> acres, modelled
            </>
          ),
        },
      ]}
      markers={markers}
      className={className}
    >
      <PlaceOnClick onPick={onPinMove} />
      <Marker
        position={at}
        icon={PIN_ICON}
        draggable
        keyboard
        title="Hypothetical campus: drag it, click the map, or use the arrow keys to move it"
        eventHandlers={handlers}
      >
        <Popup>Hypothetical campus. Drag it, click the map, or use the arrow keys to move it.</Popup>
      </Marker>
    </GridMap>
  )
}
