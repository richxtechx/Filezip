import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
import pyzipper

# --- SERVIDOR WEB PARA RENDER (Health Check) ---
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

# --- LÓGICA DEL BOT DE TELEGRAM ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("❌ No se encontró la variable de entorno TELEGRAM_TOKEN")

bot = telebot.TeleBot(TOKEN)
user_sessions = {}

@bot.message_handler(commands=['start'])
def send_welcome(m):
    bot.reply_to(m, "🤖 ¡Bot multimedia seguro activo!\n\n1️⃣ Envía `/password <tu_clave>`\n2️⃣ Envía tus archivos (fotos, videos, documentos o notas circulares)\n3️⃣ Envía `/comprimir` para obtener tu ZIP protegido.")

@bot.message_handler(commands=['password'])
def set_password(m):
    uid = m.from_user.id
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        return bot.reply_to(m, "❌ Indica la contraseña. Ejemplo: `/password mi_clave`")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"files": [], "password": "DefaultPassword123"}
    
    user_sessions[uid]["password"] = args[1]
    # Mensaje exacto solicitado
    bot.reply_to(m, "🔒 Contraseña guardada correctamente.\n\n📥 **Ahora puedes enviar los archivos** que deseas comprimir (fotos, videos, documentos o notas circulares).")

# --- MANEJO SEGURO DE ARCHIVOS Y FORMATOS ---
@bot.message_handler(content_types=['document', 'photo', 'video', 'video_note'])
def handle_files(m):
    uid = m.from_user.id
    if uid not in user_sessions:
        user_sessions[uid] = {"files": [], "password": "DefaultPassword123"}
    
    f_info = None
    f_name = f"archivo_{m.message_id}"
    
    if m.document:
        f_info = bot.get_file(m.document.file_id)
        if m.document.file_name:
            f_name = m.document.file_name
    elif m.photo:
        f_info = bot.get_file(m.photo[-1].file_id)
        f_name = f"foto_{m.photo[-1].file_unique_id}.jpg"
    elif m.video:
        f_info = bot.get_file(m.video.file_id)
        if m.video.file_name:
            f_name = m.video.file_name
        else:
            f_name = f"video_{m.video.file_unique_id}.mp4"
    elif m.video_note:
        f_info = bot.get_file(m.video_note.file_id)
        f_name = f"nota_circular_{m.video_note.file_unique_id}.mp4"

    if f_info and f_info.file_path:
        down = bot.download_file(f_info.file_path)
        safe_name = str(f_name)
        path = f"temp_{uid}_{safe_name}"
        
        with open(path, "wb") as f:
            f.write(down)
        
        user_sessions[uid]["files"].append({"path": path, "name": safe_name})
        # Mensaje orientativo tras recibir cada archivo
        bot.reply_to(m, f"✅ Archivo añadido: `{safe_name}`\n\nCuando termines de enviar todos tus archivos, escribe **`/comprimir`**.", parse_mode="Markdown")

@bot.message_handler(commands=['comprimir'])
def compress_files(m):
    uid = m.from_user.id
    if uid not in user_sessions or not user_sessions[uid]["files"]:
        return bot.reply_to(m, "⚠️ No hay archivos acumulados para comprimir. Envía algunos primero.")
    
    sess = user_sessions[uid]
    zname = f"archivo_protegido_{uid}.zip"
    pwd = sess["password"]
    bot.reply_to(m, "🗜️ Generando ZIP protegido con AES-256...")
    
    try:
        # Se usa string "AES_256" para evitar errores de atributos en pyzipper
        with pyzipper.AESZipFile(zname, "w", compression=pyzipper.ZIP_DEFLATED, encryption="AES_256") as zf:
            zf.setpassword(pwd.encode("utf-8"))
            for file_item in sess["files"]:
                c_path = str(file_item["path"])
                c_name = str(file_item["name"])
                if os.path.exists(c_path):
                    zf.write(c_path, arcname=c_name)
                
        with open(zname, "rb") as zf:
            # Mensaje exacto de que está listo
            bot.send_document(
                m.chat.id, 
                zf, 
                caption=f"🎉 **¡Tu archivo comprimido está listo!**\n\n🔒 Contraseña: `{pwd}`", 
                parse_mode="Markdown"
            )
    except Exception as e:
        bot.reply_to(m, f"❌ Error durante la compresión: {e}")
    finally:
        # Limpieza de archivos temporales del servidor
        for file_item in sess["files"]:
            if os.path.exists(file_item["path"]):
                os.remove(file_item["path"])
        if os.path.exists(zname):
            os.remove(zname)
        sess["files"] = []

if __name__ == "__main__":
    print("🤖 Bot iniciado correctamente en la nube...")
    bot.infinity_polling()
