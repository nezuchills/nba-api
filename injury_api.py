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
    
    # ESPN Mappings
    espn_abbr = abbr_lower
    if abbr_lower == 'uta': espn_abbr = 'utah'
    if abbr_lower == 'nop': espn_abbr = 'no'
    if abbr_lower == 'gsw': espn_abbr = 'gs'
    if abbr_lower == 'sas': espn_abbr = 'sa'
    if abbr_lower == 'nyk': espn_abbr = 'ny'
    if abbr_lower == 'phx': espn_abbr = 'phx'
    # URL ESPN spécifique à l'équipe (par ex. /_/name/no pour New Orleans)
    espn_url = f"https://www.espn.com/nba/team/injuries/_/name/{espn_abbr}"
    
    # CBS Mappings
    slug_cbs = f"{team_city}-{team_name}".lower().replace(' ', '-').replace('76ers', '76ers')
    cbs_url = f"https://www.cbssports.com/nba/teams/{team_abbr.upper()}/{slug_cbs}/injuries/"

    # NBC Mappings (CORRIGÉ : Utilisation de /injuries comme demandé)
    slug_nbc = f"{team_city}-{team_name}".lower().replace(' ', '-')
    nbc_url = f"https://www.nbcsports.com/nba/{slug_nbc}/injuries" 

    return espn_url, cbs_url, nbc_url

# --- SCRAPERS ---

def determine_status_from_text(text):
    """Détermine le statut court à partir du texte brut de la ligne d'incidence."""
    lower_txt = text.lower()
    if "out" in lower_txt: return "Out"
    if "doubtful" in lower_txt: return "Doubtful"
    if "questionable" in lower_txt: return "Questionable"
    if "day-to-day" in lower_txt: return "Day-to-Day"
    if "probable" in lower_txt: return "Probable"
    if "available" in lower_txt or "active" in lower_txt: return "Available"
    return "Listé"

def scrape_espn_team_page(player_name, url):
    """
    Scrape la page d'incidence spécifique à l'équipe ESPN.
    Nouvelle approche : Cibler la ligne complète et analyser le texte pour plus de robustesse.
    """
    try:
        if not url: return None
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Cherche tous les liens ou cellules qui contiennent le nom du joueur
            player_elements = soup.find_all(lambda tag: tag.name in ['a', 'span', 'div', 'td'] and player_name.lower() in tag.text.lower())
            
            for element in player_elements:
                # Cherche le conteneur parent le plus pertinent (TR pour une table, DIV pour un layout)
                row_container = element.find_parent('tr') or element.find_parent('div', class_=re.compile('Injury|List|Row|Item', re.IGNORECASE))
                
                if row_container:
                    full_text = row_container.get_text(" ", strip=True)
                    
                    if len(full_text) > 30 and player_name.lower() in full_text.lower():
                        status_short = determine_status_from_text(full_text)
                        
                        # Extraire la mise à jour (l'info de blessure et statut)
                        # On essaie de trouver les colonnes Status et Injury
                        cols = row_container.find_all(['td', 'div'])
                        update_parts = []
                        for col in cols:
                            text = col.get_text(" ", strip=True)
                            if len(text) > 5 and text.lower() not in player_name.lower():
                                update_parts.append(text)
                        
                        update_text = " ".join(update_parts) or full_text.replace(player_name, "").strip()
                        
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
    Utilisation de l'approche robuste par texte pour garantir la détection du statut.
    """
    try:
        if not url: return None
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Cherche tous les liens qui contiennent le nom du joueur
            for link in soup.find_all('a'):
                if player_name.lower() in link.text.lower():
                    row = link.find_parent('tr')
                    if row:
                        full_text = row.get_text(" ", strip=True)
                        if len(full_text) > 30:
                            status_short = determine_status_from_text(full_text)
                            
                            # On récupère l'info de blessure (colonne 1) et statut (colonne 3) si possible
                            cols = row.find_all('td')
                            injury = cols[1].text.strip() if len(cols) > 1 else ""
                            status_col = cols[3].text.strip() if len(cols) > 3 else ""

                            update_text = f"{injury} - {status_col}"
                            if not injury:
                                update_text = full_text.replace(player_name, "").strip()
                            
                            return {
                                "status": status_short or status_col or "Blessé",
                                "update": update_text[:250].strip() + "...",
                                "timestamp": time.strftime("%H:%M")
                            }
        return None
    except Exception as e:
        print(f"Erreur scraping CBS: {e}")
        return None

def scrape_nbc_team_page(player_name, url):
    """
    Scrape la page /injuries de NBC Sports / Rotoworld.
    Nouvelle approche : Cibler la ligne complète de la liste d'incidents et analyser le texte.
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
            
            # Cherche les conteneurs de type ligne de tableau/liste qui contiennent le nom du joueur
            player_rows = soup.find_all(lambda tag: tag.name in ['tr', 'div', 'li', 'article'] and player_name.lower() in tag.get_text().lower())

            for row in player_rows:
                # Filtrer les conteneurs trop courts pour être une mise à jour d'incidence réelle
                full_text = row.get_text(" ", strip=True)

                if len(full_text) > 50 and player_name.lower() in full_text.lower():
                    
                    status_short = determine_status_from_text(full_text)
                    
                    # Le texte brut de la ligne est notre meilleure mise à jour
                    update_text = full_text.replace(player_name, "").strip()
                    
                    return {
                        "status": status_short,
                        "update": update_text[:300].strip() + "...",
                        "timestamp": "Liste Incidents" 
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
