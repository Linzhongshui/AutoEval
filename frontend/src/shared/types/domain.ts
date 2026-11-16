/** Hand-maintained domain shapes shared by more than one feature. */

export type Param = {
  adapter_input?: Record<string, unknown>;
  output: number;
  concurrency: number;
  temperature: number;
  top_p: number;
  scope: string;
};
