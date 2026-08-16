import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const path="C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/description_artwork_20260816/GameContent_Swords_and_Circuits_36_ArtDescriptions_2026-08-16.xlsx";
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(path));
const ranges={Master:"A1:S37",Bosses:"A1:AN37",Minions:"A1:AC37",Weapons:"A1:O119",Armor:"A1:T119",SpecialItems:"A1:AI119",WorldBosses:"A1:AN11"};
const descCols={Master:13,Bosses:39,Minions:14,Weapons:14,Armor:19,SpecialItems:34,WorldBosses:39};
const checks={file:path,rows:{},samples:{},formulaErrors:[]};
for (const [sheet,range] of Object.entries(ranges)) {
  const vals=wb.worksheets.getItem(sheet).getRange(range).values;
  const descriptions=vals.slice(1).map(r=>String(r[descCols[sheet]]||"").trim());
  checks.rows[sheet]={count:descriptions.length,nonblank:descriptions.filter(Boolean).length,minWords:Math.min(...descriptions.map(d=>d.split(/\s+/).length)),unique:new Set(descriptions).size};
  checks.samples[sheet]=[descriptions[0],descriptions[Math.floor(descriptions.length/2)],descriptions.at(-1)];
}
const errors=await wb.inspect({kind:"match",searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",options:{useRegex:true,maxResults:300},summary:"final formula error scan"});
checks.formulaErrors=(errors.ndjson||"").trim().split(/\r?\n/).filter(Boolean);
await fs.writeFile("C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/description_artwork_20260816/final_verification.json",JSON.stringify(checks,null,2),"utf8");
console.log(JSON.stringify(checks,null,2));
