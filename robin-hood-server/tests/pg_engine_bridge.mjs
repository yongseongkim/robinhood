import { pathToFileURL } from "node:url";
import path from "node:path";
const modulePath =
  process.env.PGLITE_MODULE ||
  path.resolve("../.artifacts/postgres/pglite/package/dist/index.js");
const { PGlite } = await import(pathToFileURL(modulePath).href);
import readline from "node:readline";
const db = new PGlite();
await db.waitReady;
for await (const line of readline.createInterface({ input: process.stdin })) {
  const request = JSON.parse(line);
  try {
    const result =
      request.op === "exec"
        ? await db.exec(request.sql)
        : await db.query(request.sql, request.args || []);
    process.stdout.write(
      JSON.stringify({ result }, (_, v) =>
        typeof v === "bigint" ? v.toString() : v,
      ) + "\n",
    );
  } catch (e) {
    process.stdout.write(
      JSON.stringify({ error: e.message, code: e.code }) + "\n",
    );
  }
}
await db.close();
