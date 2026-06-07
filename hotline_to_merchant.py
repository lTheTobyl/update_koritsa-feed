#!/usr/bin/env python3
"""
Конвертер фіду Хорошоп (формат Hotline / Prom XML) -> Google Merchant Center (RSS 2.0).

Використання:
    # з URL фіду (так робитиме автооновлення):
    python hotline_to_merchant.py --url "https://ВАШ-САЙТ/export/hotline.xml" --out merchant.xml
    # або з локального файлу:
    python hotline_to_merchant.py --in hotline.xml --out merchant.xml
"""
import argparse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

G = "http://base.google.com/ns/1.0"          # простір імен Google Merchant
CURRENCY = "UAH"                              # priceRUAH у цьому фіді = гривні
SITE_LINK = "https://koritsa.net.ua"         # головна сторінка магазину
LEAD_DAYS = 10                               # за скільки днів привозите товар "під замовлення"

# Як трактувати <stock> -> g:availability.
# Для цього магазину "під замовлення / під замовлення" = товару просто немає
# (на сторінці "Немає в наявності" + кнопка "Повідомити, коли з'явиться") -> out_of_stock.
# backorder/preorder тут не використовуються (вони вимагали б availability_date).
AVAILABILITY_MAP = {
    "в наличии": "in_stock", "в наявності": "in_stock", "є в наявності": "in_stock",
    "нет в наличии": "out_of_stock", "немає в наявності": "out_of_stock",
    "под заказ": "out_of_stock", "під замовлення": "out_of_stock",
    "ожидается": "out_of_stock", "очікується": "out_of_stock",
}

# Дата доступності для backorder/preorder = сьогодні + LEAD_DAYS (у UTC, без проблем із DST).
# Фід регенерується -> дата сама зсувається вперед і лишається актуальною.
AVAIL_DATE = (datetime.now(timezone.utc) + timedelta(days=LEAD_DAYS)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def load(args):
    if args.url:
        req = urllib.request.Request(args.url, headers={"User-Agent": "feed-converter/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    with open(args.infile, "rb") as f:
        return f.read()


def t(el, tag, default=""):
    c = el.find(tag)
    return c.text.strip() if (c is not None and c.text) else default


def availability(stock):
    return AVAILABILITY_MAP.get(stock.strip().lower(), "in_stock" if stock else "out_of_stock")


def category_paths(root):
    names, parents = {}, {}
    for c in root.findall(".//categories/category"):
        cid = t(c, "id")
        names[cid] = t(c, "name")
        parents[cid] = t(c, "parentId")
    out = {}
    for cid in names:
        parts, cur, seen = [], cid, set()
        while cur and cur in names and cur not in seen:
            seen.add(cur)
            parts.append(names[cur])
            cur = parents.get(cur) or ""
        out[cid] = " > ".join(reversed(parts))
    return out


def convert(data):
    root = ET.fromstring(data)
    firm = t(root, "firmName") or "Shop"
    cats = category_paths(root)

    ET.register_namespace("g", G)
    rss = ET.Element("rss", {"version": "2.0"})
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = firm
    ET.SubElement(ch, "link").text = SITE_LINK
    ET.SubElement(ch, "description").text = f"Google Merchant feed — {firm}"

    n = 0
    for it in root.findall(".//items/item"):
        name, url, price = t(it, "name"), t(it, "url"), t(it, "priceRUAH")
        if not (name and url and price):
            continue  # пропускаємо неповні позиції
        item = ET.SubElement(ch, "item")

        def g(tag, val):
            ET.SubElement(item, f"{{{G}}}{tag}").text = val

        g("id", t(it, "code") or t(it, "id"))
        g("title", name[:150])
        if t(it, "description"):
            g("description", t(it, "description")[:5000])
        g("link", url)
        if t(it, "image"):
            g("image_link", t(it, "image"))
        avail = availability(t(it, "stock"))
        g("availability", avail)
        if avail in ("backorder", "preorder"):
            g("availability_date", AVAIL_DATE)
        g("price", f"{price} {CURRENCY}")
        g("condition", "new" if t(it, "condition", "0") in ("0", "new", "") else "used")
        vendor = t(it, "vendor")
        if vendor:
            g("brand", vendor)
        # У фіді немає GTIN і реального MPN (code — це внутрішній артикул магазину,
        # а не номер виробника). За правилами Google такий артикул НЕ можна
        # видавати за mpn — натомість явно повідомляємо, що ідентифікаторів немає.
        g("identifier_exists", "no")
        cpath = cats.get(t(it, "categoryId"))
        if cpath:
            g("product_type", cpath)
        n += 1

    ET.indent(rss, space="  ")
    return ET.ElementTree(rss), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--in", dest="infile")
    ap.add_argument("--out", default="merchant.xml")
    args = ap.parse_args()
    if not args.url and not args.infile:
        ap.error("вкажіть --url або --in")
    tree, n = convert(load(args))
    tree.write(args.out, encoding="utf-8", xml_declaration=True)
    print(f"Готово: {n} товарів -> {args.out}")


if __name__ == "__main__":
    main()
