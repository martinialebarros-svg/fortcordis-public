import { Request, Response } from "express";
import { query } from "../services/dbService";

export async function listAgents(_req: Request, res: Response): Promise<void> {
  const result = await query(
    `
      SELECT id, name, email, role, active, created_at
      FROM agents
      ORDER BY id ASC
    `
  );

  res.json({ data: result.rows });
}

export async function createAgent(req: Request, res: Response): Promise<void> {
  const name = req.body?.name ?? null;
  const email = req.body?.email;
  const role = req.body?.role ?? "agent";
  const active = req.body?.active ?? true;

  if (typeof email !== "string" || email.trim().length === 0) {
    res.status(400).json({ error: "email is required" });
    return;
  }

  const result = await query(
    `
      INSERT INTO agents (name, email, role, active, created_at)
      VALUES ($1, $2, $3, $4, now())
      RETURNING id, name, email, role, active, created_at
    `,
    [
      typeof name === "string" ? name.trim() : null,
      email.trim().toLowerCase(),
      typeof role === "string" && role.trim().length > 0 ? role.trim() : "agent",
      Boolean(active)
    ]
  );

  res.status(201).json(result.rows[0]);
}

export async function updateAgent(req: Request, res: Response): Promise<void> {
  const agentId = req.params.id;
  const body = req.body ?? {};
  const fields: string[] = [];
  const values: unknown[] = [];

  if ("name" in body) {
    const name = body.name;
    if (name !== null && typeof name !== "string") {
      res.status(400).json({ error: "name must be a string or null" });
      return;
    }
    values.push(typeof name === "string" ? name.trim() || null : null);
    fields.push(`name = $${values.length}`);
  }

  if ("email" in body) {
    const email = body.email;
    if (typeof email !== "string" || email.trim().length === 0) {
      res.status(400).json({ error: "email must be a non-empty string" });
      return;
    }
    values.push(email.trim().toLowerCase());
    fields.push(`email = $${values.length}`);
  }

  if ("role" in body) {
    const role = body.role;
    if (typeof role !== "string" || role.trim().length === 0) {
      res.status(400).json({ error: "role must be a non-empty string" });
      return;
    }
    values.push(role.trim());
    fields.push(`role = $${values.length}`);
  }

  if ("active" in body) {
    values.push(Boolean(body.active));
    fields.push(`active = $${values.length}`);
  }

  if (fields.length === 0) {
    res.status(400).json({ error: "No updatable fields provided" });
    return;
  }

  values.push(agentId);

  const result = await query(
    `
      UPDATE agents
      SET ${fields.join(", ")}
      WHERE id = $${values.length}
      RETURNING id, name, email, role, active, created_at
    `,
    values
  );

  if (result.rowCount === 0) {
    res.status(404).json({ error: "Agent not found" });
    return;
  }

  res.status(200).json(result.rows[0]);
}
