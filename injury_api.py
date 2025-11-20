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
    
    # ESPN
    espn_abbr = abbr_lower
    if abbr_lower == 'uta': espn_abbr = 'utah'
    if abbr_lower == 'nop': espn_abbr = 'no'
    if abbr_lower == 'gsw': espn_abbr = 'gs'
    if abbr_lower == 'sas': espn_abbr = 'sa'
    if abbr_lower == 'nyk': espn_abbr = 'ny'
    if abbr_lower == 'phx': espn_abbr = 'phx'
    espn_url = f"https://www.espn.com/nba/team/injuries/_/name/{espn_abbr}"
    
    # CBS
    slug_cbs = f"{team_city}-{team_name}".lower().replace(' ', '-').replace('76ers', '76ers')
    cbs_url = f"https://www.cbssports.com/nba/teams/{team_abbr.upper()}/{slug_cbs}/injuries/"

    # NBC (Lien pour l'affichage frontend uniquement)
    slug_nbc = f"{team_city}-{team_name}".lower().replace(' ', '-')
    nbc_url = f"https://www.nbcsports.com/fantasy/basketball/team-news/{slug_nbc}"

    return espn_url, cbs_url, nbc_url

# --- SCRAPERS ---

def scrape_espn(player_name, team_url):
    try:
        target_url = team_url if team_url else "https://www.espn.com/nba/injuries"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(target_url, headers=headers, timeout=4)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            for link in soup.find_all('a'):
                if player_name.lower() in link.text.lower():
                    row = link.find_parent('tr')
                    if row:
                        cols = row.find_all('td')
                        full_text = row.get_text(" ", strip=True)
                        
                        status_short = "Listé"
                        lower_txt = full_text.lower()
                        if "out" in lower_txt: status_short = "Out"
                        elif "day-to-day" in lower_txt: status_short = "Day-to-Day"
                        elif "questionable" in lower_txt: status_short = "Questionable"
                        elif "doubtful" in lower_txt: status_short = "Doubtful"
                        elif "probable" in lower_txt: status_short = "Probable"
                        
                        clean_update = full_text.replace(player_name, "").strip()
                        return {
                            "status": status_short,
                            "update": clean_update[:200],
                            "timestamp": time.strftime("%H:%M")
                        }
        return None
    except: return None

def scrape_cbs(player_name, team_url):
    try:
        target_url = team_url if team_url else "https://www.cbssports.com/nba/injuries/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(target_url, headers=headers, timeout=4)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            for link in soup.find_all('a'):
                if player_name.lower() in link.text.lower():
                    row = link.find_parent('tr')
                    if row:
                        cols = row.find_all('td')
                        if len(cols) >= 3:
                            injury_info = " ".join([c.text.strip() for c in cols[2:]])
                            status = "Blessé"
                            if "Questionable" in injury_info: status = "Questionable"
                            if "Out" in injury_info: status = "Out"
                            return {
                                "status": status,
                                "update": injury_info,
                                "timestamp": time.strftime("%H:%M")
                            }
        return None
    except: return None

# --- STRATÉGIE NBC ROBUSTE (Fallback FantasyPros) ---

def scrape_fantasypros_player(player_name):
    """
    Scrape la page joueur FantasyPros qui contient les news NBC/Rotoworld.
    URL: https://www.fantasypros.com/nba/players/prenom-nom.php
    """
    try:
        # Conversion nom: "LeBron James" -> "lebron-james"
        # "Shai Gilgeous-Alexander" -> "shai-gilgeous-alexander"
        slug = player_name.lower().replace(" ", "-").replace(".", "").replace("'", "")
        url = f"https://www.fantasypros.com/nba/players/{slug}.php"
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Recherche de la première news dans la timeline
            # FantasyPros structure: div.content (ou .news-item) -> p
            
            # On cherche le bloc "Recent News" ou "Latest News"
            # Souvent dans une div avec class "player-news-item" ou juste le premier paragraphe significatif
            
            news_items = soup.find_all('div', class_='content')
            for item in news_items:
                # Vérifions s'il y a une date récente ou un titre de news
                # FantasyPros met souvent: <b>Source:</b> ... <p>The news text</p>
                paragraphs = item.find_all('p')
                for p in paragraphs:
                    text = p.get_text().strip()
                    # Filtrer les textes trop courts ou non pertinents
                    if len(text) > 30 and player_name.split()[1] in text: # Le nom de famille est dans le texte
                         
                        status_short = "News"
                        lower_txt = text.lower()
                        if "out" in lower_txt and "rule" in lower_txt: status_short = "Out"
                        elif "questionable" in lower_txt: status_short = "Questionable"
                        elif "day-to-day" in lower_txt: status_short = "Day-to-Day"
                        elif "available" in lower_txt: status_short = "Available"
                        
                        return {
                            "status": status_short,
                            "update": text[:250] + "...",
                            "timestamp": "Récent"
                        }
                        
            # Fallback: on cherche n'importe quel paragraphe contenant "injury" ou "out"
            snippet = soup.find(string=re.compile(r'(injury|ruled out|questionable|game-time)', re.IGNORECASE))
            if snippet:
                parent = snippet.find_parent('p') or snippet.find_parent('div')
                if parent:
                     return {
                        "status": "News",
                        "update": parent.get_text().strip()[:200] + "...",
                        "timestamp": "Récent"
                    }
                    
    except Exception as e:
        print(f"Erreur FantasyPros: {e}")
        return None
    return None

def scrape_nbc_chain(player_name, nbc_team_url):
    # 1. On tente le lien d'équipe NBC (souvent bloqué)
    try:
        if nbc_team_url:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(nbc_team_url, headers=headers, timeout=3)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'lxml')
                # Recherche simple texte
                if player_name in soup.text:
                    # Logique complexe d'extraction omise car souvent bloqué
                    pass 
    except: pass

    # 2. LA VRAIE SOLUTION : FantasyPros (Page Joueur Directe)
    # C'est notre source "NBC" de facto car ils partagent les mêmes infos
    return scrape_fantasypros_player(player_name)


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

    espn_data = scrape_espn(clean_name, player_info.get('espn_link'))
    cbs_data = scrape_cbs(clean_name, player_info.get('cbs_link'))
    
    # On utilise la chaîne robuste pour NBC
    nbc_data = scrape_nbc_chain(clean_name, player_info.get('nbc_link'))
    
    if espn_data: espn_data['url'] = player_info['espn_link']
    if cbs_data: cbs_data['url'] = player_info['cbs_link']
    # Si on a trouvé via FantasyPros, on garde quand même le lien NBC officiel pour le clic utilisateur
    # car c'est ce qu'ils veulent voir
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
