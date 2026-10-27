import { Circle, CircleMarker, MapContainer, Polygon, Popup, TileLayer } from 'react-leaflet'
import type { Brief } from '../types'

const FIVE_MILES_M = 8047

// The five-mile ring is the product's unit of concern. Everything else on the
// map is a dot or an outline, in the status colours.
export default function MapView({ brief }: { brief: Brief }) {
  const { lat, lon } = brief.address
  const facilities = brief.sections.on_your_grid.facilities ?? []
  const construction = brief.sections.coming.construction ?? []

  return (
    <MapContainer
      center={[lat, lon]}
      zoom={12}
      scrollWheelZoom={false}
      className="h-[360px] w-full sm:h-[440px]"
      attributionControl
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        className="basemap"
      />

      <Circle center={[lat, lon]} radius={FIVE_MILES_M} pathOptions={{ color: '#15202b', weight: 1.5, dashArray: '6 6', fill: false }} />
      <CircleMarker center={[lat, lon]} radius={7} pathOptions={{ color: '#15202b', fillColor: '#ffc300', fillOpacity: 1, weight: 2 }}>
        <Popup>Your address</Popup>
      </CircleMarker>

      {facilities.filter((f) => f.lat && f.lon).map((f) => (
        <CircleMarker
          key={f.name}
          center={[f.lat!, f.lon!]}
          radius={f.status === 'live' ? 6 : 5}
          pathOptions={{
            color: '#15202b',
            weight: 1,
            fillColor: f.status === 'live' ? '#15202b' : f.status === 'under_construction' ? '#b7791f' : '#3b5b8c',
            fillOpacity: f.status === 'announced' ? 0.5 : 0.95,
          }}
        >
          <Popup>
            <strong>{f.name}</strong><br />
            {f.operator}{f.codename ? ` (filed as ${f.codename})` : ''}<br />
            {f.status.replace('_', ' ')}, {f.distance_km.toFixed(1)} km
          </Popup>
        </CircleMarker>
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
    </MapContainer>
  )
}
