from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
from nba_api.stats.static import players

app = FastAPI()

# Configuration pour accepter les demandes venant de n'importe quel site (y compris ton Carrd)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 1. LISTE DES JOUEURS (Source Automatique) ---
@app.get("/api/players")
def get_all_players():
    """
    Récupère la liste officielle des joueurs NBA actifs.
    Plus besoin de fichier JSON externe.
    """
    try:
        # Récupère tous les joueurs actifs de la saison
        active_players = players.get_active_players()
        # On formate pour ton site (Nom, ID, Equipe non dispo dans cette méthode simple mais on fait sans pour l'instant)
        formatted_list = [
            {"id": p['id'], "name": p['full_name'], "team": "NBA", "position": "Active"} 
            for p in active_players
        ]
        return formatted_list
    except Exception as e:
        return [{"id": 0, "name": "Erreur chargement liste", "team": "", "position": ""}]

# --- 2. SCRAPING (Récupération des blessures) ---
def scrape_espn(player_name):
    try:
        url = "https://www.espn.com/nba/injuries"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            # Recherche simple (Pour une V1)
            if player_name.lower() in response.text.lower():
                return {
                    "status": "Listé Blessé",
                    "update": "Ce joueur apparaît sur le rapport officiel d'ESPN.",
                    "timestamp": time.strftime("%H:%M")
                }
        return None
    except:
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
