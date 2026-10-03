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

# --- LÓGICA DEL BOT ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("❌ No se encontró la variable de entorno TELEGRAM_TOKEN")

bot = telebot.TeleBot(TOKEN)
user_sessions = {}

@bot.message_handler(commands=['start'])
def send_welcome(m):
    bot.reply_to(m, "🤖 ¡Bot multimedia seguro activo!\n\n• Envía `/password <tu_clave>` para la contraseña.\n• Envía fotos, videos, documentos o notas circulares.\n• Envía `/comprimir` para crear tu ZIP protegido.")

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

# --- MANEJO ROBUSTO DE ARCHIVOS ---
@bot.message_handler(content_types=['document', 'photo', 'video', 'video_note'])
def handle_files(m):
    uid = m.from_user.id
    if uid not in user_sessions:
        user_sessions[uid] = {"files": [], "password": "DefaultPassword123"}
    
    f_info, f_name = None, ""
    
    if m.document:
        f_info = bot.get_file(m.document.file_id)
        f_name = m.document.file_name or f"documento_{m.document.file_unique_id}"
    elif m.photo:
        f_info = bot.get_file(m.photo[-1].file_id)
        f_name = f"foto_{m.photo[-1].file_unique_id}.jpg"
    elif m.video:
        f_info = bot.get_file(m.video.file_id)
        f_name = m.video.file_name or f"video_{m.video.file_unique_id}.mp4"
    elif m.video_note:
        f_info = bot.get_file(m.video_note.file_id)
        f_name = f"nota_circular_{m.video_note.file_unique_id}.mp4"

    if f_info:
        down = bot.download_file(f_info.file_path)
        path = f"temp_{uid}_{f_name}"
        with open(path, "wb") as f:
            f.write(down)
        
        # Guardamos como objeto estructurado para evitar errores de nombres nulos
        user_sessions[uid]["files"].append({"path": path, "name": f_name})
        bot.reply_to(m, f"📥 Archivo añadido al lote: `{f_name}`", parse_mode="Markdown")

@bot.message_handler(commands=['comprimir'])
def compress_files(m):
    uid = m.from_user.id
    if uid not in user_sessions or not user_sessions[uid]["files"]:
        return bot.reply_to(m, "⚠️ No hay archivos acumulados.")
    
    sess = user_sessions[uid]
    zname = f"archivo_protegido_{uid}.zip"
    pwd = sess["password"]
    bot.reply_to(m, "🗜️ Generando ZIP protegido con AES-256...")
    
    try:
        with pyzipper.AESZipFile(zname, "w", compression=pyzipper.ZIP_DEFLATED, encryption="AES_256") as zf:
            zf.setpassword(pwd.encode("utf-8"))
            for file_item in sess["files"]:
                # Añade el archivo usando su nombre limpio guardado previamente
                zf.write(file_item["path"], arcname=file_item["name"])
                
        with open(zname, "rb") as zf:
            bot.send_document(m.chat.id, zf, caption=f"🔒 ¡Lote comprimido!\nContraseña: `{pwd}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(m, f"❌ Error: {e}")
    finally:
        # Limpieza de archivos temporales
        for file_item in sess["files"]:
            if os.path.exists(file_item["path"]):
                os.remove(file_item["path"])
        if os.path.exists(zname):
            os.remove(zname)
        sess["files"] = []

if __name__ == "__main__":
    print("🤖 Bot iniciado correctamente en la nube...")
    bot.infinity_polling()
