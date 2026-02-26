import json
import os
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

OFFSET_FILE = os.path.join(os.path.dirname(__file__), "bot_offset.json")


def load_offset():
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE, "r") as f:
            return json.load(f).get("offset", 0)
    return 0


def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        json.dump({"offset": offset}, f)


def fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode()


def get_latest_products(count=4):
    """Get the N most recent products across all collections via JSON API."""
    all_products = []
    for collection in COLLECTIONS:
        url = f"{BASE_URL}/collections/{collection}/products.json?limit=4&sort_by=created-descending"
        try:
            data = json.loads(fetch_url(url))
            for p in data.get("products", []):
                handle = p.get("handle", "")
                title = p.get("title", "")
                image = p["images"][0].get("src", "") if p.get("images") else ""
                price = p["variants"][0].get("price", "") if p.get("variants") else ""
                created = p.get("created_at", "")
                all_products.append({
                    "handle": handle,
                    "title": title,
                    "image": image,
                    "price": price,
                    "url": f"{BASE_URL}/collections/{collection}/products/{handle}",
                    "collection": collection,
                    "created_at": created,
                })
        except Exception as e:
            print(f"Error fetching {collection}: {e}")
            # Fallback: scrape HTML for first few
            try:
                html = fetch_url(f"{BASE_URL}/collections/{collection}")
                import re
                pattern = r'<a[^>]*href="(/collections/' + re.escape(collection) + r'/products/([^"]+))"'
                seen = set()
                for match in re.finditer(pattern, html):
                    path, handle = match.group(1), match.group(2)
                    if handle in seen:
                        continue
                    seen.add(handle)
                    start = match.end()
                    img_match = re.search(r'<img[^>]*src="(//circusbymaniac\.shop/cdn/shop/files/[^"]+)"', html[start:start+1000])
                    image = ""
                    if img_match:
                        image = "https:" + img_match.group(1)
                        image = re.sub(r'_\d+x\d+(@2x)?\.', '_600x600.', image)
                    price_match = re.search(r'¥([\d,]+)', html[start:start+1000])
                    price = price_match.group(0) if price_match else ""
                    all_products.append({
                        "handle": handle,
                        "title": handle.replace("-", " ").upper(),
                        "image": image,
                        "price": price,
                        "url": f"{BASE_URL}{path}",
                        "collection": collection,
                        "created_at": "",
                    })
                    if len(seen) >= 4:
                        break
            except Exception:
                pass
        time.sleep(0.3)

    # Sort by created_at descending, take top N
    all_products.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return all_products[:count]


def collection_label(slug):
    labels = {
        "ifsixwasnine-beyond-the-time-man": "IF SIX WAS NINE / BEYOND THE TIME",
        "ifsixwasnine-limited-man": "IF SIX WAS NINE / LIMITED",
        "lgb-beyond-the-time-man": "L.G.B. / BEYOND THE TIME",
        "lgb-limited-man": "L.G.B. / LIMITED",
    }
    return labels.get(slug, slug)


def send_telegram_photo(image_url, caption, chat_id):
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
        print(f"Photo failed: {e}")
        return send_telegram_message(caption, chat_id)


def send_telegram_message(text, chat_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def get_updates(offset=0):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=0"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return data.get("result", [])


def main():
    offset = load_offset()
    updates = get_updates(offset)
    
    handled = False
    for update in updates:
        offset = update["update_id"] + 1
        msg = update.get("message", {})
        text = msg.get("text", "")
        chat_id = msg.get("chat", {}).get("id")

        if not chat_id:
            continue

        if text.strip().lower() in ["/latest", "/latest@circusbymaniac_bot"]:
            print(f"Got /latest from {chat_id}")
            send_telegram_message("🔍 Fetching latest products...", chat_id)
            products = get_latest_products(4)
            if not products:
                send_telegram_message("❌ Could not fetch products right now.", chat_id)
            else:
                for p in products:
                    label = collection_label(p["collection"])
                    caption = f"<b>{p['title']}</b>\n"
                    if p["price"]:
                        caption += f"💴 ¥{p['price']}\n"
                    caption += f"📁 {label}\n"
                    caption += f"\n🔗 <a href=\"{p['url']}\">View product</a>"
                    if p["image"]:
                        send_telegram_photo(p["image"], caption, chat_id)
                    else:
                        send_telegram_message(caption, chat_id)
                    time.sleep(0.3)
            handled = True

        elif text.strip().lower() in ["/start", "/start@circusbymaniac_bot"]:
            send_telegram_message(
                "👋 Hey! I monitor new products on CIRCUS by MANIAC.\n\n"
                "Commands:\n/latest — show 4 most recent products",
                chat_id
            )
            handled = True

    save_offset(offset)
    if not handled:
        print("No commands to process.")
    print("Done.")


if __name__ == "__main__":
    main()
