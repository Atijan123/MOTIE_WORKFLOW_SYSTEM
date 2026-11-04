// The API's response shapes that the screens use (see backend/app/**/schemas.py).

export type Me = {
  id: number;
  email: string | null;
  full_name: string;
  roles: string[];
  positions: string[];
  position_titles: string[];
};

export type Status = {
  code: string | null; // staff only
  name: string | null; // staff only
  label: string;
  explanation: string | null;
  is_final: boolean;
  editable: boolean;
};

export type Action = {
  to_status: string;
  name: string;
  on_behalf_of: string | null;
  requires_comment: boolean;
  requires_applicant_message: boolean;
  blocked_by: string[] | null;
  warnings: string[] | null;
};

export type Case = {
  id: number;
  reference: string | null;
  submitted_at: string | null;
  workflow: string;
  status: Status;
  created_by: number;
  entered_by: number | null;
  created_at: string;
  updated_at: string;
  applicant_message: string | null;
  available_actions: Action[];
  on_hold: boolean | null;
  applicant_emailed: boolean | null;
};

export type CaseSummary = {
  id: number;
  reference: string | null;
  workflow: string;
  service: string;
  status: Status;
  submitted_at: string | null;
  status_since: string;
  days_waiting: number;
  summary: string | null;
  applicant_name: string | null;
  applicant_message: string | null;
  available_actions: Action[];
};

export type TimelineEntry = { occurred_at: string; label: string; message: string | null };

export type Certificate = { number: string; issued_on: string | null; expires_on: string | null };

export type FacilityLetter = {
  case_id: number;
  reference: string | null;
  status: string | null;
  status_label: string;
  importer_name: string | null;
  importer_address: string | null;
  product: string | null;
  hs_code: string | null;
  hs_code_confirmed: string | null;
  quantity: string | null;
  unit: string | null;
  exporter_name: string | null;
  exporter_country: string | null;
  exporter_etls_approval_number: string | null;
  product_approval_numbers: string[];
  certificates_of_origin: Certificate[];
};

export type UploadedDocument = {
  id: number;
  type: string;
  filename: string;
  size_bytes: number;
  uploaded_at: string;
  original_seen_at: string | null;
  original_seen_by: number | null;
};

export type Requirement = {
  type: string;
  name: string;
  applies: boolean | null;
  missing: boolean;
  original_required: boolean;
  original_pending: boolean;
  documents: UploadedDocument[]; // newest first
};

export type ActingFor = {
  position: string;
  title: string;
  basis: string;
  absences: { person: string; starts_on: string; ends_on: string }[];
  delegation: { from_position: string; to_position: string; starts_on: string; ends_on: string } | null;
  in_absence: string | null; // an authorised signatory: "in the Director's absence"
};

export type HistoryEvent = {
  occurred_at: string;
  actor_user_id: number | null;
  actor_name: string | null;
  actor_title: string | null;
  acting_for: ActingFor | null;
  action: string;
  details: Record<string, unknown>;
};

export type ActingNow = {
  position: string;
  title: string;
  basis: string;
  workflows: string[] | null;
  absences: { person: string; starts_on: string; ends_on: string }[];
  delegation_starts_on: string | null;
  delegation_ends_on: string | null;
  in_absence: string | null; // basis "signatory"
};

// S11: absences and delegations (backend/app/core/workflow/schemas.py).
export type CoverForPost = {
  position: string;
  title: string;
  delegations: { id: number; to_position: string; to_title: string; workflow: string | null; starts_on: string; ends_on: string }[];
  // `signatories` instead of `line` where the service uses the authorised signatories list for this post.
  succession: { workflow: string; line: { position: string; title: string; holders: string[] }[]; signatories: string[] | null }[];
};

export type AbsenceView = {
  id: number;
  person: string;
  posts: string[];
  starts_on: string;
  ends_on: string;
  reason: string | null;
  may_cancel: boolean;
  recorded_by: string;
  recorded_by_self: boolean;
  // Worked out for the absence's first day (or today, if it has started).
  // For "signatory", position and title are the list's, and holders the people on it at work.
  who_acts: {
    position: string;
    title: string;
    holders: string[];
    basis: "delegation" | "succession" | "signatory" | "same_post";
    workflows: string[] | null;
  }[];
};

export type Choices = {
  posts: { code: string; title: string; holders: { user_id: number; name: string }[] }[];
  workflows: { code: string; name: string }[];
};

// S12: authorised signatories (backend/app/core/workflow/signatories.py).
export type Signatory = {
  id: number;
  user_id: number;
  name: string;
  posts: string[];
  added_at: string;
  added_by: string;
  removed_at: string | null;
  removed_by: string | null;
};

export type SignatoryList = {
  code: string;
  name: string;
  absence_wording: string;
  used_for: { workflow: string; workflow_name: string; position: string; position_title: string }[];
  current: Signatory[];
  past: Signatory[];
};

export type SignatoryCandidate = { user_id: number; name: string; posts: string[] };
