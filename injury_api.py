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

# --- OUTILS DE GÉNÉRATION D'URLS ---

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
    
    # --- ESPN ---
    espn_abbr = abbr_lower
    # Mapping des codes spécifiques ESPN
    if abbr_lower == 'uta': espn_abbr = 'utah'
    if abbr_lower == 'nop': espn_abbr = 'no'
    if abbr_lower == 'gsw': espn_abbr = 'gs'
    if abbr_lower == 'sas': espn_abbr = 'sa'
    if abbr_lower == 'nyk': espn_abbr = 'ny'
    if abbr_lower == 'phx': espn_abbr = 'phx' # Parfois phx
    
    espn_url = f"https://www.espn.com/nba/team/injuries/_/name/{espn_abbr}"
    
    # --- CBS ---
    # Format: /teams/MIA/miami-heat/injuries/
    slug_cbs = f"{team_city}-{team_name}".lower().replace(' ', '-').replace('76ers', '76ers')
    cbs_url = f"https://www.cbssports.com/nba/teams/{team_abbr.upper()}/{slug_cbs}/injuries/"

    # --- NBC SPORTS (Stratégie Team News) ---
    # Format: https://www.nbcsports.com/fantasy/basketball/team-news/atlanta-hawks
    slug_nbc = f"{team_city}-{team_name}".lower().replace(' ', '-')
    nbc_url = f"https://www.nbcsports.com/fantasy/basketball/team-news/{slug_nbc}"

    return espn_url, cbs_url, nbc_url

# --- SCRAPING ---

def scrape_espn(player_name, team_url):
    try:
        # On va chercher la page spécifique de l'équipe si possible, sinon fallback général
        target_url = team_url if team_url else "https://www.espn.com/nba/injuries"
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(target_url, headers=headers, timeout=4)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            # Recherche du lien du joueur
            for link in soup.find_all('a'):
                if player_name.lower() in link.text.lower():
                    row = link.find_parent('tr')
                    if row:
                        cols = row.find_all('td')
                        # Sur la page équipe, la structure peut varier légèrement mais souvent:
                        # NOM | POS | STATUS | COMMENTAIRE
                        # On prend tout le texte de la ligne
                        full_text = row.get_text(" ", strip=True)
                        
                        # Extraction statut sommaire
                        status_short = "Listé"
                        lower_txt = full_text.lower()
                        
                        if "out" in lower_txt: status_short = "Out"
                        elif "day-to-day" in lower_txt: status_short = "Day-to-Day"
                        elif "questionable" in lower_txt: status_short = "Questionable"
                        elif "doubtful" in lower_txt: status_short = "Doubtful"
                        elif "probable" in lower_txt: status_short = "Probable"
                        
                        # Nettoyage du nom du joueur dans le texte pour ne garder que l'info
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
                        if len(cols) >= 3: # CBS team page a moins de colonnes parfois
                            # On prend le texte des dernières cellules
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

def scrape_nbc_team_page(player_name, team_url):
    """
    Nouvelle stratégie : Scraper la page News de l'ÉQUIPE.
    C'est beaucoup plus fiable que le flux global.
    """
    try:
        if not team_url: return None
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        response = requests.get(team_url, headers=headers, timeout=6)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Sur la page équipe NBC, les news sont listées par joueur.
            # On cherche le bloc qui contient le nom du joueur.
            # Souvent dans des balises <div> avec des classes comme 'PlayerNews-item' ou générique.
            
            # Recherche textuelle ciblée
            # On découpe la page en blocs de texte et on cherche le nom
            
            # 1. Chercher tous les liens ou titres de joueurs
            candidates = soup.find_all(['div', 'a', 'h3'], string=lambda t: t and player_name.lower() in t.lower())
            
            for candidate in candidates:
                # Une fois le nom trouvé, on cherche le paragraphe de texte suivant ou parent
                # Remontons au parent conteneur (souvent un wrapper de news)
                container = candidate.find_parent('div')
                if container:
                    text = container.get_text(" ", strip=True)
                    
                    # Vérification de sécurité : le texte doit être assez long pour être une news
                    if len(text) > 50:
                        # Extraction du statut
                        status_short = "News"
                        lower_txt = text.lower()
                        if "out" in lower_txt: status_short = "Out"
                        elif "questionable" in lower_txt: status_short = "Questionable"
                        elif "day-to-day" in lower_txt: status_short = "Day-to-Day"
                        elif "probable" in lower_txt: status_short = "Probable"
                        
                        # On nettoie un peu (on enlève le nom pour éviter la répétition)
                        update_text = text.replace(player_name, "").strip()
                        
                        # Si on trouve une date relative (ex: "Nov 20"), c'est bon signe
                        
                        return {
                            "status": status_short,
                            "update": update_text[:300] + "...", # On coupe si trop long
                            "timestamp": time.strftime("%H:%M")
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
        # 1. Récupération Metadata
        found_players = players.find_players_by_full_name(clean_name)
        if found_players:
            pid = found_players[0]['id']
            info = commonplayerinfo.CommonPlayerInfo(player_id=pid).get_data_frames()[0]
            if not info.empty:
                row = info.iloc[0]
                # Génération des liens spécifiques à l'équipe
                espn, cbs, nbc = get_team_urls(row['TEAM_ABBREVIATION'], row['TEAM_CITY'], row['TEAM_NAME'])
                player_info = {
                    "team": f"{row['TEAM_CITY']} {row['TEAM_NAME']}",
                    "age": f"{calculate_age(row['BIRTHDATE'])} ans",
                    "espn_link": espn,
                    "cbs_link": cbs,
                    "nbc_link": nbc
                }
    except: pass

    # 2. Scraping Ciblé (Team Pages)
    # On passe le lien d'équipe généré pour cibler la recherche
    espn_data = scrape_espn(clean_name, player_info.get('espn_link'))
    cbs_data = scrape_cbs(clean_name, player_info.get('cbs_link'))
    nbc_data = scrape_nbc_team_page(clean_name, player_info.get('nbc_link'))
    
    # 3. Ajout des URLs de redirection pour le frontend
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
