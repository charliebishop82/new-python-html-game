import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/swords_and_circuits_36_20260815/GameContent_Swords_and_Circuits_36_Balanced_2026-08-15.xlsx";
const outputPath = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/description_artwork_20260816/description_audit.json";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const targets = {
  Master: "A1:S37",
  Bosses: "A1:AN37",
  Minions: "A1:AC37",
  Weapons: "A1:O119",
  Armor: "A1:T119",
  SpecialItems: "A1:AI119",
  WorldBosses: "A1:AN11",
};
const output = {};
for (const [sheetName, range] of Object.entries(targets)) {
  const sheet = workbook.worksheets.getItem(sheetName);
  output[sheetName] = sheet.getRange(range).values;
}
await fs.writeFile(outputPath, JSON.stringify(output, null, 2), "utf8");
console.log(`Saved ${outputPath}`);
