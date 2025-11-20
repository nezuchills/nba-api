# requirements.txt : fastapi, uvicorn, requests, beautifulsoup4, lxml, nba_api, pandas

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
import re
from datetime import datetime
from nba_api.stats.static import players
from nba_api.stats.endpoints import commonplayerinfo

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
            {"id": p['id'], "name": p['full_name']} 
            for p in active_players
        ]
        return formatted_list
    except:
        return [{"id": 0, "name": "Erreur chargement liste"}]

# --- OUTILS ---

def calculate_age(birth_date_str):
    try:
        birth_date = datetime.strptime(birth_date_str.split('T')[0], "%Y-%m-%d")
        today = datetime.today()
        return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    except:
        return "??"

def get_team_urls(team_abbr, team_city, team_name):
    if not team_abbr: return None, None, None
    
    abbr_lower = team_abbr.lower()
    
    # ESPN Mappings
    espn_abbr = abbr_lower
    if abbr_lower == 'uta': espn_abbr = 'utah'
    if abbr_lower == 'nop': espn_abbr = 'no'
    if abbr_lower == 'gsw': espn_abbr = 'gs'
    if abbr_lower == 'sas': espn_abbr = 'sa'
    if abbr_lower == 'nyk': espn_abbr = 'ny'
    if abbr_lower == 'phx': espn_abbr = 'phx'
    espn_url = f"https://www.espn.com/nba/team/injuries/_/name/{espn_abbr}"
    
    # CBS Mappings
    slug_cbs = f"{team_city}-{team_name}".lower().replace(' ', '-').replace('76ers', '76ers')
    cbs_url = f"https://www.cbssports.com/nba/teams/{team_abbr.upper()}/{slug_cbs}/injuries/"

    # NBC Mappings (CORRIGÉ : Ajout de /player-news)
    # Format: https://www.nbcsports.com/nba/new-orleans-pelicans/player-news
    slug_nbc = f"{team_city}-{team_name}".lower().replace(' ', '-')
    nbc_url = f"https://www.nbcsports.com/nba/{slug_nbc}/player-news"

    return espn_url, cbs_url, nbc_url

# --- SCRAPERS ---

def scrape_espn(player_name):
    try:
        target_url = "https://www.espn.com/nba/injuries"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(target_url, headers=headers, timeout=4)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            for link in soup.find_all('a'):
                if player_name.lower() in link.text.lower():
                    row = link.find_parent('tr')
                    if row:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            full_text = " ".join([c.text.strip() for c in cols[1:]])
                            status_short = "Listé"
                            lower_txt = full_text.lower()
                            if "out" in lower_txt: status_short = "Out"
                            elif "day-to-day" in lower_txt: status_short = "Day-to-Day"
                            elif "questionable" in lower_txt: status_short = "Questionable"
                            elif "probable" in lower_txt: status_short = "Probable"
                            clean_update = full_text.replace(player_name, "").strip()
                            return {
                                "status": status_short,
                                "update": clean_update[:200],
                                "timestamp": time.strftime("%H:%M")
                            }
        return None
    except: return None

def scrape_cbs(player_name):
    try:
        target_url = "https://www.cbssports.com/nba/injuries/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(target_url, headers=headers, timeout=4)
        
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
                                "timestamp": time.strftime("%H:%M")
                            }
        return None
    except: return None

def scrape_nbc_team_page(player_name, url):
    """
    Stratégie ultra-ciblée : Va sur la page News de l'équipe.
    Recherche la news la plus récente où le NOM DU JOUEUR est dans le TITRE.
    """
    try:
        if not url: return None
        
        # Headers pour ressembler à un vrai navigateur
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Cibler les conteneurs de news. Rotoworld/NBC utilise souvent la classe 'PlayerNews-item'
            # Mais par sécurité, on cible une div générique et on vérifie son contenu.
            
            # On cherche les titres de news (souvent des <h3> ou <h4>) qui contiennent le nom du joueur
            # On cherche spécifiquement la balise <a> dans la structure principale de l'article (ex: un h4 ou un h3 dans une div)
            
            # Cibler les blocs d'articles complets pour garantir la bonne chronologie
            # Rotoworld utilise des structures variées, on cible les liens qui ont l'air d'être des titres
            
            # Recherche de tous les liens qui pourraient être des titres de news
            news_links = soup.find_all('a', href=True)
            
            for link in news_links:
                title_text = link.get_text(" ", strip=True)
                
                # S'assurer que le nom du joueur est dans le titre de l'article
                if player_name.lower() in title_text.lower():
                    # Une fois le titre ciblé, on essaie de remonter au conteneur de la news pour extraire le corps.
                    # Le corps est souvent dans une balise <p> juste après le titre.
                    
                    # On cherche le parent commun qui englobe le titre et le corps de la news (souvent une div)
                    news_container = link.find_parent('div', class_=re.compile(r'NewsItem|PlayerNews-item|rotoworld-news-story', re.IGNORECASE))
                    
                    # Si on ne trouve pas de conteneur structuré, on utilise le texte suivant le lien.
                    if not news_container:
                        # Fallback: chercher le premier paragraphe ou texte significatif après le lien
                        container = link.find_next_sibling(['p', 'div'])
                    else:
                        # Chercher le corps de la news dans le conteneur structuré
                        container = news_container.find('p', class_=re.compile(r'NewsItem-content|Body', re.IGNORECASE)) or news_container.find('p')

                    if container:
                        full_text = title_text + " " + container.get_text(" ", strip=True)
                    else:
                        full_text = title_text # Si on n'a que le titre

                    # Vérification de sécurité : longueur minimale pour être une news
                    if len(full_text) > 50:
                        
                        status_short = "News"
                        lower_txt = full_text.lower()
                        
                        # Déterminer le statut à partir du corps de la news
                        if "out" in lower_txt and ("ruled" in lower_txt or "will not play" in lower_txt): status_short = "Out"
                        elif "available" in lower_txt: status_short = "Available"
                        elif "questionable" in lower_txt: status_short = "Questionable"
                        elif "day-to-day" in lower_txt: status_short = "Day-to-Day"
                        elif "probable" in lower_txt: status_short = "Probable"
                        
                        # Puisque nous avons trouvé la première news de la liste (la plus récente ET pertinente)
                        return {
                            "status": status_short,
                            "update": full_text[:300].strip() + "...",
                            "timestamp": "Récent" 
                        }
                        
        return None
    except Exception as e:
        # Afficher l'erreur dans la console pour le debug si besoin
        print(f"Erreur NBC Team (Scraper mis à jour): {e}")
        return None

@app.get("/api/injury/{player_name}")
def get_injury_status(player_name: str):
    clean_name = player_name.strip()
    
    player_info = {"team": "NBA", "age": "", "espn_link": "", "cbs_link": "", "nbc_link": ""}
    
    try:
        found_players = players.find_players_by_full_name(clean_name)
        if found_players:
            pid = found_players[0]['id']
            info = commonplayerinfo.CommonPlayerInfo(player_id=pid).get_data_frames()[0]
            if not info.empty:
                row = info.iloc[0]
                espn, cbs, nbc = get_team_urls(row['TEAM_ABBREVIATION'], row['TEAM_CITY'], row['TEAM_NAME'])
                player_info = {
                    "team": f"{row['TEAM_CITY']} {row['TEAM_NAME']}",
                    "age": f"{calculate_age(row['BIRTHDATE'])} ans",
                    "espn_link": espn,
                    "cbs_link": cbs,
                    "nbc_link": nbc
                }
    except: pass

    # 1. Scrape ESPN (Global List)
    espn_data = scrape_espn(clean_name)
    
    # 2. Scrape CBS (Global List)
    cbs_data = scrape_cbs(clean_name)
    
    # 3. Scrape NBC (Page d'équipe Spécifique - Ciblage sur le Titre de l'article)
    nbc_data = scrape_nbc_team_page(clean_name, player_info.get('nbc_link'))
    
    # Injection des liens
    if espn_data: espn_data['url'] = player_info['espn_link']
    if cbs_data: cbs_data['url'] = player_info['cbs_link']
    if nbc_data: nbc_data['url'] = player_info['nbc_link']
    
    return {
        "player": clean_name,
        "meta": player_info,
        "sources": {
            "espn": espn_data,
            "cbs": cbs_data,
            "nbc": nbc_data
        }
    }
