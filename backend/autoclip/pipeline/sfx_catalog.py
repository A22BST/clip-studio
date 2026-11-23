"""Editable local sound catalogue. Names match asset basenames exactly."""

# category, use when, avoid when
CATALOG = {
    "BONE CRACK": ("IMPACT", "being hit, falls, crashes, deaths", "quiet discoveries or dialogue"),
    "Boom": ("IMPACT", "explosions, crashes, shocking payoff", "small dialogue beats"),
    "Bang": ("IMPACT", "shots, hits, jump scares", "quiet discoveries"),
    "FAH": ("FAIL", "clear blunder or absurd payoff", "serious or sad moments"),
    "MEME BOOM": ("FAIL", "obviously comedic fail only", "ordinary surprises, serious or sad moments"),
    "ROBLOX": ("FAIL", "comedic oh-no or blunder", "serious or sad moments"),
    "SPONGEBOB": ("FAIL", "deadpan funny payoff", "serious or sad moments"),
    "AMONG US": ("FAIL", "absurd or suspicious comedic payoff", "serious or sad moments"),
    "MAGIC REVEAL": ("REVEAL", "finding, unveiling, discovery", "hits or dialogue"),
    "GLITTER": ("REVEAL", "discovery or unveiling", "hits or dialogue"),
    "Intro sound (correct)": ("REVEAL", "discovery or reveal", "unrelated opening"),
    "CHA CHING": ("MONEY", "money, rewards, big wins", "ordinary discoveries"),
    "DING": ("NOTIFICATION", "chat, comments, messages, tech", "crashes"),
    "DISCORD NOTIFICATION": ("NOTIFICATION", "chat or messages", "crashes"),
    "CLICK": ("NOTIFICATION", "tech, chat reading", "crashes"),
    "KEYBOARD TYPING": ("NOTIFICATION", "typing or chat", "crashes"),
    "Pop": ("SPOTLIGHT", "small clear beat or quick punchline", "no identifiable payoff"),
    "Camera flash": ("SPOTLIGHT", "caught or quick punchline", "no identifiable payoff"),
    "PEW": ("SPOTLIGHT", "small action beat", "serious or sad moments"),
    "CORE": ("SPOTLIGHT", "small clear emphasis beat", "no identifiable payoff"),
    "RISER": ("BUILD-UP", "build-up ending at payoff, kind riser", "impact placement"),
    "Riser (1)": ("BUILD-UP", "build-up ending at payoff, kind riser", "impact placement"),
    "Riser 2": ("BUILD-UP", "build-up ending at payoff, kind riser", "impact placement"),
    "RIZZ": ("AWKWARD", "explicit flirt, awkward or cringe beat", "serious or sad moments"),
    "PIANO MEME": ("AWKWARD", "explicit awkward, cringe, theatrical dramatic beat", "serious or genuinely sad moments"),
}

# Phrase matching uses word boundaries, so e.g. 'shot' does not match 'screenshot'.
KEYWORDS = {
    "IMPACT": ("kill", "killed", "died", "death", "wasted", "crash", "crashed", "shot",
               "shooting", "explode", "exploded", "explosion", "mauled", "fell", "hit", "shark attack", "jump scare"),
    "REVEAL": ("found", "discovered", "discovery", "secret", "reveal", "revealed", "unveils"),
    "MONEY": ("money", "million", "cash", "payout", "reward", "jackpot", "big win"),
    "NOTIFICATION": ("chat", "comment", "comments", "donation", "message", "messages", "typing"),
    "FAIL": ("did not expect", "funny", "lol", "fail", "failed", "oops", "what the", "oh no", "absurd", "blunder", "roaches"),
    "SPOTLIGHT": ("caught", "punchline", "heist", "pulls off", "succeeds", "i did it"),
    "AWKWARD": ("flirt", "flirting", "awkward", "cringe", "rizz", "theatrical drama", "dramatic-sad"),
}
COMEDIC = ("funny", "lol", "fail", "failed", "oops", "absurd", "blunder", "comedic")
SERIOUS = ("serious", "tragic", "tragedy", "grief", "mourning", "sad", "sadness", "heartbroken", "real death", "real-life death")
