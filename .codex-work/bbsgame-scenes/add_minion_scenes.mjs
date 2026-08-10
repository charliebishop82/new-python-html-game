import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const sourcePath = "C:/Users/charl/OneDrive/Desktop/bbsgame/data/GameContent_Perks_Worldbosses.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));

const definitions = [
  {key:"TOTALRECALL_REKALL_AMBUSH",movie:"Total Recall",name:"Ambush at Rekall",setup:"Emergency lights flash through the memory clinic as security shutters close. Douglas Quaid searches for an exit while Richter advances through the procedure rooms with a pistol drawn.",hero:"Douglas Quaid",enemy:"Richter",level:7,xp:95,credits:42,base:15,notes:"Minion Scene combining uncertain memories with a clinic pursuit.",a:[
    ["BREAK_SHUTTER","STR","Force a security shutter open before Richter reaches the corridor.","The shutter buckles and Quaid pulls you into the service hall.","The mechanism locks and Richter corners you at the controls."],
    ["IGNORE_IMPLANT","END","Fight through the memory procedure's aftereffects and keep moving.","You steady yourself and guide Quaid through the distorted clinic.","A false memory freezes you long enough for Richter to arrive."],
    ["SLIDE_LAB","AGI","Slide across the procedure table and enter the ventilation passage.","You clear the lab and flank Richter through the adjoining room.","Loose instruments scatter across the floor and betray the route."],
    ["TRUST_MEMORY","LCK","Follow a half-remembered escape route that may never have existed.","The imagined corridor proves real and opens behind Richter.","The memory ends at a blank wall as Richter enters."],
    ["READ_CAMERAS","PER","Compare clinic cameras to identify which image of Richter is current.","A timestamp exposes his true position and lets Quaid prepare.","A looping recording sends you toward his approach."],
  ]},
  {key:"STARTREKVI_CONSPIRACY",movie:"Star Trek VI: The Undiscovered Country",name:"Conspiracy on Deck Six",setup:"A phaser alarm sounds through an empty corridor while sealed orders appear on the wall terminal. James T. Kirk follows the evidence as Valeris steps from the turbolift with a disruptor.",hero:"James T. Kirk",enemy:"Valeris",level:7,xp:95,credits:42,base:15,notes:"Investigation Scene aboard the Enterprise.",a:[
    ["JAM_LIFT","STR","Force the turbolift doors closed before Valeris clears them.","The doors lock and deny her prepared firing lane.","The doors reopen under emergency power and expose you."],
    ["CROSS_STUN_FIRE","END","Advance through suppressing fire while Kirk reaches the terminal.","You endure the barrage and keep Valeris occupied.","A near strike breaks your advance and she closes in."],
    ["JEFFERIES_TUBE","AGI","Enter the narrow maintenance tube and circle behind Valeris.","You emerge at the junction behind her position.","A loose access panel announces your movement."],
    ["ISSUE_FALSE_ORDER","LCK","Transmit a false command and gamble that Valeris obeys protocol.","She hesitates long enough for Kirk to expose the conspiracy.","She recognizes the forged authorization immediately."],
    ["CHECK_LOGIC","PER","Find the contradiction hidden inside Valeris's carefully logical account.","The inconsistency reveals where she concealed the evidence.","A planted detail leads you into her prepared ambush."],
  ]},
  {key:"THREEHUNDRED_IMMORTAL_NIGHT",movie:"300",name:"Immortals in the Dark",setup:"The moon disappears behind smoke as masked warriors climb over the bodies at the pass. Leonidas lowers his spear while a Persian Immortal moves silently toward the broken shield wall.",hero:"Leonidas",enemy:"Persian Immortal",level:8,xp:105,credits:47,base:16,notes:"Night assault by Xerxes's elite minion.",a:[
    ["RAISE_WALL","STR","Lift a fallen shield into the breach beside Leonidas.","The shield wall reforms and traps the Immortal in the pass.","The shield slips and the Immortal attacks through the gap."],
    ["HOLD_SPEAR","END","Hold the extended spear line while the Immortal tests it.","You withstand the pressure until Leonidas finds an opening.","Your arms fail and the spear line folds inward."],
    ["VAULT_SHIELDS","AGI","Vault the shield wall and land beyond the Immortal's guard.","You land cleanly and turn the masked warrior toward Leonidas.","The warrior reads the leap and meets you in the air."],
    ["THROW_IN_DARK","LCK","Cast a spear toward the sound of breathing in the dark.","The throw tears away the Immortal's mask and ruins the ambush.","The spear strikes only stone and reveals your position."],
    ["WATCH_DUST","PER","Follow disturbed dust beneath the Immortal's silent steps.","The dust reveals the attack a heartbeat before it begins.","Wind across the pass creates a false trail."],
  ]},
  {key:"T2_FREEWAY_AMBUSH",movie:"Terminator 2: Judgment Day",name:"Endoskeleton on the Freeway",setup:"Abandoned vehicles burn beneath the overpass as mechanical footsteps echo through the smoke. Sarah Connor checks her weapon while a T-800 Endoskeleton advances between the wrecks.",hero:"Sarah Connor",enemy:"T-800 Endoskeleton",level:8,xp:105,credits:47,base:16,notes:"Future-war minion encounter on a ruined freeway.",a:[
    ["TIP_TRUCK","STR","Tip a damaged truck frame into the endoskeleton's route.","The wreck pins one metal leg and gives Sarah a clear shot.","The frame collapses short of the target."],
    ["CROSS_FIRE","END","Draw the machine's fire while Sarah moves between vehicles.","You endure the barrage and hold its targeting focus.","The sustained fire forces you out of cover."],
    ["UNDER_WRECK","AGI","Crawl beneath the wreckage and attack its exposed rear assembly.","You emerge behind the machine before it recalibrates.","A hanging axle catches your gear and alerts it."],
    ["START_ENGINE","LCK","Turn the key in a ruined vehicle and gamble that it still runs.","The engine surges forward and smashes into the endoskeleton.","The starter clicks uselessly in the silence."],
    ["TRACK_OPTICS","PER","Watch the red optic and predict its next targeting sweep.","You call the sweep and Sarah fires between scans.","Smoke reflects the optic and hides its true aim."],
  ]},
  {key:"TWOTOWERS_DEEPING_BREACH",movie:"The Lord of the Rings: The Two Towers",name:"Breach at the Deeping Wall",setup:"Rain lashes the fortress as ladders rise against the stone. Aragorn reaches the shattered parapet while an Uruk-hai Berserker charges through the smoke.",hero:"Aragorn",enemy:"Uruk-hai Berserker",level:9,xp:115,credits:52,base:17,notes:"Helm's Deep minion Scene.",a:[
    ["PUSH_LADDER","STR","Push the siege ladder away before more Uruk-hai reach the wall.","The ladder falls and isolates the Berserker beside Aragorn.","The ladder's hooks hold and the Berserker clears the parapet."],
    ["HOLD_BREACH","END","Stand in the broken wall while Aragorn rallies the defenders.","You hold the narrow breach and absorb the first assault.","The Berserker drives you back into the courtyard."],
    ["CROSS_PARAPET","AGI","Run the rain-slick parapet and strike from the tower side.","You reach the flank before the Berserker turns.","Your footing slips on the broken stone."],
    ["CUT_ROPE","LCK","Cut one siege rope and gamble on which ladder it supports.","The correct ladder twists away and exposes the Berserker.","The rope belongs to a defender's barricade."],
    ["SPOT_CHARGE","PER","Identify the Berserker carrying the explosive charge through the rain.","You point out the threat and Aragorn intercepts it.","A decoy charge draws your warning away."],
  ]},
  {key:"MATRIX_ROOFTOP_AGENT",movie:"The Matrix",name:"Agent on the Rooftop",setup:"Helicopter rotors beat against a glass tower while green code ripples across the skyline. Neo reaches the roof as Agent Jones takes control of a nearby guard.",hero:"Neo",enemy:"Agent Jones",level:9,xp:115,credits:52,base:17,notes:"Rooftop minion confrontation inside the Matrix.",a:[
    ["BEND_MAST","STR","Pull down the antenna mast across Jones's firing position.","The mast forces the Agent into Neo's line of attack.","Jones catches the falling structure and turns it aside."],
    ["IGNORE_BULLETS","END","Keep moving despite the simulation's impact warnings.","You remain focused and hold Jones's attention.","The pain response overwhelms your concentration."],
    ["ROOFTOP_LEAP","AGI","Leap the gap to the adjacent roof and attack from above.","You clear the gap and arrive beyond Jones's tracking arc.","The distance stretches as the Matrix resists you."],
    ["ENTER_GLITCH","LCK","Step into a flickering service door before its destination stabilizes.","The glitch deposits you behind the Agent.","The door loops back into his sights."],
    ["SEE_POSSESSION","PER","Watch the crowd below for the next body Jones intends to occupy.","You identify the transfer before it completes.","A harmless bystander flickers and draws your attention."],
  ]},
  {key:"GLADIATOR_TIGRIS_ARENA",movie:"Gladiator",name:"Champion of the Arena",setup:"Iron gates rise and the crowd roars for blood. Maximus enters the sand beside you as Tigris of Gaul advances behind heavy armor.",hero:"Maximus",enemy:"Tigris of Gaul",level:10,xp:125,credits:57,base:18,notes:"Arena minion Scene against the celebrated champion.",a:[
    ["BREAK_CHAIN","STR","Break the chain controlling the arena obstacle between you.","The obstacle falls and traps Tigris away from his support.","The chain snaps toward you and opens the fight."],
    ["MEET_CHARGE","END","Meet Tigris's charge and hold the center for Maximus.","You withstand the impact and halt his momentum.","The armored charge drives you through the sand."],
    ["ROLL_BLADE","AGI","Roll beneath the war sword and reach Tigris's unarmored side.","You clear the blade and force him to turn.","The sword changes direction inside the swing."],
    ["RELEASE_GATE","LCK","Pull an unmarked arena lever and gamble on what it releases.","A gate rises behind Tigris and blocks his retreat.","The lever opens another hazard beside you."],
    ["READ_ARMOR","PER","Study the dents in Tigris's armor for the joint he protects.","The wear reveals a weak shoulder fastening.","Decorative damage disguises the strongest plate."],
  ]},
  {key:"THING_GENERATOR_SHED",movie:"The Thing",name:"Something in the Generator Shed",setup:"The outpost lights die one building at a time. MacReady raises his shotgun as an Infected Crewman backs toward the generator shed with an unfamiliar smile.",hero:"MacReady",enemy:"Infected Crewman",level:10,xp:125,credits:57,base:18,notes:"Suspicion-driven minion Scene outside Outpost 31.",a:[
    ["BAR_DOOR","STR","Jam a steel bar through the shed door before the imitation escapes.","The door holds and contains the creature with MacReady.","The frame tears apart under inhuman strength."],
    ["CROSS_BLIZZARD","END","Circle the shed through the blizzard without losing the trail.","You endure the cold and seal the rear exit.","The wind erases the tracks and slows you."],
    ["CLIMB_ROOF","AGI","Climb the iced roof and enter through the generator vent.","You reach the rafters above the imitation.","Ice breaks away and drops you beside it."],
    ["CUT_FUEL","LCK","Cut one fuel hose and gamble that it feeds the generator rather than the heater.","The lights flare and expose the creature changing shape.","The outpost falls darker while the creature moves."],
    ["CHECK_BREATH","PER","Compare everyone's breath and movement in the freezing air.","One pattern remains wrong and reveals the infected crewman.","Fear makes an innocent crewman appear unnatural."],
  ]},
  {key:"EMPIRE_ECHO_CORRIDOR",movie:"Star Wars: The Empire Strikes Back",name:"Escape from Echo Base",setup:"Ice dust falls from the ceiling as warning sirens echo through the rebel base. Luke Skywalker reaches the hangar route while an Imperial Stormtrooper squad leader blocks the corridor.",hero:"Luke Skywalker",enemy:"Imperial Stormtrooper",level:11,xp:135,credits:62,base:19,notes:"Echo Base evacuation minion Scene.",a:[
    ["MOVE_CANNON","STR","Drag a disabled cannon across the stormtrooper's firing lane.","The cannon forms cover and lets Luke advance.","The frozen mount locks before reaching the lane."],
    ["CROSS_BLASTER_FIRE","END","Draw blaster fire while evacuees clear the junction.","You hold the corridor until Luke reaches the squad.","The barrage forces you against the blast door."],
    ["ICE_TUNNEL","AGI","Take the narrow maintenance tunnel above the corridor.","You emerge behind the stormtrooper position.","Falling ice gives away the tunnel exit."],
    ["FIRE_STEAM","LCK","Shoot a frozen pipe and gamble that it vents across the enemy.","Steam blinds the stormtrooper without blocking Luke.","The pipe vents across your own route."],
    ["READ_HELMET","PER","Watch the helmet movement to anticipate the squad's targeting calls.","You identify the next firing lane before it forms.","A false head turn sends you into the shot."],
  ]},
  {key:"FLASHGORDON_SKY_CITY",movie:"Flash Gordon",name:"Revolt Above the Clouds",setup:"Floating platforms buckle beneath an imperial bombardment. Flash Gordon reaches the landing bridge while a Hawkman champion challenges anyone attempting to cross.",hero:"Flash Gordon",enemy:"Hawkman",level:11,xp:135,credits:62,base:19,notes:"Aerial minion challenge over Sky City.",a:[
    ["HOLD_BRIDGE","STR","Hold the landing bridge in place as the platforms separate.","The bridge stays aligned and corners the Hawkman before Flash.","The bridge twists free and leaves you exposed."],
    ["FACE_WIND","END","Advance into the violent crosswind without surrendering ground.","You endure the gusts and keep the Hawkman's attention.","The wind drives you back toward the platform edge."],
    ["SWING_CHAIN","AGI","Swing beneath the bridge and climb behind the winged warrior.","You clear the open air and reach his blind side.","The chain jerks and the Hawkman spots you."],
    ["JUMP_GLIDER","LCK","Leap onto an unmanned glider and trust its controls.","The glider carries you directly across the champion's path.","It banks toward the imperial guns instead."],
    ["WATCH_FEATHERS","PER","Read the Hawkman's wing feathers to predict his next dive.","The feather angle reveals the attack before he commits.","A sudden gust changes the dive at the last moment."],
  ]},
  {key:"WILLOW_NOCKMAAR_GATE",movie:"Willow",name:"The Gate of Nockmaar",setup:"Rain runs black over the fortress stones as chains rattle above the moat. Willow Ufgood reaches the gate controls while a Nockmaar Soldier descends the stair with sword raised.",hero:"Willow Ufgood",enemy:"Nockmaar Soldier",level:12,xp:145,credits:67,base:20,notes:"Fortress infiltration minion Scene.",a:[
    ["TURN_WINCH","STR","Turn the gate winch against its locking mechanism.","The chain moves and blocks the soldier's advance.","The winch catches and signals the guard."],
    ["HOLD_PORTCULLIS","END","Hold the descending portcullis while Willow passes beneath it.","You endure the weight and keep the route open.","The iron teeth force you to release it."],
    ["CLIMB_CHAIN","AGI","Climb the gate chain and enter through the upper mechanism.","You reach the stair above the soldier.","The chain swings against the stone and alerts him."],
    ["USE_ACORN","LCK","Cast an enchanted acorn at the gate and trust what it transforms.","The locking bar turns to stone and snaps under its own weight.","The acorn transforms a harmless support instead."],
    ["READ_CREST","PER","Study the guard crests to identify the captain's control key.","The correct insignia reveals which key opens the gate.","A ceremonial crest points to the wrong ring."],
  ]},
  {key:"LABYRINTH_GOBLIN_PATROL",movie:"Labyrinth",name:"The Door That Wasn't There",setup:"A blank wall opens onto a corridor crowded with mismatched doors. Sarah Williams chooses a path while a Goblin Guard drags a club around the nearest corner.",hero:"Sarah Williams",enemy:"Goblin Guard",level:12,xp:145,credits:67,base:20,notes:"Maze-navigation minion Scene.",a:[
    ["MOVE_WALL","STR","Push the rotating wall before the goblin seals the passage.","The wall turns and traps the guard on Sarah's side.","The mechanism reverses and opens beside him."],
    ["IGNORE_RIDDLES","END","Keep walking as the corridor repeats the same taunts and turns.","You resist the maze and maintain the true direction.","The repetition breaks your focus and the guard catches up."],
    ["CLIMB_DOORS","AGI","Climb the stacked doorframes and cross above the patrol.","You descend behind the Goblin Guard.","A painted door swings open beneath your hand."],
    ["CHOOSE_KNOCKER","LCK","Use one of two arguing door knockers without resolving which tells the truth.","The chosen door opens onto the guard's blind side.","It opens directly in front of his patrol."],
    ["FOLLOW_CHALK","PER","Separate Sarah's chalk marks from the copies made by the maze.","The smudged original reveals the real route.","A perfect imitation leads toward the guard."],
  ]},
  {key:"TRON_DISC_ARENA",movie:"Tron",name:"The Disc Arena",setup:"A glowing grid forms beneath the prisoners as walls rise around the arena. Kevin Flynn catches an identity disc while Sark steps onto the opposite platform.",hero:"Kevin Flynn",enemy:"Sark",level:13,xp:155,credits:72,base:21,notes:"Digital arena minion Scene.",a:[
    ["BREAK_WALL","STR","Drive a disc into the arena wall until its code fractures.","The wall opens and limits Sark's movement.","The disc rebounds into his attack path."],
    ["ABSORB_IMPACT","END","Take Sark's first disc impact and keep Flynn's platform active.","You remain coherent and preserve the platform.","The impact destabilizes your code."],
    ["JUMP_GRID","AGI","Leap between disappearing grid squares and reach Sark's platform.","You cross before the sequence resets.","A square vanishes beneath your landing."],
    ["THROW_BANK","LCK","Bank a disc off an untested wall angle.","The ricochet strikes Sark from outside his guard.","The angle returns the disc toward you."],
    ["READ_PATTERN","PER","Study the arena pulse to predict which grid squares will remain.","The pattern reveals a stable path to Sark.","The MCP changes the sequence after you commit."],
  ]},
  {key:"ARMYDARKNESS_GRAVEYARD",movie:"Army of Darkness",name:"The Graveyard Awakens",setup:"Moonlight cuts across crooked stones as skeletal hands break through the soil. Ash Williams raises his boomstick while a Deadite Warrior claws free beside the open grave.",hero:"Ash Williams",enemy:"Deadite Warrior",level:13,xp:155,credits:72,base:21,notes:"Graveyard minion Scene with improvised slapstick hazards.",a:[
    ["SLAM_COFFIN","STR","Slam a coffin lid across the Deadite's path.","The lid pins the warrior long enough for Ash to aim.","The rotten wood bursts apart in your hands."],
    ["IGNORE_BITE","END","Hold the Deadite back despite its claws and teeth.","You keep it occupied and refuse to release your grip.","Its relentless attack breaks your hold."],
    ["SWING_SHOVEL","AGI","Vault a gravestone and seize the shovel behind the Deadite.","You land with the weapon at its exposed back.","The stone tips and drops you into the grave."],
    ["RECITE_WORDS","LCK","Recite the half-remembered burial phrase and hope it is close enough.","The ground grips the Deadite's legs and halts it.","The wrong words awaken another burst of movement."],
    ["CHECK_SHADOW","PER","Use the moonlight to distinguish the moving corpse from the still ones.","The wrong shadow reveals the Deadite before it lunges.","A swaying branch creates a convincing false target."],
  ]},
  {key:"STARGATE_TEMPLE_GATE",movie:"Stargate",name:"The Horus Gate",setup:"Sunlight cuts through the temple doorway as villagers scatter across the courtyard. Daniel Jackson reaches the symbol wall while a Horus Guard lowers its staff weapon.",hero:"Daniel Jackson",enemy:"Horus Guard",level:14,xp:165,credits:77,base:22,notes:"Temple uprising minion Scene.",a:[
    ["TOPPLE_COLUMN","STR","Topple a cracked column across the guard's route.","The column falls and traps the Horus Guard in the courtyard.","The stone turns and falls away from the target."],
    ["CROSS_STAFF_FIRE","END","Advance through staff blasts while Daniel reaches the glyphs.","You endure the fire and keep the guard focused on you.","The barrage halts you short of the doorway."],
    ["CLIMB_STATUE","AGI","Climb the temple statue and descend behind the guard.","You land beyond the helmet's field of view.","Loose ornament crashes into the courtyard."],
    ["PRESS_SYMBOL","LCK","Press an unknown wall symbol and gamble that it controls the gate.","The gate shifts and separates the guard from reinforcements.","The symbol activates a warning beacon."],
    ["TRANSLATE_COMMAND","PER","Translate the cartouche on the guard's control bracer.","You identify the symbol that interrupts its weapon.","A ceremonial inscription conceals the real command."],
  ]},
  {key:"EXCALIBUR_BLACK_BRIDGE",movie:"Excalibur",name:"The Black Bridge",setup:"Mist covers a narrow bridge where shields and broken lances lie abandoned. King Arthur approaches beside you as the Black Knight lowers a lance and seals the crossing.",hero:"King Arthur",enemy:"Black Knight",level:14,xp:165,credits:77,base:22,notes:"Chivalric minion duel at a guarded crossing.",a:[
    ["BREAK_LANCE","STR","Catch the lowered lance and break it against the bridge rail.","The shaft splits and Arthur advances into the opening.","The lance drives you backward across the stones."],
    ["HOLD_CROSSING","END","Stand in the center of the bridge and absorb the knight's charge.","You withstand the impact and halt the armored horse.","The charge carries you toward the edge."],
    ["VAULT_RAIL","AGI","Vault the bridge rail and return behind the Black Knight.","You land beyond the lance point and divide his guard.","Wet stone ruins the landing."],
    ["CHALLENGE_OATH","LCK","Invoke an old knightly oath and gamble that he still honors it.","The knight hesitates and lowers his shield to answer.","He recognizes no authority in the words."],
    ["READ_HERALDRY","PER","Study the damaged heraldry for the battle that broke his confidence.","The crest reveals which feint he expects.","The marks belong to armor taken from another knight."],
  ]},
  {key:"DUNE_SARDAUKAR_RAID",movie:"Dune 2021",name:"Raid Beneath the Sand",setup:"Ornithopter wreckage burns beneath a moonless sky as blades move through the dust. Paul Atreides draws his crysknife while a Sardaukar Trooper descends the dune.",hero:"Paul Atreides",enemy:"Sardaukar Trooper",level:15,xp:175,credits:82,base:23,notes:"Desert minion ambush against an elite trooper.",a:[
    ["SHIFT_WRECK","STR","Shift the ornithopter wreckage into the Sardaukar's descent.","The metal slides and forces the trooper into Paul's reach.","The wreck settles deeper into the sand."],
    ["CONTROL_WATER","END","Control your breathing and movement through the exhausting heat.","You conserve strength and hold the line beside Paul.","The heat drains your reactions before the attack."],
    ["SANDWALK_FLANK","AGI","Use an irregular sandwalk to circle beyond the trooper's sight.","You reach the flank without creating a readable rhythm.","One repeated step reveals your path."],
    ["TRUST_VISION","LCK","Follow a brief prescient image without knowing which future it belongs to.","The vision leads you through the blade's exact opening.","The possible future dissolves as you commit."],
    ["READ_BLADE","PER","Watch the Sardaukar's blade angle for the killing feint.","You identify the hidden second strike and warn Paul.","The trooper changes grip inside the motion."],
  ]},
];

const effects = {
  STR:[1,"FIRST_STRIKE",1,0,0.02,"Strength approach."],
  END:[0,"ALLY_BUFF",2,5,0,"Endurance approach; failure may cause opening damage."],
  AGI:[-1,"COMBAT_ADVANTAGE",1,0,0.03,"Agility approach."],
  LCK:[3,"ENEMY_DEBUFF",2,0,0.06,"High-risk luck approach."],
  PER:[-2,"ENEMY_DEBUFF",1,0,0.02,"Perception approach."],
};

const scenesRows = definitions.map(d => [
  d.key,d.movie,d.name,d.setup,d.hero,"MINION",d.enemy,2,d.level,8,"DEFEAT_ENEMY","ATTACK_ONLY","THREAT_WEIGHTED",false,
  0.18,0.10,d.xp,d.credits,true,d.notes,
]);
const choicesRows = definitions.flatMap(d => d.a.map((a,index) => {
  const [key,attr,text,success,failure] = a;
  const [offset,effect,effectValue,failureValue,rewardMod,note] = effects[attr];
  return [d.key,key,attr,text,d.base+offset,success,failure,
    Math.round(d.xp*(0.42 + index*0.02)),Math.round(d.credits*(0.42 + index*0.025)),
    effect,effectValue,"COMBAT",failureValue,true,rewardMod,note];
}));

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

const sceneCheck = await workbook.inspect({ kind: "table", sheetId: "Scenes", range: `A${scenesStart}:T${scenesStart + scenesRows.length - 1}`, include: "values,formulas", tableMaxRows: 20, tableMaxCols: 20, maxChars: 16000 });
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
console.log(`Added ${scenesRows.length} minion scenes and ${choicesRows.length} choices.`);
