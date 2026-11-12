import assert from "assert";
import { buildPostgresConfig } from "../src/config/database";

const secureUrl = "postgresql://user:password@db.example.test:5432/fortcordis?sslmode=require";

const defaultConfig = buildPostgresConfig(secureUrl, undefined, "");
assert.equal(defaultConfig.connectionString, secureUrl);
assert.equal(defaultConfig.ssl, undefined);
assert.equal(defaultConfig.max, undefined);

const verifiedConfig = buildPostgresConfig(secureUrl, "true", "");
assert.equal(verifiedConfig.connectionString, secureUrl);
assert.equal(verifiedConfig.ssl, undefined);
assert.equal(verifiedConfig.max, undefined);

const selfSignedConfig = buildPostgresConfig(secureUrl, "false", "");
assert.equal(
  new URL(String(selfSignedConfig.connectionString)).searchParams.has("sslmode"),
  false
);
assert.deepEqual(selfSignedConfig.ssl, { rejectUnauthorized: false });

assert.throws(
  () => buildPostgresConfig(secureUrl, "invalid", ""),
  /must be true or false/
);
assert.throws(
  () =>
    buildPostgresConfig(
      "postgresql://user:password@db.example.test:5432/fortcordis?sslmode=disable",
      "false",
      ""
    ),
  /requires DATABASE_URL with sslmode=require/
);
assert.throws(
  () =>
    buildPostgresConfig(
      `${secureUrl}&sslrootcert=%2Fetc%2Fssl%2Fcustom-ca.pem`,
      "false",
      ""
    ),
  /cannot override explicit database certificates/
);

for (const poolMax of ["1", "2", "10", " 2 "]) {
  for (const tlsSetting of ["", "true", "false"]) {
    const config = buildPostgresConfig(secureUrl, tlsSetting, poolMax);
    assert.equal(config.max, Number(poolMax));
    if (tlsSetting === "false") {
      assert.deepEqual(config.ssl, { rejectUnauthorized: false });
    } else {
      assert.equal(config.connectionString, secureUrl);
      assert.equal(config.ssl, undefined);
    }
  }
}

assert.equal(buildPostgresConfig(secureUrl, "true", "   ").max, undefined);
for (const invalidPoolMax of ["0", "11", "-1", "2.5", "NaN", "Infinity", "1e0", "2abc"]) {
  assert.throws(
    () => buildPostgresConfig(secureUrl, "true", invalidPoolMax),
    /WHATSAPP_DATABASE_POOL_MAX must be an integer between 1 and 10/
  );
}

const originalPoolMax = process.env.WHATSAPP_DATABASE_POOL_MAX;
try {
  delete process.env.WHATSAPP_DATABASE_POOL_MAX;
  assert.equal(buildPostgresConfig(secureUrl, "true").max, undefined);
  process.env.WHATSAPP_DATABASE_POOL_MAX = "2";
  assert.equal(buildPostgresConfig(secureUrl, "true").max, 2);
} finally {
  if (originalPoolMax === undefined) {
    delete process.env.WHATSAPP_DATABASE_POOL_MAX;
  } else {
    process.env.WHATSAPP_DATABASE_POOL_MAX = originalPoolMax;
  }
}

console.log("Database TLS and pool configuration checks passed.");
