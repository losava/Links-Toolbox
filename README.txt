===============================================================================
                              LINK'S TOOL BOX
   Mod loader + save editor for Zelda: Ocarina of Time (Triforce / Longshot)
                              by Cum_Dumpster
===============================================================================

Link's Tool Box is a small Windows app for people who play Ocarina of Time
through Triforce. In one window it lets you:

  * turn your mods on and off before you play, and choose which one wins
    when two mods change the same file
  * edit your save: hearts, magic, rupees, items, ammo, bottles, keys and
    story progress, with the names the game itself uses
  * point it at a different game, mods or saves folder
  * make it look the way you like (themes and tab colours)

It brings its own Python (nothing else to install), and it never changes the game
itself. It only touches your mods folder and your save files.


-------------------------------------------------------------------------------
 GETTING STARTED
-------------------------------------------------------------------------------

INSTALLED APP (Windows, recommended): double-click  Install Link Toolbox.bat
  It goes to %LOCALAPPDATA%\Programs\Link Toolbox (no admin needed), with
  Start menu and Desktop shortcuts, and an entry in Windows Settings > Apps.
  It stays in one place, so your settings (game, folders, shared builds,
  look) are kept through every update. Running it again over an installed
  copy upgrades it. Installing from a portable copy you've used brings its
  settings and backups along.
  To uninstall the app: Updates tab > "Uninstall Link's Tool Box (this app)",
  or Windows Settings > Apps. It removes only the toolbox app (it asks
  first): the game, your game saves and your mods are not touched.

PORTABLE (nothing installed):
  1. Unzip the "Link Toolbox" folder anywhere (Desktop, Documents, a USB
     stick...).
  2. Double-click  Link Toolbox.bat
  It updates itself too (Updates tab), but a fresh download starts with no
  settings. To install it later: Updates tab > "Install as an app".
  To remove the portable copy, delete its folder.

UPDATES: the Updates tab checks GitHub for a newer version (when the
toolbox opens, unless you turn that off). It only tells you: nothing
changes until you click "Update now", which downloads it, closes the
toolbox, puts the new version in and opens it again. Your settings,
backups and icon are kept.

The first time, it also makes a "Link's Tool Box" shortcut with the toolbox's
icon next to the .bat (a .bat file can't have an icon of its own). Use that
shortcut from then on, or make one on your Desktop in the Look tab.

The first time, the toolbox looks for your game where Triforce installed it.
If it can't find it, it asks once: pick the folder that has Triforce.exe (or longshot.exe)
and the "romfs" folder in it. You can change it later in the Folders tab.

The first time you open the save editor, it reads the item and flag names
from your game files. That takes a little while, but only once.

Needs Windows 10 or 11 and a game built with Triforce (or Longshot, below).

LINUX (the "Link Toolbox (Linux).tar.gz" download):
  1. Unpack it anywhere:  tar xzf "Link Toolbox (Linux).tar.gz"
  2. Open "Link Toolbox.sh" (double-click, or run ./"Link Toolbox.sh").
     Some file managers ask first, or need "Allow launching" / "Run as a
     program" turned on for it.
  It uses this computer's Python, which must be 3.14 or newer with Tk
  (python3-tk / python3-tkinter / tk). If it's missing, the script says
  what to install. On Linux the toolbox works best with Longshot's Linux
  build (saves in ~/.local/share/longshot/save). Triforce or NX2navi run
  through Wine/Proton can be picked in the Folders tab. The slot picture
  needs Pillow, ImageMagick or ffmpeg installed (without them it's left
  out). The first start makes a "Link's Tool Box" launcher next to the script.


-------------------------------------------------------------------------------
 LONGSHOT (EARLY SUPPORT)
-------------------------------------------------------------------------------

Longshot is another PC port of the same game, by MagicBeanDev
(https://git.magicbean.dev/MagicBeanDev/Longshot). It loads mods by the same
rules as Triforce, and its saves look the same, so the Mods tab, the included
mods and the save editor work with it too.

SEVERAL BUILDS (any app: Triforce, Longshot, NX2navi...): some apps put every
build in a new folder (Longshot always does), whose mods folder starts empty.
  New builds: when the toolbox finds a newer build of the app you use, it
  asks to copy your mods across and switch to it (the old build stays as it
  was). Folders tab > "Bring my mods to new builds without asking" does it
  automatically.
  One shared mods folder (optional): Folders tab > "Use one shared mods
  folder..." makes one folder every build of every app uses: each build's
  "mods" folder becomes a link to it (new builds get linked when found).
  "Stop sharing" removes the links (not the shared folder) and can copy the
  mods back into every build.
  Shared saves (optional): Folders tab > "Use one shared saves folder..."
  gives Triforce and Longshot one "user" folder, so both play the same
  saves. You pick whose saves to start from; the others are kept as they
  are, renamed "... (before sharing)", and every save is backed up first.
  "Stop sharing" gives each its own copy again. NX2navi is left out.

Longshot is still in development, so this support is early: a change in
Longshot may need a toolbox update.

To use it: Folders tab > Game folder > pick Longshot's game folder (the one
with longshot.exe, usually Games\Longshot in your user folder) > Apply, then
open the toolbox again. Its saves are found in %APPDATA%\Longshot\save, and
Save and play starts longshot.exe. (If Triforce isn't installed, the toolbox
finds Longshot by itself.)


-------------------------------------------------------------------------------
 THE MODS THAT COME WITH IT
-------------------------------------------------------------------------------

The "mods" folder in this zip has six mods:

  Young Link Mirror Shield     young Link holds the Mirror Shield in his hand
  Young Link Hylian Shield     young Link holds the Hylian Shield in his hand,
                               like the Deku Shield
  Young Link All Items         young Link can pick the adult's items in the
                               menu (big swords, Mirror Shield, hookshot...)
  Biggoron One-Handed          the Biggoron Sword swung with one hand
  Young Link Adult Motions     young Link gets the adult's motions for the big
                               swords, hookshot, bow and hammer
  Young Link Two-Handed Swords the Biggoron Sword swung with both hands
  (comes switched off)         (needs Young Link Adult Motions)

Biggoron One-Handed and Young Link Two-Handed Swords change the same file,
so only one can be on. One-Handed comes on: for two hands, switch it off
and Two-Handed on in the Mods tab, then press Save.

To install them:
  1. Open the toolbox, go to the Mods tab, click "Add mods..." and answer Yes.
  2. Press Save. (That also builds the "~Size Table" for YOUR game.)
  3. Start the game (or press Save and play).

They need the same game version they were made for: The Legend of Zelda:
Ocarina of Time v131072, built with Triforce. On another version
they may crash or not work. Turn them off in the Mods tab at any time.
Tip: give young Link the Master Sword or Biggoron Sword in the save editor's
Inventory tab to try them.


-------------------------------------------------------------------------------
 THE TABS
-------------------------------------------------------------------------------

 MODS
   Game (at the top): whose mods you see - each game's "mods" folder
   (Triforce and NX2navi share one, Longshot has its own), or one kept from
   the Folders tab. Save and play starts that game.
   Lists every mod in that "mods" folder.
     - Tick a mod (or press Space) to turn it on or off.
     - Up / Down sets the order. When two mods replace the same file, the
       LOWER one in the list wins. Clashes are shown in red.
     - Save writes your choice. Save and play writes it and starts the game.
     - Add mods... copies mods in: the ones that came with the toolbox, a
       folder you pick (a mod is a folder with a "romfs" folder inside), or
       a .zip (from HookyCreator or a download).
     - A mod with an exefs part (Switch code: .ips/.pchtxt patches or a
       subsdk plugin) can't run on the PC ports. The toolbox says so and
       offers to add only its romfs part, or to skip it. .rar and .7z work
       like .zip.
     - Or drag mods from Explorer onto the window (Windows): .zip files and
       folders, code mods too. Each is sorted out and added the right way.
     - Code mods... (Longshot): mods that change how the game works, like
       Hyrule Armory. They go into Longshot's own sources, then you press
       Build in the Longshot Launcher (a full build, about as long as the
       first one; about 60 GB free while it runs). The window adds them
       (from their .zip), removes them, and puts them back after a Longshot
       update. It checks every place the mod connects to first: if Longshot
       moved one, nothing is changed. Until you build, the Mods tab shows a
       red line as a reminder.
     - Triforce needs one shared "size table" for mods that make game files
       bigger. The toolbox builds it for you (the "~Size Table" folder) every
       time you press Save. Don't delete or edit it by hand.
   Close the game first: mods can't be switched while it is running, unless you
   tick "Save while the game runs" (Mods and Save editor tabs). The game then
   uses changed mods from its next start, and may write over an edited save.

 SAVE EDITOR
   Pick the Game at the top (Triforce, NX2navi or Longshot: each keeps its
   own saves; the top bar always shows which one you're editing and its
   folder), then a save slot. The summary shows hearts, rupees and
   Gold Skulltula tokens, and the Stats tab shows the picture the game
   took when you last saved.

   Stats
     Heart containers and current hearts (in quarter hearts), the magic meter
     (none / single / double) and current magic, wallet and rupees, bag and
     quiver sizes, ammo and other counts (sticks, nuts, seeds, bombs,
     bombchus, arrows, beans, scrub seeds, skulltula tokens, heart pieces),
     the five bottles and their contents, and small keys for every dungeon.
     Quick buttons: Full hearts, Full magic, Full wallet, Fill all, All keys.
     Age: shows Young Link or Adult Link, and "Switch to adult / young"
     changes it. It works where Link is saved outdoors (Kakariko, Hyrule
     Field, Kokiri Forest, the Market, Lost Woods, Death Mountain, Goron City,
     the Zora areas, Graveyard, Gerudo Valley...): those places have a young
     and an adult map, and he loads into the other age's one. In a dungeon or
     a house both ages share one map, so save outside first.

   Inventory
     All 104 items by their in-game names, with their group (Swords, Shields,
     Clothes, Masks, Gear, Magic, Quest, Trade, Upgrades, Ammo) and the age
     that normally uses them.
       - Give / Take away, or double-click an item.
       - Ctrl-click or Shift-click to pick several at once.
       - "Give everything missing" fills your inventory in one go.
       - Items you have equipped, and the default clothes, can't be taken away.

   Progress
     More than 6,000 on/off story flags (events and cutscenes, talks and
     Navi hints, dungeons, places, items found, mini-games...), searchable and
     filtered by group and by On / Off / Edited. Set on / Set off works on
     several at once. Careful: some quests depend on several flags together.

   All entries
     Every value in the slot's files (progress, file-select summary, options,
     account) for advanced editing. Double-click a value to change it.

   Every list can be sorted: click a column heading, click again to reverse.
   Edited values show in red until you save. "Save and play" saves your edits
   and starts the game (with the mods as set in the Mods tab).
   "Save to..." writes the slot (with your edits) to every save location the
   toolbox finds - Triforce, NX2navi, Longshot, all ticked - and into the
   slot you pick. What was in those slots is copied to the backups first.

 FOLDERS
   Games found: every game the toolbox finds, by app (Triforce, Longshot,
   NX2navi). Pick one and press Apply to play that one: the toolbox opens
   again with its program for Save and play, its mods and its saves.
   Or use a different game folder, mods folder or saves folder. Leave a box
   empty to use the default. Folders you fill in by hand are kept as choices
   (in Games found and in the Mods and Save editor Game lists) while "Keep"
   is ticked. The "Kept choices" list shows them all: "Forget" removes one. (Triforce and Longshot only load mods from the
   "mods" folder in the game folder.)

 LOOK
   Choose a theme (Dark green, Dark grey, Dark blue, Midnight purple, Light),
   an accent colour, and a colour for every tab. Changes show at once and
   are remembered.
   Icon: Link's Tool Box, a Triforce, or a square of any save slot's picture
   (the slider picks which part). "Use this icon" puts it on the window and
   the shortcuts. "Shortcut on the Desktop" makes one there.


-------------------------------------------------------------------------------
 SAFETY
-------------------------------------------------------------------------------

  * CLOSE THE GAME BEFORE SAVING A SAVE. A running game writes over the save
    files when it saves, and your edits would be lost.
  * Every time you save, the old files are first copied into
    app\backups\<date and time>\ . The "Backups folder" button opens it.
    To undo a save, copy the files from there back into your save folder.
  * "Undo all edits" throws away everything you changed since the last save.
  * Hearts, magic and rupees are also written to the slot's caption.sav,
    so the file-select screen shows the same numbers.


-------------------------------------------------------------------------------
 QUESTIONS
-------------------------------------------------------------------------------

 Where are my saves?
   In the game folder, under  user\save\<long number>\slot_00 ... slot_05
   (slot_00 is Slot 1). Longshot started from its launcher keeps them in
   %APPDATA%\Longshot\save\<long number>\ instead.

 I edited my save but nothing changed in the game.
   The game was probably still running and wrote over the save. Close it,
   open the toolbox again, make the edit, press Save, then start the game.

 A mod doesn't show up in the game.
   Check it is ticked in the Mods tab and that you pressed Save. Mods must be
   inside the "mods" folder in the game folder, each in its own folder with
   a "romfs" folder inside. Cheat (.txt) and code mods are not supported by
   Triforce. The Notes column says when a mod isn't a RomFS mod.

 The game won't start after turning on a mod.
   Turn mods off one by one in the Mods tab (press Save each time) to find
   the one causing it.

 Can I move the toolbox folder?
   Yes. Move the whole "Link Toolbox" folder anywhere. Your settings and
   backups go with it (in the app folder).


-------------------------------------------------------------------------------
 WHAT'S INSIDE
-------------------------------------------------------------------------------

  Link Toolbox.bat     starts the toolbox
  Install Link Toolbox.bat   installs it (shortcuts, Windows Settings > Apps)
  README.txt           this file
  app\                 the toolbox itself
     toolbox.pyw         the main window
     mod_loader.pyw      Mods tab (also opens on its own)
     save_editor.pyw     Save editor tab (also opens on its own)
     nxsave.py           reads and writes the save files
     oot_catalog.py      the item list and where each value is kept
     size_table.py       builds the size table for mods
     theme.py            the colours
     jpeg_win.py         shows the slot picture (uses Windows' own decoder)
     icons.py            the icon and the shortcuts
     updater.py          the Updates tab
     install.py          installing and uninstalling
     code_mods.py        code mods for Longshot (code_mods_ui.py: their window)
     dragdrop.py         mods dragged onto the window (Windows)
     builds.py           several builds: mods to new builds, shared folder
     icon.ico, icon.png  the icon in use
  mods\                the five mods above (install with Mods tab > Add mods...)
  python\              the Python the toolbox runs with (no install needed)

  Made by the toolbox: app\backups (save backups), app\names-cache-*.json
  (the names read from your game), app\toolbox_settings.json (your folders
  and colours).


-------------------------------------------------------------------------------
 CREDITS
-------------------------------------------------------------------------------

  Link's Tool Box by Cum_Dumpster.
  Built for the Triforce PC port of Ocarina of Time.
  Python is included under its own license (python\LICENSE.txt).

  This is a fan-made tool, not affiliated with Nintendo. You need your own
  copy of the game. Always keep a backup of saves you care about.

===============================================================================
