"""اختبارات استخراج السعر. التشغيل:  python -m pytest tests"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import extract, parse_price, store_key, store_name  # noqa: E402


def test_parse_price_formats():
    assert parse_price("1,299.00 ر.س") == 1299.0
    assert parse_price("SAR 2,849") == 2849.0
    assert parse_price("١٬٢٩٩٫٥٠ ريال") == 1299.5
    assert parse_price("1299,50") == 1299.5
    assert parse_price("1 299") == 1299.0
    assert parse_price(899) == 899.0
    assert parse_price("غير متوفر") is None
    assert parse_price(None) is None


def test_store_detection():
    assert store_key("https://www.amazon.sa/dp/B0X") == "amazon.sa"
    assert store_name("https://www.noon.com/saudi-ar/x/p/") == "نون"
    assert store_key("https://shop.example.sa/p/1") == "shop.example.sa"


def test_jsonld_product():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"BreadcrumbList"},
      {"@type":"Product","name":"Ryzen 5 7600","image":["https://img/1.jpg"],
       "offers":[{"@type":"Offer","price":"899.00","priceCurrency":"SAR",
                  "availability":"https://schema.org/InStock"},
                 {"@type":"Offer","price":"949.00","priceCurrency":"SAR"}]}
    ]}
    </script></head><body>""" + "x" * 600 + "</body></html>"
    r = extract(html, "https://shop.example.sa/p/1")
    assert r["price"] == 899.0
    assert r["title"] == "Ryzen 5 7600"
    assert r["image"] == "https://img/1.jpg"
    assert r["in_stock"] is True
    assert r["method"] == "json-ld"


def test_meta_fallback():
    html = '<meta property="product:price:amount" content="2,349.00"><h1>RTX</h1>'
    r = extract(html, "https://shop.example.sa/p/2")
    assert r["price"] == 2349.0
    assert r["title"] == "RTX"
    assert r["method"] == "meta"


def test_amazon_selector_fallback():
    html = """<div id="corePrice_feature_div">
      <span class="a-price"><span class="a-offscreen">ر.س.‏ 1,849.00</span></span>
    </div>"""
    r = extract(html, "https://www.amazon.sa/dp/B0TEST")
    assert r["price"] == 1849.0
    assert r["method"] == "selector"


def test_out_of_stock():
    html = """<script type="application/ld+json">
    {"@type":"Product","name":"PSU","offers":{"price":450,
     "availability":"https://schema.org/OutOfStock"}}</script>"""
    r = extract(html, "https://shop.example.sa/p/3")
    assert r["price"] == 450.0
    assert r["in_stock"] is False


def test_no_price():
    assert extract("<html><h1>Nothing</h1></html>", "https://x.sa/")["price"] is None


def test_new_stores_detected():
    assert store_name("https://pcd.com.sa/en/product/x") == "طبيب الكمبيوتر"
    assert store_name("https://www.infiniarc.com/en/shop/x-8924") == "إنفني أرك"
    assert store_name("https://saudi.microless.com/x") == "مايكروليس"


def test_infiniarc_odoo_price():
    html = """<div class="product_price"><b class="oe_price">
      <span class="oe_currency_value">2,899.00</span> SR</b></div>"""
    r = extract(html, "https://www.infiniarc.com/en/shop/x-8924")
    assert r["price"] == 2899.0


def test_pcd_data_price_attribute():
    html = '<div data-price="3149.5"></div>'
    r = extract(html, "https://pcd.com.sa/product/x")
    assert r["price"] == 3149.5


def test_nextjs_embedded_price():
    # صيغة مشابهة لموقع طبيب الكمبيوتر: البيانات داخل سكربت بعلامات تنصيص مهربة
    html = ('<script>self.__next_f.push([1,"{\\"related\\":[{\\"slug\\":\\"other\\",'
            '\\"price\\":99,\\"displayPrice\\":89}],\\"product\\":{\\"id\\":5,'
            '\\"slug\\":\\"rtx-5070-eagle\\",\\"price\\":2999,\\"discountedPrice\\":2799,'
            '\\"displayPrice\\":2799}}"])</script>')
    r = extract(html, "https://pcd.com.sa/en/product/rtx-5070-eagle")
    assert r["price"] == 2799.0
    assert r["method"] == "nextjs"


def test_discontinued_page():
    html = '<script>self.__next_f=[]</script><div>Looks like the product (x) is discontinued</div>'
    r = extract(html, "https://pcd.com.sa/en/product/x")
    assert r["price"] is None
    assert r["discontinued"] is True


def test_nextjs_image_and_title():
    html = ('<script>self.__next_f.push([1,"{\\"product\\":{\\"id\\":5,'
            '\\"slug\\":\\"rtx-5070-eagle\\",\\"titleEn\\":\\"Gigabyte RTX 5070 Eagle\\",'
            '\\"mainImage\\":{\\"formats\\":{\\"thumbnail\\":{\\"url\\":\\"/uploads/thumbnail_a.webp\\"}},'
            '\\"url\\":\\"/uploads/a.webp\\"},\\"price\\":2999,\\"displayPrice\\":2799}}"])</script>')
    r = extract(html, "https://pcd.com.sa/en/product/rtx-5070-eagle")
    assert r["price"] == 2799.0
    assert r["title"] == "Gigabyte RTX 5070 Eagle"
    assert r["image"] == "https://pcd.com.sa/uploads/a.webp"


def test_amazon_image_and_title():
    html = """<span id="productTitle">  ASUS Prime RTX 5070  </span>
    <div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">2,599.00 ر.س</span></span></div>
    <img id="landingImage" src="data:image/gif;base64,xx"
         data-old-hires="https://m.media-amazon.com/images/I/big.jpg">"""
    r = extract(html, "https://www.amazon.sa/dp/B0TEST")
    assert r["title"] == "ASUS Prime RTX 5070"
    assert r["image"] == "https://m.media-amazon.com/images/I/big.jpg"


# ---------------- التوفر ----------------

def test_amazon_unavailable():
    html = """<span id="productTitle">RTX 5070</span>
    <div id="availability"><span class="a-color-price">Currently unavailable.</span></div>
    <div id="outOfStock">We don't know when or if this item will be back in stock.</div>"""
    assert extract(html, "https://www.amazon.sa/dp/B0TEST")["in_stock"] is False


def test_amazon_unavailable_arabic():
    html = """<div id="availability"><span>غير متوفر حاليًا.</span></div>
    <div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">999 ر.س</span></span></div>"""
    assert extract(html, "https://www.amazon.sa/dp/B0TEST")["in_stock"] is False


def test_amazon_in_stock():
    html = """<div id="availability"><span>In Stock</span></div>
    <div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">999 ر.س</span></span></div>
    <input id="add-to-cart-button" type="submit">"""
    r = extract(html, "https://www.amazon.sa/dp/B0TEST")
    assert r["in_stock"] is True and r["price"] == 999.0


def test_related_product_does_not_trigger_oos():
    # منتج مقترح أسفل الصفحة مكتوب عليه نافد، المنتج نفسه متوفر
    html = """<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">999 ر.س</span></span></div>
    <input id="add-to-cart-button"><div class="related">Other item - Out of stock</div>"""
    assert extract(html, "https://www.amazon.sa/dp/B0TEST")["in_stock"] is True


def test_infiniarc_out_of_stock():
    html = """<div class="product_price"><span class="oe_currency_value">2,899.00</span></div>
    <div id="out_of_stock_message">Temporarily out of stock</div>"""
    r = extract(html, "https://www.infiniarc.com/en/shop/x-8924")
    assert r["price"] == 2899.0 and r["in_stock"] is False


def test_jsonld_outofstock_wins():
    html = """<script type="application/ld+json">{"@type":"Product","name":"PSU",
      "offers":{"price":450,"availability":"https://schema.org/OutOfStock"}}</script>"""
    assert extract(html, "https://www.noon.com/saudi-en/x/N1/p/")["in_stock"] is False


def test_pcd_stock_fields():
    def page(oos, qty, main):
        return ('<script>self.__next_f.push([1,"{\\"product\\":{\\"slug\\":\\"gpu-x\\",'
                '\\"displayPrice\\":2799,\\"outOfStock\\":%s,\\"stockQuantity\\":\\"%s\\",'
                '\\"mainStockQuantity\\":%s}}"])</script>' % (oos, qty, main))
    url = "https://pcd.com.sa/en/product/gpu-x"
    assert extract(page("false", 4, 0), url)["in_stock"] is True
    assert extract(page("false", 0, 0), url)["in_stock"] is False
    assert extract(page("false", 0, 12), url)["in_stock"] is True
    assert extract(page("true", 4, 0), url)["in_stock"] is False
