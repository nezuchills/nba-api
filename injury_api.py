from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
from nba_api.stats.static import players

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- LISTE DES JOUEURS ---
@app.get("/api/players")
def get_all_players():
    try:
        active_players = players.get_active_players()
        formatted_list = [
            {"id": p['id'], "name": p['full_name'], "team": "NBA", "position": "Active"} 
            for p in active_players
        ]
        return formatted_list
    except:
        return [{"id": 0, "name": "Erreur liste", "team": "", "position": ""}]

# --- FONCTIONS DE SCRAPING ---

def scrape_espn(player_name):
    """Scrape ESPN NBA Injuries"""
    try:
        url = "https://www.espn.com/nba/injuries"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            # Recherche large dans les liens
            for link in soup.find_all('a'):
                if player_name.lower() in link.text.lower():
                    row = link.find_parent('tr')
                    if row:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            full_text = " ".join([c.text.strip() for c in cols[1:]])
                            return {
                                "status": "Listé (ESPN)",
                                "update": full_text[:150] + "..." if len(full_text) > 150 else full_text,
                                "timestamp": time.strftime("%H:%M")
                            }
        return None
    except Exception as e:
        print(f"Erreur ESPN: {e}")
        return None

def scrape_cbs(player_name):
    """Scrape CBS Sports NBA Injuries"""
    try:
        url = "https://www.cbssports.com/nba/injuries/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            # CBS utilise des liens dans des tables pour les joueurs
            for link in soup.find_all('a'):
                if player_name.lower() in link.text.lower():
                    # Remonter au TR parent
                    row = link.find_parent('tr')
                    if row:
                        cols = row.find_all('td')
                        # Colonnes CBS: Player | Position | Updated | Injury | Status
                        if len(cols) >= 5:
                            injury = cols[3].text.strip()
                            status = cols[4].text.strip()
                            return {
                                "status": status or "Blessé",
                                "update": f"{injury} - {status}",
                                "timestamp": time.strftime("%H:%M")
                            }
        return None
    except Exception as e:
        print(f"Erreur CBS: {e}")
        return None

def scrape_fantasylabs(player_name):
    """Scrape FantasyLabs NBA News"""
    try:
        # On cherche dans les news récentes, c'est le plus fiable pour FantasyLabs
        url = "https://www.fantasylabs.com/nba/news/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            # FantasyLabs liste des items de news
            news_items = soup.find_all('div', class_='news-item')
            
            for item in news_items:
                player_link = item.find('div', class_='player-name')
                if player_link and player_name.lower() in player_link.text.lower():
                    news_body = item.find('div', class_='news-body')
                    news_text = news_body.text.strip() if news_body else "Nouvelle info disponible"
                    return {
                        "status": "News",
                        "update": news_text[:150] + "..." if len(news_text) > 150 else news_text,
                        "timestamp": time.strftime("%H:%M")
                    }
        return None
    except Exception as e:
        print(f"Erreur FantasyLabs: {e}")
        return None

# --- ENDPOINT PRINCIPAL ---
@app.get("/api/injury/{player_name}")
def get_injury_status(player_name: str):
    clean_name = player_name.strip()
    
    # Lancement séquentiel (pourrait être parallélisé pour plus de vitesse)
    espn_data = scrape_espn(clean_name)
    cbs_data = scrape_cbs(clean_name)
    fl_data = scrape_fantasylabs(clean_name)
    
    return {
        "player": clean_name,
        "sources": {
            "espn": espn_data,
            "cbs": cbs_data, 
            "fantasyLabs": fl_data
        }
    }
