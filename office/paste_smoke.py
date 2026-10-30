"""Check the viewer's TSV parser with Node.js."""
import subprocess

import watch

parser = watch.PAGE.split('function parseGridPaste(text) {', 1)[1].split("document.getElementById('grid-output').addEventListener('paste'", 1)[0]
subprocess.run(['node', '-e', 'function parseGridPaste(text) {' + parser + r'''
const assert=require('node:assert/strict');
assert.deepEqual(parseGridPaste('7\t\r\n=B1*3\t\r\n'), [['7',''],['=B1*3','']]);
assert.deepEqual(parseGridPaste('"a\tb"\t"a ""quote"""'), [['a\tb','a "quote"']]);
for (const text of ['a\tb\nc', '"a\nb"\tc', '"unterminated\tx']) {
  assert.throws(() => parseGridPaste(text));
}
'''], check=True)
print('Paste smoke passed: rectangular TSV, quoted content and invalid input')
