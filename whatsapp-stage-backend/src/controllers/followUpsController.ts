import type {} from "../types/express";
import { Request, Response } from "express";
import { query, withTransaction } from "../services/dbService";

export const FOLLOW_UP_JOIN = `LEFT JOIN conversation_follow_ups follow_up ON follow_up.conversation_id = c.id`;
export const FOLLOW_UP_ACTIVE = "follow_up.status = 'pending'";
export const FOLLOW_UP_DUE = `(${FOLLOW_UP_ACTIVE} AND follow_up.due_at <= now())`;
export const FOLLOW_UP_READY = `(${FOLLOW_UP_ACTIVE} AND (follow_up.due_at <= now() OR follow_up.inbound_received_at IS NOT NULL))`;
export const FOLLOW_UP_TODAY = `(${FOLLOW_UP_ACTIVE} AND follow_up.due_at > now() AND follow_up.due_at < (date_trunc('day', now() AT TIME ZONE 'America/Fortaleza') + interval '1 day') AT TIME ZONE 'America/Fortaleza')`;
export const FOLLOW_UP_JSON = `CASE WHEN follow_up.conversation_id IS NOT NULL THEN jsonb_build_object(
  'due_at', follow_up.due_at, 'note', follow_up.note, 'agent_id', follow_up.agent_id::text,
  'agent_name', (SELECT name FROM agents WHERE id = follow_up.agent_id),
  'status', follow_up.status, 'revision', follow_up.revision,
  'inbound_received_at', follow_up.inbound_received_at, 'updated_at', follow_up.updated_at
) ELSE NULL END`;

export function validId(value: unknown): value is string {
  return typeof value === "string" && /^[1-9]\d{0,18}$/.test(value) && BigInt(value) <= 9223372036854775807n;
}

function validTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
      || !Number.isFinite(Date.parse(value))) return false;
  // Date.parse normalizes dates such as February 31; PostgreSQL rejects them.
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  return month >= 1 && month <= 12 && day >= 1 && day <= new Date(Date.UTC(year, month, 0)).getUTCDate();
}

export async function getFollowUp(req: Request, res: Response): Promise<void> {
  if (!validId(req.params.id)) { res.status(422).json({ error: "Conversa inválida." }); return; }
  const result = await query(`SELECT ${FOLLOW_UP_JSON} AS data FROM conversations c ${FOLLOW_UP_JOIN} WHERE c.id = $1`, [req.params.id]);
  if (!result.rowCount) { res.status(404).json({ error: "Conversa não encontrada." }); return; }
  res.json(result.rows[0]);
}

export async function saveFollowUp(req: Request, res: Response): Promise<void> {
  const { action, expected_revision: revision, due_at: dueAt, note, agent_id: agentId } = req.body ?? {};
  if (!validId(req.params.id) || !["schedule", "complete", "cancel"].includes(action)
      || !Number.isInteger(revision) || revision < 0 || revision >= 2147483647) {
    res.status(422).json({ error: "Ação ou versão do retorno inválida." }); return;
  }
  if (action === "schedule" && (!validTimestamp(dueAt) || Date.parse(dueAt) <= Date.now()
      || Date.parse(dueAt) > Date.now() + 366 * 86400000
      || typeof note !== "string" || !note.trim() || note.trim().length > 1000 || !validId(agentId))) {
    res.status(422).json({ error: "Informe responsável ativo, nota de até 1000 caracteres e horário futuro em até um ano." }); return;
  }
  const result = await withTransaction(async (client) => {
    const conversation = await client.query("SELECT id FROM conversations WHERE id = $1 FOR UPDATE", [req.params.id]);
    if (!conversation.rowCount) return { status: 404, error: "Conversa não encontrada." };
    const current = (await client.query("SELECT * FROM conversation_follow_ups WHERE conversation_id = $1", [req.params.id])).rows[0];
    if ((current?.revision ?? 0) !== revision) return { status: 409, error: "O retorno mudou ou recebeu nova mensagem. Atualize e revise antes de salvar.", code: "FOLLOW_UP_CHANGED" };
    if (action === "schedule") {
      if (Date.parse(dueAt) <= Date.now()) return { status: 422, error: "O horário já passou. Escolha um horário futuro." };
      const agent = await client.query("SELECT id FROM agents WHERE id = $1 AND active = TRUE FOR SHARE", [agentId]);
      if (!agent.rowCount) return { status: 422, error: "Selecione um responsável ativo." };
      await client.query(`INSERT INTO conversation_follow_ups (conversation_id, due_at, note, agent_id)
        VALUES ($1, $2, $3, $4) ON CONFLICT (conversation_id) DO UPDATE
        SET due_at = EXCLUDED.due_at, note = EXCLUDED.note, agent_id = EXCLUDED.agent_id,
          status = 'pending', inbound_received_at = NULL, revision = conversation_follow_ups.revision + 1, updated_at = now()`,
        [req.params.id, dueAt, note.trim(), agentId]);
    } else {
      if (!current || current.status !== "pending") return { status: 409, error: "Não há retorno pendente. Atualize o retorno.", code: "FOLLOW_UP_CHANGED" };
      await client.query(`UPDATE conversation_follow_ups SET status = $2, revision = revision + 1, updated_at = now() WHERE conversation_id = $1`,
        [req.params.id, action === "complete" ? "completed" : "cancelled"]);
    }
    await client.query(`INSERT INTO audit_logs (conversation_id, action, payload) VALUES ($1, 'conversation_follow_up_changed', $2::jsonb)`,
      [req.params.id, JSON.stringify({ action, revision: revision + 1, actor_user_id: req.authUser?.id ?? null, auth_source: req.authUser?.authSource ?? null })]);
    const row = await client.query(`SELECT ${FOLLOW_UP_JSON} AS data FROM conversations c ${FOLLOW_UP_JOIN} WHERE c.id = $1`, [req.params.id]);
    return { status: 200, data: row.rows[0].data };
  });
  res.status(result.status).json(result);
}
