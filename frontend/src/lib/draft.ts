import type { Project, ProjectPatch, ProjectType } from '../types'

export interface Draft {
  name: string
  type: string
  voltage_kv: string
  location_ref: string
  lat: string
  lng: string
  start_date: string
  end_date: string
}

export function toDraft(p: Project): Draft {
  return {
    name: p.name ?? '',
    type: p.type ?? '',
    voltage_kv: p.voltage_kv?.toString() ?? '',
    location_ref: p.location_ref ?? '',
    lat: p.lat?.toString() ?? '',
    lng: p.lng?.toString() ?? '',
    start_date: p.start_date ?? '',
    end_date: p.end_date ?? '',
  }
}

/** Build a PATCH body containing only the fields the planner changed. */
export function diffDraft(p: Project, d: Draft): ProjectPatch {
  const orig = toDraft(p)
  const patch: ProjectPatch = {}
  const num = (s: string) => (s.trim() === '' ? null : Number(s))
  const str = (s: string) => (s.trim() === '' ? null : s.trim())
  if (d.name !== orig.name) patch.name = str(d.name)
  if (d.type !== orig.type) patch.type = (str(d.type) as ProjectType | null) ?? null
  if (d.voltage_kv !== orig.voltage_kv) patch.voltage_kv = num(d.voltage_kv)
  if (d.location_ref !== orig.location_ref) patch.location_ref = str(d.location_ref)
  if (d.lat !== orig.lat || d.lng !== orig.lng) {
    patch.lat = num(d.lat)
    patch.lng = num(d.lng)
  }
  if (d.start_date !== orig.start_date) patch.start_date = str(d.start_date)
  if (d.end_date !== orig.end_date) patch.end_date = str(d.end_date)
  return patch
}
