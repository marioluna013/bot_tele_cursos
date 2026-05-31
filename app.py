import os
import time
from datetime import datetime, timedelta
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
DetectorFactory.seed = 0  
load_dotenv()
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN")
ID_CANAL = os.getenv("TELEGRAM_CHANNEL_ID")
DATABASE_URL = os.getenv("DATABASE_URL")

FUENTES_RSS = [
    "https://facialix.com/feed/",
    "https://www.reddit.com/r/udemyfreebies/.rss",
    "https://www.reddit.com/r/udemyfreecourses/.rss",
    "https://www.reddit.com/r/FreeUdemyCoupons/.rss",
]

PLATAFORMAS = [
    'udemy.com', 'coursera.org', 'edx.org', 'sharecourse.net',
    'linksynergy.com', 'click.linksynergy.com', 'udemy-k.com',
    'hotmart.com', 'crehana.com', 'domestika.org', 'platzi.com'
]

# ================= AUXILIARES =================
def limpiar_html(texto):
    if not texto:
        return ""
    soup = BeautifulSoup(texto, 'html.parser')
    texto_plano = soup.get_text(separator=' ', strip=True)
    texto_plano = re.sub(r'\s+', ' ', texto_plano)
    soup.decompose()  # Libera memoria RAM
    return texto_plano.strip()

def es_espanol(texto):
    if not texto:
        return False
    try:
        return detect(texto) == 'es'
    except:
        return False

# ================= BASE DE DATOS =================
def iniciar_base_datos():
    """Crea la tabla en PostgreSQL si no existe"""
    try:
        with psycopg2.connect(DATABASE_URL) as conexion:
            with conexion.cursor() as cursor:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cursos (
                        id SERIAL PRIMARY KEY,
                        url_original TEXT UNIQUE,
                        titulo TEXT,
                        plataforma TEXT,
                        fecha_publicacion TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
                    )
                ''')
                conexion.commit()
        print("📊 Base de datos PostgreSQL verificada correctamente.", flush=True)
    except Exception as e:
        print(f"❌ Error al iniciar la base de datos: {e}", flush=True)

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
        print(f"❌ Error de red en Telegram: {e}", flush=True)
        return None

# ================= SCRAPING FUENTES =================
def scraping_cursoteca_cupones():
    cursos = []
    url_listado = "https://cursotecaplus.com/cupones-udemy/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        respuesta = requests.get(url_listado, headers=headers, timeout=15)
        if respuesta.status_code != 200: return []
        
        soup = BeautifulSoup(respuesta.text, 'html.parser')
        for article in soup.find_all('article', class_='curso-card'):
            enlace_tag = article.find('a', href=True)
            if not enlace_tag: continue
            
            titulo_tag = article.find('h2')
            titulo = limpiar_html(titulo_tag.get_text()) if titulo_tag else "Curso sin título"
            url_articulo = urljoin(url_listado, enlace_tag['href'])
            
            enlace_real, plataforma = None, None
            try:
                resp_articulo = requests.get(url_articulo, headers=headers, timeout=15)
                if resp_articulo.status_code == 200:
                    soup_art = BeautifulSoup(resp_articulo.text, 'html.parser')
                    for a in soup_art.find_all('a', href=True):
                        for patron in PLATAFORMAS:
                            if patron in a['href'].lower():
                                enlace_real = a['href']
                                plataforma = patron.split('.')[0].capitalize()
                                break
                        if enlace_real: break
                    soup_art.decompose()
            except: pass
            
            cursos.append({
                'titulo': titulo, 'url': enlace_real if enlace_real else url_articulo,
                'plataforma': plataforma if plataforma else "Web"
            })
        soup.decompose()
    except Exception as e: print(f"❌ Error Cursoteca Cupones: {e}", flush=True)
    return cursos

def scraping_cursoteca_blog():
    cursos = []
    url_listado = "https://cursotecaplus.com/category/programacion/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        respuesta = requests.get(url_listado, headers=headers, timeout=15)
        if respuesta.status_code != 200: return []
        soup = BeautifulSoup(respuesta.text, 'html.parser')
        for article in soup.find_all('article', class_='entry-card'):
            titulo_tag = article.find('h2', class_='entry-title')
            if not titulo_tag: continue
            enlace_tag = titulo_tag.find('a', href=True)
            if not enlace_tag: continue
            
            titulo = limpiar_html(titulo_tag.get_text())
            url_articulo = urljoin(url_listado, enlace_tag['href'])
            
            enlace_real, plataforma = None, None
            try:
                resp_articulo = requests.get(url_articulo, headers=headers, timeout=15)
                if resp_articulo.status_code == 200:
                    soup_art = BeautifulSoup(resp_articulo.text, 'html.parser')
                    for a in soup_art.find_all('a', href=True):
                        for patron in PLATAFORMAS:
                            if patron in a['href'].lower():
                                enlace_real = a['href']
                                plataforma = patron.split('.')[0].capitalize()
                                break
                        if enlace_real: break
                    soup_art.decompose()
            except: pass
            
            cursos.append({
                'titulo': titulo, 'url': enlace_real if enlace_real else url_articulo,
                'plataforma': plataforma if plataforma else "Web"
            })
        soup.decompose()
    except Exception as e: print(f"❌ Error Cursoteca Blog: {e}", flush=True)
    return cursos

def scraping_centro_educatic():
    """Extrae cursos de Centro Educatic con búsqueda flexible por clase"""
    cursos = []
    url_listado = "https://centro-educatic.com/public/gratis-udemy"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        respuesta = requests.get(url_listado, headers=headers, timeout=15)
        if respuesta.status_code != 200: return []
        
        soup = BeautifulSoup(respuesta.text, 'html.parser')
        tarjetas = soup.find_all(True, class_='course-card')
        print(f"   📊 Tarjetas encontradas en Centro Educatic: {len(tarjetas)}", flush=True)
        
        for card in tarjetas:
            enlace_tag = card.find('a', class_='course-link')
            if not enlace_tag or not enlace_tag.get('href'): continue
            
            url_articulo = urljoin(url_listado, enlace_tag['href'])
            titulo = limpiar_html(enlace_tag.get_text())
            
            print(f"   🔍 Analizando ficha: {titulo[:30]}...", flush=True)
            enlace_real = None
            plataforma = "Web"
            
            try:
                time.sleep(3.0)  # Pausa prudencial para evitar bloqueos
                resp_articulo = requests.get(url_articulo, headers=headers, timeout=15)
                if resp_articulo.status_code == 200:
                    soup_art = BeautifulSoup(resp_articulo.text, 'html.parser')
                    for a in soup_art.find_all('a', href=True):
                        for patron in PLATAFORMAS:
                            if patron in a['href'].lower():
                                enlace_real = a['href']
                                plataforma = patron.split('.')[0].capitalize()
                                break
                        if enlace_real: break
                    soup_art.decompose()
            except Exception as e:
                print(f"   ⚠️ Error en ficha interna: {e}", flush=True)
            
            if not enlace_real:
                enlace_real = url_articulo
            
            cursos.append({'titulo': titulo, 'url': enlace_real, 'plataforma': plataforma})
        soup.decompose()
    except Exception as e: print(f"❌ Error Centro Educatic: {e}", flush=True)
    return cursos

def scraping_cursosdev():
    cursos = []
    url_listado = "https://www.cursosdev.com/coupons/Spanish"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        respuesta = requests.get(url_listado, headers=headers, timeout=15)
        if respuesta.status_code != 200: return []
        soup = BeautifulSoup(respuesta.text, 'html.parser')
        for articulo in soup.find_all('article', class_='group'):
            enlace_tag = articulo.find('a', href=True)
            if not enlace_tag: continue
            url_curso = urljoin(url_listado, enlace_tag['href'])
            titulo_tag = articulo.find('h2')
            titulo = limpiar_html(titulo_tag.get_text()) if titulo_tag else "Curso sin título"
            
            enlace_udemy = None
            try:
                resp_cur = requests.get(url_curso, headers=headers, timeout=15)
                if resp_cur.status_code == 200:
                    soup_cur = BeautifulSoup(resp_cur.text, 'html.parser')
                    boton = soup_cur.find('a', class_='bg-indigo-600') or soup_cur.find('a', string=lambda t: t and 'cupón' in t.lower())
                    if boton and boton.get('href'): enlace_udemy = boton['href']
                    soup_cur.decompose()
            except: pass
            
            cursos.append({
                'titulo': titulo, 'url': enlace_udemy if enlace_udemy else url_curso,
                'plataforma': "Udemy" if enlace_udemy and 'udemy' in enlace_udemy.lower() else "Web"
            })
        soup.decompose()
    except Exception as e: print(f"❌ Error CursosDev: {e}", flush=True)
    return cursos

# ================= LÓGICA PRINCIPAL (PROTEGIDA CONTRA TIPOS) =================
def revisar_y_publicar():
    iniciar_base_datos()
    fecha_limite = datetime.now() - timedelta(days=7)
    
    print("\n--- 🔄 INICIANDO NUEVA RONDA DE SCRAPING EN TIEMPO REAL ---", flush=True)
    
    with psycopg2.connect(DATABASE_URL) as conexion:
        with conexion.cursor() as cursor:
            
            # ----- 1. FUENTES RSS -----
            for url_feed in FUENTES_RSS:
                print(f"📡 RSS ➡️ Conectando a: {url_feed}", flush=True)
                try:
                    respuesta = requests.get(url_feed, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                    if respuesta.status_code != 200: 
                        print(f"   ❌ Error de conexión RSS ({respuesta.status_code})", flush=True)
                        continue
                    feed = feedparser.parse(respuesta.text)
                except Exception as e: 
                    print(f"   ❌ Error crítico al leer RSS: {e}", flush=True)
                    continue
                
                print(f"   📊 Encontradas {len(feed.entries)} entradas en el feed.", flush=True)
                for entrada in feed.entries[:20]:
                    if not hasattr(entrada, 'link'): continue
                    url_articulo = entrada.link
                    titulo = limpiar_html(entrada.title) if hasattr(entrada, 'title') else "Curso sin título"
                    
                    if 'reddit.com' in url_feed and not es_espanol(titulo): 
                        print(f"   ⏩ Ignorado por idioma (No ES): {titulo[:30]}...", flush=True)
                        continue
                    
                    cursor.execute("SELECT fecha_publicacion FROM cursos WHERE url_original = %s", (url_articulo,))
                    registro = cursor.fetchone()
                    
                    if registro:
                        fecha_registro = registro[0]
                        # 🔐 PROTECCIÓN: Si viene como texto (String), lo convertimos a Datetime
                        if isinstance(fecha_registro, str):
                            try:
                                fecha_registro = datetime.strptime(fecha_registro.split(".")[0], "%Y-%m-%d %H:%M:%S")
                            except:
                                fecha_registro = datetime.now() - timedelta(days=10) # Forzado a pasar filtro si falla
                        
                        if fecha_registro > fecha_limite:
                            print(f"   ⏩ Duplicado reciente (RSS): {titulo[:30]}...", flush=True)
                            continue
                    
                    print(f"🚀 [RSS] ¡NUEVO CURSO DETECTADO!: {titulo[:40]}...", flush=True)
                    mensaje = f"🎁 *NUEVO CURSO DISPONIBLE*\n\n📘 *Título:* {titulo}\n\n🔗 [VER CURSO]({url_articulo})\n\n⚠️ *Reclama el cupón rápido antes de que expire.*"
                    resultado = enviar_a_telegram(mensaje)
                    if resultado and resultado.get("ok"):
                        cursor.execute("""
                            INSERT INTO cursos (url_original, titulo, plataforma, fecha_publicacion) 
                            VALUES (%s, %s, %s, NOW())
                            ON CONFLICT (url_original) DO UPDATE SET fecha_publicacion = NOW()
                        """, (url_articulo, titulo, "RSS"))
                        conexion.commit()
                        print(f"   💤 Pausa anti-spam de 30 segundos...", flush=True)
                        time.sleep(30.0)
            
            # ----- 2. SCRAPING WEBS -----
            fuentes_scraping = [
                ("Cursoteca Cupones", scraping_cursoteca_cupones),
                ("Cursoteca Blog", scraping_cursoteca_blog),
                ("Centro Educatic", scraping_centro_educatic),
                ("CursosDev", scraping_cursosdev)
            ]
            
            for nombre_fuente, funcion_scraping in fuentes_scraping:
                print(f"\n🕷️ WEB ➡️ Iniciando extracción en: {nombre_fuente}...", flush=True)
                cursos_encontrados = funcion_scraping()
                print(f"   📊 {nombre_fuente} devolvió {len(cursos_encontrados)} cursos en total.", flush=True)
                
                for curso in cursos_encontrados:
                    cursor.execute("SELECT fecha_publicacion FROM cursos WHERE url_original = %s", (curso['url'],))
                    registro = cursor.fetchone()
                    
                    if registro:
                        fecha_registro = registro[0]
                        # 🔐 PROTECCIÓN: Si viene como texto (String), lo convertimos a Datetime
                        if isinstance(fecha_registro, str):
                            try:
                                fecha_registro = datetime.strptime(fecha_registro.split(".")[0], "%Y-%m-%d %H:%M:%S")
                            except:
                                fecha_registro = datetime.now() - timedelta(days=10)
                                
                        if fecha_registro > fecha_limite:
                            print(f"   ⏩ Duplicado reciente ({nombre_fuente}): {curso['titulo'][:30]}...", flush=True)
                            continue
                    
                    print(f"🚀 [{nombre_fuente}] ¡NUEVO CURSO DETECTADO!: {curso['titulo'][:40]}...", flush=True)
                    if curso['plataforma'] != "Web":
                        mensaje = f"🎁 *NUEVO CURSO GRATIS EN {curso['plataforma'].upper()}*\n\n📘 *Título:* {curso['titulo']}\n\n🔗 [ACCEDER AL CURSO GRATIS]({curso['url']})\n\n⚠️ *Cupón activo por tiempo limitado.*"
                    else:
                        mensaje = f"🎁 *NUEVO CURSO DISPONIBLE*\n\n📘 *Título:* {curso['titulo']}\n\n🔗 [VER EN LA WEB]({curso['url']})\n\n⚠️ *Sigue los pasos en la web para conseguirlo.*"
                    
                    resultado = enviar_a_telegram(mensaje)
                    if resultado and resultado.get("ok"):
                        cursor.execute("""
                            INSERT INTO cursos (url_original, titulo, plataforma, fecha_publicacion) 
                            VALUES (%s, %s, %s, NOW())
                            ON CONFLICT (url_original) DO UPDATE SET fecha_publicacion = NOW()
                        """, (curso['url'], curso['titulo'], curso['plataforma']))
                        conexion.commit()
                        print(f"   💤 Pausa anti-spam de 30 segundos...", flush=True)
                        time.sleep(30.0)

    print("\n✅ --- CICLO DE SCRAPING COMPLETADO CON ÉXITO ---", flush=True)

# ================= SERVIDOR FLASK =================
app = Flask(__name__)

@app.route('/')
def home(): return "🤖 Bot de Cursos con Trazabilidad Completa Activo...", 200

@app.route('/ping')
def ping(): return "OK", 200

def bucle_scraping_infinito():
    print("🤖 Hilo de scraping iniciado en segundo plano...", flush=True)
    while True:
        try:
            revisar_y_publicar()
        except Exception as e:
            print(f"❌ Error crítico en el bucle: {e}", flush=True)
        print("💤 Esperando 10 minutos para la siguiente ronda...\n", flush=True)
        time.sleep(600)

if __name__ == "__main__":
    print("🤖 BOT INICIADO - Forzado de Vaciado de Consola NATIVO (Flush=True)", flush=True)
    hilo = threading.Thread(target=bucle_scraping_infinito, daemon=True)
    hilo.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
