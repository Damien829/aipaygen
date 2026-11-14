import { z } from "zod";
import { fetchJson } from "../lib/net";
import { ToolError } from "../lib/errors";
import { defineTool } from "./types";

/**
 * Weather from MET Norway (api.met.no): free, worldwide, commercial use allowed
 * under CC BY 4.0 with credit. Place names are geocoded with OpenStreetMap
 * Nominatim (low volume, cached for 30 days, credited).
 */

const MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact";
const GEOCODE_URL = "https://nominatim.openstreetmap.org/search";
const GEO_CACHE = "https://cache.aipaygen.internal/geo/v1/";

interface MetDetails {
  air_temperature?: number;
  relative_humidity?: number;
  wind_speed?: number;
  wind_from_direction?: number;
  cloud_area_fraction?: number;
  air_pressure_at_sea_level?: number;
}
interface MetPeriod { summary?: { symbol_code?: string }; details?: { precipitation_amount?: number } }
export interface MetStep {
  time: string;
  data: { instant: { details: MetDetails }; next_1_hours?: MetPeriod; next_6_hours?: MetPeriod; next_12_hours?: MetPeriod };
}
export interface MetForecast { properties: { meta?: { updated_at?: string }; timeseries: MetStep[] } }

const WORDS: [RegExp, string][] = [
  [/^clearsky/, "Clear"],
  [/^fair/, "Mostly clear"],
  [/^partlycloudy/, "Partly cloudy"],
  [/^cloudy/, "Cloudy"],
  [/^fog/, "Fog"],
];

/** "lightrainshowersandthunder_day" -> "Light rain showers and thunder". */
export function describeSymbol(code: string | undefined): string | null {
  if (!code) return null;
  const base = code.replace(/_(day|night|polartwilight)$/, "");
  for (const [re, text] of WORDS) if (re.test(base)) return text;
  // MET's codes are run-together words, and a few carry a typo ("lightssleet...", "lightssnow...").
  const words = ["light", "heavy", "rain", "sleet", "snow", "showers", "and", "thunder"];
  let rest = base.replace(/^lights(?=s(leet|now))/, "light");
  const out: string[] = [];
  while (rest) {
    const w = words.find((x) => rest.startsWith(x));
    if (!w) return base; // unknown shape: show it raw rather than guess
    out.push(w);
    rest = rest.slice(w.length);
  }
  const spaced = out.join(" ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const round1 = (n: number | undefined) => (typeof n === "number" ? Math.round(n * 10) / 10 : null);
const toF = (c: number | null) => (c === null ? null : Math.round((c * 9) / 5 + 32));
const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const compass = (deg: number | undefined) => (typeof deg === "number" ? COMPASS[Math.round(deg / 45) % 8]! : null);

/** Turns MET's hourly series into what an agent wants: now, the next hours, and daily highs and lows. */
export function summarizeForecast(f: MetForecast, lon: number, hours = 12, days = 5) {
  const steps = f.properties.timeseries;
  if (!steps.length) throw new ToolError("No forecast data for that location.", "NO_DATA", 404);
  const now = steps[0]!;
  const d = now.data.instant.details;
  const tempC = round1(d.air_temperature);

  // Approximate local day from longitude (MET returns UTC).
  const offsetMs = Math.round(lon / 15) * 3_600_000;
  const byDay = new Map<string, { min: number; max: number; precip: number; symbols: Map<string, number> }>();
  for (const s of steps) {
    const day = new Date(Date.parse(s.time) + offsetMs).toISOString().slice(0, 10);
    const t = s.data.instant.details.air_temperature;
    if (typeof t !== "number") continue;
    const e = byDay.get(day) ?? { min: t, max: t, precip: 0, symbols: new Map<string, number>() };
    e.min = Math.min(e.min, t);
    e.max = Math.max(e.max, t);
    e.precip += s.data.next_1_hours?.details?.precipitation_amount ?? 0;
    const sym = describeSymbol(s.data.next_1_hours?.summary?.symbol_code ?? s.data.next_6_hours?.summary?.symbol_code);
    if (sym) e.symbols.set(sym, (e.symbols.get(sym) ?? 0) + 1);
    byDay.set(day, e);
  }

  return {
    updated_at: f.properties.meta?.updated_at ?? null,
    current: {
      time: now.time,
      conditions: describeSymbol(now.data.next_1_hours?.summary?.symbol_code ?? now.data.next_6_hours?.summary?.symbol_code),
      temperature_c: tempC,
      temperature_f: toF(tempC),
      humidity_pct: round1(d.relative_humidity),
      wind_ms: round1(d.wind_speed),
      wind_mph: d.wind_speed === undefined ? null : Math.round(d.wind_speed * 2.237),
      wind_from: compass(d.wind_from_direction),
      cloud_cover_pct: round1(d.cloud_area_fraction),
      pressure_hpa: round1(d.air_pressure_at_sea_level),
      precipitation_next_hour_mm: round1(now.data.next_1_hours?.details?.precipitation_amount),
    },
    next_hours: steps.slice(0, hours).map((s) => {
      const c = round1(s.data.instant.details.air_temperature);
      return {
        time: s.time,
        conditions: describeSymbol(s.data.next_1_hours?.summary?.symbol_code),
        temperature_c: c,
        temperature_f: toF(c),
        precipitation_mm: round1(s.data.next_1_hours?.details?.precipitation_amount),
      };
    }),
    daily: [...byDay.entries()].slice(0, days).map(([date, e]) => ({
      date,
      conditions: [...e.symbols.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null,
      min_c: round1(e.min),
      max_c: round1(e.max),
      min_f: toF(round1(e.min)),
      max_f: toF(round1(e.max)),
      precipitation_mm: round1(e.precip),
    })),
  };
}

function geoCache(): Cache | null {
  return typeof caches !== "undefined" && "default" in caches ? (caches as unknown as { default: Cache }).default : null;
}

async function geocode(place: string): Promise<{ lat: number; lon: number; name: string }> {
  const norm = place.toLowerCase().replace(/\s+/g, " ").trim();
  const cache = geoCache();
  const key = new Request(GEO_CACHE + encodeURIComponent(norm));
  const hit = await cache?.match(key);
  if (hit) return (await hit.json()) as { lat: number; lon: number; name: string };

  const { data } = await fetchJson<{ lat: string; lon: string; display_name: string }[]>(
    `${GEOCODE_URL}?q=${encodeURIComponent(norm)}&format=jsonv2&limit=1`,
    { timeoutMs: 6000 },
  );
  const top = data?.[0];
  if (!top) throw new ToolError(`Couldn't find a place called "${place}". Try "City, Country" or pass lat and lon.`, "PLACE_NOT_FOUND", 404);
  const out = { lat: Number(top.lat), lon: Number(top.lon), name: top.display_name };
  await cache?.put(key, new Response(JSON.stringify(out), { headers: { "content-type": "application/json", "cache-control": "max-age=2592000" } }));
  return out;
}

export const weather = defineTool({
  name: "weather",
  title: "Weather forecast",
  description:
    "Current weather, the next 12 hours and a 5-day forecast for any place on Earth: temperature (C and F), conditions, rain, wind, humidity. Pass a place name (\"Austin, TX\") or lat/lon.",
  priceMicro: 2000,
  cacheTtl: 900,
  input: z.object({
    location: z.string().max(200).optional().describe('Place name, e.g. "Paris, France" or "10001 USA". Use this or lat/lon.'),
    lat: z.number().min(-90).max(90).optional().describe("Latitude, e.g. 40.71"),
    lon: z.number().min(-180).max(180).optional().describe("Longitude, e.g. -74.01"),
  }),
  example: { location: "Austin, TX" },
  async run({ location, lat, lon }) {
    let place: { lat: number; lon: number; name: string | null };
    if (typeof lat === "number" && typeof lon === "number") place = { lat, lon, name: null };
    else if (location?.trim()) place = await geocode(location);
    else throw new ToolError("Pass a location name, or both lat and lon.", "INVALID_INPUT", 400);

    // MET asks for at most 4 decimals (better caching on their side too).
    const la = Math.round(place.lat * 1e4) / 1e4;
    const lo = Math.round(place.lon * 1e4) / 1e4;
    const { status, data } = await fetchJson<MetForecast>(`${MET_URL}?lat=${la}&lon=${lo}`, { timeoutMs: 8000 });
    if (!data?.properties?.timeseries) throw new ToolError(`The weather service didn't answer (status ${status}).`, "UPSTREAM_ERROR", 502);

    return {
      location: { name: place.name, lat: la, lon: lo },
      ...summarizeForecast(data, lo),
      credit: place.name
        ? "Forecast: MET Norway (api.met.no), CC BY 4.0. Geocoding: © OpenStreetMap contributors (ODbL)."
        : "Forecast: MET Norway (api.met.no), CC BY 4.0.",
    };
  },
});
