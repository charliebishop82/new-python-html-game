import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const [source, output] = process.argv.slice(2);
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(source));
const old = workbook.worksheets.getItemOrNullObject?.("Contracts");
if (old && !old.isNullObject) old.delete();
const sheet = workbook.worksheets.add("Contracts");
const rows = [
  ["Name","Description","Metric","Target","RewardXP","RewardCredits","RewardAP","MinLevel"],
  ["Three Names Crossed Out","Win three battles against other characters before midnight.","PVP_WINS",3,450,300,2,2],
  ["Villain of the Day","Defeat three movie bosses before midnight.","BOSS_WINS",3,500,325,2,2],
  ["Raid Call Sheet","Attack the weekly multiplayer world boss three times before midnight.","WORLD_BOSS_ATTEMPTS",3,425,350,2,1],
  ["Clean Up the Extras","Defeat five roaming minions before midnight.","MINION_WINS",5,400,275,2,1],
  ["Five-Scene Winning Streak","Win five completed combats of any kind before midnight.","COMBAT_WINS",5,525,350,2,2],
  ["Leave a Mark","Deal 150 post-resistance damage across completed combats before midnight.","DAMAGE_DEALT",150,500,300,2,3],
];
sheet.getRangeByIndexes(0,0,rows.length,rows[0].length).values = rows;
const header = sheet.getRange("A1:H1");
header.format.fill = "#151515"; header.format.font = {bold:true,color:"#ffb000"};
sheet.getRange(`A2:H${rows.length}`).format.fill = "#f7f2e7";
sheet.getRange(`A1:H${rows.length}`).format.borders = {style:"continuous",color:"#b89b65"};
sheet.getRange("A:A").format.columnWidth = 25;
sheet.getRange("B:B").format.columnWidth = 62;
sheet.getRange("C:C").format.columnWidth = 24;
sheet.getRange("D:H").format.columnWidth = 14;
sheet.getRange(`A1:H${rows.length}`).format.wrapText = true;
sheet.freezePanes.freezeRows(1);
const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(output);
console.log((await workbook.inspect({kind:"table",range:`Contracts!A1:H${rows.length}`,include:"values",tableMaxRows:20,tableMaxCols:10})).ndjson);
