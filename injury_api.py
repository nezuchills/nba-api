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

# --- SCRAPING ---

def scrape_espn(player_name):
    try:
        url = "https://www.espn.com/nba/injuries"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            for link in soup.find_all('a'):
                if player_name.lower() in link.text.lower():
                    row = link.find_parent('tr')
                    if row:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            full_text = " ".join([c.text.strip() for c in cols[1:]])
                            # Détection sommaire du statut pour le frontend
                            status_short = "Listé"
                            if "out" in full_text.lower(): status_short = "Out"
                            elif "day" in full_text.lower(): status_short = "Day-to-Day"
                            elif "questionable" in full_text.lower(): status_short = "Questionable"
                            
                            return {
                                "status": status_short,
                                "update": full_text[:150] + "..." if len(full_text) > 150 else full_text,
                                "timestamp": time.strftime("%H:%M"),
                                "url": url # Lien pour redirection
                            }
        return None
    except Exception as e:
        return None

def scrape_cbs(player_name):
    try:
        url = "https://www.cbssports.com/nba/injuries/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            for link in soup.find_all('a'):
                if player_name.lower() in link.text.lower():
                    row = link.find_parent('tr')
                    if row:
                        cols = row.find_all('td')
                        if len(cols) >= 5:
                            injury = cols[3].text.strip()
                            status = cols[4].text.strip()
                            return {
                                "status": status or "Blessé",
                                "update": f"{injury} - {status}",
                                "timestamp": time.strftime("%H:%M"),
                                "url": url # Lien pour redirection
                            }
        return None
    except Exception as e:
        return None

@app.get("/api/injury/{player_name}")
def get_injury_status(player_name: str):
    clean_name = player_name.strip()
    
    espn_data = scrape_espn(clean_name)
    cbs_data = scrape_cbs(clean_name)
    
    return {
        "player": clean_name,
        "sources": {
            "espn": espn_data,
            "cbs": cbs_data
        }
    }
