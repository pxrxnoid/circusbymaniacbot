import json
import os
import re
import time
import threading
import urllib.request
import urllib.parse

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
PORT = int(os.environ.get("PORT", 10000))

RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

BASE_URL = "https://circusbymaniac.shop"

COLLECTIONS = [
    "ifsixwasnine-beyond-the-time-man",
    "ifsixwasnine-limited-man",
    "lgb-beyond-the-time-man",
    "lgb-limited-man",
]

CHECK_INTERVAL = 600  # 10 minutes

# In-memory state
seen_products = set()
bot_offset = 0


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
            image = p["images"][0].get("src", "") if p.get("images") else ""
            price = p["variants"][0].get("price", "") if p.get("variants") else ""
            created = p.get("created_at", "")
            products.append({
                "handle": handle,
                "title": title,
                "image": image,
                "price": price,
                "url": f"{BASE_URL}/collections/{collection}/products/{handle}",
                "collection": collection,
                "created_at": created,
            })
        return products
    except Exception:
        return None


def fetch_all_products(collection):
    all_products = []
    page = 1
    while True:
        products = fetch_products_json(collection, page)
        if products is None or not products:
            break
        all_products.extend(products)
        if len(products) < 250:
            break
        page += 1
        time.sleep(0.5)
    return all_products


def get_latest_products(days=7):
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_products = []
    seen_handles = set()

    for collection in COLLECTIONS:
        page = 1
        while True:
            url = f"{BASE_URL}/collections/{collection}/products.json?limit=50&page={page}"
            try:
                data = json.loads(fetch_url(url))
                products = data.get("products", [])
                if not products:
                    break
                found_old = False
                for p in products:
                    handle = p.get("handle", "")
                    if handle in seen_handles:
                        continue
                    created_str = p.get("created_at", "")
                    if not created_str:
                        continue
                    # Parse ISO timestamp
                    created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    if created < cutoff:
                        found_old = True
                        continue
                    seen_handles.add(handle)
                    all_products.append({
                        "handle": handle,
                        "title": p.get("title", ""),
                        "image": p["images"][0].get("src", "") if p.get("images") else "",
                        "price": p["variants"][0].get("price", "") if p.get("variants") else "",
                        "url": f"{BASE_URL}/collections/{collection}/products/{handle}",
                        "collection": collection,
                        "created_at": created_str,
                    })
                if found_old or len(products) < 50:
                    break
                page += 1
            except Exception as e:
                print(f"Error fetching latest from {collection}: {e}")
                break
            time.sleep(0.3)

    all_products.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return all_products


def collection_label(slug):
    labels = {
        "ifsixwasnine-beyond-the-time-man": "IF SIX WAS NINE / BEYOND THE TIME",
        "ifsixwasnine-limited-man": "IF SIX WAS NINE / LIMITED",
        "lgb-beyond-the-time-man": "L.G.B. / BEYOND THE TIME",
        "lgb-limited-man": "L.G.B. / LIMITED",
    }
    return labels.get(slug, slug)


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
        print(f"Photo failed: {e}")
        return send_telegram_message(caption, chat_id)


def send_telegram_message(text, chat_id=None):
    chat_id = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def send_product(p, chat_id=None):
    label = collection_label(p["collection"])
    caption = f"🆕 <b>{p['title']}</b>\n"
    if p["price"]:
        caption += f"💴 ¥{p['price']}\n"
    caption += f"📁 {label}\n"
    caption += f"\n🔗 <a href=\"{p['url']}\">View product</a>"
    if p["image"]:
        send_telegram_photo(p["image"], caption, chat_id)
    else:
        send_telegram_message(caption, chat_id)


# ─── Product checker (runs every 10 min) ───

def check_new_products():
    global seen_products
    first_run = len(seen_products) == 0
    new_products = []

    for collection in COLLECTIONS:
        print(f"Checking {collection}...")
        try:
            products = fetch_all_products(collection)
            print(f"  Found {len(products)} products")
            for p in products:
                if p["handle"] not in seen_products:
                    new_products.append(p)
                    seen_products.add(p["handle"])
        except Exception as e:
            print(f"  Error: {e}")

    if first_run:
        print(f"First run — indexed {len(new_products)} products silently.")
        send_telegram_message(
            f"✅ Bot started! Monitoring 4 collections.\n"
            f"📦 Indexed {len(new_products)} existing products.\n\n"
            f"You'll get notified when something new drops.\n"
            f"Send /latest to see 4 most recent products."
        )
    elif new_products:
        print(f"{len(new_products)} new products found!")
        for p in new_products:
            send_product(p)
            time.sleep(0.5)
    else:
        print("No new products.")


def checker_loop():
    while True:
        try:
            check_new_products()
        except Exception as e:
            print(f"Checker error: {e}")
        print(f"Next check in {CHECK_INTERVAL}s...")
        time.sleep(CHECK_INTERVAL)


# ─── Telegram bot polling (handles /latest instantly) ───

def get_updates(offset=0):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return data.get("result", [])


def handle_command(text, chat_id):
    cmd = text.strip().lower().split("@")[0]

    if cmd == "/day":
        send_telegram_message("🔍 Fetching products added today...", chat_id)
        products = get_latest_products(1)
        if not products:
            send_telegram_message("No new products today.", chat_id)
        else:
            send_telegram_message(f"Found {len(products)} products from today:", chat_id)
            for p in products:
                send_product(p, chat_id)
                time.sleep(0.5)

    elif cmd == "/week":
        send_telegram_message("🔍 Fetching products added this week...", chat_id)
        products = get_latest_products(7)
        if not products:
            send_telegram_message("No new products this week.", chat_id)
        else:
            send_telegram_message(f"Found {len(products)} products from the last 7 days:", chat_id)
            for p in products:
                send_product(p, chat_id)
                time.sleep(0.5)

    elif cmd == "/start":
        send_telegram_message(
            "👋 I monitor new products on CIRCUS by MANIAC.\n\n"
            "/day — products added today\n"
            "/week — products added this week\n"
            "/status — bot info\n\n"
            "New drops are sent automatically.",
            chat_id
        )

    elif cmd == "/status":
        send_telegram_message(
            f"📊 Tracking {len(seen_products)} products across 4 collections.\n"
            f"Checking every {CHECK_INTERVAL // 60} minutes.",
            chat_id
        )


def bot_polling_loop():
    global bot_offset
    while True:
        try:
            updates = get_updates(bot_offset)
            for update in updates:
                bot_offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "")
                chat_id = msg.get("chat", {}).get("id")
                if chat_id and text.startswith("/"):
                    handle_command(text, chat_id)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)


# ─── Simple HTTP server to keep Render happy ───

def start_health_server():
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, format, *args):
            pass  # silence logs

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


# ─── Self-ping to keep Render awake ───

def self_ping_loop():
    while True:
        time.sleep(300)  # every 5 min
        if RENDER_URL:
            try:
                urllib.request.urlopen(RENDER_URL, timeout=10)
                print("Self-ping OK")
            except Exception:
                pass


# ─── Main ───

if __name__ == "__main__":
    print("Starting bot...")

    # Health check server (Render needs an open port)
    threading.Thread(target=start_health_server, daemon=True).start()
    print(f"Health server on port {PORT}")

    # Self-ping to prevent Render sleep
    threading.Thread(target=self_ping_loop, daemon=True).start()
    print("Self-ping started")

    # Product checker in background
    threading.Thread(target=checker_loop, daemon=True).start()
    print("Product checker started")

    # Telegram polling in main thread
    print("Bot polling started")
    bot_polling_loop()
