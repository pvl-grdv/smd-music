import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

function usage() {
  console.error("usage: node _mucom_compile.mjs <mucom88-js/dist/index.js> <input.muc> <output.mub>");
  process.exit(2);
}

if (process.argv.length < 5) usage();
const modulePath = path.resolve(process.argv[2]);
const input = path.resolve(process.argv[3]);
const output = path.resolve(process.argv[4]);

const { Mucom88 } = await import(pathToFileURL(modulePath).href);
await Mucom88.initialize();

const raw = fs.readFileSync(input);
let mml;
try {
  mml = new TextDecoder("utf-8", { fatal: true }).decode(raw);
} catch {
  mml = new TextDecoder("shift_jis").decode(raw);
}

function attachment(name) {
  const re = new RegExp(`^#${name}\\s+([^\\s]+)$`, "mi");
  return mml.match(re)?.[1] ?? null;
}

function ensureMemDir(file) {
  const parts = file.split(/[\\/]+/).slice(0, -1);
  let current = "";
  for (const part of parts) {
    if (!part || part === ".") continue;
    current += `/${part}`;
    try { Mucom88.FS.mkdir(current); } catch {}
  }
}

function copyAttachment(name) {
  if (!name) return;
  const diskPath = path.resolve(path.dirname(input), name);
  if (!fs.existsSync(diskPath)) return;
  ensureMemDir(name);
  const data = fs.readFileSync(diskPath);
  const memPath = name.replaceAll("\\", "/");
  const fp = Mucom88.FS.open(memPath, "w");
  Mucom88.FS.write(fp, data, data.byteOffset, data.byteLength);
  Mucom88.FS.close(fp);
}

copyAttachment(attachment("voice"));
copyAttachment(attachment("pcm"));

const mucom = new Mucom88();
try {
  mucom.reset(55467);
  const mub = mucom.compile(mml);
  if (!mub || mub.length === 0) {
    throw new Error(mucom.getMessageBuffer() || "MUCOM88 compile returned no data");
  }
  fs.writeFileSync(output, Buffer.from(mub));
  const messages = mucom.getMessageBuffer();
  if (messages.trim()) process.stderr.write(messages);
} finally {
  mucom.release();
}
