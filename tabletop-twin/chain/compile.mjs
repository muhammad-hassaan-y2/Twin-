// Compiles the agent contracts with the locally installed solc and writes the artifacts
// the node sidecar deploys. Nothing is downloaded at run time: the bytecode in
// artifacts/ is the bytecode this repository was tested with.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import solc from 'solc';

const require = createRequire(import.meta.url);
const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1'));
const sourcesDir = path.join(here, 'contracts');
const outDir = path.join(here, 'artifacts');

const sources = {};
for (const file of fs.readdirSync(sourcesDir)) {
  if (!file.endsWith('.sol')) continue;
  sources[file] = { content: fs.readFileSync(path.join(sourcesDir, file), 'utf8') };
}

const input = {
  language: 'Solidity',
  sources,
  settings: {
    optimizer: { enabled: true, runs: 200 },
    outputSelection: { '*': { '*': ['abi', 'evm.bytecode.object', 'evm.methodIdentifiers'] } },
  },
};

const parsed = JSON.parse(solc.compile(JSON.stringify(input)));
for (const error of parsed.errors || []) {
  console.log(`${error.severity}: ${error.formattedMessage?.trim() || error.message}`);
}
const fatal = (parsed.errors || []).filter((e) => e.severity === 'error');
if (fatal.length) {
  console.error(`compile failed with ${fatal.length} error(s)`);
  process.exit(1);
}

fs.mkdirSync(outDir, { recursive: true });
const names = [];
for (const [file, byContract] of Object.entries(parsed.contracts || {})) {
  for (const [name, artifact] of Object.entries(byContract)) {
    if (!artifact.evm.bytecode.object) continue;
    const out = {
      source: file,
      contract: name,
      abi: artifact.abi,
      bytecode: '0x' + artifact.evm.bytecode.object,
      selectors: artifact.evm.methodIdentifiers,
      compiler: solc.version(),
    };
    fs.writeFileSync(path.join(outDir, `${name}.json`), JSON.stringify(out, null, 1) + '\n');
    names.push(`${name} (${artifact.evm.bytecode.object.length / 2} bytes)`);
  }
}
console.log(`solc ${solc.version()}`);
console.log(`compiled: ${names.join(', ')}`);
console.log(`artifacts -> ${outDir}`);
