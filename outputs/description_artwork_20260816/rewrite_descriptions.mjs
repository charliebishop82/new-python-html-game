import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/swords_and_circuits_36_20260815/GameContent_Swords_and_Circuits_36_Balanced_2026-08-15.xlsx";
const outputPath = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/description_artwork_20260816/GameContent_Swords_and_Circuits_36_ArtDescriptions_2026-08-16.xlsx";
const reportPath = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/description_artwork_20260816/description_validation.json";

const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const values = {};
for (const [name, range] of Object.entries({Master:"A1:S37",Bosses:"A1:AN37",Minions:"A1:AC37",Weapons:"A1:O119",Armor:"A1:T119",SpecialItems:"A1:AI119",WorldBosses:"A1:AN11"})) {
  values[name] = wb.worksheets.getItem(name).getRange(range).values;
}

const palettes = [
  ["smoke-black", "aged brass", "deep crimson"], ["weathered umber", "iron grey", "forest green"],
  ["bone ivory", "dark bronze", "dried-blood red"], ["midnight blue", "cold silver", "ash grey"],
  ["burnished gold", "oxblood leather", "charcoal"], ["storm grey", "copper", "faded indigo"],
  ["obsidian", "antique gold", "royal purple"], ["sandstone", "tarnished steel", "dusty scarlet"],
  ["oil-black", "gunmetal", "warning amber"], ["ceramic white", "graphite", "electric blue"],
  ["matte black", "brushed steel", "signal red"], ["industrial grey", "copper wire", "acid green"]
];
const surfaces = ["fine scratches and dulled edges", "hammer marks and shallow battle scars", "careful hand-stitching and worn seams", "heat discoloration and soot along the working surfaces", "engraved borders softened by years of handling", "chipped enamel and rubbed metal at every exposed corner", "rain spotting, dust, and old repairs", "polished high points contrasting with dark recessed detail"];
const accents = ["a narrow geometric border", "small rivets set in disciplined rows", "a restrained heraldic motif", "asymmetrical field repairs", "layered panels that catch the light", "a single vivid accent line", "dense filigree around the fittings", "practical straps and reinforced fasteners"];
const silhouettes = ["long and narrow", "broad and top-heavy", "compact and angular", "swept and crescent-like", "tapered and needle-sharp", "blocky and industrial", "gracefully curved", "severe and symmetrical", "forward-weighted", "low and streamlined", "tall and ceremonial", "irregular and hand-forged"];
const closeDetails = ["crosshatched grip texture", "three inset studs", "a scalloped edge treatment", "a recessed spine channel", "a braided binding pattern", "a faceted central ridge", "a double-line engraved border", "a reinforced lower collar", "a cluster of tiny ventilation cuts", "a contrasting wrapped seam"];
const garmentDetails = ["closely spaced shoulder lames", "three offset fastening straps", "a scalloped lower edge", "a recessed central breastplate channel", "braided binding around the openings", "a faceted ridge down the torso", "double-line stitching at every border", "a reinforced waist collar", "small ventilation cuts beneath the arms", "a contrasting seam running down the back"];
const artifactDetails = ["a crosshatched contact surface", "three tiny inset studs", "a scalloped outer edge", "a recessed central channel", "a braided binding loop", "a faceted raised ridge", "a double-line engraved border", "a reinforced mounting collar", "a cluster of minute perforations", "a contrasting wrapped seam"];
function uniqueVisual(index) { return `${silhouettes[index%silhouettes.length]}, with ${closeDetails[Math.floor(index/silhouettes.length)%closeDetails.length]}`; }
function uniqueGarment(index) { return `${silhouettes[index%silhouettes.length]}, with ${garmentDetails[Math.floor(index/silhouettes.length)%garmentDetails.length]}`; }
function uniqueArtifact(index) { return `${silhouettes[index%silhouettes.length]}, with ${artifactDetails[Math.floor(index/silhouettes.length)%artifactDetails.length]}`; }
const bodyProfiles = ["lean and long-limbed", "broad-shouldered and powerful", "compact and tightly muscled", "tall with an austere bearing", "wiry and quick-looking", "heavy-set with a low center of gravity", "athletic and evenly proportioned", "angular and almost statuesque", "scarred and thick-necked", "slender with precise posture", "imposing beneath layered clothing", "weathered and asymmetrical"];
const faceDetails = ["a strong brow and watchful eyes", "a weather-cut face and tight jaw", "deep-set eyes beneath a shadowed brow", "a pale face marked by fine scars", "closely cropped hair and a guarded expression", "loose hair framing sharp cheekbones", "an expression of controlled exhaustion", "a rigid profile softened by age lines", "a broken nose and old bruising", "a calm face fixed on a distant threat"];
function uniquePerson(index) { return `${bodyProfiles[index%bodyProfiles.length]}, with ${faceDetails[Math.floor(index/bodyProfiles.length)%faceDetails.length]}`; }

function hash(s) { let h=2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h,16777619); } return h>>>0; }
function pick(arr, seed, n=0) { return arr[(hash(seed)+n*7919)%arr.length]; }
function words(s) { return String(s||"").toLowerCase(); }
function article(s) { return /^[aeiou]/i.test(s) ? "an" : "a"; }
function category(name, type="weapon") {
  const n=words(name);
  const groups = type === "weapon" ? [
    [/bow|crossbow/,"bow"],[/pistol|revolver|auto-9|handgun/,"pistol"],[/shotgun/,"shotgun"],[/rifle|carbine|musket/,"rifle"],[/blaster|laser|plasma|phaser|ray/,"energy weapon"],
    [/spear|lance|trident|pike/,"polearm"],[/axe|hatchet/,"axe"],[/hammer|maul|mace|club/,"blunt weapon"],[/dagger|knife|blade|dirk|stiletto/,"knife"],[/staff|wand|scepter|rod/,"staff"],
    [/claw|talon/,"claw weapon"],[/whip|chain/,"flexible weapon"],[/sword|sabre|saber|rapier|katana|scimitar|claymore|falchion/,"sword"],[/gauntlet|fist|glove/,"gauntlet"],[/shield/,"shield weapon"]
  ] : type === "armor" ? [
    [/plate|cuirass|carapace|armor|armour/,"plate harness"],[/mail|chain/,"mail coat"],[/robe|regalia|gown|dress/,"ceremonial garment"],[/suit|uniform|vest|tactical/,"fitted combat suit"],
    [/coat|jacket|duster/,"long coat"],[/leather|hide|skin/,"layered leather outfit"],[/cloak|mantle|cape/,"traveling mantle"],[/exo|powered|cyber|mech/,"powered shell"]
  ] : [
    [/ring|band|signet/,"ring"],[/amulet|talisman|pendant|necklace/,"pendant"],[/crown|tiara|circlet/,"headpiece"],[/mask|helmet|helm/,"mask"],[/book|tome|scroll|journal/,"bound volume"],
    [/chip|device|communicator|scanner|module|drive|computer/,"compact device"],[/horn|flute|instrument/,"ceremonial instrument"],[/gem|crystal|stone/,"faceted stone"],[/badge|medal|emblem|token/,"insignia"],[/shield/,"ceremonial shield"],[/key/,"ornate key"]
  ];
  return (groups.find(([re])=>re.test(n))||[])[1] || (type==="weapon"?"hand weapon":type==="armor"?"protective outfit":"personal artifact");
}

function visualNameHints(name) {
  const n=words(name), hints=[];
  if (/gold|gild/.test(n)) hints.push("gilded trim");
  if (/silver/.test(n)) hints.push("silvered fittings");
  if (/black|dark|shadow/.test(n)) hints.push("light-swallowing black surfaces");
  if (/red|scarlet|crimson/.test(n)) hints.push("crimson accents");
  if (/ice|frost|winter/.test(n)) hints.push("frost-pale detailing");
  if (/fire|flame|burn/.test(n)) hints.push("ember-colored markings");
  if (/royal|king|queen|crown/.test(n)) hints.push("formal royal ornament");
  if (/dragon|scale|serpent|snake/.test(n)) hints.push("overlapping scale motifs");
  if (/crystal|glass/.test(n)) hints.push("translucent crystalline elements");
  return hints;
}

function weaponDescription(row,index) {
  const name=row[0], kind=category(name,"weapon"), [a,b,c]=pick(palettes,`${name}|palette`), hint=visualNameHints(name)[0]||pick(accents,`${name}|accent`);
  const anatomy = {
    bow:"A recurved frame of laminated wood and dark horn surrounds a taut braided string, with a wrapped grip and compact arrow rest",
    pistol:"A compact metal frame carries a squared barrel, textured grip panels, exposed controls, and a clean sight line",
    shotgun:"A broad-bored firearm combines a heavy receiver, reinforced barrel, ribbed fore-end, and a stock built to absorb recoil",
    rifle:"A long, balanced firearm pairs a rigid barrel assembly with a shouldered stock, precise sights, and a protected action",
    "energy weapon":"A sharply machined emitter housing surrounds luminous conduits, vented coils, a guarded trigger, and a compact power cell",
    polearm:"A long, straight shaft ends in a leaf-shaped metal head with reinforced shoulders, binding bands, and a weighted butt cap",
    axe:"A wedge-shaped head sits firmly around a reinforced haft, balancing a keen cutting edge against a dense counterweight",
    "blunt weapon":"A weighty striking head crowns a wrapped handle, with reinforced collars and a flared pommel for control",
    knife:"A narrow full-tang blade rises from a guarded grip, its spine thick near the hand and tapering to a severe point",
    staff:"A tall, balanced shaft is capped with sculpted metalwork and inset elements, its grip worn smooth at the center",
    "claw weapon":"Curved talons project from a close-fitting hand brace, each hooked point anchored by articulated metal plates",
    "flexible weapon":"Interlocking segments run from a reinforced grip to a weighted striking end, allowing a coiled, serpentine silhouette",
    sword:"A full-length blade runs from a defined point through a guarded hilt, wrapped grip, and weighted pommel",
    gauntlet:"Articulated plates sheath the hand and forearm, with reinforced knuckles and flexible joints built for close strikes",
    "shield weapon":"A broad defensive face is built around a rigid central boss, reinforced rim, and tightly secured arm straps",
    "hand weapon":"A purpose-built striking tool combines a balanced core, reinforced grip, and clearly defined working edge"
  }[kind];
  return `${anatomy}. Its overall profile is ${uniqueVisual(index)}. The ${a}, ${b}, and ${c} finish is broken by ${hint}, while ${pick(surfaces,`${name}|surface`)} gives the piece a tangible, battle-used character.`;
}

function armorDescription(row,index) {
  const name=row[0], kind=category(name,"armor"), [a,b,c]=pick(palettes,`${name}|palette`), hint=visualNameHints(name)[0]||pick(accents,`${name}|accent`);
  const anatomy={
    "plate harness":"Overlapping rigid plates shape the torso, shoulders, and limbs, leaving narrow articulated gaps for movement",
    "mail coat":"Thousands of interlocked rings form a flexible knee-length defense, strengthened at the shoulders and lined at the collar",
    "ceremonial garment":"Layered fabric falls in a commanding silhouette, structured at the shoulders and gathered by fitted belts and ornamental closures",
    "fitted combat suit":"Close-cut protective panels follow the body beneath reinforced seams, compact pockets, and a high guarded collar",
    "long coat":"A long tailored coat hangs from firm shoulders, with a split hem, deep cuffs, concealed fastenings, and reinforced inner layers",
    "layered leather outfit":"Shaped leather panels overlap across the chest and limbs, joined by lacing, buckled straps, and flexible underlayers",
    "traveling mantle":"A broad mantle drapes from a reinforced collar, falling in weathered folds over fitted protective layers beneath",
    "powered shell":"Segmented mechanical plating encloses a flexible undersuit, with compact actuators, sealed joints, and recessed status lights",
    "protective outfit":"A fitted collection of layered garments protects the torso and limbs with reinforced seams, guards, and practical closures"
  }[kind];
  return `${anatomy}. The complete silhouette is ${uniqueGarment(index)}, distinguishing its construction at a glance. Its ${a}, ${b}, and ${c} palette is defined by ${hint}; the presence of ${pick(surfaces,`${name}|surface`)} keeps the protection grounded, worn, and physically believable.`;
}

function specialDescription(row,index) {
  const name=row[0], kind=category(name,"special"), [a,b,c]=pick(palettes,`${name}|palette`), hint=visualNameHints(name)[0]||pick(accents,`${name}|accent`);
  const anatomy={
    ring:"A weighty band surrounds a raised face of carved metal and inset material, small enough to wear yet unmistakably deliberate in its craftsmanship",
    pendant:"A palm-sized centerpiece hangs from a finely linked chain, its layered setting framing a polished core and minute engraved marks",
    headpiece:"A rigid arc rises into a sculpted silhouette of points and openwork, balanced to sit above the brow without hiding the face",
    mask:"A fitted face covering combines a severe brow, shaped cheek planes, narrow eye openings, and concealed fastenings along the edge",
    "bound volume":"A thick hand-bound volume is wrapped in textured covers, reinforced at the corners, and packed with uneven deckled pages",
    "compact device":"A palm-sized casing contains inset controls, tiny indicator lights, vent slots, and tightly fitted mechanical seams",
    "ceremonial instrument":"A sculpted hollow body narrows toward a carefully finished mouthpiece, with engraved bands following its curves",
    "faceted stone":"An irregular polished stone is cut into deep planes that catch light along its edges while shadow gathers inside its core",
    insignia:"A compact emblem layers stamped metal, colored enamel, and a sturdy pinning mechanism into a crisp symbolic silhouette",
    "ceremonial shield":"A compact shield bears a raised central emblem, a polished rim, and a close leather grip hidden behind its decorated face",
    "ornate key":"A long-toothed key ends in an elaborate openwork bow, its shaft marked by tiny notches and hand-cut symbols",
    "personal artifact":"A palm-sized personal object combines carefully fitted materials, intricate surface detail, and a silhouette made distinctive by long use"
  }[kind];
  return `${anatomy}. Its profile is ${uniqueArtifact(index)}. The ${a}, ${b}, and ${c} surfaces define the color and material treatment, with ${hint} and ${pick(surfaces,`${name}|surface`)} providing the close-up detail needed for a convincing prop.`;
}

function personDescription(name, role, layer, weaponName, armorName, seedExtra="", index=0) {
  const seed=`${name}|${role}|${seedExtra}`, [a,b,c]=pick(palettes,`${seed}|palette`), weapon=category(weaponName,"weapon"), armor=category(armorName,"armor");
  const builds = role==="protagonist" ? ["alert, athletic stance","weathered, determined bearing","controlled, ready posture","lean silhouette poised to move"] : role==="boss" ? ["commanding, immovable stance","severe silhouette with predatory stillness","theatrical posture charged with menace","upright bearing that dominates the frame"] : ["compact, dangerous stance","restless enforcer's posture","hardened silhouette ready to lunge","guarded stance shaped by constant violence"];
  const faces = layer==="Circuits" ? ["hard side-light cuts across a focused face","cool instrument light reflects across tense features","the face is framed by cables, smoke, and angular shadows"] : ["wind and torchlight shape a stern face","dust and weather mark the exposed features","the face sits beneath deep cloth and metal-cast shadows"];
  return `${pick(builds,`${seed}|build`).replace(/^./,c=>c.toUpperCase())} fills the frame as ${pick(faces,`${seed}|face`)}. The figure is ${uniquePerson(index)}. The ${a}, ${b}, and ${c} ${armor} shapes the silhouette, while ${article(weapon)} ${weapon} is held in a practiced grip; ${pick(surfaces,`${seed}|surface`)} and ${pick(accents,`${seed}|accent`)} add grounded, cinematic detail.`;
}

// Build role and item context from the master sheet.
const master=values.Master, mh=master[0];
const mi=Object.fromEntries(mh.map((h,i)=>[h,i]));
const itemOwners=new Map();
const characterContext=new Map();
for (const r of master.slice(1)) {
  const context={movie:r[mi.MovieName],layer:r[mi.Layer],tile:r[mi.TileNumber]};
  for (const [role,prefix] of [["boss","Boss"],["minion","Minion"],["protagonist","Protagonist"]]) {
    const owner=r[mi[`${prefix}Name`]];
    characterContext.set(String(owner),{...context,role,owner,weapon:r[mi[`${prefix}Weapon`]],armor:r[mi[`${prefix}Armor`]]});
    for (const type of ["Weapon","Armor","Special"]) {
      itemOwners.set(String(r[mi[`${prefix}${type}`]]),{...context,role,owner,type});
    }
  }
}

const changes=[];
function writeColumn(sheetName, descIndex, make) {
  const rows=values[sheetName];
  for (let i=1;i<rows.length;i++) {
    if (!rows[i][0] && sheetName!=="Master") continue;
    const desc=make(rows[i],i);
    wb.worksheets.getItem(sheetName).getCell(i,descIndex).values=[[desc]];
    changes.push({sheet:sheetName,row:i+1,name:String(rows[i][sheetName==="Master"?mi.ProtagonistName:0]||""),description:desc});
  }
}

writeColumn("Weapons",14,weaponDescription);
writeColumn("Armor",19,armorDescription);
writeColumn("SpecialItems",34,specialDescription);
writeColumn("Master",13,(r,i)=>personDescription(r[mi.ProtagonistName],"protagonist",r[mi.Layer],r[mi.ProtagonistWeapon],r[mi.ProtagonistArmor],r[mi.MovieName],i));
writeColumn("Bosses",39,(r,i)=>{const c=characterContext.get(String(r[0]))||{}; return personDescription(r[0],"boss",c.layer||"Swords",c.weapon,c.armor,r[1],i);});
writeColumn("Minions",14,(r,i)=>{const c=characterContext.get(String(r[0]))||{}; return personDescription(r[0],"minion",c.layer||"Swords",c.weapon,c.armor,r[1],i);});

// World-boss descriptions were already bespoke physical art prompts. Clean any accidental name lead-in and retain their richer authored detail.
const world=values.WorldBosses;
for (let i=1;i<world.length;i++) {
  const name=String(world[i][0]||"").trim(); let desc=String(world[i][39]||"").trim();
  if (name) desc=desc.replace(new RegExp(`^${name.replace(/[.*+?^${}()|[\\]\\]/g,"\\$&")}\\s*(?:is|—|-|:)\\s*`,`i`),"");
  wb.worksheets.getItem("WorldBosses").getCell(i,39).values=[[desc]];
  changes.push({sheet:"WorldBosses",row:i+1,name,description:desc});
}

const banned=["is a recognizable","central hero of","principal threat from","tied directly to","carries it in","worn by"];
const problems=[]; const seen=new Map();
for (const c of changes) {
  const d=c.description.trim(), low=d.toLowerCase(), name=c.name.trim().toLowerCase();
  if (!d || d.split(/\s+/).length<20) problems.push({...c,problem:"too short or blank"});
  if (name && new RegExp(`(^|[^a-z0-9])${name.replace(/[.*+?^${}()|[\\]\\]/g,"\\$&")}([^a-z0-9]|$)`,`i`).test(d)) problems.push({...c,problem:"description repeats row name"});
  for (const phrase of banned) if (low.includes(phrase)) problems.push({...c,problem:`generic phrase: ${phrase}`});
  if (seen.has(low)) problems.push({...c,problem:`duplicate of ${seen.get(low)}`}); else seen.set(low,`${c.sheet}!${c.row}`);
}
if (problems.length) throw new Error(`Description validation failed: ${JSON.stringify(problems.slice(0,10),null,2)}`);

await SpreadsheetFile.exportXlsx(wb).then(blob=>blob.save(outputPath));
await fs.writeFile(reportPath,JSON.stringify({inputPath,outputPath,updated:changes.length,bySheet:Object.fromEntries([...new Set(changes.map(c=>c.sheet))].map(s=>[s,changes.filter(c=>c.sheet===s).length])),problems,changes},null,2),"utf8");
console.log(JSON.stringify({outputPath,updated:changes.length,bySheet:Object.fromEntries([...new Set(changes.map(c=>c.sheet))].map(s=>[s,changes.filter(c=>c.sheet===s).length]))},null,2));
