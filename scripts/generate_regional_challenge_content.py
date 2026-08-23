"""Generate the regional Gym/Trial/Elite Four/Champion challenge packs.

The rosters are the canonical story-mode teams for the named campaign.  The service
completes their move/ability/EV lines from the pinned Showdown Dex at launch, which keeps
the source roster readable and guarantees legality in the current NatDex Draft format.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONTENT = ROOT / "backend/koalabattle/challenges/content"


REGIONS: tuple[dict[str, object], ...] = (
    {
        "id": "johto-gym-gauntlet",
        "name": "Johto Gym Gauntlet",
        "region": "Johto",
        "generation": 2,
        "description": "Falkner through Champion Lance with canonical Johto story teams.",
        "reference": "https://bulbapedia.bulbagarden.net/wiki/Johto_Gym_Leaders",
        "stages": (
            (
                "falkner",
                "Falkner",
                "Violet Gym Leader",
                "Flying",
                ("Pidgey", "Pidgeotto"),
            ),
            (
                "bugsy",
                "Bugsy",
                "Azalea Gym Leader",
                "Bug",
                ("Metapod", "Kakuna", "Scyther"),
            ),
            (
                "whitney",
                "Whitney",
                "Goldenrod Gym Leader",
                "Normal",
                ("Clefairy", "Miltank"),
            ),
            (
                "morty",
                "Morty",
                "Ecruteak Gym Leader",
                "Ghost",
                ("Gastly", "Haunter", "Gengar", "Gengar"),
            ),
            (
                "chuck",
                "Chuck",
                "Cianwood Gym Leader",
                "Fighting",
                ("Primeape", "Poliwrath"),
            ),
            (
                "jasmine",
                "Jasmine",
                "Olivine Gym Leader",
                "Steel",
                ("Magnemite", "Magnemite", "Steelix"),
            ),
            (
                "pryce",
                "Pryce",
                "Mahogany Gym Leader",
                "Ice",
                ("Seel", "Dewgong", "Piloswine"),
            ),
            (
                "clair",
                "Clair",
                "Blackthorn Gym Leader",
                "Dragon",
                ("Dragonair", "Dragonair", "Dragonair", "Kingdra"),
            ),
            (
                "will",
                "Will",
                "Elite Four",
                "Psychic",
                ("Xatu", "Xatu", "Jynx", "Exeggutor", "Slowbro"),
            ),
            (
                "koga",
                "Koga",
                "Elite Four",
                "Poison",
                ("Ariados", "Venomoth", "Forretress", "Crobat"),
            ),
            (
                "bruno",
                "Bruno",
                "Elite Four",
                "Fighting",
                ("Hitmontop", "Hitmonlee", "Hitmonchan", "Onix", "Steelix", "Machamp"),
            ),
            (
                "karen",
                "Karen",
                "Elite Four",
                "Dark",
                ("Umbreon", "Vileplume", "Gengar", "Murkrow", "Houndoom"),
            ),
            (
                "lance",
                "Lance",
                "Champion",
                "Dragon",
                (
                    "Gyarados",
                    "Dragonite",
                    "Dragonite",
                    "Dragonite",
                    "Aerodactyl",
                    "Charizard",
                ),
            ),
        ),
    },
    {
        "id": "hoenn-gym-gauntlet",
        "name": "Hoenn Gym Gauntlet",
        "region": "Hoenn",
        "generation": 3,
        "description": "Roxanne through Champion Steven with canonical Hoenn story teams.",
        "reference": "https://bulbapedia.bulbagarden.net/wiki/Hoenn_Gym_Leaders",
        "stages": (
            (
                "roxanne",
                "Roxanne",
                "Rustboro Gym Leader",
                "Rock",
                ("Geodude", "Geodude", "Nosepass"),
            ),
            (
                "brawly",
                "Brawly",
                "Dewford Gym Leader",
                "Fighting",
                ("Machop", "Meditite", "Makuhita"),
            ),
            (
                "wattson",
                "Wattson",
                "Mauville Gym Leader",
                "Electric",
                ("Voltorb", "Electrike", "Magneton", "Manectric"),
            ),
            (
                "flannery",
                "Flannery",
                "Lavaridge Gym Leader",
                "Fire",
                ("Numel", "Slugma", "Torkoal"),
            ),
            (
                "norman",
                "Norman",
                "Petalburg Gym Leader",
                "Normal",
                ("Slaking", "Vigoroth", "Spinda", "Slaking"),
            ),
            (
                "winona",
                "Winona",
                "Fortree Gym Leader",
                "Flying",
                ("Swellow", "Pelipper", "Skarmory", "Altaria"),
            ),
            (
                "tate-liza",
                "Tate & Liza",
                "Mossdeep Gym Leaders",
                "Psychic",
                ("Solrock", "Lunatone"),
            ),
            (
                "juan",
                "Juan",
                "Sootopolis Gym Leader",
                "Water",
                ("Luvdisc", "Whiscash", "Sealeo", "Seaking", "Kingdra"),
            ),
            (
                "sidney",
                "Sidney",
                "Elite Four",
                "Dark",
                ("Mightyena", "Shiftry", "Cacturne", "Crawdaunt", "Absol"),
            ),
            (
                "phoebe",
                "Phoebe",
                "Elite Four",
                "Ghost",
                ("Dusclops", "Dusclops", "Banette", "Banette"),
            ),
            (
                "glacia",
                "Glacia",
                "Elite Four",
                "Ice",
                ("Glalie", "Glalie", "Sealeo", "Walrein"),
            ),
            (
                "drake",
                "Drake",
                "Elite Four",
                "Dragon",
                ("Shelgon", "Altaria", "Flygon", "Kingdra", "Salamence"),
            ),
            (
                "steven",
                "Steven",
                "Champion",
                "Steel",
                ("Skarmory", "Aggron", "Metagross", "Claydol", "Armaldo", "Cradily"),
            ),
        ),
    },
    {
        "id": "sinnoh-gym-gauntlet",
        "name": "Sinnoh Gym Gauntlet",
        "region": "Sinnoh",
        "generation": 4,
        "description": "Roark through Champion Cynthia with canonical Sinnoh story teams.",
        "reference": "https://bulbapedia.bulbagarden.net/wiki/Sinnoh_Gym_Leaders",
        "stages": (
            (
                "roark",
                "Roark",
                "Oreburgh Gym Leader",
                "Rock",
                ("Geodude", "Onix", "Cranidos"),
            ),
            (
                "gardenia",
                "Gardenia",
                "Eterna Gym Leader",
                "Grass",
                ("Turtwig", "Cherrim", "Roserade"),
            ),
            (
                "maylene",
                "Maylene",
                "Veilstone Gym Leader",
                "Fighting",
                ("Meditite", "Machoke", "Lucario"),
            ),
            (
                "wake",
                "Wake",
                "Pastoria Gym Leader",
                "Water",
                ("Gyarados", "Quagsire", "Floatzel"),
            ),
            (
                "fantina",
                "Fantina",
                "Hearthome Gym Leader",
                "Ghost",
                ("Duskull", "Haunter", "Mismagius"),
            ),
            (
                "byron",
                "Byron",
                "Canalave Gym Leader",
                "Steel",
                ("Bronzor", "Steelix", "Bastiodon"),
            ),
            (
                "candice",
                "Candice",
                "Snowpoint Gym Leader",
                "Ice",
                ("Snover", "Sneasel", "Medicham", "Abomasnow"),
            ),
            (
                "volkner",
                "Volkner",
                "Sunyshore Gym Leader",
                "Electric",
                ("Raichu", "Ambipom", "Octillery", "Luxray"),
            ),
            (
                "aaron",
                "Aaron",
                "Elite Four",
                "Bug",
                ("Dustox", "Beautifly", "Vespiquen", "Heracross", "Drapion"),
            ),
            (
                "bertha",
                "Bertha",
                "Elite Four",
                "Ground",
                ("Quagsire", "Hippowdon", "Golem", "Whiscash", "Rhyperior"),
            ),
            (
                "flint",
                "Flint",
                "Elite Four",
                "Fire",
                ("Rapidash", "Steelix", "Drifblim", "Lopunny", "Infernape"),
            ),
            (
                "lucian",
                "Lucian",
                "Elite Four",
                "Psychic",
                ("Mr. Mime", "Girafarig", "Medicham", "Alakazam", "Bronzong"),
            ),
            (
                "cynthia",
                "Cynthia",
                "Champion",
                "Mixed",
                ("Spiritomb", "Roserade", "Togekiss", "Lucario", "Milotic", "Garchomp"),
            ),
        ),
    },
    {
        "id": "unova-gym-gauntlet",
        "name": "Unova Gym Gauntlet",
        "region": "Unova",
        "generation": 5,
        "description": "The Unova Gym Leaders, Elite Four and Champion Alder with canonical story teams.",
        "reference": "https://bulbapedia.bulbagarden.net/wiki/Unova_Gym_Leaders",
        "stages": (
            (
                "striaton",
                "Striaton Trio",
                "Striaton Gym Leaders",
                "Starter Type",
                ("Pansage", "Pansear", "Panpour"),
            ),
            (
                "lenora",
                "Lenora",
                "Nacrene Gym Leader",
                "Normal",
                ("Herdier", "Watchog"),
            ),
            (
                "burgh",
                "Burgh",
                "Castelia Gym Leader",
                "Bug",
                ("Swadloon", "Dwebble", "Leavanny"),
            ),
            (
                "elesa",
                "Elesa",
                "Nimbasa Gym Leader",
                "Electric",
                ("Emolga", "Emolga", "Zebstrika", "Zebstrika"),
            ),
            (
                "clay",
                "Clay",
                "Driftveil Gym Leader",
                "Ground",
                ("Krokorok", "Excadrill", "Palpitoad"),
            ),
            (
                "skyla",
                "Skyla",
                "Mistralton Gym Leader",
                "Flying",
                ("Swoobat", "Unfezant", "Swanna"),
            ),
            (
                "brycen",
                "Brycen",
                "Icirrus Gym Leader",
                "Ice",
                ("Vanillish", "Cryogonal", "Beartic"),
            ),
            (
                "drayden",
                "Drayden",
                "Opelucid Gym Leader",
                "Dragon",
                ("Fraxure", "Druddigon", "Haxorus"),
            ),
            (
                "shauntal",
                "Shauntal",
                "Elite Four",
                "Ghost",
                ("Cofagrigus", "Jellicent", "Golurk", "Chandelure"),
            ),
            (
                "marshal",
                "Marshal",
                "Elite Four",
                "Fighting",
                ("Throh", "Sawk", "Mienshao", "Mienshao", "Conkeldurr"),
            ),
            (
                "grimsley",
                "Grimsley",
                "Elite Four",
                "Dark",
                ("Liepard", "Scrafty", "Krookodile", "Bisharp"),
            ),
            (
                "caitlin",
                "Caitlin",
                "Elite Four",
                "Psychic",
                ("Musharna", "Sigilyph", "Reuniclus", "Gothitelle"),
            ),
            (
                "alder",
                "Alder",
                "Champion",
                "Mixed",
                (
                    "Accelgor",
                    "Bouffalant",
                    "Escavalier",
                    "Volcarona",
                    "Druddigon",
                    "Braviary",
                ),
            ),
        ),
    },
    {
        "id": "kalos-gym-gauntlet",
        "name": "Kalos Gym Gauntlet",
        "region": "Kalos",
        "generation": 6,
        "description": "Viola through Champion Diantha with canonical Kalos story teams.",
        "reference": "https://bulbapedia.bulbagarden.net/wiki/Kalos_Gym_Leaders",
        "stages": (
            ("viola", "Viola", "Santalune Gym Leader", "Bug", ("Surskit", "Vivillon")),
            ("grant", "Grant", "Cyllage Gym Leader", "Rock", ("Amaura", "Tyrunt")),
            (
                "korrina",
                "Korrina",
                "Shalour Gym Leader",
                "Fighting",
                ("Mienfoo", "Machoke", "Hawlucha"),
            ),
            (
                "ramos",
                "Ramos",
                "Coumarine Gym Leader",
                "Grass",
                ("Jumpluff", "Gogoat", "Weepinbell"),
            ),
            (
                "clemont",
                "Clemont",
                "Lumiose Gym Leader",
                "Electric",
                ("Emolga", "Magneton", "Heliolisk"),
            ),
            (
                "valerie",
                "Valerie",
                "Laverre Gym Leader",
                "Fairy",
                ("Mawile", "Mr. Mime", "Sylveon"),
            ),
            (
                "olympia",
                "Olympia",
                "Anistar Gym Leader",
                "Psychic",
                ("Sigilyph", "Sigilyph", "Meowstic"),
            ),
            (
                "wulfric",
                "Wulfric",
                "Snowbelle Gym Leader",
                "Ice",
                ("Cryogonal", "Abomasnow", "Avalugg"),
            ),
            (
                "malva",
                "Malva",
                "Elite Four",
                "Fire",
                ("Pyroar", "Torkoal", "Chandelure", "Talonflame"),
            ),
            (
                "wikstrom",
                "Wikstrom",
                "Elite Four",
                "Steel",
                ("Klefki", "Probopass", "Scizor", "Aegislash"),
            ),
            (
                "drasna",
                "Drasna",
                "Elite Four",
                "Dragon",
                ("Dragalge", "Druddigon", "Altaria", "Noivern"),
            ),
            (
                "siebold",
                "Siebold",
                "Elite Four",
                "Water",
                ("Clawitzer", "Gyarados", "Starmie", "Barbaracle"),
            ),
            (
                "diantha",
                "Diantha",
                "Champion",
                "Mixed",
                (
                    "Hawlucha",
                    "Tyrantrum",
                    "Gourgeist",
                    "Goodra",
                    "Aurorus",
                    "Gardevoir",
                ),
            ),
        ),
    },
    {
        "id": "alola-trial-gauntlet",
        "name": "Alola Grand Trial Gauntlet",
        "region": "Alola",
        "generation": 7,
        "description": "Alola's four Grand Trials, Elite Four and Champion Kukui.",
        "reference": "https://bulbapedia.bulbagarden.net/wiki/Alola_Grand_Trials",
        "stages": (
            (
                "hala-trial",
                "Hala",
                "Melemele Grand Trial",
                "Fighting",
                ("Machoke", "Makuhita", "Crabrawler"),
            ),
            (
                "olivia-trial",
                "Olivia",
                "Akala Grand Trial",
                "Rock",
                ("Anorith", "Lileep", "Lycanroc"),
            ),
            (
                "nanu-trial",
                "Nanu",
                "Ulaula Grand Trial",
                "Dark",
                ("Sableye", "Krokorok", "Persian"),
            ),
            (
                "hapus-trial",
                "Hapu",
                "Poni Grand Trial",
                "Ground",
                ("Dugtrio", "Mudsdale", "Flygon"),
            ),
            (
                "hala-elite",
                "Hala",
                "Elite Four",
                "Fighting",
                ("Hariyama", "Poliwrath", "Bewear", " crabrawler"),
            ),
            (
                "olivia-elite",
                "Olivia",
                "Elite Four",
                "Rock",
                ("Relicanth", "Carbink", "Probopass", "Lycanroc"),
            ),
            (
                "acerola-elite",
                "Acerola",
                "Elite Four",
                "Ghost",
                ("Sableye", "Drifblim", "Dhelmise", "Palossand"),
            ),
            (
                "kahili-elite",
                "Kahili",
                "Elite Four",
                "Flying",
                ("Skarmory", "Crobat", "Oricorio", "Toucannon"),
            ),
            (
                "kukui",
                "Kukui",
                "Champion",
                "Mixed",
                (
                    "Lycanroc",
                    "Ninetales",
                    "Braviary",
                    "Snorlax",
                    "Magnezone",
                    "Incineroar",
                ),
            ),
        ),
    },
    {
        "id": "galar-gym-gauntlet",
        "name": "Galar Gym Gauntlet",
        "region": "Galar",
        "generation": 8,
        "description": "The Galar Gym Leaders and Champion Leon with canonical Sword story teams.",
        "reference": "https://bulbapedia.bulbagarden.net/wiki/Galar_Gym_Leaders",
        "stages": (
            (
                "milo",
                "Milo",
                "Turffield Gym Leader",
                "Grass",
                ("Gossifleur", "Eldegoss"),
            ),
            (
                "nessa",
                "Nessa",
                "Hulbury Gym Leader",
                "Water",
                ("Goldeen", "Arrokuda", "Drednaw"),
            ),
            (
                "kabu",
                "Kabu",
                "Motostoke Gym Leader",
                "Fire",
                ("Ninetales", "Arcanine", "Centiskorch"),
            ),
            (
                "bea",
                "Bea",
                "Stow-on-Side Gym Leader",
                "Fighting",
                ("Hitmontop", "Pangoro", "Sirfetch'd", "Machamp"),
            ),
            (
                "allister",
                "Allister",
                "Stow-on-Side Gym Leader",
                "Ghost",
                ("Yamask", "Mimikyu", "Cursola", "Gengar"),
            ),
            (
                "opal",
                "Opal",
                "Ballonlea Gym Leader",
                "Fairy",
                ("Weezing", "Mawile", "Togekiss", "Alcremie"),
            ),
            (
                "gordie",
                "Gordie",
                "Circhester Gym Leader",
                "Rock",
                ("Barbaracle", "Shuckle", "Stonjourner", "Coalossal"),
            ),
            (
                "piers",
                "Piers",
                "Spikemuth Gym Leader",
                "Dark",
                ("Scrafty", "Malamar", "Skuntank", "Obstagoon"),
            ),
            (
                "raihan",
                "Raihan",
                "Hammerlocke Gym Leader",
                "Dragon",
                ("Gigalith", "Flygon", "Sandaconda", "Duraludon"),
            ),
            (
                "leon",
                "Leon",
                "Champion",
                "Mixed",
                (
                    "Aegislash",
                    "Dragapult",
                    "Haxorus",
                    "Seismitoad",
                    "Mr. Rime",
                    "Charizard",
                ),
            ),
        ),
    },
    {
        "id": "paldea-gym-gauntlet",
        "name": "Paldea Gym Gauntlet",
        "region": "Paldea",
        "generation": 9,
        "description": "Paldea's eight Gym Leaders, Elite Four and Champion Geeta.",
        "reference": "https://bulbapedia.bulbagarden.net/wiki/Paldea_Gym_Leaders",
        "stages": (
            (
                "katy",
                "Katy",
                "Cortondo Gym Leader",
                "Bug",
                ("Nymble", "Tarountula", "Teddiursa"),
            ),
            (
                "brassius",
                "Brassius",
                "Artazon Gym Leader",
                "Grass",
                ("Petilil", "Smoliv", "Sudowoodo"),
            ),
            (
                "iono",
                "Iono",
                "Levincia Gym Leader",
                "Electric",
                ("Wattrel", "Bellibolt", "Luxio", "Mismagius"),
            ),
            (
                "kofu",
                "Kofu",
                "Cascarrafa Gym Leader",
                "Water",
                ("Veluza", "Wugtrio", "Crabominable"),
            ),
            (
                "larry",
                "Larry",
                "Medali Gym Leader",
                "Normal",
                ("Komala", "Dudunsparce", "Staraptor"),
            ),
            (
                "ryme",
                "Ryme",
                "Montenevera Gym Leader",
                "Ghost",
                ("Mimikyu", "Banette", "Houndstone", "Toxtricity"),
            ),
            (
                "tulip",
                "Tulip",
                "Alfornada Gym Leader",
                "Psychic",
                ("Farigiraf", "Gardevoir", "Espathra", "Florges"),
            ),
            (
                "grusha",
                "Grusha",
                "Glaseado Gym Leader",
                "Ice",
                ("Frosmoth", "Beartic", "Cetitan", "Altaria"),
            ),
            (
                "rika",
                "Rika",
                "Elite Four",
                "Ground",
                ("Whiscash", "Camerupt", "Donphan", "Clodsire"),
            ),
            (
                "poppy",
                "Poppy",
                "Elite Four",
                "Steel",
                ("Copperajah", "Magnezone", "Bronzong", "Tinkaton"),
            ),
            (
                "larry-elite",
                "Larry",
                "Elite Four",
                "Flying",
                ("Tropius", "Staraptor", "Oricorio", "Flamigo"),
            ),
            (
                "hassel",
                "Hassel",
                "Elite Four",
                "Dragon",
                ("Noivern", "Dragalge", "Flapple", "Haxorus"),
            ),
            (
                "geeta",
                "Geeta",
                "Champion",
                "Mixed",
                ("Espathra", "Avalugg", "Kingambit", "Veluza", "Gogoat", "Glimmora"),
            ),
        ),
    },
)

FILLED_RESERVES: dict[str, tuple[str, ...]] = {
    "Bug": ("Heracross", "Scizor", "Volcarona", "Ribombee", "Forretress"),
    "Dark": ("Umbreon", "Houndoom", "Bisharp", "Krookodile", "Grimmsnarl", "Kingambit"),
    "Dragon": ("Dragonite", "Salamence", "Garchomp", "Haxorus", "Goodra", "Baxcalibur"),
    "Electric": ("Jolteon", "Electivire", "Magnezone", "Rotom", "Pawmot"),
    "Fairy": ("Azumarill", "Gardevoir", "Mawile", "Grimmsnarl", "Togekiss", "Tinkaton"),
    "Fighting": ("Machamp", "Hariyama", "Lucario", "Mienshao", "Bewear", "Hawlucha"),
    "Fire": (
        "Arcanine",
        "Magmortar",
        "Chandelure",
        "Volcarona",
        "Torkoal",
        "Skeledirge",
    ),
    "Flying": (
        "Crobat",
        "Skarmory",
        "Togekiss",
        "Gliscor",
        "Corviknight",
        "Kilowattrel",
    ),
    "Ghost": ("Gengar", "Chandelure", "Mimikyu", "Banette", "Dragapult", "Houndstone"),
    "Grass": (
        "Venusaur",
        "Roserade",
        "Breloom",
        "Lilligant",
        "Tsareena",
        "Meowscarada",
    ),
    "Ground": ("Golem", "Hippowdon", "Flygon", "Krookodile", "Mudsdale", "Clodsire"),
    "Ice": ("Lapras", "Mamoswine", "Weavile", "Froslass", "Baxcalibur", "Cetitan"),
    "Normal": ("Snorlax", "Porygon2", "Tauros", "Indeedee", "Dubwool", "Dudunsparce"),
    "Poison": ("Crobat", "Muk", "Toxapex", "Drapion", "Gengar", "Glimmora"),
    "Psychic": (
        "Alakazam",
        "Espeon",
        "Metagross",
        "Gardevoir",
        "Reuniclus",
        "Hatterene",
    ),
    "Rock": ("Golem", "Rhyperior", "Tyranitar", "Lycanroc", "Coalossal", "Garganacl"),
    "Steel": (
        "Metagross",
        "Scizor",
        "Excadrill",
        "Corviknight",
        "Copperajah",
        "Tinkaton",
    ),
    "Water": ("Gyarados", "Lapras", "Ludicolo", "Milotic", "Floatzel", "Palafin"),
    "Mixed": (
        "Arcanine",
        "Gardevoir",
        "Metagross",
        "Garchomp",
        "Volcarona",
        "Tyranitar",
    ),
    "Starter Type": (
        "Pansage",
        "Pansear",
        "Panpour",
        "Simisage",
        "Simisear",
        "Simipour",
    ),
}


def _block(species: str, level: int) -> str:
    return f"{species.strip()}\nLevel: {level}"


def _stage(
    stage: tuple[object, ...], index: int, total: int, region: str
) -> dict[str, object]:
    stage_id, name, title, specialty, species = stage
    assert isinstance(stage_id, str)
    assert isinstance(name, str)
    assert isinstance(title, str)
    assert isinstance(specialty, str)
    roster = tuple(str(item).strip() for item in species if str(item).strip())
    level = round(10 + (90 * index / max(1, total - 1)))
    reserve = tuple(dict.fromkeys(roster))
    # Filled mode keeps the leader's known roster first and adds themed reserve species
    # only where the story team is smaller than six.  The exact source roster remains the
    # default/original mode and is never silently replaced.
    filled = list(reserve)
    for candidate in FILLED_RESERVES.get(specialty, FILLED_RESERVES["Mixed"]):
        if len(filled) >= 6:
            break
        if candidate not in filled:
            filled.append(candidate)
    if reserve:
        cursor = 0
        while len(filled) < 6:
            candidate = reserve[cursor % len(reserve)]
            if candidate not in filled or len(reserve) == 1:
                filled.append(candidate)
            cursor += 1
    return {
        "id": stage_id,
        "name": name,
        "title": title,
        "theme": specialty.lower(),
        "level": level,
        "specialty": specialty,
        "visual_accent": "#7bf0a2",
        "full_heal_before": True,
        "opponent_team": "\n\n".join(_block(item, level) for item in roster),
        "filled_opponent_team": "\n\n".join(_block(item, level) for item in filled),
        "trainer_asset_id": None,
    }


def _definition(region: dict[str, object]) -> dict[str, object]:
    stages = tuple(region["stages"])  # type: ignore[arg-type]
    stage_rows = [
        _stage(item, index, len(stages), str(region["region"]))
        for index, item in enumerate(stages)
    ]
    for index, row in enumerate(stage_rows):
        title = str(row["title"])
        previous_title = str(stage_rows[index - 1]["title"]) if index else ""
        gauntlet_stage = "Elite Four" in title or "Champion" in title
        previous_gauntlet_stage = (
            "Elite Four" in previous_title or "Champion" in previous_title
        )
        row["full_heal_before"] = not (gauntlet_stage and previous_gauntlet_stage)
    return {
        "id": region["id"],
        "version": "1.0.0",
        "name": region["name"],
        "description": region["description"],
        "format": "gen9natdexdraft",
        "region": region["region"],
        "generation": region["generation"],
        "campaign_kind": "regional",
        "stage_count_label": f"{len(stages)} story stages",
        "mechanics_assumptions": [
            "Canonical story-mode species and order are preserved in Original teams mode",
            "The pinned Gen 9 NatDex Draft validator supplies legal modern move and ability details",
            "Regional campaign levels are normalized to the shared 10-to-100 progression",
        ],
        "source": {
            "game": f"Pokémon {region['region']} story campaign",
            "generation": region["generation"],
            "variant": "Canonical Gym/Trial, Elite Four and Champion story rosters",
            "references": [region["reference"]],
            "compatibility_note": "Story rosters are presented in the current NatDex Draft battle format.",
        },
        "draft_rules": {
            "roster_size": 6,
            "rerolls": 3,
            "type_rerolls": 1,
            "generation_rerolls": 1,
            "choice_count": 3,
            "species_clause": True,
            "draft_pool_mode": "all-forms",
        },
        "training_rules": {"per_pokemon_max": 510, "per_stat_max": 252},
        "stages": stage_rows,
    }


def main() -> None:
    CONTENT.mkdir(parents=True, exist_ok=True)
    definitions = [_definition(region) for region in REGIONS]
    for definition in definitions:
        path = CONTENT / f"{definition['id']}.json"
        path.write_text(
            json.dumps(definition, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    kanto = json.loads(
        (CONTENT / "kanto-gym-gauntlet.json").read_text(encoding="utf-8")
    )
    stages: list[dict[str, object]] = []
    for definition in [kanto, *definitions]:
        for stage in definition["stages"]:
            copied = dict(stage)
            copied["id"] = (
                f"{definition['id'].removesuffix('-gym-gauntlet')}-{stage['id']}"
            )
            stages.append(copied)
    combined = dict(kanto)
    combined.update(
        {
            "id": "all-generations-gauntlet",
            "version": "1.0.0",
            "name": "All Generations Gauntlet",
            "description": "One persistent draft through every regional Gym, Trial, Elite Four and Champion campaign.",
            "region": "All regions",
            "generation": 1,
            "campaign_kind": "multi-generation",
            "stage_count_label": f"{len(stages)} stages · Gen I–IX",
            "source": {
                "game": "Pokémon mainline regional campaigns",
                "generation": 1,
                "variant": "Kanto, Johto, Hoenn, Sinnoh, Unova, Kalos, Alola, Galar and Paldea",
                "references": ["https://bulbapedia.bulbagarden.net/wiki/Gym_Leader"],
                "compatibility_note": "Each regional section keeps its canonical story roster and heals at its own first stage.",
            },
            "stages": stages,
        }
    )
    (CONTENT / "all-generations-gauntlet.json").write_text(
        json.dumps(combined, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
