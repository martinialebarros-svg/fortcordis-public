import { Request, Response } from "express";
import { query, withTransaction } from "../services/dbService";

const SMOKE_MESSAGE_ID_PATTERN = "wamid.smoke.%";
const SMOKE_MESSAGE_ID_SUBSTRING_PATTERN = "%wamid.smoke.%";
const SMOKE_AGENT_EMAIL_PATTERN = "agent.smoke.%@example.com";

async function findSmokeConversationIds(): Promise<string[]> {
  const result = await query<{ id: string }>(
    `SELECT DISTINCT conversation_id AS id FROM messages WHERE wa_message_id LIKE $1`,
    [SMOKE_MESSAGE_ID_PATTERN]
  );
  return result.rows.map((row) => row.id);
}

async function findSmokeAgentIds(): Promise<string[]> {
  const result = await query<{ id: string }>(
    `SELECT id FROM agents WHERE email LIKE $1`,
    [SMOKE_AGENT_EMAIL_PATTERN]
  );
  return result.rows.map((row) => row.id);
}

export async function previewSmokeCleanup(_req: Request, res: Response): Promise<void> {
  const conversationIds = await findSmokeConversationIds();
  const agentIds = await findSmokeAgentIds();

  const [messagesCount, messageStatusEventsCount, webhookEventsCount, auditLogsCount, sampleAgents] =
    await Promise.all([
      query<{ count: string }>(
        `SELECT COUNT(*)::text AS count FROM messages WHERE wa_message_id LIKE $1`,
        [SMOKE_MESSAGE_ID_PATTERN]
      ),
      query<{ count: string }>(
        `SELECT COUNT(*)::text AS count FROM message_status_events WHERE wa_message_id LIKE $1`,
        [SMOKE_MESSAGE_ID_PATTERN]
      ),
      query<{ count: string }>(
        `SELECT COUNT(*)::text AS count FROM webhook_events WHERE raw_body LIKE $1 OR raw_body LIKE '%WABA_SMOKE%'`,
        [SMOKE_MESSAGE_ID_SUBSTRING_PATTERN]
      ),
      query<{ count: string }>(
        `SELECT COUNT(*)::text AS count FROM audit_logs WHERE conversation_id = ANY($1::bigint[]) OR agent_id = ANY($2::bigint[])`,
        [conversationIds, agentIds]
      ),
      query<{ email: string }>(`SELECT email FROM agents WHERE id = ANY($1::bigint[]) LIMIT 10`, [agentIds]),
    ]);

  res.json({
    would_delete: {
      conversations: conversationIds.length,
      agents: agentIds.length,
      messages: Number(messagesCount.rows[0]?.count ?? 0),
      message_status_events: Number(messageStatusEventsCount.rows[0]?.count ?? 0),
      webhook_events: Number(webhookEventsCount.rows[0]?.count ?? 0),
      audit_logs: Number(auditLogsCount.rows[0]?.count ?? 0),
    },
    sample_conversation_ids: conversationIds.slice(0, 10),
    sample_agent_emails: sampleAgents.rows.map((row) => row.email),
  });
}

export async function executeSmokeCleanup(req: Request, res: Response): Promise<void> {
  const papeis = req.authUser?.papeis ?? [];
  if (!papeis.includes("admin")) {
    res.status(403).json({ error: "Apenas administradores podem executar a limpeza de dados de smoke test." });
    return;
  }

  const deleted = await withTransaction(async (client) => {
    const conversationIds = (
      await client.query<{ id: string }>(
        `SELECT DISTINCT conversation_id AS id FROM messages WHERE wa_message_id LIKE $1`,
        [SMOKE_MESSAGE_ID_PATTERN]
      )
    ).rows.map((row) => row.id);
    const agentIds = (
      await client.query<{ id: string }>(`SELECT id FROM agents WHERE email LIKE $1`, [SMOKE_AGENT_EMAIL_PATTERN])
    ).rows.map((row) => row.id);

    const messageStatusEvents = await client.query(
      `DELETE FROM message_status_events WHERE wa_message_id LIKE $1`,
      [SMOKE_MESSAGE_ID_PATTERN]
    );
    const webhookEvents = await client.query(
      `DELETE FROM webhook_events WHERE raw_body LIKE $1 OR raw_body LIKE '%WABA_SMOKE%'`,
      [SMOKE_MESSAGE_ID_SUBSTRING_PATTERN]
    );
    const auditLogs = await client.query(
      `DELETE FROM audit_logs WHERE conversation_id = ANY($1::bigint[]) OR agent_id = ANY($2::bigint[])`,
      [conversationIds, agentIds]
    );
    // messages e conversation_participants tem ON DELETE CASCADE a partir de conversations.
    const conversations = await client.query(`DELETE FROM conversations WHERE id = ANY($1::bigint[])`, [
      conversationIds,
    ]);
    const agents = await client.query(`DELETE FROM agents WHERE id = ANY($1::bigint[])`, [agentIds]);

    return {
      conversations: conversations.rowCount,
      agents: agents.rowCount,
      message_status_events: messageStatusEvents.rowCount,
      webhook_events: webhookEvents.rowCount,
      audit_logs: auditLogs.rowCount,
    };
  });

  res.json({ deleted });
}
