import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/swords_and_circuits_36_20260815/GameContent_Swords_and_Circuits_36_Balanced_2026-08-15.xlsx";
const outputDir = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/description_artwork_20260816";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));

const sheetInfo = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 12000,
});
console.log(sheetInfo.ndjson);

const sheetNames = ["README", "Master", "Bosses", "Minions", "Weapons", "Armor",
  "SpecialItems", "Classes", "RandomEvents", "Settings", "WorldBosses", "Perks",
  "Contracts", "Scenes", "SceneChoices"];
for (const sheetName of sheetNames) {
  try {
    const preview = await workbook.render({
      sheetName,
      range: "A1:H12",
      scale: 1,
      format: "png",
    });
    await fs.writeFile(`${outputDir}/before_${sheetName.replace(/[^a-z0-9]+/gi, "_")}.png`,
      new Uint8Array(await preview.arrayBuffer()));
  } catch (error) {
    console.error(`Render failed for ${sheetName}:`, error?.message || error);
  }
}

const summary = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 20000,
  tableMaxRows: 5,
  tableMaxCols: 18,
  tableMaxCellChars: 180,
});
await fs.writeFile(`${outputDir}/workbook_summary.ndjson`, summary.ndjson, "utf8");
console.log("Rendered workbook sheet samples and saved compact summary.");
