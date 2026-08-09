import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const sourcePath = "C:/Users/charl/OneDrive/Desktop/bbsgame/data/GameContent_Perks_Worldbosses.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));

const scenesRows = [
  ["HIGHLANDER_GARAGE_DUEL","Highlander","Steel Beneath the City","An underground garage rings with the scrape of drawn steel. Connor MacLeod recognizes the stance of a Hired Sword blocking the only ramp to the street.","Connor MacLeod","MINION","Hired Sword",2,5,8,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.18,0.10,75,35,true,"Close-quarters sword encounter beneath the city."],
  ["HIGHLANDER_ROOFTOP_STORM","Highlander","Storm Over the Rooftops","Lightning builds above the skyline as The Kurgan steps onto a rain-swept rooftop. Connor draws his katana while loose signs and cables whip through the wind.","Connor MacLeod","BOSS","The Kurgan",2,6,4,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.10,0.06,125,55,true,"Advanced rooftop confrontation with environmental hazards."],
  ["DREDD_PEACH_TREES_LOCKDOWN","Dredd","Peach Trees Lockdown","Blast doors seal the level and every public screen flashes a gang warning. Judge Dredd advances down the central concourse while Kay directs fire from a fortified storefront.","Judge Dredd","MINION","Kay",2,5,8,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.18,0.10,75,35,true,"Block-war scene with cover, surveillance, and civilian danger."],
  ["DREDD_PENTHOUSE_ASSAULT","Dredd","The Slo-Mo Penthouse","Golden dust hangs in the penthouse air, stretching every movement into a dream. Ma-Ma watches from behind reinforced glass as Judge Dredd searches for a clean approach.","Judge Dredd","BOSS","Ma-Ma",2,6,4,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.10,0.06,125,55,true,"Boss confrontation shaped by distorted perception and fortified terrain."],
  ["DARKKNIGHT_NARROWS_HUNT","The Dark Knight","Hunt Through the Narrows","Police sirens fade beneath the elevated tracks. Batman spots Victor Zsasz moving through a condemned tenement, using frightened residents as cover.","Batman","MINION","Victor Zsasz",2,6,8,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.18,0.10,80,38,true,"Investigation and pursuit scene with a dangerous hostage-taker."],
  ["DARKKNIGHT_FERRY_GAMBIT","The Dark Knight","The Ferry Gambit","Two ferries drift in the black water while a timer counts down across a hijacked signal. Batman searches the waterfront as The Joker prepares to enforce his impossible choice.","Batman","BOSS","The Joker",2,7,4,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.10,0.06,135,60,true,"High-stakes boss scene involving deception, explosives, and public panic."],
  ["PREDATOR_JUNGLE_KILLZONE","Predator","Jungle Kill Zone","The jungle has gone unnaturally quiet. Dutch signals toward a shimmer moving between the trees as a Jungle Hunter Scout circles the team's exposed flank.","Dutch","MINION","Jungle Hunter Scout",2,6,8,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.18,0.10,85,40,true,"Tracking and counter-ambush scene against a cloaked hunter."],
  ["PREDATOR_FINAL_HUNT","Predator","The Final Hunt","Night settles over a field of mud, traps, and burning timber. Dutch waits beside you as The Predator abandons stealth and approaches for the final hunt.","Dutch","BOSS","The Predator",2,7,4,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,0.10,0.06,140,65,true,"Advanced boss scene built around traps and survival tactics."],
];

const choicesRows = [
  ["HIGHLANDER_GARAGE_DUEL","SHIFT_VEHICLE","STR","Push an abandoned car into the duelist's escape route.",14,"The vehicle rolls across the ramp and traps the Hired Sword in Connor's reach.","The parking brake catches and the duelist charges while you strain against it.",38,15,"ENEMY_DEBUFF",1,"COMBAT",0,true,0,"Strength controls the battlefield."],
  ["HIGHLANDER_GARAGE_DUEL","TAKE_OPENING","END","Absorb the first rush and hold the narrow lane for Connor.",14,"You withstand the assault and give Connor room to counterattack.","The sustained attack drives you backward into a concrete pillar.",40,15,"ALLY_BUFF",1,"COMBAT",3,true,0,"Failure begins with minor HP loss."],
  ["HIGHLANDER_GARAGE_DUEL","VAULT_BARRIER","AGI","Vault the divider and close from the duelist's blind side.",12,"You land behind the Hired Sword and force him to split his attention.","Your boot clips the rail and announces the maneuver.",37,17,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Agility is favored."],
  ["HIGHLANDER_GARAGE_DUEL","TRIGGER_ALARM","LCK","Strike a random vehicle and trust its alarm to hide your movement.",15,"A chorus of alarms erupts and masks Connor's approach.","Only one weak horn sounds, pointing directly to your position.",46,21,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.04,"Risk-reward distraction."],
  ["HIGHLANDER_GARAGE_DUEL","READ_REFLECTION","PER","Use windshields and mirrors to track the duelist's footwork.",12,"The reflections reveal his intended lunge before it begins.","A shattered mirror feeds you a false angle.",39,16,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.01,"Perception is favored."],

  ["HIGHLANDER_ROOFTOP_STORM","TEAR_SUPPORT","STR","Tear loose a sign support and deny The Kurgan the center of the roof.",17,"The falling frame forces The Kurgan toward Connor's blade.","The support twists in your hands and opens your guard.",60,24,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.02,"Difficult environmental attack."],
  ["HIGHLANDER_ROOFTOP_STORM","GROUND_LIGHTNING","END","Hold a grounding cable in place while the storm breaks overhead.",16,"The charge passes safely into the roof and Connor keeps his footing.","The cable tears free and the shock leaves you reeling.",58,24,"ALLY_BUFF",2,"COMBAT",5,true,0,"Endurance protection with opening damage on failure."],
  ["HIGHLANDER_ROOFTOP_STORM","CROSS_GIRDERS","AGI","Cross the wet girders and reach The Kurgan's flank.",15,"You cross before the next lightning flash and divide his attention.","Your footing slips and The Kurgan turns toward the noise.",56,26,"FIRST_STRIKE",1,"COMBAT",0,true,0.03,"Agility route."],
  ["HIGHLANDER_ROOFTOP_STORM","CUT_RANDOM_CABLE","LCK","Cut one of the whipping support cables and gamble on where it falls.",18,"The cable coils around rooftop machinery and blocks The Kurgan's charge.","It lashes across your own escape route.",70,32,"ENEMY_DEBUFF",2,"COMBAT",0,true,0.06,"Highest-risk choice."],
  ["HIGHLANDER_ROOFTOP_STORM","WATCH_STANCE","PER","Study The Kurgan's stance through the rain and call his opening attack.",14,"You identify the feint and warn Connor before the true swing.","The Kurgan changes rhythm at the final instant.",58,25,"ALLY_BUFF",1,"COMBAT",0,true,0.02,"Perception is favored."],

  ["DREDD_PEACH_TREES_LOCKDOWN","MOVE_BARRICADE","STR","Drag a concrete divider across Kay's strongest firing lane.",14,"The divider seals the lane and lets Dredd advance under cover.","The divider catches on debris and Kay opens fire.",40,16,"ENEMY_DEBUFF",1,"COMBAT",0,true,0,"Strength creates cover."],
  ["DREDD_PEACH_TREES_LOCKDOWN","SHIELD_CIVILIANS","END","Hold position between the gunfire and fleeing residents.",15,"You keep the corridor protected until Dredd clears the crossfire.","The sustained fire breaks your stance before the corridor empties.",44,16,"ALLY_BUFF",1,"COMBAT",4,true,0,"Protective endurance choice."],
  ["DREDD_PEACH_TREES_LOCKDOWN","SERVICE_SHAFT","AGI","Climb through a maintenance shaft above the barricade.",12,"You emerge behind Kay and signal Dredd to strike.","A loose panel falls into the concourse below.",40,18,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Agility is favored."],
  ["DREDD_PEACH_TREES_LOCKDOWN","HIJACK_LIFT","LCK","Call a damaged lift and gamble that it stops on the correct level.",16,"The doors open behind Kay's position and create a perfect distraction.","The lift arrives full of armed gang members.",50,22,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.05,"High-risk building-system gamble."],
  ["DREDD_PEACH_TREES_LOCKDOWN","TRACE_CAMERAS","PER","Follow the security-camera blind spots to Kay's command post.",12,"You map the gang's surveillance gap and guide Dredd through it.","A hidden camera catches your movement and warns Kay.",42,17,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.01,"Perception is favored."],

  ["DREDD_PENTHOUSE_ASSAULT","BREAK_GLASS","STR","Shatter a damaged section of reinforced glass before Ma-Ma repositions.",17,"The panel collapses inward and gives Dredd a direct firing lane.","The glass holds and Ma-Ma marks your position.",62,25,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Direct boss approach."],
  ["DREDD_PENTHOUSE_ASSAULT","RESIST_SLOMO","END","Fight through the Slo-Mo haze and keep Dredd oriented.",16,"You maintain focus and guide both of you through the distorted room.","Your reactions slow until Ma-Ma seems impossibly fast.",60,25,"ALLY_BUFF",2,"COMBAT",5,true,0,"Failure opens with HP loss."],
  ["DREDD_PENTHOUSE_ASSAULT","CROSS_BALCONY","AGI","Cross the exposed balcony between Ma-Ma's firing cycles.",15,"You reach the side entrance before her weapon tracks back.","The stretched perception ruins your timing.",58,27,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.03,"Agility approach."],
  ["DREDD_PENTHOUSE_ASSAULT","FIRE_BLIND","LCK","Fire through the golden haze at the shadow you think is Ma-Ma.",18,"The shot breaks a control panel and strips away her cover.","The shadow is a reflection and your shot reveals your angle.",72,33,"ENEMY_DEBUFF",2,"COMBAT",0,true,0.06,"Highest-risk option."],
  ["DREDD_PENTHOUSE_ASSAULT","TRACK_PARTICLES","PER","Watch how the airborne particles move around Ma-Ma's position.",14,"The currents reveal her movement behind the glass.","Ventilation turbulence creates a convincing false trail.",60,26,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.02,"Perception is favored."],

  ["DARKKNIGHT_NARROWS_HUNT","FORCE_DOOR","STR","Break through the sealed apartment door before Zsasz moves his hostage.",15,"The lock gives way and Batman enters beside you.","The frame jams halfway and warns Zsasz.",42,18,"FIRST_STRIKE",1,"COMBAT",0,true,0,"Fast forced entry."],
  ["DARKKNIGHT_NARROWS_HUNT","HOLD_STAIRWELL","END","Hold the crumbling stairwell while residents escape past you.",15,"You keep the route open until Batman clears the upper floor.","The damaged steps collapse and leave you exposed below.",44,18,"ALLY_BUFF",1,"COMBAT",4,true,0,"Protective approach."],
  ["DARKKNIGHT_NARROWS_HUNT","FIRE_ESCAPE","AGI","Scale the fire escape and enter above Zsasz's position.",13,"You reach the landing silently and block the rooftop exit.","A rusted rung snaps and sends noise through the alley.",42,20,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.02,"Agility is favored."],
  ["DARKKNIGHT_NARROWS_HUNT","CUT_POWER","LCK","Cut power to one section and gamble that Zsasz loses sight of the exits.",16,"Darkness isolates Zsasz while Batman's equipment keeps tracking him.","Emergency lights illuminate your approach instead.",52,24,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.05,"Risky building-control choice."],
  ["DARKKNIGHT_NARROWS_HUNT","READ_TALLIES","PER","Study the pattern of Zsasz's markings and predict where he will stage the confrontation.",12,"The pattern points toward the unfinished top floor.","The clues were deliberately placed to lead pursuers away.",44,19,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.01,"Investigation is favored."],

  ["DARKKNIGHT_FERRY_GAMBIT","MOVE_DEBRIS","STR","Clear a collapsed waterfront barrier so Batman can reach the transmitter.",17,"The path opens and Batman closes on The Joker's signal.","The barrier shifts loudly and reveals your approach.",66,27,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.02,"Physical route."],
  ["DARKKNIGHT_FERRY_GAMBIT","CARRY_TECHNICIAN","END","Carry an injured technician to the signal controls under fire.",16,"The technician reaches the console and narrows the broadcast source.","The crossing takes too long and the timer advances.",64,27,"ALLY_BUFF",2,"COMBAT",5,true,0,"Endurance rescue."],
  ["DARKKNIGHT_FERRY_GAMBIT","CROSS_CRANE","AGI","Cross a loading crane above the waterfront patrols.",15,"You reach the transmitter platform without drawing attention.","The crane shifts and The Joker spots the movement.",62,29,"FIRST_STRIKE",1,"COMBAT",0,true,0.03,"Agility approach."],
  ["DARKKNIGHT_FERRY_GAMBIT","CHOOSE_WIRE","LCK","Cut one unmarked wire and gamble that it interrupts the detonator relay.",19,"The ferry timers freeze and The Joker loses his leverage.","The timer accelerates and forces an immediate confrontation.",78,36,"ENEMY_DEBUFF",2,"COMBAT",0,true,0.07,"Extremely risky option."],
  ["DARKKNIGHT_FERRY_GAMBIT","TRACE_SIGNAL","PER","Separate The Joker's false broadcasts from the live detonator signal.",14,"You isolate the true source and guide Batman directly to it.","A repeating decoy signal sends you to the wrong pier.",64,28,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.02,"Perception is favored."],

  ["PREDATOR_JUNGLE_KILLZONE","MOVE_LOG","STR","Roll a fallen log across the scout's clearest firing corridor.",15,"The barrier forces the hunter down into Dutch's line of fire.","The log catches in tangled roots and exposes your effort.",46,20,"ENEMY_DEBUFF",1,"COMBAT",0,true,0,"Strength reshapes the terrain."],
  ["PREDATOR_JUNGLE_KILLZONE","ENDURE_HEAT","END","Remain motionless in the suffocating heat until the shimmer passes close.",15,"You endure the wait and signal Dutch at the perfect moment.","Your breathing betrays you before the hunter enters the trap.",48,20,"ALLY_BUFF",1,"COMBAT",4,true,0,"Endurance ambush."],
  ["PREDATOR_JUNGLE_KILLZONE","CANOPY_ROUTE","AGI","Move through the canopy beyond the scout's thermal sweep.",13,"You reach the hunter's flank without touching the jungle floor.","A branch breaks and the scout turns its plasma caster upward.",46,22,"FIRST_STRIKE",1,"COMBAT",0,true,0.02,"Agility is favored."],
  ["PREDATOR_JUNGLE_KILLZONE","THROW_STONE","LCK","Throw a stone into the brush and gamble on which heat source the scout follows.",16,"The scout tracks the false movement and enters Dutch's kill zone.","The stone strikes metal and reveals the trap.",56,26,"COMBAT_ADVANTAGE",1,"COMBAT",0,true,0.05,"Risky misdirection."],
  ["PREDATOR_JUNGLE_KILLZONE","SPOT_SHIMMER","PER","Watch the rain and leaves for the outline of the cloaking field.",12,"The distorted droplets reveal the scout's exact path.","Moving foliage creates a false silhouette.",48,21,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.01,"Perception is favored."],

  ["PREDATOR_FINAL_HUNT","RAISE_DEADFALL","STR","Raise the heavy deadfall while Dutch resets its trigger.",17,"The trap locks into place and narrows The Predator's approach.","The support slips and crashes before the hunter arrives.",68,30,"ENEMY_DEBUFF",2,"COMBAT",0,true,0.02,"Powerful trap preparation."],
  ["PREDATOR_FINAL_HUNT","HIDE_IN_MUD","END","Remain buried in cold mud while The Predator scans the clearing.",16,"You suppress every movement until the hunter steps into range.","The cold forces a shiver that appears in thermal vision.",66,30,"ALLY_BUFF",2,"COMBAT",5,true,0,"Survival endurance."],
  ["PREDATOR_FINAL_HUNT","SWING_TRAP","AGI","Cross the clearing by rope and arm the suspended-log trap in motion.",15,"You complete the swing before The Predator can track you.","The rope snags and leaves you hanging in view.",64,32,"FIRST_STRIKE",1,"COMBAT",0,true,0.03,"Agility trap setup."],
  ["PREDATOR_FINAL_HUNT","IMITATE_CALL","LCK","Imitate a jungle call and gamble that the hunter reads it as a challenge.",18,"The Predator abandons cover and enters the prepared ground.","The imitation sounds wrong and draws immediate plasma fire.",80,38,"COMBAT_ADVANTAGE",2,"COMBAT",0,true,0.06,"High-risk provocation."],
  ["PREDATOR_FINAL_HUNT","MAP_ESCAPE","PER","Study broken branches, blood marks, and heat distortion to predict the hunter's retreat.",14,"You identify the path it will use after the first exchange.","The Predator has planted a false trail around the clearing.",66,31,"ENEMY_DEBUFF",1,"COMBAT",0,true,0.02,"Perception is favored."],
];

const scenes = workbook.worksheets.getItem("Scenes");
const choices = workbook.worksheets.getItem("SceneChoices");
const scenesStart = scenes.getUsedRange(true).rowCount + 1;
const choicesStart = choices.getUsedRange(true).rowCount + 1;
scenes.tables.getItem("ScenesTable").rows.add(null, scenesRows);
choices.tables.getItem("SceneChoicesTable").rows.add(null, choicesRows);

scenes.getRange(`A${scenesStart}:T${scenesStart + scenesRows.length - 1}`).format = { font: { typeface: "Calibri", fontSize: 9 }, verticalAlignment: "top", wrapText: true, rowHeight: 48 };
choices.getRange(`A${choicesStart}:P${choicesStart + choicesRows.length - 1}`).format = { font: { typeface: "Calibri", fontSize: 9 }, verticalAlignment: "top", wrapText: true, rowHeight: 48 };
scenes.getRange(`H${scenesStart}:J${scenesStart + scenesRows.length - 1}`).format.numberFormat = "0";
scenes.getRange(`O${scenesStart}:P${scenesStart + scenesRows.length - 1}`).format.numberFormat = "0%";
scenes.getRange(`Q${scenesStart}:R${scenesStart + scenesRows.length - 1}`).format.numberFormat = "0";
choices.getRange(`E${choicesStart}:E${choicesStart + choicesRows.length - 1}`).format.numberFormat = "0";
choices.getRange(`H${choicesStart}:I${choicesStart + choicesRows.length - 1}`).format.numberFormat = "0";
choices.getRange(`O${choicesStart}:O${choicesStart + choicesRows.length - 1}`).format.numberFormat = "0%";

const sceneCheck = await workbook.inspect({ kind: "table", sheetId: "Scenes", range: `A${scenesStart}:T${scenesStart + scenesRows.length - 1}`, include: "values,formulas", tableMaxRows: 12, tableMaxCols: 20, maxChars: 9000 });
const choiceCheck = await workbook.inspect({ kind: "table", sheetId: "SceneChoices", range: `A${choicesStart}:P${choicesStart + 9}`, include: "values,formulas", tableMaxRows: 12, tableMaxCols: 16, maxChars: 9000 });
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" });
console.log(sceneCheck.ndjson);
console.log(choiceCheck.ndjson);
console.log(errors.ndjson);

const outputDir = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/019fc439-d617-7783-a9b4-5347c2d0bf25";
await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/GameContent_Perks_Worldbosses_with_Scenes.xlsx`);
await output.save(sourcePath);
console.log(`Added ${scenesRows.length} scenes and ${choicesRows.length} choices.`);
