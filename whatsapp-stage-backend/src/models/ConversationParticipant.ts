export interface ConversationParticipant {
  id: string;
  conversation_id: string;
  agent_id: string;
  joined_at: string;
  left_at: string | null;
}
