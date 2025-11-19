from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
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
        # On récupère la liste statique pour la recherche rapide
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
        # Format NBA API typique: "1984-12-30T00:00:00"
        birth_date = datetime.strptime(birth_date_str.split('T')[0], "%Y-%m-%d")
        today = datetime.today()
        return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    except:
        return "??"

def get_team_urls(team_abbr, team_city, team_name):
    """Génère les liens directs vers les pages blessures des équipes"""
    if not team_abbr:
        return None, None
    
    abbr_lower = team_abbr.lower()
    
    # Mapping ESPN (Certaines équipes ont des codes différents)
    # ex: Utah -> utah (pas uta), New Orleans -> no, Phoenix -> phx
    espn_abbr = abbr_lower
    if abbr_lower == 'uta': espn_abbr = 'utah'
    if abbr_lower == 'nop': espn_abbr = 'no'
    if abbr_lower == 'gsw': espn_abbr = 'gs'
    if abbr_lower == 'sas': espn_abbr = 'sa'
    if abbr_lower == 'nyk': espn_abbr = 'ny'
    
    espn_url = f"https://www.espn.com/nba/team/injuries/_/name/{espn_abbr}"
    
    # Mapping CBS
    # ex: https://www.cbssports.com/nba/teams/ATL/atlanta-hawks/injuries/
    slug = f"{team_city}-{team_name}".lower().replace(' ', '-').replace('76ers', '76ers') # Phila case
    cbs_url = f"https://www.cbssports.com/nba/teams/{team_abbr.upper()}/{slug}/injuries/"
    
    return espn_url, cbs_url

# --- SCRAPING ---

def scrape_espn(player_name, team_url):
    try:
        # On utilise l'URL générique si l'URL d'équipe échoue ou n'est pas fournie
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
                            elif "day" in lower_txt: status_short = "Day-to-Day"
                            elif "questionable" in lower_txt: status_short = "Questionable"
                            elif "doubtful" in lower_txt: status_short = "Doubtful"
                            elif "probable" in lower_txt: status_short = "Probable"
                            
                            return {
                                "status": status_short,
                                "update": full_text[:200],
                                "timestamp": time.strftime("%H:%M")
                            }
        return None
    except:
        return None

def scrape_cbs(player_name, team_url):
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
    except:
        return None

@app.get("/api/injury/{player_name}")
def get_injury_status(player_name: str):
    clean_name = player_name.strip()
    
    # 1. Récupérer ID et Infos Joueur (Equipe, Age)
    # Cela prend un peu de temps API mais permet d'avoir les liens corrects
    player_info = {"team": "NBA", "age": "", "espn_link": "", "cbs_link": ""}
    
    try:
        found_players = players.find_players_by_full_name(clean_name)
        if found_players:
            pid = found_players[0]['id']
            # Appel API NBA pour les détails
            info = commonplayerinfo.CommonPlayerInfo(player_id=pid).get_data_frames()[0]
            if not info.empty:
                row = info.iloc[0]
                team_abbr = row['TEAM_ABBREVIATION']
                team_city = row['TEAM_CITY']
                team_name = row['TEAM_NAME']
                
                # Construction des liens
                espn_url, cbs_url = get_team_urls(team_abbr, team_city, team_name)
                
                player_info = {
                    "team": f"{team_city} {team_name}",
                    "age": f"{calculate_age(row['BIRTHDATE'])} ans",
                    "espn_link": espn_url,
                    "cbs_link": cbs_url
                }
    except Exception as e:
        print(f"Erreur metadata: {e}")

    # 2. Scraping
    espn_data = scrape_espn(clean_name, player_info['espn_link'])
    cbs_data = scrape_cbs(clean_name, player_info['cbs_link'])
    
    # On injecte les liens d'équipe dans les objets data pour le frontend
    if espn_data: espn_data['url'] = player_info['espn_link']
    if cbs_data: cbs_data['url'] = player_info['cbs_link']
    
    return {
        "player": clean_name,
        "meta": player_info,
        "sources": {
            "espn": espn_data,
            "cbs": cbs_data
        }
    }
