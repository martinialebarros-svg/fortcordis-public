export interface Agent {
  id: string;
  name: string | null;
  email: string | null;
  role: string;
  active: boolean;
  created_at: string;
}
