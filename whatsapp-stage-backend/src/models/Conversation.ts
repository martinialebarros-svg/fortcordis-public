export interface Conversation {
  id: string;
  wa_phone_number: string;
  wa_psid: string | null;
  status: string;
  subject: string | null;
  last_agent_id: string | null;
  last_activity_at: string;
  created_at: string;
  updated_at: string;
}
