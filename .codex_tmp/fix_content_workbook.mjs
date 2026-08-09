import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const source = process.argv[2];
const output = process.argv[3];
const previewRoot = process.argv[4];
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(source));

async function renderAll(folder) {
  await fs.mkdir(folder, { recursive: true });
  for (const sheet of workbook.worksheets.items) {
    const preview = await workbook.render({ sheetName: sheet.name, autoCrop: "all", scale: 0.8, format: "png" });
    await fs.writeFile(path.join(folder, `${sheet.name.replace(/[^a-z0-9]+/gi, "_")}.png`),
      new Uint8Array(await preview.arrayBuffer()));
  }
}

const armor = workbook.worksheets.getItem("Armor");
const armorValues = armor.getUsedRange(true).values;
for (let row = 1; row < armorValues.length; row += 1) {
  if (armorValues[row][0] === "Emperor's Robes" && String(armorValues[row][1]).includes("Emperor Palpatine")) {
    armor.getCell(row, 0).values = [["Palpatine's Imperial Robes"]];
  }
}

const worldBosses = workbook.worksheets.getItem("WorldBosses");
const wbValues = worldBosses.getUsedRange(true).values;
const resBluntColumn = wbValues[0].indexOf("Res_Blunt");
for (let row = 1; row < wbValues.length; row += 1) {
  if (wbValues[row][0] === "HAL 9000") {
    worldBosses.getCell(row, resBluntColumn).values = [[false]];
  }
}

await fs.mkdir(path.dirname(output), { recursive: true });
const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(output);

const check = await workbook.inspect({
  kind: "match",
  searchTerm: "Palpatine's Imperial Robes|HAL 9000",
  options: { useRegex: true, maxResults: 20 },
  summary: "authorized content corrections",
});
console.log(check.ndjson);
