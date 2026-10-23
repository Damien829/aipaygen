/**
 * Fingerprints for detecting web technologies from a page's HTML, script
 * URLs, response headers and cookies. Written for AIPayGen; patterns match
 * publicly visible markers only.
 */
export interface TechSignature {
  name: string;
  category: string;
  website?: string;
  html?: RegExp[];
  scripts?: RegExp[];
  headers?: Record<string, RegExp>;
  cookies?: RegExp[];
  meta?: Record<string, RegExp>;
  /** Other technologies this one implies (e.g. Next.js implies React). */
  implies?: string[];
}

export const TECH_SIGNATURES: TechSignature[] = [
  // Frameworks
  { name: "Next.js", category: "Framework", html: [/__NEXT_DATA__/, /\/_next\/static\//], headers: { "x-powered-by": /next\.js/i }, implies: ["React"] },
  { name: "Nuxt", category: "Framework", html: [/__NUXT__/, /\/_nuxt\//], implies: ["Vue.js"] },
  { name: "Remix", category: "Framework", html: [/__remixContext/, /__reactRouterContext/], implies: ["React"] },
  { name: "Gatsby", category: "Framework", html: [/___gatsby/, /gatsby-image/], meta: { generator: /gatsby/i }, implies: ["React"] },
  { name: "Astro", category: "Framework", html: [/astro-island/, /\/_astro\//], meta: { generator: /astro/i } },
  { name: "SvelteKit", category: "Framework", html: [/__sveltekit/, /\/_app\/immutable\//], implies: ["Svelte"] },
  { name: "Angular", category: "Framework", html: [/ng-version="/, /<app-root/] },
  { name: "Ember.js", category: "Framework", html: [/ember-application/, /data-ember-extension/] },
  { name: "Ruby on Rails", category: "Framework", html: [/csrf-param" content="authenticity_token/], headers: { "x-runtime": /\d/ }, cookies: [/_session_id/] },
  { name: "Laravel", category: "Framework", cookies: [/laravel_session/] },
  { name: "Django", category: "Framework", cookies: [/csrftoken/], html: [/csrfmiddlewaretoken/] },
  { name: "Express", category: "Framework", headers: { "x-powered-by": /express/i } },
  { name: "ASP.NET", category: "Framework", headers: { "x-powered-by": /asp\.net/i, "x-aspnet-version": /./ }, html: [/__VIEWSTATE/], cookies: [/ASP\.NET_SessionId/] },
  { name: "PHP", category: "Language", headers: { "x-powered-by": /php/i }, cookies: [/PHPSESSID/] },

  // UI libraries
  { name: "React", category: "JavaScript library", html: [/data-reactroot/, /react-dom/], scripts: [/react(\.production)?(\.min)?\.js/, /react-dom/] },
  { name: "Vue.js", category: "JavaScript library", html: [/data-v-[0-9a-f]{8}/, /\bv-cloak\b/], scripts: [/vue(\.runtime)?(\.global)?(\.prod)?(\.min)?\.js/] },
  { name: "Svelte", category: "JavaScript library", html: [/class="[^"]*svelte-[a-z0-9]{5,}/] },
  { name: "jQuery", category: "JavaScript library", scripts: [/jquery[.-]?\d*(\.\d+)*(\.min)?\.js/i] },
  { name: "Alpine.js", category: "JavaScript library", html: [/\bx-data=/], scripts: [/alpinejs/] },
  { name: "htmx", category: "JavaScript library", html: [/\bhx-(get|post|target|swap)=/], scripts: [/htmx(\.min)?\.js/] },
  { name: "Tailwind CSS", category: "CSS framework", html: [/class="[^"]*\b(?:flex|grid) [^"]*\b(?:px|py|mt|mb)-\d/, /--tw-/] },
  { name: "Bootstrap", category: "CSS framework", scripts: [/bootstrap(\.bundle)?(\.min)?\.js/], html: [/bootstrap(\.min)?\.css/] },

  // CMS / site builders / e-commerce
  { name: "WordPress", category: "CMS", html: [/\/wp-content\//, /\/wp-includes\//], meta: { generator: /wordpress/i }, implies: ["PHP"] },
  { name: "WooCommerce", category: "E-commerce", html: [/\/wp-content\/plugins\/woocommerce\//, /class="[^"]*\bwoocommerce-(?:page|cart|checkout|no-js)\b/], implies: ["WordPress"] },
  // Only store-specific markers: other sites often embed images from cdn.shopify.com.
  { name: "Shopify", category: "E-commerce", html: [/Shopify\.theme\s*=/, /\bshopify-section\b/, /cdn\.shopify\.com\/s\/files\/[^"']+\/(?:t|assets)\//], headers: { "x-shopid": /./, "x-shopify-stage": /./, powered_by: /shopify/i } },
  { name: "Wix", category: "Site builder", html: [/static\.wixstatic\.com/, /wix-warmup-data/], headers: { "x-wix-request-id": /./ } },
  { name: "Squarespace", category: "Site builder", html: [/static1\.squarespace\.com/, /Squarespace\.Constants/] },
  { name: "Webflow", category: "Site builder", html: [/data-wf-page=/, /assets\.website-files\.com|cdn\.prod\.website-files\.com/] },
  { name: "Framer", category: "Site builder", html: [/framerusercontent\.com/, /data-framer-/] },
  { name: "Ghost", category: "CMS", meta: { generator: /ghost/i }, html: [/ghost-portal/] },
  { name: "Drupal", category: "CMS", headers: { "x-generator": /drupal/i }, meta: { generator: /drupal/i }, html: [/Drupal\.settings/, /\/sites\/default\/files\//] },
  { name: "Joomla", category: "CMS", meta: { generator: /joomla/i } },
  { name: "HubSpot CMS", category: "CMS", html: [/hs-sites\.com|hubspotusercontent/] },
  { name: "Contentful", category: "Headless CMS", html: [/images\.ctfassets\.net/] },
  { name: "Sanity", category: "Headless CMS", html: [/cdn\.sanity\.io/] },
  { name: "Magento", category: "E-commerce", html: [/Mage\.Cookies/, /\/static\/version\d+\/frontend\//], cookies: [/^mage-/] },
  { name: "BigCommerce", category: "E-commerce", html: [/cdn\d*\.bigcommerce\.com/] },
  { name: "Mintlify", category: "Documentation", html: [/mintlify/i] },
  { name: "Docusaurus", category: "Documentation", meta: { generator: /docusaurus/i }, implies: ["React"] },
  { name: "GitBook", category: "Documentation", html: [/gitbook/i] },

  // Hosting / CDN / infrastructure
  // Cloudflare is detected from the site's IP addresses (see tech.ts): fetches made
  // from a Worker carry Cloudflare's own server/cf-ray headers for every site.
  { name: "Cloudflare", category: "CDN" },
  { name: "Vercel", category: "Hosting", headers: { server: /vercel/i, "x-vercel-id": /./ } },
  { name: "Netlify", category: "Hosting", headers: { server: /netlify/i, "x-nf-request-id": /./ } },
  { name: "Fastly", category: "CDN", headers: { "x-served-by": /cache-/, via: /varnish|fastly/i, "x-fastly-request-id": /./ } },
  { name: "Amazon CloudFront", category: "CDN", headers: { via: /cloudfront/i, "x-amz-cf-id": /./ } },
  { name: "Amazon S3", category: "Hosting", headers: { server: /AmazonS3/i } },
  { name: "Akamai", category: "CDN", headers: { "x-akamai-transformed": /./, server: /akamai/i } },
  { name: "Google Cloud", category: "Hosting", headers: { server: /gws|Google Frontend|gfe/i, via: /google/i } },
  { name: "Microsoft Azure", category: "Hosting", headers: { "x-azure-ref": /./, "x-ms-request-id": /./ } },
  { name: "GitHub Pages", category: "Hosting", headers: { server: /GitHub\.com/i } },
  { name: "Fly.io", category: "Hosting", headers: { server: /fly\/|Fly/, "fly-request-id": /./ } },
  { name: "Render", category: "Hosting", headers: { "rndr-id": /./, "x-render-origin-server": /./ } },
  { name: "Heroku", category: "Hosting", headers: { via: /vegur/i } },
  { name: "Nginx", category: "Web server", headers: { server: /nginx/i } },
  { name: "Apache", category: "Web server", headers: { server: /apache/i } },
  { name: "Microsoft IIS", category: "Web server", headers: { server: /IIS/ } },
  { name: "LiteSpeed", category: "Web server", headers: { server: /litespeed/i } },
  { name: "Caddy", category: "Web server", headers: { server: /caddy/i } },

  // Analytics / tag managers
  { name: "Google Analytics", category: "Analytics", scripts: [/google-analytics\.com\/(analytics|ga)\.js/, /googletagmanager\.com\/gtag\/js/], html: [/gtag\(['"]config['"],\s*['"]G-/] },
  { name: "Google Tag Manager", category: "Tag manager", scripts: [/googletagmanager\.com\/gtm\.js/], html: [/GTM-[A-Z0-9]{4,}/] },
  { name: "Segment", category: "Analytics", scripts: [/cdn\.segment\.com\/analytics\.js/] },
  { name: "Mixpanel", category: "Analytics", scripts: [/cdn\.mxpnl\.com|mixpanel/] },
  { name: "Amplitude", category: "Analytics", scripts: [/cdn\.amplitude\.com|amplitude\.com\/libs/] },
  { name: "PostHog", category: "Analytics", scripts: [/posthog/], html: [/posthog\.init/] },
  { name: "Plausible", category: "Analytics", scripts: [/plausible\.io\/js/] },
  { name: "Fathom", category: "Analytics", scripts: [/cdn\.usefathom\.com/] },
  { name: "Hotjar", category: "Analytics", scripts: [/static\.hotjar\.com/], html: [/hotjar/] },
  { name: "Microsoft Clarity", category: "Analytics", scripts: [/clarity\.ms/] },
  { name: "Heap", category: "Analytics", scripts: [/heapanalytics\.com|cdn\.heapanalytics/] },
  { name: "Vercel Analytics", category: "Analytics", scripts: [/\/_vercel\/insights|va\.vercel-scripts\.com/] },
  { name: "Cloudflare Web Analytics", category: "Analytics", scripts: [/static\.cloudflareinsights\.com/] },

  // Marketing / ads
  { name: "Meta Pixel", category: "Advertising", scripts: [/connect\.facebook\.net\/[^/]+\/fbevents\.js/], html: [/fbq\(['"]init/] },
  { name: "LinkedIn Insight", category: "Advertising", scripts: [/snap\.licdn\.com/] },
  { name: "TikTok Pixel", category: "Advertising", scripts: [/analytics\.tiktok\.com/] },
  { name: "Google Ads", category: "Advertising", scripts: [/googleadservices\.com|googlesyndication\.com/], html: [/AW-\d{6,}/] },
  { name: "HubSpot", category: "Marketing automation", scripts: [/js\.hs-scripts\.com|js\.hsforms\.net|js\.hs-analytics\.net/] },
  { name: "Marketo", category: "Marketing automation", scripts: [/munchkin\.marketo\.net/] },
  { name: "Klaviyo", category: "Marketing automation", scripts: [/static\.klaviyo\.com/] },
  { name: "Mailchimp", category: "Email marketing", scripts: [/chimpstatic\.com|list-manage\.com/] },

  // Support / chat
  { name: "Intercom", category: "Live chat", scripts: [/widget\.intercom\.io|js\.intercomcdn\.com/] },
  { name: "Zendesk", category: "Support", scripts: [/static\.zdassets\.com|zopim/] },
  { name: "Drift", category: "Live chat", scripts: [/js\.driftt\.com/] },
  { name: "Crisp", category: "Live chat", scripts: [/client\.crisp\.chat/] },
  { name: "Tawk.to", category: "Live chat", scripts: [/embed\.tawk\.to/] },

  // Payments
  { name: "Stripe", category: "Payments", scripts: [/js\.stripe\.com/] },
  { name: "PayPal", category: "Payments", scripts: [/paypal\.com\/sdk\/js|paypalobjects\.com/] },
  { name: "Paddle", category: "Payments", scripts: [/cdn\.paddle\.com/] },
  { name: "Lemon Squeezy", category: "Payments", scripts: [/lemonsqueezy\.com/] },

  // Auth / security / misc
  { name: "Auth0", category: "Authentication", scripts: [/cdn\.auth0\.com/] },
  { name: "Clerk", category: "Authentication", scripts: [/clerk\.[a-z0-9.-]+\/npm\/@clerk|clerk\.browser\.js/], html: [/__clerk/] },
  { name: "reCAPTCHA", category: "Security", scripts: [/google\.com\/recaptcha|gstatic\.com\/recaptcha/] },
  { name: "hCaptcha", category: "Security", scripts: [/hcaptcha\.com\/1\/api\.js/] },
  { name: "Cloudflare Turnstile", category: "Security", scripts: [/challenges\.cloudflare\.com\/turnstile/] },
  { name: "Sentry", category: "Monitoring", scripts: [/browser\.sentry-cdn\.com|sentry\.io/], html: [/Sentry\.init/] },
  { name: "Datadog RUM", category: "Monitoring", scripts: [/datadoghq-browser-agent|datadog-rum/] },
  { name: "OneTrust", category: "Cookie consent", scripts: [/cdn\.cookielaw\.org|onetrust/i] },
  { name: "Cookiebot", category: "Cookie consent", scripts: [/consent\.cookiebot\.com/] },
  { name: "Google Fonts", category: "Fonts", html: [/fonts\.googleapis\.com/] },
  { name: "Adobe Fonts", category: "Fonts", html: [/use\.typekit\.net/] },
  { name: "Font Awesome", category: "Fonts", html: [/font-awesome|fontawesome/i] },
  { name: "YouTube embed", category: "Video", html: [/youtube\.com\/embed\//] },
  { name: "Vimeo", category: "Video", html: [/player\.vimeo\.com/] },
  { name: "Calendly", category: "Scheduling", scripts: [/assets\.calendly\.com/], html: [/calendly\.com\//] },
  { name: "Typeform", category: "Forms", scripts: [/embed\.typeform\.com/] },
];
