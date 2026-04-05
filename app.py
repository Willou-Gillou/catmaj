import streamlit as st
import os
st.set_page_config(page_title="Sorites FR 2.04", page_icon="logo.jpeg")
import requests
from bs4 import BeautifulSoup
import re
import json
import time
from urllib.parse import quote


# ── Configuration persistante via localStorage ────────────────────────────
from streamlit_local_storage import LocalStorage
localS = LocalStorage()

_CFG_DEFAULTS = {
    "tmdb_api_key": "",
    "metas_films_pastebin": "",
    "megas_series_pastebin": "",
}

def get_config(key: str) -> str:
    # Lecture pure en RAM (instantané), le LocalStorage n'est interrogé qu'une fois dans la sidebar
    return st.session_state.get(f"cfg_{key}", _CFG_DEFAULTS.get(key, ""))


def render_config_sidebar():
    """Panneau ⚙️ Configuration dans la sidebar — persiste dans localStorage."""
    with st.sidebar:
        st.markdown("---")
        cfg_ok = bool(get_config("tmdb_api_key"))
        with st.expander("⚙️ Configuration", expanded=not cfg_ok):
            st.caption("Paramètres sauvegardés dans le cache local de votre navigateur.")
            fields = [
                ("tmdb_api_key", "🔑 TMDB API Key", "password", "Clé API TMDb — https://www.themoviedb.org/settings/api"),
                ("metas_films_pastebin", "🎬 Pastebin Films (URL raw)", "default", "URL raw Pastebin pour les métas films"),
                ("megas_series_pastebin", "📺 Pastebin Séries (URL raw)","default", "URL raw Pastebin pour les mégas séries"),
            ]
            # Synchronisation initiale depuis le Local Storage
            if "ls_synced" not in st.session_state:
                synced_all = True
                for key in _CFG_DEFAULTS:
                    val = localS.getItem(key)
                    if val is not None:
                        st.session_state[f"cfg_{key}"] = val
                    else:
                        synced_all = False
                if synced_all:
                    st.session_state["ls_synced"] = True

            for key, label, input_type, help_txt in fields:
                session_key = f"cfg_{key}"
                widget_key = f"widget_{key}"

                current_val = get_config(key)

                new_val = st.text_input(
                    label,
                    value=current_val if current_val is not None else "",
                    key=widget_key,
                    type=input_type,
                    help=help_txt,
                )

                if new_val != current_val and new_val is not None:
                    st.session_state[session_key] = new_val
                    localS.setItem(key, new_val)
                    st.rerun()

            if not get_config("tmdb_api_key"):
                st.warning("⚠️ TMDB API Key non renseignée.")
            else:
                st.success("✅ Configuration OK")

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/w92"
BASE_IMDB_SEARCH = "https://www.imdb.com/fr/find/?q="
BASE_JW_SEARCH = "https://www.justwatch.com/fr/recherche?q="
BASE_JW_IMAGE = "https://images.justwatch.com"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# ── TMDb helpers ────────────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def tmdb_search_top3(titre):
    """Recherche TMDb par titre, retourne les 3 premiers résultats avec imdb_id."""
    try:
        r = requests.get(
            f"{TMDB_BASE}/search/movie",
            params={"query": titre, "api_key": get_config("tmdb_api_key"), "language": "fr-FR"},
            timeout=10
        )
        data = r.json()
        items = data.get("results", [])[:3]
        results = []
        for item in items:
            tmdb_id = item.get("id")
            # Récupère imdb_id via external_ids
            imdb_id = ""
            try:
                ext = requests.get(
                    f"{TMDB_BASE}/movie/{tmdb_id}/external_ids",
                    params={"api_key": get_config("tmdb_api_key")},
                    timeout=8
                ).json()
                raw_id = ext.get("imdb_id", "") or ""
                imdb_id = raw_id if raw_id.startswith("tt") else f"tt{raw_id}" if raw_id else ""
            except Exception:
                pass
            poster_path = item.get("poster_path")
            results.append({
                "id": imdb_id,
                "tmdb_id": tmdb_id,
                "title": item.get("title", ""),
                "year": (item.get("release_date") or "")[:4],
                "img": f"{TMDB_IMG_BASE}{poster_path}" if poster_path else None,
            })
            time.sleep(0.1)
        return results
    except Exception:
        return []

@st.cache_data(ttl=86400, show_spinner=False)
def tmdb_get_title(imdb_id):
    """Récupère le titre depuis TMDb via imdbID."""
    try:
        clean_id = imdb_id if imdb_id.startswith("tt") else f"tt{imdb_id}"
        r = requests.get(
            f"{TMDB_BASE}/find/{clean_id}",
            params={"api_key": get_config("tmdb_api_key"), "external_source": "imdb_id", "language": "fr-FR"},
            timeout=8
        )
        data = r.json()
        results = data.get("movie_results", [])
        if results:
            return results[0].get("title", "")
        return ""
    except Exception:
        return ""

@st.cache_data(ttl=86400, show_spinner=False)
def tmdb_get_rating_by_imdb_id(imdb_id):
    try:
        clean_id = imdb_id if imdb_id.startswith('tt') else f'tt{imdb_id}'
        r = requests.get(
            f"{TMDB_BASE}/find/{clean_id}",
            params={"api_key": get_config("tmdb_api_key"), "external_source": "imdb_id", "language": "fr-FR"},
            timeout=8,
        )
        data = r.json()
        movie_results = data.get('movie_results', [])
        tv_results = data.get('tv_results', [])
        if movie_results:
            return movie_results[0].get('vote_average') or movie_results[0].get('rating') or ''
        if tv_results:
            return tv_results[0].get('vote_average') or tv_results[0].get('rating') or ''
    except Exception:
        pass
    return ''



# ── JustWatch ────────────────────────────────────────────────────────────────

def normalise_titre_plein(titre_plein):
    if not titre_plein or isinstance(titre_plein, (int, float)):
        return str(titre_plein)
    titre = str(titre_plein).strip()
    titre = re.sub(r', ', ' ', titre).strip()
    pattern = r'^(.?),?(Le|La|Les|L\'|Un|Une) (.+)$'
    match = re.match(pattern, titre, re.IGNORECASE)
    if match:
        debut, particule, fin = match.groups()
        return f"{particule.title()} {debut.strip()} {fin.strip()}"
    return titre


def normalise_titre_recherche(titre_brut: str) -> str:
    """
    Nettoie un titre pour la recherche TMDb :
    1. Retire les parenthèses et leur contenu  → "Elio (2025)" → "Elio"
    2. En cas de virgule, retire la virgule et tout ce qui suit → "Titre, Le" → "Titre"
    """
    titre = str(titre_brut).strip()
    # Retire (xxxx) et tout contenu entre parenthèses
    titre = re.sub(r'\s*\(.*?\)', '', titre).strip()
    # Retire la virgule et tout ce qui suit
    if ',' in titre:
        titre = titre[:titre.index(',')].strip()
    return titre

def normalize_jw_poster_url(raw_url):
    if not raw_url:
        return None
    m = re.search(r'/poster/(\d+)/', raw_url)
    if m:
        return f"{BASE_JW_IMAGE}/poster/{m.group(1)}/s332/img"
    return None

@st.cache_data(ttl=86400, show_spinner=False)
def scraper_justwatch_top3(titre_plein):
    titre_normalise = normalise_titre_plein(titre_plein)
    url = f"{BASE_JW_SEARCH}{quote(titre_normalise)}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        rows = soup.select('div.title-list-row__row')[:3]
        results = []
        for row in rows:
            title_el = row.select_one('span.header-title')
            year_el  = row.select_one('span.header-year')
            title = title_el.get_text(strip=True) if title_el else ""
            year  = year_el.get_text(strip=True) if year_el else ""
            img_src = None
            for s in row.select('picture.picture-comp.title-poster__image source'):
                if 'jpeg' in s.get('type', ''):
                    srcset = s.get('srcset', '')
                    img_src = srcset.split(',')[0].strip().split(' ')[0]
                    break
            if not img_src:
                img_el = row.select_one('picture.picture-comp.title-poster__image img')
                if img_el:
                    img_src = img_el.get('src')
            poster_url = normalize_jw_poster_url(img_src) if img_src else None
            if title:
                results.append({"title": title, "year": year, "poster": poster_url, "img": img_src})
        return results
    except Exception:
        return []

def scraper_justwatch_poster(titre_plein):
    top3 = scraper_justwatch_top3(titre_plein)
    return top3[0]["poster"] if top3 else None

# ── Session search helpers ───────────────────────────────────────────────────

def reset_search():
    for key in ["imdb_id", "poster_url", "film_nom", "imdb_page_title", "imdb_search_error", "imdb_top3", "jw_top3"]:
        if key in st.session_state:
            del st.session_state[key]

def do_search(film_nom):
    with st.spinner("Recherche TMDb et poster..."):
        film_nom_recherche = normalise_titre_recherche(film_nom)
        top3 = tmdb_search_top3(film_nom_recherche)
        imdb_id = top3[0]["id"] if top3 else None
        st.session_state.imdb_top3 = top3
        top3_jw = scraper_justwatch_top3(film_nom_recherche)
        st.session_state.jw_top3 = top3_jw
        if imdb_id:
            title = tmdb_get_title(imdb_id) or film_nom_recherche
            st.session_state.imdb_page_title = title
            st.session_state.imdb_id = imdb_id
            st.session_state.poster_url = top3_jw[0]["poster"] if top3_jw else None
            st.session_state.film_nom = title
        else:
            st.session_state.imdb_search_error = True

# ── Render helpers ───────────────────────────────────────────────────────────

def render_top3_selector(top3, chosen_key, radio_key):
    if not top3:
        return
    st.markdown("<p style='color:#94a3b8; font-size:0.85rem; margin:0.3rem 0 0.4rem 0;'>🔎 Sélectionner le bon résultat IMDb :</p>", unsafe_allow_html=True)
    img_cols = st.columns(len(top3))
    for j, r in enumerate(top3):
        with img_cols[j]:
            if r["img"]:
                st.image(r["img"], width=70)
            st.caption(f"`{r['id']}`")
    radio_labels = [f"{r['title']} ({r['year']})" if r['year'] else r['title'] for r in top3]
    current_chosen = st.session_state.get(chosen_key, top3[0]["id"])
    default_idx = next((j for j, r in enumerate(top3) if r["id"] == current_chosen), 0)
    chosen = st.radio("##imdb", radio_labels, index=default_idx, key=radio_key,
                      horizontal=False, label_visibility="collapsed")
    st.session_state[chosen_key] = top3[radio_labels.index(chosen)]["id"]

def render_jw_top3_selector(top3_jw, jw_chosen_key, jw_radio_key):
    if not top3_jw:
        return
    st.markdown("<p style='color:#94a3b8; font-size:0.8rem; margin:0 0 0.3rem 0;'>🔎 Sélectionner le bon résultat :</p>", unsafe_allow_html=True)
    jw_img_cols = st.columns(len(top3_jw))
    for j, r in enumerate(top3_jw):
        with jw_img_cols[j]:
            if r["img"]:
                st.image(r["img"], width=60)
            st.caption(r["year"] or "")
    jw_labels = [f"{r['title']} ({r['year']})" if r['year'] else r['title'] for r in top3_jw]
    current_jw = st.session_state.get(jw_chosen_key, "")
    jw_default = next((j for j, r in enumerate(top3_jw) if r["poster"] == current_jw), 0)
    chosen = st.radio("##jw", jw_labels, index=jw_default, key=jw_radio_key,
                      horizontal=False, label_visibility="collapsed")
    st.session_state[jw_chosen_key] = top3_jw[jw_labels.index(chosen)]["poster"] or ""

@st.fragment
def render_result_card(i, res, frun, prefix="ffr"):
    icon          = "✅" if res["id"] else "⚠️"
    name_original = res.get("name_original", "")
    display_name  = (
        f"{res['name']}  _(original : {name_original})_"
        if name_original and name_original != res["name"]
        else res["name"]
    )

    with st.expander(f"{icon} {display_name}"):
        name_key      = f"{prefix}_name_{frun}_{i}"
        id_key        = f"{prefix}_id_{frun}_{i}"
        poster_key    = f"{prefix}_poster_{frun}_{i}"
        radio_key     = f"{prefix}_top3_radio_{frun}_{i}"
        chosen_key    = f"{prefix}_chosen_id_{frun}_{i}"
        jw_radio_key  = f"{prefix}_jw_radio_{frun}_{i}"
        jw_chosen_key = f"{prefix}_jw_chosen_{frun}_{i}"

        if name_key not in st.session_state:
            st.session_state[name_key] = name_original or res["name"]
        if chosen_key not in st.session_state:
            st.session_state[chosen_key] = res.get("_chosen_id") or res["id"] or ""
        if id_key not in st.session_state:
            st.session_state[id_key] = res.get("_chosen_id") or res["id"] or ""
        if jw_chosen_key not in st.session_state:
            st.session_state[jw_chosen_key] = res.get("_jw_chosen") or res.get("poster") or ""

        # Titre original / reformaté
        if name_original and name_original != res["name"]:
            col_orig, col_fmt = st.columns(2)
            with col_orig:
                st.markdown("**Titre original**")
                st.info(name_original)
            with col_fmt:
                st.markdown("**Titre reformaté (recherche)**")
                st.success(res["name"])

        st.text_input("Nom du film", key=name_key)

        # IMDb
        top3 = res.get("top3", [])
        col_radio, col_verify = st.columns([2, 1.5])

        with col_radio:
            if top3:
                st.markdown(
                    "<p style='color:#94a3b8;font-size:0.82rem;margin:0 0 0.3rem 0;'>"
                    "🔎 Sélectionner le bon résultat IMDb :</p>",
                    unsafe_allow_html=True
                )
                img_cols = st.columns(len(top3))
                for j, r in enumerate(top3):
                    with img_cols[j]:
                        if r["img"]:
                            st.image(r["img"], width=70)
                        st.caption(f"`{r['id']}`")
                radio_labels   = [f"{r['title']} ({r['year']})" if r["year"] else r["title"] for r in top3]
                current_chosen = st.session_state.get(chosen_key, top3[0]["id"])
                default_idx    = next((j for j, r in enumerate(top3) if r["id"] == current_chosen), 0)
                chosen_label   = st.radio(
                    "##imdb", radio_labels, index=default_idx,
                    key=radio_key, horizontal=False, label_visibility="collapsed"
                )
                selected_id = top3[radio_labels.index(chosen_label)]["id"]
                if st.session_state.get(chosen_key) != selected_id:
                    st.session_state[chosen_key] = selected_id
                    st.session_state[id_key]     = selected_id

            edited_id = st.text_input(
                "ID IMDb (modifiable)", key=id_key,
                help="Modifiable manuellement. Le préfixe tt sera ajouté automatiquement."
            )
            if edited_id and not edited_id.startswith("tt"):
                st.session_state[id_key] = f"tt{edited_id}"

        effective_id = st.session_state.get(id_key) or ""

        with col_verify:
            st.markdown(
                "<p style='color:#94a3b8;font-size:0.85rem;margin:0 0 0.4rem 0;'>"
                "🎬 Vérification poster IMDb</p>",
                unsafe_allow_html=True
            )
            if effective_id:
                st.image(f"https://live.metahub.space/poster/small/{effective_id}/img", width=150)
                st.markdown(
                    f'<a href="https://www.imdb.com/fr/title/{effective_id}/" target="_blank">🔍 IMDb page</a>',
                    unsafe_allow_html=True
                )
            else:
                nom_val = st.session_state.get(name_key) or res["name"]
                st.markdown(
                    f'<a href="https://www.imdb.com/fr/find/?q={quote(nom_val)}" target="_blank">🔍 Rechercher sur IMDb</a>',
                    unsafe_allow_html=True
                )
                st.info("Saisissez un ID IMDb ci-dessus pour activer le poster.")

        st.markdown("<hr style='border-color:#2d2d5e;margin:0.8rem 0;'>", unsafe_allow_html=True)

        # JustWatch
        top3_jw = res.get("top3_jw", [])
        col_jw_radio, col_jw_img = st.columns([2, 1.5])
        with col_jw_radio:
            st.markdown(
                "<p style='color:#94a3b8;font-size:0.85rem;margin:0 0 0.3rem 0;'>🎬 JustWatch</p>",
                unsafe_allow_html=True
            )
            render_jw_top3_selector(top3_jw, jw_chosen_key, jw_radio_key)

        effective_poster = st.session_state.get(jw_chosen_key) or ""
        if poster_key not in st.session_state or st.session_state[poster_key] != effective_poster:
            st.session_state[poster_key] = effective_poster

        with col_jw_img:
            st.markdown(
                "<p style='color:#94a3b8;font-size:0.85rem;margin:0 0 0.4rem 0;'>Poster JustWatch</p>",
                unsafe_allow_html=True
            )
            if effective_poster:
                st.image(effective_poster, width=120)
            else:
                st.info("Pas de poster")
            nom_val = st.session_state.get(name_key) or res["name"]
            jw_url  = f"{BASE_JW_SEARCH}{quote(normalise_titre_plein(nom_val))}"
            st.markdown(
                f'<a href="{jw_url}" target="_blank">🔍 JustWatch recherche</a>',
                unsafe_allow_html=True
            )
        st.text_input("URL Poster JustWatch", key=poster_key)

        st.markdown("<hr style='border-color:#2d2d5e;margin:0.8rem 0;'>", unsafe_allow_html=True)

        # Preview meta
        imdb_id_val  = st.session_state.get(id_key) or ""
        poster_val   = st.session_state.get(poster_key) or ""
        meta_preview = {
            "id":     imdb_id_val,
            "name":   st.session_state.get(name_key) or (name_original or res["name"]),
            "poster": poster_val or (f"https://live.metahub.space/poster/small/{imdb_id_val}/img" if imdb_id_val else "")
        }
        st.code(json.dumps(meta_preview, indent=2, ensure_ascii=False) + ",", language="json")

        compile_key = f"{prefix}_compile_{frun}_{i}"
        delete_key  = f"{prefix}_delete_{frun}_{i}"
        col_compile, col_delete = st.columns(2)

        with col_compile:
            if st.button("📋 Compiler ce meta", key=compile_key, width="stretch"):
                ids_existants = [m["id"] for m in st.session_state.compiled_metas]
                if meta_preview["id"] not in ids_existants:
                    st.session_state.compiled_metas.append(meta_preview)
                st.rerun()

        with col_delete:
            if st.button("🗑️ Supprimer", key=delete_key, width="stretch"):
                results_key  = "v2_results" if prefix == "v2" else "ffr_results"
                results_list = st.session_state[results_key]
                n, run       = len(results_list), frun
                for j in range(i + 1, n):
                    res_j   = results_list[j]
                    mapping = {
                        "name_original": f"{prefix}_name_{run}_{j}",
                        "id":            f"{prefix}_id_{run}_{j}",
                        "poster":        f"{prefix}_poster_{run}_{j}",
                        "_chosen_id":    f"{prefix}_chosen_id_{run}_{j}",
                        "_jw_chosen":    f"{prefix}_jw_chosen_{run}_{j}",
                    }
                    for field, k in mapping.items():
                        if k in st.session_state:
                            res_j[field] = st.session_state[k]
                for j in range(n):
                    for sk in ["name", "id", "poster", "chosen_id", "jw_chosen", "top3_radio", "jw_radio"]:
                        k = f"{prefix}_{sk}_{run}_{j}"
                        if k in st.session_state:
                            del st.session_state[k]
                results_list.pop(i)
                st.rerun()

        st.markdown("""
        <style>
        div[data-testid="stColumns"] > div:nth-child(2) > div[data-testid="stButton"]:has(button[kind="secondary"]) button {
            background: linear-gradient(135deg, #dc2626, #b91c1c) !important;
            color: white !important;
        }
        </style>
        """, unsafe_allow_html=True)


def render_compiled_metas(vider_key):
    if st.session_state.compiled_metas:
        st.markdown("""
        <div style='border-left: 4px solid #e94560; padding: 0.4rem 1rem; margin: 1rem 0 0.5rem 0;'>
            <span style='color:#e94560; font-weight:700; font-size:1.05rem;'>📋 Metas compilés</span>
        </div>
        """, unsafe_allow_html=True)
        compiled_str = ",\n".join(json.dumps(m, indent=2, ensure_ascii=False) for m in st.session_state.compiled_metas) + ","
        st.code(compiled_str, language="json")
        if st.button("🗑️ Vider la compilation", key=vider_key):
            st.session_state.compiled_metas = []
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════
# FONCTIONS FILMFR
# ══════════════════════════════════════════════════════════════════════════

def normalize_title_for_comparison(title):
    normalized = title.casefold()
    for a, b in [('é','e'),('è','e'),('ê','e'),('à','a'),('â','a'),('ä','a'),
                 ('ù','u'),('û','u'),('ü','u'),('î','i'),('ï','i'),('ô','o'),('ö','o'),('ç','c')]:
        normalized = normalized.replace(a, b)
    normalized = re.sub(r'[–—\\-\\.,!?:;]', ' ', normalized)
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip()

def load_pastebin_robust(url):
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return set()
        raw = response.text.strip()
        try:
            data = json.loads(raw)
            items = [data] if isinstance(data, dict) else data
        except json.JSONDecodeError:
            items = []
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith('{') and line.endswith('}'):
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        result = set()
        for item in items:
            if "name" in item:
                result.add(normalize_title_for_comparison(item["name"]))
        return result
    except Exception:
        return set()

def clean_title_filmfr(title):
    if not title or not title.strip():
        return title
    result = re.sub(r"(L\'|D\'|l\'|d\')\s+", r"\1", title)
    year_match = re.search(r'\s*(\d{4})\s*$', result)
    if year_match:
        year = f" ({year_match.group(1)})"
        result = re.sub(r'\s*\d{4}\s*$', '', result).strip() + year
    return result.strip() or title.strip()

def is_serie(title, div):
    if any(mot in title.lower() for mot in ["saison", "série", "tv", "t.v.", "episode"]):
        return True
    parent = div.parent
    while parent and parent != parent.parent:
        classes = " ".join(parent.get("class", []))
        if any(cat in classes for cat in ["serie", "tv", "series", "television"]):
            return True
        parent = parent.parent
    return False

def get_nouveautes_menu():
    try:
        response = requests.get("https://www.filmfr.com", headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        items = []
        base_url = "https://www.filmfr.com"
        menu_links = soup.find_all("a", string=re.compile(r"(Nouveautés|Série|Séries)", re.I))
        for link in menu_links:
            li_parent = link.find_parent("li")
            submenu = li_parent.find_next_sibling("ul") or li_parent.find("ul") if li_parent else None
            if submenu:
                for a in submenu.find_all("a", href=True):
                    text = a.get_text(strip=True)
                    href = a.get("href")
                    if text and href:
                        items.append({"text": text, "url": href if href.startswith("http") else base_url + href})
            else:
                text = link.get_text(strip=True)
                href = link.get("href")
                if text and href:
                    items.append({"text": text, "url": href if href.startswith("http") else base_url + href})
        seen = set()
        unique = []
        for item in items:
            if item['url'] not in seen:
                seen.add(item['url'])
                unique.append(item)
        return unique[:10]
    except Exception:
        return []

def get_contenus_from_page(url, existing_films, existing_series):
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        product_divs = soup.find_all("div", class_="product-content")
        if not product_divs:
            product_divs = soup.find_all("div", class_=re.compile(r"product"))
        films_nouveaux, films_existants, series_nouveaux, series_existants = [], [], [], []
        for div in product_divs[:50]:
            title_elem = (div.find("h3") or div.find("h2") or div.find("h4") or
                          div.find("div", class_=re.compile(r"title")))
            if title_elem:
                a = title_elem.find("a") or title_elem
                raw_title = a.get_text(strip=True) if a.name == 'a' else title_elem.get_text(strip=True)
                if raw_title and len(raw_title) > 2:
                    clean = clean_title_filmfr(raw_title)
                    norm = normalize_title_for_comparison(clean)
                    if is_serie(clean, div):
                        (series_existants if norm in existing_series else series_nouveaux).append(clean)
                    else:
                        (films_existants if norm in existing_films else films_nouveaux).append(clean)
        return films_nouveaux, films_existants, series_nouveaux, series_existants
    except Exception:
        return [], [], [], []

def clean_title_for_search(titre):
    """Nettoie le préfixe FILM/SÉRIE puis applique normalise_titre_recherche."""
    titre = re.sub(r'^(?:FILM|SÉRIE)\s*', '', titre).strip()
    return normalise_titre_recherche(titre)

# ══════════════════════════════════════════════════════════════════════════
# INITIALISATION SESSION STATE
# ══════════════════════════════════════════════════════════════════════════

defaults = {
    "search_run_count": 0, "imdb_id": "", "poster_url": "",
    "last_searched_nom": "", "compiled_metas": [], "imdb_top3": [], "jw_top3": [],
    "ffr_menu_items": None, "ffr_films_nouveaux": [], "ffr_films_existants": [],
    "ffr_series_nouveaux": [], "ffr_series_existants": [],
    "ffr_selected_films": [], "ffr_selected_series": [],
    "ffr_results": [], "ffr_run_count": 0,
    "v2_results": [], "v2_run_count": 0,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f0f23 0%, #1a1a3e 100%);
    border-right: 1px solid #2d2d5e;
}
[data-testid="stSidebar"] * { color: #e0e0ff !important; }
[data-testid="stSidebar"] .stRadio label {
    background: rgba(255,255,255,0.05);
    border-radius: 8px;
    padding: 0.4rem 0.8rem;
    margin: 2px 0;
    transition: background 0.2s;
}
[data-testid="stSidebar"] .stRadio label:hover { background: rgba(99,102,241,0.3); }

h1 { color: #818cf8 !important; font-weight: 700 !important; }
h2, h3 { color: #a5b4fc !important; font-weight: 600 !important; }

.stButton > button {
    background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: opacity 0.2s !important;
    height: 2.75rem !important;
    margin-top: 0 !important;
}
.stButton > button:hover { opacity: 0.85 !important; }

[data-testid="stHorizontalBlock"] > div:nth-child(2) .stButton > button {
    background: linear-gradient(135deg, #dc2626, #b91c1c) !important;
}

[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
    border-radius: 8px !important;
    border: 1px solid #3d3d7e !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 2px rgba(99,102,241,0.3) !important;
}

[data-testid="stExpander"] {
    border: 1px solid #2d2d5e !important;
    border-radius: 10px !important;
    margin-bottom: 0.5rem !important;
}
[data-testid="stExpander"] summary { font-weight: 600 !important; color: #c7d2fe !important; }

[data-testid="stImage"] { display: flex; justify-content: center; }

a { color: #818cf8 !important; text-decoration: none !important; }
a:hover { color: #c7d2fe !important; text-decoration: underline !important; }

[data-testid="stTextInput"] label,
[data-testid="stTextArea"] label,
[data-testid="stSelectbox"] label { color: #94a3b8 !important; font-size: 0.85rem !important; }

div[data-testid="stCodeBlock"] pre {
    background: #0d0d1f !important;
    border: 1px solid #2d2d5e !important;
    border-radius: 8px !important;
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION
# ══════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.image("logo.jpeg", width="stretch")
    page = st.radio(
        "Navigation",
        ["Ajout manuel multiple", "Ajout depuis FilmFR", "Ajout du rating"],
        label_visibility="collapsed"
    )

render_config_sidebar()

# ══════════════════════════════════════════════════════════════════════════
# PAGE : Ajout manuel multiple
# ══════════════════════════════════════════════════════════════════════════

if page == "Ajout manuel multiple":
    st.markdown("<h1>✏️ Générateur de métas - Ajout manuel multiple</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color:#94a3b8; margin-top:-0.5rem; margin-bottom:1.5rem;'>Recherche en batch — un titre par ligne</p>", unsafe_allow_html=True)

    v2run = st.session_state.v2_run_count
    titres_input = st.text_area("🎬 Titres à rechercher (un par ligne)", height=120, key=f"v2_input_{v2run}")

    col_go, col_pb, _ = st.columns([2, 1.5, 5])
    with col_go:
        lancer_v2 = st.button("🚀 Lancer la recherche", disabled=not titres_input.strip())
    with col_pb:
        st.link_button("📎 Pastebin", "https://pastebin.com")

    if lancer_v2:
        titres_list = [t.strip() for t in titres_input.strip().splitlines() if t.strip()]
        st.session_state.v2_run_count += 1
        st.session_state.v2_results = []
        results = []
        progress = st.progress(0)
        status = st.empty()
        for i, titre in enumerate(titres_list):
            titre_recherche = normalise_titre_recherche(titre)
            status.text(f"⏳ Traitement {i+1}/{len(titres_list)} : {titre_recherche}")
            top3 = tmdb_search_top3(titre_recherche)
            imdb_id = top3[0]["id"] if top3 else None
            time.sleep(0.2)
            top3_jw = scraper_justwatch_top3(titre_recherche)
            poster_url = top3_jw[0]["poster"] if top3_jw else None
            time.sleep(0.3)
            imdb_title = titre_recherche
            if imdb_id:
                imdb_title = tmdb_get_title(imdb_id) or titre_recherche
                time.sleep(0.1)
            results.append({
                "id": imdb_id,
                "name_original": titre,
                "name": titre_recherche,
                "imdb_title": imdb_title,
                "poster": poster_url or (f"https://live.metahub.space/poster/small/{imdb_id}/img" if imdb_id else None),
                "top3": top3, "top3_jw": top3_jw
            })
            progress.progress((i + 1) / len(titres_list))
        st.session_state.v2_results = results
        status.empty()
        st.rerun()

    if st.session_state.v2_results:
        v2run = st.session_state.v2_run_count
        ok = [r for r in st.session_state.v2_results if r["id"]]
        ko = [r for r in st.session_state.v2_results if not r["id"]]
        st.markdown("---")
        if ko:
            st.warning(f"⚠️ {len(ko)} contenu(s) sans IMDb ID — à compléter manuellement.")
        if ok:
            st.success(f"✅ {len(ok)} contenu(s) trouvés automatiquement.")
        for i, res in enumerate(st.session_state.v2_results):
            render_result_card(i, res, v2run, prefix="v2")

        st.markdown("---")
        col_all, _ = st.columns([2, 5])
        with col_all:
            if st.button("📋 Compiler tous les metas valides", key="v2_compile_all"):
                ids_existants = [m["id"] for m in st.session_state.compiled_metas]
                for res in ok:
                    if res["id"] not in ids_existants:
                        st.session_state.compiled_metas.append({
                            "id": res["id"],
                            "name": res.get("name_original") or res["name"],
                            "poster": res["poster"] or f"https://live.metahub.space/poster/small/{res['id']}/img"
                        })
                st.rerun()
        render_compiled_metas("vider_v2")


# ══════════════════════════════════════════════════════════════════════════
# PAGE : Ajout du rating
# ══════════════════════════════════════════════════════════════════════════
elif page == "Ajout du rating":
    st.markdown("<h1>⭐ Ajout du rating</h1>", unsafe_allow_html=True)
    source = st.radio("Source", ["Pastebin Films", "Pastebin Séries"], horizontal=True)
    pastebin_url = get_config("metas_films_pastebin") if source == "Pastebin Films" else get_config("megas_series_pastebin")
    if not pastebin_url:
        st.error("Pastebin manquant dans la configuration.")
    else:
        if st.button("🔄 Charger et enrichir"):
            with st.spinner("Lecture du JSON et ajout des ratings..."):
                resp = requests.get(pastebin_url, timeout=20)
                resp.raise_for_status()
                raw = resp.text.strip()
                data = json.loads(raw)
                if isinstance(data, dict):
                    items = data.get("metas", data.get("items", []))
                    container_key = "metas" if "metas" in data else "items" if "items" in data else None
                else:
                    items = data
                    container_key = None
                total = len(items) if isinstance(items, list) else 0
                progress = st.progress(0)
                enriched = []
                for i, item in enumerate(items):
                    imdb_id = item.get("imdb_id") or item.get("id") or ""
                    rating = tmdb_get_rating_by_imdb_id(imdb_id) if imdb_id else ""
                    new_item = dict(item)
                    new_item["rating"] = rating
                    enriched.append(new_item)
                    if total:
                        progress.progress((i + 1) / total)
                if container_key:
                    data[container_key] = enriched
                    output = json.dumps(data, ensure_ascii=False, indent=2)
                else:
                    output = json.dumps(enriched, ensure_ascii=False, indent=2)
                st.success(f"{len(enriched)} meta(s) enrichi(s).")
                st.download_button(
                    "⬇️ Télécharger le JSON enrichi",
                    data=output.encode("utf-8"),
                    file_name=f"rating_{source.lower().replace(' ', '_')}.json",
                    mime="application/json",
                )

# ══════════════════════════════════════════════════════════════════════════
# PAGE : Ajout depuis FilmFR
# ══════════════════════════════════════════════════════════════════════════

elif page == "Ajout depuis FilmFR":
    st.markdown("<h1>🎬 Générateur de métas - Ajout depuis FilmFR</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color:#94a3b8; margin-top:-0.5rem; margin-bottom:1.5rem;'>Scan automatique des nouveautés FilmFR</p>", unsafe_allow_html=True)

    frun = st.session_state.ffr_run_count

    col_btn, _ = st.columns([2, 5])
    with col_btn:
        if st.button("🔄 Charger le menu FilmFR"):
            with st.spinner("Chargement du menu FilmFR..."):
                st.session_state.ffr_menu_items = get_nouveautes_menu()
                for k in ["ffr_films_nouveaux", "ffr_films_existants", "ffr_series_nouveaux",
                          "ffr_series_existants", "ffr_selected_films", "ffr_selected_series", "ffr_results"]:
                    st.session_state[k] = []
            st.rerun()

    if st.session_state.ffr_menu_items is not None:
        if not st.session_state.ffr_menu_items:
            st.error("❌ Aucun menu trouvé sur FilmFR.")
        else:
            menu_labels = [item["text"] for item in st.session_state.ffr_menu_items]
            choix_menu = st.selectbox("📂 Choisir une section", menu_labels)
            selected_item = next(i for i in st.session_state.ffr_menu_items if i["text"] == choix_menu)

            col_scan, _ = st.columns([2, 5])
            with col_scan:
                if st.button("🔍 Scanner cette section"):
                    with st.spinner(f"Scan de « {choix_menu} » + chargement Pastebins..."):
                        existing_films = load_pastebin_robust(get_config("metas_films_pastebin"))
                        existing_series = load_pastebin_robust(get_config("megas_series_pastebin"))
                        fn, fe, sn, se = get_contenus_from_page(selected_item["url"], existing_films, existing_series)
                        st.session_state.ffr_films_nouveaux = fn
                        st.session_state.ffr_films_existants = fe
                        st.session_state.ffr_series_nouveaux = sn
                        st.session_state.ffr_series_existants = se
                        st.session_state.ffr_selected_films = []
                        st.session_state.ffr_selected_series = []
                        st.session_state.ffr_results = []
                        st.session_state.ffr_run_count += 1
                    st.rerun()

    fn = st.session_state.ffr_films_nouveaux
    fe = st.session_state.ffr_films_existants
    sn = st.session_state.ffr_series_nouveaux
    se = st.session_state.ffr_series_existants

    if fn or fe or sn or se:
        st.markdown("---")
        col_films, col_series = st.columns(2)
        with col_films:
            st.markdown(f"<h3>🎬 Films nouveaux <span style='background:#6366f1;color:white;border-radius:12px;padding:2px 10px;font-size:0.85rem;'>{len(fn)}</span></h3>", unsafe_allow_html=True)
            if fn:
                st.session_state.ffr_selected_films = st.multiselect("Films à traiter", fn, default=fn, key=f"ms_films_{frun}")
            else:
                st.info("Aucun nouveau film.")
            if fe:
                with st.expander(f"✔️ Déjà présents ({len(fe)})"):
                    for f in fe:
                        st.text(f"• {f}")
        with col_series:
            st.markdown(f"<h3>📺 Séries nouvelles <span style='background:#8b5cf6;color:white;border-radius:12px;padding:2px 10px;font-size:0.85rem;'>{len(sn)}</span></h3>", unsafe_allow_html=True)
            if sn:
                st.session_state.ffr_selected_series = st.multiselect("Séries à traiter", sn, default=sn, key=f"ms_series_{frun}")
            else:
                st.info("Aucune nouvelle série.")
            if se:
                with st.expander(f"✔️ Déjà présentes ({len(se)})"):
                    for s in se:
                        st.text(f"• {s}")

        total_selected = len(st.session_state.ffr_selected_films) + len(st.session_state.ffr_selected_series)
        if total_selected > 0:
            st.markdown("---")
            col_go, _ = st.columns([3, 5])
            with col_go:
                if st.button(f"🚀 Traiter {total_selected} contenus (TMDb + JustWatch)"):
                    st.session_state.ffr_run_count += 1
                    st.session_state.ffr_results = []
                    all_to_process = st.session_state.ffr_selected_films + st.session_state.ffr_selected_series
                    results = []
                    progress = st.progress(0)
                    status = st.empty()
                    for i, titre in enumerate(all_to_process):
                        status.text(f"⏳ Traitement {i+1}/{len(all_to_process)} : {titre}")
                        search_name = clean_title_for_search(titre)
                        top3 = tmdb_search_top3(search_name)
                        imdb_id = top3[0]["id"] if top3 else None
                        time.sleep(0.2)
                        top3_jw = scraper_justwatch_top3(search_name)
                        poster_url = top3_jw[0]["poster"] if top3_jw else None
                        time.sleep(0.3)
                        imdb_title = search_name
                        if imdb_id:
                            imdb_title = tmdb_get_title(imdb_id) or search_name
                            time.sleep(0.1)
                        results.append({
                            "id": imdb_id,
                            "name_original": titre,
                            "name": search_name,
                            "imdb_title": imdb_title,
                            "poster": poster_url or (f"https://live.metahub.space/poster/small/{imdb_id}/img" if imdb_id else None),
                            "top3": top3, "top3_jw": top3_jw
                        })
                        progress.progress((i + 1) / len(all_to_process))
                    st.session_state.ffr_results = results
                    status.empty()
                    st.rerun()

    if st.session_state.ffr_results:
        frun = st.session_state.ffr_run_count
        st.markdown("---")
        st.markdown("<h2>📊 Résultats du traitement</h2>", unsafe_allow_html=True)
        ok = [r for r in st.session_state.ffr_results if r["id"]]
        ko = [r for r in st.session_state.ffr_results if not r["id"]]
        if ko:
            st.warning(f"⚠️ {len(ko)} contenu(s) sans IMDb ID — à compléter manuellement.")
        if ok:
            st.success(f"✅ {len(ok)} contenu(s) trouvés automatiquement.")
        for i, res in enumerate(st.session_state.ffr_results):
            render_result_card(i, res, frun, prefix="ffr")

        st.markdown("---")
        col_all, col_pb, _ = st.columns([2, 1.5, 4])
        with col_all:
            if st.button("📋 Compiler tous les metas valides", key="ffr_compile_all"):
                ids_existants = [m["id"] for m in st.session_state.compiled_metas]
                for res in ok:
                    if res["id"] not in ids_existants:
                        st.session_state.compiled_metas.append({
                            "id": res["id"],
                            "name": res.get("name_original") or res["name"],
                            "poster": res["poster"] or f"https://live.metahub.space/poster/small/{res['id']}/img"
                        })
                st.rerun()
        with col_pb:
            st.link_button("📎 Pastebin", "https://pastebin.com")
        render_compiled_metas("vider_ffr")
