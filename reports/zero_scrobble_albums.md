# Zero-Scrobble Albums — cleanup candidates

> ✅ **RESOLVED (2026-08-11).** All 137 true-zero orphans purged: 134 via
> `purge_zero_scrobble_albums.py` and 3 typo-variants merged via
> `fix_typo_album_orphans.py` (Genesis 'Trepass' repointed onto 'Trespass';
> Joy 'Divsion' and Steve Howe 'Beginings' deleted onto their live entities).
> Removed 137 `album` + 134 `album_alias` + 138 `album_art` + 993 `album_tracks`
> rows, 0 cover files (orphans held remote URLs only). Post-fix the regeneration
> query returns **0** true-zeros; `integrity_check` ok; 0 dangling `album_id` refs
> across `album_alias`/`album_art`/`album_tracks`/`scrobble`. Backup:
> `files/backups/lastfmstats_20260811_105843.sqlite`. The report below is the
> historical pre-fix record.

Generated: 2026-07-18
Database : files/lastfmstats.sqlite
Snapshot : 196,985 scrobbles, 4,465 album_art rows, scrobble.album_id 100% populated

## Definition

An album is listed here if it has **0 scrobbles** by BOTH checks:
1. canonical album_id — no `scrobble.album_id` points to `album_art.album_id`, AND
2. exact text match — no `scrobble` row with the same `artist` + `album` name.

These are genuine orphans: `album_art` + canonical `album` entity + `album_alias` exist
but nothing plays them. Safe to purge with the same FK-safe transaction used for
"The Bodyguard - Original Soundtrack Album" (delete album_alias + album_art + album,
children before parent, PRAGMA foreign_keys=ON, then the orphaned cover file under
app/static/covers/).

## Counts

- **134** true-zero albums  <- the table below (cleanup candidates)
- **358** additional album_art rows resolve to 0 scrobbles by album_id BUT have
  scrobbles by text match -> a SEPARATE duplicate-canonical-entity bug. **DO NOT delete**
  these; see "Mismatch finding" below.

## The 134 true-zero albums

| # | artist | album | album_id |
|---|--------|-------|----------|
| 1 | a-ha | Headlines and Deadlines - the Hits of A-HA | 4357 |
| 2 | Accept | Hungry Years (Remixed) | 4118 |
| 3 | Aerosmith | Greatest Hits | 4379 |
| 4 | Alanis Morissette | The Collection (Standard Edition) | 4398 |
| 5 | Armia | Tam gdzie kończy się kraj | 4117 |
| 6 | Aya RL | Aya RL | 4126 |
| 7 | Bartek Królik | Obietnice | 4128 |
| 8 | Ben Reilly | Freelance: Charlie | 4130 |
| 9 | Benson Boone | Fireworks & Rollerblades | 4300 |
| 10 | Billie Eilish | Guitar Songs | 4298 |
| 11 | Buzzcocks | Gotta Get Better | 4133 |
| 12 | Buzzcocks | Love Bites | 4134 |
| 13 | Błażej Król | Dziękuję | 4135 |
| 14 | Błażej Król | Przewijanie na podglądzie | 4136 |
| 15 | Cool Kids of Death | Afterparty 2 | 3473 |
| 16 | Cool Kids of Death | Żart | 4144 |
| 17 | Dead or Alive | Evolution: the Hits | 4316 |
| 18 | Deep Purple | Deep Purple in Rock | 4373 |
| 19 | Deep Purple | Made in Japan (Steven Wilson 2025 Remix) | 4113 |
| 20 | Dehet Sinn | Najmłodsza generacja | 4151 |
| 21 | Depeche Mode | 101 (Live) | 4152 |
| 22 | Depeche Mode | The Singles 86-98 | 4369 |
| 23 | Destroyer | Kaputt | 4153 |
| 24 | Dezerter | Słowa | 4304 |
| 25 | Dire Straits | Alchemy Dire Straits Live | 4446 |
| 26 | Dire Straits | Live at the BBC | 4447 |
| 27 | Echoboy | Volume One | 4158 |
| 28 | Ennio Morricone | Ennio Morricone Greatest Hits 2017 (Spotify Exclusive) | 4161 |
| 29 | Enya | A Box of Dreams - Oceans | 4451 |
| 30 | Enya | A Box of Dreams - Stars | 4452 |
| 31 | Eric Carmen | The Definitive Collection | 4162 |
| 32 | Eric Clapton | Unplugged (Live) | 4163 |
| 33 | Eurythmics | 1984 - for the Love of Big Brother | 4318 |
| 34 | Faces | Ooh La La | 4165 |
| 35 | Fluke | Absurd | 4167 |
| 36 | GBH | Ha Ha | 4170 |
| 37 | GBH | Leather, Bristles, Studs and Acne | 4171 |
| 38 | Genesis | Trepass | 4459 |
| 39 | Genesis | Wind and Wuthering | 4460 |
| 40 | George Martin | Yellow Submarine | 4302 |
| 41 | Happy Birthday | Happy Birthday (Traditional) | 4299 |
| 42 | IDLES | CRAWLER | 4180 |
| 43 | IDLES | Dancer | 4181 |
| 44 | Izabela Trojanowska | Komu więcej, komu mniej (The Best) | 4182 |
| 45 | Joy Division | The Best Of | 4193 |
| 46 | Joy Divsion | Heart and Soul | 4297 |
| 47 | Kapitan Nemo | The Best Of | 4412 |
| 48 | Kapitan Nemo | Zimne kino | 4413 |
| 49 | Kaśka Sochacka | Wszystko (Live) | 4195 |
| 50 | Kobiety | Podarte sukienki | 4197 |
| 51 | Korn | Word Up! (The Remixes) | 4114 |
| 52 | Lombard | The Best - Przeżyj to sam | 4203 |
| 53 | Madness | 7 | 4208 |
| 54 | Madness | The Rise & Fall | 4209 |
| 55 | Mandalay | Solace | 4210 |
| 56 | Massive Attack | Karmacoma | 4374 |
| 57 | Massive Attack | Sly | 4375 |
| 58 | Melissa Auf der Maur | Out of Our Minds | 4330 |
| 59 | Muse | Collateral Damage | 4216 |
| 60 | Muse | Cryogen | 4396 |
| 61 | Myslovitz | The Best of Myslovitz | 4397 |
| 62 | Neil Young | 100 Greatest Classic Rock Songs | 4370 |
| 63 | Neil Young | After the Gold Rush | 4220 |
| 64 | Neil Young | Everybody Knows This Is Nowhere | 4221 |
| 65 | New Model Army | History - the Singles 85-91 | 4596 |
| 66 | New Order, John Robie, Shep Pettibone | Substance | 4358 |
| 67 | Olivia Vedder | My Father's Daughter (From The “Flag Day” Original Soundtrack) | 4226 |
| 68 | Opera | Opera | 4227 |
| 69 | Orchestral Manoeuvres in the Dark | Organisation | 4228 |
| 70 | Orchestral Manoeuvres in the Dark | The Best of OMD | 4372 |
| 71 | Pacifica | Anita | 4229 |
| 72 | Pacifica | With or Without You | 4335 |
| 73 | Palms | Opening Titles / End Credits | 4230 |
| 74 | Pearl Jam | Waiting for Stevie (Radio Edit) | 4336 |
| 75 | Prong | Beg to Differ | 4236 |
| 76 | Prong | Carved into Stone | 4337 |
| 77 | Prong | Cleansing | 4237 |
| 78 | Prong | Rude Awakening | 4238 |
| 79 | Prong | State of Emergency | 4338 |
| 80 | Prong | Working Man | 4383 |
| 81 | Puscifer | Billy D and the Hall of Feathered Serpents (Live) | 4239 |
| 82 | Puscifer | What Is… (Live) | 4240 |
| 83 | Republika | Kombinat | 4245 |
| 84 | Rezerwat | Polskie Single '86 | 4303 |
| 85 | Rezerwat | Zaopiekuj się mną | 4246 |
| 86 | Roan | Soundcheck | 4250 |
| 87 | Rob Dougan | Music from and Inspired by the Motion Picture the Matrix | 4342 |
| 88 | Sinéad O'Connor | Lion and the Cobra | 4257 |
| 89 | Sisters of Mercy | Floodland | 4259 |
| 90 | Sisters of Mercy | Some Girls Wander by Mistake | 4345 |
| 91 | Sisters of Mercy | Vision Thing | 4260 |
| 92 | Soundgarden | Badmotorfinger (25th Anniversary Remaster) | 4364 |
| 93 | Soundgarden | Superunknown (20th Anniversary) | 4262 |
| 94 | Steve Howe | Beginings | 4388 |
| 95 | Sting | The Very Best of Sting and the Police | 4347 |
| 96 | super girl romantic boys | DANSING | 4371 |
| 97 | Swans | Greed/Holy Money | 4533 |
| 98 | Swans | Holy Money / a Screw | 4348 |
| 99 | Swans | I Am a Tower | 4265 |
| 100 | Swans | Swans Are Dead: Live '95-'97 | 4266 |
| 101 | T.Love | I Love You (Live) | 4267 |
| 102 | Tarantula Hawk | Tarantula Hawk2 | 4534 |
| 103 | The Charlatans | Between 10th and 11th | 4271 |
| 104 | The Cranberries | Dreaming My Dreams with You | 4349 |
| 105 | The Cranberries | No Need to Argue (The Complete Sessions 1994-1995) | 4305 |
| 106 | The Cure | Curaetion-25: from There to Here \| from Here to There (Live) | 4350 |
| 107 | The Cure | Staring at the Sea - the Singles | 4351 |
| 108 | The Flaming Lips | Yoshimi Battles the Pink Robots | 4273 |
| 109 | The Killers | Caution | 4377 |
| 110 | The Killers | Day & Age (Bonus Tracks) | 4275 |
| 111 | The Killers | My Own Soul's Warning | 4376 |
| 112 | The Police | Greatest Hits | 4277 |
| 113 | The Police | The Very Best of Sting and the Police | 4352 |
| 114 | The Prodigy | Music from and Inspired by the Motion Picture the Matrix | 4353 |
| 115 | The Rolling Stones | Between the Buttons | 4279 |
| 116 | The Sisters of Mercy | Temple of Rarities Vol2 | 4573 |
| 117 | The Smashing Pumpkins | Atum | 4280 |
| 118 | The Smashing Pumpkins | Who Goes There | 4282 |
| 119 | The Stranglers | Dreamtime | 4116 |
| 120 | The Yardbirds | The Yardbirds Story - Pt. 3 - 1965/66 - Big Hits & America Calling | 4395 |
| 121 | Thomas Bangalter | IRREVERSIBLE | 4411 |
| 122 | Throwing Muses | Anthology | 4115 |
| 123 | Tom Petty | Greatest Hits | 4289 |
| 124 | Tones and I | Dance Monkey (Stripped Back) / Dance Monkey | 4301 |
| 125 | Tool | Metal Heads | 4389 |
| 126 | Toto | The Definitive Collection | 4359 |
| 127 | Various Artists | Flag Day | 4385 |
| 128 | Various Artists | Radio Nieprzemakalnych | 4392 |
| 129 | Various Artists | Twang ! | 4249 |
| 130 | Varius Manx | 25 (Edycja specjalna) | 4292 |
| 131 | Varius Manx | ZLOTA KOLEKCJA - Zanim Zrozumiesz | 4378 |
| 132 | Whitney Houston | My Love Is Your Love | 3410 |
| 133 | Wilki | Acousticus Rockus (Live) | 4294 |
| 134 | XXANAXX | Triangles | 4296 |

## Special cases — review before any bulk delete

- **Whitney Houston - My Love Is Your Love (3410)** — orphan created THIS session by
  moving its title track to the best-of. Expected; safe to delete.
- **Cool Kids of Death - Afterparty 2 (3473)** — subject of the in-progress, untracked
  `app/services/redistribute_afterparty2.py`. EXCLUDE until that script is resolved.
- Typos to MERGE (not delete): Joy Divsion - Heart and Soul, Genesis - Trepass,
  Steve Howe - Beginings.
- Many entries are Last.fm single-tag artifacts (one track tagged as its own album):
  Massive Attack - Karmacoma / Sly, Pearl Jam - Waiting for Stevie, Tones and I - Dance
  Monkey (Stripped Back), The Killers - Caution / My Own Soul's Warning, etc.

## Mismatch finding (duplicate canonical entities) — DO NOT DELETE

358 album_art rows have album_id pointing at a canonical `album` entity that holds
0 scrobbles, while the real scrobbles for the same (artist, album) live under a DIFFERENT
album_id whose canonical title is the same string. The album_art backfill minted fresh
high-id entities (~4100+) instead of reusing the scrobble-seeded ones (e.g. Armia -
22 Polish Punk Classics: album_art->4125 dead, scrobbles->1217 live).
Fix = repoint album_art.album_id + album_alias at the live entity and drop the duplicate,
NOT delete the album (it has plays).

## Regeneration queries

```sql
-- True zeros (the table above):
SELECT aa.artist, aa.album, aa.album_id
FROM album_art aa
WHERE (SELECT COUNT(*) FROM scrobble s WHERE s.album_id = aa.album_id) = 0
  AND (SELECT COUNT(*) FROM scrobble s WHERE s.artist = aa.artist AND s.album = aa.album) = 0
ORDER BY lower(aa.artist), lower(aa.album);

-- album_id mismatches (the duplicate-entity cases) — live album_id per row:
SELECT aa.artist, aa.album, aa.album_id AS dead_album_art_id,
       (SELECT s.album_id FROM scrobble s
        WHERE s.artist = aa.artist AND s.album = aa.album LIMIT 1) AS live_scrobble_album_id
FROM album_art aa
WHERE (SELECT COUNT(*) FROM scrobble s WHERE s.album_id = aa.album_id) = 0
  AND (SELECT COUNT(*) FROM scrobble s WHERE s.artist = aa.artist AND s.album = aa.album) > 0;
```
