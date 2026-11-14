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
import { findTool } from "../router";
import { registerAgentTool } from "../growth";
import { runSkill } from "../skills";
import { weather } from "./weather";
import { translate } from "./translate";
import { classifyText, extractData, summarize } from "./ai";
import { currencyConvert, hackerNews, paperSearch, publicHolidays, wikipedia } from "./data";
import { ipLookup, packageInfo, packageVulns, redirectCheck } from "./devtools";
import { registerTools } from "../registry";

/** Every paid tool, cheapest first. Order is used in docs and listings. */
export const TOOLS: ToolDef[] = [
  searchMarketplace,
  findTool,
  registerAgentTool,
  runSkill,
  dnsLookup,
  currencyConvert,
  publicHolidays,
  wikipedia,
  hackerNews,
  packageInfo,
  ipLookup,
  redirectCheck,
  securityHeaders,
  weather,
  translate,
  classifyText,
  packageVulns,
  paperSearch,
  domainWhois,
  emailSecurity,
  siteMetadata,
  pageToMarkdown,
  sslCertificates,
  techStack,
  summarize,
  extractData,
  companyProfile,
  domainReport,
] as unknown as ToolDef[];

registerTools(TOOLS);

export const TOOLS_BY_NAME = new Map(TOOLS.map((t) => [t.name, t]));
