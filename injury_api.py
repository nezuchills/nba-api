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

# --- NOUVELLE LOGIQUE DE SCRAPING PLUS PRÉCISE ---
def scrape_espn(player_name):
    try:
        url = "https://www.espn.com/nba/injuries"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.content, 'lxml')
        
        # On cherche tous les liens car les noms des joueurs sont des liens dans le tableau
        links = soup.find_all('a')
        
        for link in links:
            if player_name.lower() in link.text.lower():
                # Bingo, on a trouvé le joueur. On remonte à la ligne (tr) du tableau
                row = link.find_parent('tr')
                if row:
                    cols = row.find_all('td')
                    # Structure typique ESPN : Nom | Pos | Date | Statut | Commentaire
                    # On récupère tout le texte pertinent
                    if len(cols) >= 2:
                        # On essaie de concaténer le statut et le commentaire
                        # Le statut est souvent dans la colonne 4 (index 3) et commentaire en 5 (index 4)
                        full_text = ""
                        for col in cols[1:]: # On ignore la colonne nom
                            text = col.text.strip()
                            if text:
                                full_text += text + " "
                        
                        return {
                            "status": "Blessé",
                            "update": full_text.strip(), # Ex: "Day-to-Day Out with ankle injury"
                            "timestamp": time.strftime("%H:%M")
                        }
        
        return None # Pas trouvé dans la page -> Sain
            
    except Exception as e:
        print(f"Erreur Scraping: {e}")
        return None

@app.get("/api/injury/{player_name}")
def get_injury_status(player_name: str):
    clean_name = player_name.strip()
    espn_data = scrape_espn(clean_name)
    
    return {
        "player": clean_name,
        "sources": {
            "espn": espn_data,
            "cbs": None, 
            "fantasyLabs": None
        }
    }
