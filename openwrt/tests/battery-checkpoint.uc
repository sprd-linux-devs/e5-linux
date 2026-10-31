import * as fs from 'fs';
import { little, encode_time, native_record_matches, checkpoint_file,
         checkpoint_interval_ms } from '/guard/checkpoint.uc';

function check(ok, message) { if (!ok) die('FAIL: ' + message + '\n'); };
const fields = 'charge.shutdown_rtc_time=1793377111 charge.charge_cycle=5318 charge.basp=-1 charge.total_mah=3000000 ';
let record = substr(encode_time(0x5a5aa5a5), 0, 4) + encode_time(1793380165) +
    substr(encode_time(5318), 0, 4) + substr(encode_time(0xffffffff), 0, 4) +
    substr(encode_time(3000000 ^ 0x20160726), 0, 4) + substr(encode_time(3000000 ^ 0x15211517), 0, 4);
check(length(record) == 28 && native_record_matches(record, fields), 'actual LK/native record');
check(native_record_matches(record, fields + chr(0)), 'DT terminator');
check(!native_record_matches(record, fields + 'charge.basp=-1'), 'duplicate fields');
check(!native_record_matches(record, replace(fields, '5318', '5319')), 'wrong charge cycle');
check(!native_record_matches(record, replace(fields, 'basp=-1', 'basp=0')), 'wrong BASP');
check(!native_record_matches(record, replace(fields, '3000000', '2900000')), 'wrong learned capacity');
check(!native_record_matches(substr(record, 0, 27), fields), 'short record');
check(!native_record_matches(replace(record, chr(0x5a), chr(0x59)), fields), 'bad magic');
check(!native_record_matches(record, 'other bootloader'), 'missing native fields');
for (let i = 0; i < 28; i++) {
    if (i >= 4 && i < 12) continue; // LK resets the timestamp after emitting bootargs.
    for (let bit = 0; bit < 8; bit++) {
        const changed = substr(record, 0, i) + chr(ord(record, i) ^ (1 << bit)) + substr(record, i + 1);
        check(!native_record_matches(changed, fields), 'changed native record field');
    }
}
check(checkpoint_interval_ms == 15000, 'stock 15-second heartbeat');

let original = '';
for (let i = 0; i < 16384; i++) original += chr((i * 13) & 255);
original = substr(original, 0, 10496) + record + substr(original, 10524);
const path = '/fixtures/power-record.bin';
fs.writefile(path, original);
let file = fs.open(path, 'r+');
for (let now in [1793382400, 1793382415, 1793382430, 4294967297, 1793382420]) {
    check(checkpoint_file(file, now, fields) == null, 'checkpoint/update/RTC correction');
    const actual = fs.readfile(path);
    check(actual == substr(original, 0, 10500) + encode_time(now) + substr(original, 10508), 'only eight RTC bytes change');
    check(little(actual, 10500, 8) == now, '64-bit RTC roundtrip');
}
file.close();
const before = fs.readfile(path);
file = fs.open(path, 'r+');
check(checkpoint_file(file, null, fields) == 'rtc_invalid', 'unavailable RTC');
check(checkpoint_file(file, 0, fields) == 'rtc_invalid', 'reset RTC');
check(checkpoint_file(file, 1793382440, 'unrecognized') == 'record_mismatch', 'no writes for unknown layout');
file.close();
check(fs.readfile(path) == before, 'invalid inputs unchanged');
file = fs.open(path, 'r');
check(checkpoint_file(file, 1793382440, fields) == 'write_failed', 'read-only handle failure');
file.close();
check(fs.readfile(path) == before, 'failed writer leaves adjacent data intact');
check(checkpoint_file({ seek: () => false }, 1793382440, fields) == 'seek_failed', 'failed seek');
check(checkpoint_file({ seek: () => true, read: () => record,
    write: () => 7, flush: () => true }, 1793382440, fields) == 'write_failed', 'short write');
check(checkpoint_file({ seek: () => true, read: () => record,
    write: () => 8, flush: () => false }, 1793382440, fields) == 'write_failed', 'failed flush');
check(checkpoint_file({ seek: () => true, read: n => n == 28 ? record : 'bad',
    write: () => 8, flush: () => true }, 1793382440, fields) == 'readback_failed', 'failed readback');
print('PASS: native record discovery, clock heartbeat, 64-bit encoding, only eight modified bytes, malformed inputs and write failures\n');
