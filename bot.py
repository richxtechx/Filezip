import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
import pyzipper

# --- SERVIDOR WEB PARA RENDER ---
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheck)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# --- LÓGICA DEL BOT (Lee el token de las variables de entorno de Render) ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("❌ No se encontró la variable de entorno TELEGRAM_TOKEN")

bot = telebot.TeleBot(TOKEN)
user_sessions = {}

@bot.message_handler(commands=['start'])
def send_welcome(m):
    bot.reply_to(m, "🤖 ¡Bot seguro en la nube activo!\n\n• Envía `/password <tu_clave>`\n• Envía tus archivos\n• Envía `/comprimir`")

@bot.message_handler(commands=['password'])
def set_password(m):
    uid = m.from_user.id
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        return bot.reply_to(m, "❌ Indica la contraseña. Ejemplo: `/password mi_clave`")
    if uid not in user_sessions:
        user_sessions[uid] = {"files": [], "password": "DefaultPassword123"}
    user_sessions[uid]["password"] = args[1]
    bot.reply_to(m, "🔒 Contraseña guardada correctamente.")

@bot.message_handler(content_types=['document', 'photo', 'video'])
def handle_files(m):
    uid = m.from_user.id
    if uid not in user_sessions:
        user_sessions[uid] = {"files": [], "password": "DefaultPassword123"}
    f_info, f_name = None, ""
    if m.document:
        f_info = bot.get_file(m.document.file_id)
        f_name = m.document.file_name
    elif m.photo:
        f_info = bot.get_file(m.photo[-1].file_id)
        f_name = f"foto_{m.photo[-1].file_unique_id}.jpg"
    elif m.video:
        f_info = bot.get_file(m.video.file_id)
        f_name = m.video.file_name or f"video_{m.video.file_unique_id}.mp4"
    if f_info:
        down = bot.download_file(f_info.file_path)
        path = f"temp_{uid}_{f_name}"
        with open(path, "wb") as f:
            f.write(down)
        user_sessions[uid]["files"].append(path)
        bot.reply_to(m, f"📥 Archivo añadido: `{f_name}`", parse_mode="Markdown")

@bot.message_handler(commands=['comprimir'])
def compress_files(m):
    uid = m.from_user.id
    if uid not in user_sessions or not user_sessions[uid]["files"]:
        return bot.reply_to(m, "⚠️ No hay archivos acumulados.")
    sess = user_sessions[uid]
    zname = f"archivo_protegido_{uid}.zip"
    pwd = sess["password"]
    bot.reply_to(m, "🗜️ Generando ZIP protegido...")
    try:
        with pyzipper.AESZipFile(zname, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES_256) as zf:
            zf.setpassword(pwd.encode("utf-8"))
            for p in sess["files"]:
                zf.write(p, arcname=p.split("_", 2)[-1])
        with open(zname, "rb") as zf:
            bot.send_document(m.chat.id, zf, caption=f"🔒 ¡Lote comprimido!\nContraseña: `{pwd}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(m, f"❌ Error: {e}")
    finally:
        for p in sess["files"]:
            if os.path.exists(p): os.remove(p)
        if os.path.exists(zname): os.remove(zname)
        sess["files"] = []

if __name__ == "__main__":
    print("🤖 Bot iniciado de forma segura...")
    bot.infinity_polling()
