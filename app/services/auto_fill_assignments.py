#!/usr/bin/env python3
"""
Auto-fill common albums for compilation tracks.
Uses a knowledge base of well-known tracks and their original albums.
"""

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
MAPPINGS_FILE = BASE_DIR / "files" / "track_assignments.csv"

# Knowledge base of common tracks and their original albums
COMMON_ALBUMS = {
    # Soundtracks
    ("Berlin", "Take My Breath Away"): "Top Gun - Motion Picture Soundtrack",
    ("Jan Hammer", "Crockett's Theme from Miami Vice"): "Miami Vice",
    ("Harold Faltermeyer", "Axel F"): "Beverly Hills Cop",
    ("Irene Cara", "Flashdance... What a Feeling"): "Flashdance",
    ("Irene Cara", "Fame"): "Fame",
    ("Kenny Loggins", "Footloose"): "Footloose",
    ("Phil Collins", "Against All Odds"): "Against All Odds",
    ("Ray Parker Jr.", "Ghostbusters"): "Ghostbusters",
    ("Dire Straits", "Money for Nothing"): "Brothers in Arms",

    # 80s Pop/Rock
    ("A-HA", "The Sun Always Shines on Tv"): "Hunting High and Low",
    ("A-HA", "Take on Me"): "Hunting High and Low",
    ("Alphaville", "Big in Japan"): "Forever Young",
    ("Alphaville", "Sounds Like a Melody"): "Forever Young",
    ("Level 42", "Lessons in Love"): "Running in the Family",
    ("Level 42", "Something About You"): "The Promise of Love",
    ("The Bangles", "Manic Monday"): "Different Light",
    ("The Bangles", "Walk Like an Egyptian"): "Different Light",
    ("The Bangles", "Eternal Flame"): "Everything",
    ("Belinda Carlisle", "Heaven Is a Place on Earth"): "Heaven on Earth",
    ("Belinda Carlisle", "Leave a Light On"): "Runaway Horses",
    ("Cher", "If I Could Turn Back Time"): "Heart of Stone",
    ("Cher", "Believe"): "Believe",
    ("Cher", "It's in His Kiss (The Shoop Shoop Song)"): "Mermaids",
    ("Cyndi Lauper", "Girls Just Want to Have Fun"): "She's So Unusual",
    ("Cyndi Lauper", "Time After Time"): "She's So Unusual",
    ("Madonna", "Papa Don't Preach"): "True Blue",
    ("Madonna", "Like a Prayer"): "Like a Prayer",
    ("Madonna", "Crazy for You"): "Vision Quest",
    ("Madonna", "Into the Groove"): "Desperately Seeking Susan",
    ("Madonna", "Live to Tell"): "True Blue",
    ("Madonna", "Material Girl"): "Like a Virgin",
    ("Prince", "Kiss"): "Parade",
    ("Prince", "1999"): "1999",
    ("Whitney Houston", "I Will Always Love You"): "The Bodyguard",
    ("Whitney Houston", "I Wanna Dance with Somebody"): "Whitney Houston",

    # 90s Pop/Rock
    ("Allanah Myles", "Black Velvet"): "Alannah Myles",
    ("Allanah Myles", "Love Is"): "Alannah Myles",
    ("Anastacia", "I'm Outta Love"): "Not That Kind",
    ("Anastacia", "One Day in Your Life"): "Freak of Nature",
    ("Cher", "The Shoop Shoop Song"): "Mermaids",
    ("Christina Aguilera", "Genie in a Bottle"): "Genie in a Bottle",
    ("Christina Aguilera", "What a Girl Wants"): "Christina Aguilera",
    ("Deee-Lite", "Groove Is in the Heart"): "World Clique",
    ("Deep Blue Something", "Breakfast at Tiffany's"): "Home",
    ("Des'ree", "You Gotta Be"): "I Ain't Movin'",
    ("Eiffel 65", "Blue (Da Ba Dee)"): "Europop",
    ("Faithless", "God Is a Dj"): "Sunday 8PM",
    ("Faithless", "Insomnia"): "Sunday 8PM",
    ("The Cardigans", "Lovefool"): "First Band on the Moon",
    ("The Cranberries", "Zombie"): "No Need to Argue",
    ("The Cranberries", "Linger"): "Everybody Else Is Doing It",
    ("The Offspring", "Pretty Fly (For a White Guy)"): "Americana",
    ("The Offspring", "Self Esteem"): "Smash",
    ("The Prodigy", "Firestarter"): "The Fat of the Land",
    ("The Prodigy", "Breathe"): "The Fat of the Land",
    ("No Doubt", "Don't Speak"): "Tragic Kingdom",
    ("R.E.M.", "Losing My Religion"): "Out of Time",
    ("Nirvana", "Smells Like Teen Spirit"): "Nevermind",
    ("Nirvana", "Come As You Are"): "Nevermind",
    ("Radiohead", "Creep"): "Pablo Honey",

    # R&B/Hip-Hop
    ("2Pac", "California Love"): "All Eyez on Me",
    ("2Pac", "Changes"): "Greatest Hits",
    ("2Pac", "Dear Mama"): "Me Against the World",
    ("2Pac", "Hit 'Em Up"): "All Eyez on Me",
    ("Dr. Dre", "Nuthin' but a 'G' Thang"): "The Chronic",
    ("Dr. Dre", "Still D.R.E."): "2001",
    ("Snoop Dogg", "Gin and Juice"): "Doggystyle",
    ("Snoop Dogg", "What's My Name"): "Doggystyle",
    ("The Notorious B.I.G.", "Juicy"): "Ready to Die",
    ("The Notorious B.I.G.", "Big Poppa"): "Ready to Die",
    ("Fugees", "Killing Me Softly With His Song"): "The Score",
    ("Wyclef Jean", "Ghetto Supastar"): "The Carnival",
    ("Coolio", "Gangsta's Paradise"): "Gangsta's Paradise",
    ("Blackstreet", "No Diggity"): "Another Level",
    ("TLC", "Waterfalls"): "CrazySexyCool",
    ("TLC", "No Scrubs"): "FanMail",
    ("Destiny's Child", "Say My Name"): "The Writing's on the Wall",
    ("Destiny's Child", "Bootylicious"): "Survivor",
    ("Beyonce", "Crazy in Love"): "Dangerously in Love",

    # Rock/Alternative
    ("The Cure", "Friday I'm in Love"): "Wish",
    ("The Cure", "Just Like Heaven"): "Kiss Me Kiss Me Kiss Me",
    ("The Smiths", "Please Please Please Let Me Get What I Want"): "Louder Than Bombs",
    ("The Smiths", "There Is a Light That Never Goes Out"): "The Queen Is Dead",
    ("Depeche Mode", "Enjoy the Silence"): "Violator",
    ("Depeche Mode", "Personal Jesus"): "Violator",
    ("New Order", "Blue Monday"): "Power, Corruption & Lies",
    ("Pet Shop Boys", "West End Girls"): "Please",
    ("Pet Shop Boys", "Always on My Mind"): "Actually",
    ("Erasure", "A Little Respect"): "The Innocents",
    ("The Police", "Every Breath You Take"): "Synchronicity",
    ("The Police", "Roxanne"): "Outlandos d'Amour",
    ("Sting", "Englishman in New York"): "...Nothing Like the Sun",
    ("U2", "With or Without You"): "The Joshua Tree",
    ("U2", "I Still Haven't Found What I'm Looking For"): "The Joshua Tree",
    ("U2", "One"): "Achtung Baby",
    ("R.E.M.", "Everybody Hurts"): "Automatic for the People",
    ("Red Hot Chili Peppers", "Under the Bridge"): "Blood Sugar Sex Magik",
    ("Red Hot Chili Peppers", "Give It Away"): "Blood Sugar Sex Magik",
    ("Nirvana", "Come As You Are"): "Nevermind",
    ("Nirvana", "Lithium"): "Nevermind",
    ("Pearl Jam", "Alive"): "Ten",
    ("Pearl Jam", "Jeremy"): "Ten",
    ("Soundgarden", "Black Hole Sun"): "Superunknown",
    ("Green Day", "Basket Case"): "Dookie",
    ("Green Day", "When I Come Around"): "Dookie",
    ("The Offspring", "Self Esteem"): "Smash",
    ("Blink-182", "All the Small Things"): "Enema of the State",

    # Pop
    ("Kylie Minogue", "I Should Be so Lucky"): "Kylie",
    ("Kylie Minogue", "Can't Get You out of My Head"): "Fever",
    ("Kylie Minogue", "Love at First Sight"): "Fever",
    ("Dannii Minogue", "Love and Kisses"): "Love and Kisses",
    ("Jason Donovan", "Especially for You"): "Ten Good Reasons",
    ("Rick Astley", "Never Gonna Give You Up"): "Whenever You Need Somebody",
    ("Rick Astley", "Together Forever"): "Whenever You Need Somebody",
    ("Belinda Carlisle", "Circle in the Sand"): "Heaven on Earth",
    ("Tiffany", "I Think We're Alone Now"): "Tiffany",
    ("Debbie Gibson", "Lost in Your Eyes"): "Electric Youth",

    # Electronic/Dance
    ("U96", "Das Boot"): "Das Boot",
    ("Snap!", "Rhythm Is a Dancer"): "The Madman's Return",
    ("Snap!", "The Power"): "World Power",
    ("Culture Beat", "Mr. Vain"): "Serenity",
    ("2 Unlimited", "No Limit"): "No Limits!",
    ("2 Unlimited", "Tribal Dance"): "No Limits!",
    ("Corona", "The Rhythm of the Night"): "The Rhythm of the Night",
    ("Gala", "Freed From Desire"): "Come Into My Life",
    ("Eiffel 65", "Blue (Da Ba Dee)"): "Europop",
    ("Gigi D'Agostino", "The Riddle"): "L'Amour Toujours",
    ("Daft Punk", "Around the World"): "Homework",
    ("Daft Punk", "One More Time"): "Discovery",
    ("The Chemical Brothers", "Hey Boy Hey Girl"): "Surrender",
    ("The Prodigy", "Out of Space"): "Experience",
    ("Faithless", "Insomnia"): "Sunday 8PM",
    ("Underworld", "Born Slippy"): "Trainspotting",

    # German/European
    ("Reamon", "Supergirl"): "Raum",
    ("Sasha", "If You Believe"): "Dedicated to...",
    ("Nana", "Lonely"): "Nana",
    ("Blumchen", "Herz an Herz"): "Herz an Herz",
    ("Blumchen", "Boomerang"): "Heart of Glass",
    ("Kim Wilde", "Kids in America"): "Kim Wilde",
    ("Kim Wilde", "You Keep Me Hangin' On"): "Another Step",
    ("Sandra", "Maria Magdalena"): "The Long Play",
    ("Sandra", "(I'll Never Be) Maria Magdalena"): "The Long Play",
    ("Modern Talking", "You're My Heart, You're My Soul"): "The 1st Album",
    ("Blue System", "Sorry Little Sarah"): "Walking on Fire",
    ("City", "Am Fenster"): "City",

    # Various Artists / Soundtracks (handle separately)
    ("Youssou N'dour & Neneh Cherry", "7 Seconds"): "The Guide",  # or Neneh Cherry - Woman
    ("David Bowie & Queen", "Under Pressure"): "Hot Space",
    ("Brandy & Monica", "The Boy Is Mine"): "Never Say Never",  # Brandy
    ("Joe Cocker & Jennifer Warnes", "Up Where We Belong"): "An Officer and a Gentleman",
    ("Paul Mccartney & Stevie Wonder", "Ebony and Ivory"): "Tug of War",
    ("Micheal Jackson & Paul Mccartney", "Say Say Say"): "Pipes of Peace",
}


def normalize_for_matching(text: str) -> str:
    """Simple normalization for matching."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def auto_fill_assignments():
    """Auto-fill the CSV with known albums."""
    if not MAPPINGS_FILE.exists():
        print(f"Error: {MAPPINGS_FILE} not found. Run export first.")
        return

    filled = 0
    unfilled = 0

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
        if key in COMMON_ALBUMS:
            output_lines.append(f"{artist},{track},{COMMON_ALBUMS[key]}\n")
            filled += 1
            print(f"✓ {artist}: {track} → {COMMON_ALBUMS[key]}")
            continue

        # Try fuzzy match on artist + normalized track
        norm_track = normalize_for_matching(track)
        for (kb_artist, kb_track), album in COMMON_ALBUMS.items():
            if (artist == kb_artist and
                normalize_for_matching(kb_track) == norm_track):
                output_lines.append(f"{artist},{track},{album}\n")
                filled += 1
                print(f"~ {artist}: {track} → {album} (fuzzy)")
                break
        else:
            output_lines.append(line)
            unfilled += 1

    # Write back
    with open(MAPPINGS_FILE, 'w', encoding='utf-8') as f:
        f.writelines(output_lines)

    print(f"\nAuto-filled: {filled}")
    print(f"Still need assignment: {unfilled}")
    print(f"\nEdit {MAPPINGS_FILE} to fill in the rest, then run:")
    print(f"  python -m app.services.batch_assign_tracks \"20 Years on MTV\" --import --execute")


if __name__ == "__main__":
    auto_fill_assignments()
