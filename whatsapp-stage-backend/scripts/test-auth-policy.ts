import assert from "assert";
import { assertWhatsAppAuthPolicyOrThrow, buildAuthRuntimePolicy } from "../src/middleware/auth";

function run(): void {
  const productionDisabled = {
    NODE_ENV: "production",
    WHATSAPP_API_AUTH_ENABLED: "false"
  } as NodeJS.ProcessEnv;

  assert.throws(
    () => assertWhatsAppAuthPolicyOrThrow(productionDisabled),
    /WHATSAPP_API_AUTH_ENABLED=false/
  );

  const productionDefault = {
    NODE_ENV: "production"
  } as NodeJS.ProcessEnv;
  const policyProdDefault = buildAuthRuntimePolicy(productionDefault);
  assert.strictEqual(policyProdDefault.isProduction, true);
  assert.strictEqual(policyProdDefault.authEnabled, true);

  const stageDisabled = {
    APP_ENV: "stage",
    WHATSAPP_API_AUTH_ENABLED: "false"
  } as NodeJS.ProcessEnv;
  const policyStage = buildAuthRuntimePolicy(stageDisabled);
  assert.strictEqual(policyStage.isProduction, false);
  assert.strictEqual(policyStage.authEnabled, false);
  assert.doesNotThrow(() => assertWhatsAppAuthPolicyOrThrow(stageDisabled));

  const productionDisabledButEnforcementOff = {
    NODE_ENV: "production",
    WHATSAPP_API_AUTH_ENABLED: "false",
    WHATSAPP_ENFORCE_AUTH_IN_PRODUCTION: "false"
  } as NodeJS.ProcessEnv;
  assert.doesNotThrow(() => assertWhatsAppAuthPolicyOrThrow(productionDisabledButEnforcementOff));

  console.log("Auth policy test passed.");
}

run();
