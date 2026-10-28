"""
سكربت سحب الأسعار
=================
يقرأ قائمة المنتجات من products.yaml
يزور رابط كل منتج في كل متجر
يستخرج السعر
ويكتب النتيجة في site/data.json اللي يقرأها الموقع

التشغيل:
    python scraper.py
"""

from __future__ import annotations

import json
from html import unescape as html_unescape
from io import BytesIO
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
PRODUCTS_FILE = ROOT / "products.yaml"
SITE_DIR = ROOT / "site"
OUTPUT_FILE = SITE_DIR / "data.json"     # اللي يقرأه الموقع: المتوفر فقط
IMG_DIR = SITE_DIR / "img"              # صور القطع
STATE_FILE = ROOT / "state.json"        # حالة كل رابط (متوفر/نافد) وسجل الأسعار

HISTORY_LIMIT = 60          # كم سعر قديم نحفظ لكل منتج (للرسم البياني)

# ---- الحماية من الحظر ----
DELAY_RANGE = (1.5, 3.5)    # انتظار بين أي طلبين
STORE_GAP = (8.0, 15.0)     # أقل وقت بين طلبين لنفس المتجر (ثواني)
MAX_PER_STORE = 120         # أقصى عدد طلبات لكل متجر في التشغيل الواحد
REFRESH_HOURS = 5           # ما نعيد فحص رابط إلا إذا مر عليه هالوقت

# ---- التوفر ----
CONFIRM_WAIT = 90           # كم ثانية ننتظر قبل ما نعيد فحص قطعة طلعت نافدة
MAX_STALE_HOURS = 48        # لو آخر مرة شفنا القطعة متوفرة أقدم من كذا، نخفيها

# ---- الصور ----
MAX_IMAGES_PER_RUN = 60
TIMEOUT = 20
MAX_STORE_FAILS = 3         # بعد كم فشل متتالي نتخطى المتجر في هذا التشغيل
RETRIES = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# أسماء المتاجر بالعربي حسب الدومين
STORE_NAMES = {
    "amazon.sa": "أمازون السعودية",
    "noon.com": "نون",
    "pcd.com.sa": "طبيب الكمبيوتر",
    "infiniarc.com": "إنفني أرك",
    "microless.com": "مايكروليس",
    "feeh.sa": "فيه",
    "geekay.com": "جيكاي",
    "extra.com": "إكسترا",
    "jarir.com": "جرير",
}

# محددات احتياطية لكل متجر، تُستخدم فقط إذا ما لقينا السعر بالطرق العامة.
# المتاجر تغيّر تصميمها أحياناً، فإذا متجر وقف يشتغل غالباً تحتاج تحدّث هنا.
STORE_SELECTORS = {
    "amazon.sa": [
        "#corePrice_feature_div span.a-offscreen",
        "#corePriceDisplay_desktop_feature_div span.a-offscreen",
        "span.a-price span.a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
    ],
    "noon.com": [
        '[data-qa="div-price-now"]',
        '[data-qa="price-now"]',
        ".priceNow",
    ],
    "pcd.com.sa": [
        ".total-price",
        ".product-price",
        "[data-price]",
        ".price-wrapper .price",
        ".price",
    ],
    # إنفني أرك مبني على منصة أودو
    "infiniarc.com": [
        ".oe_price .oe_currency_value",
        ".product_price .oe_currency_value",
        ".oe_currency_value",
    ],
    "microless.com": [".product-price-value", ".product-price"],
    "extra.com": [".price-value", ".product-price .price"],
    "jarir.com": [".price-box .price", ".price"],
}

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")


# ----------------------------------------------------------
# أدوات مساعدة
# ----------------------------------------------------------

def store_key(url: str) -> str:
    """يرجع اسم الدومين بدون www (مثل amazon.sa)."""
    host = urlparse(url).netloc.lower()
    host = host.removeprefix("www.")
    for key in STORE_NAMES:
        if host == key or host.endswith("." + key):
            return key
    return host


def store_name(url: str) -> str:
    key = store_key(url)
    return STORE_NAMES.get(key, key)


def parse_price(text) -> float | None:
    """يحوّل نص السعر لرقم. يدعم الأرقام العربية والفواصل ورموز العملة."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text) if text > 0 else None

    s = str(text).translate(ARABIC_DIGITS)
    s = s.replace(" ", " ")
    match = re.search(r"\d[\d,\s]*(?:\.\d+)?", s)
    if not match:
        return None
    num = match.group(0).replace(" ", "")

    # "1,299.00" أو "1299,00"
    if "," in num and "." not in num:
        parts = num.split(",")
        if len(parts[-1]) == 2:          # فاصلة عشرية أوروبية
            num = "".join(parts[:-1]) + "." + parts[-1]
        else:                             # فاصلة آلاف
            num = "".join(parts)
    else:
        num = num.replace(",", "")

    try:
        value = float(num)
    except ValueError:
        return None
    return value if value > 0 else None


# ----------------------------------------------------------
# استخراج السعر من صفحة المنتج
# ----------------------------------------------------------

def _walk_jsonld(node):
    """يمشي داخل بيانات JSON-LD ويرجع كل العناصر اللي نوعها Product."""
    if isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)
    elif isinstance(node, dict):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if "Product" in types:
            yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _walk_jsonld(node[key])


def _offer_price(offers):
    if isinstance(offers, list):
        prices = [p for p in (_offer_price(o) for o in offers) if p]
        return min(prices) if prices else None
    if isinstance(offers, dict):
        for key in ("price", "lowPrice"):
            p = parse_price(offers.get(key))
            if p:
                return p
        spec = offers.get("priceSpecification")
        if spec:
            return _offer_price(spec)
    return None


def _offer_in_stock(offers) -> bool | None:
    if isinstance(offers, list):
        flags = [_offer_in_stock(o) for o in offers]
        flags = [f for f in flags if f is not None]
        return any(flags) if flags else None
    if isinstance(offers, dict):
        avail = str(offers.get("availability", ""))
        if not avail:
            return None
        return "InStock" in avail or "LimitedAvailability" in avail
    return None


DISCONTINUED_RE = re.compile(r"is discontinued|المنتج متوقف|توقف بيع", re.I)


def _nextjs_product(html: str, url: str) -> dict | None:
    """
    مواقع Next.js تحط بيانات المنتج داخل سكربتات بصيغة مشفرة.
    ندور على كائن المنتج اللي فيه نفس اسم الرابط، ونأخذ منه السعر والصورة والاسم.
    """
    if "__next_f" not in html and "__NEXT_DATA__" not in html:
        return None
    text = html.replace('\\"', '"')
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    keys = ("displayPrice", "discountedPrice", "salePrice", "price")
    price_re = re.compile(r'"(%s)":\s*"?(\d+(?:\.\d+)?)' % "|".join(keys))

    for m in re.finditer(r'"slug":"%s"' % re.escape(slug), text):
        start, end = _object_bounds(text, m.start())
        if start is None:
            continue
        obj = text[start:end]
        top = _top_level(obj)
        found = {}
        for pm in price_re.finditer(top):
            found.setdefault(pm.group(1), float(pm.group(2)))
        price = next((found[k] for k in keys if found.get(k)), None)
        if not price:
            continue
        title = re.search(r'"(?:titleEn|titleAr|title|name)":"([^"]{3,300})"', top)
        image = None
        img_pos = obj.find('"mainImage":{')
        if img_pos != -1:
            s, e = _object_bounds(obj, img_pos + len('"mainImage":{'))
            urls = re.findall(r'"url":"([^"]+)"', obj[s:e]) if s is not None else []
            full = [u for u in urls if "thumbnail_" not in u]
            image = (full or urls or [None])[0]
        title_text = None
        if title:
            title_text = title.group(1).replace("\\\\u", "\\u")
            try:
                title_text = json.loads(f'"{title_text}"')
            except ValueError:
                pass
        # المخزون: طبيب الكمبيوتر يكتب حالة المخزون داخل بيانات المنتج
        in_stock = None
        oos = re.search(r'"outOfStock":(true|false)', top)
        qty = re.search(r'"stockQuantity":"?(-?\d+)', top)
        main_qty = re.search(r'"mainStockQuantity":"?(-?\d+)', top)
        if oos and oos.group(1) == "true":
            in_stock = False
        elif qty is not None:
            total = int(qty.group(1)) + (int(main_qty.group(1)) if main_qty else 0)
            in_stock = total > 0
        elif oos:
            in_stock = True
        return {"price": price,
                "title": title_text,
                "in_stock": in_stock,
                "image": urljoin(url, image) if image else None}
    return None


def _object_bounds(text: str, pos: int):
    """يرجع بداية ونهاية الكائن {...} اللي يحتوي الموضع pos."""
    depth, start = 0, None
    for i in range(pos, max(-1, pos - 20000), -1):
        c = text[i]
        if c == "}" and i != pos:
            depth += 1
        elif c == "{":
            if depth == 0:
                start = i
                break
            depth -= 1
    if start is None:
        return None, None
    depth = 0
    for i in range(start, min(len(text), start + 60000)):
        c = text[i]
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return start, i + 1
    return None, None


def _top_level(obj: str) -> str:
    """الحقول المباشرة فقط للكائن (بدون الكائنات المتداخلة داخله)."""
    out, depth = [], 0
    for c in obj:
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        elif depth == 1:
            out.append(c)
    return "".join(out)


def _find_image(soup: BeautifulSoup, url: str) -> str | None:
    """يدور على صورة المنتج بأكثر من طريقة."""
    # أمازون: الصورة الرئيسية
    img = soup.select_one("#landingImage, #imgTagWrapperId img, #main-image")
    if img:
        src = img.get("data-old-hires") or img.get("src")
        if not src and img.get("data-a-dynamic-image"):
            try:
                src = next(iter(json.loads(img["data-a-dynamic-image"])))
            except (ValueError, StopIteration):
                src = None
        if src and not src.startswith("data:"):
            return urljoin(url, src)
    for attrs in ({"property": "og:image"}, {"name": "og:image"},
                  {"name": "twitter:image"}, {"itemprop": "image"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return urljoin(url, tag["content"])
    link = soup.find("link", rel="image_src")
    if link and link.get("href"):
        return urljoin(url, link["href"])
    return None


def extract(html: str, url: str) -> dict:
    """
    يستخرج من صفحة المنتج: السعر والعنوان والصورة وحالة التوفر.
    الترتيب:
      1) بيانات JSON-LD (أدق شيء ومعظم المتاجر توفرها)
      2) وسوم meta
      3) محددات خاصة بكل متجر
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {"price": None, "title": None, "image": None,
              "in_stock": None, "method": None, "discontinued": False}

    # 1) JSON-LD
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for product in _walk_jsonld(data):
            price = _offer_price(product.get("offers"))
            if price:
                result["price"] = price
                result["title"] = product.get("name")
                img = product.get("image")
                if isinstance(img, list):
                    img = img[0] if img else None
                if isinstance(img, dict):
                    img = img.get("url")
                result["image"] = img
                result["in_stock"] = _offer_in_stock(product.get("offers"))
                result["method"] = "json-ld"
                break
        if result["price"]:
            break

    # 2) وسوم meta
    if not result["price"]:
        for attrs in (
            {"itemprop": "price"},
            {"property": "product:price:amount"},
            {"property": "og:price:amount"},
        ):
            tag = soup.find(attrs=attrs)
            if tag:
                price = parse_price(tag.get("content") or tag.get_text())
                if price:
                    result["price"] = price
                    result["method"] = "meta"
                    break

    # 2.5) بيانات Next.js المضمنة (طبيب الكمبيوتر يستخدمها)
    if not result["price"]:
        if DISCONTINUED_RE.search(html):
            result["discontinued"] = True
            result["in_stock"] = False
            return result
        nx = _nextjs_product(html, url)
        if nx:
            result.update(price=nx["price"], title=nx["title"], image=nx["image"],
                          in_stock=nx["in_stock"], method="nextjs")

    # 3) محددات المتجر
    if not result["price"]:
        for selector in STORE_SELECTORS.get(store_key(url), []):
            tag = soup.select_one(selector)
            if tag:
                price = parse_price(tag.get("data-price") or tag.get("content")
                                    or tag.get_text())
                if price:
                    result["price"] = price
                    result["method"] = "selector"
                    break

    # العنوان والصورة إذا ما جت من JSON-LD
    if not result["title"]:
        tag = soup.select_one("#productTitle")  # أمازون
        og = soup.find("meta", property="og:title")
        h1 = soup.find("h1")
        result["title"] = ((tag and tag.get_text(strip=True))
                           or (og and og.get("content"))
                           or (h1 and h1.get_text(strip=True)))
    if result["title"]:
        result["title"] = re.sub(r"\s+", " ", result["title"]).strip()[:200]
    if not result["image"]:
        result["image"] = _find_image(soup, url)
    elif not str(result["image"]).startswith("http"):
        result["image"] = urljoin(url, result["image"])

    # التوفر: أي علامة "نفدت الكمية" تغلب أي شي ثاني
    stock = _availability(soup, url)
    if stock is False:
        result["in_stock"] = False
    elif result["in_stock"] is None and stock is True:
        result["in_stock"] = True

    return result


# ----------------------------------------------------------
# فحص التوفر
# ----------------------------------------------------------

OOS_TEXT = re.compile(
    r"currently unavailable|out of stock|sold out|temporarily unavailable|"
    r"غير متوفر|غير متاح|نفد(?:ت)? (?:من )?(?:الكمية|المخزون)|نفذت الكمية|نفدت الكمية", re.I)
IN_STOCK_TEXT = re.compile(r"\bin stock\b|متوفر(?:ة)? في المخزون|متبقي|only \d+ left", re.I)


def _text(tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)) if tag else ""


def _availability(soup: BeautifulSoup, url: str) -> bool | None:
    """
    يرجع False لو المنتج نافد، True لو فيه علامة واضحة إنه متوفر، None لو مو واضح.
    نفحص أماكن محددة في الصفحة بس، عشان ما ننخدع بكلمة "نفدت الكمية"
    في منتجات ثانية مقترحة أسفل الصفحة.
    """
    key = store_key(url)

    # علامات عامة يستخدمها كثير من المتاجر
    for attrs in ({"property": "product:availability"}, {"property": "og:availability"},
                  {"itemprop": "availability"}):
        tag = soup.find(attrs=attrs)
        if tag:
            val = (tag.get("content") or tag.get("href") or "").lower()
            if "outofstock" in val.replace(" ", "") or "oos" == val or "discontinued" in val \
                    or "soldout" in val.replace(" ", ""):
                return False
            if "instock" in val.replace(" ", ""):
                return True

    if key == "amazon.sa":
        if soup.select_one("#outOfStock, #outOfStockBuyBox_feature_div #outOfStock"):
            return False
        avail = _text(soup.select_one("#availability"))
        if avail and OOS_TEXT.search(avail):
            return False
        has_cart = soup.select_one("#add-to-cart-button, #buy-now-button")
        if not has_cart and soup.select_one("#buybox-see-all-buying-choices, #unqualifiedBuyBox"):
            return False   # ما فيه شراء مباشر، بس "شوف كل العروض"
        if has_cart:
            return True
        return None

    if key == "infiniarc.com":
        if soup.select_one("#out_of_stock_message, .o_out_of_stock, #add_to_cart.disabled, "
                           "a#add_to_cart.out_of_stock, .oe_website_sale .text-danger.out_of_stock"):
            return False
        msgs = _text(soup.select_one(".availability_messages, #product_details .o_product_stock, "
                                     "#threshold_message"))
        if msgs and OOS_TEXT.search(msgs):
            return False
        if soup.select_one("#add_to_cart:not(.disabled), a.a-submit#add_to_cart"):
            return True
        return None

    if key == "noon.com":
        for sel in ('[data-qa*="out-of-stock"]', '[class*="OutOfStock"]', '[class*="outOfStock"]'):
            if soup.select_one(sel):
                return False
        box = _text(soup.select_one('[data-qa="pdp-add-to-cart"], [class*="AddToCart"], '
                                    '[class*="addToCart"]'))
        if box and OOS_TEXT.search(box):
            return False
        return None

    return None


# ----------------------------------------------------------
# الطلبات
# ----------------------------------------------------------

def make_session():
    """
    إذا مكتبة curl_cffi مثبتة نستخدمها، لأنها تتصرف مثل متصفح كروم حقيقي
    وتتخطى حماية بعض المتاجر مثل نون. وإذا مو مثبتة نرجع للطريقة العادية.
    """
    try:
        from curl_cffi import requests as browser_requests
        print("الوضع: متصفح محاكى (curl_cffi)")
        return browser_requests.Session(impersonate="chrome")
    except ImportError:
        print("الوضع: طلبات عادية (ثبّت curl_cffi عشان نون يشتغل)")
        return requests.Session()


class Blocked(RuntimeError):
    """المتجر بدأ يرفض الطلبات (علامة إنه ممكن يحظرنا)."""


BLOCK_CODES = {403, 429, 503}
CAPTCHA_RE = re.compile(r"captcha|robot check|are you a robot|access denied|"
                        r"automated access|unusual traffic", re.I)


def fetch(url: str, session) -> str:
    last_error = None
    for attempt in range(RETRIES + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code in BLOCK_CODES:
                raise Blocked(f"HTTP {resp.status_code}")
            if resp.status_code == 200 and len(resp.text) > 500:
                # صفحة تحقق بدل صفحة المنتج = بداية حظر
                if len(resp.text) < 15000 and CAPTCHA_RE.search(resp.text):
                    raise Blocked("صفحة تحقق من الروبوت")
                return resp.text
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code == 404:
                break  # الرابط مو موجود، ما في فايدة نعيد
        except Blocked:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = type(exc).__name__
            if "Timeout" in last_error:
                break  # المتجر ما يرد، ما في فايدة نعيد
        time.sleep(4 * (attempt + 1) + random.uniform(0, 2))
    raise RuntimeError(last_error or "فشل غير معروف")


def is_placeholder(url: str) -> bool:
    return "XXXX" in url


# ----------------------------------------------------------
# التشغيل الرئيسي
# ----------------------------------------------------------

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def _hours_since(ts: str | None, now_dt: datetime) -> float:
    if not ts:
        return 1e9
    try:
        return (now_dt - datetime.fromisoformat(ts)).total_seconds() / 3600
    except ValueError:
        return 1e9


def plan_requests(products: list, links_state: dict, now_dt: datetime, force: bool) -> list:
    """
    يرتب الطلبات بحيث:
      - المتاجر تتناوب (ما نضرب نفس المتجر ورا بعض)
      - الروابط اللي انفحصت قريب نتخطاها
      - الأقدم فحصاً يجي أول
      - ما نتعدى الحد الأقصى لكل متجر
    """
    per_store: dict[str, list] = {}
    for item in products:
        for url in item.get("links", []):
            if is_placeholder(url):
                continue
            age = _hours_since((links_state.get(url) or {}).get("checked_at"), now_dt)
            if not force and age < REFRESH_HOURS:
                continue
            per_store.setdefault(store_key(url), []).append((age, url))

    queues = []
    for items in per_store.values():
        items.sort(key=lambda x: -x[0])          # الأقدم أول
        queues.append([u for _, u in items[:MAX_PER_STORE]])
    random.shuffle(queues)

    plan = []
    while any(queues):                           # تناوب بين المتاجر
        for q in queues:
            if q:
                plan.append(q.pop(0))
    return plan


class Crawler:
    """يمسك الطلبات مع احترام الوقت بين طلبات نفس المتجر."""

    def __init__(self):
        self.session = make_session()
        self.last_hit: dict[str, float] = {}
        self.blocked: set[str] = set()
        self.fails: dict[str, int] = {}

    def get(self, url: str) -> str:
        key = store_key(url)
        if key in self.blocked:
            raise Blocked("متوقف في هذا التشغيل")
        wait = self.last_hit.get(key, 0) + random.uniform(*STORE_GAP) - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            html = fetch(url, self.session)
            self.fails[key] = 0
            return html
        except Blocked:
            self.blocked.add(key)
            raise
        except Exception:
            self.fails[key] = self.fails.get(key, 0) + 1
            if self.fails[key] >= MAX_STORE_FAILS:
                self.blocked.add(key)
            raise
        finally:
            self.last_hit[key] = time.time()
            time.sleep(random.uniform(*DELAY_RANGE))


def check_link(crawler: "Crawler", url: str) -> dict:
    """يفحص رابط واحد ويرجع النتيجة: available / out_of_stock / no_price / error / blocked."""
    try:
        html = crawler.get(url)
    except Blocked as exc:
        return {"result": "blocked", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"result": "error", "error": str(exc)}
    info = extract(html, url)
    base = {"title": info["title"], "image": info["image"]}
    if info.get("discontinued") or info["in_stock"] is False:
        return {**base, "result": "out_of_stock", "price": info["price"]}
    if not info["price"]:
        return {**base, "result": "no_price"}
    return {**base, "result": "available", "price": info["price"]}


def main(force: bool = False) -> int:
    config = yaml.safe_load(PRODUCTS_FILE.read_text(encoding="utf-8"))
    categories = config.get("categories", {})
    products = config.get("products", [])
    state = _load_json(STATE_FILE)
    links = state.setdefault("links", {})        # حالة كل رابط
    prods = state.setdefault("products", {})     # سجل الأسعار وصورة كل قطعة
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec="seconds")

    plan = plan_requests(products, links, now_dt, force)
    total_links = sum(len(p.get("links", [])) for p in products)
    print(f"بنفحص {len(plan)} رابط من أصل {total_links} "
          f"(الباقي انفحص قبل أقل من {REFRESH_HOURS} ساعات)")

    crawler = Crawler()
    to_confirm = []                    # روابط طلعت نافدة ونبي نتأكد منها
    counts = {"available": 0, "out_of_stock": 0, "no_price": 0, "error": 0, "blocked": 0}

    def apply(url: str, r: dict, confirmed_oos: bool = False):
        st = links.setdefault(url, {})
        st["store"] = store_name(url)
        if r["result"] in ("error", "blocked"):
            st["last_error"] = r["error"]   # نخلي آخر حالة معروفة زي ما هي
            return
        st["checked_at"] = now
        st.pop("last_error", None)
        for k in ("title", "image"):
            if r.get(k):
                st[k] = r[k]
        if r["result"] == "available":
            st.update(status="available", price=r["price"], seen_at=now, oos_since=None)
        elif r["result"] == "out_of_stock":
            if confirmed_oos:
                st["status"] = "out_of_stock"
                st["oos_since"] = st.get("oos_since") or now
        else:  # no_price
            st["status"] = "no_price"

    for n, url in enumerate(plan, 1):
        sname = store_name(url)
        if store_key(url) in crawler.blocked:
            continue
        r = check_link(crawler, url)
        counts[r["result"]] += 1
        tag = f"[{n}/{len(plan)}]"
        if r["result"] == "available":
            print(f"{tag} ✓ {sname}: {r['price']:.2f} ر.س")
        elif r["result"] == "out_of_stock":
            print(f"{tag} … {sname}: يبين نافد، بنتأكد منه آخر التشغيل")
            to_confirm.append(url)
            continue
        elif r["result"] == "no_price":
            print(f"{tag} ✗ {sname}: ما لقيت السعر")
        elif r["result"] == "blocked":
            print(f"{tag} ⛔ {sname}: {r['error']} — وقفنا هالمتجر في هذا التشغيل عشان ما ينحظر")
        else:
            print(f"{tag} ✗ {sname}: {r['error']}")
        apply(url, r)

    # ---- التأكيد: نعيد فحص اللي طلع نافد قبل ما نخفيه ----
    if to_confirm:
        print(f"\nنتأكد من {len(to_confirm)} قطعة طلعت نافدة...")
        time.sleep(CONFIRM_WAIT)
    for url in to_confirm:
        r = check_link(crawler, url)
        if r["result"] == "out_of_stock":
            print(f"   ✗ {store_name(url)}: نافد فعلاً، بنخفيه من الموقع لين يرجع")
            apply(url, r, confirmed_oos=True)
        elif r["result"] == "available":
            print(f"   ✓ {store_name(url)}: طلع متوفر ({r['price']:.2f} ر.س)")
            apply(url, r)
        else:
            print(f"   ? {store_name(url)}: ما قدرنا نتأكد، نخليه على حالته السابقة")

    # ---- الصور ----
    fetch_images(products, links, prods, crawler)

    # ---- نبني ملف الموقع: المتوفر فقط ----
    out_products, hidden, hidden_items = [], 0, []
    for item in products:
        name = item["name"]
        pstate = prods.setdefault(name, {})
        offers = []
        for url in item.get("links", []):
            st = links.get(url) or {}
            fresh = _hours_since(st.get("seen_at"), now_dt) <= MAX_STALE_HOURS
            if st.get("status") == "available" and st.get("price") and fresh:
                offers.append({"store": st["store"], "url": url, "price": st["price"],
                               "title": st.get("title"), "in_stock": True})
        if not offers:
            hidden += 1
            hidden_items.append({"name": name, "category": item.get("category"),
                                 "reason": "نافد" if any((links.get(u) or {}).get("status") == "out_of_stock"
                                                        for u in item.get("links", [])) else "ما انفحص أو بدون سعر"})
            continue
        offers.sort(key=lambda o: o["price"])
        best = offers[0]

        history = pstate.setdefault("history", [])
        last = history[-1] if history else None
        if (not last or abs(last["price"] - best["price"]) > 0.01
                or _hours_since(last.get("t"), now_dt) > 20):
            if last and abs(last["price"] - best["price"]) > 0.01:
                pstate["previous_best"] = last["price"]
            history.append({"t": now, "price": best["price"]})
        del history[:-HISTORY_LIMIT]

        out_products.append({
            "name": name,
            "category": item.get("category", "other"),
            "image": pstate.get("image"),
            "offers": offers,
            "best": best,
            "previous_best": pstate.get("previous_best"),
            "history": history,
        })

    # ننظف الحالة من روابط انشالت من القائمة
    active = {u for p in products for u in p.get("links", [])}
    for url in list(links):
        if url not in active:
            del links[url]

    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps({
        "updated_at": now, "currency": "SAR", "demo": False,
        "categories": categories, "products": out_products,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- تقرير صحة السحب للوحة التحكم ----
    per_store: dict[str, dict] = {}
    for url, st in links.items():
        s = per_store.setdefault(st.get("store") or store_name(url),
                                 {"available": 0, "out_of_stock": 0, "no_price": 0, "errors": 0, "never": 0})
        if st.get("last_error"):
            s["errors"] += 1
        status = st.get("status")
        if status in ("available", "out_of_stock", "no_price"):
            s[status] += 1
        elif not st.get("checked_at"):
            s["never"] += 1
    (SITE_DIR / "health.json").write_text(json.dumps({
        "updated_at": now,
        "run": {**counts, "confirmed_oos": len(to_confirm), "planned": len(plan),
                "blocked_stores": sorted(store_name("https://" + k) for k in crawler.blocked)},
        "products": {"total": len(products), "shown": len(out_products), "hidden": hidden},
        "stores": per_store,
        "hidden": hidden_items[:200],
        "missing_images": [p["name"] for p in out_products if not p.get("image")][:200],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nتم: {counts['available']} متوفر، {len(to_confirm)} نافد (انفحص مرتين)، "
          f"{counts['no_price']} بدون سعر، {counts['error'] + counts['blocked']} فشل")
    print(f"الموقع فيه {len(out_products)} قطعة متوفرة، و{hidden} قطعة مخفية لأنها مو متوفرة أو ما انفحصت")
    return 0


# ----------------------------------------------------------
# الصور
# ----------------------------------------------------------

def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:80] or "item"


def save_image(data: bytes, dest: Path) -> bool:
    """يتأكد إن الملف صورة حقيقية بمقاس معقول، ويحفظها بخلفية بيضاء ومقاس خفيف."""
    try:
        from PIL import Image
        img = Image.open(BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001
        return False
    w, h = img.size
    if w < 180 or h < 180 or max(w, h) / min(w, h) > 3.2:
        return False   # صغيرة أو شريط إعلاني
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((640, 640))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=86, optimize=True)
    return True


def _download(session, url: str) -> bytes | None:
    try:
        resp = session.get(url, headers={**HEADERS, "Accept": "image/*,*/*;q=0.8"}, timeout=TIMEOUT)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
    except Exception:  # noqa: BLE001
        pass
    return None


def search_images(session, query: str) -> list[str]:
    """يبحث عن صور القطعة باسمها بالضبط: قوقل أول، وبعدها بنق."""
    from urllib.parse import quote_plus
    found: list[str] = []
    q = quote_plus(query)
    try:
        r = session.get(f"https://www.google.com/search?q={q}&tbm=isch&hl=en&gl=sa",
                        headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            for u in re.findall(r'\["(https://[^"]+?\.(?:jpe?g|png|webp)[^"]*?)",\s*(\d+),\s*(\d+)\]', r.text):
                if "gstatic.com" not in u[0] and int(u[1]) >= 300:
                    found.append(json.loads(f'"{u[0]}"'))
    except Exception:  # noqa: BLE001
        pass
    time.sleep(random.uniform(2, 4))
    try:
        r = session.get(f"https://www.bing.com/images/search?q={q}&form=HDRSC2&first=1",
                        headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            found += [html_unescape(u) for u in re.findall(r'murl&quot;:&quot;(.*?)&quot;', r.text)]
    except Exception:  # noqa: BLE001
        pass
    seen, out = set(), []
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:8]


def fetch_images(products: list, links: dict, prods: dict, crawler: "Crawler") -> None:
    """
    لكل قطعة: ناخذ الصورة من صفحة المتجر نفسه (أمازون أول)، ولو ما فيه
    نبحث عنها باسمها بالضبط. الصورة تنحفظ في site/img عشان ما تختفي.
    """
    done = 0
    for item in products:
        if done >= MAX_IMAGES_PER_RUN:
            print(f"   (باقي صور، بنكملها في التشغيل الجاي)")
            break
        name = item["name"]
        pstate = prods.setdefault(name, {})
        current = pstate.get("image")
        if current and (SITE_DIR / current).exists():
            continue
        dest = IMG_DIR / f"{_slug(name)}.jpg"
        rel = f"img/{dest.name}"

        candidates = []
        for url in sorted(item.get("links", []), key=lambda u: "amazon" not in u):
            img = (links.get(url) or {}).get("image")
            if img and img not in candidates:
                candidates.append(img)

        ok = False
        for src in candidates:
            data = _download(crawler.session, src)
            if data and save_image(data, dest):
                ok = True
                break
        if not ok and not pstate.get("search_tried_at"):
            pstate["search_tried_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for src in search_images(crawler.session, name):
                data = _download(crawler.session, src)
                if data and save_image(data, dest):
                    ok = True
                    break
        if ok:
            pstate["image"] = rel
            done += 1
            print(f"   🖼  صورة: {name}")


def debug(url: str) -> int:
    """
    يفحص رابط واحد ويحفظ الصفحة في ملف debug_page.html
    التشغيل:  python scraper.py --debug الرابط
    """
    session = make_session()
    try:
        html = fetch(url, session)
    except Exception as exc:  # noqa: BLE001
        print(f"فشل فتح الصفحة: {exc}")
        return 1
    out = ROOT / "debug_page.html"
    out.write_text(html, encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    info = extract(html, url)
    print(f"حجم الصفحة: {len(html):,} حرف")
    print(f"بيانات منظمة: {len(soup.find_all('script', type='application/ld+json'))}")
    print(f"السعر: {info['price']}  الطريقة: {info['method']}")
    print(f"العنوان: {info['title']}")
    print(f"\nالصفحة محفوظة في: {out}")
    print("أرسل هذا الملف عشان نضبط قراءة السعر لهذا المتجر")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--debug":
        sys.exit(debug(sys.argv[2]))
    # --all يفحص كل الروابط حتى اللي انفحصت قريب
    sys.exit(main(force="--all" in sys.argv))
