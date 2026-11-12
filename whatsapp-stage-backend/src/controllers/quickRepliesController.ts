import { Request, Response } from "express";
import { query } from "../services/dbService";

interface QuickReply {
  id: string;
  title: string;
  body: string;
  category: string;
  shortcut: string;
  active: boolean;
  created_at: Date;
  updated_at: Date;
}

const COLUMNS = "id, title, body, category, shortcut, active, created_at, updated_at";
const EDITABLE = new Set(["title", "body", "category", "shortcut", "active"]);

function validateFields(body: unknown, partial: boolean): { fields: Record<string, unknown>; error?: string } {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { fields: {}, error: "Informe os campos da resposta rápida." };
  }
  const input = body as Record<string, unknown>;
  const fields: Record<string, unknown> = {};
  if (Object.keys(input).some((key) => !EDITABLE.has(key) && !(partial && key === "expected_updated_at"))) {
    return { fields, error: "A requisição contém campos não permitidos." };
  }
  for (const [key, maximum] of [["title", 100], ["body", 4096], ["category", 60], ["shortcut", 32]] as const) {
    if (!(key in input) && partial) continue;
    const value = key === "category" && !(key in input) ? "" : input[key];
    if (typeof value !== "string") return { fields, error: `O campo ${key} deve ser um texto.` };
    const normalized = key === "shortcut" ? value.trim().toLowerCase() : value.trim();
    if ((key !== "category" && !normalized) || normalized.length > maximum) {
      return { fields, error: `O campo ${key} deve ter ${key === "category" ? "até" : "entre 1 e"} ${maximum} caracteres.` };
    }
    if (key === "shortcut" && !/^[a-z0-9_-]{2,32}$/.test(normalized)) {
      return { fields, error: "O atalho deve ter de 2 a 32 letras, números, hífen ou sublinhado, sem a barra." };
    }
    fields[key] = normalized;
  }
  if ("active" in input) {
    if (typeof input.active !== "boolean") return { fields, error: "active deve ser verdadeiro ou falso." };
    fields.active = input.active;
  } else if (!partial) fields.active = true;
  if (!Object.keys(fields).length) return { fields, error: "Informe ao menos um campo para atualizar." };
  return { fields };
}

function handleUniqueConflict(error: unknown, res: Response): boolean {
  if ((error as { code?: string })?.code !== "23505") return false;
  res.status(409).json({
    code: "QUICK_REPLY_SHORTCUT_TAKEN",
    error: "Este atalho já existe, inclusive entre respostas inativas. Escolha outro ou edite a resposta existente."
  });
  return true;
}

export async function listQuickReplies(_req: Request, res: Response): Promise<void> {
  const result = await query<QuickReply>(`SELECT ${COLUMNS} FROM quick_replies ORDER BY active DESC, lower(category), lower(title), id`);
  res.json({ data: result.rows });
}

export async function createQuickReply(req: Request, res: Response): Promise<void> {
  const { fields, error } = validateFields(req.body, false);
  if (error) { res.status(422).json({ error }); return; }
  try {
    const result = await query<QuickReply>(
      `INSERT INTO quick_replies (title, body, category, shortcut, active)
       VALUES ($1, $2, $3, $4, $5) RETURNING ${COLUMNS}`,
      [fields.title, fields.body, fields.category, fields.shortcut, fields.active]
    );
    res.status(201).json({ data: result.rows[0] });
  } catch (failure) {
    if (!handleUniqueConflict(failure, res)) throw failure;
  }
}

export async function updateQuickReply(req: Request, res: Response): Promise<void> {
  const id = req.params.id;
  if (typeof id !== "string" || !/^[1-9]\d*$/.test(id) || id.length > 19 || BigInt(id) > 9223372036854775807n) {
    res.status(422).json({ error: "Identificador de resposta rápida inválido." }); return;
  }
  const { fields, error } = validateFields(req.body, true);
  if (error) { res.status(422).json({ error }); return; }
  const expected = req.body.expected_updated_at;
  if (typeof expected !== "string" || !/^\d{4}-\d{2}-\d{2}T/.test(expected) || !Number.isFinite(Date.parse(expected))) {
    res.status(422).json({ error: "Informe expected_updated_at para preservar as alterações da equipe." }); return;
  }
  const entries = Object.entries(fields);
  const values: unknown[] = entries.map(([, value]) => value);
  values.push(id, new Date(expected).toISOString());
  try {
    const result = await query<QuickReply>(
      `UPDATE quick_replies
       SET ${entries.map(([key], index) => `${key} = $${index + 1}`).join(", ")},
           updated_at = GREATEST(date_trunc('milliseconds', clock_timestamp()), updated_at + interval '1 millisecond')
       WHERE id = $${values.length - 1} AND updated_at = $${values.length}::timestamptz
       RETURNING ${COLUMNS}`,
      values
    );
    if (!result.rowCount) {
      const existing = await query<QuickReply>(`SELECT ${COLUMNS} FROM quick_replies WHERE id = $1`, [id]);
      if (!existing.rowCount) { res.status(404).json({ error: "Resposta rápida não encontrada." }); return; }
      res.status(409).json({
        code: "QUICK_REPLY_STALE",
        error: "Outra pessoa alterou esta resposta. Atualize o cadastro antes de salvar novamente.",
        data: existing.rows[0]
      });
      return;
    }
    res.json({ data: result.rows[0] });
  } catch (failure) {
    if (!handleUniqueConflict(failure, res)) throw failure;
  }
}
