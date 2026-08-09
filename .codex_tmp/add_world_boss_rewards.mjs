import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const [source, output, previewDir] = process.argv.slice(2);
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(source));

const weaponRows = [
  ["Titanstone Reaper","Kronos (WorldBoss)",115,"Melee","d12","Explosive",20,18,4,6,10,7600,0.8,100,"Colossal crescent blade broken from Kronos's volcanic body, formed from black stone with molten orange cracks and a long jagged grip."],
  ["Gozerian Maul","Stay Puft Marshmallow Man (WorldBoss)",80,"Melee","d12","Blunt",16,15,5,10,7,4700,0.8,100,"Oversized white ceremonial mallet with rounded marshmallow-like striking faces, a blue-banded handle, and a faint supernatural glow."],
  ["Megatron's Fusion Cannon","Megatron (WorldBoss)",100,"Ranged","d12","Energy",14,14,10,8,16,6600,0.8,100,"Massive cylindrical arm-mounted cannon of dark gunmetal and silver alloy, with layered cooling vents and a bright violet energy chamber."],
  ["Maker's Crysknife","Sandworm (WorldBoss)",95,"Melee","d12","Blade",14,12,13,9,14,6100,0.8,100,"Long pale blade carved from an immense sandworm tooth, slightly curved and naturally ridged, with a dark wrapped handle and no visible seam."],
  ["Atomic Dorsal Blade","Godzilla (WorldBoss)",120,"Melee","d12","Energy",20,18,8,8,12,8200,0.8,100,"Jagged sword-like shard resembling one of Godzilla's dorsal plates, charcoal black with rough scaled edges and blue-white atomic light glowing through its core."],
];

const armorRows = [
  ["Kronos's Molten Carapace","Kronos (WorldBoss)",115,18,true,true,true,true,true,true,true,18,20,3,6,10,7900,0.75,100,"Towering suit of layered volcanic plates, black and uneven like cooled lava, with deep orange fissures glowing across the chest and shoulders."],
  ["Stay Puft Sailor Regalia","Stay Puft Marshmallow Man (WorldBoss)",80,14,false,true,false,false,true,false,true,12,18,5,10,8,4900,0.75,100,"Padded white supernatural suit with rounded limbs, blue sailor collar, red neckerchief, and a soft surface that reforms after impact."],
  ["Decepticon Command Armor","Megatron (WorldBoss)",100,17,true,true,true,true,false,true,true,17,18,8,7,13,7000,0.75,100,"Angular silver-grey robotic armor with overlapping mechanical plates, black joint assemblies, red illuminated details, and a raised Decepticon insignia."],
  ["Maker Hide Stillsuit","Sandworm (WorldBoss)",95,16,true,true,true,false,false,true,true,15,17,9,8,14,6400,0.75,100,"Heavy desert stillsuit reinforced with overlapping tan-brown plates cut from sandworm hide, sealed joints, filtration tubes, and a wrapped face covering."],
  ["Titan Scale Armor","Godzilla (WorldBoss)",120,19,true,true,true,true,true,true,true,20,20,5,7,11,8500,0.75,100,"Massive charcoal-grey armor of interlocking titan scales, with a broad chest, heavy tail-like back guard, and jagged dorsal plates glowing blue-white."],
];

const specialRows = [
  ["Ember of Tartarus","Kronos","WorldBoss",16,18,5,8,12,6,true,0.1,0.5,12,true,true,true,true,true,true,true,"Explosive",14,0.4,0.4,0.1,5,0.35,0.4,0.1,0.2,0.25,9800,0.6,100,"Fist-sized core of black volcanic stone split by pulsing molten fissures, radiating heat and ancient imprisoned power."],
  ["Gozerian Destructor Sigil","Stay Puft Marshmallow Man","WorldBoss",10,16,7,14,10,8,true,0.12,0.6,8,false,true,false,false,true,false,true,"Blunt",10,0.35,0.45,0.15,5,0.4,0.3,0.15,0.25,0.25,7200,0.6,100,"Small bronze disk engraved with Gozerian symbols, its recessed markings filled with glossy white material that shifts when unobserved."],
  ["AllSpark Fragment","Megatron","WorldBoss",14,15,10,10,16,10,true,0.15,0.7,10,true,true,true,true,false,true,true,"Energy",14,0.4,0.4,0.15,6,0.3,0.35,0.15,0.25,0.3,9200,0.6,100,"Angular shard of metallic alien machinery covered in dense geometric glyphs, with blue-white energy moving beneath its dark silver surface."],
  ["Water of Life","Sandworm","WorldBoss",10,14,12,12,18,9,true,0.12,0.6,9,true,true,true,false,true,true,true,"Venom",12,0.45,0.35,0.2,5,0.4,0.3,0.15,0.25,0.35,8800,0.6,100,"Small sealed crystal vial containing intensely blue liquid, fitted into an ornate desert-metal frame with fine tubing and engraved maker symbols."],
  ["G-Cell Reactor","Godzilla","WorldBoss",18,18,8,10,14,8,true,0.15,0.75,12,true,true,true,true,true,true,true,"Energy",16,0.45,0.4,0.15,6,0.45,0.4,0.1,0.2,0.3,10500,0.6,100,"Dense cluster of charcoal-black regenerative cells suspended in a reinforced capsule, pulsing rhythmically with brilliant blue atomic energy."],
];

for (const [sheetName, rows] of [["Weapons", weaponRows], ["Armor", armorRows], ["SpecialItems", specialRows]]) {
  const sheet = workbook.worksheets.getItem(sheetName);
  const used = sheet.getUsedRange(true);
  const start = used.rowCount;
  sheet.getRangeByIndexes(start, 0, rows.length, rows[0].length).values = rows;
}

const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(output);
console.log((await workbook.inspect({kind:"table",range:"Weapons!A76:O83",include:"values",tableMaxRows:10,tableMaxCols:15})).ndjson);
