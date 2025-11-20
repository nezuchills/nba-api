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

# --- SCRAPER NBC REVU POUR ROBUSTESSE MAXIMALE ---

def scrape_nbc_team_page(player_name, url):
    """
    Scrape la page /injuries de NBC Sports en utilisant une recherche très large 
    des conteneurs de news.
    """
    try:
        if not url: return None
        # Simuler un navigateur classique
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # TENTATIVE AGRESSIVE: Rechercher tous les conteneurs d'articles ou de news potentiels
            # On cible les balises structurelles courantes pour les items de liste de news
            all_potential_items = soup.find_all(['li', 'div', 'article', 'a'], class_=re.compile(r'StoryLink|StoryItem|article|news|feed|content', re.IGNORECASE))
            
            # ITÉRATION et FILTRAGE
            for container in all_potential_items:
                full_text = container.get_text(" ", strip=True)
                
                # Le nom du joueur doit être présent et le texte doit être assez long 
                # pour être une vraie news (filtrer les liens de navigation)
                if player_name.lower() in full_text.lower() and len(full_text) > 70:
                    
                    # 1. Déterminer le statut
                    status_short = determine_status_from_text(full_text)
                    
                    # 2. Tenter de trouver la date (dans le conteneur ou ses enfants)
                    date_element = container.find(['span', 'p', 'time'], class_=re.compile(r'date|timestamp|pubTime|time', re.IGNORECASE))
                    date_text = date_element.get_text(" ", strip=True) if date_element else "Récent"
                    
                    # 3. Tenter d'isoler l'update (titre + corps)
                    title_element = container.find(['h2', 'h3', 'a'], class_=re.compile(r'title|headline|link', re.IGNORECASE))
                    body_element = container.find('p', class_=re.compile(r'content|body|description|summary', re.IGNORECASE))

                    update_text = ""
                    if title_element: update_text += title_element.get_text(" ", strip=True) + " "
                    if body_element: update_text += body_element.get_text(" ", strip=True)

                    # Si on n'a rien trouvé de structuré, utiliser le texte brut du conteneur
                    if not update_text:
                        # Remplacer le nom du joueur par un espace pour nettoyer l'update
                        update_text = re.sub(r'\b' + re.escape(player_name) + r'\b', '', full_text, flags=re.IGNORECASE).strip()

                    # Si le texte est toujours trop court, on peut considérer que ce n'est pas la bonne news
                    if len(update_text) < 30: continue
                    
                    return {
                        "status": status_short,
                        "update": update_text[:300].strip() + "...",
                        "timestamp": date_text
                    }
                        
        return None
    except Exception as e:
        # Afficher l'erreur pour le débogage si le scraping échoue complètement
        print(f"Erreur scraping NBC (Version MAX ROBuste): {e}")
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
