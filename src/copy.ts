/**
 * Rounded catalog sizes used in public descriptions (tool descriptions, llms.txt,
 * agent card, MCP server info). One place, so they don't drift apart.
 * Live exact numbers: GET /v1/catalog/stats. Update these when the catalog grows.
 */
export const SIZES = {
  total: "19,000+",
  apis: "11,000+",
  apisAndMcp: "12,000+",
  mcp: "1,500+",
  skills: "3,900+",
  agents: "950+",
  services: "1,500+",
} as const;
