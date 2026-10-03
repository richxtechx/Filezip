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

# Límite de Telegram: 50 MB en la API de Bot
TELEGRAM_MAX_SIZE = 50 * 1024 * 1024  # 50 MB

def format_size(bytes_size):
    """Convierte bytes a formato legible (MB, GB, etc)"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} TB"

@bot.message_handler(commands=['start'])
def send_welcome(m):
    bot.reply_to(m, "🤖 ¡Bot multimedia seguro activo!\n\n1️⃣ Envía `/password <tu_clave>`\n2️⃣ Envía tus archivos (fotos, videos, documentos o notas circulares)\n3️⃣ Envía `/comprimir` para obtener tu ZIP protegido.", parse_mode="Markdown")

@bot.message_handler(commands=['password'])
def set_password(m):
    uid = m.from_user.id
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        return bot.reply_to(m, "❌ Indica la contraseña. Ejemplo: `/password mi_clave`", parse_mode="Markdown")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"files": [], "password": "DefaultPassword123"}
    
    user_sessions[uid]["password"] = args[1]
    bot.reply_to(m, "🔒 Contraseña guardada correctamente.\n\n📥 *Ahora puedes enviar los archivos* que deseas comprimir (fotos, videos, documentos o notas circulares).", parse_mode="Markdown")

# --- MANEJO BLINDADO DE ARCHIVOS ---
@bot.message_handler(content_types=['document', 'photo', 'video', 'video_note'])
def handle_files(m):
    uid = m.from_user.id
    if uid not in user_sessions:
        user_sessions[uid] = {"files": [], "password": "DefaultPassword123"}
    
    f_info = None
    original_name = None
    file_size = None
    
    if m.document:
        f_info = bot.get_file(m.document.file_id)
        original_name = m.document.file_name
        file_size = m.document.file_size
    elif m.photo:
        f_info = bot.get_file(m.photo[-1].file_id)
        original_name = f"foto_{m.photo[-1].file_unique_id}.jpg"
        file_size = m.photo[-1].file_size
    elif m.video:
        f_info = bot.get_file(m.video.file_id)
        original_name = m.video.file_name or f"video_{m.video.file_unique_id}.mp4"
        file_size = m.video.file_size
    elif m.video_note:
        f_info = bot.get_file(m.video_note.file_id)
        original_name = f"nota_circular_{m.video_note.file_unique_id}.mp4"
        file_size = m.video_note.file_size

    if f_info:
        # Fallback estricto por si el nombre viene nulo de la API de Telegram
        if not original_name or not isinstance(original_name, str):
            original_name = f"archivo_{m.message_id}.bin"
            
        down = bot.download_file(f_info.file_path)
        path = f"temp_{uid}_{m.message_id}_{original_name}"
        
        with open(path, "wb") as f:
            f.write(down)
        
        actual_size = os.path.getsize(path)
        user_sessions[uid]["files"].append({"path": path, "name": original_name, "size": actual_size})
        
        size_display = format_size(actual_size) if file_size is None else format_size(file_size)
        bot.reply_to(m, f"✅ Archivo añadido: {original_name} ({size_display})\n\nCuando termines de enviar todos tus archivos, escribe /comprimir")

@bot.message_handler(commands=['listar'])
def list_files(m):
    uid = m.from_user.id
    if uid not in user_sessions or not user_sessions[uid]["files"]:
        return bot.reply_to(m, "📭 No hay archivos acumulados.")
    
    sess = user_sessions[uid]
    total_size = sum(f["size"] for f in sess["files"])
    
    msg = "📂 Archivos acumulados:\n\n"
    for i, file_item in enumerate(sess["files"], 1):
        msg += f"{i}. {file_item['name']} ({format_size(file_item['size'])})\n"
    
    msg += f"\nTamaño total: {format_size(total_size)}"
    bot.reply_to(m, msg)

@bot.message_handler(commands=['limpiar'])
def clear_files(m):
    uid = m.from_user.id
    if uid not in user_sessions or not user_sessions[uid]["files"]:
        return bot.reply_to(m, "📭 No hay archivos para limpiar.")
    
    sess = user_sessions[uid]
    for file_item in sess["files"]:
        if os.path.exists(file_item["path"]):
            os.remove(file_item["path"])
    sess["files"] = []
    bot.reply_to(m, "✅ Archivos limpios. Puedes comenzar de nuevo.")

@bot.message_handler(commands=['comprimir'])
def compress_files(m):
    uid = m.from_user.id
    if uid not in user_sessions or not user_sessions[uid]["files"]:
        return bot.reply_to(m, "⚠️ No hay archivos acumulados para comprimir. Envía algunos primero.")
    
    sess = user_sessions[uid]
    
    # Calcular tamaño total ANTES de comprimir
    total_size = sum(f["size"] for f in sess["files"])
    
    # Validación: si el tamaño total YA supera 45 MB, avisar
    # (dejamos 5 MB de margen porque la compresión rara vez reduce mucho videos/fotos)
    if total_size > 45 * 1024 * 1024:
        size_display = format_size(total_size)
        bot.reply_to(m, 
            f"⚠️ DEMASIADO GRANDE\n\n"
            f"Tamaño total de archivos: {size_display}\n"
            f"Límite de Telegram: 50 MB\n\n"
            f"Soluciones:\n"
            f"1. Usa /limpiar y envía menos archivos\n"
            f"2. Usa /listar para ver el tamaño de cada uno\n"
            f"3. Elimina los archivos más pesados"
        )
        return
    
    zname = f"archivo_protegido_{uid}.zip"
    pwd = sess["password"]
    bot.reply_to(m, "🗜️ Generando ZIP protegido con AES-256...")
    
    try:
        with pyzipper.AESZipFile(zname, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(pwd.encode("utf-8"))
            zf.setencryption(pyzipper.WZ_AES, nbits=256)
            for file_item in sess["files"]:
                c_path = str(file_item["path"])
                c_name = str(file_item["name"])
                if os.path.exists(c_path):
                    zf.write(c_path, arcname=c_name)
        
        # Validar tamaño del ZIP ANTES de intentar enviarlo
        zip_size = os.path.getsize(zname)
        if zip_size > TELEGRAM_MAX_SIZE:
            size_display = format_size(zip_size)
            os.remove(zname)
            bot.reply_to(m, 
                f"❌ El ZIP es demasiado grande ({size_display})\n\n"
                f"Límite de Telegram: {format_size(TELEGRAM_MAX_SIZE)}\n\n"
                f"Usa /limpiar y envía menos archivos."
            )
            return
        
        with open(zname, "rb") as zf:
            bot.send_document(
                m.chat.id, 
                zf, 
                caption=f"🎉 ¡Tu archivo comprimido está listo!\n\n🔒 Contraseña: {pwd}\n\n📦 Tamaño: {format_size(zip_size)}"
            )
    except Exception as e:
        bot.reply_to(m, f"❌ Error durante la compresión: {e}")
    finally:
        for file_item in sess["files"]:
            if os.path.exists(file_item["path"]):
                os.remove(file_item["path"])
        if os.path.exists(zname):
            os.remove(zname)
        sess["files"] = []

if __name__ == "__main__":
    print("🤖 Bot iniciado correctamente en la nube...")
    bot.infinity_polling()
