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
    # Lien d'équipe ESPN (utilisé uniquement pour le lien dans l'interface, pas pour le scraping)
    espn_url = f"https://www.espn.com/nba/team/injuries/_/name/{espn_abbr}"
    
    # CBS Mappings
    slug_cbs = f"{team_city}-{team_name}".lower().replace(' ', '-').replace('76ers', '76ers')
    cbs_url = f"https://www.cbssports.com/nba/teams/{team_abbr.upper()}/{slug_cbs}/injuries/"

    # NBC Mappings (CORRIGÉ : Ajout de /player-news pour le lien d'équipe)
    slug_nbc = f"{team_city}-{team_name}".lower().replace(' ', '-')
    nbc_url = f"https://www.nbcsports.com/nba/{slug_nbc}/player-news"

    return espn_url, cbs_url, nbc_url

# --- SCRAPERS ---

def scrape_espn(player_name):
    """
    Scrape la liste globale des blessures ESPN (méthode la plus stable).
    """
    try:
        target_url = "https://www.espn.com/nba/injuries"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(target_url, headers=headers, timeout=4)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            # Cherche tous les liens qui contiennent le nom du joueur
            for link in soup.find_all('a'):
                if player_name.lower() in link.text.lower():
                    row = link.find_parent('tr')
                    if row:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            # Concatène le texte de la colonne statut et de la colonne mise à jour
                            full_text = " ".join([c.text.strip() for c in cols[1:]])
                            status_short = "Listé"
                            lower_txt = full_text.lower()
                            
                            # Détermine le statut court
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
    """
    Scrape la liste globale des blessures CBS Sports (méthode la plus stable).
    """
    try:
        target_url = "https://www.cbssports.com/nba/injuries/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(target_url, headers=headers, timeout=4)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            # Cherche tous les liens qui contiennent le nom du joueur
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
    Stratégie ultra-ciblée pour NBC (Rotoworld) : 
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
            
            # Cibler les conteneurs de news spécifiques à Rotoworld (NBC Sports)
            # On cherche les blocs qui contiennent les news individuelles, souvent des divs ou des articles.
            # Classes Rotoworld courantes: PlayerNews-item, RotoworldPlayerNews, etc.
            news_containers = soup.find_all(['div', 'article'], class_=re.compile(r'NewsItem|PlayerNews-item|StoryLink|article', re.IGNORECASE))
            
            # Si on ne trouve rien de spécifique, on prend les balises principales de news
            if not news_containers:
                 news_containers = soup.find_all('div', class_=re.compile(r'col-|row|NewsCard', re.IGNORECASE))

            for container in news_containers:
                # 1. Chercher le titre (souvent dans un lien <a> ou un titre h)
                title_element = container.find(['a', 'h3', 'h4'], class_=re.compile(r'title|headline|PlayerNews-title', re.IGNORECASE))
                
                # S'assurer que le nom du joueur est dans le TITRE (ou l'élément principal)
                if title_element and player_name.lower() in title_element.get_text(" ", strip=True).lower():
                    
                    # 2. Extraire le corps de la news (souvent un paragraphe <p> sous le titre)
                    body_element = container.find('p', class_=re.compile(r'content|body|description', re.IGNORECASE)) or container.find('p')
                    
                    # Concaténer le titre et le corps
                    title_text = title_element.get_text(" ", strip=True)
                    full_text = title_text + " " + (body_element.get_text(" ", strip=True) if body_element else "")

                    # Vérification de sécurité : longueur minimale pour être une news pertinente
                    if len(full_text) > 50:
                        
                        status_short = "News"
                        lower_txt = full_text.lower()
                        
                        # Déterminer le statut à partir du corps de la news
                        if "out" in lower_txt and ("ruled" in lower_txt or "will not play" in lower_txt): status_short = "Out"
                        elif "available" in lower_txt: status_short = "Available"
                        elif "questionable" in lower_txt: status_short = "Questionable"
                        elif "day-to-day" in lower_txt: status_short = "Day-to-Day"
                        elif "probable" in lower_txt: status_short = "Probable"
                        
                        # Puisque c'est la première news pertinente (en théorie la plus récente)
                        return {
                            "status": status_short,
                            "update": full_text[:300].strip() + "...",
                            "timestamp": "Récent" 
                        }
                        
            # Fallback (si la structure n'est pas standard, on cherche n'importe quel texte pertinent)
            fallback_text = soup.find(string=re.compile(re.escape(player_name), re.IGNORECASE))
            if fallback_text:
                parent = fallback_text.find_parent('p') or fallback_text.find_parent('div')
                if parent and len(parent.get_text()) > 50:
                    return {
                        "status": "News",
                        "update": parent.get_text(" ", strip=True)[:300].strip() + "...",
                        "timestamp": "Récent (Fallback)"
                    }


        return None
    except Exception as e:
        print(f"Erreur NBC Team: {e}")
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

    # Scrape les sources stables et la nouvelle source NBC ciblée
    espn_data = scrape_espn(clean_name)
    cbs_data = scrape_cbs(clean_name)
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
