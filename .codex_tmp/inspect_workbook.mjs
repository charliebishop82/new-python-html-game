import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = process.argv[2];
const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const sheets = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 12000,
});
console.log("SHEETS");
console.log(sheets.ndjson);

for (const sheet of workbook.worksheets.items) {
  const used = sheet.getUsedRange(true);
  if (!used) continue;
  const rowCount = Math.min(used.rowCount, 12);
  const colCount = Math.min(used.columnCount, 40);
  const range = sheet.getRangeByIndexes(0, 0, rowCount, colCount);
  console.log(`\nSHEET ${sheet.name} ${used.address}`);
  console.log(JSON.stringify(range.values));
}

const perks = workbook.worksheets.getItem("Perks").getUsedRange(true).values;
console.log("\nFULL Perks");
console.log(JSON.stringify(perks));

const worldBossNames = new Set(
  workbook.worksheets.getItem("WorldBosses").getUsedRange(true).values.slice(1).map((row) => row[0]),
);
for (const name of ["Weapons", "Armor", "SpecialItems"]) {
  const rows = workbook.worksheets.getItem(name).getUsedRange(true).values;
  const matches = rows.slice(1).filter((row) => {
    const association = String(row[1] ?? "");
    return [...worldBossNames].some((bossName) => association.startsWith(bossName));
  });
  console.log(`\nWORLD BOSS ITEMS ${name}`);
  console.log(JSON.stringify([rows[0], ...matches]));
}

const armorRows = workbook.worksheets.getItem("Armor").getUsedRange(true).values;
console.log("\nDUPLICATE EMPEROR ROBES");
console.log(JSON.stringify(armorRows.filter((row) => row[0] === "Emperor's Robes")));
const wbRows = workbook.worksheets.getItem("WorldBosses").getUsedRange(true).values;
console.log("\nHAL ROW");
console.log(JSON.stringify([wbRows[0], ...wbRows.filter((row) => row[0] === "HAL 9000")]));
