"""Canonical vehicle catalog and conservative multilingual name recognition.

Catalog is intentionally extensible; unidentified names are not hallucinated.
"""
import re
import unicodedata
from difflib import SequenceMatcher

CATALOG_TEXT = "Toyota|Camry,Corolla,RAV4,Highlander,Grand Highlander,Sequoia,Prius,Prius Prime,4Runner,Land Cruiser,Tacoma,Tundra,Avalon,C-HR,Venza,Sienna,Corolla Cross,GR86,Supra,Crown,Crown Signia,bZ4X,bZ,Mirai,Yaris,Aygo,Hilux,Fortuner,Innova,Century,Alphard,Vellfire,Raize,Urban Cruiser\nLexus|IS,ES,GS,LS,UX,NX,RX,GX,LX,TX,RC,LC,RZ,CT,HS,SC,LFA,LBX,LM\nHonda|Civic,Accord,CR-V,HR-V,Passport,Pilot,Ridgeline,Odyssey,Fit,Insight,Clarity,Element,CR-Z,Prelude,Prologue,City,Shuttle,Freed,Stepwgn,ZR-V,WR-V,e:Ny1\nAcura|ILX,TLX,RLX,Integra,MDX,RDX,ADX,ZDX,NSX,TL,TSX,RL,RSX\nNissan|Altima,Maxima,Sentra,Versa,Leaf,Rogue,Rogue Sport,Kicks,Murano,Pathfinder,Armada,Frontier,Titan,370Z,350Z,Z,Ariya,Quest,Juke,Note,Qashqai,X-Trail,Navara,Patrol,Serena,Micra,March,Sunny,Teana,Elgrand\nInfiniti|Q30,Q50,Q60,Q70,QX30,QX50,QX55,QX60,QX70,QX80,G35,G37,EX35,FX35,FX37,FX50,JX35,M35,M37\nSubaru|Impreza,Legacy,Outback,Forester,Crosstrek,XV,Ascent,WRX,STI,BRZ,Solterra,Levorg,Tribeca\nMazda|Mazda2,Mazda3,Mazda5,Mazda6,CX-3,CX-30,CX-5,CX-50,CX-60,CX-70,CX-80,CX-9,CX-90,MX-5,MX-30,RX-8,Tribute,BT-50\nMitsubishi|Outlander,Outlander Sport,Eclipse Cross,Mirage,Lancer,Galant,Pajero,Montero,ASX,RVR,L200,Triton,Delica,i-MiEV\nSuzuki|Swift,Vitara,Grand Vitara,S-Cross,SX4,Jimny,Ignis,Baleno,Alto,Celerio,Spacia,Carry,Ertiga\nHyundai|Elantra,Sonata,Accent,Veloster,Kona,Kona Electric,Tucson,Santa Fe,Santa Cruz,Palisade,Venue,Ioniq,Ioniq 5,Ioniq 6,Ioniq 9,Nexo,Azera,Genesis,i10,i20,i30,i40,Bayon,Creta,Staria,Starex,Porter\nKia|Rio,Forte,K3,K4,K5,Optima,Stinger,Soul,Seltos,Sportage,Sorento,Telluride,Carnival,Sedona,Niro,Niro EV,EV3,EV4,EV5,EV6,EV9,Ceed,ProCeed,XCeed,Stonic,Picanto,Ray,Morning,Mohave,Bongo\nGenesis|G70,G80,G90,GV60,GV70,GV80,GV80 Coupe\nFord|Fiesta,Focus,Fusion,Mondeo,Taurus,Mustang,Mustang Mach-E,Escape,Kuga,EcoSport,Edge,Explorer,Expedition,Bronco,Bronco Sport,Ranger,Maverick,F-150,F-150 Lightning,F-250,F-350,Super Duty,Flex,Transit,Transit Connect,Excursion,C-Max,B-Max,Galaxy,S-Max,Everest\nLincoln|MKZ,MKS,MKC,MKX,MKT,Continental,Corsair,Nautilus,Aviator,Navigator\nChevrolet|Spark,Sonic,Cruze,Malibu,Impala,Volt,Bolt EV,Bolt EUV,Trax,Trailblazer,Equinox,Equinox EV,Blazer,Blazer EV,Traverse,Tahoe,Suburban,Colorado,Silverado,Silverado EV,Camaro,Corvette,Captiva,Orlando,Aveo,Lacetti,Niva,Express\nGMC|Terrain,Acadia,Yukon,Yukon XL,Canyon,Sierra,Sierra EV,Hummer EV,Savana\nCadillac|ATS,CTS,CT4,CT5,CT6,XT4,XT5,XT6,Escalade,Escalade ESV,Escalade IQ,Lyriq,Optiq,Vistiq,SRX,XTS,DTS\nBuick|Encore,Encore GX,Envision,Enclave,Regal,LaCrosse,Verano,Cascada,Envista\nChrysler|200,300,Pacifica,Voyager,Town & Country\nDodge|Charger,Challenger,Durango,Journey,Hornet,Grand Caravan,Caravan,Dart,Nitro,Caliber,Avenger\nJeep|Wrangler,Gladiator,Cherokee,Grand Cherokee,Grand Cherokee L,Compass,Renegade,Patriot,Liberty,Commander,Wagoneer,Grand Wagoneer,Avenger,Recon\nRAM|1500,2500,3500,ProMaster,ProMaster City\nVolkswagen|Golf,e-Golf,Golf GTI,Golf R,Jetta,Passat,Arteon,Tiguan,Taos,Atlas,Atlas Cross Sport,Touareg,ID.3,ID.4,ID.5,ID.6,ID.7,ID.Buzz,ID.UNYX,T-Roc,T-Cross,Polo,Up,Scirocco,Caddy,Transporter,Multivan,Amarok,Touran,Sharan,Beetle,CC\nAudi|A1,A3,A4,A5,A6,A7,A8,Q2,Q3,Q4 e-tron,Q5,Q6 e-tron,Q7,Q8,Q8 e-tron,e-tron,e-tron GT,TT,R8,RS3,RS4,RS5,RS6,RS7,S3,S4,S5,S6\nBMW|1 Series,2 Series,3 Series,4 Series,5 Series,6 Series,7 Series,8 Series,X1,X2,X3,X4,X5,X6,X7,XM,Z4,i3,i4,i5,i7,i8,iX,iX1,iX2,M2,M3,M4,M5,M8\nMercedes-Benz|A-Class,B-Class,C-Class,E-Class,S-Class,CLA,CLS,GLA,GLB,GLC,GLE,GLS,G-Class,GLK,ML,SL,SLK,SLC,Sprinter,Vito,V-Class,EQB,EQA,EQC,EQE,EQS,EQE SUV,EQS SUV,AMG GT,Citan,T-Class,R-Class,Metris\nPorsche|Macan,Cayenne,Panamera,Taycan,911,718 Cayman,718 Boxster,Boxster,Cayman\nVolvo|S40,S60,S80,S90,V40,V60,V90,XC40,XC60,XC70,XC90,C30,C40,EX30,EX40,EX90,EC40,EM90\nPolestar|1,2,3,4,5\nTesla|Model S,Model 3,Model X,Model Y,Cybertruck,Roadster\nRivian|R1T,R1S,R2,R3\nLucid|Air,Gravity\nFisker|Ocean,Karma\nLand Rover|Defender,Discovery,Discovery Sport,Freelander\nRange Rover|Evoque,Velar,Sport,Autobiography\nJaguar|XE,XF,XJ,F-Type,F-Pace,E-Pace,I-Pace\nMINI|Cooper,Cooper S,Countryman,Clubman,Paceman,Aceman,Hardtop,Convertible\nFiat|500,500e,500X,500L,Panda,Tipo,Doblo,Ducato,Punto\nAlfa Romeo|Giulia,Stelvio,Tonale,4C,MiTo,Giulietta\nPeugeot|208,308,408,508,2008,3008,5008,Rifter,Partner,Traveller,e-208,e-2008\nCitroen|C1,C3,C4,C5,C5 Aircross,Berlingo,Jumpy,Spacetourer,DS3,DS4,DS5\nRenault|Clio,Megane,Scenic,Captur,Kadjar,Koleos,Arkana,Kangoo,Trafic,Master,Zoe,Austral,Rafale,Symbioz,Duster\nDacia|Sandero,Logan,Duster,Jogger,Spring,Bigster,Lodgy,Dokker\nSkoda|Fabia,Octavia,Superb,Rapid,Scala,Kamiq,Karoq,Kodiaq,Enyaq,Elroq,Roomster,Yeti\nSeat|Ibiza,Leon,Ateca,Arona,Tarraco,Alhambra\nCupra|Formentor,Leon,Born,Tavascan,Terramar,Ateca\nOpel|Corsa,Astra,Insignia,Mokka,Crossland,Grandland,Zafira,Combo,Vivaro\nVauxhall|Corsa,Astra,Insignia,Mokka,Crossland,Grandland,Zafira,Combo,Vivaro\nSaab|9-3,9-5,9-4X\nSmart|Fortwo,Forfour,#1,#3\nBYD|Atto 3,Seal,Sealion 7,Dolphin,Han,Tang,Song Plus,Yuan Plus,Seagull,Destroyer 05,Qin Plus,Shark\nGeely|Coolray,Atlas,Monjaro,Emgrand,Preface,Tugella,Galaxy E5,Galaxy L7\nZeekr|001,007,009,X,7X,MIX\nNIO|ES6,ES7,ES8,ET5,ET7,EC6,EC7,EL6,EL7,EL8\nXPeng|P5,P7,P7i,G6,G9,X9,MONA M03\nLi Auto|L6,L7,L8,L9,Mega,i6,i8\nLeapmotor|T03,C10,C11,C16,B10\nChery|Tiggo 4,Tiggo 7,Tiggo 8,Arrizo 5,Arrizo 8,eQ1\nChangan|CS35,CS55,CS75,UNI-T,UNI-K,UNI-V,Deepal S07\nMG|MG3,MG4,MG5,ZS,HS,Marvel R,Cyberster\nVinFast|VF 3,VF 5,VF 6,VF 7,VF 8,VF 9\nIsuzu|D-Max,MU-X,NPR\nHummer|H2,H3,EV\nBentley|Bentayga,Continental GT,Flying Spur,Mulsanne\nRolls-Royce|Cullinan,Ghost,Phantom,Wraith,Dawn,Spectre\nLamborghini|Urus,Huracan,Aventador,Revuelto,Temerario\nFerrari|Roma,Portofino,California,488,458,F8,296,812,SF90,Purosangue\nMaserati|Ghibli,Levante,Grecale,Quattroporte,GranTurismo,MC20"
BRAND_TEXT = "Toyota|тойота,тоёта,тайота,taоyota,toyota,toyta,toyotta\nVolkswagen|фольксваген,фолксваген,фольцваген,вольксваген,фольц,volkswagen,volksvagen,folkswagen,vw\nMercedes-Benz|мерседес,мерс,мерседес бенц,мерседес-бенц,mercedes,mercedes benz,mercedes-benz,merc\nChevrolet|шевроле,шевролет,шевролє,шеві,шеви,chevrolet,chevy,chevrole\nHyundai|хундай,хюндай,хендай,хйундай,хенде,hyundai,hundai,hyndai\nKia|кіа,киа,kia,кия\nNissan|нісан,ниссан,ніссан,нисан,nissan,nisan\nMitsubishi|мітсубісі,митсубиси,міцубісі,мицубиси,mitsubishi,mitsubisi\nHonda|хонда,хонда,honda\nFord|форд,ford\nMazda|мазда,mazda\nSubaru|субару,subaru\nAudi|ауді,ауди,audi\nBMW|бмв,bmw,біемдабл\nJeep|джип,jeep\nRange Rover|рендж ровер,ренж ровер,рейндж ровер,ренджровер,range rover\nLand Rover|ленд ровер,ланд ровер,land rover\nLexus|лексус,lexus\nInfiniti|інфініті,инфинити,infiniti\nAcura|акура,acura\nTesla|тесла,tesla\nCadillac|каділак,кадиллак,cadillac\nBuick|бьюік,бюік,бьюик,buick\nDodge|додж,dodge\nRAM|рам,ram\nGMC|джмс,гмс,gmc\nSkoda|шкода,skoda\nRenault|рено,ренo,renault,reno\nPeugeot|пежо,peugeot\nCitroen|сітроен,ситроен,сітроєн,citroen\nVolvo|вольво,volvo\nPorsche|порше,porsche\nSuzuki|сузукі,сузуки,suzuki\nJaguar|ягуар,jaguar\nOpel|опель,opel\nFiat|фіат,фиат,fiat\nChery|чері,чери,chery\nGeely|джилі,джили,geely\nBYD|бід,биайди,bуd,byd\nMG|мг,емджі,mg"
MODEL_TEXT = "Toyota|Sequoia:секвоя,секвойя,сіквоя,сиквоя,секвоія,секвойа,секвой,sequoya,sekvoya,seqouia,secoia;Camry:камрі,камри,кемрі,кемри,kamri;Highlander:хайлендер,хайландер;Land Cruiser:ленд крузер,ланд крузер,крузак;Prius:пріус,приус;Corolla:корола,королла;4Runner:форранер,форанер;RAV4:рав4,раф4,рав 4\nFord|Edge:едж,эдж;Escape:ескейп,эскейп;Explorer:експлорер,эксплорер;Fusion:фюжн,фьюжн;Mustang:мустанг\nRange Rover|Evoque:евок,евоук,эвок;Velar:велар;Sport:спорт\nHyundai|Tucson:тусан,туссан,туксон;Santa Fe:санта фе,сантафе;Kona:кона;Ioniq 5:іонік 5,ионик 5,айонік 5\nKia|Sportage:спортейдж,спортаж;Sorento:соренто;Niro:ніро,ниро;Stinger:стінгер\nNissan|Rogue:роуг,рог;Leaf:ліф,лиф;Kicks:кікс,кикс;Qashqai:кашкай;X-Trail:ікстрейл,х-трейл\nSubaru|Forester:форестер;Crosstrek:крострек,кросстрек;Outback:аутбек,оутбек\nChevrolet|Equinox:еквінокс,эквинокс;Tahoe:тахо;Bolt EV:болт ев,болт ev\nTesla|Model 3:модель 3,модел 3;Model Y:модель у,модель y;Model S:модель с,модель s;Model X:модель х,модель x\nVolkswagen|Tiguan:тігуан,тигуан;Touareg:туарег;Passat:пасат;Jetta:джетта;Golf:гольф\nBMW|X3:х3,ікс3,икс3;X5:х5,ікс5,икс5;X6:х6,ікс6,икс6\nMercedes-Benz|C-Class:ц клас,с клас;E-Class:е клас,є клас;S-Class:ес клас;GLE:гле;GLC:глц\nHonda|Civic:сівік,сивик;Accord:акорд,аккорд;CR-V:срв,црв,crv\nJeep|Grand Cherokee:гранд черокі,гранд чероки;Wrangler:ранглер,врэнглер;Cherokee:черокі,чероки\nMazda|CX-5:сх5,цх5,сх 5;CX-30:сх30,цх30;Mazda3:мазда 3\nLexus|RX:рх,ерікс;NX:нх,енікс;LX:лх,елікс"

def key(text):
    t = unicodedata.normalize("NFKC", str(text)).casefold()
    t = t.replace("ё", "е").replace("ґ", "г").replace("ї", "і")
    return "".join(c for c in t if c.isalnum())

def words(text):
    return re.findall(r"[a-zа-яіїєґё0-9]+", str(text).casefold())

def translit(text):
    pairs = {"щ":"shch","ш":"sh","ч":"ch","ж":"zh","х":"kh","ц":"ts","ю":"yu","я":"ya","є":"ye","ї":"yi","й":"y","ы":"y","э":"e","ъ":"","ь":"","а":"a","б":"b","в":"v","г":"g","ґ":"g","д":"d","е":"e","ё":"yo","з":"z","и":"i","і":"i","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f"}
    return "".join(pairs.get(c, c) for c in str(text).casefold())

def variants(value):
    t = key(value)
    return {t, key(translit(value))}

CATALOG = {}
for line in CATALOG_TEXT.splitlines():
    brand, models = line.split("|", 1)
    CATALOG[brand] = tuple(m.strip() for m in models.split(","))

BRAND_INDEX = {}
for brand in CATALOG:
    for v in variants(brand):
        BRAND_INDEX.setdefault(v, set()).add(brand)
for line in BRAND_TEXT.splitlines():
    brand, values = line.split("|", 1)
    for name in values.split(","):
        for v in variants(name):
            BRAND_INDEX.setdefault(v, set()).add(brand)

MODEL_INDEX = {}
for brand, models in CATALOG.items():
    index = {}
    for model in models:
        for v in variants(model):
            index.setdefault(v, set()).add(model)
    MODEL_INDEX[brand] = index
for line in MODEL_TEXT.splitlines():
    brand, values = line.split("|", 1)
    for item in values.split(";"):
        model, aliases = item.split(":", 1)
        for alias in aliases.split(","):
            for v in variants(alias):
                MODEL_INDEX[brand].setdefault(v, set()).add(model)

def _resolve(index, raw, *, threshold=.88):
    probes = variants(raw)
    exact = set()
    for probe in probes:
        exact.update(index.get(probe, ()))
    if len(exact) == 1:
        return next(iter(exact))
    if exact:
        return None
    scored = []
    for candidate in index:
        score = max(SequenceMatcher(None, probe, candidate).ratio() for probe in probes)
        if score >= threshold:
            scored.append((score, candidate))
    if not scored:
        return None
    scored.sort(reverse=True)
    best = scored[0][0]
    winners = set()
    for score, candidate in scored:
        if best - score > .035:
            break
        winners.update(index[candidate])
    return next(iter(winners)) if len(winners) == 1 else None

def resolve_brand(text):
    tokens = words(text)
    for length in (3, 2, 1):
        for i in range(len(tokens) - length + 1):
            phrase = " ".join(tokens[i:i+length])
            name = _resolve(BRAND_INDEX, phrase, threshold=.92 if length == 1 else .9)
            if name:
                return name
    return None

def resolve_model(brand, text):
    index = MODEL_INDEX.get(brand)
    if not index:
        return None
    raw = re.sub(r"(?i)^(?:мене цікавить|меня интересует|хочу|шукаю|ищу|авто|машина)\\s+", "", str(text).strip())
    if key(raw) in ("", "неважливо", "любой"):
        return None
    # Model token from full name or a model-only follow-up, never arbitrary prose.
    tokens = words(raw)
    candidates = [raw]
    for length in (3, 2, 1):
        candidates.extend(" ".join(tokens[i:i+length]) for i in range(len(tokens)-length+1))
    # longest recognized name preferred, but require high confidence for single tokens
    results = []
    for candidate in candidates:
        name = _resolve(index, candidate, threshold=.9 if len(key(candidate)) >= 5 else .98)
        if name:
            results.append((len(key(candidate)), name))
    if not results:
        return None
    results.sort(reverse=True)
    top_size = results[0][0]
    names = {name for size, name in results if size == top_size}
    return next(iter(names)) if len(names) == 1 else None
