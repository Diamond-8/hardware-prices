"""
فحص ملف القائمة قبل التشغيل
===========================
يتأكد أن كل رابط شكله صحيح لصفحة منتج سعودية، وأنه ما في روابط مكررة،
وأن كل منتج قسمه موجود.

التشغيل:
    python check_links.py
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent

# شكل رابط صفحة المنتج في كل متجر
PATTERNS = {
    "amazon.sa": re.compile(r"^https://(www\.)?amazon\.sa/.*/dp/[A-Z0-9]{10}"),
    "noon.com": re.compile(r"^https://www\.noon\.com/saudi-(ar|en)/.+/p/?"),
    "pcd.com.sa": re.compile(r"^https://pcd\.com\.sa/(en/)?product/.+"),
    "infiniarc.com": re.compile(r"^https://(www\.)?infiniarc\.com/(en/)?shop/.+-\d+$"),
}


def store_of(url: str) -> str | None:
    for key in PATTERNS:
        if key in url.split("/")[2]:
            return key
    return None


def main() -> int:
    config = yaml.safe_load((ROOT / "products.yaml").read_text(encoding="utf-8"))
    categories = config.get("categories", {})
    problems = []
    seen = {}
    total = 0

    for product in config.get("products", []):
        name = product.get("name", "؟")
        if product.get("category") not in categories:
            problems.append(f"{name}: القسم غير معروف ({product.get('category')})")
        for url in product.get("links", []):
            total += 1
            if url in seen:
                problems.append(f"{name}: رابط مكرر (موجود أيضاً في {seen[url]})\n    {url}")
            seen[url] = name
            store = store_of(url)
            if store and not PATTERNS[store].search(url):
                problems.append(f"{name}: شكل الرابط مو صفحة منتج سعودية\n    {url}")

    print(f"{len(config.get('products', []))} منتج، {total} رابط")
    if problems:
        print(f"\nفي {len(problems)} مشكلة:")
        for p in problems:
            print(" -", p)
        return 1
    print("كل الروابط سليمة")
    return 0


if __name__ == "__main__":
    sys.exit(main())
