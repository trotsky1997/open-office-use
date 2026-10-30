"""Check the viewer clears submitted format choices while retaining target and palette."""
import subprocess
import watch

body = watch.PAGE.split('function resetGridFormatting() {', 1)[1].split("document.getElementById('grid-format').addEventListener", 1)[0]
subprocess.run(['node', '-e', '''
const assert=require('node:assert/strict');
const controls={};
global.document={getElementById(id) { return controls[id] ||= {value:'chosen', checked:true}; }};
function resetGridFormatting() {''' + body + '''
resetGridFormatting();
for (const name of ['bold','italic','underline','horizontal','vertical','wrap','border','font-name','font-size','numberformat']) assert.equal(controls['grid-'+name].value,'');
assert.equal(controls['grid-border-scope'].value,'all');
for (const name of ['font-color','fill','border-color']) assert.equal(controls['grid-'+name+'-enabled'].checked,false);
assert.equal(controls['grid-style-range'],undefined);
assert.equal(controls['grid-border-color'],undefined);
'''], check=True)
print('Grid formatting controls smoke passed')
