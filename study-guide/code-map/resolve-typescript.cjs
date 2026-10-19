// Parse source only. Never import or execute the frontend application.
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const root = fs.realpathSync(process.argv[2]);
const ts = createRequire(path.join(root, 'package.json'))('typescript');
const references = JSON.parse(fs.readFileSync(0, 'utf8'));
const files = new Map();
const ranges = {};
for (const [id, reference] of Object.entries(references)) {
  const filename = fs.realpathSync(path.resolve(root, reference.file));
  if (!filename.startsWith(path.join(root, 'src') + path.sep)) {
    throw new Error(`Source outside frontend src: ${reference.file}`);
  }
  if (!files.has(filename)) {
    const source = ts.createSourceFile(filename, fs.readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true);
    if (source.parseDiagnostics.length) throw new Error(`Invalid TypeScript: ${filename}`);
    const symbols = new Map();
    function visit(node, parents) {
      const named = ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node)
        || ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node)
        || ts.isVariableDeclaration(node) || ts.isMethodDeclaration(node)
        || ts.isPropertyAssignment(node);
      const name = named && node.name && (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)) ? node.name.text : null;
      const scope = name ? [...parents, name] : parents;
      if (name) {
        const symbol = scope.join('.');
        const ranges = symbols.get(symbol) ?? [];
        ranges.push([source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
          source.getLineAndCharacterOfPosition(node.end).line + 1]);
        symbols.set(symbol, ranges);
      }
      ts.forEachChild(node, child => visit(child, scope));
    }
    visit(source, []);
    files.set(filename, symbols);
  }
  const matches = files.get(filename).get(reference.symbol);
  if (matches?.length !== 1) throw new Error(`Cannot uniquely resolve ${reference.symbol} in ${reference.file}`);
  ranges[id] = matches[0];
}
process.stdout.write(JSON.stringify(ranges));
