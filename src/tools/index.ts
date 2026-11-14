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
import { currencyConvert, earthquakes, geocode, hackerNews, paperSearch, publicHolidays, wikipedia } from "./data";
import { domainAvailable, ipLookup, packageInfo, packageVulns, redirectCheck } from "./devtools";
import { askLlm, describeImage, embedText, generateImage, rankTexts, textToSpeech, transcribeAudio } from "./media";
import { cryptoPrice, dexToken, gasPrice, tokenSecurity, walletBalance } from "./crypto";
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
  geocode,
  earthquakes,
  cryptoPrice,
  dexToken,
  walletBalance,
  gasPrice,
  embedText,
  securityHeaders,
  weather,
  translate,
  classifyText,
  packageVulns,
  paperSearch,
  domainAvailable,
  rankTexts,
  tokenSecurity,
  domainWhois,
  emailSecurity,
  siteMetadata,
  pageToMarkdown,
  sslCertificates,
  techStack,
  summarize,
  extractData,
  describeImage,
  textToSpeech,
  askLlm,
  transcribeAudio,
  generateImage,
  companyProfile,
  domainReport,
] as unknown as ToolDef[];

registerTools(TOOLS);

export const TOOLS_BY_NAME = new Map(TOOLS.map((t) => [t.name, t]));
