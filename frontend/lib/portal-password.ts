export const PORTAL_PASSWORD_MIN_LENGTH = 8;

export function validatePortalPasswordConfirmation(
  password: string,
  passwordConfirmation: string,
): string | null {
  if (
    password.length < PORTAL_PASSWORD_MIN_LENGTH ||
    passwordConfirmation.length < PORTAL_PASSWORD_MIN_LENGTH
  ) {
    return `A senha deve ter pelo menos ${PORTAL_PASSWORD_MIN_LENGTH} caracteres.`;
  }
  if (password !== passwordConfirmation) {
    return "A confirmação da senha não confere.";
  }
  return null;
}
