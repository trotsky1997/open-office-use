"""Check fixed validation list suggestions and stale-grid locking."""
import subprocess
import watch

script = watch.PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
helper = script.split('function validationList(validation, cell) {', 1)[1].split('async function loadGrid', 1)[0]
locking = script.split('function lockGridInputs(inputs, locked) {', 1)[1].split('function elementDirty()', 1)[0]
subprocess.run(['node', '-e', '''
const assert=require('node:assert/strict');
new Function(process.argv[1]);
function validationList(validation, cell) {''' + helper + '''
function lockGridInputs(inputs, locked) {''' + locking + '''
const rule={cells:['A1'], attributes:{type:'list'}, formula1:'"Low,001,=text"'};
const data={complete:true, rules:[rule]};
assert.deepEqual(validationList(data,'A1'),['Low','001','=text']);
assert.equal(validationList(data,'B1'),null);
assert.equal(validationList({...data,complete:false},'A1'),null);
assert.equal(validationList({...data,rules:[rule,rule]},'A1'),null);
assert.equal(validationList({...data,rules:[{...rule,formula1:'Sheet1!A1:A3'}]},'A1'),null);
assert.deepEqual(validationList({...data,rules:[{...rule,list_resolution:'resolved',list_values:['001','=text']}]},'A1'),['001','=text']);
const controls=[{},{}], input={dataset:{editable:'true'},parentElement:{querySelectorAll(){return controls;}}};
lockGridInputs([input],true); assert.ok(input.readOnly && controls.every(item=>item.disabled));
lockGridInputs([input],false); assert.ok(!input.readOnly && controls.every(item=>!item.disabled));
input.dataset.editable='false'; lockGridInputs([input],false); assert.ok(input.readOnly && controls.every(item=>item.disabled));
''', script], check=True)
print('Grid validation controls smoke passed')
