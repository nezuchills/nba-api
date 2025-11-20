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
    
    # ESPN mapping
    espn_abbr = abbr_lower
    if abbr_lower == 'uta': espn_abbr = 'utah'
    if abbr_lower == 'nop': espn_abbr = 'no'
    if abbr_lower == 'gsw': espn_abbr = 'gs'
    if abbr_lower == 'sas': espn_abbr = 'sa'
    if abbr_lower == 'nyk': espn_abbr = 'ny'
    espn_url = f"https://www.espn.com/nba/team/injuries/_/name/{espn_abbr}"
    
    # CBS mapping
    slug = f"{team_city}-{team_name}".lower().replace(' ', '-').replace('76ers', '76ers')
    cbs_url = f"https://www.cbssports.com/nba/teams/{team_abbr.upper()}/{slug}/injuries/"

    # NBC/FantasyNews Link
    nbc_url = "https://www.nbcsports.com/fantasy/basketball/player-news"

    return espn_url, cbs_url, nbc_url

# --- SCRAPING ---

def scrape_espn(player_name, team_url):
    try:
        # ESPN Direct
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get("https://www.espn.com/nba/injuries", headers=headers, timeout=4)
        
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
                            return {
                                "status": status_short,
                                "update": full_text[:200],
                                "timestamp": time.strftime("%H:%M")
                            }
        return None
    except: return None

def scrape_cbs(player_name, team_url):
    try:
        # CBS Direct
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get("https://www.cbssports.com/nba/injuries/", headers=headers, timeout=4)
        
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

# --- CHAÎNE DE SCRAPING NEWS (NBC -> ROTOWIRE -> FANTASYPROS) ---

def scrape_fantasypros(player_name):
    """Fallback 2 : FantasyPros (Très robuste)"""
    try:
        url = "https://www.fantasypros.com/nba/player-news.php"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            # Cherche les liens avec le nom du joueur
            for link in soup.find_all('a'):
                if player_name.lower() in link.text.lower():
                    # Remonter au conteneur de la news
                    # Structure souvent: div.content ou div.player-news-item
                    container = link.find_parent('div', class_='content') or link.find_parent('div', class_='player-news-item')
                    if container:
                        full_text = container.text.strip()
                        # Nettoyage simple
                        clean_text = " ".join(full_text.split())
                        
                        status = "News"
                        if "out" in clean_text.lower(): status = "Out"
                        elif "questionable" in clean_text.lower(): status = "Questionable"
                        
                        return {
                            "status": status,
                            "update": clean_text[:250] + "...",
                            "timestamp": time.strftime("%H:%M")
                        }
    except: return None
    return None

def scrape_rotowire(player_name):
    """Fallback 1 : Rotowire"""
    try:
        url = "https://www.rotowire.com/basketball/news.php"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=4)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            for item in soup.find_all('div', class_='news-update'):
                player_link = item.find('a', class_='news-update__player-link')
                if player_link and player_name.lower() in player_link.text.lower():
                    news_div = item.find('div', class_='news-update__news')
                    if news_div:
                        return {
                            "status": "News",
                            "update": news_div.text.strip()[:250] + "...",
                            "timestamp": time.strftime("%H:%M")
                        }
    except: return None
    return None

def scrape_nbc_chain(player_name):
    """Tente NBC, puis Rotowire, puis FantasyPros"""
    
    # 1. Tentative NBC
    try:
        url = "https://www.nbcsports.com/fantasy/basketball/player-news"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        response = requests.get(url, headers=headers, timeout=4)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            page_text = soup.get_text(" ||| ", strip=True)
            idx = page_text.lower().find(player_name.lower())
            if idx != -1:
                snippet = page_text[idx:idx+400].replace("|||", " ").strip()
                return {
                    "status": "News (NBC)",
                    "update": snippet[:200] + "...",
                    "timestamp": time.strftime("%H:%M")
                }
    except: pass

    # 2. Fallback Rotowire
    rw_data = scrape_rotowire(player_name)
    if rw_data: 
        rw_data['update'] = "(Via Rotowire) " + rw_data['update']
        return rw_data

    # 3. Fallback FantasyPros (Souvent le plus fiable sur serveur)
    fp_data = scrape_fantasypros(player_name)
    if fp_data:
        fp_data['update'] = "(Via FantasyPros) " + fp_data['update']
        return fp_data

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

    # Lancement des robots
    espn_data = scrape_espn(clean_name, player_info['espn_link'])
    cbs_data = scrape_cbs(clean_name, player_info['cbs_link'])
    
    # Chaîne NBC / News
    nbc_data = scrape_nbc_chain(clean_name)
    
    # Ajout des liens de redirection
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
