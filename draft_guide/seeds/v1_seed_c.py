"""v1 seed (2026-10-08): ONE-TIME import of the first research pass into draft_guide/data/*.json. Kept for provenance — after v1, edit the JSON directly (re-running a seed overwrites manual edits). Absolute paths assume the Claude Code cloud checkout."""
import json, re, collections, os
S = '/home/user/fantasy_life/draft_guide/raw/'
D = '/home/user/fantasy_life/draft_guide/data'
AS_OF = '2026-10-08'
exec(open('/home/user/fantasy_life/draft_guide/seeds/film_model.py').read().split("comp=collections")[0])   # films, M, spec

def dump(cat, entries, note=None):
    with open(f'{D}/{cat}.json', 'w') as f:
        json.dump({"category": cat, "as_of": AS_OF, "note": note, "entries": entries}, f, indent=1, ensure_ascii=False)
    print(cat, len(entries))

FEMALE = set("""Kristen Hailee Lauren Lauren Kimiko Mia Amy Rachel Isabela María Sara Milly Idina Cameron Zendaya Nico Dichen Yvonne Lydia Bo Colleen Tika Kirsten
Danielle Jennifer Kate Adria Cate Anya Letitia Vanessa Hayley Sadie Alycia Dakota Elle Shira Michelle Daisy Brittany Selena Allison Margot Monica Vicky
Emily Millicent Katy Penélope Sydney Melissa Octavia Maria Annie Jenna Sophie Merritt Regina Kaitlyn Jane Jessica Emmy Yara Pom Aubrey Phoebe Maya Brie
Margaret Julia Elizabeth Lizzy Ashley Emma Queen Hannah Keke Daphne Kristin Andie Bryce Violet Juliana Rosamund Cynthia Lily Carey Meryl Cristin Madelyn
Kyra Sosie Liza Amélie Storm Aunjanue Ella Sasha Jennifer Danai Lily Lashana Amandla Tosin Isabel Roselyn Lucy Christine Julie Ione Willa Callie Louise
Sandra Amanda Tao Mariana Olivia Renate Renée Julianne Sandra Inde Inde Rosalind Ruth Virginie Gemma Marion Shailene Scarlett Natalie Isabella Parker Mikey
Rebecca Fanning Jaafar Hailey Samantha Zoë Brittany Selma Lupita Zara Ravyn Sienna Tate Karol Billie Dua Chappell Megan Renee Nicola Helena Charithra Betty
Erin Elisabeth Tracy Sissy Lorelei Hassie Tig Vanessa Chase Cole Kate""".split())
# names that look female by first name but are not / male names in FEMALE: fix
NOT_FEMALE = {"Kimiko Glenn"} - {"Kimiko Glenn"}
MALE_OVERRIDE = {"Lee Majdoub", "Parker Finn", "Chase Yi", "Jaafar Jackson", "Cameron Diaz"} - {"Cameron Diaz"}
FEMALE_OVERRIDE = {"Cameron Diaz", "Lauren Vélez", "Lauren Ridloff", "Bo Bragason", "Nico Parker", "Queen Latifah", "Shameik Moore"} - {"Shameik Moore"}
MALE_FORCE = {"Shameik Moore", "Jaafar Jackson", "Lee Majdoub", "Chase Yi"}
def gender(n):
    if n in MALE_FORCE: return 'M'
    if n in FEMALE_OVERRIDE: return 'F'
    first = n.split()[0]
    return 'F' if first in FEMALE else 'M'

comp = collections.defaultdict(float); where = collections.defaultdict(list)
for f in films:
    bo, rt, p = spec(f['title'])
    names = [re.sub(r'\s*\(.*\)', '', n.strip()) for n in re.split(r'\s*,\s*', f['cast']) if n.strip() and 'screenplay' not in n and 'director' not in n]
    for n in dict.fromkeys(names):
        # Dec-17+ openers: bo already "through Dec 31" in M for tentpoles
        c = p * (rt / 100) * bo
        comp[n] += c
        where[n].append({"title": re.sub(r"^(Star Wars: )", "", f['title'])[:46], "date": f"{f['m'][:3].title()} {f['d']}", "p_release": p, "bo_mid": bo, "rt_mid": rt})

def entry(n, g):
    fl = where.get(n, [])
    mu = round(comp.get(n, 0.0), 1)
    detail = "; ".join(f"{x['title']} ({x['date']})" for x in sorted(fl, key=lambda x: -(x['p_release'] * x['bo_mid'] * x['rt_mid']))[:4]) or "no 2027 film found in Wikipedia's cast lists"
    return {"name": n, "detail": detail, "odds": None, "mu": mu, "sd": round(max(mu * 0.5, 8), 1), "confidence": "C",
            "source": "Wikipedia 'List of American films of 2027' casts (Actions-runner pull 2026-10-08) x comp-based box office/RT estimates; cast lists are billed leads only (cameos not captured)",
            "as_of": AS_OF, "notes": "", "films": fl}

people = sorted(comp.items(), key=lambda kv: -kv[1])
actors, actresses = [], []
for n, c in people:
    (actresses if gender(n) == 'F' else actors).append(entry(n, gender(n)))
# league-relevant names with no/low 2027 film must still be on the board
for n, g in [("Timothée Chalamet", 'M'), ("Pedro Pascal", 'M'), ("Chris Hemsworth", 'M'), ("Matt Damon", 'M'), ("Tom Holland", 'M'), ("Robert Pattinson", 'M'),
             ("Jon Bernthal", 'M'), ("Dwayne Johnson", 'M'), ("Jeremy Allen White", 'M'), ("Leonardo DiCaprio", 'M'), ("George Clooney", 'M'), ("Sean Penn", 'M'),
             ("Wagner Moura", 'M'), ("Zendaya", 'F'), ("Florence Pugh", 'F'), ("Anya Taylor-Joy", 'F'), ("Anne Hathaway", 'F'), ("Charlize Theron", 'F'),
             ("Jessie Buckley", 'F'), ("Ariana Grande", 'F'), ("Emma Stone", 'F'), ("Sydney Sweeney", 'F'), ("Cynthia Erivo", 'F'), ("Teyana Taylor", 'F'),
             ("Amanda Seyfried", 'F'), ("Tessa Thompson", 'F')]:
    tgt = actors if g == 'M' else actresses
    nn = n.replace("Timothée", "Timothée")
    if not any(e['name'].lower() in (n.lower(), n.replace('é', 'e').lower()) for e in tgt):
        tgt.append(entry(n, g))

# Oscar-race names need a row even with no 2027 film (their bonus EV alone can be ~7 pts)
aw_path = D + '/Awards.json'
if os.path.exists(aw_path):
    for a in json.load(open(aw_path))['entries']:
        tgt = actors if a['category'] in ('Best Actor', 'Best Supporting Actor') else actresses
        if not any(e['name'].replace('é', 'e').lower() == a['name'].replace('é', 'e').lower() for e in tgt):
            tgt.append(entry(a['name'], 'M' if tgt is actors else 'F'))

# pull the Timothee/ Timothée duplicate guard
PROTECTED = set()
if os.path.exists(D + '/Awards.json'):
    PROTECTED |= {x['name'].replace('é', 'e').lower() for x in json.load(open(D + '/Awards.json'))['entries']}
PROTECTED |= {n.replace('é', 'e').lower() for n in ["Timothée Chalamet", "Pedro Pascal", "Chris Hemsworth", "Matt Damon", "Tom Holland", "Robert Pattinson", "Jon Bernthal",
    "Dwayne Johnson", "Jeremy Allen White", "Leonardo DiCaprio", "George Clooney", "Sean Penn", "Wagner Moura", "Zendaya", "Florence Pugh", "Anya Taylor-Joy",
    "Anne Hathaway", "Charlize Theron", "Jessie Buckley", "Ariana Grande", "Emma Stone", "Sydney Sweeney", "Cynthia Erivo", "Teyana Taylor", "Amanda Seyfried", "Tessa Thompson"]}
def fix(entries):
    seen = {}; out = []
    for e in sorted(entries, key=lambda e: -e['mu']):
        k = e['name'].replace('é', 'e').lower()
        if k in seen: continue
        seen[k] = 1
        if len(out) < 70 or k in PROTECTED:
            out.append(e)
    return out
actors, actresses = fix(actors), fix(actresses)
# manual caveats
notes = {
 "Ryan Gosling": "Also cast in Avengers: Secret Wars per Wikipedia (unconfirmed by Marvel); Secret Wars may slip to 2028",
 "Timothée Chalamet": "Voice lead in Illumination's Not Alone (Apr 16, 2027). Dune 3 (Dec 18, 2026) scores 0 in 2027",
 "Pedro Pascal": "Secret Wars (Dec 17) only ~62% of its run falls inside 2027 and slip risk is high",
 "Zendaya": "Shrek 5 voice (Jun 30). Spider-Man BND and Dune 3 are 2026 -> 0",
 "Matt Damon": "Untitled Daniels film (Nov 19) only; The Odyssey is a 2026 film -> 0",
 "Anne Hathaway": "Alone at Dawn (Dec 25) opens 6 days before year-end",
 "Anya Taylor-Joy": "Hunt for Gollum (Dec 17)",
 "Aaron Pierre": "Starfighter + Man of Tomorrow (Superman credit is a Wikipedia cast-list read; verify)",
 "Kristen Bell": "Frozen 3 (Nov 24, ~78% of run in 2027) + Sonic 4",
}
for lst in (actors, actresses):
    for e in lst:
        if e['name'] in notes: e['notes'] = notes[e['name']]
dump('Actor', actors, "mu = sum over 2027 releases of p(release) x RT/100 x domestic $M through Dec 31 2027. Cast lists are Wikipedia's billed leads; cameos not captured. Box office/RT are comp-based estimates (C).")
dump('Actress', actresses, "Same model as Actor. Gender assigned from first names with manual overrides — double-check before relying on a name.")
for lst, nm in ((actors, 'ACTOR'), (actresses, 'ACTRESS')):
    print(nm)
    for e in lst[:40]: print(f"  {e['mu']:6.0f}  {e['name']:26} {e['detail'][:90]}")
