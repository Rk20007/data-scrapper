export type Grade = "HOT" | "HIGH" | "WARM" | "LOW";

export interface CompanyBrief {
  id: number;
  name: string;
  domain: string | null;
  website: string | null;
  cluster: string | null;
  size_tier: string;
  is_quality: boolean | null;
  grade: Grade;
  score: number;
}

export interface Company extends CompanyBrief {
  industry: string | null;
  employee_estimate: number | null;
  quality_reason: string | null;
  monitor_website: boolean;
  source: string;
  notes: string | null;
  last_monitored_at: string | null;
  last_enriched_at: string | null;
  created_at: string;
  project_count?: number;
  contact_count?: number;
  email_contact_count?: number;
}

export interface Contact {
  id: number;
  company_id: number;
  name: string | null;
  title: string | null;
  role_category: string;
  email: string | null;
  email_status: string;
  email_source_url: string | null;
  phone: string | null;
  profile_url: string | null;
  source_url: string | null;
  is_generic: boolean;
  confidence: number;
  do_not_contact: boolean;
}

export interface Evidence {
  id: number;
  url: string;
  source_kind: string;
  title: string | null;
  quote: string | null;
  published_at: string | null;
  created_at: string;
}

export interface Email {
  id: number;
  outreach_id: number;
  step: number;
  to_email: string;
  subject: string;
  status: string;
  generated_by: string;
  scheduled_at: string | null;
  approved_at: string | null;
  sent_at: string | null;
  error: string | null;
  attempts: number;
  created_at: string;
  body_text?: string;
  facts_used?: string[];
  project_id?: number;
  project_title?: string;
  company_name?: string | null;
  contact_name?: string | null;
  contact_title?: string | null;
  grade?: Grade;
  score?: number;
}

export interface Outreach {
  id: number;
  project_id: number;
  status: string;
  current_step: number;
  next_action_at: string | null;
  stopped_reason: string | null;
  contact: Contact;
  messages: Email[];
  created_at: string;
}

export interface LeadRow {
  id: number;
  title: string;
  kind: string;
  project_type: string;
  stage: string;
  cluster: string | null;
  location_text: string | null;
  investment_inr_crore: number | null;
  score: number;
  grade: Grade;
  lead_status: string;
  is_current: boolean;
  is_relevant: boolean;
  ai_confidence: number;
  first_seen_at: string;
  last_evidence_at: string | null;
  tender_closing_at: string | null;
  tender_authority: string | null;
  company: CompanyBrief | null;
  evidence_count: number;
  top_evidence: Evidence | null;
  contact: Contact | null;
  email_status: string | null;
  outreach_status: string | null;
}

export interface LeadDetail extends LeadRow {
  summary: string | null;
  ai_reason: string | null;
  key_facts: string[];
  area_sqft: number | null;
  timeline: string | null;
  announcement_date: string | null;
  score_breakdown: Record<string, number | string> | null;
  tender_ref: string | null;
  tender_value_inr: number | null;
  notes: string | null;
  evidence: Evidence[];
  contacts: Contact[];
  outreaches: Outreach[];
}

export interface Source {
  id: number;
  name: string;
  kind: string;
  url: string | null;
  config: Record<string, unknown>;
  enabled: boolean;
  interval_minutes: number;
  last_run_at: string | null;
  last_success_at: string | null;
  last_status: string | null;
  last_error: string | null;
  items_last_run: number;
}

export interface Page<T> {
  total: number;
  items: T[];
}
