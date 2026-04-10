#!/usr/bin/env python3
"""
Final comprehensive auto-fill for all remaining tracks.
"""

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
MAPPINGS_FILE = BASE_DIR / "files" / "track_assignments.csv"

# Final comprehensive knowledge base
FINAL_ALBUMS = {
    # From the remaining list
    ("Dee Lite", "Groove Is in the Heart"): "World Clique",
    ("Tlc", "Waterfalls"): "CrazySexyCool",
    ("Beck", "Loser"): "Mellow Gold",
    ("Inxs", "I Need You Tonight"): "Kick",
    ("Rednex", "Wish You Were Here"): "Sex & Violins",
    ("Cyndi Lauper", "Girls Just Wanna Have Fun"): "She's So Unusual",
    ("Die Aerzte", "Maenner Sind Schweine"): "Die Aerzte",
    ("Enigma", "Sadeness (Part 1)"): "MCMXC a.D.",
    ("Joan Jett", "I Love Rock and Roll"): "I Love Rock 'n Roll",
    ("John Farnham", "You're the Voice"): "Age of Reason",
    ("Mc Hammer", "U Can't Touch This"): "Please Hammer Don't Hurt 'Em",
    ("Meatloaf", "I Would Do Anything for Love"): "Bat Out of Hell II",
    ("Nick Cave & the Bad Seeds", "Where the Wild Roses Grow"): "Murder Ballads",
    ("Ofra Haza", "Im Nin Alu"): "Shaday",
    ("Orchestral Manoeuvres in the Dark", "Sailing on the Seven Seas"): "Sugar Tax",
    ("Pet Shop Boys", "Go West"): "Very",
    ("Peter Gabriel", "Sledgehammer"): "So",
    ("Queen", "A Kind of Magic"): "A Kind of Magic",
    ("Queen", "Flash"): "Flash Gordon",
    ("Rammstein", "Engel"): "Sehnsucht",
    ("Ricky Martin", "The Cup of Life"): "Vuelve",
    ("Salt-N-Pepa", "Push It"): "Hot, Cool & Vicious",
    ("Simple Minds", "Dont You Forget About Me"): "The Breakfast Club",
    ("Simply Red", "Holding Back the Years"): "Picture Book",
    ("Snap", "The Power"): "World Power",
    ("Suzanne Vega", "Luka"): "Solitude Standing",
    ("Tears for Fears", "Shout"): "Songs from the Big Chair",
    ("The Buggles", "Video Killed the Radio Star"): "The Age of Plastic",
    ("The Connells", "'74-'75"): "Ring",
    ("The Police", "Every Little Thing She Does"): "Synchronicity",
    ("Tight Fit", "The Lion Sleeps Tonight"): "Tight Fit",
    ("UB40", "Kingston Town"): "Labour of Love II",
    ("Wet Wet Wet", "Love Is All Around"): "Four Weddings and a Funeral",
    ("Whitney Houston", "My Love Is Your Love"): "My Love Is Your Love",
    ("4 Non Blondes", "What's Up"): "Bigger, Better, Faster, More!",
    ("Aerosmith", "Cryin"): "Get a Grip",
    ("Babylon Zoo", "Spaceman"): "The Boy with the X-Ray Eyes",
    ("Backstreet Boys", "We've Got It Going On"): "Backstreet Boys",
    ("Bon Jovi", "Always"): "Cross Road",
    ("Bryan Adams", "Everything I Do"): "Waking Up the Neighbours",
    ("Crash Test Dummies", "Mmm Mmm Mmm Mmm"): "God Shuffles His Feet",
    ("Culture Club", "Do You Really Want to Hurt Me"): "Kissing to Be Clever",
    ("David Bowie", "Let's Dance"): "Let's Dance",
    ("David Bowie and Mick Jagger", "Dancing in the Street"): "Dancing in the Street",
    ("David Lee Roth", "Just a Gigolo"): "Crazy from the Heat",
    ("Dexy's Midnight Runners", "Come on Eileen"): "Too-Rye-Ay",
    ("Die Fantastischen Vier", "Mfg"): "4 Gewinnt",
    ("Die Toten Hosen", "Zehn Kleine Jaegermeister"): "Opium fürs Volk",
    ("Die Aerzte", "Ein Song Namens Schunder"): "Die Bestie in Menschengestalt",
    ("Die Aerzte", "Schrei Nach Liebe"): "Die Bestie in Menschengestalt",
    ("Dr. Alban", "It's My Life"): "It's My Life",
    ("Extreme", "More Than Words"): "Pornograffitti",
    ("Falco", "Der Kommissar"): "Einzelhaft",
    ("Foreigner", "Waiting for a Girl Like You"): "4",
    ("Freddie Mercury", "Living on My Own"): "Mr. Bad Guy",
    ("Freundeskreis", "Mit Dir"): "Quadratur des Kreises",
    ("George Michael", "I Want Your Sex"): "Faith",
    ("Guano Apes", "Open Your Eyes"): "Proud Like a God",
    ("Herbert Grönemeyer", "Bleibt Alles Anders"): "Chaos",
    ("Herbert Grönemeyer", "Was Soll Das"): "So gut",
    ("Human League", "Don't You Want Me"): "Dare",
    ("Inner Circle", "Sweat (A La La La La Long)"): "Bad Boys",
    ("Jennifer Lopez", "If You Had My Love"): "On the 6",
    ("London Beat", "I've Been Thinking About You"): "London Beat",
    ("Madonna", "Frozen"): "Ray of Light",
    ("Madonna", "La Isla Bonita"): "True Blue",
    ("Mariah Carey", "Without You"): "Music Box",
    ("Melanie C", "I Turn to You"): "Northern Star",
    ("Men at Work", "Land Downunder"): "Business as Usual",
    ("Michael Jackson", "Bad"): "Bad",
    ("Michael Jackson", "Black or White"): "Dangerous",
    ("Michael Jackson", "Dirty Diana"): "Bad",
    ("Michael Jackson", "Thriller"): "Thriller",
    ("Michael Jackson", "Beat It"): "Thriller",
    ("Michael Jackson", "Billie Jean"): "Thriller",
    ("Milli Vanilli", "Girl You Know It's True"): "Girl You Know It's True",
    ("New Kids on the Block", "Hangin' Tough"): "Hangin' Tough",
    ("Orchestral Manoeuvres in the Dark", "Maid of Orleans"): "Architecture & Morality",
    ("Pet Shop Boys", "It's a Sin"): "Actually",
    ("Peter Schilling", "Major Tom"): "Error in the System",
    ("Phil Collins", "In the Air Tonight"): "Face Value",
    ("Pras Michael Feat. Mya", "Ghetto Supastar"): "Ghetto Supastar",
    ("Roxette", "Must Have Been Love"): "Pretty Woman",
    ("Run Dmc & Aerosmith", "Walk This Way"): "Raising Hell",
    ("Sabrina Setlur", "Du Liebst Mich Nicht"): "Die neue Esprit",
    ("Simple Minds", "Belfast Child"): "Street Fighting Years",
    ("Simply Red", "Something Got Me Started"): "Stars",
    ("Sinead O'Connor", "Nothing Compares to You"): "I Do Not Want What I Haven't Got",
    ("Snap", "Rythm Is a Dancer"): "The Madman's Return",
    ("Spice Girls", "Wannabe"): "Spice",
    ("Stevie Wonder", "I Just Called to Say I Love You"): "The Woman in Red",
    ("Survivor", "Eye of the Tiger"): "Rocky III",
    ("Suzanne Vega & Dna", "Tom's Diner"): "Solitude Standing",
    ("Talking Heads", "Burning Down the House"): "Speaking in Tongues",
    ("Tanita Tikaram", "Twist in My Sobriety"): "Ancient Heart",
    ("The Cardigans", "Love Fool"): "First Band on the Moon",
    ("Tom Jones with Mousse T", "Sexbomb"): "Reload",
    ("Toni Braxton", "Unbreak My Heart"): "Secrets",
    ("U2", "I Still Haven't Found"): "The Joshua Tree",
    ("Ub40", "Red Red Wine"): "Labour of Love",
    ("Ugly Kid Joe", "Cats in the Craddle"): "America's Least Wanted",
    ("Usa for Africa", "We Are the World"): "We Are the World",
    ("Vanilla Ice", "Ice Ice Baby"): "To the Extreme",
    ("Whitney Houston", "One Moment in Time"): "1988 Summer Olympics",
    ("Will Smith", "Men in Black"): "Men in Black",
    ("Witt & Heppner", "Die Flut"): "Weltfrieden",
    ("Xavier Naidoo", "Sie Siet Mich Nicht"): "Nicht von dieser Welt",

    # Additional well-known tracks
    ("ABBA", "Dancing Queen"): "Arrival",
    ("ABBA", "Mamma Mia"): "ABBA",
    ("ABBA", "Fernando"): "Arrival",
    ("Beatles", "Hey Jude"): "Hey Jude",
    ("Beatles", "Let It Be"): "Let It Be",
    ("Beatles", "Come Together"): "Abbey Road",
    ("Bob Marley", "No Woman No Cry"): "Natty Dread",
    ("Bob Marley", "Three Little Birds"): "Exodus",
    ("Bob Marley", "One Love"): "Exodus",
    ("Elton John", "Rocket Man"): "Honky Château",
    ("Elton John", "Candle in the Wind"): "Goodbye Yellow Brick Road",
    ("Elton John", "Your Song"): "Elton John",
    ("Elton John", "Sacrifice"): "Sleeping with the Past",
    ("Fleetwood Mac", "Go Your Own Way"): "Rumours",
    ("Fleetwood Mac", "Dreams"): "Rumours",
    ("Fleetwood Mac", "Don't Stop"): "Rumours",
    ("Abba", "Dancing Queen"): "Arrival",
    ("Abba", "Knowing Me Knowing You"): "Arrival",
    ("Abba", "Take a Chance on Me"): "Abba",
    ("Elton John", "I Guess That's Why They Call It the Blues"): "Too Low for Zero",
    ("Elton John", "I'm Still Standing"): "Too Low for Zero",
    ("Rod Stewart", "Maggie May"): "Every Picture Tells a Story",
    ("Rod Stewart", "Do Ya Think I'm Sexy?"): "Blondes Have More Fun",
    ("Rod Stewart", "Sailing"): "Atlantic Crossing",
    ("Cat Stevens", "Morning Has Broken"): "Teaser and the Firecat",
    ("Cat Stevens", "Wild World"): "Tea for the Tillerman",
    ("Simon & Garfunkel", "Bridge over Troubled Water"): "Bridge over Troubled Water",
    ("Simon & Garfunkel", "The Sound of Silence"): "Sounds of Silence",
    ("Simon & Garfunkel", "Mrs. Robinson"): "Bookends",
    ("Police", "Every Breath You Take"): "Synchronicity",
    ("Police", "King of Pain"): "Synchronicity",
    ("Police", "Wrapped Around Your Finger"): "Synchronicity",
}


def normalize_for_matching(text: str) -> str:
    """Simple normalization for matching."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def auto_fill_final():
    """Final comprehensive auto-fill."""
    if not MAPPINGS_FILE.exists():
        print(f"Error: {MAPPINGS_FILE} not found.")
        return

    filled = 0
    with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    output_lines = []
    for line in lines:
        if line.startswith('#') or not line.strip():
            output_lines.append(line)
            continue

        parts = line.strip().split(',')
        if len(parts) < 3:
            output_lines.append(line)
            continue

        artist = parts[0].strip()
        track = parts[1].strip()
        target_album = parts[2].strip() if len(parts) > 2 else ""

        if target_album:
            output_lines.append(line)
            continue

        # Try exact match
        key = (artist, track)
        if key in FINAL_ALBUMS:
            output_lines.append(f"{artist},{track},{FINAL_ALBUMS[key]}\n")
            filled += 1
            print(f"✓ {artist}: {track} → {FINAL_ALBUMS[key]}")
            continue

        # Try fuzzy match
        norm_track = normalize_for_matching(track)
        for (kb_artist, kb_track), album in FINAL_ALBUMS.items():
            if (artist == kb_artist and
                normalize_for_matching(kb_track) == norm_track):
                output_lines.append(f"{artist},{track},{album}\n")
                filled += 1
                print(f"~ {artist}: {track} → {album} (fuzzy)")
                break
        else:
            output_lines.append(line)

    # Write back
    with open(MAPPINGS_FILE, 'w', encoding='utf-8') as f:
        f.writelines(output_lines)

    print(f"\nAuto-filled: {filled}")


if __name__ == "__main__":
    auto_fill_final()
