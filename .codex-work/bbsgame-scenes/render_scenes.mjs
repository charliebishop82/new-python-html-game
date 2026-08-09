import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const sourcePath = "C:/Users/charl/OneDrive/Desktop/bbsgame/data/GameContent_Perks_Worldbosses.xlsx";
const workDir = "C:/Users/charl/OneDrive/Desktop/bbsgame/.codex-work/bbsgame-scenes";
const source = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));
const previewBook = Workbook.create();

for (const [sheetName, range, widths] of [
  ["Scenes", "A1:T10", [["A:A",22],["B:B",21],["C:C",24],["D:D",55],["E:G",21],["H:J",10],["K:M",22],["N:N",15],["O:P",18],["Q:S",18],["T:T",42]]],
  ["SceneChoices", "A1:P46", [["A:A",22],["B:B",20],["C:C",10],["D:D",50],["E:E",10],["F:G",55],["H:I",14],["J:J",22],["K:K",14],["L:L",20],["M:M",14],["N:N",16],["O:O",18],["P:P",38]]],
]) {
  const values = source.worksheets.getItem(sheetName).getRange(range).values;
  const sheet = previewBook.worksheets.add(sheetName);
  sheet.getRange(range).values = values;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  const used = sheet.getRange(range);
  used.format.font = { typeface: "Calibri", fontSize: 9 };
  used.format.verticalAlignment = "top";
  used.format.wrapText = true;
  sheet.getRangeByIndexes(0, 0, 1, values[0].length).format = {
    fill: "#1F3864", font: { typeface: "Calibri", fontSize: 9, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center", verticalAlignment: "center", wrapText: true,
    borders: { preset: "all", style: "thin", color: "#CCCCCC" }, rowHeight: 32,
  };
  sheet.getRangeByIndexes(1, 0, values.length - 1, values[0].length).format.rowHeight = 48;
  for (const [colRange, width] of widths) sheet.getRange(colRange).format.columnWidth = width;
  const renderRange = sheetName === "Scenes" ? "A1:T10" : "A1:P16";
  const image = await previewBook.render({ sheetName, range: renderRange, scale: 1, format: "png" });
  await fs.writeFile(`${workDir}/${sheetName}.png`, new Uint8Array(await image.arrayBuffer()));
  console.log(`Rendered ${sheetName}`);
}
