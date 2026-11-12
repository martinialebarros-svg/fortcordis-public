export interface Message {
  id: string;
  conversation_id: string;
  wa_message_id: string | null;
  from_me: boolean;
  body: string | null;
  type: string;
  metadata: unknown;
  status: string;
  created_at: string;
}
