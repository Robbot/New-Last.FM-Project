#!/usr/bin/env python3
"""
Extended auto-fill with comprehensive album knowledge base.
"""

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
MAPPINGS_FILE = BASE_DIR / "files" / "track_assignments.csv"

# Extended knowledge base
EXTENDED_ALBUMS = {
    # 80s Rock/Pop continued
    ("Soul Asylum", "Runaway Train"): "Grave Dancers Union",
    ("Yello", "The Race"): "Stella",
    ("The Bloodhound Gang", "The Bad Touch"): "Hooray for Boobies",
    ("Visage", "Fade to Grey"): "Visage",
    ("Adamski", "Killer"): " Adamski's Album",
    ("Bananarama", "Venus"): "True Confessions",
    ("Camoflage", "Love Is a Shield"): "Methods of Silence",
    ("John Lennon", "Woman"): "Double Fantasy",
    ("Kajagoogoo", "Too Shy"): "White Feathers",
    ("Limahl", "Never Ending Story"): "The NeverEnding Story",
    ("Prince", "Purple Rain"): "Purple Rain",
    ("Prince", "When Doves Cry"): "Purple Rain",
    ("Robert Palmer", "Addicted to Love"): "Riptide",
    ("Van Halen", "Jump"): "1984",
    ("Van Halen", "Panama"): "1984",
    ("Billy Idol", "Sweet Sixteen"): "Whiplash Smile",
    ("Billy Idol", "White Wedding"): "Billy Idol",
    ("Bon Jovi", "Livin` on a Prayer"): "Slippery When Wet",
    ("Bon Jovi", "You Give Love a Bad Name"): "Slippery When Wet",
    ("Kim Carnes", "Bette Davis Eyes"): "Mistaken Identity",
    ("Mike Oldfield", "Moonlight shadow"): "Crises",
    ("Olivia Newton John", "Physical"): "Physical",
    ("Roxy Music", "Jealous Guy"): "Country Life",
    ("Soft Cell", "Tainted Love"): "Non-Stop Erotic Cabaret",
    ("Talk Talk", "Such a Shame"): "It's My Life",
    ("The Rolling Stones", "Start Me Up"): "Tattoo You",
    ("Ultravox", "Vienna"): "Vienna",
    ("Wham!", "Last Christmas"): "Last Christmas",
    ("Wham!", "Wake Me Up Before You Go-Go"): "Make It Big",
    ("Whitney Houston", "How Will I Know"): "Whitney Houston",
    ("Wham!", "Careless Whisper"): "Make It Big",  # George Michael solo, but often credited to Wham

    # 90s Rock/Pop
    ("Ace of Base", "All That She Wants"): "Happy Nation",
    ("Ace of Base", "The Sign"): "Happy Nation",
    ("Alanis Morissette", "Ironic"): "Jagged Little Pill",
    ("Alanis Morissette", "Hand in My Pocket"): "Jagged Little Pill",
    ("Apollo 440", "Aint Talk About Dub"): "Electro Glide in Blue",
    ("Band Aid", "Do They Know It's Christmas?"): "Do They Know It's Christmas?",
    ("Blondie", "Maria"): "No Exit",
    ("Brian Adams", "When You Really Love a Woman"): "18 Til I Die",
    ("Britney Spears", "Baby One More Time"): "...Baby One More Time",
    ("Britney Spears", "Oops!... I Did It Again"): "Oops!... I Did It Again",
    ("Celine Dion", "My Heart Will Go On"): "Let's Talk About Love",
    ("Celine Dion", "The Power of Love"): "The Colour of My Love",
    ("Die Aerzte", "Maenner Sind Schweine"): "Die Aerzte",
    ("Enigma", "Sadeness (Part 1)"): "MCMXC a.D.",
    ("Enigma", "Return to Innocence"): "The Cross of Changes",
    ("Europe", "The Final Countdown"): "The Final Countdown",
    ("Europe", "Carrie"): "The Final Countdown",
    ("Eurythmics", "Sweet Dreams"): "Sweet Dreams (Are Made of This)",
    ("Eurythmics", "Here Comes the Rain Again"): "Touch",
    ("Everything but the Girl", "Missing"): "Amplified Heart",
    ("Frankie Goes to Hollywood", "Relax"): "Welcome to the Pleasuredome",
    ("Frankie Goes to Hollywood", "Two Tribes"): "Welcome to the Pleasuredome",
    ("George Michael", "Faith"): "Faith",
    ("George Michael", "Father Figure"): "Faith",
    ("George Michael", "Careless Whisper"): "Make It Big",
    ("Guns N' Roses", "Sweet Child O' Mine"): "Appetite for Destruction",
    ("Guns N' Roses", "November Rain"): "Use Your Illusion I",
    ("Housemartins", "Caravan of Love"): "London 0 Hull 4",
    ("INXS", "I Need You Tonight"): "Kick",
    ("INXS", "Need You Tonight"): "Kick",
    ("INXS", "New Sensation"): "Kick",
    ("Lenny Kravitz", "Are You Gonna Go My Way"): "Are You Gonna Go My Way",
    ("Lenny Kravitz", "American Woman"): "5",
    ("Lenny Kravitz", "Fly Away"): "5",
    ("Metallica", "Enter Sandman"): "Metallica",
    ("Metallica", "Nothing Else Matters"): "Metallica",
    ("Metallica", "One"): "...And Justice for All",
    ("Nirvana", "Come As You Are"): "Nevermind",
    ("Nirvana", "Lithium"): "Nevermind",
    ("Nirvana", "Heart-Shaped Box"): "In Utero",
    ("Oasis", "Wonderwall"): "(What's the Story) Morning Glory?",
    ("Oasis", "Don't Look Back in Anger"): "(What's the Story) Morning Glory?",
    ("Oasis", "Live Forever"): "Definitely Maybe",
    ("Placebo", "Nancy Boy"): "Placebo",
    ("Placebo", "Pure Morning"): "Without You I'm Nothing",
    ("Pulp", "Common People"): "Different Class",
    ("Radiohead", "Creep"): "Pablo Honey",
    ("Radiohead", "High and Dry"): "The Bends",
    ("Rammstein", "Du Hast"): "Sehnsucht",
    ("Rammstein", "Sonne"): "Mutter",
    ("Red Hot Chili Peppers", "Californication"): "Californication",
    ("Red Hot Chili Peppers", "Otherside"): "Californication",
    ("Red Hot Chili Peppers", "Scar Tissue"): "Californication",
    ("Roxette", "The Look"): "Look Sharp!",
    ("Roxette", "Listen to Your Heart"): "Look Sharp!",
    ("Roxette", "Joyride"): "Joyride",
    ("Sheryl Crow", "All I Wanna Do"): "Tuesday Night Music Club",
    ("Sheryl Crow", "Soak Up the Sun"): "C'mon C'mon",
    ("Smashing Pumpkins", "1979"): "Mellon Collie and the Infinite Sadness",
    ("Smashing Pumpkins", "Today"): "Siamese Dream",
    ("Soundgarden", "Black Hole Sun"): "Superunknown",
    ("Space", "Female of the Species"): "Spiders",
    ("Supergrass", "Alright"): "I Should Coco",
    ("Tlc", "No Scrubs"): "FanMail",
    ("Travis", "Why Does It Always Rain on Me?"): "The Man Who",
    ("The Verve", "Bitter Sweet Symphony"): "Urban Hymns",
    ("The Verve", "The Drugs Don't Work"): "Urban Hymns",
    ("Weezer", "Buddy Holly"): "Weezer",
    ("Weezer", "Say It Ain't So"): "Weezer",

    # 2000s
    ("Amy Winehouse", "Rehab"): "Back to Black",
    ("Amy Winehouse", "You Know I'm No Good"): "Back to Black",
    ("Avril Lavigne", "Complicated"): "Let Go",
    ("Avril Lavigne", "Sk8er Boi"): "Let Go",
    ("Beyonce", "Crazy in Love"): "Dangerously in Love",
    ("Beyonce", "Baby Boy"): "Dangerously in Love",
    ("Black Eyed Peas", "Where Is the Love?"): "Elephunk",
    ("Black Eyed Peas", "Shut Up"): "Elephunk",
    ("Coldplay", "Yellow"): "Parachutes",
    ("Coldplay", "Clocks"): "A Rush of Blood to the Head",
    ("Coldplay", "The Scientist"): "A Rush of Blood to the Head",
    ("Dido", "Thank You"): "No Angel",
    ("Dido", "White Flag"): "Life for Rent",
    ("Eminem", "Without Me"): "The Eminem Show",
    ("Eminem", "Stan"): "The Slim Shady LP",
    ("Eminem", "Lose Yourself"): "8 Mile",
    ("Evanescence", "Bring Me to Life"): "Fallen",
    ("Evanescence", "My Immortal"): "Fallen",
    ("James Blunt", "You're Beautiful"): "Back to Bedlam",
    ("James Blunt", "Goodbye My Lover"): "Back to Bedlam",
    ("Jay-Z", "99 Problems"): "The Black Album",
    ("Jay-Z", "Crazy in Love"): "The Blueprint",
    ("Justin Timberlake", "Cry Me a River"): "Justified",
    ("Justin Timberlake", "Rock Your Body"): "Justified",
    ("Kanye West", "Through the Wire"): "The College Dropout",
    ("Kanye West", "Jesus Walks"): "The College Dropout",
    ("Kanye West", "Gold Digger"): "Late Registration",
    ("Kings of Leon", "Sex on Fire"): "Only by the Night",
    ("Kings of Leon", "Use Somebody"): "Only by the Night",
    ("Linkin Park", "In the End"): "Hybrid Theory",
    ("Linkin Park", "Crawling"): "Hybrid Theory",
    ("Linkin Park", "Numb"): "Meteora",
    ("Maroon 5", "This Love"): "Songs About Jane",
    ("Maroon 5", "She Will Be Loved"): "Songs About Jane",
    ("Nelly Furtado", "I'm Like a Bird"): "Whoa, Nelly!",
    ("Nelly Furtado", "Maneater"): "Loose",
    ("Norah Jones", "Don't Know Why"): "Come Away with Me",
    ("OutKast", "Hey Ya!"): "Speakerboxxx / The Love Below",
    ("OutKast", "Ms. Jackson"): "Stankonia",
    ("Pink", "Get the Party Started"): "M!ssundaztood",
    ("Pink", "Just like a Pill"): "M!ssundaztood",
    ("Robbie Williams", "Angels"): "Life thru a Lens",
    ("Robbie Williams", "Feel"): "Escapology",
    ("Scissor Sisters", "I Don't Feel Like Dancin'"): "Ta-Dah",
    ("Snow Patrol", "Run"): "Final Straw",
    ("Snow Patrol", "Chasing Cars"): "Eyes Open",
    ("The Strokes", "Last Nite"): "Is This It",
    ("The Strokes", "Someday"): "Room on Fire",

    # Electronic/Dance extended
    ("ATB", "9 PM (Till I Come)"): "Movin' Melodies",
    ("Alice Deejay", "Better Off Alone"): "Who Needs Guitars Anyway?",
    ("Cascada", "Everytime We Touch"): "Everytime We Touch",
    ("Darude", "Sandstorm"): "Before the Storm",
    ("David Guetta", "Love Don't Let Me Go"): "Guetta Blaster",
    ("David Guetta", "When Love Takes Over"): "One Love",
    ("Deadmau5", "Ghosts 'n' Stuff"): "For Lack of a Better Name",
    ("DJ Snake", "Turn Down for What"): "Turn Down for What",
    ("Duck Sauce", "Barbra Streisand"): "Quack",
    ("Fedde Le Grand", "Put Your Hands Up 4 Detroit"): "Output",
    ("Guetta", "Without You"): "Nothing but the Beat",
    ("Klas", "I'm Not Alone"): "I'm Not Alone",
    ("Klan", "Life"): "Life",
    ("LMFAO", "Party Rock Anthem"): "Sorry for Party Rocking",
    ("Martin Solveig", "Hello"): "Smash",
    ("Pitbull", "I Know You Want Me"): "Rebelution",
    ("Swedish House Mafia", "Don't You Worry Child"): "Until Now",
    ("Tiësto", "Adagio for Strings"): "Just Be",
    ("Tiësto", "Traffic"): "Just Be",
    ("Zedd", "Clarity"): "Clarity",

    # German/European extended
    ("Die Aerzte", "Maenner Sind Schweine"): "Die Aerzte",
    ("Die Aerzte", "Westerland"): "Die Aerzte",
    ("Die Fantastischen Vier", "Die Da"): "4 Gewinnt",
    ("Fools Garden", "Lemon Tree"): "Dish of the Day",
    ("Guano Apes", "Lords of the Boards"): "Proud Like a God",
    ("Guano Apes", "Losing My Religion"): "Proud Like a God",
    ("Herbert Grönemeyer", "Männer"): "Bochum",
    ("Nena", "99 Luftballons"): "Nena",
    ("Nena", "Leuchtturm"): "Nena",
    ("Peter Maffay", "Du"): "Tabaluga",
    ("Rosenstolz", "Gib mir Sonne"): "Macht",
    ("Sash!", "Ecuador"): "It's My Life",
    ("Sash!", "Encore Une Fois"): "It's My Life",
    ("Scooter", "How Much Is the Fish"): "No Time to Chill",
    ("Scooter", "The Logical Song"): "No Time to Chill",
    ("Wolfsheim", "The Sparrows and the Nightingale"): "Spectators",
    ("Wolfsheim", "Kein Zurück"): "Casting Shadows",

    # Soundtracks extended
    ("Bonnie Bianco & Pierre Cosso", "Stay (La Boum)"): "La Boum",
    ("Franka Potente & Thomas D", "Wish"): "Run Lola Run",
    ("Joe Cocker & Jennifer Warnes", "Up Where We Belong"): "An Officer and a Gentleman",
    ("Phil Collins", "Against All Odds"): "Against All Odds",
    ("Phil Collins", "Two Hearts"): "Buster",
    ("Steppenwolf", "Born to Be Wild"): "Easy Rider",

    # Collaborations
    ("Micheal Jackson & Paul Mccartney", "Say Say Say"): "Pipes of Peace",
    ("Paul Mccartney & Stevie Wonder", "Ebony and Ivory"): "Tug of War",
    ("David Bowie & Queen", "Under Pressure"): "Hot Space",
    ("Youssou N'dour & Neneh Cherry", "7 Seconds"): "The Guide",
    ("Brandy & Monica", "The Boy Is Mine"): "Never Say Never",
    ("Kool & the Gang", "Celebration"): "Celebrate!",
}


def normalize_for_matching(text: str) -> str:
    """Simple normalization for matching."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def auto_fill_extended():
    """Auto-fill with extended knowledge base."""
    if not MAPPINGS_FILE.exists():
        print(f"Error: {MAPPINGS_FILE} not found.")
        return

    # Combine both dictionaries
    all_albums = {**EXTENDED_ALBUMS}

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
        if key in all_albums:
            output_lines.append(f"{artist},{track},{all_albums[key]}\n")
            filled += 1
            print(f"✓ {artist}: {track} → {all_albums[key]}")
            continue

        # Try fuzzy match
        norm_track = normalize_for_matching(track)
        for (kb_artist, kb_track), album in all_albums.items():
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
    auto_fill_extended()
