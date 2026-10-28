/**
 * سيرفر إحصائيات موقع أرخص قطعة
 * =============================
 * POST /e                     يستقبل حدث من الموقع (زيارة، ضغطة، بحث...)
 * POST /admin/api/login       يتأكد من كلمة سر الأدمن
 * GET  /admin/api/stats       كل أرقام لوحة التحكم
 * GET  /admin/api/export      تنزيل البيانات كملف CSV
 *
 * كلمة السر تنحفظ كسر في كلاودفلير باسم ADMIN_PASSWORD
 */

const TYPES = new Set(["pv", "click", "search", "filter", "ping"]);
const BOT_RE = /bot|crawl|spider|slurp|headless|lighthouse|preview|facebookexternalhit|whatsapp|curl|wget|python|axios|node-fetch/i;
const RIYADH_OFFSET = 3 * 3600 * 1000;   // توقيت السعودية ثابت +٣
const DAY = 86400000;

// ---------------- أدوات ----------------

const cors = (extra = {}) => ({
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Access-Control-Max-Age": "86400",
  ...extra,
});

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: cors({ "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" }) });

const riyadh = ts => {
  const d = new Date(ts + RIYADH_OFFSET);
  return { day: d.toISOString().slice(0, 10), hour: d.getUTCHours() };
};

const str = (v, max = 200) => (typeof v === "string" && v.trim() ? v.trim().slice(0, max) : null);
const num = v => (typeof v === "number" && isFinite(v) ? v : null);

function device(ua, width) {
  if (/iPad|Tablet/i.test(ua) || (width >= 600 && width < 1024 && /Android/i.test(ua))) return "tablet";
  if (/Mobi|Android|iPhone/i.test(ua) || (width && width < 600)) return "mobile";
  return "desktop";
}

function browser(ua) {
  if (/Edg\//.test(ua)) return "Edge";
  if (/OPR\/|Opera/.test(ua)) return "Opera";
  if (/SamsungBrowser/.test(ua)) return "Samsung";
  if (/Firefox\//.test(ua)) return "Firefox";
  if (/Chrome\//.test(ua)) return "Chrome";
  if (/Safari\//.test(ua)) return "Safari";
  return "Other";
}

function refHost(ref) {
  try { return ref ? new URL(ref).hostname.replace(/^www\./, "") : null; } catch { return null; }
}

// مقارنة كلمة السر بوقت ثابت (عشان ما أحد يخمنها من سرعة الرد)
function safeEqual(a, b) {
  const enc = new TextEncoder();
  const x = enc.encode(a || ""), y = enc.encode(b || "");
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] || 0) ^ (y[i] || 0);
  return diff === 0;
}

async function isAdmin(request, env) {
  const auth = request.headers.get("Authorization") || "";
  const pass = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  if (env.ADMIN_PASSWORD && pass && safeEqual(pass, env.ADMIN_PASSWORD)) return true;
  await new Promise(r => setTimeout(r, 800));   // نبطّئ المحاولات الغلط
  return false;
}

// ---------------- استقبال الأحداث ----------------

async function collect(request, env) {
  const ua = request.headers.get("User-Agent") || "";
  if (BOT_RE.test(ua)) return new Response(null, { status: 204, headers: cors() });
  const text = await request.text();
  if (text.length > 4000) return new Response(null, { status: 413, headers: cors() });

  let list;
  try {
    const body = JSON.parse(text);
    list = Array.isArray(body) ? body.slice(0, 20) : [body];
  } catch {
    return new Response(null, { status: 400, headers: cors() });
  }

  const now = Date.now();
  const { day, hour } = riyadh(now);
  const country = (request.cf && request.cf.country) || request.headers.get("CF-IPCountry") || null;
  const br = browser(ua);

  const rows = [];
  for (const e of list) {
    if (!e || !TYPES.has(e.t)) continue;
    const dev = device(ua, num(e.w));
    let ref = refHost(str(e.ref, 300));
    const own = refHost(request.headers.get("Origin") || "");
    if (ref && own && ref === own) ref = null;
    rows.push(env.DB.prepare(
      `INSERT INTO events (ts, day, hour, type, vid, sid, path, ref, product, category, store, url, price, query, results, device, browser, country)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).bind(now, day, hour, e.t, str(e.vid, 40), str(e.sid, 40), str(e.p, 200), ref,
      str(e.product), str(e.category, 40), str(e.store, 60), str(e.url, 500), num(e.price),
      e.q ? str(e.q, 80).toLowerCase() : null, num(e.results), dev, br, country));
  }
  if (rows.length) await env.DB.batch(rows);
  return new Response(null, { status: 204, headers: cors() });
}

// ---------------- إحصائيات لوحة التحكم ----------------

function range(url) {
  const days = Math.min(Math.max(parseInt(url.searchParams.get("days") || "7", 10) || 7, 1), 366);
  const now = Date.now();
  const to = riyadh(now).day;
  const from = riyadh(now - (days - 1) * DAY).day;
  const prevTo = riyadh(now - days * DAY).day;
  const prevFrom = riyadh(now - (2 * days - 1) * DAY).day;
  return { days, from, to, prevFrom, prevTo };
}

async function stats(url, env) {
  const { days, from, to, prevFrom, prevTo } = range(url);
  const R = "day BETWEEN ?1 AND ?2";
  const q = (sql, ...extra) => env.DB.prepare(sql).bind(from, to, ...extra);

  const totalsSql = `SELECT
      COUNT(DISTINCT CASE WHEN type='pv' THEN vid END) AS visitors,
      COUNT(DISTINCT CASE WHEN type='pv' THEN sid END) AS sessions,
      SUM(type='pv') AS pageviews, SUM(type='click') AS clicks, SUM(type='search') AS searches,
      COUNT(DISTINCT CASE WHEN type='click' THEN sid END) AS clicking_sessions
    FROM events WHERE ${R}`;

  const results = await env.DB.batch([
    q(totalsSql),
    env.DB.prepare(totalsSql).bind(prevFrom, prevTo),
    q(`SELECT day, COUNT(DISTINCT CASE WHEN type='pv' THEN vid END) AS visitors,
              SUM(type='pv') AS pageviews, SUM(type='click') AS clicks
       FROM events WHERE ${R} GROUP BY day ORDER BY day`),
    q(`SELECT product, MAX(category) AS category, COUNT(*) AS clicks, COUNT(DISTINCT vid) AS users,
              ROUND(AVG(price)) AS price
       FROM events WHERE ${R} AND type='click' AND product IS NOT NULL
       GROUP BY product ORDER BY clicks DESC LIMIT 15`),
    q(`SELECT store, COUNT(*) AS clicks FROM events WHERE ${R} AND type='click' AND store IS NOT NULL
       GROUP BY store ORDER BY clicks DESC`),
    q(`SELECT query, COUNT(*) AS n, MIN(results) AS results FROM events
       WHERE ${R} AND type='search' AND query IS NOT NULL GROUP BY query ORDER BY n DESC LIMIT 20`),
    q(`SELECT query, COUNT(*) AS n FROM events
       WHERE ${R} AND type='search' AND results = 0 AND query IS NOT NULL
       GROUP BY query ORDER BY n DESC LIMIT 20`),
    q(`SELECT COALESCE(ref, 'direct') AS ref, COUNT(DISTINCT sid) AS sessions FROM events
       WHERE ${R} AND type='pv' GROUP BY ref ORDER BY sessions DESC LIMIT 12`),
    q(`SELECT device, COUNT(DISTINCT vid) AS visitors FROM events WHERE ${R} AND type='pv'
       GROUP BY device ORDER BY visitors DESC`),
    q(`SELECT browser, COUNT(DISTINCT vid) AS visitors FROM events WHERE ${R} AND type='pv'
       GROUP BY browser ORDER BY visitors DESC`),
    q(`SELECT COALESCE(country, '??') AS country, COUNT(DISTINCT vid) AS visitors FROM events
       WHERE ${R} AND type='pv' GROUP BY country ORDER BY visitors DESC LIMIT 12`),
    q(`SELECT hour, SUM(type='pv') AS pageviews, SUM(type='click') AS clicks FROM events
       WHERE ${R} GROUP BY hour ORDER BY hour`),
    q(`SELECT category, COUNT(*) AS n FROM events WHERE ${R} AND type='filter' AND category IS NOT NULL
       GROUP BY category ORDER BY n DESC`),
    // زوار جدد: أول ظهور لهم داخل الفترة
    q(`SELECT COUNT(*) AS n FROM (SELECT vid, MIN(day) AS first FROM events WHERE type='pv' AND vid IS NOT NULL
       GROUP BY vid) WHERE first BETWEEN ?1 AND ?2`),
    // متوسط مدة الجلسة (بالثواني)
    q(`SELECT ROUND(AVG(dur) / 1000) AS avg_seconds FROM (
         SELECT MAX(ts) - MIN(ts) AS dur FROM events WHERE ${R} AND sid IS NOT NULL GROUP BY sid
       )`),
    env.DB.prepare(`SELECT COUNT(DISTINCT vid) AS n FROM events WHERE ts > ?`).bind(Date.now() - 5 * 60000),
    env.DB.prepare(`SELECT ts, type, product, store, query, results, category, country, device, ref
                    FROM events WHERE type != 'ping' ORDER BY ts DESC LIMIT 40`),
  ]);

  const r = i => results[i].results || [];
  const totals = r(0)[0] || {};
  const prev = r(1)[0] || {};
  return json({
    range: { days, from, to },
    totals: {
      ...totals,
      new_visitors: (r(13)[0] || {}).n || 0,
      avg_session_seconds: (r(14)[0] || {}).avg_seconds || 0,
      live: (r(15)[0] || {}).n || 0,
    },
    previous: prev,
    daily: r(2),
    topProducts: r(3),
    stores: r(4),
    searches: r(5),
    zeroSearches: r(6),
    referrers: r(7),
    devices: r(8),
    browsers: r(9),
    countries: r(10),
    hours: r(11),
    categories: r(12),
    recent: r(16),
  });
}

async function exportCsv(url, env) {
  const { from, to } = range(url);
  const { results } = await env.DB.prepare(
    `SELECT ts, day, hour, type, vid, sid, ref, product, category, store, url, price, query, results, device, browser, country
     FROM events WHERE day BETWEEN ? AND ? AND type != 'ping' ORDER BY ts LIMIT 100000`
  ).bind(from, to).all();
  const cols = ["time", "day", "hour", "type", "visitor", "session", "referrer", "product", "category",
                "store", "url", "price", "search", "results", "device", "browser", "country"];
  const keys = ["ts", "day", "hour", "type", "vid", "sid", "ref", "product", "category",
                "store", "url", "price", "query", "results", "device", "browser", "country"];
  const cell = v => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const lines = [cols.join(",")].concat((results || []).map(row =>
    keys.map(k => cell(k === "ts" ? new Date(row.ts).toISOString() : row[k])).join(",")));
  return new Response("﻿" + lines.join("\n"), {
    headers: cors({
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="analytics-${from}-to-${to}.csv"`,
    }),
  });
}

// ---------------- التوجيه ----------------

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors() });

    try {
      if (url.pathname === "/e" && request.method === "POST") return await collect(request, env);

      if (url.pathname.startsWith("/admin/api/")) {
        if (!env.ADMIN_PASSWORD) return json({ error: "ما تم ضبط كلمة سر الأدمن في السيرفر" }, 500);
        if (!(await isAdmin(request, env))) return json({ error: "كلمة السر غلط" }, 401);
        if (url.pathname === "/admin/api/login") return json({ ok: true });
        if (url.pathname === "/admin/api/stats") return await stats(url, env);
        if (url.pathname === "/admin/api/export") return await exportCsv(url, env);
        return json({ error: "not found" }, 404);
      }

      if (url.pathname === "/") return new Response("ok", { headers: cors() });
      return new Response("not found", { status: 404, headers: cors() });
    } catch (err) {
      return json({ error: String(err && err.message || err) }, 500);
    }
  },

  // تنظيف يومي: نحذف البيانات الأقدم من المدة المحددة
  async scheduled(event, env) {
    const keep = parseInt(env.RETENTION_DAYS || "400", 10);
    const cutoff = Date.now() - keep * DAY;
    await env.DB.prepare("DELETE FROM events WHERE ts < ?").bind(cutoff).run();
  },
};
