import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
const input = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/swords_and_circuits_36_20260815/GameContent_Swords_and_Circuits_36_Balanced_2026-08-15.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(input));
const preview = await workbook.render({ sheetName: "Weapons", range: "A1:O8", scale: 1, format: "png" });
await fs.writeFile("before_weapons.png", new Uint8Array(await preview.arrayBuffer()));
console.log("Rendered before_weapons.png");
