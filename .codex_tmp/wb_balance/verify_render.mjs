import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(process.argv[2]));
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
  maxChars: 5000,
});
console.log(errors.ndjson);
const preview = await workbook.render({ sheetName: "Armor", range: "A70:T83", scale: 0.55, format: "png" });
await fs.writeFile(process.argv[3], new Uint8Array(await preview.arrayBuffer()));
