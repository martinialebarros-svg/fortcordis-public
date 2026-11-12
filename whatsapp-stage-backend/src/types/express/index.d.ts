import "express";

declare global {
  namespace Express {
    interface AuthenticatedRequestUser {
      id: number | null;
      email: string | null;
      nome: string | null;
      papeis: string[];
      authSource: "core_api" | "internal_token";
    }

    interface Request {
      rawBody?: Buffer;
      authUser?: AuthenticatedRequestUser;
    }
  }
}

export {};
