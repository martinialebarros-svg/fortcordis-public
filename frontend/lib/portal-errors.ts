type PortalValidationIssue = {
  type?: unknown;
  loc?: unknown;
  ctx?: unknown;
};

function isPasswordValidationIssue(issue: PortalValidationIssue): boolean {
  if (!Array.isArray(issue.loc)) {
    return false;
  }

  const field = issue.loc.at(-1);
  return field === "password" || field === "password_confirmation";
}

function validationErrorMessage(detail: unknown): string | null {
  if (!Array.isArray(detail)) {
    return null;
  }

  const issues = detail.filter(
    (issue): issue is PortalValidationIssue => Boolean(issue) && typeof issue === "object",
  );
  const passwordIssue = issues.find(isPasswordValidationIssue);
  if (passwordIssue) {
    const minLength =
      passwordIssue.ctx && typeof passwordIssue.ctx === "object" && "min_length" in passwordIssue.ctx
        ? passwordIssue.ctx.min_length
        : null;
    if (typeof minLength === "number") {
      return `A senha deve ter pelo menos ${minLength} caracteres.`;
    }
    return "Revise a senha informada e tente novamente.";
  }

  return issues.length > 0 ? "Revise os dados informados e tente novamente." : null;
}

export function portalErrorMessageFromBody(body: string, fallback: string): string {
  const text = body.trim();
  if (!text) {
    return fallback;
  }

  try {
    const parsed = JSON.parse(text) as { detail?: unknown; message?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail.trim();
    }
    if (typeof parsed.message === "string" && parsed.message.trim()) {
      return parsed.message.trim();
    }

    return validationErrorMessage(parsed.detail) || fallback;
  } catch {
    return text;
  }
}
