"""Check the viewer's TSV parser with Node.js."""
import subprocess

import watch

parser = watch.PAGE.split('function parseGridPaste(text) {', 1)[1].split("document.getElementById('grid-output').addEventListener('paste'", 1)[0]
changed = watch.PAGE.split('function gridChanged(input) {', 1)[1].split('function gridDirty()', 1)[0]
subprocess.run(['node', '-e', 'function gridChanged(input) {' + changed + 'function parseGridPaste(text) {' + parser + r'''
const assert=require('node:assert/strict');
const cell=(value, baseline, mode)=>({value,dataset:{baseline},parentElement:{querySelector:()=>({value:mode})}});
assert.equal(gridChanged(cell('123','123','default')), false);
assert.equal(gridChanged(cell('123','123','text')), true);
assert.equal(gridChanged(cell('changed','old','default')), true);
assert.equal(gridChanged(cell('','','text')), false);
assert.deepEqual(parseGridPaste('7\t\r\n=B1*3\t\r\n'), [['7',''],['=B1*3','']]);
assert.deepEqual(parseGridPaste('"a\tb"\t"a ""quote"""'), [['a\tb','a "quote"']]);
assert.deepEqual(parseGridPaste('"a\r\nb"\tc'), [['a\nb','c']]);
for (const text of ['a\tb\nc', '"unterminated\tx']) {
  assert.throws(() => parseGridPaste(text));
}
'''], check=True)
print('Paste smoke passed: rectangular TSV, quoted content and invalid input')
