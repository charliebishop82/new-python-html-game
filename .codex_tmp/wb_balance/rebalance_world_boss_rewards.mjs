import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = process.argv[2];
const outputPath = process.argv[3];
const auditPath = process.argv[4];
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));

const worldBossSheet = workbook.worksheets.getItem("WorldBosses");
const worldBossValues = worldBossSheet.getUsedRange(true).values;
const worldBossHeaders = worldBossValues[0];
const wbNameCol = worldBossHeaders.indexOf("Name");
const wbLevelCol = worldBossHeaders.indexOf("Level");
const bossLevels = new Map(worldBossValues.slice(1).map(row => [String(row[wbNameCol]), Number(row[wbLevelCol])]));

const audit = [];
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const scaledStat = (value, factor, cap) => {
  const current = Number(value || 0);
  return current > 0 ? clamp(Math.round(current * factor), 1, cap) : 0;
};
const setCell = (sheet, rowIndex, colIndex, value, record) => {
  const before = sheet.getCell(rowIndex, colIndex).values[0][0];
  if (before !== value) {
    sheet.getCell(rowIndex, colIndex).values = [[value]];
    record.changes.push({ column: record.headers[colIndex], before, after: value });
  }
};

for (const sheetName of ["Weapons", "Armor", "SpecialItems"]) {
  const sheet = workbook.worksheets.getItem(sheetName);
  const values = sheet.getUsedRange(true).values;
  const headers = values[0];
  const col = Object.fromEntries(headers.map((name, index) => [name, index]));

  for (let rowIndex = 1; rowIndex < values.length; rowIndex += 1) {
    const row = values[rowIndex];
    const associated = String(row[col.AssociatedTo] || "");
    const isWorldBoss = sheetName === "SpecialItems"
      ? String(row[col.AssociationType] || "") === "WorldBoss"
      : associated.endsWith(" (WorldBoss)");
    if (!isWorldBoss) continue;

    const record = { sheet: sheetName, item: row[col.Name], headers, changes: [] };
    const bossName = associated.replace(/ \(WorldBoss\)$/, "");

    if (sheetName === "Weapons") {
      setCell(sheet, rowIndex, col.Level, (bossLevels.get(bossName) || 10) + 3, record);
      for (const field of ["STR", "END", "AGI", "LCK", "PER"])
        setCell(sheet, rowIndex, col[field], scaledStat(row[col[field]], 0.18, 4), record);
    } else if (sheetName === "Armor") {
      setCell(sheet, rowIndex, col.Level, (bossLevels.get(bossName) || 10) + 3, record);
      setCell(sheet, rowIndex, col.AC_Bonus, clamp(Math.round(Number(row[col.AC_Bonus] || 0) * 0.35), 5, 7), record);
      for (const field of ["STR", "END", "AGI", "LCK", "PER"])
        setCell(sheet, rowIndex, col[field], scaledStat(row[col[field]], 0.15, 3), record);
    } else {
      for (const field of ["STR", "END", "AGI", "LCK", "PER"])
        setCell(sheet, rowIndex, col[field], scaledStat(row[col[field]], 0.15, 3), record);
      setCell(sheet, rowIndex, col.InitiativeBonus, clamp(Math.round(Number(row[col.InitiativeBonus] || 0) * 0.25), 2, 3), record);
      setCell(sheet, rowIndex, col.ExtraAttack, false, record);
      setCell(sheet, rowIndex, col.CritChanceBonus, Math.min(Number(row[col.CritChanceBonus] || 0), 0.05), record);
      setCell(sheet, rowIndex, col.CritDmgMultiplier, Math.min(Number(row[col.CritDmgMultiplier] || 0), 0.25), record);
      setCell(sheet, rowIndex, col.ACBonus, clamp(Math.round(Number(row[col.ACBonus] || 0) * 0.25), 2, 3), record);
      setCell(sheet, rowIndex, col.BonusDamageAmount, clamp(Math.round(Number(row[col.BonusDamageAmount] || 0) * 0.5), 5, 7), record);
      setCell(sheet, rowIndex, col.XPMultiplier, 0.1, record);
      setCell(sheet, rowIndex, col.CreditMultiplier, 0.1, record);
      setCell(sheet, rowIndex, col.StealBonus, 0.05, record);
      setCell(sheet, rowIndex, col.BonusAP, 2, record);
      setCell(sheet, rowIndex, col.HPRegenBonus, 1, record);
      setCell(sheet, rowIndex, col.DurabilityReduction, 0.1, record);
      setCell(sheet, rowIndex, col.ShopDiscount, 0.05, record);
      setCell(sheet, rowIndex, col.SellBonus, 0.1, record);
      setCell(sheet, rowIndex, col.EncounterBonus, 0.1, record);
    }
    audit.push(record);
  }
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.writeFile(auditPath, JSON.stringify(audit.map(({ headers, ...rest }) => rest), null, 2), "utf8");
