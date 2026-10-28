/*
 * تتبع الزيارات والضغطات
 * ما نحفظ أي معلومة شخصية: بس رقم عشوائي يتولد في متصفح الزائر
 */
(function () {
  "use strict";
  const base = ((window.SITE_CONFIG || {}).analyticsUrl || "").replace(/\/+$/, "");
  const noop = () => {};
  window.track = noop;
  if (!base) return;
  // نحترم إعداد "عدم التتبع" في المتصفح
  if (navigator.doNotTrack === "1" || window.doNotTrack === "1") return;
  if (/[?&]notrack/.test(location.search)) {
    try { localStorage.setItem("notrack", "1"); } catch (e) {}
  }
  try { if (localStorage.getItem("notrack") === "1") return; } catch (e) {}

  const rid = () => Math.random().toString(36).slice(2) + Date.now().toString(36);
  const store = (s, k) => {
    try { let v = s.getItem(k); if (!v) { v = rid(); s.setItem(k, v); } return v; }
    catch (e) { return rid(); }
  };
  const vid = store(window.localStorage, "vid");
  const sid = store(window.sessionStorage, "sid");
  const endpoint = base + "/e";

  let queue = [];
  let timer = null;
  function flush() {
    timer = null;
    if (!queue.length) return;
    const body = JSON.stringify(queue.splice(0, 20));
    // نرسل كنص عادي عشان ما يحتاج طلب إذن مسبق من المتصفح
    const ok = navigator.sendBeacon && navigator.sendBeacon(endpoint, new Blob([body], { type: "text/plain" }));
    if (!ok) fetch(endpoint, { method: "POST", body, keepalive: true, headers: { "Content-Type": "text/plain" } }).catch(noop);
  }

  window.track = function (t, data) {
    queue.push(Object.assign({ t, vid, sid, p: location.pathname, w: window.innerWidth }, data || {}));
    if (t === "click") flush();           // الضغطة ترسل فوراً لأن الزائر بيطلع من الصفحة
    else if (!timer) timer = setTimeout(flush, 1500);
  };

  track("pv", { ref: document.referrer || null });

  // نبضة كل دقيقتين عشان نعرف مدة البقاء والمتواجدين الحين
  let pings = 0;
  setInterval(() => {
    if (document.visibilityState === "visible" && pings < 15) { pings++; track("ping"); }
  }, 120000);

  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") flush(); });
  window.addEventListener("pagehide", flush);
})();
