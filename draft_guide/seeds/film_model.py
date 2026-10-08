import json, re, collections
S='/home/user/fantasy_life/draft_guide/raw/'
films=json.load(open(S+'wikipedia_films_2027_2026-10-08.json'))
# title -> (bo_mid $M domestic through Dec 31 2027, rt_mid, p_release_in_2027, note)
M={
 "Ice Age":(90,30,.9),"Gatto":(120,85,.92),"Sonic the Hedgehog 4":(200,85,.95),"Not Alone":(130,70,.9),"Legend of Zelda":(320,62,.92),
 "Resurrection of the Christ":(180,45,.8),"Starfighter":(380,72,.92),"How to Train Your Dragon 2":(250,78,.92),"Spider-Verse":(370,94,.8),
 "Shrek 5":(320,68,.9),"Man of Tomorrow":(320,80,.92),"Minecraft Movie Squared":(290,52,.9),"Quiet Place Part III":(110,75,.9),
 "Godzilla x Kong":(150,50,.9),"Exorcist: Martyrs":(80,55,.8),"Thomas Crown":(60,65,.85),"Narnia":(45,80,.6),"Frozen 3":(335,75,.93),
 "Secret Wars":(298,75,.5),"Hunt for Gollum":(198,72,.8),"Housemaid's Secret":(66,55,.75),"Beekeeper 2":(60,55,.9),"Comeback King":(50,65,.9),
 "Spaceballs":(35,45,.9),"Ocean's Eleven prequel":(110,72,.8),"Panic Carefully":(40,70,.9),"Wife & Dog":(25,60,.9),"The Catch":(70,70,.9),
 "Day Drinker":(15,50,.9),"CoComelon":(40,45,.9),"Comebacker":(40,75,.85),"Remain":(35,45,.9),"The Great Beyond":(60,70,.85),
 "Mummy Returns":(70,60,.8),"Naughty":(25,55,.85),"Margie Claus":(40,50,.85),"Treasure Island":(50,65,.85),"24 Jump Street":(60,60,.8),
 "Paris Paramount":(30,70,.9),"Alone at Dawn":(15,70,.9),"The Surgeon":(25,55,.9),"Skeletons":(20,60,.9),"Possession":(25,50,.9),"John Rambo":(30,45,.9),
 "A Place in Hell":(15,65,.9),"Nightingale":(25,65,.9),"Animal Friends":(45,45,.85),"Children of Blood":(30,55,.85),"Karoshi":(8,55,.85),
 "Bad Fairies":(110,70,.7),"Daniels film":(100,78,.65),"Pendulum":(5,50,.9),"Rescue":(15,55,.9),"Snoop":(30,55,.85),"Statham Stole":(30,55,.85),
 "Shiver":(25,50,.85),"Beach Read":(25,60,.9),"Anything but Ghosts":(20,60,.9),"F.A.S.T.":(25,65,.9),"Family Movie":(8,55,.9),"Wishful Thinking":(5,70,.9),
 "Charlie vs":(0,60,.0),"Seasons":(10,55,.5),"Tomorrow, and Tomorrow":(20,65,.8),"Third Parent":(3,40,.9),"Drag":(3,55,.9),"Revenge of La Llorona":(35,35,.9),
}
def spec(title):
    for k,v in M.items():
        if k.lower() in title.lower(): return v
    return (8,50,.8)
comp=collections.defaultdict(float); where=collections.defaultdict(list)
for f in films:
    bo,rt,p=spec(f['title'])
    names=[n.strip() for n in re.split(r'\s*,\s*',f['cast']) if n.strip() and 'screenplay' not in n and 'director' not in n]
    for n in names:
        n=re.sub(r'\s*\(.*\)','',n)
        c=p*(rt/100)*bo
        comp[n]+=c; where[n].append((f['title'][:28],round(c)))
top=sorted(comp.items(), key=lambda kv:-kv[1])
json.dump({n:{'mu':round(c,1),'films':where[n]} for n,c in top}, open('/tmp/people_comp.json','w'), ensure_ascii=False, indent=0)
for n,c in top[:90]: print(f"{c:6.0f}  {n:24} {where[n]}")
