-- قاعدة بيانات الإحصائيات
-- كل زيارة أو ضغطة أو بحث ينحفظ كسطر واحد هنا
-- ما نحفظ عنوان الزائر أبداً، بس رقم عشوائي يتولد في متصفحه

CREATE TABLE IF NOT EXISTS events (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        INTEGER NOT NULL,      -- الوقت بالملي ثانية
  day       TEXT    NOT NULL,      -- التاريخ بتوقيت السعودية
  hour      INTEGER NOT NULL,      -- الساعة بتوقيت السعودية
  type      TEXT    NOT NULL,      -- pv زيارة، click ضغطة رابط، search بحث، filter قسم، ping بقاء في الصفحة
  vid       TEXT,                  -- رقم الزائر العشوائي
  sid       TEXT,                  -- رقم الجلسة
  path      TEXT,
  ref       TEXT,                  -- الموقع اللي جاء منه الزائر
  product   TEXT,
  category  TEXT,
  store     TEXT,
  url       TEXT,
  price     REAL,
  query     TEXT,
  results   INTEGER,
  device    TEXT,
  browser   TEXT,
  country   TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_day_type ON events (day, type);
CREATE INDEX IF NOT EXISTS idx_events_ts       ON events (ts);
CREATE INDEX IF NOT EXISTS idx_events_vid      ON events (vid, day);
CREATE INDEX IF NOT EXISTS idx_events_sid      ON events (sid);
