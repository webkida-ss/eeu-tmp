import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../contracts/openapi/openapi.yaml",
  output: "src/lib/api/generated",
});
