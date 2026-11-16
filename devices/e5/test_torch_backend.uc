// Run the production ucode routes with fake LED files; no hardware access.
import { readfile } from 'fs';

const PREFIX = '/sys/class/leds/e5:white:torch/';
let files = { max_brightness: '1\n', brightness: '0\n' };
let writes = [], fail = false, ignore = false;
function check(value, message) { if (!value) die(message); }
global.torch_read = path => {
 check(substr(path, 0, length(PREFIX)) == PREFIX, 'unexpected hardware path');
 return files[substr(path, length(PREFIX))];
};
global.torch_write = (path, value) => {
 check(path == PREFIX + 'brightness', 'unexpected write target');
 check(value == '0\n' || value == '1\n', 'non-binary LED write');
 push(writes, value);
 if (fail) return null;
 if (!ignore) files.brightness = value;
 return length(value);
};
let source = readfile(ARGV[0]);
check(type(source) == 'string', 'missing backend');
source = replace(source, "import { readfile, writefile } from 'fs';",
 'let readfile = global.torch_read, writefile = global.torch_write;');
let routes = loadstring(source, ARGV[0])()({});
let get = routes['GET /state'], toggle = routes['POST /toggle'];
check(get().ok && get().on == false && !length(writes), 'initial state must be read-only');
files.brightness = '1\n';
check(get().on == true, 'external change not read');
check(toggle({body:{on:true,path:'/etc/shadow'}}).on == false, 'must toggle hardware, ignore supplied state/path');
check(toggle({body:{}}).on == true, 'second toggle failed');
check(length(writes) == 2, 'unexpected writes');
fail = true;
let result = toggle({body:{}});
check(!result.ok && result.on == true && result.error == 'write_failed', 'write failure reported success');
fail = false; ignore = true;
result = toggle({body:{}});
check(!result.ok && result.on == true && result.error == 'readback_failed', 'readback not checked');
ignore = false;
for (let bad in [null, '', '9\n', 'garbage']) {
 files.brightness = bad;
 let count = length(writes);
 check(!get().ok && get().on == null && !get().available, 'invalid brightness accepted');
 check(!toggle({body:{}}).ok && length(writes) == count, 'wrote to unavailable LED');
}
files.brightness = '0\n'; files.max_brightness = '255\n';
check(!get().available, 'wrong LED topology accepted');
files.max_brightness = '1\n';
check(get().ok && get().on == false, 'recovery not reflected');
print('PASS: real ucode routes, hardware state, toggles, fixed target, write errors and readback\n');
