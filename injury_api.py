# requirements.txt : fastapi, uvicorn, requests, beautifulsoup4, lxml, nba_api, pandas

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
import re
from datetime import datetime, date

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration NBA-API (laissez en bas)
from nba_api.stats.static import players
from nba_api.stats.endpoints import commonplayerinfo

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
        # Fallback générique en cas d'échec de l'API NBA
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
    
    # ESPN Mappings (Nom de l'équipe court pour l'URL)
    espn_abbr = abbr_lower
    if abbr_lower == 'uta': espn_abbr = 'utah'
    if abbr_lower == 'nop': espn_abbr = 'no'
    if abbr_lower == 'gsw': espn_abbr = 'gs'
    if abbr_lower == 'sas': espn_abbr = 'sa'
    if abbr_lower == 'nyk': espn_abbr = 'ny'
    if abbr_lower == 'phx': espn_abbr = 'phx'
    # URL ESPN spécifique à l'équipe (par ex. /_/name/no pour New Orleans)
    espn_url = f"https://www.espn.com/nba/team/injuries/_/name/{espn_abbr}"
    
    # CBS Mappings (Slug complet pour l'URL)
    # Ex: ATL/atlanta-hawks/injuries/
    team_name_fixed = team_name.replace('76ers', '76ers').replace('Trail Blazers', 'trail-blazers')
    slug_cbs = f"{team_city}-{team_name_fixed}".lower().replace(' ', '-')
    cbs_url = f"https://www.cbssports.com/nba/teams/{team_abbr.upper()}/{slug_cbs}/injuries/"

    # NBC Mappings (Slug complet pour l'URL)
    slug_nbc = f"{team_city}-{team_name}".lower().replace(' ', '-')
    nbc_url = f"https://www.nbcsports.com/nba/{slug_nbc}/injuries" 

    return espn_url, cbs_url, nbc_url

def determine_status_from_text(text):
    """Détermine le statut court à partir du texte brut de la ligne d'incidence."""
    lower_txt = text.lower()
    if "out" in lower_txt or "absent" in lower_txt: return "Out"
    if "doubtful" in lower_txt: return "Doubtful"
    if "questionable" in lower_txt: return "Questionable"
    if "day-to-day" in lower_txt: return "Day-to-Day"
    if "probable" in lower_txt: return "Probable"
    if "available" in lower_txt or "active" in lower_txt: return "Available"
    return "Listé"

# --- SCRAPERS ---

def scrape_espn_team_page(player_name, url):
    """
    Scrape la page d'incidence spécifique à l'équipe ESPN.
    Approche robuste : recherche du conteneur parent (ligne du tableau) par le nom du joueur.
    """
    try:
        if not url: return None
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Cibler la table principale des blessures
            table = soup.find('div', id='fittPageContainer').find('table')
            if not table: return None
            
            # Cherche toutes les lignes TR dans le corps de la table
            rows = table.find_all('tr')
            
            for row in rows:
                if player_name.lower() in row.get_text().lower():
                    # Ligne trouvée, extraction du texte
                    full_text = row.get_text(" ", strip=True)
                    
                    if len(full_text) > 30:
                        status_short = determine_status_from_text(full_text)
                        
                        # Tenter d'extraire les colonnes pour une mise à jour précise (Injury et Status sont généralement les 2e et 3e cols)
                        cols = row.find_all('td')
                        update_parts = []
                        if len(cols) >= 3:
                            # Col 1: Player Name, Col 2: Injury, Col 3: Status
                            update_parts.append(cols[1].get_text(" ", strip=True)) # Injury
                            update_parts.append(cols[2].get_text(" ", strip=True)) # Status
                        
                        update_text = " ".join(update_parts)
                        # Fallback au texte complet si les colonnes sont vides
                        if not update_text.strip():
                           update_text = full_text.replace(player_name, "").strip()
                        
                        return {
                            "status": status_short,
                            "update": update_text[:250].strip() + "...",
                            "timestamp": time.strftime("%H:%M")
                        }
        return None
    except Exception as e: 
        print(f"Erreur scraping ESPN: {e}")
        return None

def scrape_cbs_team_page(player_name, url):
    """
    Scrape la page d'incidence spécifique à l'équipe CBS Sports.
    Approche plus ciblée sur la structure du tableau CBS.
    """
    try:
        if not url: return None
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Cibler le tableau principal des blessures de CBS (classe standard)
            injury_table = soup.find('table', class_='TableBase')
            if not injury_table: return None
            
            # Chercher la ligne qui contient le nom du joueur
            for row in injury_table.find_all('tr'):
                if player_name.lower() in row.get_text().lower():
                    # Ligne trouvée
                    cols = row.find_all('td')
                    if len(cols) >= 4:
                        # Colonnes CBS: Player (0), Injury (1), Updated (2), Status (3)
                        injury = cols[1].get_text(" ", strip=True)
                        updated_date = cols[2].get_text(" ", strip=True)
                        status = cols[3].get_text(" ", strip=True) 

                        full_update = f"{injury} - {status} (Mise à jour: {updated_date})"
                        status_short = determine_status_from_text(status)

                        return {
                            "status": status_short or status,
                            "update": full_update[:250].strip() + "...",
                            "timestamp": updated_date
                        }
        return None
    except Exception as e:
        print(f"Erreur scraping CBS: {e}")
        return None

def scrape_nbc_team_page(player_name, url):
    """
    Scrape la page /injuries de NBC Sports / Rotoworld.
    Approche basée sur la recherche de conteneurs de NEWS contenant le nom du joueur.
    """
    try:
        if not url: return None
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Cibler les conteneurs de news (Rotoworld utilise souvent ces classes)
            news_containers = soup.find_all(['div', 'article'], class_=re.compile(r'PlayerNews-item|StoryLink|article|StoryItem', re.IGNORECASE))
            
            for container in news_containers:
                full_text = container.get_text(" ", strip=True)
                
                # S'assurer que le nom du joueur est présent et que c'est une entrée significative
                if player_name.lower() in full_text.lower() and len(full_text) > 70:
                    
                    # Tenter de trouver la date de la news pour s'assurer qu'elle est récente (pas parfait, mais mieux que rien)
                    date_element = container.find(['span', 'p'], class_=re.compile(r'date|timestamp|pubTime', re.IGNORECASE))
                    date_text = date_element.get_text(" ", strip=True) if date_element else "Récent"
                    
                    status_short = determine_status_from_text(full_text)
                    
                    # Le titre et le corps de la news sont souvent dans des balises spécifiques
                    title = container.find(['h2', 'h3', 'a'], class_=re.compile(r'title|headline', re.IGNORECASE))
                    body = container.find('p', class_=re.compile(r'content|body|description|summary', re.IGNORECASE))

                    update_text = ""
                    if title: update_text += title.get_text(" ", strip=True) + " "
                    if body: update_text += body.get_text(" ", strip=True)

                    if not update_text:
                        update_text = full_text.replace(player_name, "").strip()
                    
                    return {
                        "status": status_short,
                        "update": update_text[:300].strip() + "...",
                        "timestamp": date_text
                    }
                        
        return None
    except Exception as e:
        print(f"Erreur NBC Team (Injuries): {e}")
        return None

@app.get("/api/injury/{player_name}")
def get_injury_status(player_name: str):
    clean_name = player_name.strip()
    
    player_info = {"team": "NBA", "age": "", "espn_link": "", "cbs_link": "", "nbc_link": ""}
    
    try:
        found_players = players.find_players_by_full_name(clean_name)
        if found_players:
            pid = found_players[0]['id']
            # Utilise CommonPlayerInfo pour récupérer l'info de l'équipe et la date de naissance
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

    # Scrape les sources en utilisant les liens d'équipe spécifiques
    espn_data = scrape_espn_team_page(clean_name, player_info.get('espn_link'))
    cbs_data = scrape_cbs_team_page(clean_name, player_info.get('cbs_link'))
    nbc_data = scrape_nbc_team_page(clean_name, player_info.get('nbc_link'))
    
    # Injection des liens dans les données de source
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
