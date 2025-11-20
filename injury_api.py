# requirements.txt : fastapi, uvicorn, requests, beautifulsoup4, lxml, nba_api, pandas

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
import re
from datetime import datetime

app = FastAPI()

# Permet au frontend React de faire des requêtes au backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration NBA-API
from nba_api.stats.static import players
from nba_api.stats.endpoints import commonplayerinfo

@app.get("/api/players")
def get_all_players():
    """Récupère la liste de tous les joueurs actifs de la NBA."""
    try:
        active_players = players.get_active_players()
        formatted_list = [
            {"id": p['id'], "name": p['full_name']} 
            for p in active_players
        ]
        return formatted_list
    except Exception as e:
        print(f"Erreur chargement liste joueurs NBA: {e}")
        return [{"id": 0, "name": "Erreur chargement liste"}]

# --- OUTILS ---

def calculate_age(birth_date_str):
    """Calcule l'âge à partir d'une date de naissance."""
    try:
        birth_date = datetime.strptime(birth_date_str.split('T')[0], "%Y-%m-%d")
        today = datetime.today()
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
        return str(age)
    except:
        return "??"

def get_nbc_url(team_abbr, team_city, team_name):
    """Génère l'URL d'incidence NBC pour l'équipe donnée."""
    if not team_abbr: return None
    
    # Création du slug pour l'URL NBC (ex: portland-trail-blazers)
    slug_nbc = f"{team_city}-{team_name}".lower().replace(' ', '-').replace("'", "")
    nbc_url = f"https://www.nbcsports.com/nba/{slug_nbc}/injuries" 

    return nbc_url

def determine_status_from_text(text):
    """Détermine le statut court à partir du texte brut de la ligne d'incidence."""
    lower_txt = text.lower()
    if "out" in lower_txt or "absent" in lower_txt: return "Out"
    if "doubtful" in lower_txt: return "Doubtful"
    if "questionable" in lower_txt: return "Questionable"
    if "day-to-day" in lower_txt: return "Day-to-Day"
    if "probable" in lower_txt: return "Probable"
    return "Listé"

# --- SCRAPER NBC REVU (Approche Bottom-Up) ---

def scrape_nbc_team_page(player_name, url):
    """
    Scrape la page /injuries de NBC Sports.
    Approche : Trouve le nom du joueur dans le HTML, puis remonte aux parents 
    pour trouver le texte contextuel.
    """
    try:
        if not url: return None
        # Headers complets pour simuler un vrai utilisateur (Chrome sur Windows)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.google.com/'
        }
        
        # Timeout un peu plus long pour laisser le temps au serveur de répondre
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # 1. Recherche directe du nom du joueur dans tout le document
            # On utilise une regex pour ignorer la casse
            target_elements = soup.find_all(string=re.compile(re.escape(player_name), re.IGNORECASE))
            
            for element in target_elements:
                # L'élément trouvé est juste une chaîne de texte. 
                # On doit vérifier ses parents pour trouver le conteneur de l'info.
                
                # On remonte jusqu'à 3 niveaux de parents pour trouver un bloc de texte substantiel
                parent = element.parent
                grandparent = parent.parent if parent else None
                greatgrandparent = grandparent.parent if grandparent else None
                
                candidates = [parent, grandparent, greatgrandparent]
                
                for container in candidates:
                    if not container: continue
                    
                    full_text = container.get_text(" ", strip=True)
                    
                    # Si le texte contient plus que juste le nom du joueur (c'est une phrase ou un paragraphe)
                    # Et ce n'est pas juste un lien de menu (souvent court)
                    if len(full_text) > len(player_name) + 20:
                        
                        # Nettoyage : On ne veut pas capturer toute la page si on est remonté trop haut (ex: body)
                        if len(full_text) > 800: continue 
                        
                        status_short = determine_status_from_text(full_text)
                        
                        # Extraction d'une date si possible (format NBC habituel : Day, Mon DD)
                        date_match = re.search(r'\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \w+ \d+\b', full_text)
                        date_text = date_match.group(0) if date_match else "Récent"
                        
                        # Nettoyage pour l'affichage
                        # On essaie d'isoler la partie "News" si possible
                        update_text = full_text
                        
                        # Si on trouve le motif "Player Name ... News Text", on essaie de couper
                        split_name = re.split(re.escape(player_name), full_text, flags=re.IGNORECASE, maxsplit=1)
                        if len(split_name) > 1:
                            # On prend ce qui suit le nom
                            update_text = player_name + split_name[1]
                        
                        return {
                            "status": status_short,
                            "update": update_text[:300].strip() + "...",
                            "timestamp": date_text
                        }

        return None
    except Exception as e:
        print(f"Erreur scraping NBC (Bottom-Up): {e}")
        return None

@app.get("/api/injury/{player_name}")
def get_injury_status(player_name: str):
    """Point d'API pour récupérer le statut d'incidence d'un joueur, uniquement via NBC."""
    clean_name = player_name.strip()
    
    player_info = {"team": "NBA", "age": "", "nbc_link": ""}
    
    # 1. Obtenir les informations de base du joueur via NBA API
    try:
        found_players = players.find_players_by_full_name(clean_name)
        if found_players:
            pid = found_players[0]['id']
            info = commonplayerinfo.CommonPlayerInfo(player_id=pid).get_data_frames()[0]
            if not info.empty:
                row = info.iloc[0]
                nbc_url = get_nbc_url(row['TEAM_ABBREVIATION'], row['TEAM_CITY'], row['TEAM_NAME'])
                player_info = {
                    "team": f"{row['TEAM_CITY']} {row['TEAM_NAME']}",
                    "age": f"{calculate_age(row['BIRTHDATE'])} ans",
                    "nbc_link": nbc_url
                }
    except Exception as e: 
        print(f"Erreur API NBA info: {e}")
        pass

    # 2. Scrape la source NBC
    nbc_data = scrape_nbc_team_page(clean_name, player_info.get('nbc_link'))
    
    # 3. Injecter le lien d'équipe dans le résultat
    if nbc_data and player_info.get('nbc_link'): 
        nbc_data['url'] = player_info['nbc_link']
    
    return {
        "player": clean_name,
        "meta": player_info,
        "sources": {
            "nbc": nbc_data
        }
    }
