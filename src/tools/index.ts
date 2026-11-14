import type { ToolDef } from "./types";
import { dnsLookup } from "./dns";
import { domainWhois } from "./whois";
import { sslCertificates } from "./certs";
import { emailSecurity } from "./emailsec";
import { securityHeaders } from "./headers";
import { techStack } from "./tech";
import { pageToMarkdown, siteMetadata } from "./page";
import { companyProfile, domainReport } from "./composite";
import { searchMarketplace } from "../catalog";
import { registerAgentTool } from "../growth";
import { runSkill } from "../skills";
import { weather } from "./weather";
import { translate } from "./translate";

/** Every paid tool, cheapest first. Order is used in docs and listings. */
export const TOOLS: ToolDef[] = [
  searchMarketplace,
  registerAgentTool,
  runSkill,
  dnsLookup,
  securityHeaders,
  weather,
  translate,
  domainWhois,
  emailSecurity,
  siteMetadata,
  pageToMarkdown,
  sslCertificates,
  techStack,
  companyProfile,
  domainReport,
] as unknown as ToolDef[];

export const TOOLS_BY_NAME = new Map(TOOLS.map((t) => [t.name, t]));
