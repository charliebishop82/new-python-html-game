import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const sourcePath = "C:/Users/charl/OneDrive/Desktop/bbsgame/data/GameContent_Perks_Worldbosses.xlsx";
const workDir = "C:/Users/charl/OneDrive/Desktop/bbsgame/.codex-work/bbsgame-scenes";

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));

const scenesHeaders = [
  "SceneKey","MovieName","SceneName","SetupText","ProtagonistName","EnemyType","EnemyName","AP_Cost","MinLevel","Weight",
  "CombatObjective","ProtagonistBehavior","EnemyTargeting","ProtagonistKO_FailsScene","EnemyGearRewardChance","ProtagonistGearRewardChance",
  "FirstCompletionXP","FirstCompletionCredits","IsActive","Notes"
];

const scenesRows = [
  ["CONAN_TOWER_SERPENT","Conan the Barbarian","The Tower of the Serpent","Torchlight crawls over the walls of a forbidden tower. Conan waits beside a narrow entrance while cult guards circle the chamber protecting a serpent relic.","Conan","MINION","Snake Cult Warrior",2,1,10,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.18,0.10,45,20,true,"Introductory infiltration scene; a failed approach begins allied combat."],
  ["CONAN_MOUNTAIN_POWER","Conan the Barbarian","The Mountain of Power","Pilgrims crowd the mountain temple while Thulsa Doom addresses his followers. Conan needs an opening, and the wrong move will draw the full attention of the cult.","Conan","BOSS","Thulsa Doom",2,2,6,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.12,0.07,80,35,true,"Harder boss-linked scene intended for characters ready to challenge Thulsa Doom."],
  ["CONAN_BATTLE_MOUNDS","Conan the Barbarian","Battle of the Mounds","The old stone mounds have become a killing ground. Conan takes position among the traps as a Snake Cult warrior advances through the fog.","Conan","MINION","Snake Cult Warrior",2,1,8,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.20,0.11,55,25,true,"Direct defensive scene with several viable preparations."],
  ["ROBOCOP_STORE_ALARM","RoboCop","Night Shift Alarm","A silent alarm leads into a wrecked Old Detroit storefront. RoboCop advances through the front while Boddicker watches from behind overturned shelving.","RoboCop","MINION","Clarence Boddicker",2,2,9,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.18,0.10,55,25,true,"Urban confrontation with Boddicker and environmental choices."],
  ["ROBOCOP_BOARDROOM_TEST","RoboCop","Boardroom Malfunction","An OCP demonstration has gone catastrophically wrong. ED-209 is tracking movement across the boardroom while RoboCop searches for a safe firing angle.","RoboCop","BOSS","ED-209",2,4,5,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.11,0.06,95,45,true,"High-risk mechanical boss scene."],
  ["ROBOCOP_FACTORY_RAID","RoboCop","Factory Raid","The abandoned factory is filled with catwalks, chemical drums, and armed lookouts. RoboCop signals that Boddicker is inside and the exits are closing.","RoboCop","MINION","Clarence Boddicker",2,3,8,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.20,0.11,65,30,true,"Tactical raid with multiple routes into allied combat."],
  ["ALIENS_OPERATIONS_LOCKDOWN","Aliens","Operations Lockdown","Motion alarms echo through the colony operations room. Ripley braces the inner door while a Warrior Drone searches the ceiling above the failing barricade.","Ellen Ripley","MINION","Warrior Drone",2,3,9,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.18,0.10,65,30,true,"Defensive survival scene; failed preparations let the drone breach."],
  ["ALIENS_REACTOR_RESCUE","Aliens","Reactor Rescue","Emergency lights pulse along the reactor access corridor. Ripley is moving toward trapped survivors, but a Warrior Drone blocks the only direct route.","Ellen Ripley","MINION","Warrior Drone",2,4,8,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.20,0.11,75,35,true,"Rescue-flavored encounter with physical and investigative approaches."],
  ["ALIENS_QUEEN_CHAMBER","Aliens","The Queen's Chamber","Heat and vapor roll across a chamber filled with eggs. Ripley raises her pulse rifle as the Xenomorph Queen turns toward the intruders.","Ellen Ripley","BOSS","Xenomorph Queen",2,5,4,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.10,0.06,120,55,true,"Advanced boss scene; protagonist gear remains rare."],
];

const choicesHeaders = [
  "SceneKey","ChoiceKey","Attribute","ChoiceText","Difficulty","SuccessText","FailureText","SuccessXP","SuccessCredits",
  "SuccessEffect","SuccessValue","FailureEffect","FailureValue","CombatOnFailure","RewardChanceModifier","Notes"
];

const choicesRows = [
  ["CONAN_TOWER_SERPENT","BREAK_GATE","STR","Tear the rusted gate from its hinges before the patrol returns.",11,"The gate gives way silently enough for Conan to lead you inside.","The metal crashes across the floor and a cult warrior charges toward the noise.",22,8,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0,"Strength creates an opening-round advantage on success."],
  ["CONAN_TOWER_SERPENT","HOLD_CHAIN","END","Hold the counterweight while Conan crosses the suspended passage.",12,"You endure the strain until Conan secures the mechanism.","Your grip fails and the passage drops into the guard chamber.",24,8,"ALLY_BUFF",1,"COMBAT",0,true,0,"Endurance success improves the protagonist's opening defense."],
  ["CONAN_TOWER_SERPENT","CROSS_LEDGE","AGI","Cross the outer ledge and lower a rope from above.",10,"You reach the upper window without disturbing the sentries.","Loose stone breaks away and carries you into the chamber below.",20,10,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Agility is the favored approach."],
  ["CONAN_TOWER_SERPENT","TRUST_SHADOW","LCK","Trust the shifting torchlight and walk through the patrol gap.",13,"The guards turn at precisely the wrong moment and you pass unseen.","A guard steps from an alcove that looked empty a heartbeat earlier.",28,12,"BONUS_CREDITS",5,"COMBAT",0,true,0.03,"Riskier approach with a better reward modifier."],
  ["CONAN_TOWER_SERPENT","READ_MARKS","PER","Study the floor dust and cult markings for the true entrance.",9,"You identify the route used by the inner guard and avoid the trap.","The marks are deliberately misleading and lead into an ambush.",24,9,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.01,"Perception is highly effective here."],

  ["CONAN_MOUNTAIN_POWER","CHALLENGE_GUARDS","STR","Force a path through the outer guard before the crowd closes ranks.",15,"Your sudden violence scatters the guards and gives Conan a clear route.","The crowd surrounds you as Thulsa Doom turns his attention your way.",40,15,"FIRST_STRIKE",1,"COMBAT",0,true,0.01,"Direct but difficult."],
  ["CONAN_MOUNTAIN_POWER","ENDURE_RITE","END","Submit to the exhausting mountain rite long enough to reach the inner circle.",14,"You withstand the ordeal and enter the temple beside the faithful.","Your strength gives out at the worst moment and the cult exposes you.",38,14,"ALLY_BUFF",1,"COMBAT",0,true,0,"Endurance infiltration."],
  ["CONAN_MOUNTAIN_POWER","CLIMB_TEMPLE","AGI","Climb the temple face beyond the view of the pilgrims.",13,"You reach the high gallery and signal Conan to advance.","A handhold shears away and your fall alerts the temple.",36,16,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.01,"Agility offers a strong route."],
  ["CONAN_MOUNTAIN_POWER","BLEND_PILGRIMS","LCK","Take a discarded robe and gamble that nobody questions another pilgrim.",16,"The procession carries you directly past the guards.","The robe belongs to someone the guards know, and the deception collapses.",46,20,"BONUS_CREDITS",10,"COMBAT",0,true,0.04,"Highest-risk option."],
  ["CONAN_MOUNTAIN_POWER","FIND_CONTROL","PER","Watch the crowd and identify how Thulsa Doom controls its movement.",12,"You find the signal controlling the guards and create a moment of confusion.","You mistake ceremony for command and walk into the guarded aisle.",38,15,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.02,"Perception is favored."],

  ["CONAN_BATTLE_MOUNDS","SET_BOULDER","STR","Move a fallen boulder into the narrowest approach.",11,"The new barrier funnels the warrior directly into Conan's reach.","The boulder rolls wide and reveals your position.",26,10,"ENEMY_DEBUFF",1,"COMBAT",0,true,0,"Battle preparation."],
  ["CONAN_BATTLE_MOUNDS","HOLD_GROUND","END","Stand openly at the center mound and absorb the first assault.",12,"You refuse to yield and the warrior loses momentum.","The impact drives you from the mound before Conan can intervene.",28,10,"PLAYER_GUARD",1,"COMBAT",2,true,0,"Failure value represents opening HP loss."],
  ["CONAN_BATTLE_MOUNDS","RIG_TRAP","AGI","Reset the old rope trap before the warrior reaches the stones.",10,"The trap catches cleanly and leaves the enemy exposed.","The knot slips and the warrior charges through it untouched.",25,12,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Favored approach."],
  ["CONAN_BATTLE_MOUNDS","BAIT_CHARGE","LCK","Leave one opening and trust the warrior to choose it.",13,"The warrior commits to the exact path you prepared.","The warrior notices the bait and attacks from the fog instead.",32,14,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.03,"Risk-reward option."],
  ["CONAN_BATTLE_MOUNDS","READ_FOG","PER","Track movement through the fog by sound and disturbed grass.",10,"You call the attack a moment before it begins.","Echoes among the stones send your warning in the wrong direction.",27,11,"ALLY_BUFF",1,"COMBAT",0,true,0.01,"Perception preparation."],

  ["ROBOCOP_STORE_ALARM","SHIFT_DISPLAY","STR","Shove a steel display across Boddicker's firing lane.",12,"The barrier forces Boddicker into RoboCop's line of fire.","The display catches on broken flooring and leaves you exposed.",26,10,"ENEMY_DEBUFF",1,"COMBAT",0,true,0,"Environmental control."],
  ["ROBOCOP_STORE_ALARM","DRAW_FIRE","END","Draw Boddicker's attention while RoboCop advances.",13,"You weather the opening fire and RoboCop closes the distance.","A shot catches you before RoboCop can cover the aisle.",30,10,"ALLY_BUFF",1,"COMBAT",3,true,0,"Failure opens with HP loss."],
  ["ROBOCOP_STORE_ALARM","FLANK_AISLE","AGI","Slip through the narrow service aisle and attack from the side.",11,"You emerge behind Boddicker and deny him his prepared position.","Broken glass betrays your approach and Boddicker pivots toward you.",27,12,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Agility favored."],
  ["ROBOCOP_STORE_ALARM","RICOCHET_DISTRACTION","LCK","Kick loose debris toward the alarm sensor and trust the noise to distract him.",14,"The alarm erupts again and Boddicker fires at the wrong movement.","The debris rolls harmlessly past the sensor.",34,14,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.03,"Uncertain but rewarding."],
  ["ROBOCOP_STORE_ALARM","TRACK_REFLECTION","PER","Use the security mirrors to locate Boddicker without exposing yourself.",10,"His reflection gives away both his position and weapon hand.","A cracked mirror shows an old reflection and sends you into the open.",28,11,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.01,"Perception favored."],

  ["ROBOCOP_BOARDROOM_TEST","JAM_LEG","STR","Drive a conference table into ED-209's leg assembly.",16,"The impact catches a joint and slows the machine's first turn.","The table splinters against the armored chassis.",48,18,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.01,"Hard physical solution."],
  ["ROBOCOP_BOARDROOM_TEST","CARRY_EXECUTIVE","END","Carry an injured executive through the machine's firing zone.",15,"You reach cover and give RoboCop freedom to engage.","The crossing takes too long and ED-209 acquires both targets.",44,18,"ALLY_BUFF",1,"COMBAT",4,true,0,"Protective endurance choice."],
  ["ROBOCOP_BOARDROOM_TEST","REACH_STAIRS","AGI","Sprint for the stairwell before ED-209 finishes turning.",13,"The machine struggles with the steps and exposes its rear armor.","Its cannons track faster than expected.",42,20,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Canonical environmental weakness without quoting dialogue."],
  ["ROBOCOP_BOARDROOM_TEST","TRIGGER_DEMO","LCK","Trigger another presentation system and hope its signal confuses ED-209.",17,"The overlapping signals divide its targeting system.","The machine treats the new signal as confirmation of a threat.",54,25,"ENEMY_DEBUFF",2,"COMBAT",0,true,0.05,"High-risk option."],
  ["ROBOCOP_BOARDROOM_TEST","FIND_MAINTENANCE","PER","Locate the emergency maintenance controls in the wall console.",14,"You interrupt a targeting cycle and give RoboCop an opening.","The controls require authorization you do not have.",46,20,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.02,"Technical observation."],

  ["ROBOCOP_FACTORY_RAID","BREAK_CATWALK","STR","Drop a catwalk section behind Boddicker and seal his retreat.",14,"The collapsing steel cuts off the rear exit.","The supports fall toward you instead and announce the raid.",35,14,"ENEMY_DEBUFF",1,"COMBAT",0,true,0,"Factory environment."],
  ["ROBOCOP_FACTORY_RAID","CROSS_CHEMICALS","END","Push through the chemical vapor to reach the control room.",14,"You hold your breath long enough to unlock the side entrance.","The vapor overwhelms you and Boddicker hears the alarm.",36,14,"ALLY_BUFF",1,"COMBAT",3,true,0,"Endurance path."],
  ["ROBOCOP_FACTORY_RAID","CATWALK_FLANK","AGI","Move across the overhead catwalk while RoboCop advances below.",12,"You reach Boddicker's flank before he sees the second attacker.","A loose grate crashes to the floor beneath you.",34,16,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Agility favored."],
  ["ROBOCOP_FACTORY_RAID","START_CONVEYOR","LCK","Hit an unlabeled factory switch and trust the machinery to create cover.",15,"A conveyor roars to life and divides Boddicker's crew.","The switch activates every warning light in the building.",42,20,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.04,"Chaotic machinery gamble."],
  ["ROBOCOP_FACTORY_RAID","READ_TRACKS","PER","Trace fresh boot marks and shell casings to Boddicker's position.",11,"The evidence reveals his ambush before it closes.","Old tracks lead you toward an empty office.",35,15,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.01,"Investigation favored."],

  ["ALIENS_OPERATIONS_LOCKDOWN","HOLD_BULKHEAD","STR","Hold the damaged bulkhead while Ripley secures its lock.",14,"The lock catches and forces the drone through a predictable breach.","The frame twists out of your grip and the drone tears through.",34,14,"ENEMY_DEBUFF",1,"COMBAT",0,true,0,"Physical defense."],
  ["ALIENS_OPERATIONS_LOCKDOWN","KEEP_PRESSURE","END","Maintain pressure on the failing door controls despite the heat.",13,"The circuit remains alive long enough for Ripley to prepare.","The panel burns through your glove and the door releases.",34,14,"ALLY_BUFF",1,"COMBAT",3,true,0,"Endurance defense."],
  ["ALIENS_OPERATIONS_LOCKDOWN","SEAL_VENT","AGI","Climb the equipment racks and seal the ceiling vent.",12,"You close the vent and drive the drone into Ripley's firing lane.","The drone reaches the opening before you do.",32,16,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Agility favored."],
  ["ALIENS_OPERATIONS_LOCKDOWN","TRUST_SENSOR","LCK","Choose one motion-sensor contact and commit before it resolves.",15,"You choose correctly and catch the drone changing direction.","The contact is an echo; the real threat drops behind you.",42,20,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.04,"Sensor gamble."],
  ["ALIENS_OPERATIONS_LOCKDOWN","MAP_DUCTS","PER","Compare the sensor pattern with the colony duct map.",11,"You predict the exact vent the drone will use.","The damaged map omits a maintenance shaft.",35,15,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.01,"Perception favored."],

  ["ALIENS_REACTOR_RESCUE","CLEAR_DEBRIS","STR","Lift a collapsed support away from the shortest route.",15,"You clear the passage before the drone can circle back.","The support shifts and traps you in the drone's path.",38,16,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0,"Rescue strength."],
  ["ALIENS_REACTOR_RESCUE","CROSS_STEAM","END","Push through the steam-filled maintenance corridor.",14,"You endure the heat and open the route for Ripley.","The heat forces you back as the drone closes in.",38,16,"ALLY_BUFF",1,"COMBAT",3,true,0,"Endurance route."],
  ["ALIENS_REACTOR_RESCUE","CRAWL_CONDUIT","AGI","Take the narrow service conduit above the reactor floor.",12,"You reach the far side and draw the drone beneath Ripley's rifle.","The conduit buckles and drops you into the open.",36,18,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Agility favored."],
  ["ALIENS_REACTOR_RESCUE","OPEN_UNKNOWN_DOOR","LCK","Open an unmarked pressure door and trust it reconnects with the rescue route.",16,"The door reveals a protected service corridor.","It opens into a chamber already occupied by the drone.",46,22,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.05,"High-risk exploration."],
  ["ALIENS_REACTOR_RESCUE","FOLLOW_RESIDUE","PER","Follow fresh resin and acid scoring to predict the drone's route.",12,"The signs reveal where it will intercept the survivors.","The residue belongs to an older passage and delays you.",39,17,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.02,"Perception route."],

  ["ALIENS_QUEEN_CHAMBER","THREATEN_EGGS","STR","Smash the nearest egg cluster and force the Queen to react.",17,"The Queen turns from Ripley and exposes her flank.","The chamber erupts with movement before you gain position.",58,22,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Dangerous provocation."],
  ["ALIENS_QUEEN_CHAMBER","HOLD_LINE","END","Hold the narrow approach while Ripley prepares her weapon.",16,"You withstand the Queen's advance long enough for Ripley to fire first.","The Queen crashes through your guard and separates you.",56,22,"ALLY_BUFF",2,"COMBAT",5,true,0,"Endurance protection."],
  ["ALIENS_QUEEN_CHAMBER","CIRCLE_SAC","AGI","Circle the egg chamber and attack from beyond the Queen's crest.",15,"You reach the blind angle and divide her attention.","Her tail catches the route before you clear it.",54,24,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.03,"Agility approach."],
  ["ALIENS_QUEEN_CHAMBER","RISK_FLAME","LCK","Fire near the egg chamber controls and gamble that the Queen retreats.",18,"The flames spread in a line that drives the Queen away from Ripley.","The fire cuts off your own escape route instead.",68,30,"ENEMY_DEBUFF",2,"COMBAT",0,true,0.06,"Highest-risk choice."],
  ["ALIENS_QUEEN_CHAMBER","READ_POSTURE","PER","Watch the Queen's crest, tail, and inner jaws for the instant before she attacks.",14,"You recognize her attack posture and warn Ripley in time.","The Queen feints and strikes from a different angle.",56,24,"ALLY_BUFF",1,"COMBAT",0,true,0.02,"Perception favored."],
];

const scenes = workbook.worksheets.add("Scenes");
scenes.getRangeByIndexes(0, 0, scenesRows.length + 1, scenesHeaders.length).values = [scenesHeaders, ...scenesRows];
const scenesTable = scenes.tables.add(`A1:T${scenesRows.length + 1}`, true, "ScenesTable");
scenesTable.style = "TableStyleMedium2";
scenes.showGridLines = false;
scenes.freezePanes.freezeRows(1);

const choices = workbook.worksheets.add("SceneChoices");
choices.getRangeByIndexes(0, 0, choicesRows.length + 1, choicesHeaders.length).values = [choicesHeaders, ...choicesRows];
const choicesTable = choices.tables.add(`A1:P${choicesRows.length + 1}`, true, "SceneChoicesTable");
choicesTable.style = "TableStyleMedium2";
choices.showGridLines = false;
choices.freezePanes.freezeRows(1);

for (const [sheet, cols, rows] of [[scenes, scenesHeaders.length, scenesRows.length + 1], [choices, choicesHeaders.length, choicesRows.length + 1]]) {
  const used = sheet.getRangeByIndexes(0, 0, rows, cols);
  used.format.font = { typeface: "Calibri", fontSize: 9 };
  used.format.verticalAlignment = "top";
  used.format.wrapText = true;
  const header = sheet.getRangeByIndexes(0, 0, 1, cols);
  header.format = {
    fill: "#1F3864",
    font: { typeface: "Calibri", fontSize: 9, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: "#CCCCCC" },
    rowHeight: 32,
  };
  sheet.getRangeByIndexes(1, 0, rows - 1, cols).format.rowHeight = 48;
}

// Widths are deliberately capped so descriptive text wraps without creating an unusably wide sheet.
for (const [range, width] of [["A:A",22],["B:B",21],["C:C",24],["D:D",55],["E:G",21],["H:J",10],["K:M",22],["N:N",15],["O:P",18],["Q:S",18],["T:T",42]]) scenes.getRange(range).format.columnWidth = width;
for (const [range, width] of [["A:A",22],["B:B",20],["C:C",10],["D:D",50],["E:E",10],["F:G",55],["H:I",14],["J:J",22],["K:K",14],["L:L",20],["M:M",14],["N:N",16],["O:O",18],["P:P",38]]) choices.getRange(range).format.columnWidth = width;

scenes.getRange(`H2:J${scenesRows.length + 1}`).format.numberFormat = "0";
scenes.getRange(`O2:P${scenesRows.length + 1}`).format.numberFormat = "0%";
scenes.getRange(`Q2:R${scenesRows.length + 1}`).format.numberFormat = "0";
choices.getRange(`E2:E${choicesRows.length + 1}`).format.numberFormat = "0";
choices.getRange(`H2:I${choicesRows.length + 1}`).format.numberFormat = "0";
choices.getRange(`O2:O${choicesRows.length + 1}`).format.numberFormat = "0%";

const outputDir = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/019fc439-d617-7783-a9b4-5347c2d0bf25";
await fs.mkdir(outputDir, { recursive: true });

const scenesCheck = await workbook.inspect({ kind: "table", sheetId: "Scenes", range: "A1:T10", include: "values,formulas", tableMaxRows: 12, tableMaxCols: 20, maxChars: 8000 });
const choicesCheck = await workbook.inspect({ kind: "table", sheetId: "SceneChoices", range: "A1:P16", include: "values,formulas", tableMaxRows: 18, tableMaxCols: 16, maxChars: 10000 });
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" });
console.log(scenesCheck.ndjson);
console.log(choicesCheck.ndjson);
console.log(errors.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/GameContent_Perks_Worldbosses_with_Scenes.xlsx`);
await output.save(sourcePath);
console.log(`Saved ${scenesRows.length} scenes and ${choicesRows.length} choices.`);
