import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
const [source, preview] = process.argv.slice(2);
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(source));
const errors = await workbook.inspect({kind:"match",searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",options:{useRegex:true,maxResults:100},summary:"contract workbook formula errors"});
console.log(errors.ndjson);
const image = await workbook.render({sheetName:"Contracts",range:"A1:H7",scale:1.5,format:"png"});
await fs.writeFile(preview,new Uint8Array(await image.arrayBuffer()));
