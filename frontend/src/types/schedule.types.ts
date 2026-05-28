import type { Contact } from './contact.types'
import type { ContactGroup } from './group.types'

export type ScheduleStatus =
  | 'pending'
  | 'queued'
  | 'processing'
  | 'sent'
  | 'retrying'
  | 'delivered'
  | 'failed'
  | 'cancelled'

export const TRANSIENT_STATUSES: ReadonlySet<ScheduleStatus> = new Set([
  'pending', 'queued', 'processing', 'retrying',
])

export function hasTransientSchedule(schedules: Array<{ status: ScheduleStatus }>): boolean {
  return schedules.some(s => TRANSIENT_STATUSES.has(s.status))
}

export type Schedule = {
  id: number
  name?: string | null
  template?: number | null
  text?: string | null
  message_parts: number
  contact?: number | null
  contact_detail?: Contact | null
  phone?: string | null
  group?: number | null
  group_detail?: ContactGroup | null
  parent?: number | null
  recipient_count?: number
  scheduled_time: string
  sent_time?: string | null
  status: ScheduleStatus
  error?: string | null
  format?: string | null
  media_url?: string | null
  subject?: string | null
  alphanumeric_sender?: string | null
  provider_message_id?: string | null
  retry_count?: number
  max_retries?: number
  next_retry_at?: string | null
  failure_category?: string | null
  delivered_time?: string | null
  created_at: string
  updated_at: string
}

export type CreateSchedule = {
  template_id?: number | null
  text?: string
  contact_id?: number | null
  phone: string
  scheduled_time: string
  format?: string
  media_url?: string
  subject?: string
  alphanumeric_sender?: string
}

export type UpdateSchedule = {
  id: number
  contact_id?: number
  scheduled_time?: string
  template_id?: number
  text?: string
}
