import discord
import asyncio
from aiohttp import web
import json
import os
import socket

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(BASE_DIR, "config.json"), "r") as f:
    config = json.load(f)

DISCORD_TOKEN = config["discord_token"]
CHANNEL_ID    = int(config["channel_id"])
PORT          = config.get("port", 3000)
IMG_DURATION  = config.get("image_duration_seconds", 8)
MEDIA_SCALE   = config.get("media_scale", 30)

# ws -> {"ip": str, "host": str}
ws_clients = {}

async def broadcast(data: dict):
    msg = json.dumps(data)
    dead = []
    for ws in list(ws_clients):
        try:
            await ws.send_str(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.pop(ws, None)

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f"Bot connecté : {bot.user}")
    print(f"En écoute sur le channel : {CHANNEL_ID}")
    print(f"Overlay accessible sur : http://<votre-ip>:{PORT}")

@bot.event
async def on_message(message: discord.Message):
    try:
        if message.channel.id != CHANNEL_ID:
            return

        for att in message.attachments:
            ct = att.content_type or ""
            if ct.startswith("image/") or ct.startswith("video/"):
                is_video = ct.startswith("video/")
                await broadcast({
                    "url":      att.url,
                    "type":     "video" if is_video else "image",
                    "author":   message.author.display_name,
                    "message":  message.content,
                    "duration": IMG_DURATION,
                    "scale":    MEDIA_SCALE,
                })
                print(f"→ {message.author.display_name} : {'vidéo' if is_video else 'image'} ({att.filename})")
                return

        for embed in message.embeds:
            if embed.type == "gifv" and embed.video and embed.video.url:
                await broadcast({
                    "url":      embed.video.url,
                    "type":     "video",
                    "author":   message.author.display_name,
                    "message":  message.content,
                    "duration": IMG_DURATION,
                    "scale":    MEDIA_SCALE,
                })
                print(f"→ {message.author.display_name} : gif tenor")
                return

    except Exception as e:
        print(f"ERREUR on_message : {e}")

async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ip = request.remote
    try:
        host = socket.gethostbyaddr(ip)[0]
    except Exception:
        host = ip
    ws_clients[ws] = {"ip": ip, "host": host}
    print(f"+ Client connecté : {host} ({ip})")
    try:
        async for _ in ws:
            pass
    finally:
        ws_clients.pop(ws, None)
        print(f"- Client déconnecté : {host} ({ip})")
    return ws

HTML_PATH = os.path.join(BASE_DIR, "overlay.html")

async def index_handler(request):
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read().replace("{{PORT}}", str(PORT))
    return web.Response(text=html, content_type="text/html")

# ── API Admin ──────────────────────────────────────────────────────────────────

async def admin_clients(request):
    clients = [{"ip": v["ip"], "host": v["host"]} for v in ws_clients.values()]
    return web.json_response(clients)

async def admin_clear(request):
    await broadcast({"type": "clear"})
    return web.json_response({"ok": True})

async def admin_mute(request):
    await broadcast({"type": "mute"})
    return web.json_response({"ok": True})

async def admin_unmute(request):
    await broadcast({"type": "unmute"})
    return web.json_response({"ok": True})

# ── Lancement ─────────────────────────────────────────────────────────────────

async def main():
    app = web.Application()
    app.router.add_get("/",                index_handler)
    app.router.add_get("/ws",              ws_handler)
    app.router.add_get("/admin/clients",   admin_clients)
    app.router.add_post("/admin/clear",    admin_clear)
    app.router.add_post("/admin/mute",     admin_mute)
    app.router.add_post("/admin/unmute",   admin_unmute)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
