import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = process.argv[2];
const outputDir = process.argv[3];
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
await fs.mkdir(outputDir, { recursive: true });

const overview = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 5000,
});
console.log(overview.ndjson);

for (const sheetName of ["WorldBosses", "Weapons", "Armor", "SpecialItems"]) {
  const sheet = workbook.worksheets.getItem(sheetName);
  const used = sheet.getUsedRange(true);
  const table = await workbook.inspect({
    kind: "table",
    sheetId: sheetName,
    range: used.address,
    include: "values,formulas",
    tableMaxRows: 140,
    tableMaxCols: 40,
    tableMaxCellChars: 100,
    maxChars: 50000,
  });
  await fs.writeFile(`${outputDir}/${sheetName}.ndjson`, table.ndjson, "utf8");
  const style = await workbook.inspect({
    kind: "computedStyle",
    sheetId: sheetName,
    range: "A1:H6",
    maxChars: 5000,
  });
  await fs.writeFile(`${outputDir}/${sheetName}-style.ndjson`, style.ndjson, "utf8");
}
