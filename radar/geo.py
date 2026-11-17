"""Location strings -> ISO-2 countries, plus coordinates for HQ dots and expansion arcs."""
from __future__ import annotations

import re
import unicodedata

# iso2: (English name, lat, lon) — centroids tuned to sit on land for the map
COUNTRIES = {
    "ES": ("Spain", 40.2, -3.6), "PT": ("Portugal", 39.6, -8.2), "FR": ("France", 46.6, 2.4),
    "DE": ("Germany", 51.1, 10.4), "GB": ("United Kingdom", 52.8, -1.6), "IE": ("Ireland", 53.2, -7.9),
    "NL": ("Netherlands", 52.2, 5.5), "BE": ("Belgium", 50.6, 4.6), "LU": ("Luxembourg", 49.8, 6.1),
    "IT": ("Italy", 42.8, 12.6), "CH": ("Switzerland", 46.8, 8.2), "AT": ("Austria", 47.6, 14.1),
    "DK": ("Denmark", 56.0, 9.3), "SE": ("Sweden", 60.1, 15.6), "NO": ("Norway", 61.0, 9.0),
    "FI": ("Finland", 62.5, 25.8), "IS": ("Iceland", 64.9, -18.6), "PL": ("Poland", 52.1, 19.4),
    "CZ": ("Czechia", 49.8, 15.5), "SK": ("Slovakia", 48.7, 19.7), "HU": ("Hungary", 47.2, 19.4),
    "RO": ("Romania", 45.9, 24.9), "BG": ("Bulgaria", 42.7, 25.3), "GR": ("Greece", 39.3, 22.0),
    "HR": ("Croatia", 45.3, 16.0), "SI": ("Slovenia", 46.1, 14.8), "RS": ("Serbia", 44.0, 20.8),
    "EE": ("Estonia", 58.7, 25.5), "LV": ("Latvia", 56.9, 24.6), "LT": ("Lithuania", 55.3, 23.9),
    "UA": ("Ukraine", 49.0, 31.4), "TR": ("Turkey", 39.0, 35.2), "CY": ("Cyprus", 35.0, 33.2),
    "MT": ("Malta", 35.9, 14.4), "US": ("United States", 39.8, -98.6), "CA": ("Canada", 56.1, -106.3),
    "MX": ("Mexico", 23.6, -102.6), "BR": ("Brazil", -14.2, -51.9), "AR": ("Argentina", -38.4, -63.6),
    "CO": ("Colombia", 4.6, -74.3), "CL": ("Chile", -35.7, -71.5), "PE": ("Peru", -9.2, -75.0),
    "AE": ("United Arab Emirates", 24.3, 54.4), "SA": ("Saudi Arabia", 24.0, 45.0), "IL": ("Israel", 31.0, 34.9),
    "IN": ("India", 21.0, 78.0), "SG": ("Singapore", 1.35, 103.8), "AU": ("Australia", -25.3, 133.8),
    "JP": ("Japan", 36.2, 138.3), "ZA": ("South Africa", -30.6, 22.9), "MA": ("Morocco", 31.8, -7.1),
    "EG": ("Egypt", 26.8, 30.8), "NG": ("Nigeria", 9.1, 8.7), "KE": ("Kenya", 0.0, 37.9),
    "PH": ("Philippines", 12.9, 121.8), "HK": ("Hong Kong", 22.3, 114.2), "CN": ("China", 35.9, 104.2),
}

_ALIASES = {
    "ES": ["spain", "espana", "espanya", "madrid", "barcelona", "valencia", "seville", "sevilla", "malaga", "bilbao",
           "zaragoza", "alicante", "san sebastian", "donostia", "a coruna", "gijon", "cordoba", "granada", "palma",
           "murcia", "girona", "lleida", "vigo", "santander", "pamplona", "las palmas", "tenerife", "valladolid"],
    "PT": ["portugal", "lisbon", "lisboa", "porto", "oporto", "braga", "coimbra", "aveiro", "faro"],
    "FR": ["france", "paris", "lyon", "marseille", "toulouse", "bordeaux", "lille", "nantes", "nice", "montpellier",
           "strasbourg", "rennes", "grenoble", "aix-en-provence", "ile-de-france"],
    "DE": ["germany", "deutschland", "berlin", "munich", "munchen", "hamburg", "frankfurt", "cologne", "koln",
           "dusseldorf", "stuttgart", "leipzig", "dresden", "aachen", "heidelberg", "freiburg", "hannover", "nuremberg",
           "nurnberg", "karlsruhe", "bonn", "essen", "dortmund", "mannheim"],
    "GB": ["united kingdom", "uk", "england", "scotland", "wales", "northern ireland", "great britain", "london",
           "manchester", "edinburgh", "glasgow", "bristol", "birmingham", "leeds", "cambridge", "oxford", "belfast",
           "cardiff", "liverpool", "newcastle", "brighton", "sheffield", "nottingham"],
    "IE": ["ireland", "dublin", "cork", "galway", "limerick"],
    "NL": ["netherlands", "the netherlands", "holland", "amsterdam", "rotterdam", "utrecht", "eindhoven", "the hague",
           "den haag", "groningen", "leiden", "delft"],
    "BE": ["belgium", "brussels", "bruxelles", "antwerp", "ghent", "gent", "leuven", "liege"],
    "LU": ["luxembourg"],
    "IT": ["italy", "italia", "milan", "milano", "rome", "roma", "turin", "torino", "bologna", "florence", "firenze",
           "naples", "napoli", "genoa", "padova", "verona", "bari", "venice", "trento"],
    "CH": ["switzerland", "schweiz", "suisse", "zurich", "geneva", "geneve", "basel", "lausanne", "bern", "zug", "lugano"],
    "AT": ["austria", "osterreich", "vienna", "wien", "graz", "linz", "salzburg", "innsbruck"],
    "DK": ["denmark", "danmark", "copenhagen", "kobenhavn", "aarhus", "odense", "aalborg"],
    "SE": ["sweden", "sverige", "stockholm", "gothenburg", "goteborg", "malmo", "uppsala", "lund"],
    "NO": ["norway", "norge", "oslo", "bergen", "trondheim", "stavanger"],
    "FI": ["finland", "suomi", "helsinki", "espoo", "tampere", "oulu", "turku"],
    "IS": ["iceland", "reykjavik"],
    "PL": ["poland", "polska", "warsaw", "warszawa", "krakow", "wroclaw", "gdansk", "poznan", "lodz", "katowice", "szczecin"],
    "CZ": ["czechia", "czech republic", "prague", "praha", "brno", "ostrava"],
    "SK": ["slovakia", "bratislava", "kosice"],
    "HU": ["hungary", "budapest", "debrecen"],
    "RO": ["romania", "bucharest", "bucuresti", "cluj", "cluj-napoca", "iasi", "timisoara", "brasov"],
    "BG": ["bulgaria", "sofia", "plovdiv", "varna"],
    "GR": ["greece", "athens", "thessaloniki"],
    "HR": ["croatia", "zagreb"],
    "SI": ["slovenia", "ljubljana"],
    "RS": ["serbia", "belgrade", "novi sad"],
    "EE": ["estonia", "tallinn", "tartu"],
    "LV": ["latvia", "riga"],
    "LT": ["lithuania", "vilnius", "kaunas"],
    "UA": ["ukraine", "kyiv", "kiev", "lviv", "kharkiv"],
    "TR": ["turkey", "turkiye", "istanbul", "ankara", "izmir"],
    "CY": ["cyprus", "limassol", "nicosia"],
    "MT": ["malta", "valletta"],
    "US": ["united states", "usa", "u.s.", "new york", "nyc", "san francisco", "boston", "austin", "chicago", "seattle",
           "los angeles", "miami", "denver", "atlanta", "washington, dc", "palo alto", "menlo park", "dallas",
           "houston", "remote - us", "remote, us", "remote (us)", "us remote", "remote us", "california", "texas",
           "massachusetts", "illinois", "colorado", "florida", "georgia, us", "north carolina", "raleigh", "phoenix",
           "philadelphia", "salt lake city", "portland, or", "san diego", "san jose", "nashville", "minneapolis"],
    "CA": ["canada", "toronto", "montreal", "vancouver", "ottawa", "calgary"],
    "MX": ["mexico", "ciudad de mexico", "cdmx", "mexico city", "guadalajara", "monterrey"],
    "BR": ["brazil", "brasil", "sao paulo", "rio de janeiro", "belo horizonte", "curitiba"],
    "AR": ["argentina", "buenos aires", "cordoba, argentina"],
    "CO": ["colombia", "bogota", "medellin"],
    "CL": ["chile", "santiago de chile", "santiago, chile"],
    "PE": ["peru", "lima"],
    "AE": ["united arab emirates", "uae", "dubai", "abu dhabi"],
    "SA": ["saudi arabia", "riyadh", "jeddah", "ksa"],
    "IL": ["israel", "tel aviv", "jerusalem", "haifa"],
    "IN": ["india", "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad", "pune", "chennai", "gurgaon", "gurugram", "noida"],
    "SG": ["singapore"],
    "AU": ["australia", "sydney", "melbourne", "brisbane", "perth"],
    "JP": ["japan", "tokyo", "osaka"],
    "ZA": ["south africa", "cape town", "johannesburg"],
    "MA": ["morocco", "casablanca", "rabat"],
    "EG": ["egypt", "cairo"],
    "NG": ["nigeria", "lagos"],
    "KE": ["kenya", "nairobi"],
    "PH": ["philippines", "manila"],
    "HK": ["hong kong"],
    "CN": ["china", "shanghai", "beijing", "shenzhen"],
}

CITY_COORDS = {
    "madrid": (40.42, -3.70), "barcelona": (41.39, 2.17), "valencia": (39.47, -0.38), "seville": (37.39, -5.98),
    "malaga": (36.72, -4.42), "bilbao": (43.26, -2.93), "san sebastian": (43.32, -1.98), "a coruna": (43.36, -8.41),
    "gijon": (43.53, -5.66), "cordoba": (37.89, -4.78), "girona": (41.98, 2.82), "lleida": (41.62, 0.62),
    "zaragoza": (41.65, -0.89), "alicante": (38.35, -0.48), "lisbon": (38.72, -9.14), "porto": (41.15, -8.61),
    "coimbra": (40.21, -8.43), "braga": (41.55, -8.42), "paris": (48.86, 2.35), "lyon": (45.76, 4.84),
    "aix-en-provence": (43.53, 5.45), "montpellier": (43.61, 3.88), "toulouse": (43.60, 1.44), "nantes": (47.22, -1.55),
    "lille": (50.63, 3.06), "bordeaux": (44.84, -0.58), "berlin": (52.52, 13.40), "munich": (48.14, 11.58),
    "hamburg": (53.55, 9.99), "cologne": (50.94, 6.96), "frankfurt": (50.11, 8.68), "aachen": (50.78, 6.08),
    "heidelberg": (49.40, 8.67), "freiburg": (47.99, 7.84), "dusseldorf": (51.23, 6.77), "stuttgart": (48.78, 9.18),
    "leipzig": (51.34, 12.37), "karlsruhe": (49.01, 8.40), "london": (51.51, -0.13), "edinburgh": (55.95, -3.19),
    "manchester": (53.48, -2.24), "cambridge": (52.21, 0.12), "oxford": (51.75, -1.26), "bristol": (51.45, -2.59),
    "belfast": (54.60, -5.93), "glasgow": (55.86, -4.25), "dublin": (53.35, -6.26), "cork": (51.90, -8.47),
    "amsterdam": (52.37, 4.90), "rotterdam": (51.92, 4.48), "utrecht": (52.09, 5.12), "eindhoven": (51.44, 5.47),
    "the hague": (52.08, 4.30), "brussels": (50.85, 4.35), "antwerp": (51.22, 4.40), "ghent": (51.05, 3.72),
    "milan": (45.46, 9.19), "rome": (41.90, 12.50), "turin": (45.07, 7.69), "bologna": (44.49, 11.34),
    "zurich": (47.38, 8.54), "geneva": (46.20, 6.14), "lausanne": (46.52, 6.63), "zug": (47.17, 8.52),
    "basel": (47.56, 7.59), "vienna": (48.21, 16.37), "linz": (48.31, 14.29), "graz": (47.07, 15.44),
    "copenhagen": (55.68, 12.57), "aarhus": (56.16, 10.20), "stockholm": (59.33, 18.07), "gothenburg": (57.71, 11.97),
    "malmo": (55.60, 13.00), "oslo": (59.91, 10.75), "bergen": (60.39, 5.32), "helsinki": (60.17, 24.94),
    "oulu": (65.01, 25.47), "espoo": (60.21, 24.66), "warsaw": (52.23, 21.01), "krakow": (50.06, 19.94),
    "wroclaw": (51.11, 17.03), "szczecin": (53.43, 14.55), "gdansk": (54.35, 18.65), "prague": (50.08, 14.44),
    "brno": (49.20, 16.61), "budapest": (47.50, 19.04), "bucharest": (44.43, 26.10), "cluj-napoca": (46.77, 23.60),
    "sofia": (42.70, 23.32), "athens": (37.98, 23.73), "zagreb": (45.81, 15.98), "ljubljana": (46.06, 14.51),
    "belgrade": (44.79, 20.45), "tallinn": (59.44, 24.75), "riga": (56.95, 24.11), "vilnius": (54.69, 25.28),
    "kyiv": (50.45, 30.52), "istanbul": (41.01, 28.98), "luxembourg": (49.61, 6.13), "reykjavik": (64.15, -21.94),
    "dubai": (25.20, 55.27), "tel aviv": (32.09, 34.78), "new york": (40.71, -74.01), "san francisco": (37.77, -122.42),
    "boston": (42.36, -71.06),
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


_PATTERNS = []
for iso, words in _ALIASES.items():
    for w in words:
        _PATTERNS.append((iso, re.compile(r"(?<![a-z])" + re.escape(_norm(w)) + r"(?![a-z])")))
_AMBIG_REMOTE = re.compile(r"\b(remote|anywhere|worldwide|global|emea|europe|eu)\b")


def countries_in(locations: list[str], country_codes: list[str] = ()) -> list[str]:
    found = {c for c in country_codes if c in COUNTRIES}
    for loc in locations:
        n = _norm(loc)
        for iso, pat in _PATTERNS:
            if pat.search(n):
                found.add(iso)
    # "Cordoba, Argentina" also matches ES "cordoba": drop ES if AR matched on that exact token
    if "AR" in found and any("argentina" in _norm(l) for l in locations) and \
            not any(re.search(r"spain|espana|madrid|barcelona", _norm(l)) for l in locations):
        found.discard("ES")
    return sorted(found)


def is_remote_only(locations: list[str]) -> bool:
    return bool(locations) and all(_AMBIG_REMOTE.search(_norm(l)) for l in locations)


def city_coords(city: str, country: str) -> tuple[float, float]:
    c = CITY_COORDS.get(_norm(city))
    if c:
        return c
    _, lat, lon = COUNTRIES.get(country, ("", 48.0, 10.0))
    return lat, lon
