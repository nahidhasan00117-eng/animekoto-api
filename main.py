import os
import time
import requests
import mysql.connector
from datetime import datetime

# --- CONFIGURATION: SECURE DATABASE BINDING ---
# Render reads these variables from its dashboard environment dashboard configurations
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'yourdomain.com'),
    'user': os.environ.get('DB_USER', 'cpaneluser_dbuser'),
    'password': os.environ.get('DB_PASSWORD', 'your_password'),
    'database': os.environ.get('DB_NAME', 'cpaneluser_dbname'),
    'port': int(os.environ.get('DB_PORT', 3306))
}

BASE_URL = "https://anikotoapi.site"

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

def setup_tables():
    """Verifies targeted cPanel database tables exist before starting sync."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anime (
            id INT PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            type VARCHAR(50),
            year INT,
            status VARCHAR(50),
            genre TEXT,
            poster TEXT,
            description TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anime_episodes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            anime_id INT,
            episode_number FLOAT,
            embed_sub TEXT,
            embed_dub TEXT,
            FOREIGN KEY (anime_id) REFERENCES anime(id) ON DELETE CASCADE,
            UNIQUE KEY anime_ep_unique (anime_id, episode_number)
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

def save_anime_to_db(anime_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    genres = "N/A"
    if 'terms_by_type' in anime_data and 'genre' in anime_data['terms_by_type']:
        genres = ", ".join([g['name'] for g in anime_data['terms_by_type']['genre']])
    elif 'genre' in anime_data:
        genres = anime_data['genre']

    sql = """
        INSERT INTO anime (id, title, type, year, status, genre, poster, description)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
            title=VALUES(title), type=VALUES(type), year=VALUES(year), 
            status=VALUES(status), genre=VALUES(genre), poster=VALUES(poster), 
            description=VALUES(description)
    """
    values = (
        anime_data['id'],
        anime_data.get('title'),
        anime_data.get('type', 'TV'),
        anime_data.get('year', datetime.now().year),
        anime_data.get('status', 'Ongoing'),
        genres,
        anime_data.get('poster'),
        anime_data.get('description', '')
    )
    cursor.execute(sql, values)
    conn.commit()
    cursor.close()
    conn.close()

def save_episodes_to_db(anime_id, episodes):
    if not episodes:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    sql = """
        INSERT INTO anime_episodes (anime_id, episode_number, embed_sub, embed_dub)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE embed_sub=VALUES(embed_sub), embed_dub=VALUES(embed_dub)
    """
    for ep in episodes:
        ep_num = ep.get('episode_number') or ep.get('number', 1)
        embed_urls = ep.get('embed_url', {})
        sub_url = embed_urls.get('sub') if embed_urls else None
        dub_url = embed_urls.get('dub') if embed_urls else None
        cursor.execute(sql, (anime_id, ep_num, sub_url, dub_url))
    conn.commit()
    cursor.close()
    conn.close()

def run_scraper_autoloop():
    print("🚀 --- INITIATING PRODUCTION BACKGROUND SCRAPER ENGINE ---")
    setup_tables()
    
    page = 1
    per_page = 40
    request_tracker = 0
    
    while True:
        print(f"\n📡 Parsing API Catalog Page: {page}...")
        
        # Pacing safeguard to remain completely clear of 60req/120s API throttling barriers
        if request_tracker >= 50:
            print("⏳ Reached boundary buffer threshold. Cooling down for 75 seconds...")
            time.sleep(75)
            request_tracker = 0

        try:
            res = requests.get(f"{BASE_URL}/recent-anime?page={page}&per_page={per_page}", timeout=15)
            request_tracker += 1
            
            if res.status_code != 200:
                print(f"⚠️ API responded with anomalous code {res.status_code}. Pausing stream...")
                time.sleep(30)
                continue
                
            data = res.json()
            anime_items = data.get('data', []) or data.get('rows', [])
            
            if not anime_items:
                print("🏁 Finished scraping full database from A to Z! Sleeping 6 hours before update verification pass...")
                time.sleep(21600)  # Wait 6 hours, then loop back to capture newly ongoing episodes
                page = 1
                continue
                
            for item in anime_items:
                anime_id = item['id']
                print(f" ➜ Syncing Meta & Links: {item.get('title')} (ID #{anime_id})")
                
                save_anime_to_db(item)
                
                if request_tracker >= 50:
                    print("⏳ Reached pacing limits mid-loop. Cooling down for 75 seconds...")
                    time.sleep(75)
                    request_tracker = 0
                
                # Pull deeper series map for targeted video embeds
                series_res = requests.get(f"{BASE_URL}/series/{anime_id}", timeout=15)
                request_tracker += 1
                
                if series_res.status_code == 200:
                    ep_data = series_res.json()
                    save_episodes_to_db(anime_id, ep_data.get('episodes', []))
                
                time.sleep(0.4) # Tiny safety buffer between iterations
                
            page += 1
            
        except Exception as e:
            print(f"✖ Operational Exception Encountered: {str(e)}. Retrying loop context in 10 seconds...")
            time.sleep(10)
            continue

if __name__ == "__main__":
    run_scraper_autoloop()
