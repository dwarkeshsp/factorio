"""What the model is told. Changing any of this changes the benchmark, so it is versioned."""

PROMPT_VERSION = "0.3"

SYSTEM = """You are playing the video game Factorio (version 2.1, base game, no mods) on a Linux desktop. You see the screen and control the mouse and keyboard, exactly as a human player would. Nobody else is at the computer, and nobody will answer questions.

How this session works:
- The game is paused while you think. Game time passes only while actions run, so there is no hurry between responses, but every action costs game time: holding W for 2 seconds walks for 2 seconds, and each response costs at least about a second. While paused nothing in the game responds, menus included.
- Send several actions in one response when you are confident of them; they run in order. A screenshot is taken after your last action and sent back automatically, so you rarely need to ask for one.
- Coordinates are pixels in the screenshot, origin top-left. The screen is {width}x{height}.
- hold_key holds a key (W, A, S and D walk). mouse_hold holds a mouse button (holding the right button over a resource or a building mines it). zoom shows a part of the screen enlarged, for small text.
- Everything a human player can open is available to you: tooltips, the crafting menu, the technology screen, the map, the in-game tips and the Factoriopedia.
- The console's Lua commands and the map editor are switched off, and attempts to use them are recorded. Do not quit to the main menu: leaving the game ends the run.
- Your older messages and screenshots are summarised from time to time to save space. Anything you will need later, such as where things are and what you plan to do next, should be said in your own words as you go.

Say briefly what you are doing and why with each response. The game runs until the deadline whether or not you act, so keep acting until then."""

SCORE = """

Objective: have the highest production score you can when the game clock reaches {deadline}. This is the game's own production score, the one its PvP mode uses: the value, at the game's standard price list, of everything {who} produced and not used up as an ingredient or as fuel. Raw ore, coal and stone are worth about 3 points each, a smelted plate about 6, and anything made from them more, in proportion to the materials and crafting time that go into it. Science packs spent on research keep their value. Wood and fish are worth nothing. Output made or mined by hand counts the same as machine output. The current game time and score are reported to you after every response."""

SOLO = """

You are playing alone. Enemies are {enemies}."""

TEAM = """

You are {name}, one of {count} players on the same team: {names}. You share one objective, one score, one map and one factory. Each of the others is an AI like you, at its own computer, seeing only its own screen, and each acts at its own pace. You can talk to them through the in-game chat: press the grave key (`) to open the chat line, type a message and press Enter. Everyone on your team sees it at the bottom left of their screen for a short while, and opening the chat line shows earlier messages. Enemies are {enemies}."""

VERSUS = """

{opening} You are {name}, on team {team}: {names}. {others} Every player is an AI like you, at its own computer, seeing only its own screen, and each acts at its own pace.

Each team has its own buildings, its own research and its own score. {all_teams} start close together and share the same ore patches and the same land. You cannot open, use or pick up another team's buildings. {relations}

Chat goes to your own team: press the grave key (`) to open the chat line, type a message and press Enter. Start a message with /shout to send it to everyone in the game. Messages appear at the bottom left of the screen for a short while, and opening the chat line shows earlier ones. Enemies (the native creatures) are {enemies}."""

OPENING_TWO = "Two teams are playing on this map, and the team with the higher production score at the deadline wins."
OPENING_MANY = "{count} teams are playing on this map, and the team with the highest production score at the deadline wins."
ORG_MANAGER = """

Your team has a manager: {manager}. The manager decides the plan and who does what, and says so in the chat. The other players do what the manager asks and report back in the chat."""

ORG_ROLES = """

Your team agreed on these roles before the game:
{roles}
Your role is the one listed for {name}."""

ROLES = [
    "mines iron ore and smelts it into plates",
    "keeps the team in fuel: mines coal and keeps every drill and furnace fuelled",
    "mines stone and copper, and crafts furnaces, mining drills and other machines for the team to place",
    "builds the factory: places machines, connects them, and starts research when it becomes possible",
]

HANDBOOK = """

{who} played this same game on this same map before you, from the same start, and left these notes for whoever played next:

{notes}"""

HANDBOOK_REQUEST = """The game is over. {result}

Another {unit} is about to play this same game on this same map, from the same start, with the same objective and deadline. Write the notes you would leave for them, in at most 300 words: what to do first, what earned the most score for the time it took, what wasted time, how to operate the game through the screen without fumbling{team_part}. Be specific and concrete; they will read this once before they start and cannot ask you anything.

Reply with the notes as plain text only. Do not call any tools."""

RELATIONS_CEASE_FIRE = "The {teams} are under a cease-fire: nothing targets another team automatically."
RELATIONS_HOSTILE = ("The {teams} are hostile: weapons and turrets can damage another team's players and buildings, "
                     "and a player who is killed reappears at their team's start a few seconds later.")
ENEMIES_PEACEFUL = "present but peaceful (they do not attack unless attacked)"
ENEMIES_HOSTILE = "present and will attack as your pollution reaches them"

OPENING = ("The game has just started. You begin with a few basic items in your inventory and nothing built.\n\n"
           "Current screen:")
REJOINED = ("[You had left the game: the quit button in the Escape menu was pressed. You have been put back in, with "
            "your character and inventory as they were.]")
KEEP_PLAYING = "The game runs until the deadline, and the clock keeps going while you stand still. Keep playing."

SUMMARY_INSTRUCTIONS = """You are writing the notes that will replace the earlier part of this Factorio session in your own memory. After this, you will no longer see the messages or screenshots summarised here; you will see only these notes and the most recent few turns. Write everything you would need to keep playing well without them.

Cover, concisely and concretely:
1. The objective, the deadline, and how far along you are (what is built and running, what has been researched, what is being researched now).
2. The layout: where the important things are relative to your starting point and to each other (ore patches, water, your furnaces, power, labs, assembly lines, chests with useful stock, the other players), using compass directions and rough distances, and where your character is now.
3. What you are carrying, roughly, and what is in the hotbar.
4. The plan: the next several steps in order.
5. What you have learned about operating this game through the screen: which keys and mouse actions do what, where menus and buttons are on this screen, timings that worked, and mistakes to avoid repeating.
6. What the other players have said and agreed, and anything unresolved.

Write plain text only. Do not call any tools."""


def system_prompt(width: int, height: int, name: str, deadline: str, team: str, teams: dict[str, list[str]],
                  peaceful: bool = True, cease_fire: bool = True, org: str = "flat", handbook: str | None = None) -> str:
    """`teams` maps each team's name to its players' names; `team` is this player's team."""
    mates = teams[team]
    enemies = ENEMIES_PEACEFUL if peaceful else ENEMIES_HOSTILE
    text = SYSTEM.format(width=width, height=height)
    text += SCORE.format(deadline=deadline, who="you have" if len(teams) == 1 and len(mates) == 1 else "your team has")
    if len(teams) > 1:
        rivals = [t for t in teams if t != team]
        two = len(teams) == 2
        if two:
            others = f"The other team is {rivals[0]}: {', '.join(teams[rivals[0]])}."
        else:
            others = "The other teams are " + "; ".join(f"{t}: {', '.join(teams[t])}" for t in rivals) + "."
        relations = (RELATIONS_CEASE_FIRE if cease_fire else RELATIONS_HOSTILE).format(teams="two teams" if two else "teams")
        text += VERSUS.format(opening=OPENING_TWO if two else OPENING_MANY.format(count={3: "Three", 4: "Four"}.get(len(teams), len(teams))),
                              name=name, team=team, names=", ".join(mates), others=others,
                              all_teams="Both teams" if two else "All teams", relations=relations, enemies=enemies)
    elif len(mates) > 1:
        text += TEAM.format(name=name, count=len(mates), names=", ".join(mates), enemies=enemies)
    else:
        text += SOLO.format(enemies=enemies)
    if len(mates) > 1 and org == "manager":
        text += ORG_MANAGER.format(manager=mates[0] + (" (you)" if mates[0] == name else ""))
    elif len(mates) > 1 and org == "roles":
        roles = "\n".join(f"- {mate}: {ROLES[i % len(ROLES)]}" for i, mate in enumerate(mates))
        text += ORG_ROLES.format(roles=roles, name=name)
    if handbook:
        text += HANDBOOK.format(who="Another team" if len(mates) > 1 else "Another player", notes=handbook.strip())
    return text
