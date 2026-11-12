export interface AuditLog {
  id: string;
  conversation_id: string | null;
  agent_id: string | null;
  action: string;
  payload: unknown;
  created_at: string;
}
