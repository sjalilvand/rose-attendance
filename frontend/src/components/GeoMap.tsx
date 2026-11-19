/** نقشهٔ انتخاب مرکز شعبه — Leaflet با کاشی OpenStreetMap.
 * کلیک روی نقشه یا جابه‌جایی نشان، مرکز را می‌دهد؛ دایرهٔ ژئوفنس شعاع مجاز را می‌کشد. */
import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'

const DefaultIcon = L.icon({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
})
L.Marker.prototype.options.icon = DefaultIcon

const TEHRAN: L.LatLngExpression = [35.6892, 51.389]

interface Props {
  lat: number | null
  lng: number | null
  radiusM: number
  onPick: (lat: number, lng: number) => void
}

export default function GeoMap({ lat, lng, radiusM, onPick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const markerRef = useRef<L.Marker | null>(null)
  const circleRef = useRef<L.Circle | null>(null)
  const onPickRef = useRef(onPick)
  useEffect(() => {
    onPickRef.current = onPick
  })

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = L.map(containerRef.current, { scrollWheelZoom: true }).setView(
      lat != null && lng != null ? [lat, lng] : TEHRAN,
      lat != null ? 16 : 10,
    )
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap',
    }).addTo(map)
    map.on('click', (e: L.LeafletMouseEvent) => onPickRef.current(e.latlng.lat, e.latlng.lng))
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
      markerRef.current = null
      circleRef.current = null
    }
    // فقط یک بار؛ به‌روزرسانی‌ها در افکت بعدی
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (lat == null || lng == null) {
      markerRef.current?.remove()
      markerRef.current = null
      circleRef.current?.remove()
      circleRef.current = null
      return
    }
    const ll: L.LatLngExpression = [lat, lng]
    if (!markerRef.current) {
      const marker = L.marker(ll, { draggable: true }).addTo(map)
      marker.on('dragend', () => {
        const p = marker.getLatLng()
        onPickRef.current(p.lat, p.lng)
      })
      markerRef.current = marker
    } else {
      markerRef.current.setLatLng(ll)
    }
    if (!circleRef.current) {
      circleRef.current = L.circle(ll, { radius: radiusM, color: '#e11d48', fillOpacity: 0.08 }).addTo(map)
    } else {
      circleRef.current.setLatLng(ll).setRadius(radiusM)
    }
    map.setView(ll, Math.max(map.getZoom(), 16))
  }, [lat, lng, radiusM])

  return <div ref={containerRef} className="geo-map" dir="ltr" />
}
