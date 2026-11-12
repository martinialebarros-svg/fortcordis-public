export interface WebhookContact {
  profile?: { name?: string };
  wa_id?: string;
  [key: string]: unknown;
}

export interface WebhookMessage {
  from?: string;
  id?: string;
  timestamp?: string;
  type?: string;
  text?: { body?: string };
  button?: { text?: string; payload?: string };
  interactive?: Record<string, unknown>;
  image?: { caption?: string };
  audio?: Record<string, unknown>;
  video?: { caption?: string };
  document?: { filename?: string };
  reaction?: { message_id?: string; emoji?: string };
  [key: string]: unknown;
}

export interface WebhookStatusEvent {
  id?: string;
  status?: string;
  timestamp?: string;
  recipient_id?: string;
  [key: string]: unknown;
}

export interface WebhookChangeValue {
  messaging_product?: string;
  metadata?: {
    display_phone_number?: string;
    phone_number_id?: string;
    [key: string]: unknown;
  };
  contacts?: WebhookContact[];
  messages?: WebhookMessage[];
  statuses?: WebhookStatusEvent[];
  [key: string]: unknown;
}

export interface WebhookPayload {
  object?: string;
  entry?: Array<{
    id?: string;
    changes?: Array<{
      field?: string;
      value?: WebhookChangeValue;
      [key: string]: unknown;
    }>;
    [key: string]: unknown;
  }>;
  [key: string]: unknown;
}
