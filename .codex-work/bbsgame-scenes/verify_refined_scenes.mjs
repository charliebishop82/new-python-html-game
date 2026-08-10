import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const sourcePath = "C:/Users/charl/OneDrive/Desktop/bbsgame/outputs/019fc439-d617-7783-a9b4-5347c2d0bf25/GameContent_Perks_Worldbosses_with_Refined_Scenes.xlsx";
const workDir = "C:/Users/charl/OneDrive/Desktop/bbsgame/.codex-work/bbsgame-scenes";
const source = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));
for (const spec of [
  { name: "Scenes", renderRange: "A35:T52" },
  { name: "SceneChoices", renderRange: "A172:P211" },
]) {
  const image = await source.render({ sheetName: spec.name, range: spec.renderRange, scale: 0.7, format: "png" });
  await fs.writeFile(`${workDir}/${spec.name}_refined.png`, new Uint8Array(await image.arrayBuffer()));
  console.log(`Rendered ${spec.name}`);
}
