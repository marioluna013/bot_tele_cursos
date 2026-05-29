import os
import time
import feedparser
import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from dotenv import load_dotenv
from langdetect import detect, DetectorFactory
from flask import Flask
import threading
import psycopg2  # Conector para PostgreSQL

# ================= CONFIGURACIÓN =================
DetectorFactory.seed = 0  # Para resultados consistentes
load_dotenv()
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN")
ID_CANAL = os.getenv("TELEGRAM_CHANNEL_ID")
# Render inyecta esta variable automáticamente tras ponerla en el panel
DATABASE_URL = os.getenv("DATABASE_URL")

# Fuentes RSS (incluyendo Reddit)
FUENTES_RSS = [
    "https://facialix.com/feed/",
    "https://www.reddit.com/r/udemyfreebies/.rss",
    "https://www.reddit.com/r/udemyfreecourses/.rss",
    "https://www.reddit.com/r/FreeUdemyCoupons/.rss",
]

# Plataformas válidas para detectar
PLATAFORMAS = [
    'udemy.com', 'coursera.org', 'edx.org', 'sharecourse.net',
    'linksynergy.com', 'click.linksynergy.com', 'udemy-k.com',
    'hotmart.com', 'crehana.com', 'domestika.org', 'platzi.com'
]

# ================= LIMPIAR HTML =================
def limpiar_html(texto):
    """Elimina todas las etiquetas HTML y deja solo texto plano limpio"""
    if not texto:
        return ""
    soup = BeautifulSoup(texto, 'html.parser')
    texto_plano = soup.get_text(separator=' ', strip=True)
    texto_plano = re.sub(r'\s+', ' ', texto_plano)
    return texto_plano.strip()

# ================= DETECTAR IDIOMA =================
def es_espanol(texto):
    """Detecta si un texto está en español usando langdetect"""
    if not texto:
        return False
    try:
        return detect(texto) == 'es'
    except:
        return False

# ================= BASE DE DATOS (POSTGRESQL) =================
def iniciar_base_datos():
    """Crea la tabla en PostgreSQL si no existe"""
    try:
        conexion = psycopg2.connect(DATABASE_URL)
        cursor = conexion.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cursos (
                id SERIAL PRIMARY KEY,
                url_original TEXT UNIQUE,
                titulo TEXT,
                plataforma TEXT,
                fecha_publicacion TEXT
            )
        ''')
        conexion.commit()
        cursor.close()
        conexion.close()
        print("📊 Base de datos PostgreSQL verificada/iniciada correctamente.")
    except Exception as e:
        print(f"❌ Error al iniciar la base de datos PostgreSQL: {e}")

# ================= ENVIAR A TELEGRAM =================
def enviar_a_telegram(texto):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": ID_CANAL,
        "text": texto,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"❌ Error de red al enviar a Telegram: {e}")
        return None

# ================= SCRAPING CURSOTECAPLUS (CUPONES UDEMY) =================
def scraping_cursoteca_cupones():
    """Extrae cursos de https://cursotecaplus.com/cupones-udemy/"""
    cursos = []
    url_listado = "https://cursotecaplus.com/cupones-udemy/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        respuesta = requests.get(url_listado, headers=headers, timeout=15)
        if respuesta.status_code != 200:
            print(f"⚠️ Error {respuesta.status_code} en Cursoteca Cupones")
            return cursos
        
        soup = BeautifulSoup(respuesta.text, 'html.parser')
        
        for article in soup.find_all('article', class_='curso-card'):
            enlace_tag = article.find('a', href=True)
            if not enlace_tag:
                continue
            
            titulo_tag = article.find('h2')
            titulo_raw = titulo_tag.get_text(strip=True) if titulo_tag else "Curso sin título"
            titulo = limpiar_html(titulo_raw)
            url_articulo = urljoin(url_listado, enlace_tag['href'])
            
            print(f"   🔍 Procesando: {titulo[:40]}...")
            
            enlace_real = None
            plataforma = None
            
            try:
                resp_articulo = requests.get(url_articulo, headers=headers, timeout=15)
                if resp_articulo.status_code == 200:
                    soup_articulo = BeautifulSoup(resp_articulo.text, 'html.parser')
                    
                    for a in soup_articulo.find_all('a', href=True):
                        for patron in PLATAFORMAS:
                            if patron in a['href'].lower():
                                enlace_real = a['href']
                                plataforma = patron.split('.')[0].capitalize()
                                break
                        if enlace_real:
                            break
                    
                    if enlace_real:
                        print(f"   ✅ Enlace encontrado: {plataforma}")
                    else:
                        boton = soup_articulo.find('a', string=lambda t: t and ('Ver cupón' in t or 'Acceder' in t or 'Ir al curso' in t))
                        if boton and boton.get('href'):
                            enlace_real = urljoin(url_articulo, boton['href'])
                            for patron in PLATAFORMAS:
                                if patron in enlace_real.lower():
                                    plataforma = patron.split('.')[0].capitalize()
                                    print(f"   ✅ Redirección a: {plataforma}")
                                    break
                            if not plataforma:
                                print(f"   ⚠️ Botón encontrado pero no es de plataforma conocida")
                        else:
                            print(f"   ⚠️ No se encontró enlace a plataforma conocida")
            except Exception as e:
                print(f"   ⚠️ Error: {e}")
            
            if not enlace_real:
                enlace_real = url_articulo
                plataforma = "Web"
            
            cursos.append({
                'titulo': titulo,
                'url': enlace_real,
                'plataforma': plataforma,
                'fuente': 'Cursoteca Cupones'
            })
            
            time.sleep(0.3)
            
    except Exception as e:
        print(f"❌ Error en scraping de Cursoteca Cupones: {e}")
    
    return cursos

# ================= SCRAPING CURSOTECAPLUS (BLOG) =================
def scraping_cursoteca_blog():
    """Extrae cursos del blog de https://cursotecaplus.com/category/programacion/"""
    cursos = []
    url_listado = "https://cursotecaplus.com/category/programacion/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        respuesta = requests.get(url_listado, headers=headers, timeout=15)
        if respuesta.status_code != 200:
            print(f"⚠️ Error {respuesta.status_code} en Cursoteca Blog")
            return cursos
        
        soup = BeautifulSoup(respuesta.text, 'html.parser')
        
        for article in soup.find_all('article', class_='entry-card'):
            titulo_tag = article.find('h2', class_='entry-title')
            if not titulo_tag:
                continue
            
            enlace_tag = titulo_tag.find('a', href=True)
            if not enlace_tag:
                continue
            
            titulo_raw = titulo_tag.get_text(strip=True)
            titulo = limpiar_html(titulo_raw)
            url_articulo = urljoin(url_listado, enlace_tag['href'])
            
            print(f"   🔍 Procesando: {titulo[:40]}...")
            
            enlace_real = None
            plataforma = None
            
            try:
                resp_articulo = requests.get(url_articulo, headers=headers, timeout=15)
                if resp_articulo.status_code == 200:
                    soup_articulo = BeautifulSoup(resp_articulo.text, 'html.parser')
                    
                    for a in soup_articulo.find_all('a', href=True):
                        for patron in PLATAFORMAS:
                            if patron in a['href'].lower():
                                enlace_real = a['href']
                                plataforma = patron.split('.')[0].capitalize()
                                break
                        if enlace_real:
                            break
                    
                    if enlace_real:
                        print(f"   ✅ Enlace encontrado: {plataforma}")
                    else:
                        iframes = soup_articulo.find_all('iframe', src=True)
                        for iframe in iframes:
                            for patron in PLATAFORMAS:
                                if patron in iframe['src'].lower():
                                    enlace_real = iframe['src']
                                    plataforma = patron.split('.')[0].capitalize()
                                    print(f"   ✅ Enlace en iframe: {plataforma}")
                                    break
                            if enlace_real:
                                break
                        
                        if not enlace_real:
                            print(f"   ⚠️ No se encontró enlace a plataforma conocida")
            except Exception as e:
                print(f"   ⚠️ Error: {e}")
            
            if not enlace_real:
                enlace_real = url_articulo
                plataforma = "Web"
            
            cursos.append({
                'titulo': titulo,
                'url': enlace_real,
                'plataforma': plataforma,
                'fuente': 'Cursoteca Blog'
            })
            
            time.sleep(0.3)
            
    except Exception as e:
        print(f"❌ Error en scraping de Cursoteca Blog: {e}")
    
    return cursos

# ================= SCRAPING CENTRO EDUCATIC =================
def scraping_centro_educatic():
    """Extrae cursos de https://centro-educatic.com/public/gratis-udemy"""
    cursos = []
    url_listado = "https://centro-educatic.com/public/gratis-udemy"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        respuesta = requests.get(url_listado, headers=headers, timeout=15)
        if respuesta.status_code != 200:
            print(f"⚠️ Error {respuesta.status_code} en Centro Educatic")
            return cursos
        
        soup = BeautifulSoup(respuesta.text, 'html.parser')
        
        for col in soup.find_all('div', class_='col-md-6 col-lg-4'):
            card = col.find('div', class_='card')
            if not card:
                continue
            
            titulo_tag = card.find('h6', class_='card-title')
            if not titulo_tag:
                titulo_tag = card.find('h5') or card.find('h3')
            
            if not titulo_tag:
                continue
            
            enlace_tag = titulo_tag.find('a', href=True)
            if not enlace_tag:
                continue
            
            titulo_raw = titulo_tag.get_text(strip=True)
            titulo = limpiar_html(titulo_raw)
            url_curso = urljoin(url_listado, enlace_tag['href'])
            
            boton = card.find('a', class_='btn-primary')
            if boton and boton.get('href'):
                url_curso = urljoin(url_listado, boton['href'])
            
            print(f"   🔍 Procesando: {titulo[:40]}...")
            
            enlace_real = None
            plataforma = None
            
            try:
                for patron in PLATAFORMAS:
                    if patron in url_curso.lower():
                        enlace_real = url_curso
                        plataforma = patron.split('.')[0].capitalize()
                        break
                
                if not enlace_real:
                    resp_curso = requests.get(url_curso, headers=headers, timeout=15)
                    if resp_curso.status_code == 200:
                        soup_curso = BeautifulSoup(resp_curso.text, 'html.parser')
                        for a in soup_curso.find_all('a', href=True):
                            for patron in PLATAFORMAS:
                                if patron in a['href'].lower():
                                    enlace_real = a['href']
                                    plataforma = patron.split('.')[0].capitalize()
                                    break
                            if enlace_real:
                                break
                
                if enlace_real:
                    print(f"   ✅ Enlace encontrado: {plataforma}")
                else:
                    print(f"   ⚠️ Usando enlace original")
                    enlace_real = url_curso
                    plataforma = "Web"
                    
            except Exception as e:
                print(f"   ⚠️ Error: {e}")
                enlace_real = url_curso
                plataforma = "Web"
            
            cursos.append({
                'titulo': titulo,
                'url': enlace_real,
                'plataforma': plataforma,
                'fuente': 'Centro Educatic'
            })
            
            time.sleep(0.3)
            
    except Exception as e:
        print(f"❌ Error en scraping de Centro Educatic: {e}")
    
    return cursos

# ================= SCRAPING CURSOSDEV =================
def scraping_cursosdev():
    """Extrae cursos de https://www.cursosdev.com/coupons/Spanish"""
    cursos = []
    url_listado = "https://www.cursosdev.com/coupons/Spanish"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        respuesta = requests.get(url_listado, headers=headers, timeout=15)
        if respuesta.status_code != 200:
            print(f"⚠️ Error {respuesta.status_code} en CursosDev")
            return cursos
        
        soup = BeautifulSoup(respuesta.text, 'html.parser')
        
        articulos = soup.find_all('article', class_='group')
        
        if not articulos:
            print(f"   ⚠️ No se encontraron cursos en el listado")
            return cursos
        
        print(f"   📊 Cursos encontrados: {len(articulos)}")
        
        for articulo in articulos:
            enlace_tag = articulo.find('a', href=True)
            if not enlace_tag:
                continue
            
            url_curso = urljoin(url_listado, enlace_tag['href'])
            
            titulo_tag = articulo.find('h2')
            titulo_raw = titulo_tag.get_text(strip=True) if titulo_tag else "Curso sin título"
            titulo = limpiar_html(titulo_raw)
            
            print(f"   🔍 Procesando: {titulo[:40]}...")
            
            enlace_udemy = None
            plataforma = "Web"
            
            try:
                resp_curso = requests.get(url_curso, headers=headers, timeout=15)
                if resp_curso.status_code == 200:
                    soup_curso = BeautifulSoup(resp_curso.text, 'html.parser')
                    
                    boton = soup_curso.find('a', class_='bg-indigo-600')
                    if not boton:
                        boton = soup_curso.find('a', string=lambda t: t and ('Obtener Cupón' in t or 'cupón' in t.lower() or 'Cupón' in t))
                    
                    if boton and boton.get('href'):
                        enlace_udemy = boton['href']
                        if 'udemy.com' in enlace_udemy or 'trk.udemy.com' in enlace_udemy:
                            plataforma = "Udemy"
                            print(f"   ✅ Enlace Udemy encontrado")
                        else:
                            print(f"   ⚠️ Enlace no es de Udemy")
                    else:
                        print(f"   ⚠️ No se encontró botón de cupón")
            except Exception as e:
                print(f"   ⚠️ Error obteniendo enlace: {e}")
            
            if not enlace_udemy:
                enlace_udemy = url_curso
                print(f"   ⚠️ Usando enlace del artículo")
            
            cursos.append({
                'titulo': titulo,
                'url': enlace_udemy,
                'plataforma': plataforma,
                'fuente': 'CursosDev'
            })
            
            time.sleep(0.3)
            
    except Exception as e:
        print(f"❌ Error en scraping de CursosDev: {e}")
    
    return cursos

# ================= LÓGICA PRINCIPAL =================
def revisar_y_publicar():
    iniciar_base_datos()
    conexion = psycopg2.connect(DATABASE_URL)
    cursor = conexion.cursor()
    
    # ----- 1. RSS FACIALIX Y REDDIT -----
    headers_rss = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for url_feed in FUENTES_RSS:
        print(f"🔍 Revisando RSS: {url_feed}")
        try:
            respuesta = requests.get(url_feed, headers=headers_rss, timeout=15)
            if respuesta.status_code != 200:
                print(f"⚠️ Error {respuesta.status_code}")
                continue
            feed = feedparser.parse(respuesta.text)
        except Exception as e:
            print(f"❌ Error en RSS {url_feed}: {e}")
            continue
        
        if not feed.entries:
            print(f"⚠️ Feed vacío: {url_feed}")
            continue
        
        for entrada in feed.entries[:20]:
            if not hasattr(entrada, 'link'):
                continue
            url_articulo = entrada.link
            titulo_raw = entrada.title if hasattr(entrada, 'title') else "Curso sin título"
            titulo = limpiar_html(titulo_raw)
            
            if 'reddit.com' in url_feed:
                if not es_espanol(titulo):
                    print(f"⏩ Curso omitido (no es español): {titulo[:40]}...")
                    continue
            
            cursor.execute("SELECT id FROM cursos WHERE url_original = %s", (url_articulo,))
            if cursor.fetchone():
                print(f"⏩ Duplicado (RSS): {titulo[:40]}...")
                continue
            
            print(f"🚀 Publicando desde RSS: {titulo[:50]}...")
            mensaje = f"🎁 *NUEVO CURSO DISPONIBLE*\n\n📘 *Título:* {titulo}\n\n🔗 [VER CURSO]({url_articulo})\n\n⚠️ *Entra en el enlace para reclamar el cupón antes de que se agote.*"
            
            resultado = enviar_a_telegram(mensaje)
            if resultado and resultado.get("ok"):
                cursor.execute("INSERT INTO cursos (url_original, titulo, plataforma, fecha_publicacion) VALUES (%s, %s, %s, %s)",
                               (url_articulo, titulo, "RSS", time.strftime("%Y-%m-%d %H:%M:%S")))
                conexion.commit()
                time.sleep(2)
    
    # ----- 2. CURSOTECA CUPONES -----
    print("\n🕷️ Scraping Cursoteca Cupones...")
    for curso in scraping_cursoteca_cupones():
        cursor.execute("SELECT id FROM cursos WHERE url_original = %s", (curso['url'],))
        if cursor.fetchone():
            print(f"⏩ Duplicado (Cursoteca Cupones): {curso['titulo'][:40]}...")
            continue
        
        print(f"🚀 Publicando desde Cursoteca Cupones: {curso['titulo'][:50]}...")
        if curso['plataforma'] != "Web":
            mensaje = f"🎁 *NUEVO CURSO GRATIS EN {curso['plataforma'].upper()}*\n\n📘 *Título:* {curso['titulo']}\n\n🔗 [ACCEDER AL CURSO GRATIS]({curso['url']})\n\n⚠️ *El cupón puede caducar en horas. ¡Actívate!*"
        else:
            mensaje = f"🎁 *NUEVO CURSO DISPONIBLE*\n\n📘 *Título:* {curso['titulo']}\n\n🔗 [VER CUPÓN EN LA WEB]({curso['url']})\n\n⚠️ *Entra en la web y busca el botón para reclamar el cupón.*"
        
        resultado = enviar_a_telegram(mensaje)
        if resultado and resultado.get("ok"):
            cursor.execute("INSERT INTO cursos (url_original, titulo, plataforma, fecha_publicacion) VALUES (%s, %s, %s, %s)",
                           (curso['url'], curso['titulo'], curso['plataforma'], time.strftime("%Y-%m-%d %H:%M:%S")))
            conexion.commit()
            time.sleep(2)
    
    # ----- 3. CURSOTECA BLOG -----
    print("\n🕷️ Scraping Cursoteca Blog...")
    for curso in scraping_cursoteca_blog():
        cursor.execute("SELECT id FROM cursos WHERE url_original = %s", (curso['url'],))
        if cursor.fetchone():
            print(f"⏩ Duplicado (Cursoteca Blog): {curso['titulo'][:40]}...")
            continue
        
        print(f"🚀 Publicando desde Cursoteca Blog: {curso['titulo'][:50]}...")
        if curso['plataforma'] != "Web":
            mensaje = f"🎁 *NUEVO CURSO GRATIS EN {curso['plataforma'].upper()}*\n\n📘 *Título:* {curso['titulo']}\n\n🔗 [ACCEDER AL CURSO GRATIS]({curso['url']})\n\n⚠️ *El cupón puede caducar en horas. ¡Actívate!*"
        else:
            mensaje = f"🎁 *NUEVO CURSO DISPONIBLE*\n\n📘 *Título:* {curso['titulo']}\n\n🔗 [VER CURSO EN LA WEB]({curso['url']})\n\n⚠️ *Entra en la web para más información.*"
        
        resultado = enviar_a_telegram(mensaje)
        if resultado and resultado.get("ok"):
            cursor.execute("INSERT INTO cursos (url_original, titulo, plataforma, fecha_publicacion) VALUES (%s, %s, %s, %s)",
                           (curso['url'], curso['titulo'], curso['plataforma'], time.strftime("%Y-%m-%d %H:%M:%S")))
            conexion.commit()
            time.sleep(2)
    
    # ----- 4. CENTRO EDUCATIC -----
    print("\n🕷️ Scraping Centro Educatic...")
    for curso in scraping_centro_educatic():
        cursor.execute("SELECT id FROM cursos WHERE url_original = %s", (curso['url'],))
        if cursor.fetchone():
            print(f"⏩ Duplicado (Centro Educatic): {curso['titulo'][:40]}...")
            continue
        
        print(f"🚀 Publicando desde Centro Educatic: {curso['titulo'][:50]}...")
        if curso['plataforma'] != "Web":
            mensaje = f"🎁 *NUEVO CURSO GRATIS EN {curso['plataforma'].upper()}*\n\n📘 *Título:* {curso['titulo']}\n\n🔗 [ACCEDER AL CURSO GRATIS]({curso['url']})\n\n⚠️ *El cupón puede caducar en horas. ¡Actívate!*"
        else:
            mensaje = f"🎁 *NUEVO CURSO DISPONIBLE*\n\n📘 *Título:* {curso['titulo']}\n\n🔗 [VER CUPÓN EN LA WEB]({curso['url']})\n\n⚠️ *Entra en la web y busca el botón para reclamar el cupón.*"
        
        resultado = enviar_a_telegram(mensaje)
        if resultado and resultado.get("ok"):
            cursor.execute("INSERT INTO cursos (url_original, titulo, plataforma, fecha_publicacion) VALUES (%s, %s, %s, %s)",
                           (curso['url'], curso['titulo'], curso['plataforma'], time.strftime("%Y-%m-%d %H:%M:%S")))
            conexion.commit()
            time.sleep(2)
    
    # ----- 5. CURSOSDEV -----
    print("\n🕷️ Scraping CursosDev...")
    for curso in scraping_cursosdev():
        cursor.execute("SELECT id FROM cursos WHERE url_original = %s", (curso['url'],))
        if cursor.fetchone():
            print(f"⏩ Duplicado (CursosDev): {curso['titulo'][:40]}...")
            continue
        
        print(f"🚀 Publicando desde CursosDev: {curso['titulo'][:50]}...")
        if curso['plataforma'] != "Web":
            mensaje = f"🎁 *NUEVO CURSO GRATIS EN {curso['plataforma'].upper()}*\n\n📘 *Título:* {curso['titulo']}\n\n🔗 [ACCEDER AL CURSO GRATIS]({curso['url']})\n\n⚠️ *El cupón puede caducar en horas. ¡Actívate!*"
        else:
            mensaje = f"🎁 *NUEVO CURSO DISPONIBLE*\n\n📘 *Título:* {curso['titulo']}\n\n🔗 [VER CUPÓN EN LA WEB]({curso['url']})\n\n⚠️ *Entra en la web y busca el botón para reclamar el cupón.*"
        
        resultado = enviar_a_telegram(mensaje)
        if resultado and resultado.get("ok"):
            cursor.execute("INSERT INTO cursos (url_original, titulo, plataforma, fecha_publicacion) VALUES (%s, %s, %s, %s)",
                           (curso['url'], curso['titulo'], curso['plataforma'], time.strftime("%Y-%m-%d %H:%M:%S")))
            conexion.commit()
            time.sleep(2)
    
    cursor.close()
    conexion.close()
    print("\n✅ Ciclo completado. Esperando 10 minutos...")

# ================= SERVIDOR WEB (PARA RENDER) Y EJECUCIÓN =================
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot de Cursos activo y escaneando con PostgreSQL...", 200

@app.route('/ping')
def ping():
    return "OK", 200

def bucle_scraping_infinito():
    print("🤖 Hilo de scraping iniciado en segundo plano...")
    while True:
        try:
            revisar_y_publicar()
        except Exception as e:
            print(f"❌ Error crítico en el ciclo de revisión: {e}")
        
        print("💤 Esperando 10 minutos para la siguiente ronda...\n")
        time.sleep(600)

if __name__ == "__main__":
    print("🤖 BOT INICIADO - Modo: RSS + Scraping Multiplataforma con DB Persistente")
    
    hilo_scraping = threading.Thread(target=bucle_scraping_infinito, daemon=True)
    hilo_scraping.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
