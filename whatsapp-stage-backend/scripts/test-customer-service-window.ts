import assert from "node:assert/strict";
import {
  CUSTOMER_SERVICE_WINDOW_HOURS,
  describeCustomerServiceWindow
} from "../src/services/customerServiceWindow";

assert.equal(CUSTOMER_SERVICE_WINDOW_HOURS, 24);

const inboundAt = "2026-08-16T12:00:00.000Z";

assert.deepEqual(
  describeCustomerServiceWindow(inboundAt, new Date("2026-08-17T11:59:59.999Z")),
  {
    last_inbound_at: inboundAt,
    expires_at: "2026-08-17T12:00:00.000Z",
    is_open: true
  }
);

assert.equal(
  describeCustomerServiceWindow(inboundAt, new Date("2026-08-17T12:00:00.000Z")).is_open,
  false,
  "the window must close exactly 24 hours after the last inbound message"
);

assert.deepEqual(describeCustomerServiceWindow(null), {
  last_inbound_at: null,
  expires_at: null,
  is_open: false
});

assert.deepEqual(describeCustomerServiceWindow("invalid-date"), {
  last_inbound_at: null,
  expires_at: null,
  is_open: false
});

console.log("Customer service window tests passed.");
