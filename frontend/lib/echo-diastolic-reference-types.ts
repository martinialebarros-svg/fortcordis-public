/** Statistical descriptions are distinct from individual reference intervals. */
export type EchoDiastolicReference = {
  text: string;
  source: string;
  doi: string;
  statistic: string;
  note: string;
  bibliography: string;
  kind: "reference_interval" | "descriptive" | "uninterpretable" | "unconfirmed";
  min?: number;
  max?: number;
};
