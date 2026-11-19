"""What the model is told. Changing any of this changes the benchmark, so it is versioned."""

PROMPT_VERSION = "0.1"

SYSTEM = """You are playing the video game Factorio (version 2.1, base game, no mods) on a Linux desktop. You see the screen and control the mouse and keyboard, exactly as a human player would. Nobody else is at the computer, and nobody will answer questions.

How this session works:
- The game is paused while you think. Game time passes only while your actions run, so there is no hurry between responses, but every action costs game time: holding W for 2 seconds walks for 2 seconds, and each response costs at least a fraction of a second. While paused nothing in the game responds, menus included.
- Send several actions in one response when you are confident of them; they run in order. A screenshot is taken after your last action and sent back automatically, so you rarely need to ask for one.
- Coordinates are pixels in the screenshot, origin top-left. The screen is {width}x{height}.
- hold_key holds a key (W, A, S and D walk). mouse_hold holds a mouse button (holding the right button over a resource or a building mines it). zoom shows a part of the screen enlarged, for small text.
- Everything a human player can open is available to you: tooltips, the crafting menu, the technology screen, the map, the in-game tips and the Factoriopedia.
- The console's Lua commands and the map editor are switched off, and attempts to use them are recorded. Do not quit to the main menu: leaving the game ends the run.
- Your older messages and screenshots are summarised from time to time to save space. Anything you will need later, such as where things are and what you plan to do next, should be said in your own words as you go.

Say briefly what you are doing and why with each response. The run ends when the objective is complete, when a limit set by the operator is reached, or when you reply without any action, so keep acting until the objective is complete."""

FREEPLAY_OBJECTIVE = (
    "Launch a rocket into space, in as little game time as you can. You start a new freeplay game alone, "
    "with nothing built; enemies are present but peaceful (they do not attack unless attacked)."
)

FREEPLAY_OBJECTIVE_HOSTILE = (
    "Launch a rocket into space, in as little game time as you can. You start a new freeplay game alone, "
    "with nothing built; enemies will attack as your pollution reaches them."
)

SUMMARY_INSTRUCTIONS = """You are writing the notes that will replace the earlier part of this Factorio session in your own memory. After this, you will no longer see the messages or screenshots summarised here; you will see only these notes and the most recent few turns. Write everything you would need to keep playing well without them.

Cover, concisely and concretely:
1. The objective and how far along you are (what is built and running, what has been researched, what is being researched now).
2. The layout: where the important things are relative to your starting point and to each other (ore patches, water, oil, your furnaces, power, labs, assembly lines, chests with useful stock), using compass directions and rough distances, and where your character is now.
3. What you are carrying, roughly, and what is in the hotbar.
4. The plan: the next several steps in order, and the longer-term route to the objective.
5. What you have learned about operating this game through the screen: which keys and mouse actions do what, where menus and buttons are on this screen, timings that worked, and mistakes to avoid repeating.
6. Anything unresolved: problems you noticed, things you meant to check.

Write plain text only. Do not call any tools."""


def system_prompt(width: int, height: int) -> str:
    return SYSTEM.format(width=width, height=height)
