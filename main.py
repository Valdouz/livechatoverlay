import discord
import asyncio
from aiohttp import web
import json
import os
import threading
import time
import ctypes

# --- Chargement config ---
with open("config.json", "r") as f:
    config = json.load(f)

DISCORD_TOKEN = config["discord_token"]
CHANNEL_ID    = int(config["channel_id"])
PORT          = config.get("port", 3000)
IMG_DURATION  = config.get("image_duration_seconds", 8)

# --- Clients WebSocket connectés ---
ws_clients = set()

async def broadcast(data: dict):
    msg = json.dumps(data)
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_str(msg)
        except Exception:
            dead.add(ws)
    ws_clients -= dead

# --- Bot Discord ---
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f"Bot connecté : {bot.user}")
    print(f"Écoute le channel ID : {CHANNEL_ID}")

@bot.event
async def on_message(message: discord.Message):
    if message.channel.id != CHANNEL_ID:
        return
    if not message.attachments:
        return

    for att in message.attachments:
        ct = att.content_type or ""
        if ct.startswith("image/") or ct.startswith("video/"):
            is_video = ct.startswith("video/")
            await broadcast({
                "url":      att.url,
                "type":     "video" if is_video else "image",
                "author":   message.author.display_name,
                "duration": IMG_DURATION,
            })
            kind = "vidéo" if is_video else "image"
            print(f"→ {message.author.display_name} a envoyé {kind} : {att.filename}")
            break

# --- Serveur web ---
async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    try:
        async for _ in ws:
            pass
    finally:
        ws_clients.discard(ws)
    return ws

HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlay.html")

async def index_handler(request):
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read().replace("{{PORT}}", str(PORT))
    return web.Response(text=html, content_type="text/html")

async def run_server_and_bot():
    app = web.Application()
    app.router.add_get("/",   index_handler)
    app.router.add_get("/ws", ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"Serveur démarré sur le port {PORT}")
    await bot.start(DISCORD_TOKEN)

def start_background():
    asyncio.run(run_server_and_bot())

# --- Lancement ---
if __name__ == "__main__":
    # Bot + serveur dans un thread en arrière-plan
    t = threading.Thread(target=start_background, daemon=True)
    t.start()
    time.sleep(2)  # Laisser le serveur démarrer

    # Taille de l'écran (Win32, pas de dépendance extra)
    user32 = ctypes.windll.user32
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)

    # Fenêtre overlay transparente, toujours au premier plan, clic traversant
    import webview

    TITLE = "LiveChatOverlay_9f3a"

    def on_shown():
        """Rend la fenêtre transparente aux clics (Win32)."""
        try:
            import win32gui
            import win32con
            hwnd = win32gui.FindWindow(None, TITLE)
            if hwnd:
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                win32gui.SetWindowLong(
                    hwnd, win32con.GWL_EXSTYLE,
                    style | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
                )
                print("Fenêtre en mode clic-traversant activé.")
        except Exception as e:
            print(f"(clic-traversant non disponible : {e})")

    win = webview.create_window(
        TITLE,
        f"http://localhost:{PORT}",
        transparent=True,
        frameless=True,
        on_top=True,
        width=screen_w,
        height=screen_h,
        x=0,
        y=0,
        shadow=False,
    )
    win.events.shown += on_shown
    webview.start()
