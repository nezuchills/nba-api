from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
import json
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
    espn_url = f"https://www.espn.com/nba/team/injuries/_/name/{espn_abbr}"
    
    # CBS
    slug = f"{team_city}-{team_name}".lower().replace(' ', '-').replace('76ers', '76ers')
    cbs_url = f"https://www.cbssports.com/nba/teams/{team_abbr.upper()}/{slug}/injuries/"

    # NBC (Lien générique pour redirection)
    nbc_url = "https://www.nbcsports.com/fantasy/basketball/player-news"

    return espn_url, cbs_url, nbc_url

# --- SCRAPING ---

def scrape_espn(player_name, team_url):
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

def scrape_nbc_fallback(player_name):
    """Fallback sur Rotowire (plus facile à scraper) si NBC échoue"""
    try:
        url = "https://www.rotowire.com/basketball/news.php"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            # Rotowire a une structure propre: div.news-update contenant le nom
            news_items = soup.find_all('div', class_='news-update')
            for item in news_items:
                # Chercher le nom du joueur
                player_link = item.find('a', class_='news-update__player-link')
                if player_link and player_name.lower() in player_link.text.lower():
                    # Trouver le texte de la news
                    news_text_div = item.find('div', class_='news-update__news')
                    if news_text_div:
                        full_text = news_text_div.text.strip()
                        
                        status_short = "News"
                        if "out" in full_text.lower(): status_short = "Out"
                        elif "questionable" in full_text.lower(): status_short = "Questionable"
                        
                        return {
                            "status": status_short,
                            "update": full_text[:250] + "...",
                            "timestamp": time.strftime("%H:%M")
                        }
    except: return None
    return None

def scrape_nbc(player_name, team_url):
    """Tentative NBC principale + Fallback"""
    try:
        target_url = "https://www.nbcsports.com/fantasy/basketball/player-news"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        response = requests.get(target_url, headers=headers, timeout=5)
        
        found_data = None
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Recherche textuelle large (plus robuste que les classes CSS qui changent)
            # On cherche le nom du joueur, et on regarde le texte autour
            page_text = soup.get_text(" ||| ", strip=True) # Séparateur unique
            
            # On cherche l'index du nom
            idx = page_text.lower().find(player_name.lower())
            if idx != -1:
                # On extrait une fenêtre de texte autour
                snippet = page_text[idx:idx+400]
                # Nettoyage sommaire
                snippet = snippet.replace("|||", " ").strip()
                
                found_data = {
                    "status": "News (NBC)",
                    "update": snippet[:200] + "...",
                    "timestamp": time.strftime("%H:%M")
                }

        if found_data:
            return found_data
        else:
            # Si NBC direct échoue, on tente le fallback
            return scrape_nbc_fallback(player_name)
            
    except Exception as e: 
        print(f"Erreur NBC: {e}")
        return scrape_nbc_fallback(player_name)

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
                espn_url, cbs_url, nbc_url = get_team_urls(row['TEAM_ABBREVIATION'], row['TEAM_CITY'], row['TEAM_NAME'])
                
                player_info = {
                    "team": f"{row['TEAM_CITY']} {row['TEAM_NAME']}",
                    "age": f"{calculate_age(row['BIRTHDATE'])} ans",
                    "espn_link": espn_url,
                    "cbs_link": cbs_url,
                    "nbc_link": nbc_url
                }
    except Exception as e: print(e)

    espn_data = scrape_espn(clean_name, player_info['espn_link'])
    cbs_data = scrape_cbs(clean_name, player_info['cbs_link'])
    nbc_data = scrape_nbc(clean_name, player_info['nbc_link'])
    
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
