import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const sourcePath = "C:/Users/charl/OneDrive/Desktop/bbsgame/data/GameContent_Perks_Worldbosses.xlsx";
const outputDir = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/019fc439-d617-7783-a9b4-5347c2d0bf25";
const outputPath = `${outputDir}/GameContent_Perks_Worldbosses_with_Refined_Scenes.xlsx`;

const sceneUpdates = {
  HIGHLANDER_GARAGE_DUEL: {
    SceneName: "The Madison Square Garage",
    SetupText: "The wrestling crowd has emptied into the night, leaving Madison Square Garden's parking garage to echo with tire squeals and distant laughter. Connor MacLeod hears another blade clear its sheath as a cackling swordsman cartwheels between the parked cars.",
  },
  TOTALRECALL_REKALL_AMBUSH: {
    SceneName: "Pursuit Through Venusville",
    SetupText: "Neon signs and red dust crowd the alleys of Venusville as Richter's men close every route to the Last Resort. Douglas Quaid pulls Melina toward the mutant tunnels while Richter enters the district with a pistol and orders to bring back Quaid's body.",
  },
  STARTREKVI_CONSPIRACY: {
    SceneName: "The Logic of Betrayal",
    SetupText: "The Enterprise computer has exposed a trail of altered torpedo records, missing gravity boots, and conspirators aboard both ships. Spock seals the briefing room while Kirk confronts Valeris, whose perfect Vulcan composure is beginning to fracture.",
  },
  T2_FREEWAY_AMBUSH: {
    SceneName: "Los Angeles, 2029",
    SetupText: "Hunter-Killer searchlights rake across a field of human skulls while plasma fire turns the ruined freeway blue-white. Sarah Connor's warning echoes over the resistance channel as a bare T-800 Endoskeleton steps through the flames and locks its red optic onto the survivors.",
  },
  GLADIATOR_TIGRIS_ARENA: {
    SceneName: "The Tigers of Carthage",
    SetupText: "Trapdoors open beneath the Colosseum sand and chained tigers lunge at the limits of their handlers' reach. Maximus raises his shield as Tigris of Gaul advances in engraved armor, fighting for the crowd and for Commodus watching from the imperial box.",
  },
  THING_GENERATOR_SHED: {
    SceneName: "Blair's Tool Shed",
    SetupText: "The tractor, radio equipment, and remaining escape routes have been methodically ruined. MacReady follows a trail through the snow to Blair's tool shed, where an infected crewman stands among scavenged machine parts and an unfinished shape that was never built by human hands.",
  },
  FLASHGORDON_SKY_CITY: {
    SceneName: "Trial Before Prince Vultan",
    SetupText: "The feast hall of Sky City shakes with laughter as Prince Vultan's Hawkmen debate whether an Earthman is worth following into war against Ming. A Hawkman champion sweeps onto the landing bridge and challenges Flash Gordon to prove his courage before the entire winged court.",
  },
  EXCALIBUR_BLACK_BRIDGE: {
    SceneName: "Challenge at the Ford",
    SetupText: "Morning mist hangs over a flooded ford where a black-armored knight has planted his banner and barred the road to Camelot. King Arthur rides forward beneath the dragon standard as the Black Knight lowers a lance and demands trial by arms.",
  },
};

const choiceUpdates = {
  HIGHLANDER_GARAGE_DUEL: {
    STR: ["Rip the parking barrier from its mount and sweep the swordsman's legs.", "The barrier catches him between two cars and leaves his guard open to Connor.", "He vaults the barrier, laughing, and lands inside your reach."],
    END: ["Weather his manic series of cuts until the garage sprinklers obscure his sight.", "You refuse to break while water and sparks ruin his rhythm.", "His blade finds you before the sprinklers can hide your position."],
    AGI: ["Vault a car hood as he cartwheels into another slashing pass.", "You clear the blade and land beside Connor with room to counter.", "Your boot slips on the polished hood and he turns beneath you."],
    LCK: ["Strike a car alarm and trust the echo to disguise Connor's approach.", "Every alarm on the level erupts, swallowing Connor's footsteps.", "Only one horn answers, pointing directly to your position."],
    PER: ["Separate his footfalls from their echoes among the concrete pillars.", "You identify the real approach before his blade appears around the pillar.", "A spinning hubcap supplies the wrong echo and draws your eyes away."],
  },
  TOTALRECALL_REKALL_AMBUSH: {
    STR: ["Force open the service hatch behind the Last Resort before Richter seals the block.", "The hatch tears free and Quaid gets Melina into the mutant tunnels.", "The warped frame jams halfway and Richter reaches the alley."],
    END: ["Push through Venusville's failing air while guiding the wounded toward cover.", "You keep moving through the thin air and reach Kuato's hidden route.", "The pressure drop buckles your knees as Richter's boots enter the street."],
    AGI: ["Dive across the Last Resort bar as Richter's first shots shatter the bottles.", "You slide behind the mirrored counter and emerge on Richter's flank.", "Broken glass catches your hand and kills your momentum."],
    LCK: ["Follow a mutant child through an unmarked curtain and trust that it leads below.", "The curtain hides a service stair into the resistance tunnels.", "It opens into a locked dressing room with Richter outside."],
    PER: ["Use the mirrored liquor wall to distinguish Richter from his reflections.", "His muzzle flash reveals the real angle before he clears the doorway.", "A flickering neon sign creates a convincing false flash."],
  },
  STARTREKVI_CONSPIRACY: {
    STR: ["Hold the briefing-room doors as conspirators try to retrieve Valeris.", "The doors remain sealed while Kirk forces the truth into the open.", "The emergency release tears the doors from your grip."],
    END: ["Remain at the console while Valeris floods it with a nerve-pinch feedback trap.", "You endure the shock and preserve the altered torpedo records.", "The feedback drives you away and erases part of the evidence."],
    AGI: ["Reach the equipment locker before Valeris can destroy the magnetic gravity boots.", "You secure the boots that connect the assassins to Gorkon's ship.", "Valeris seals the locker and cuts off your route."],
    LCK: ["Search the transporter buffer for one pattern the conspirators failed to purge.", "A surviving trace identifies the assassins' return to Enterprise.", "The buffer yields a decoy pattern planted for investigators."],
    PER: ["Compare Valeris's testimony with the ship's torpedo inventory and Spock's deductions.", "One impeccably logical answer contradicts the physical record.", "Her explanation accounts for the discrepancy and conceals the next lie."],
  },
  T2_FREEWAY_AMBUSH: {
    STR: ["Topple a scorched freeway divider into the Endoskeleton's path.", "The concrete pins one chrome leg beneath the ruins.", "The machine catches the slab and hurls it aside."],
    END: ["Carry a wounded resistance fighter through the Hunter-Killer searchlights.", "You cross the killing ground without abandoning the survivor.", "A plasma burst throws both of you into the open."],
    AGI: ["Sprint between the blue sweeps of the aerial Hunter-Killer.", "You reach the Endoskeleton's blind side between scanning passes.", "The searchlight reverses early and paints you in white."],
    LCK: ["Fire an abandoned resistance plasma rifle before its cracked cell overloads.", "One remaining charge strikes the Endoskeleton squarely in the chest.", "The cell vents in your hands without firing."],
    PER: ["Read the red optic's tracking rhythm against the Hunter-Killer sweep.", "You find the instant both machines lose the same patch of roadway.", "Ash in the air makes the optic appear to turn away."],
  },
  GLADIATOR_TIGRIS_ARENA: {
    STR: ["Wrench a tiger chain around Tigris's shield arm before the handler pulls it taut.", "The chain binds shield to armor and opens Tigris to Maximus.", "The tiger's lunge tears the chain out of your hands."],
    END: ["Hold the center while chained tigers strike from both trapdoors.", "You absorb the chaos and give Maximus room to face Tigris alone.", "A tiger's impact drives you beneath Tigris's sword."],
    AGI: ["Roll beneath Tigris's axe as a tiger crosses behind him.", "You rise beyond the axe and force him toward the tiger chain.", "The sand gives way above a trapdoor and ruins the roll."],
    LCK: ["Cut one handler's rope and trust the tiger to charge the brighter armor.", "The tiger turns on Tigris's polished silhouette and breaks his formation.", "The animal follows your movement instead."],
    PER: ["Watch the trapdoor sand for the tremor that precedes each tiger release.", "You call the next opening and Maximus turns Tigris into the lunge.", "The crowd's stamping hides the warning tremor."],
  },
  THING_GENERATOR_SHED: {
    STR: ["Ram Blair's heavy tool cabinet across the tunnel mouth beneath the shed.", "The cabinet seals the unfinished craft away from the infected crewman.", "Something below lifts the cabinet as though it were empty."],
    END: ["Hold the flamethrower steady while the imitation cycles through familiar faces.", "You resist the voices and keep the flame trained on the changing body.", "A perfect imitation of a crewman's plea makes your aim falter."],
    AGI: ["Cross the rafters before a half-built mechanical limb reaches the ladder.", "You reach the fuel drums and cut off the creature's escape.", "The limb punches through the boards beneath your feet."],
    LCK: ["Throw a flare into the excavation and trust the fuel trail to reveal its route.", "Fire races along the hidden tunnel and silhouettes the imitation.", "The flare lands in snowmelt and leaves the tunnel dark."],
    PER: ["Compare the scavenged parts with the missing tractor and radio components.", "The pattern reveals that the creature is assembling an escape craft below the shed.", "The parts look like ordinary sabotage until the imitation moves."],
  },
  FLASHGORDON_SKY_CITY: {
    STR: ["Catch the champion's descending war club on the haft and drive him back from the rail.", "The impact carries him across the landing bridge and wins Vultan's roar.", "His wings turn the blocked strike into a crushing dive."],
    END: ["Stand through the buffet of his wings without stepping beyond the painted challenge ring.", "You remain inside the ring and earn the Hawkmen's respect.", "The gale forces one heel across the boundary."],
    AGI: ["Swing from a hanging feast-chain and meet the Hawkman at balcony height.", "You intercept his dive in front of Vultan's throne.", "He folds one wing and drops beneath your swing."],
    LCK: ["Leap from the cloud balcony and trust a passing rocket cycle to carry you back.", "The cycle rises beneath you and turns the fall into a spectacular return.", "It banks away toward Ming's distant patrols."],
    PER: ["Watch the champion's wing joints for the twitch that begins a dive.", "You move before he leaves the perch and take away his momentum.", "Vultan's cheering masks the shift in the champion's feathers."],
  },
  EXCALIBUR_BLACK_BRIDGE: {
    STR: ["Catch the Black Knight's lance beneath your shield and wrench him from the saddle.", "The lance locks against the shield rim and the knight crashes into the ford.", "The charge drives shield and rider together through the water."],
    END: ["Stand knee-deep in the ford and refuse the full weight of his charge.", "You hold the crossing long enough for Arthur to draw Excalibur.", "The current and the horse's impact carry you downstream."],
    AGI: ["Step onto the ruined causeway and slip inside the lance point.", "You pass the point and reach the knight's unguarded rein hand.", "A moss-covered stone turns under your foot."],
    LCK: ["Answer his challenge with an older oath and gamble that his heraldry still binds him.", "The knight pauses to return the oath, giving Arthur the first clean opening.", "The banner was stolen, and the oath means nothing to him."],
    PER: ["Read the ford's ripples to find where his armored horse must slow.", "You mark the deep channel and Arthur meets the charge at its weakest point.", "The morning wind disguises the dangerous shallows."],
  },
};

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));
const scenes = workbook.worksheets.getItem("Scenes");
const choices = workbook.worksheets.getItem("SceneChoices");

function rowObjects(sheet) {
  const values = sheet.getUsedRange(true).values;
  const headers = values[0];
  return { headers, values };
}

const sceneData = rowObjects(scenes);
const sceneKeyCol = sceneData.headers.indexOf("SceneKey");
for (let r = 1; r < sceneData.values.length; r++) {
  const key = sceneData.values[r][sceneKeyCol];
  const update = sceneUpdates[key];
  if (!update) continue;
  for (const [header, value] of Object.entries(update)) {
    const c = sceneData.headers.indexOf(header);
    scenes.getCell(r, c).values = [[value]];
  }
}

const choiceData = rowObjects(choices);
const choiceSceneCol = choiceData.headers.indexOf("SceneKey");
const attrCol = choiceData.headers.indexOf("Attribute");
const choiceTextCol = choiceData.headers.indexOf("ChoiceText");
const successTextCol = choiceData.headers.indexOf("SuccessText");
const failureTextCol = choiceData.headers.indexOf("FailureText");
for (let r = 1; r < choiceData.values.length; r++) {
  const key = choiceData.values[r][choiceSceneCol];
  const attr = choiceData.values[r][attrCol];
  const update = choiceUpdates[key]?.[attr];
  if (!update) continue;
  choices.getCell(r, choiceTextCol).values = [[update[0]]];
  choices.getCell(r, successTextCol).values = [[update[1]]];
  choices.getCell(r, failureTextCol).values = [[update[2]]];
}

const sceneCheck = await workbook.inspect({ kind: "table", sheetId: "Scenes", range: "A1:T52", include: "values,formulas", tableMaxRows: 52, tableMaxCols: 20, maxChars: 8000 });
const choiceCheck = await workbook.inspect({ kind: "match", searchTerm: "Madison Square|Venusville|gravity boots|Hunter-Killer|tiger|Blair|Prince Vultan|ford", options: { useRegex: true, maxResults: 100 }, maxChars: 8000 });
const formulaErrors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan", maxChars: 3000 });
console.log(sceneCheck.ndjson);
console.log(choiceCheck.ndjson);
console.log(formulaErrors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(sourcePath);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, revisedScenes: Object.keys(sceneUpdates).length, revisedChoices: Object.keys(choiceUpdates).length * 5 }));
