import json
import os
import re
import time
import urllib.request
import urllib.parse

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

BASE_URL = "https://circusbymaniac.shop"

COLLECTIONS = [
    "ifsixwasnine-beyond-the-time-man",
    "ifsixwasnine-limited-man",
    "lgb-beyond-the-time-man",
    "lgb-limited-man",
]

SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen_products.json")


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=2)


def fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode()


def fetch_products_json(collection, page=1):
    url = f"{BASE_URL}/collections/{collection}/products.json?limit=250&page={page}"
    try:
        data = json.loads(fetch_url(url))
        products = []
        for p in data.get("products", []):
            handle = p.get("handle", "")
            title = p.get("title", "")
            image = ""
            if p.get("images"):
                image = p["images"][0].get("src", "")
            price = ""
            if p.get("variants"):
                price = p["variants"][0].get("price", "")
            products.append({
                "handle": handle,
                "title": title,
                "image": image,
                "price": price,
                "url": f"{BASE_URL}/collections/{collection}/products/{handle}",
                "collection": collection,
            })
        return products
    except Exception:
        return None


def fetch_all_products_json(collection):
    all_products = []
    page = 1
    while True:
        products = fetch_products_json(collection, page)
        if products is None:
            if page == 1:
                return None
            break
        if not products:
            break
        all_products.extend(products)
        if len(products) < 250:
            break
        page += 1
        time.sleep(0.5)
    return all_products


def fetch_products_html(collection):
    html = fetch_url(f"{BASE_URL}/collections/{collection}")
    products = []
    pattern = r'<a[^>]*href="(/collections/' + re.escape(collection) + r'/products/([^"]+))"'
    seen_handles = set()
    for match in re.finditer(pattern, html):
        path, handle = match.group(1), match.group(2)
        if handle in seen_handles:
            continue
        seen_handles.add(handle)
        start = match.end()
        img_match = re.search(r'<img[^>]*src="(//circusbymaniac\.shop/cdn/shop/files/[^"]+)"', html[start:start+1000])
        image = ""
        if img_match:
            image = "https:" + img_match.group(1)
            image = re.sub(r'_\d+x\d+(@2x)?\.', '_600x600.', image)
        price_match = re.search(r'¥([\d,]+)', html[start:start+1000])
        price = price_match.group(0) if price_match else ""
        title_block = html[start:start+500]
        title_search = re.search(r'>\s*([A-Z][^<]{3,}[^<]*)\s*<', title_block)
        title = title_search.group(1).strip() if title_search else handle
        products.append({
            "handle": handle,
            "title": title,
            "image": image,
            "price": price,
            "url": f"{BASE_URL}{path}",
            "collection": collection,
        })
    return products


def fetch_products(collection):
    products = fetch_all_products_json(collection)
    if products is not None:
        return products
    return fetch_products_html(collection)


def send_telegram_photo(image_url, caption, chat_id=None):
    chat_id = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "photo": image_url,
        "caption": caption,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Failed to send photo, trying text: {e}")
        return send_telegram_message(caption, chat_id)


def send_telegram_message(text, chat_id=None):
    chat_id = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def collection_label(slug):
    labels = {
        "ifsixwasnine-beyond-the-time-man": "IF SIX WAS NINE / BEYOND THE TIME",
        "ifsixwasnine-limited-man": "IF SIX WAS NINE / LIMITED",
        "lgb-beyond-the-time-man": "L.G.B. / BEYOND THE TIME",
        "lgb-limited-man": "L.G.B. / LIMITED",
    }
    return labels.get(slug, slug)


def main():
    seen = load_seen()
    first_run = len(seen) == 0
    new_products = []

    for collection in COLLECTIONS:
        print(f"Checking {collection}...")
        try:
            products = fetch_products(collection)
            print(f"  Found {len(products)} products")
            for p in products:
                key = p["handle"]
                if key not in seen:
                    new_products.append(p)
                    seen.add(key)
        except Exception as e:
            print(f"  Error: {e}")

    if first_run:
        print(f"First run — indexed {len(new_products)} existing products silently.")
        send_telegram_message(f"✅ Bot started! Monitoring 4 collections.\n📦 Indexed {len(new_products)} existing products.\n\nYou'll get notified when something new drops.")
    elif new_products:
        print(f"\n{len(new_products)} new products found!")
        for p in new_products:
            label = collection_label(p["collection"])
            caption = f"🆕 <b>{p['title']}</b>\n"
            if p["price"]:
                caption += f"💴 ¥{p['price']}\n"
            caption += f"📁 {label}\n"
            caption += f"\n🔗 <a href=\"{p['url']}\">View product</a>"
            print(f"  Sending: {p['title']}")
            if p["image"]:
                send_telegram_photo(p["image"], caption)
            else:
                send_telegram_message(caption)
            time.sleep(0.3)
    else:
        print("No new products.")

    save_seen(seen)
    print("Done.")


if __name__ == "__main__":
    main()
